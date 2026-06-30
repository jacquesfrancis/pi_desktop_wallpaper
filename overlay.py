#!/usr/bin/env python3
"""
pi-wallpaper-overlay: superimposes hostname and IP address onto the desktop
wallpaper. Font, size, colour, and position are read from overlay.conf.
"""

from __future__ import annotations  # allows X | Y type hints on Python < 3.10

import configparser
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:
    sys.exit("Pillow is not installed. Run: sudo pip3 install pillow --break-system-packages")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).resolve().parent
CONF_FILE   = SCRIPT_DIR / "overlay.conf"
OUT_NAME    = "wallpaper_overlay.png"

_CACHE_DIR  = Path.home() / ".cache" / "pi-wallpaper-overlay"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_IMAGE   = _CACHE_DIR / OUT_NAME
SOURCE_FILE = _CACHE_DIR / "source.conf"
LOG_FILE    = _CACHE_DIR / "overlay.log"

# Path to the pcmanfm config file that contains the active wallpaper= key.
# Set by _read_pcmanfm_prefs() when it locates the file; used by set_wallpaper()
# to patch the file directly (because pcmanfm --set-wallpaper does not always
# write back to the per-monitor config on Raspberry Pi OS).
_prefs_file_to_patch: Path | None = None

VALID_LOCATIONS = {
    "top left",    "top centre",    "top right",
    "mid left",    "centre centre", "mid right",
    "bottom left", "bottom centre", "bottom right",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_log_fh = open(LOG_FILE, "a", encoding="utf-8")

def log(msg: str):
    stamped = f"{datetime.now().strftime('%Y%m%d-%H%M%S')} {msg}"
    print(stamped, file=sys.stderr)
    print(stamped, file=_log_fh, flush=True)


# ---------------------------------------------------------------------------
# overlay.conf
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg = configparser.ConfigParser()
    with open(CONF_FILE) as fh:
        cfg.read_string("[settings]\n" + fh.read())
    s = cfg["settings"]
    return {
        "font":      s.get("font",      "DejaVuSans").strip(),
        "size":      s.getint("size",   24),
        "colour":    s.get("colour",    "white").strip(),
        "location":  s.get("location",  "bottom left").strip().lower(),
        # Manual overrides — set these when auto-detection cannot find the config.
        # 'wallpaper' wins over 'bg_colour' if both are set.
        "wallpaper": s.get("wallpaper", "").strip(),
        "bg_colour": s.get("bg_colour", "").strip(),
    }


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

def get_hostname() -> str:
    return socket.gethostname()


def get_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "No IP"


def get_screen_resolution() -> tuple[int, int]:
    try:
        out = subprocess.check_output(["xrandr"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if "*" in line:
                m = re.search(r"(\d{3,4})x(\d{3,4})", line)
                if m:
                    return int(m.group(1)), int(m.group(2))
        m = re.search(r"(\d{3,4})x(\d{3,4})", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as e:
        log(f"xrandr failed: {e}")
    log("Warning: could not determine screen resolution, assuming 1920x1080.")
    return 1920, 1080


def get_panel_height() -> int:
    for p in [
        Path.home() / ".config/lxpanel/LXDE-pi/panels/panel",
        Path.home() / ".config/lxpanel/LXDE/panels/panel",
    ]:
        if p.is_file():
            m = re.search(r"^\s*height\s*=\s*(\d+)", p.read_text(errors="ignore"), re.MULTILINE)
            if m:
                return int(m.group(1))
    return 36


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_our_image(path_str: str) -> bool:
    return Path(path_str).name == OUT_NAME


def _parse_kv(path: Path) -> dict:
    """Parse a GLib key-file as flat key=value pairs, ignoring section headers."""
    result = {}
    try:
        for line in path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    except Exception as e:
        log(f"Failed to parse {path}: {e}")
    return result


# ---------------------------------------------------------------------------
# PCManFM prefs detection
# ---------------------------------------------------------------------------

def _pcmanfm_profile_from_process() -> str | None:
    """Read the --profile argument from the running pcmanfm process."""
    try:
        out = subprocess.check_output(["ps", "-eo", "args"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if "pcmanfm" in line and "--desktop" in line:
                m = re.search(r"--profile[=\s]+(\S+)", line)
                if m:
                    profile = m.group(1)
                    log(f"pcmanfm running with --profile {profile}")
                    return profile
    except Exception:
        pass
    return None


def _read_pcmanfm_prefs() -> dict | None:
    """
    Search for the PCManFM desktop-prefs.conf in order of priority:
      1. Profile name detected from running pcmanfm process
      2. Known candidate paths (LXDE-pi, LXDE, system /etc/xdg)
      3. Any .conf under ~/.config/pcmanfm/ (broad glob)
    Returns a flat key=value dict, or None if nothing found.
    """
    seen  = set()
    candidates = []

    # Highest priority: profile matched to running process
    profile = _pcmanfm_profile_from_process()
    if profile:
        for base in [Path.home() / ".config/pcmanfm", Path("/etc/xdg/pcmanfm")]:
            p = base / profile / "desktop-prefs.conf"
            if p not in seen:
                candidates.append(p)
                seen.add(p)

    # Known fallback candidates
    for p in [
        Path.home() / ".config/pcmanfm/LXDE-pi/desktop-prefs.conf",
        Path.home() / ".config/pcmanfm/LXDE/desktop-prefs.conf",
        Path("/etc/xdg/pcmanfm/LXDE-pi/desktop-prefs.conf"),
        Path("/etc/xdg/pcmanfm/LXDE/desktop-prefs.conf"),
    ]:
        if p not in seen:
            candidates.append(p)
            seen.add(p)

    # Broad glob under ~/.config/pcmanfm/ — newest-modified file first so that
    # the config pcmanfm is actively writing to (e.g. desktop-items-NOOP-1.conf)
    # takes priority over a frozen per-monitor file (e.g. desktop-items-HDMI-A-1.conf).
    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    for p in sorted(Path.home().glob(".config/pcmanfm/**/*.conf"), key=_mtime, reverse=True):
        if p not in seen:
            candidates.append(p)
            seen.add(p)

    log(f"Searching {len(candidates)} PCManFM config candidate(s):")
    for path in candidates:
        exists = path.is_file()
        log(f"  {'FOUND' if exists else 'missing'}: {path}")
        if not exists:
            continue

        prefs = _parse_kv(path)
        log(f"  Contents: {prefs}")

        if not any(k in prefs for k in ("wallpaper", "desktop_bg", "wallpaper_mode")):
            continue

        # Remember this file for later patching (see set_wallpaper).
        global _prefs_file_to_patch
        if _prefs_file_to_patch is None and "wallpaper" in prefs:
            _prefs_file_to_patch = path
            log(f"  Will patch this config file when setting wallpaper: {path}")

        wp = prefs.get("wallpaper", "").strip()

        if wp and is_our_image(wp):
            # This file points at our own overlay. The user may have changed
            # the wallpaper via Appearance Settings, which writes to a sibling
            # desktop-prefs.conf in the same profile directory.
            # Check that file first — it holds the user's INTENDED wallpaper.
            sibling = path.parent / "desktop-prefs.conf"
            if sibling != path and sibling.is_file():
                sibling_prefs = _parse_kv(sibling)
                s_wp = sibling_prefs.get("wallpaper", "").strip()
                log(f"  Sibling desktop-prefs.conf found: {sibling} -> {sibling_prefs}")
                if s_wp and Path(s_wp).is_file() and not is_our_image(s_wp):
                    log(f"  Using sibling prefs (has user wallpaper {s_wp})")
                    return sibling_prefs
            # No useful sibling — return this prefs (caller will fall back to cache)
            return prefs

        # Non-overlay wallpaper or solid colour — use as-is
        return prefs

    log("No PCManFM prefs file found.")
    return None


# ---------------------------------------------------------------------------
# Source cache
# ---------------------------------------------------------------------------

def save_source_image(path: str):
    SOURCE_FILE.write_text(f"wallpaper={path}\n")
    log(f"Source cached: wallpaper={path}")


def save_source_colour(colour: str):
    SOURCE_FILE.write_text(f"colour={colour}\n")
    log(f"Source cached: colour={colour}")


def load_source() -> dict:
    if not SOURCE_FILE.is_file():
        return {}
    result = {}
    for line in SOURCE_FILE.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    log(f"Loaded source cache: {result}")
    return result


# ---------------------------------------------------------------------------
# Canvas builder
# ---------------------------------------------------------------------------

def _open_image(path: str) -> Image.Image:
    log(f"Opening image: {path}")
    return Image.open(path).convert("RGB")


def _solid_canvas(colour: str) -> Image.Image:
    w, h = get_screen_resolution()
    log(f"Creating solid canvas: {colour} ({w}x{h})")
    return Image.new("RGB", (w, h), colour)


def build_canvas(conf_wallpaper: str, conf_bg_colour: str) -> Image.Image:
    """
    Return a PIL Image of the desktop background.

    Priority order:
      1. 'wallpaper' in overlay.conf  — explicit image override
      2. 'bg_colour' in overlay.conf  — explicit colour override
      3. PCManFM prefs (auto-detected)
         a. Points at a real user image  → use it, cache as source
         b. Points at our own image      → use source cache
         c. No wallpaper / solid colour  → use desktop_bg colour, cache
      4. Waypaper config
      5. Source cache from a previous run
      6. Plain black
    """
    # 1. Explicit wallpaper override in overlay.conf
    if conf_wallpaper and Path(conf_wallpaper).is_file():
        log(f"Using wallpaper from overlay.conf: {conf_wallpaper}")
        return _open_image(conf_wallpaper)

    # 2. Explicit colour override in overlay.conf
    if conf_bg_colour:
        log(f"Using bg_colour from overlay.conf: {conf_bg_colour}")
        return _solid_canvas(conf_bg_colour)

    # 3. PCManFM auto-detection
    prefs = _read_pcmanfm_prefs()
    if prefs is not None:
        wp = prefs.get("wallpaper", "").strip()
        bg = prefs.get("desktop_bg", "").strip()
        if bg and not bg.startswith("#"):
            bg = f"#{bg}"

        wp_mode = prefs.get("wallpaper_mode", "").strip().lower()
        log(f"PCManFM wallpaper='{wp}', desktop_bg='{bg}', wallpaper_mode='{wp_mode}'")

        # Solid-colour mode: ignore the wallpaper path entirely and use desktop_bg.
        # (When the user switches to "no image", pcmanfm sets wallpaper_mode=color
        # but may leave wallpaper= pointing at our overlay from the previous run.)
        if wp_mode == "color":
            colour = bg or "#000000"
            log(f"PCManFM solid-colour mode - using desktop_bg: {colour}")
            save_source_colour(colour)
            return _solid_canvas(colour)

        if wp:
            if is_our_image(wp):
                log("PCManFM points at our own image - reading source cache.")
                return _canvas_from_cache(fallback_colour=bg or "#000000")
            elif Path(wp).is_file():
                log(f"PCManFM has user wallpaper: {wp}")
                save_source_image(wp)
                return _open_image(wp)
            else:
                log(f"PCManFM wallpaper path does not exist: {wp}")

        # No usable wallpaper → solid-colour desktop
        colour = bg or "#000000"
        save_source_colour(colour)
        return _solid_canvas(colour)

    # 4. Waypaper (Wayland)
    waypaper_cfg = Path.home() / ".config/waypaper/config.ini"
    if waypaper_cfg.exists():
        cfg = configparser.ConfigParser()
        cfg.read(waypaper_cfg)
        wp = cfg.get("Settings", "wallpaper", fallback="").strip()
        log(f"Waypaper wallpaper='{wp}'")
        if wp and Path(wp).is_file() and not is_our_image(wp):
            save_source_image(wp)
            return _open_image(wp)

    # 5. Source cache
    return _canvas_from_cache(fallback_colour="#000000")


def _canvas_from_cache(fallback_colour: str) -> Image.Image:
    src = load_source()
    wp  = src.get("wallpaper", "").strip()
    col = src.get("colour",    "").strip()

    if wp and is_our_image(wp):
        log("Source cache points at our own image - clearing stale cache.")
        SOURCE_FILE.unlink(missing_ok=True)
        wp = ""

    if wp and Path(wp).is_file():
        return _open_image(wp)

    if col:
        return _solid_canvas(col)

    # 6. Absolute last resort — do NOT cache this
    log(f"No source found - using fallback colour {fallback_colour}")
    return _solid_canvas(fallback_colour)


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

def find_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    if Path(font_name).is_file():
        return ImageFont.truetype(font_name, size)

    font_dirs = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local/share/fonts",
    ]
    needle = font_name.lower().replace(" ", "")
    for d in font_dirs:
        if not d.exists():
            continue
        for ext in ("*.ttf", "*.otf"):
            for f in d.rglob(ext):
                if needle in f.stem.lower().replace(" ", ""):
                    log(f"Font found: {f}")
                    return ImageFont.truetype(str(f), size)

    log(f"Warning: font '{font_name}' not found, using Pillow default.")
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Set wallpaper
# ---------------------------------------------------------------------------

def _patch_pcmanfm_config(wallpaper: str, config_file: Path):
    """
    Directly rewrite the wallpaper= line inside the pcmanfm config file.

    On some Raspberry Pi OS builds, `pcmanfm --set-wallpaper` updates only the
    in-session X11 state and does NOT write back to the per-monitor config file
    (e.g. desktop-items-HDMI-A-1.conf).  Without this patch the file stays
    frozen at whatever wallpaper was there at install time, so every boot our
    script reads the wrong source image.

    Patching the file ensures that on next boot pcmanfm shows our overlay, our
    script sees it (recognises it as its own image), and falls back to the
    source cache — which holds the real user wallpaper from the previous run.
    """
    try:
        text = config_file.read_text(errors="ignore")
        if re.search(r"^wallpaper\s*=", text, re.MULTILINE):
            new_text = re.sub(
                r"^(wallpaper\s*=).*$",
                f"wallpaper={wallpaper}",
                text,
                flags=re.MULTILINE,
            )
        else:
            # File has no wallpaper= key yet — insert one after the first section header.
            new_text = re.sub(r"(\[.*?\]\n)", rf"\1wallpaper={wallpaper}\n", text, count=1)

        if new_text != text:
            config_file.write_text(new_text)
            log(f"Patched config file: {config_file}")
        else:
            log(f"Config file already up to date (no patch needed): {config_file}")
    except Exception as e:
        log(f"Warning: could not patch config file {config_file}: {e}")


def set_wallpaper(image_path: Path):
    path_str = str(image_path)
    log(f"Setting wallpaper: {path_str}")

    if shutil.which("pcmanfm"):
        for attempt in range(1, 16):
            result = subprocess.run(
                ["pcmanfm", "--set-wallpaper", path_str, "--wallpaper-mode=stretch"],
                capture_output=True, text=True
            )
            log(f"pcmanfm attempt {attempt}: rc={result.returncode} stderr='{result.stderr.strip()}'")
            if result.returncode == 0 and "not active" not in result.stderr.lower():
                # Patch the config file directly so the change persists across
                # boots (pcmanfm --set-wallpaper may not write back to the file).
                if _prefs_file_to_patch:
                    _patch_pcmanfm_config(path_str, _prefs_file_to_patch)
                return
            time.sleep(2)
        log("Warning: gave up waiting for pcmanfm desktop manager.")
        return

    for tool, args in [
        ("feh",      ["feh", "--bg-scale", path_str]),
        ("waypaper", ["waypaper", "--wallpaper", path_str]),
        ("swww",     ["swww", "img", path_str]),
        ("swaybg",   ["swaybg", "-i", path_str, "-m", "fill"]),
    ]:
        if shutil.which(tool):
            subprocess.run(args, check=False)
            return

    log("Warning: no wallpaper tool found.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("=" * 60)
    log("overlay.py starting")

    cfg   = load_config()
    log(f"Config: {cfg}")

    label = f"{get_hostname()}  |  {get_ip()}"
    log(f"Label: {label}")

    img = build_canvas(
        conf_wallpaper=cfg["wallpaper"],
        conf_bg_colour=cfg["bg_colour"],
    )
    log(f"Canvas size before resize: {img.size}")

    sw, sh = get_screen_resolution()
    if img.size != (sw, sh):
        img = ImageOps.fit(img, (sw, sh), Image.LANCZOS)
        log(f"Canvas resized to screen: {img.size}")

    draw = ImageDraw.Draw(img)
    font = find_font(cfg["font"], cfg["size"])

    bbox   = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    log(f"Text size: {tw}x{th}")

    location = cfg["location"]
    if location not in VALID_LOCATIONS:
        log(f"Warning: unknown location '{location}', defaulting to 'bottom left'.")
        location = "bottom left"

    v, h = location.split()
    edge_padding  = 20
    panel_h       = get_panel_height() if v == "bottom" else 0
    bottom_margin = edge_padding + panel_h

    x = (edge_padding                  if h == "left"
         else (img.width - tw) // 2    if h in ("centre", "center")
         else img.width - tw - edge_padding)

    y = (edge_padding                  if v == "top"
         else (img.height - th) // 2   if v in ("mid", "centre", "center")
         else img.height - th - bottom_margin)

    log(f"Text position: ({x}, {y}), location='{location}', panel_h={panel_h}")

    shadow = "black" if cfg["colour"].lower() not in ("black", "#000000") else "white"
    draw.text((x + 2, y + 2), label, font=font, fill=shadow)
    draw.text((x,     y    ), label, font=font, fill=cfg["colour"])

    img.save(OUT_IMAGE)
    log(f"Saved: {OUT_IMAGE}")

    set_wallpaper(OUT_IMAGE)
    log(f"Done: {label}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("FATAL ERROR:")
        log(traceback.format_exc())
        sys.exit(1)
    finally:
        _log_fh.close()

<<<<<<< HEAD
# Pi Wallpaper Overlay

Superimposes a Raspberry Pi's hostname and IP address onto its desktop
wallpaper. Handy for identifying individual Pis at a glance.

## What it does

Reads the current desktop wallpaper (or solid background colour),
superimposes the hostname and IP address as text, and sets the result as the
new wallpaper. Runs automatically at desktop login.

## Installation

```bash
git clone https://github.com/jacquesfrancis/pi_desktop_wallpaper.git
cd pi_desktop_wallpaper
bash install.sh
```

This installs the script to `/usr/local/bin/pi-wallpaper-overlay/` and adds
an autostart entry so it runs at every login.

To run it immediately without logging out:

```bash
python3 /usr/local/bin/pi-wallpaper-overlay/overlay.py
```

## Configuration

Edit `/usr/local/bin/pi-wallpaper-overlay/overlay.conf`:

```ini
font=DejaVuSans       # font name or full path to .ttf/.otf
size=28               # point size
colour=white          # text colour - CSS name or hex (#FFFF00)
location=bottom left  # text position (top/mid/bottom + left/centre/right)
wallpaper=            # explicit image path override (leave blank for auto-detect)
bg_colour=            # explicit solid colour override (leave blank for auto-detect)
```

`wallpaper=` and `bg_colour=` only need to be set if wallpaper
auto-detection fails on your setup.

## How wallpaper detection works

1. `wallpaper=` in `overlay.conf` (explicit override)
2. `bg_colour=` in `overlay.conf` (explicit override)
3. PCManFM config auto-detection
4. Waypaper config (`~/.config/waypaper/config.ini`)
5. Cached source from the previous run
6. Plain black fallback

## Logs

Runtime files live in `~/.cache/pi-wallpaper-overlay/`:

- `wallpaper_overlay.png` — the generated overlay image
- `source.conf` — cached source wallpaper/colour for the next run
- `overlay.log` — timestamped log of every run

## Tested on

| Pi | OS | Desktop profile |
|----|----|-----------------|
| Raspberry Pi 5 | Bookworm | `default` |
| Raspberry Pi (older model) | Bullseye | `LXDE-pi` |

## Known issues

- On some setups `xrandr` cannot determine the screen resolution and the
  script falls back to assuming 1920x1080.
- If the desktop is set to a solid colour and then switched back to an image
  via a route the script doesn't track, the cached source may briefly show
  the wrong background until the next successful detection.

## Licence

MIT - see the licence file in the root folder.

#!/usr/bin/env bash
# install.sh -- deploy pi-wallpaper-overlay on a Raspberry Pi
# Run once per Pi:  bash install.sh
set -euo pipefail

INSTALL_DIR="/usr/local/bin/pi-wallpaper-overlay"
AUTOSTART_DIR="$HOME/.config/autostart"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing Pillow (Python imaging library)..."
# --break-system-packages is required on Bookworm (pip >= 22.1) but unknown on
# older OS releases (Bullseye / Buster).  Try new flag first, fall back if not.
if pip3 install --help 2>&1 | grep -q 'break-system-packages'; then
    sudo pip3 install pillow --break-system-packages --quiet
else
    sudo pip3 install pillow --quiet
fi

echo "==> Copying scripts to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp "$SCRIPT_DIR/overlay.py"   "$INSTALL_DIR/overlay.py"
sudo cp "$SCRIPT_DIR/overlay.conf" "$INSTALL_DIR/overlay.conf"
sudo chmod 755 "$INSTALL_DIR"
sudo chmod 644 "$INSTALL_DIR/overlay.conf"
sudo chmod 755 "$INSTALL_DIR/overlay.py"

echo "==> Installing autostart entry..."
mkdir -p "$AUTOSTART_DIR"
cp "$SCRIPT_DIR/pi-wallpaper-overlay.desktop" "$AUTOSTART_DIR/pi-wallpaper-overlay.desktop"

echo ""
echo "Done. The overlay will run automatically at next login."
echo ""
echo "To run it right now:"
echo "  python3 $INSTALL_DIR/overlay.py"
echo ""
echo "To customise font / size / colour, edit:"
echo "  $INSTALL_DIR/overlay.conf"

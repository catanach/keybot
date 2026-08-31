#!/bin/bash
# Deploys this project onto a Raspberry Pi Pico WH running CircuitPython.
#
# Handles two situations automatically:
#   1. The Pico is freshly reset and sitting in bootloader mode (shows up as
#      RPI-RP2). This script will flash the CircuitPython firmware onto it.
#      Run the script again afterward to copy the actual project files.
#   2. The Pico is already running CircuitPython (shows up as CIRCUITPY).
#      This script copies boot.py, code.py, settings.toml, and the lib
#      folders onto it.
#
# Usage: ./deploy.sh

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$PROJECT_DIR/src"
LIB_DIR="$PROJECT_DIR/lib"

BOOTLOADER_VOLUME="/Volumes/RPI-RP2"
CIRCUITPY_VOLUME="/Volumes/CIRCUITPY"

if [ -d "$BOOTLOADER_VOLUME" ]; then
    echo "Pico is in bootloader mode (RPI-RP2 found)."
    UF2_FILE=$(find "$LIB_DIR" -maxdepth 1 -name "*.uf2" | head -n 1)
    if [ -z "$UF2_FILE" ]; then
        echo "No .uf2 firmware file found in lib/."
        echo "Download the CircuitPython firmware from https://circuitpython.org/board/raspberry_pi_pico_w/"
        echo "and place the .uf2 file in the lib/ folder, then run this script again."
        exit 1
    fi
    echo "Flashing firmware: $(basename "$UF2_FILE")"
    cp "$UF2_FILE" "$BOOTLOADER_VOLUME/"
    echo "Firmware copied. The board will restart as CIRCUITPY in a few seconds."
    echo "Once it shows up as CIRCUITPY in Finder, run ./deploy.sh again to copy the project files."
    exit 0
fi

if [ ! -d "$CIRCUITPY_VOLUME" ]; then
    echo "Can't find the Pico."
    echo "Make sure the board is plugged in."
    echo "It should show up as either RPI-RP2 or CIRCUITPY in Finder."
    exit 1
fi

echo "CIRCUITPY found. Copying project files..."

if [ -f "$SRC_DIR/boot.py" ]; then
    cp "$SRC_DIR/boot.py" "$CIRCUITPY_VOLUME/boot.py"
    echo "Copied boot.py."
elif [ -f "$CIRCUITPY_VOLUME/boot.py" ]; then
    rm -f "$CIRCUITPY_VOLUME/boot.py"
    echo "Removed boot.py (none in src/)."
fi
cp "$SRC_DIR/code.py" "$CIRCUITPY_VOLUME/code.py"
echo "Copied code.py."

if [ -f "$SRC_DIR/settings.toml" ]; then
    cp "$SRC_DIR/settings.toml" "$CIRCUITPY_VOLUME/settings.toml"
    echo "Copied settings.toml."
else
    echo "No settings.toml found in src/."
    echo "Copy src/settings.toml.example to src/settings.toml, fill in your Wi-Fi details, and run this script again."
fi

mkdir -p "$CIRCUITPY_VOLUME/lib"
found_lib=false
for libfolder in "$LIB_DIR"/*/ ; do
    [ -d "$libfolder" ] || continue
    found_lib=true
    name=$(basename "$libfolder")
    echo "Copying library: $name"
    rm -rf "${CIRCUITPY_VOLUME:?}/lib/${name:?}"
    cp -R "$libfolder" "$CIRCUITPY_VOLUME/lib/$name"
done

if [ "$found_lib" = false ]; then
    echo "No library folders found in lib/."
    echo "Download the CircuitPython 10.x library bundle from https://circuitpython.org/libraries,"
    echo "unzip it, and place the adafruit_hid and adafruit_httpserver folders inside lib/."
fi

echo "Done. Safe to eject and unplug the Pico."

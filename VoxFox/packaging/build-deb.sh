#!/usr/bin/env bash
set -e

VERSION="${VERSION:-$(grep APP_VERSION "$SRC/voxfox_gtk.py" | grep -oP '".*"' | tr -d '"')}"
SRC="${SRC:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCALES="${LOCALES:-$SRC/locales}"

WORK=$(mktemp -d); trap "rm -rf $WORK" EXIT
INST="$WORK/install"

mkdir -p "$INST/usr/lib/voxfox/voxfox_core" \
         "$INST/usr/share/voxfox/locales" \
         "$INST/usr/share/applications" \
         "$INST/usr/share/icons/hicolor/256x256/apps" \
         "$INST/usr/bin" \
         "$INST/DEBIAN"

# App code
cp "$SRC/voxfox_gtk.py"        "$INST/usr/lib/voxfox/"
cp "$SRC/voxfox_core/"*.py     "$INST/usr/lib/voxfox/voxfox_core/"
cp "$LOCALES/"*.json           "$INST/usr/share/voxfox/locales/"

# Logo / icon. Ships to two places:
#  - the hicolor icon theme dir, so the desktop launcher shows the icon
#  - /usr/share/voxfox, so the in-app About dialog has a logo even before
#    the Piper voices (and the per-user ~/.piper/voxfox-logo.png) exist.
if [ -f "$SRC/voxfox-logo.png" ]; then
    cp "$SRC/voxfox-logo.png" "$INST/usr/share/icons/hicolor/256x256/apps/voxfox.png"
    cp "$SRC/voxfox-logo.png" "$INST/usr/share/voxfox/voxfox-logo.png"
else
    echo "WARNING: voxfox-logo.png not found in $SRC — package will have no icon!" >&2
fi

# Launcher
cat > "$INST/usr/bin/voxfox" <<'LAUNCHER'
#!/bin/sh
exec python3 /usr/lib/voxfox/voxfox_gtk.py "$@"
LAUNCHER
chmod 755 "$INST/usr/bin/voxfox"

# Desktop entry
cat > "$INST/usr/share/applications/voxfox.desktop" <<'DESKTOP'
[Desktop Entry]
Name=VoxFox
Comment=Screen reader and dictation tool
Exec=voxfox
Icon=voxfox
Terminal=false
Type=Application
Categories=Accessibility;
DESKTOP

# Control file — full dependency list
# - GTK4 + AT-SPI: core GUI and accessibility tree
# - xdotool + wmctrl: window management, type-text, always-on-top, position
# - xclip: primary-clipboard reading (hover-to-read, selection-follow)
# - tesseract-ocr + poppler-utils: OCR and PDF reading
# - pulseaudio-utils: pactl for audio device detection
# - ffmpeg: audio conversion for Whisper
# - python3-sounddevice + python3-soundfile + python3-numpy: dictation recording
#   (best-effort: not available on all distros; postinst installs via pip if missing)
# - libportaudio2 + libsndfile1: C libraries needed by sounddevice/soundfile
# - scrot: reliable, lightweight region-select for the OCR "Select" feature.
#   Works across desktop environments (unlike gnome-screenshot/spectacle,
#   which depend on their native shell's DBus interface and can fail
#   silently outside it, e.g. gnome-screenshot on Cinnamon).
cat > "$INST/DEBIAN/control" <<CTRL
Package: voxfox
Version: $VERSION
Architecture: all
Maintainer: Daniël Vos
Depends: python3 (>= 3.9),
 python3-gi,
 gir1.2-gtk-4.0,
 gir1.2-glib-2.0,
 python3-pyatspi,
 at-spi2-core,
 xdotool,
 wmctrl,
 xclip,
 tesseract-ocr,
 poppler-utils,
 pulseaudio-utils,
 ffmpeg,
 libportaudio2,
 libsndfile1,
 scrot
Recommends: tesseract-ocr-eng, tesseract-ocr-nld, python3-numpy
Description: VoxFox — screen reader and dictation tool
 Hover-to-read, text selection reading, OCR, PDF reading,
 and local/remote speech-to-text dictation.
 .
 After installation, run: voxfox --setup
 to download the Piper voice engine and default voices.
CTRL

# Post-install script: install Python packages that may not be in the distro repos.
# faster-whisper (dictation engine), sounddevice and soundfile are not packaged on
# all distros (e.g. missing on Zorin OS, Linux Mint). We install them via pip into
# the calling user's home — or system-wide with --break-system-packages as fallback.
cat > "$INST/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

# Refresh the icon cache and desktop database so the launcher icon and
# menu entry appear immediately — needed on Cinnamon/GNOME (Linux Mint),
# where a stale cache otherwise hides the VoxFox icon until next login.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi

PKGS="faster-whisper sounddevice soundfile"

# Find the real user (not root) to install pip packages for
REAL_USER="${SUDO_USER:-$USER}"
if [ "$REAL_USER" = "root" ] || [ -z "$REAL_USER" ]; then
    REAL_USER=$(logname 2>/dev/null || echo "")
fi

pip_install() {
    if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
        su -c "pip install --user --break-system-packages $PKGS 2>/dev/null || \
               pip install --user $PKGS 2>/dev/null || true" "$REAL_USER" || true
    else
        pip install --break-system-packages $PKGS 2>/dev/null || \
        pip install $PKGS 2>/dev/null || true
    fi
}

# Check if packages are already importable for the real user (not root).
# postinst runs as root, so a bare "python3 -c import..." would test root's
# environment, not the user who will actually run VoxFox.
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
    if su -c "python3 -c 'import faster_whisper, sounddevice, soundfile'" \
          "$REAL_USER" 2>/dev/null; then
        exit 0
    fi
else
    if python3 -c "import faster_whisper, sounddevice, soundfile" 2>/dev/null; then
        exit 0
    fi
fi

echo "VoxFox: installing Python dictation dependencies (faster-whisper, sounddevice, soundfile)..."
pip_install
echo "VoxFox: done. Run 'voxfox --setup' to download voices."

exit 0
POSTINST
chmod 755 "$INST/DEBIAN/postinst"

fakeroot dpkg-deb --build "$INST" "$SRC/voxfox_${VERSION}_all.deb"
echo "Built: $SRC/voxfox_${VERSION}_all.deb"

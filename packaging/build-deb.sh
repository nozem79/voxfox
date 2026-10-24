#!/usr/bin/env bash
set -e
# Files in the package must be readable for everyone, whatever the
# builder's own umask is.
umask 022

# Repo root, relative to this script (packaging/ lives one level below root).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${SRC:-$ROOT/src}"
VERSION="${VERSION:-$(grep APP_VERSION "$SRC/voxfox_ui/common.py" | grep -oP '".*"' | tr -d '"')}"
LOCALES="${LOCALES:-$ROOT/locales}"

WORK=$(mktemp -d); trap "rm -rf $WORK" EXIT
INST="$WORK/install"

mkdir -p "$INST/usr/lib/voxfox/voxfox_core" \
         "$INST/usr/lib/voxfox/voxfox_ui" \
         "$INST/usr/share/voxfox/locales" \
         "$INST/usr/share/applications" \
         "$INST/usr/share/icons/hicolor/256x256/apps" \
         "$INST/usr/share/pixmaps" \
         "$INST/usr/bin" \
         "$INST/DEBIAN"

# App code
cp "$SRC/voxfox_gtk.py"        "$INST/usr/lib/voxfox/"
cp "$SRC/quickshot.py"         "$INST/usr/lib/voxfox/"

# Root-side installer behind Settings' "Install Ollama" button, plus the
# polkit policy that names its authentication prompt and ties it to exactly
# this file (see src/install-ollama.sh for why it is not Ollama's own script).
cp "$SRC/install-ollama.sh" "$INST/usr/lib/voxfox/"
chmod 755 "$INST/usr/lib/voxfox/install-ollama.sh"
mkdir -p "$INST/usr/share/polkit-1/actions"
cp "$SRC/nl.voxfox.install-ollama.policy" "$INST/usr/share/polkit-1/actions/"
chmod 644 "$INST/usr/share/polkit-1/actions/nl.voxfox.install-ollama.policy"
cp "$SRC/voxfox_core/"*.py     "$INST/usr/lib/voxfox/voxfox_core/"
cp "$SRC/voxfox_ui/"*.py       "$INST/usr/lib/voxfox/voxfox_ui/"
# Sub-packages (voxfox_ui/preferences/, ...): every folder with an __init__.py.
for pkg in voxfox_core voxfox_ui; do
    for d in "$SRC/$pkg"/*/; do
        [ -f "$d/__init__.py" ] || continue
        sub="$INST/usr/lib/voxfox/$pkg/$(basename "$d")"
        mkdir -p "$sub"
        cp "$d"*.py "$sub/"
    done
done
cp "$LOCALES/"*.json           "$INST/usr/share/voxfox/locales/"

# Button icons and the pictograms of the ready-made tiles. Not optional:
# without icons/tiles/ every tile would be empty, so a failed copy stops
# the build instead of producing a package that looks fine.
mkdir -p "$INST/usr/share/voxfox/icons"
cp -r "$ROOT/icons/." "$INST/usr/share/voxfox/icons/"
for f in tiles/ja.svg tiles/ik-heb-dorst.svg hicolor/scalable/actions/voxfox-type-symbolic.svg; do
    [ -f "$INST/usr/share/voxfox/icons/$f" ] || { echo "ERROR: icons/$f missing from the package" >&2; exit 1; }
done
# Bundled community pronunciation dictionaries (optional).
if [ -d "$ROOT/dicts" ]; then
    mkdir -p "$INST/usr/share/voxfox/dicts"
    cp "$ROOT/dicts/"*.json "$INST/usr/share/voxfox/dicts/" 2>/dev/null || true
fi

# Application icon. The source PNG lives in the repo root (NOT in src/), so
# look there first, then fall back to $SRC for unusual layouts. Install it as
# the themed icon "voxfox" so the .desktop's Icon=voxfox resolves in the menu
# and taskbar. We generate the standard hicolor sizes when Pillow is available
# (crisper at panel sizes than scaling one 300px image), and always drop a
# /usr/share/pixmaps/voxfox.png copy as a theme-independent fallback.
LOGO=""
for cand in "$ROOT/voxfox-logo.png" "$SRC/voxfox-logo.png" "$SRC/../voxfox-logo.png"; do
    [ -f "$cand" ] && { LOGO="$cand"; break; }
done
if [ -n "$LOGO" ]; then
    cp "$LOGO" "$INST/usr/share/pixmaps/voxfox.png"
    if python3 - "$LOGO" "$INST" <<'PY' 2>/dev/null
import sys
from PIL import Image
logo, inst = sys.argv[1], sys.argv[2]
img = Image.open(logo).convert("RGBA")
for size in (48, 64, 128, 256, 512):
    d = f"{inst}/usr/share/icons/hicolor/{size}x{size}/apps"
    import os; os.makedirs(d, exist_ok=True)
    img.resize((size, size), Image.LANCZOS).save(f"{d}/voxfox.png")
PY
    then
        echo "Icon: generated hicolor sizes 48-512 from $(basename "$LOGO")"
    else
        # No Pillow at build time: ship the original under 256x256 as-is.
        cp "$LOGO" "$INST/usr/share/icons/hicolor/256x256/apps/voxfox.png"
        echo "Icon: Pillow unavailable, installed $(basename "$LOGO") as-is (256x256)"
    fi
else
    echo "WARNING: voxfox-logo.png not found (looked in repo root and \$SRC); package will have no icon" >&2
fi

# Launcher
cat > "$INST/usr/bin/voxfox" <<'LAUNCHER'
#!/bin/sh
exec python3 /usr/lib/voxfox/voxfox_gtk.py "$@"
LAUNCHER
chmod 755 "$INST/usr/bin/voxfox"

cat > "$INST/usr/bin/voxfox-quickshot" <<'LAUNCHER'
#!/bin/sh
exec python3 /usr/lib/voxfox/quickshot.py "$@"
LAUNCHER
chmod 755 "$INST/usr/bin/voxfox-quickshot"

# Desktop entry
cat > "$INST/usr/share/applications/voxfox.desktop" <<'DESKTOP'
[Desktop Entry]
Name=VoxFox
Comment=Screen reader and dictation tool
Comment[nl]=Schermlezer en dicteerhulpmiddel
Exec=voxfox
Icon=voxfox
Terminal=false
Type=Application
Categories=Utility;GTK;
Keywords=screen reader;tts;ocr;dictation;speech;accessibility;voorlezen;dicteren;
StartupNotify=true
StartupWMClass=org.voxfox.VoxFox
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
cat > "$INST/DEBIAN/control" <<CTRL
Package: voxfox
Version: $VERSION
Architecture: all
Maintainer: Daniël Vos <info@voxfox.nl>
Depends: python3 (>= 3.10),
 python3-gi,
 python3-pip,
 gir1.2-gtk-4.0 (>= 4.10),
 gir1.2-glib-2.0,
 at-spi2-core,
 xdotool,
 wmctrl,
 maim,
 xclip,
 tesseract-ocr,
 poppler-utils,
 pulseaudio-utils,
 ffmpeg,
 libportaudio2,
 libsndfile1
Recommends: python3-pyatspi, python3-xlib, tesseract-ocr-eng, tesseract-ocr-nld, python3-numpy, wl-clipboard, wtype, gnome-screenshot, spectacle, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0, python3-gi-cairo, grim, curl, zstd, pkexec | policykit-1, python3-speechd
Description: VoxFox — screen reader and dictation tool
 VoxFox reads text aloud from any application on your screen, lets you
 dictate by voice instead of typing, and can read text out of PDFs,
 images, or scanned documents using text recognition (OCR). Everything
 runs on your own computer.
 .
 After installing, open VoxFox and choose "Set up VoxFox" (or run:
 voxfox --setup) to download the voices and dictation model.
CTRL

# Post-install script: install Python packages that may not be in the distro repos.
# faster-whisper (dictation engine), sounddevice and soundfile are not packaged on
# all distros (e.g. missing on Zorin OS, Linux Mint). We install them via pip into
# the calling user's home — or system-wide with --break-system-packages as fallback.
cat > "$INST/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

# "av<19" is added separately, quoted at each call: a bare `<` would be read
# as a redirection by the shell su -c starts. faster-whisper only asks for
# av>=11, and PyAV 19 removed an argument it still passes.
PKGS="faster-whisper sounddevice soundfile"

# Refresh the icon cache and desktop database so the menu/taskbar pick up the
# voxfox icon and .desktop entry immediately (otherwise the icon may not
# resolve until the next login, showing a generic fallback). All best-effort.
# First, before the dictation part: that part can end the script early.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

# Find the real user (not root) to install pip packages for
REAL_USER="${SUDO_USER:-$USER}"
if [ "$REAL_USER" = "root" ] || [ -z "$REAL_USER" ]; then
    REAL_USER=$(logname 2>/dev/null || echo "")
fi

as_user() {
    if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
        su -c "$1" "$REAL_USER"
    else
        sh -c "$1"
    fi
}

have_pip() {
    as_user "python3 -m pip --version" >/dev/null 2>&1
}

pip_install() {
    # python3 -m pip, not a bare `pip` command -- only needs the pip module
    # to be importable, not a `pip`-named executable on PATH.
    if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
        # Interactive install: into that user's own site-packages.
        as_user "python3 -m pip install --user --break-system-packages $PKGS 'av<19'" 2>&1 || \
        as_user "python3 -m pip install --user $PKGS 'av<19'" 2>&1
    else
        # No real user: we are inside an image build (a live CD, FoxOS) or a
        # root shell. A --user install here would land in /root, where the
        # person who later logs in never sees it. Install system-wide so
        # every account on the finished image gets dictation.
        echo "VoxFox: no interactive user found; installing system-wide."
        python3 -m pip install --break-system-packages $PKGS "av<19" 2>&1 || \
        python3 -m pip install $PKGS "av<19" 2>&1
    fi
}

# Check if packages are already importable
if python3 -c "import faster_whisper, sounddevice, soundfile" 2>/dev/null; then
    exit 0
fi

if ! have_pip; then
    echo "VoxFox: python3-pip is not installed, so the dictation dependencies"
    echo "        (faster-whisper, sounddevice, soundfile) could not be"
    echo "        installed automatically. A fresh, minimal install often"
    echo "        doesn't include it by default. Run:"
    echo "          sudo apt install python3-pip"
    echo "        then open VoxFox and choose Set up VoxFox to finish."
    exit 0
fi

echo "VoxFox: installing Python dictation dependencies (faster-whisper, sounddevice, soundfile)..."
if ! pip_install; then
    echo "VoxFox: dictation dependency install failed. Open VoxFox and choose"
    echo "        Set up VoxFox to retry with more detail."
fi
echo "VoxFox: done. Run 'voxfox --setup' to download voices."

exit 0
POSTINST
chmod 755 "$INST/DEBIAN/postinst"

# Post-removal: refresh the caches again so the icon/entry disappear cleanly.
cat > "$INST/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    fi
fi
exit 0
POSTRM
chmod 755 "$INST/DEBIAN/postrm"

fakeroot dpkg-deb --build "$INST" "$SRC/voxfox_${VERSION}_all.deb"
echo "Built: $SRC/voxfox_${VERSION}_all.deb"

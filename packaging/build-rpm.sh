#!/usr/bin/env bash
set -e
# Files in the package must be readable for everyone, whatever the
# builder's own umask is.
umask 022

# Build an RPM package of VoxFox — the mirror of build-deb.sh, for
# Fedora/openSUSE-family distributions. EXPERIMENTAL: the file layout is
# identical to the deb; only dependency names differ (Fedora naming).
#
# Usage:  VERSION=3.5 bash packaging/build-rpm.sh
# Output: src/voxfox-<version>-1.noarch.rpm
#
# Needs: rpmbuild (Fedora: rpm-build; Debian/Ubuntu: rpm). Pillow optional
# for crisp icon sizes, same as the deb build.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${SRC:-$ROOT/src}"
VERSION="${VERSION:-$(grep APP_VERSION "$SRC/voxfox_ui/common.py" | grep -oP '".*"' | tr -d '"')}"
LOCALES="${LOCALES:-$ROOT/locales}"

# RPM versions may not contain hyphens; dev builds like 3.5-dev2 become 3.5~dev2
# (tilde sorts BEFORE the final release, exactly what we want for dev builds).
RPMVER="$(echo "$VERSION" | tr '-' '~')"

command -v rpmbuild >/dev/null 2>&1 || {
    echo "rpmbuild not found. Install it first (Fedora: sudo dnf install rpm-build," >&2
    echo "Debian/Ubuntu: sudo apt install rpm)." >&2
    exit 1
}

WORK=$(mktemp -d); trap "rm -rf $WORK" EXIT
INST="$WORK/install"

mkdir -p "$INST/usr/lib/voxfox/voxfox_core" \
         "$INST/usr/lib/voxfox/voxfox_ui" \
         "$INST/usr/share/voxfox/locales" \
         "$INST/usr/share/applications" \
         "$INST/usr/share/icons/hicolor/256x256/apps" \
         "$INST/usr/share/pixmaps" \
         "$INST/usr/bin"

# App code — identical layout to the deb.
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

# Application icon — same logic as the deb build.
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
        cp "$LOGO" "$INST/usr/share/icons/hicolor/256x256/apps/voxfox.png"
        echo "Icon: Pillow unavailable, installed $(basename "$LOGO") as-is (256x256)"
    fi
else
    echo "WARNING: voxfox-logo.png not found; package will have no icon" >&2
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

# Desktop entry — identical to the deb.
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

# ── RPM spec ─────────────────────────────────────────────────────────────────
# Dependency mapping (Debian name → Fedora name):
#   python3-gi          → python3-gobject
#   gir1.2-gtk-4.0      → gtk4 (ships the GIR typelib on Fedora)
#   python3-pyatspi     → python3-pyatspi
#   tesseract-ocr       → tesseract
#   pulseaudio-utils    → pulseaudio-utils (pactl; provided by pipewire setups too)
#   ffmpeg              → (ffmpeg-free or ffmpeg): stock Fedora ships ffmpeg-free,
#                         RPM Fusion ships ffmpeg — the rich dep accepts either
#   libportaudio2       → portaudio
#   libsndfile1         → libsndfile
# Recommends are weak deps; dnf and zypper install them by default but they
# never block installation.
mkdir -p "$WORK/rpm/SPECS" "$WORK/rpm/BUILD" "$WORK/rpm/RPMS"
cat > "$WORK/rpm/SPECS/voxfox.spec" <<SPEC
Name:           voxfox
Version:        $RPMVER
Release:        1
Summary:        VoxFox — screen reader and dictation tool
License:        GPL-3.0-or-later
URL:            https://github.com/nozem79/voxfox
Packager:       Daniël Vos <info@voxfox.nl>
Vendor:         VoxFox
BuildArch:      noarch

Requires:       python3 >= 3.10
Requires:       python3-gobject
Requires:       python3-pip
Requires:       gtk4 >= 4.10
Requires:       at-spi2-core
Requires:       xdotool
Requires:       wmctrl
Requires:       maim
Requires:       xclip
Requires:       tesseract
Requires:       poppler-utils
Requires:       pulseaudio-utils
Requires:       (ffmpeg-free or ffmpeg)
Requires:       portaudio
Requires:       libsndfile
Recommends:     python3-pyatspi
Recommends:     python3-xlib
Recommends:     tesseract-langpack-nld
Recommends:     python3-numpy
Recommends:     gnome-screenshot
Recommends:     spectacle
Recommends:     wl-clipboard
Recommends:     wtype
Recommends:     gtk3
Recommends:     gdk-pixbuf2
Recommends:     python3-cairo
Recommends:     grim
Recommends:     polkit
Recommends:     curl
Recommends:     zstd
Recommends:     python3-speechd

%description
VoxFox reads text aloud from any application on your screen, lets you
dictate by voice instead of typing, and can read text out of PDFs,
images, or scanned documents using text recognition (OCR). Everything
runs on your own computer.

After installing, open VoxFox and choose "Set up VoxFox" (or run:
voxfox --setup) to download the voices and dictation model.

EXPERIMENTAL package for RPM-based distributions (Fedora, openSUSE).
The .deb for Debian/Ubuntu/Mint remains the primary package.

%install
cp -a $INST/. %{buildroot}/

%post
# av<19 is added separately and quoted (a bare < is a redirection); see the
# note in build-deb.sh.
PKGS="faster-whisper sounddevice soundfile"
REAL_USER="\${SUDO_USER:-\$USER}"
if [ "\$REAL_USER" = "root" ] || [ -z "\$REAL_USER" ]; then
    REAL_USER=\$(logname 2>/dev/null || echo "")
fi
if ! python3 -c "import faster_whisper, sounddevice, soundfile" 2>/dev/null; then
    echo "VoxFox: installing Python dictation dependencies (faster-whisper, sounddevice, soundfile)..."
    if [ -n "\$REAL_USER" ] && [ "\$REAL_USER" != "root" ]; then
        su -c "python3 -m pip install --user --break-system-packages \$PKGS 'av<19' || \\
               python3 -m pip install --user \$PKGS 'av<19'" "\$REAL_USER"
    else
        python3 -m pip install --break-system-packages \$PKGS "av<19" || \\
        python3 -m pip install \$PKGS "av<19"
    fi
    if [ \$? -eq 0 ]; then
        echo "VoxFox: done. Run 'voxfox --setup' to download voices."
    else
        echo "VoxFox: dictation dependency install failed. Open VoxFox and choose"
        echo "        Setup assistant to retry with more detail."
    fi
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0

%postun
if [ "\$1" = "0" ]; then
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    fi
fi
exit 0

%files
/usr/bin/voxfox
/usr/bin/voxfox-quickshot
/usr/lib/voxfox/
/usr/share/voxfox/
/usr/share/applications/voxfox.desktop
/usr/share/polkit-1/actions/nl.voxfox.install-ollama.policy
/usr/share/icons/hicolor/*/apps/voxfox.png
/usr/share/pixmaps/voxfox.png
SPEC

rpmbuild -bb \
    --define "_topdir $WORK/rpm" \
    --define "INST $INST" \
    --define "_binary_payload w6.xzdio" \
    "$WORK/rpm/SPECS/voxfox.spec" >/dev/null

OUT=$(find "$WORK/rpm/RPMS" -name "voxfox-*.noarch.rpm" | head -1)
cp "$OUT" "$SRC/voxfox-${RPMVER}-1.noarch.rpm"
echo "Built: $SRC/voxfox-${RPMVER}-1.noarch.rpm"

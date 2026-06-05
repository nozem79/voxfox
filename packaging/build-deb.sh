#!/usr/bin/env bash
# Build a VoxFox .deb. Run from anywhere; paths are resolved relative to this
# script. Produces ./voxfox_<version>_all.deb next to it.
#
#   ./build-deb.sh
#
# Requires: dpkg-deb (package "dpkg"), and Python3 with Pillow for the icon.
set -euo pipefail

VERSION="${VERSION:-1.0.0}"
PKG="voxfox"
ARCH="all"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"            # repo root: holds locales, logo, docs
# Python sources live in src/ (fall back to the repo root for a flat layout).
PYSRC="$SRC/src"
[ -f "$PYSRC/voxfox_gtk.py" ] || PYSRC="$SRC"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

ROOT="$STAGE/$PKG"
mkdir -p "$ROOT/DEBIAN" \
         "$ROOT/usr/lib/voxfox" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/voxfox/locales" \
         "$ROOT/usr/share/icons/hicolor/256x256/apps" \
         "$ROOT/usr/share/doc/voxfox"

# ── program files ────────────────────────────────────────────────────────────
# voxfox_core is now a package (a directory of modules), not a single file.
mkdir -p "$ROOT/usr/lib/voxfox/voxfox_core"
install -m 0644 "$PYSRC/voxfox_core"/*.py "$ROOT/usr/lib/voxfox/voxfox_core/"
install -m 0644 "$PYSRC/voxfox_gtk.py"  "$ROOT/usr/lib/voxfox/voxfox_gtk.py"

# ── launcher ─────────────────────────────────────────────────────────────────
cat > "$ROOT/usr/bin/voxfox" <<'EOF'
#!/bin/sh
# Running the script by its full path puts /usr/lib/voxfox on sys.path[0],
# so "import voxfox_core" resolves without touching PYTHONPATH.
exec python3 /usr/lib/voxfox/voxfox_gtk.py "$@"
EOF
chmod 0755 "$ROOT/usr/bin/voxfox"

# ── desktop entry ────────────────────────────────────────────────────────────
cat > "$ROOT/usr/share/applications/voxfox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VoxFox
GenericName=Screen reader & dictation
Comment=Read selected text aloud, dictate, and OCR the screen
Exec=voxfox
Icon=voxfox
Terminal=false
Categories=Utility;Accessibility;GTK;
Keywords=tts;speech;dictation;ocr;accessibility;piper;whisper;
StartupNotify=true
EOF

# ── locales (optional UI translations) ───────────────────────────────────────
if [ -d "$SRC/locales" ]; then
    install -m 0644 "$SRC"/locales/*.json "$ROOT/usr/share/voxfox/locales/" 2>/dev/null || true
fi

# ── icon (resize logo to 256x256 if Pillow is available, else copy as-is) ─────
ICON_DST="$ROOT/usr/share/icons/hicolor/256x256/apps/voxfox.png"
if [ -f "$SRC/voxfox-logo.png" ]; then
    if python3 - "$SRC/voxfox-logo.png" "$ICON_DST" <<'PY' 2>/dev/null
import sys
from PIL import Image
src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
im.thumbnail((256, 256), Image.LANCZOS)
canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
canvas.paste(im, ((256 - im.width) // 2, (256 - im.height) // 2), im)
canvas.save(dst, "PNG")
PY
    then :; else install -m 0644 "$SRC/voxfox-logo.png" "$ICON_DST"; fi
    chmod 0644 "$ICON_DST"
fi

# ── docs ─────────────────────────────────────────────────────────────────────
if [ -f "$SRC/README-deb.md" ]; then
    install -m 0644 "$SRC/README-deb.md" "$ROOT/usr/share/doc/voxfox/README.md"
elif [ -f "$SRC/README.md" ]; then
    install -m 0644 "$SRC/README.md" "$ROOT/usr/share/doc/voxfox/README.md"
fi
[ -f "$SRC/LICENSE" ] && install -m 0644 "$SRC/LICENSE" "$ROOT/usr/share/doc/voxfox/copyright" || true
[ -f "$SRC/AFTER-INSTALL.md" ]    && install -m 0644 "$SRC/AFTER-INSTALL.md"    "$ROOT/usr/share/doc/voxfox/AFTER-INSTALL.md"    || true
[ -f "$SRC/AFTER-INSTALL.nl.md" ] && install -m 0644 "$SRC/AFTER-INSTALL.nl.md" "$ROOT/usr/share/doc/voxfox/AFTER-INSTALL.nl.md" || true

# ── control ──────────────────────────────────────────────────────────────────
INSTALLED_KB="$(du -sk "$ROOT" | cut -f1)"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: Daniël Vos <voxfox@example.com>
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.9), python3-gi, gir1.2-gtk-4.0, gir1.2-glib-2.0,
 python3-pyatspi, at-spi2-core
Recommends: xdotool, xclip, wl-clipboard, gnome-screenshot, wmctrl,
 python3-pip, tesseract-ocr, tesseract-ocr-eng, tesseract-ocr-nld, poppler-utils,
 python3-pil, ffmpeg, python3-numpy, python3-sounddevice, python3-soundfile
Suggests: wtype, ydotool, scrot, grim, slurp, spectacle
Description: Screen reader and dictation tool (GTK4)
 VoxFox reads selected text aloud with Piper voices, transcribes speech to
 text with Whisper, and can OCR a file or a selected screen region and read
 the result. It exposes every action over a small command-line interface so
 each button can be bound to a global keyboard shortcut.
 .
 Note: the Piper TTS engine and its voices, faster-whisper (dictation) and
 pytesseract (OCR) are not packaged in Debian. They are installed per-user
 under ~/.piper / pip on first run -- click "Install now" in the app or run
 "voxfox --setup". See the bundled README.
EOF

# ── maintainer script: refresh caches + print first-run hints ────────────────
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -qtf /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi
cat <<'MSG'

VoxFox installed. Two first-run steps:
  1. Install Piper (voices): launch VoxFox and click "Install now",
     or run:  voxfox --setup
  2. Enable accessibility (for hover reading and screen readers):
     VoxFox menu -> "Enable accessibility (system-wide)", then log out/in.
See /usr/share/doc/voxfox/ for details.

MSG
exit 0
EOF
chmod 0755 "$ROOT/DEBIAN/postinst"

# ── build ────────────────────────────────────────────────────────────────────
# Output to the repo root so the installable package sits next to src/ and the
# docs, while packaging/ holds only the build scripts.
OUT="$SRC/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT"
echo "Built: $OUT"

#!/usr/bin/env bash
set -e
VERSION="${VERSION:-$(grep APP_VERSION "$SRC/voxfox_gtk.py" | grep -oP '\".*\"' | tr -d '\"')}"
SRC="${SRC:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK=$(mktemp -d); trap "rm -rf $WORK" EXIT
INST="$WORK/install"
mkdir -p "$INST/usr/lib/voxfox/voxfox_core" "$INST/usr/share/voxfox/locales" \
         "$INST/usr/share/applications" "$INST/usr/share/icons/hicolor/256x256/apps" \
         "$INST/usr/bin" "$INST/DEBIAN"
cp "$SRC/voxfox_gtk.py" "$INST/usr/lib/voxfox/"
cp "$SRC/voxfox_core/"*.py "$INST/usr/lib/voxfox/voxfox_core/"
LOCALES="${LOCALES:-$SRC/locales}"
cp "$LOCALES/"*.json "$INST/usr/share/voxfox/locales/"
[ -f "$SRC/voxfox-logo.png" ] && cp "$SRC/voxfox-logo.png" "$INST/usr/share/icons/hicolor/256x256/apps/voxfox.png"
cat > "$INST/usr/bin/voxfox" <<LAUNCHER
#!/bin/sh
exec python3 /usr/lib/voxfox/voxfox_gtk.py "\$@"
LAUNCHER
chmod 755 "$INST/usr/bin/voxfox"
cat > "$INST/DEBIAN/control" <<CTRL
Package: voxfox
Version: $VERSION
Architecture: all
Maintainer: Daniël Vos
Depends: python3 (>= 3.9), python3-gi, gir1.2-gtk-4.0, gir1.2-glib-2.0, python3-pyatspi, at-spi2-core
Description: VoxFox screen reader and dictation tool
CTRL
fakeroot dpkg-deb --build "$INST" "$SRC/voxfox_${VERSION}_all.deb"
echo "Built: $SRC/voxfox_${VERSION}_all.deb"

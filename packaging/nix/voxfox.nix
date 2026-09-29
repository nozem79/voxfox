/*
  VoxFox for Nix / NixOS.

  I could not test-build or evaluate this on a real Nix installation --
  this sandbox has no `nix` binary at all. Every package name below was
  checked against real nixpkgs source (searched, not recalled from
  memory), and the overall shape follows two real, current nixpkgs
  packages that are architecturally very close to VoxFox: `niriswitcher`
  (a small PyGObject/GTK4 app: pygobject3 + wrapGAppsHook4 + a manual
  wrapper-args preFixup) and `rofi-rbw` (a Python CLI tool that wraps in
  optional X11-vs-Wayland runtime tools via `--prefix PATH`, exactly the
  X11/Wayland split VoxFox itself has to make). Even so, please run
  through NIXOS.md's checklist before trusting this on a real machine --
  in particular the one attribute name I could not fully confirm
  (`python3Packages.xlib`, noted below) and the tesseract language-data
  question.

  VoxFox is not a "real" pip package (no pyproject.toml package metadata,
  no console_scripts entry point) -- by design, per its own README: it
  ships as a source tree dropped into /usr/lib/voxfox by the .deb/.rpm.
  This derivation does the Nix-native equivalent of that: copy the
  source tree into the Nix store and wrap two launcher scripts, rather
  than pretending it is a normal buildPythonApplication.
*/
{ lib
, stdenvNoCC
, makeWrapper
, wrapGAppsHook4
, imagemagick
, python3
, gtk4
, at-spi2-core
, gobject-introspection
, hicolor-icon-theme
, glib                     # provides the gsettings binary; see runtimeTools
, gsettings-desktop-schemas # org.gnome.desktop.interface -- see buildInputs

# Runtime CLI tools. The X11 ones are always on PATH (see the
# no-withX11 note below); the Wayland-only ones are added when
# withWayland is on (the default). A Nix/NixOS install has no
# equivalent of "whatever the desktop already pulled in" to fall back
# on -- if it's not wrapped in, VoxFox can't see it, full stop.
, wmctrl
, xdotool
, maim
, xclip
, tesseract
, poppler-utils
, pulseaudio
, ffmpeg
, wl-clipboard ? null
, wtype ? null
, grim ? null
, slurp ? null

, withWayland ? true
# No withX11 flag: wmctrl/xdotool/maim/xclip are always included, even in
# a Wayland-only build, because VoxFox's stay-on-top feature works on
# Wayland precisely by restarting itself as an XWayland client -- an X11
# tool is not an "only for X11 sessions" thing here the way the Wayland
# tools genuinely are.
, withDictation ? true   # faster-whisper + sounddevice + soundfile
, withXlibFastPath ? true # the optional python3Packages.xlib hover speedup
}:

let
  pname = "voxfox";

  # Kept in sync BY HAND with APP_VERSION in src/voxfox_ui/common.py --
  # bump both together. (An automatic extraction via builtins.match on
  # the source file would be nicer, but I have no way to test here
  # whether Nix's regex engine matches "." across the newlines a
  # multi-line file needs, and a wrong guess there would fail the whole
  # build rather than just this one string, so a plain hardcoded value
  # is the safer choice until someone can verify that on a real system.)
  version = "5.0.6";

  pythonEnv = python3.withPackages (ps: with ps; [
    pygobject3
    pyatspi
    numpy
    pillow
    pytesseract
  ]
  ++ lib.optionals withDictation [ faster-whisper sounddevice soundfile ]
  # NOT fully confirmed against a real nixpkgs evaluation (no `nix` here
  # to check with) -- the source lives at
  # pkgs/development/python-modules/xlib/default.nix, which strongly
  # suggests the exposed attribute is `xlib`, but nixpkgs occasionally
  # exposes a package under a different final name than its directory.
  # If this line fails to evaluate, try `python-xlib` instead, or drop
  # -- it only enables a faster hover-mode mouse-position check and
  # VoxFox falls back to xdotool without it either way.
  ++ lib.optionals withXlibFastPath [ xlib ]
  );

  runtimeTools =
    [ wmctrl xdotool maim xclip tesseract poppler-utils pulseaudio ffmpeg glib ]
    ++ lib.optionals withWayland
      (lib.filter (p: p != null) [ wl-clipboard wtype grim slurp ]);

in
stdenvNoCC.mkDerivation {
  inherit pname version;

  src = ../..; # repo root: src/, locales/, icons/, dicts/, voxfox-logo.png

  nativeBuildInputs = [
    makeWrapper
    wrapGAppsHook4
    gobject-introspection
    imagemagick # icon resizing at build time, see installPhase
  ];

  buildInputs = [ gtk4 at-spi2-core hicolor-icon-theme gsettings-desktop-schemas ];

  # GTK4 apps normally get their PATH/typelib/schema wrapping for free
  # from wrapGAppsHook4 acting on $out/bin/*. We want to ALSO inject our
  # own PYTHONPATH and runtime-tool PATH into that same wrapper, so we
  # opt out of the automatic pass and fold both into one preFixup --
  # exactly the pattern nixpkgs' own `cozy` package uses for the same
  # reason (a Python/GTK4 app with extra wrapper needs).
  dontWrapGApps = true;

  # voxfox_ui/common.py hardcodes SYSTEM_DATA_DIR = "/usr/share/voxfox"
  # (used to find locales and the icons/ directory when no per-user copy
  # exists yet -- see voxfox_ui/app.py and _register_icon_path()). That
  # is exactly right for the .deb/.rpm, which really do install there,
  # and exactly wrong for a Nix store path. Patched here, at Nix-build
  # time, on a copy of the source -- the tracked repository is
  # untouched, so this has no effect on the .deb/.rpm builds.
  postPatch = ''
    substituteInPlace src/voxfox_ui/common.py \
      --replace-fail \
        'SYSTEM_DATA_DIR = "/usr/share/voxfox"' \
        'SYSTEM_DATA_DIR = "'"$out"'/share/voxfox"' \
      --replace-fail \
        'SYSTEM_ICON     = "/usr/share/icons/hicolor/256x256/apps/voxfox.png"' \
        'SYSTEM_ICON     = "'"$out"'/share/icons/hicolor/256x256/apps/voxfox.png"'
  '';

  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/lib/voxfox/voxfox_core" "$out/lib/voxfox/voxfox_ui"
    cp src/voxfox_gtk.py src/quickshot.py "$out/lib/voxfox/"
    cp src/voxfox_core/*.py "$out/lib/voxfox/voxfox_core/"
    cp src/voxfox_ui/*.py   "$out/lib/voxfox/voxfox_ui/"

    # icons/ as a *sibling* of voxfox_ui/, so _register_icon_path()'s own
    # relative fallback (os.path.join(here, "..", "icons"), meant for a
    # plain git checkout) finds them with no patch needed.
    cp -r icons "$out/lib/voxfox/icons"

    mkdir -p "$out/share/voxfox/locales"
    cp locales/*.json "$out/share/voxfox/locales/"

    if [ -d dicts ]; then
      mkdir -p "$out/share/voxfox/dicts"
      cp dicts/*.json "$out/share/voxfox/dicts/" 2>/dev/null || true
    fi

    mkdir -p "$out/bin"
    makeWrapper ${pythonEnv}/bin/python3 "$out/bin/voxfox" \
      --add-flags "$out/lib/voxfox/voxfox_gtk.py"
    makeWrapper ${pythonEnv}/bin/python3 "$out/bin/voxfox-quickshot" \
      --add-flags "$out/lib/voxfox/quickshot.py"

    # Icon: same hicolor sizes the .deb generates (48-512), via
    # ImageMagick instead of Pillow so the derivation doesn't need a
    # Python build-time dependency just for this.
    if [ -f voxfox-logo.png ]; then
      install -Dm644 voxfox-logo.png \
        "$out/share/pixmaps/voxfox.png"
      for size in 48 64 128 256 512; do
        d="$out/share/icons/hicolor/''${size}x''${size}/apps"
        mkdir -p "$d"
        convert voxfox-logo.png -resize "''${size}x''${size}" "$d/voxfox.png"
      done
    fi

    mkdir -p "$out/share/applications"
    cat > "$out/share/applications/voxfox.desktop" <<DESKTOP
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

    runHook postInstall
  '';

  # Fold wrapGAppsHook4's own GTK/GLib/typelib environment (gappsWrapperArgs)
  # together with our PYTHONPATH and the runtime CLI tools, in one wrapper
  # per launcher -- same shape as nixpkgs' own `cozy` and `niriswitcher`.
  preFixup = ''
    for prog in voxfox voxfox-quickshot; do
      wrapProgram "$out/bin/$prog" \
        "''${gappsWrapperArgs[@]}" \
        --set PYTHONPATH "${pythonEnv}/${pythonEnv.sitePackages}" \
        --prefix PATH : "${lib.makeBinPath runtimeTools}"
    done
  '';

  meta = {
    description = "Screen reader, dictation, and OCR tool (offline, GTK4)";
    longDescription = ''
      VoxFox reads text aloud from any application, lets you dictate by
      voice instead of typing, and reads text out of PDFs, images, and
      scanned documents via OCR. Everything runs locally.
    '';
    homepage = "https://voxfox.nl";
    license = lib.licenses.gpl3Plus;
    platforms = lib.platforms.linux;
    mainProgram = "voxfox";
  };
}

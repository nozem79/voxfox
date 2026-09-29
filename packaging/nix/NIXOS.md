# VoxFox on Nix / NixOS

This packaging was written without access to a real Nix installation --
every package name was checked against actual nixpkgs source (via search,
not memory), and the derivation's shape follows two real, current nixpkgs
packages that are architecturally close to VoxFox (a small PyGObject/GTK4
app): `niriswitcher` and `cozy`. It has never been evaluated or built.
Please work through the checklist below on a real machine before trusting
it, and treat this the way the .rpm was treated when it was new: useful,
probably correct, not yet proven.

## Trying it

Flakes:

    nix run github:nozem79/voxfox           # run without installing
    nix build github:nozem79/voxfox         # build, result in ./result/bin/voxfox
    nix develop github:nozem79/voxfox       # a shell with pytest + ruff + GTK4, for hacking on the code itself

Without flakes:

    nix-build https://github.com/nozem79/voxfox/archive/refs/heads/main.tar.gz
    ./result/bin/voxfox

On NixOS, system-wide, add it as a flake input in `configuration.nix` /
`flake.nix` and put `voxfox.packages.${system}.default` in
`environment.systemPackages` -- or, more simply, `nix profile install
github:nozem79/voxfox` for a per-user install.

## Checklist for the first real build

1. **Does it evaluate at all?** `nix build .` and read whatever the first
   error is. The single most likely failure point is the next item.

2. **`python3Packages.xlib`.** This is VoxFox's optional faster hover-mode
   mouse-position check (`python-xlib` on PyPI). The nixpkgs source lives
   at `pkgs/development/python-modules/xlib/default.nix`, which strongly
   suggests the exposed attribute is `xlib`, but I could not confirm the
   final attribute name against a real evaluation. If the build fails
   here: try `nix search nixpkgs python-xlib` to find the real name, fix
   it in `packaging/nix/voxfox.nix`'s `pythonEnv`, or just pass
   `withXlibFastPath = false` when calling the package -- VoxFox falls
   back to `xdotool` without it, working identically, just with one more
   subprocess spawned per hover-mode poll (about 6-7 times a second while
   hover mode is on).

3. **Tesseract language data.** The .deb/.rpm install per-language
   packages (`tesseract-ocr-nld`, etc.); nixpkgs bundles this differently.
   Check what `tesseract --list-langs` reports inside the built package's
   wrapped environment, and whether the languages you actually use (Slot
   1 / Slot 2) are present. If not, this needs its own small fix -- most
   likely overriding `tesseract` with the language data included, since
   nixpkgs' tesseract derivation supports selecting which trained-data
   sets to bundle.

4. **The icon.** `voxfox-logo.png` is resized with ImageMagick's
   `convert` at build time instead of Pillow (matching the .deb's own
   Pillow-based resizing, just without needing a Python build input for
   it). Confirm the launcher/taskbar icon actually shows up -- this
   exercises both that resize step and the desktop file's `Icon=voxfox`
   resolving through the standard hicolor theme path.

5. **Translations.** VoxFox looks for `$out/share/voxfox/locales` only
   when no per-user copy exists yet at `$XDG_DATA_HOME/voxfox/locales`
   (see `voxfox_ui/app.py`). Start VoxFox in a language other than
   English and confirm the interface actually translates -- this is the
   one hardcoded `/usr/share/voxfox` path that genuinely had to be
   patched for Nix (see `postPatch` in `voxfox.nix`); everything else
   either doesn't care about FHS paths or already has its own
   git-checkout-relative fallback that happens to also work under Nix's
   store layout.

6. **Dictation model downloads.** faster-whisper's model cache already
   has to cope with a read-only configured location -- that's exactly
   what the HF_HOME handling added for FoxOS in 5.0.6 does (see
   `_writable_hub_cache()` in `voxfox_core/stt.py`): look in the
   configured location, download into whichever hub folder is actually
   writable, falling back to the user's own `~/.cache/huggingface`. A
   Nix store path is always read-only, so this should already do the
   right thing with no Nix-specific change needed -- but it has not been
   tried against an actual Nix-built VoxFox, so confirm the model
   download in Settings actually lands somewhere and gets found again on
   the next start.

7. **Always-on-top / window position.** Both features restart VoxFox as
   an XWayland client on a Wayland session (see `voxfox_gtk.py`'s
   `_restart_on_xwayland`) and shell out to `wmctrl`. Confirm `wmctrl` is
   genuinely reachable from inside the wrapped launcher (it's in
   `runtimeTools`, unconditionally, in `voxfox.nix`) and that this still
   works when VoxFox itself is a Nix store path rather than
   `/usr/bin/voxfox`.

## What was deliberately left out

- No NixOS module (a `services.voxfox` or similar for declarative
  configuration). VoxFox is a desktop application someone launches
  themselves, not a service with configuration worth managing through
  NixOS options -- a plain package is the right shape for it.
- No attempt to vendor Piper voices or Whisper models into the Nix store
  itself (as a fixed-output derivation, say). They're large, numerous,
  user-chosen, and already have a working, tested download-and-cache
  path; duplicating that as Nix derivations would be a lot of extra
  surface for no real benefit over what already works.
- `withDictation` and `withWayland` exist as real, functioning
  build-time toggles (unlike the removed `withX11`, which never did
  anything and was deleted rather than kept as a decoration) --
  `withDictation = false` skips `faster-whisper` + `sounddevice` +
  `soundfile` entirely, `withWayland = false` skips `wl-clipboard` /
  `wtype` / `grim` / `slurp`.

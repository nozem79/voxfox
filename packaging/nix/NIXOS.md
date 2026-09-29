# VoxFox on Nix / NixOS

This packaging was written without access to a real Nix installation --
every package name was checked against actual nixpkgs source (via search,
not memory), and the derivation's shape follows two real, current nixpkgs
packages that are architecturally close to VoxFox (a small PyGObject/GTK4
app): `niriswitcher` and `cozy`. It has since been evaluated and built on
a real NixOS machine, which found two real bugs (nixpkgs had renamed
`poppler_utils` to `poppler-utils`; `gsettings` itself and its schemas
weren't on the wrapped launcher's PATH at all) -- both fixed. Whether
VoxFox actually speaks once it's running has not been confirmed yet (see
the Piper/nix-ld item below). `.github/workflows/nix.yml` now builds this
flake on every push against a real Nix install, which is the single
biggest gap this had before: nobody, including me, had ever actually
built it.

## Prerequisites

Two things that were only found by trying VoxFox on a real NixOS machine,
now listed here up front instead of being discovered by trial and error:

1. **Flakes and the `nix` command are off by default on NixOS.** Without
   this, every command below fails with `experimental Nix feature
   'nix-command' is disabled`. In `/etc/nixos/configuration.nix`:

       nix.settings.experimental-features = [ "nix-command" "flakes" ];

   then `sudo nixos-rebuild switch` once.

2. **Piper -- VoxFox's speech engine -- is downloaded as a prebuilt
   binary from GitHub on first run, not built by Nix.** A binary built
   outside Nix expects the dynamic linker at a fixed path
   (`/lib64/ld-linux-x86-64.so.2` and similar) that plain NixOS does not
   have -- everything lives in the Nix store instead. This will very
   likely stop the downloaded Piper binary from running at all. The
   standard NixOS fix is `nix-ld`, in `/etc/nixos/configuration.nix`:

       programs.nix-ld.enable = true;

   then `sudo nixos-rebuild switch`. Confirm with `~/.piper/piper --help`
   after VoxFox has downloaded it once -- "cannot execute" or "No such
   file or directory" despite the file existing means this is it.
   Properly packaging Piper itself as a Nix derivation (rather than
   relying on nix-ld to run a foreign binary) would remove the need for
   this, but is a separate, larger piece of work than this package.

## Trying it

**If there's no committed `flake.lock` yet**, every command below fails
with `cannot write modified lock file` -- a flake fetched straight from
GitHub is read-only, and Nix wants to write the resolved versions
somewhere. Add `--no-write-lock-file` to work around it for now (shown
below), or better, fix it once for everyone: on any machine with Nix
installed, `cd` into a checkout of this repo and run `nix flake lock`,
then commit and push the `flake.lock` it creates. `.github/workflows/nix.yml`
checks on every push that one exists, but can't generate it itself --
someone with a working Nix install has to run that command once.

Flakes:

    nix run github:nozem79/voxfox --no-write-lock-file           # run without installing
    nix build github:nozem79/voxfox --no-write-lock-file         # build, result in ./result/bin/voxfox
    nix develop github:nozem79/voxfox --no-write-lock-file       # a shell with pytest + ruff + GTK4, for hacking on the code itself

(drop `--no-write-lock-file` from all three once `flake.lock` is committed)

Without flakes:

    nix-build https://github.com/nozem79/voxfox/archive/refs/heads/main.tar.gz
    ./result/bin/voxfox

On NixOS, system-wide, add it as a flake input in `configuration.nix` /
`flake.nix` and put `voxfox.packages.${system}.default` in
`environment.systemPackages` -- or, more simply, `nix profile install
github:nozem79/voxfox` for a per-user install.

## Checklist for the first real build

1. **Does it evaluate and build at all?** `nix build .` and read whatever
   the first error is. Confirmed working past this point on a real NixOS
   machine as of this writing, after fixing two real issues nixpkgs drift
   and an incomplete PATH caused (`poppler_utils` renamed to
   `poppler-utils`; `gsettings` and its schemas missing from the wrapped
   launcher's PATH, which broke VoxFox's own "Enable accessibility" setup
   step specifically -- see `enable_accessibility()` in
   `voxfox_ui/setup.py`). `.github/workflows/nix.yml` now builds this on
   every push, which is what should catch the next thing like this before
   it reaches a real machine.

2. **No speech at all.** See "Prerequisites" above, item 2 (Piper /
   nix-ld) -- this is the single most likely explanation if VoxFox opens
   and runs but nothing is ever read aloud. Confirm with `~/.piper/piper
   --help` before looking anywhere else.

3. **`python3Packages.xlib`.** This is VoxFox's optional faster hover-mode
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

4. **Tesseract language data.** The .deb/.rpm install per-language
   packages (`tesseract-ocr-nld`, etc.); nixpkgs bundles this differently.
   Check what `tesseract --list-langs` reports inside the built package's
   wrapped environment, and whether the languages you actually use (Slot
   1 / Slot 2) are present. If not, this needs its own small fix -- most
   likely overriding `tesseract` with the language data included, since
   nixpkgs' tesseract derivation supports selecting which trained-data
   sets to bundle.

5. **The icon.** `voxfox-logo.png` is resized with ImageMagick's
   `convert` at build time instead of Pillow (matching the .deb's own
   Pillow-based resizing, just without needing a Python build input for
   it). Confirm the launcher/taskbar icon actually shows up -- this
   exercises both that resize step and the desktop file's `Icon=voxfox`
   resolving through the standard hicolor theme path.

6. **Translations.** VoxFox looks for `$out/share/voxfox/locales` only
   when no per-user copy exists yet at `$XDG_DATA_HOME/voxfox/locales`
   (see `voxfox_ui/app.py`). Start VoxFox in a language other than
   English and confirm the interface actually translates -- this is the
   one hardcoded `/usr/share/voxfox` path that genuinely had to be
   patched for Nix (see `postPatch` in `voxfox.nix`); everything else
   either doesn't care about FHS paths or already has its own
   git-checkout-relative fallback that happens to also work under Nix's
   store layout.

7. **Dictation model downloads.** faster-whisper's model cache already
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

8. **Always-on-top / window position.** Both features restart VoxFox as
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

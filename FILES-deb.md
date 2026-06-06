# VoxFox (GTK4 / Debian package) — file guide

## Install

- **`voxfox_<version>_all.deb`** — the installable package (top level):
  `sudo apt install ./voxfox_<version>_all.deb`.
- **`AFTER-INSTALL.md`** / **`AFTER-INSTALL.nl.md`** — the two first-run steps
  (install Piper voices, enable accessibility), in English and Dutch.

## Source code

- **`src/voxfox_gtk.py`** — the GTK4 front-end (window, settings, setup, hover,
  OCR, dictation, always-on-top, accessibility labels).
- **`src/voxfox_core/`** — the UI-agnostic backend, now a package of focused
  modules: `common` (logging, XDG paths, the `AppState`/i18n object, Piper
  language tables), `state` (settings + history), `tts` (Piper voices and the
  speaking worker), `stt` (Whisper local + remote API, GPU detection with a
  P40-safe compute-type cascade), `ocr` (Tesseract with a CLI fallback and
  line-merging), `a11y` (AT-SPI hover-to-read, selection, typing/paste), and
  `ipc` (the single-instance socket server and CLI). No GUI-toolkit imports;
  `import voxfox_core` re-exports the whole public API.

Run from source: `python3 src/voxfox_gtk.py` (needs GTK 4 + the dependencies).

## Build tooling (`packaging/`)

- **`build-deb.sh`** — assembles the `.deb` from the sources, writing it to the
  project root. Run `./build-deb.sh` (or `VERSION=x.y.z ./build-deb.sh`). Needs
  `dpkg-deb`. Reads the Python from `src/` (falls back to a flat layout).
- **`gen_docs.py`** — regenerates the HTML manuals from the markdown sources.

## Assets

- **`locales/*.json`** — UI translations (de, en, es, fr, it, nl, pt).
- **`voxfox-logo.png`** — app logo / icon source.
- **`licence.txt`** — GPLv3.

## Documentation

- **`README-deb.md`** / **`README-deb.html`** — manual (English)
- **`README-deb.nl.md`** / **`README-deb.nl.html`** — manual (Dutch)

## Changelog

- **`CHANGELOG.md`** — notable changes per version.

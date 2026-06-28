# VoxFox (GTK4 / Debian package)

VoxFox is a screen reader and dictation tool for Linux. It reads selected text
aloud with Piper voices, transcribes speech to text with Whisper, and can OCR a
file or a selected screen region and read the result. Every action is also a
command-line call, so each button can be bound to a global keyboard shortcut.

This document covers the **GTK4 build installed from the `.deb` package**. It is
different from the standalone Tk version: it installs system-wide via `apt`,
shares a UI-agnostic backend (`voxfox_core`), and adds GPU detection for
Whisper, a tesseract CLI fallback for OCR, and proper screen-reader labels.

## Installation

```bash
sudo apt install ./voxfox_3.4_all.deb
```

`apt` pulls in the dependencies automatically. Then launch VoxFox from the
application menu, or run `voxfox` in a terminal.

> If you install from your home folder you may see a notice that the download
> "is performed by root and not sandboxed, because `_apt` could not access the
> file". This is harmless — the install still completes. To avoid it, install
> from a world-readable path, e.g. `sudo cp voxfox_3.4_all.deb /tmp/ && sudo
> apt install /tmp/voxfox_3.4_all.deb`.

### What the package installs

The `.deb` only installs the program itself (to `/usr/lib/voxfox`, with a
launcher at `/usr/bin/voxfox`, a desktop entry, an icon and the translations).
The heavier, per-user components are fetched on first run — see Setup.

## First-time setup

Piper (the TTS engine and its voices), `faster-whisper` (dictation) and
`pytesseract` (optional OCR helper) are **not** Debian packages, so they are
installed per user. On first launch, if Piper is missing, the window shows a
banner:

> Piper TTS is not installed yet. **[Install now]**

Click it, or run the same thing headless:

```bash
voxfox --setup
```

This downloads the Piper engine for your CPU architecture, two default voices
(`en_GB-alba-medium` and `nl_NL-pim-medium`) into `~/.piper`, and installs
`faster-whisper` and `pytesseract` with pip. It is safe to re-run, and is also
available from the *Set up VoxFox…* window in the menu.

> Setup needs `python3-pip` (a recommended dependency). OCR works even without
> `pytesseract` because VoxFox falls back to the `tesseract` command line.

## The window

The title bar shows the program name, with **Settings** (gear) and the **menu**
on the right. Two rows of buttons:

- **Row 1:** Read · Stop · Pause
- **Row 2:** Speak · Hover · Select · OCR · NL/EN (the language switcher)

A status line appears below the buttons while something is happening and hides
itself again when idle. It is marked as a live region, so a screen reader
announces messages such as "Reading…" automatically. While a Whisper model or a
Piper voice is downloading, a progress bar appears just below the status line so
you can see how far along the download is.

## Reading text aloud

Select text in any application, then press **Read** (or run `voxfox --read`).
VoxFox speaks it with the active slot's voice. **Stop** halts playback;
**Pause** pauses and resumes.

## Two language slots

VoxFox keeps two voice/language slots so you can switch between, say, Dutch and
English quickly. The **NL/EN** button (and `voxfox --toggle-slot`) switches the
active slot. Each slot's language, voice and speed are configured under
**Settings** (the gear). Changing slot 1's language also re-renders the whole
interface in that language immediately.

## History

VoxFox keeps your last 20 read and dictated items. Open **Menu → History** to
see them: each entry can be read again (▶) or copied to the clipboard so you can
paste it wherever you like. **Clear all** empties the list.

## Pronunciation dictionary

VoxFox can re-spell words before they are spoken — handy for names,
abbreviations and loanwords the voice gets wrong. Open **Settings →
Pronunciation**; it edits the dictionary for slot 1's language. Add rules as
*word → pronounce as* (e.g. `VoxFox → Voks-foks`, `GUI → goo-ee`) and use
**Test** to hear them. Matching is whole-word and case-insensitive, and the
rules apply to everything spoken in that language (Read, Hover, OCR).

## Reading wrapped text, and Settings → Misc

When you read OCR output or text you've selected (for instance copied from a
PDF), VoxFox joins lines that are only word-wrapped into proper paragraphs, so
it no longer pauses in the middle of a sentence. Toggle this under
**Settings → Misc** ("Merge wrapped lines into paragraphs") — turn it off to
read every line on its own (handy for lists or code). The Misc tab also has
**Import / Export settings** to back up or move your configuration.

## Dictation (speech to text)

Press **Speak** (or `voxfox --whisper-toggle`) to start recording; press again
to stop. VoxFox transcribes the audio and types the result into the focused
application. Under **Settings → Whisper** you can choose the model, the
microphone, and whether to confirm the text before it is typed.

### Local vs. remote (API)

- **Local** runs Whisper on your machine via `faster-whisper`. Pick a model
  (`tiny` → `large-v3`) and use the download button to fetch it ahead of time;
  larger models are more accurate but slower and bigger.
- **Remote API** sends the audio to an OpenAI-compatible transcription endpoint.
  Fill in the URL, model and (optional) API key, then use **Test connection**.

### GPU acceleration

Whisper can use an NVIDIA GPU. Under **Settings → Compute**:

- **Auto** (default) uses the GPU when a CUDA runtime is detected, otherwise the
  CPU. If GPU initialisation fails it falls back to the CPU automatically.
- **CPU** / **GPU** force a choice.

A GPU mainly helps the larger models. It needs the NVIDIA driver plus the CUDA
runtime, cuBLAS and cuDNN, which are not shipped with the package. The simplest
way to get the libraries is via pip:

```bash
pip install --user nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Older Pascal cards (e.g. the Tesla P40, compute capability 6.1) cannot do
efficient float16 — VoxFox detects this and uses `int8` on such GPUs
automatically (float16 would crash or be very slow). int8 has negligible impact
on accuracy. Volta and newer cards use float16. Piper TTS uses the bundled CPU
build — it is already faster than real time, so there is no GPU build for it.

## OCR — read text from images and the screen

- **Select** (`voxfox --ocr-select`) lets you drag a rectangle on screen; the
  text inside is OCR'd and read aloud. It uses your desktop's native region
  screenshot tool, so it works on both X11 and Wayland.
- **OCR** opens a PDF or image file and reads its text.

OCR uses Tesseract. It works with just the `tesseract-ocr` package (plus the
language data, e.g. `tesseract-ocr-nld`); `pytesseract` is optional.

## Hover mode

**Hover** (`voxfox --hover-toggle`) reads the UI text under the mouse pointer
aloud, using the AT-SPI accessibility tree.

For this to work the accessibility bus must be enabled. The *Set up VoxFox…*
window in the menu can switch it on for you (it sets the GNOME
`toolkit-accessibility` option); restart the target application afterwards.
Chromium-based browsers additionally need to be launched with
`--force-renderer-accessibility`.
Hover is most reliable on GTK and Firefox windows.

## Always on top

The window stays above other windows (like the old build), via `wmctrl`. This
applies on **X11**; on Wayland the compositor controls window stacking, so it
may not take effect.

## Keyboard shortcuts

VoxFox can install five global shortcuts for you — open
**Settings → Shortcuts**, optionally change any combination by clicking it and
pressing the keys, then choose **Install shortcuts**. This works on Cinnamon,
GNOME, LXQt and XFCE; nothing is installed automatically. Defaults:

| Command                    | Action                     | Default   |
|----------------------------|----------------------------|-----------|
| `voxfox --read`            | Read selected text         | `Super+Z` |
| `voxfox --stop`            | Stop speaking              | `Super+X` |
| `voxfox --toggle-slot`     | Switch language slot       | `Super+C` |
| `voxfox --whisper-toggle`  | Dictate (speech to text)   | `Super+W` |
| `voxfox --ocr-select`      | Read a screen region (OCR) | `Super+A` |

`voxfox --install-shortcuts` does the same from a terminal. Other commands
(`voxfox --pause`, `voxfox --hover-toggle`) can be bound by hand in your
desktop's keyboard settings.

Other commands: `voxfox --ocr <file>` (OCR a file, works without a running
instance), `voxfox --status`, `voxfox --quit`, `voxfox --setup`,
`voxfox --verbose`.

## Accessibility

VoxFox is built to be usable with a screen reader. All buttons have explicit
accessible names and tooltips, icon-only buttons use symbolic icons rather than
emoji, and the status line is a live region. Tested with Orca.

## Dependencies

Installed automatically:

- **Required:** `python3`, `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-glib-2.0`,
  `python3-pyatspi`, `at-spi2-core`
- **Recommended (pulled by default):** `xdotool`, `xclip`, `wl-clipboard`,
  `gnome-screenshot`, `wmctrl`, `python3-pip`, `tesseract-ocr`,
  `tesseract-ocr-eng`, `tesseract-ocr-nld`, `poppler-utils`, `python3-pil`,
  `ffmpeg`, `python3-numpy`, `python3-sounddevice`, `python3-soundfile`

Optional, for Whisper on GPU: the NVIDIA driver, CUDA runtime and cuDNN.

## Where things live

- Program: `/usr/lib/voxfox/` (launcher `/usr/bin/voxfox`)
- Piper engine + voices: `~/.piper/`
- Whisper models cache: `~/.cache/huggingface/`
- Settings: `~/.config/voxfox_state.json`

## For developers / source code

VoxFox is written in Python, so there is no compilation to a binary — the
program runs through the Python interpreter, and the `.deb` ships the source as
plain text in `/usr/lib/voxfox/`. Reviewing, improving and rebuilding it is
therefore straightforward.

**The source** is a backend package plus a front-end and assets:

- `voxfox_core/` — the UI-agnostic backend, a package of focused modules:
  `tts.py` (Piper TTS), `stt.py` (Whisper STT — local, remote API, GPU
  detection), `ocr.py` (Tesseract OCR with a CLI fallback), `ipc.py` (the IPC
  server), `state.py` (settings/history storage and the language tables),
  `a11y.py` (accessibility helpers) and `common.py`. It imports no GUI toolkit.
- `voxfox_gtk.py` — the GTK4 front-end (window, settings, buttons) plus the
  command-line interface; it imports `voxfox_core`.
- Assets: `locales/*.json` (translations), `voxfox-logo.png`, `licence.txt`.
- `packaging/build-deb.sh` — assembles the `.deb`.

(The standalone Tk version under `tk-original/` is a separate variant and is not
needed for the GTK/`.deb` build.)

**Review** by reading the two `.py` files. **Run from source** without packaging
using `python3 voxfox_gtk.py` (GTK 4 and the dependencies must be present).
**Improve** by editing those files.

**Build the package** (no compilation; Python byte-compiles itself at runtime):

```bash
cd packaging
./build-deb.sh                 # produces voxfox_<version>_all.deb
VERSION=1.1.0 ./build-deb.sh   # build a specific version
```

Building only needs `dpkg-deb`.

## Supported systems

- **Operating system:** Debian-based Linux (Debian, Ubuntu, Linux Mint, Pop!_OS,
  …) for the `.deb`. On other distributions (Fedora, Arch) the source runs
  directly with `python3 voxfox_gtk.py`; only the prebuilt package is
  Debian-specific. Not for Windows or macOS — it relies on Linux facilities
  (AT-SPI, xdotool, the Linux Piper binary, …).
- **Desktop:** designed for GNOME. Some features are session-dependent:
  always-on-top (via `wmctrl`) works on X11, not Wayland; text selection and
  region screenshots work on both; hover (AT-SPI) works best on X11.
- **Python / GTK:** Python 3.9+ and GTK 4 (so Debian 12+, Ubuntu 22.04+ or
  newer).
- **CPU architecture:** the package is `Architecture: all` (pure Python). The
  practical limit is the components fetched during setup: the Piper binary is
  available for `x86_64`, `aarch64` and `armv7l`, and `faster-whisper` runs
  mainly on `x86_64` and `aarch64`.
- **GPU (optional):** an NVIDIA GPU with the CUDA runtime and cuDNN accelerates
  Whisper; otherwise everything runs on the CPU.

## Uninstall

```bash
sudo apt remove voxfox
```

Per-user data in `~/.piper`, `~/.config/voxfox_state.json` and the Whisper
cache is left in place; remove it by hand if you want a clean slate.

## License

GPLv3 · © 2025 Daniël Vos · <https://voxfox.nl/manual>

<img width="1376" height="577" alt="VOXFOX-GIT-BG" src="https://github.com/user-attachments/assets/389bf7d3-8538-4748-b6ca-4e75b916f019" />

# VoxFox

A screen reader and dictation tool for Linux with a graphical (GTK4) interface,
voice selection, and speed control. Built on top of
[Piper](https://github.com/rhasspy/piper) (text-to-speech) and
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (speech-to-text).

VoxFox is for people who want to *use* their computer with their voice and
ears — reading long articles aloud while doing the dishes, dictating an email
without touching the keyboard, or hearing a passage of code read back to spot a
mistake.

> The current release is the GTK4 build, packaged as a Debian `.deb`. The older
> Tkinter version is no longer maintained.

## Installation

**Debian, Ubuntu, Linux Mint** (and other Debian-based distributions):

```bash
sudo apt install ./voxfox_*_all.deb
```

**Fedora** (and other RPM-based distributions):

```bash
sudo dnf install ./voxfox-*.noarch.rpm
```

`apt` pulls in the runtime dependencies (`python3-gi`, `gir1.2-gtk-4.0`,
`python3-pyatspi`, `at-spi2-core`) and recommends the optional tools used by
some features (`tesseract-ocr`, `poppler-utils`, `xdotool`, `wmctrl`,
`gnome-screenshot`, `python3-pip`, audio libraries). Launch from the
application menu (under *Accessibility*) or by running `voxfox`.

The `.deb` only installs the program. The Piper engine, the default voices,
faster-whisper (dictation) and the OCR extras are downloaded **per user** on
first use — either click *Install now* on the banner the app shows when Piper
is missing, or run it headless:

```bash
voxfox --setup      # Piper engine + default voices + faster-whisper + OCR extras
```

While a model or voice downloads, a progress bar appears under the status line
so you can see how far along it is.

## First run

On first launch VoxFox notices Piper isn't installed yet and offers to set
everything up. Setup downloads:

- the Piper binary into `~/.piper/`
- two default voices: British English (`en_GB-alba-medium`) and Dutch
  (`nl_NL-pim-medium`)
- `faster-whisper` (for local dictation), via `pip --user`

The first run also creates `~/.config/voxfox_state.json` (your settings) and
logs to `~/.cache/voxfox.log` for debugging.

For hover-to-read, the accessibility bus must be on. The menu's *Set up VoxFox…*
window can switch it on for you (it flips the GNOME `toolkit-accessibility`
setting); restart the target app afterwards (and
launch Chromium browsers with `--force-renderer-accessibility`).

## The window

The main window is deliberately small and hugs its content. By default the
buttons are **Read**, **Stop**, **Pause**, **Speak** (dictate), **Hover**,
**Select** and **OCR**, plus the language-switch button. You can show or hide
any of them and change their order, and scale the whole interface to 75 %,
100 % or 125 % — both under **Settings → Interface** (see below). The title bar
has a **Settings** (gear) button and a **Menu** (hamburger) button.

A status line appears below the buttons while something is happening and hides
itself when idle. It is exposed as a live region, so a screen reader announces
messages like "Reading…" automatically. Just below it, a progress bar shows the
progress of any download in flight.

| Button   | Function                                                |
|----------|---------------------------------------------------------|
| Read     | Read the currently selected text aloud                  |
| Stop     | Stop speaking immediately                               |
| Pause    | Pause / resume the current speech                       |
| Speak    | Dictate: record your voice; Whisper transcribes and types it |
| Hover    | Toggle hover-to-read                                     |
| Select   | Select a screen region and read its text aloud (OCR)    |
| OCR      | Open a PDF or image and read its text aloud             |
| Language | Switch between Language 1 and Language 2                |
| Settings | Open Settings (tabs: Language 1 / 2, Dictation, Pronunciation, Misc, Interface, Shortcuts) |
| Menu     | Set up VoxFox…, History, About, Quit |

## Reading text aloud

Select text in any application, then press **Read** (or your shortcut). The
selected text is read in the active slot's voice. Long passages are split into
chunks and read one after another, so you can **Pause** and **Stop** along the
way.

When the text comes from OCR or a selection that is only word-wrapped (for
example copied from a PDF), VoxFox joins those wrapped lines into proper
paragraphs first, so it doesn't pause in the middle of a sentence. You can turn
that off under *Settings → Misc* (see below).

## Two language slots

VoxFox keeps two independent voice slots — *Language 1* and *Language 2* — each
with its own language, voice and speed. The language-switch button flips
between them in one click, which is much faster than reopening a picker when you
regularly read in two languages. The interface language follows Slot 1.

## Pronunciation dictionary

VoxFox can re-spell words before they are spoken — handy for names,
abbreviations and loanwords the voice gets wrong. Open *Settings →
Pronunciation*; it edits the dictionary for slot 1's language. Add rules as
*word → pronounce as* (e.g. `VoxFox → Voks-foks`, `GUI → goo-ee`), and use the
▶ button on each rule to hear that single word. Matching is whole-word and
case-insensitive, and the rules apply to everything spoken in that language
(Read, Hover, OCR). Stored per language in your settings file.

## History

VoxFox keeps your last 20 read and dictated items. Open *Menu → History* to see
them: each entry can be read again (▶) or copied to the clipboard so you can
paste it wherever you like. **Clear all** empties the list. Stored in
`~/.config/voxfox_history.json`.

(Copy rather than re-type: VoxFox stays always-on-top and holds focus, so typed
text would land in the wrong window — copying lets you paste it where you
actually want it.)

## Settings → Misc

The *Misc* tab holds two things:

- **Merge wrapped lines into paragraphs** (on by default) — the line-joining
  behaviour described under *Reading text aloud*. Turn it off to read every
  line on its own, which is what you want for lists, code or addresses.
- **Import / Export settings** — save the current configuration to a JSON file
  and restore it on another machine. Voices referenced in an imported file are
  downloaded automatically on first use.

```bash
# On the source machine: Settings → Misc → Export to voxfox-settings.json
scp voxfox-settings.json other-machine:~/
# On the other machine: open VoxFox, Settings → Misc → Import
```

## Settings → Interface

The *Interface* tab lets you tailor the toolbar and overall size:

- **Interface size** — scale the whole window to 75 %, 100 % or 125 %. Useful
  on high-DPI screens or when you want larger hit targets.
- **Buttons** — show or hide each toolbar button with a checkbox, and reorder
  them with the up/down arrows. Hide the ones you never use (for example *Pause*
  or *OCR*) to keep the window compact; the layout is remembered.

The *Shortcuts* tab is covered under **Keyboard shortcuts** below.

## Speech-to-text (Whisper)

Click **Dictate** to start recording, click again to stop. The transcribed text
is then typed where your cursor is. Long dictations (over ~200 characters) are
pasted via the clipboard rather than typed, so they appear instantly.

Settings live on the *Dictation* tab:

- **Model** — bigger = more accurate but slower and more memory:
  - `tiny` — fastest, weak accuracy
  - `base` — fast, ok for English
  - `small` — recommended default; good multilingual
  - `medium` — better, ~1.5 GB
  - `large-v3` — best, ~3 GB and slow on CPU
- **Compute** — *Auto* uses an NVIDIA GPU when detected (CUDA + cuDNN),
  otherwise the CPU, and falls back to CPU if GPU init fails
- **Mic** — choose a specific input device, or leave at *Default*
- **Confirm transcription before typing** — show a preview popup with the transcription so you can review and edit it, then copy it to the clipboard and paste it yourself with Ctrl+V (rather than having VoxFox type it)
- **Backend** — *Local* (runs faster-whisper here) or *Remote API* (see below)

The active slot's language is used as a hint for Whisper, which is far more
reliable than auto-detect. Models are downloaded on first use and cached under
`~/.cache/huggingface/`; use the **download** button next to the model dropdown
to fetch one ahead of time (with a progress bar).

### GPU notes

*Auto* compute speeds up the larger models when a CUDA runtime and cuDNN are
present. On older NVIDIA cards (Pascal, e.g. a Tesla P40) VoxFox uses the
`int8` compute type rather than `float16`, which would crash or run slowly, and
cascades through compute types before falling back to the CPU. Piper TTS uses
the bundled CPU build — it is already faster than real time, so no GPU build is
shipped for it.

### Remote Whisper API

If you have a server with a GPU, route transcription to it instead of running
Whisper on the laptop. VoxFox speaks the OpenAI Audio API
(`POST /v1/audio/transcriptions`), which most self-hosted Whisper servers
implement:

- [faster-whisper-server / Speaches](https://github.com/speaches-ai/speaches)
- [whisper.cpp server](https://github.com/ggerganov/whisper.cpp/tree/master/examples/server)
- [LocalAI](https://localai.io/) with the Whisper backend
- OpenAI's hosted Whisper API itself

Set **Backend** to *Remote API* and fill in:

- **URL** — the base URL, e.g. `http://gpu-box:8000/v1`. Trailing slashes don't
  matter; VoxFox appends `/audio/transcriptions`.
- **Model** — the name your server expects (e.g.
  `Systran/faster-whisper-large-v3`, or `whisper-1` / `gpt-4o-transcribe` for
  OpenAI).
- **API key** — optional; blank for most self-hosted servers.

Click **Test** to verify the connection without recording. If the remote server
is unreachable or errors during dictation, VoxFox falls back to the local model
so you don't lose the recording, and the status bar tells you it happened.

#### Example: OpenAI

| Field   | Value                              |
|---------|------------------------------------|
| URL     | `https://api.openai.com/v1`        |
| Model   | `whisper-1` or `gpt-4o-transcribe` |
| API key | `sk-...` (your OpenAI API key)     |

#### Example: faster-whisper-server (self-hosted on a GPU box)

```bash
docker run --gpus all -p 8000:8000 fedirz/faster-whisper-server:latest-cuda
```

| Field   | Value                             |
|---------|-----------------------------------|
| URL     | `http://gpu-box.local:8000/v1`    |
| Model   | `Systran/faster-whisper-large-v3` |
| API key | (leave blank)                     |

## OCR — read PDFs, images, and screen regions

VoxFox can extract text from documents and images and read it aloud:

- **OCR** opens a file picker. Select a PDF or image (PNG, JPG, BMP, TIFF,
  WEBP). PDFs with a real text layer extract instantly via `pdftotext`; scanned
  PDFs and plain images go through Tesseract OCR automatically.
- **Select** takes a screenshot, shows it full-screen, and lets you drag a
  rectangle around the text you want (Escape cancels). The region is OCR'd and
  read aloud in the active voice.

OCR output has its word-wrapped lines merged into paragraphs (the *Misc*
toggle), so reading flows naturally instead of pausing at every line.

The OCR language follows the active slot. If Slot 1 is Dutch, Tesseract uses
`nld+eng`. Install the matching language pack (`tesseract-ocr-nld`,
`tesseract-ocr-deu`, …).

### From the command line

```bash
voxfox --ocr /path/to/document.pdf
voxfox --ocr /path/to/screenshot.png
```

If VoxFox is running, the text is sent to it and read aloud. If not, it's
printed to stdout — handy for scripts.

### OCR dependencies

`apt` recommends these with the package; to install manually:

```bash
sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-deu \
                 tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-ita \
                 tesseract-ocr-por poppler-utils gnome-screenshot
```

A screenshot tool is needed for **Select** — `gnome-screenshot`, `spectacle`,
`scrot` (X11) or `grim`+`slurp` (Wayland). Add more `tesseract-ocr-<lang>`
packages for extra languages.

## Hover mode

When hover mode is on, the text under your mouse pointer is read automatically —
no need to select first. Useful for skimming lists, menus, or
accessibility-poor websites. It works best on X11 and XWayland; on pure Wayland
it depends on AT-SPI events, which not every app emits, so some windows do
nothing. Toggle with **Hover**, `--hover-toggle`, or your shortcut.

## Always on top

The window floats above other windows. This is done via `wmctrl` and only
applies on X11; under a Wayland session the compositor controls stacking and it
may not apply. VoxFox re-asserts the "above" state shortly after launch and
again whenever it loses focus, so opening another application doesn't push it
behind.

## Command-line interface

VoxFox runs as a single instance with a local Unix socket. When the GUI is
running, these flags forward to it so a shortcut press is instant:

```
voxfox                    # Start the GUI (or focus the existing one)
voxfox --read             # Read the currently selected text
voxfox --pause            # Pause / resume current speech
voxfox --stop             # Stop speaking
voxfox --toggle-slot      # Switch between Language 1 and Language 2
voxfox --hover-toggle     # Toggle hover mode on/off
voxfox --whisper-toggle   # Start/stop dictation (speech-to-text)
voxfox --ocr-select       # Select a screen region and read its text (OCR)
voxfox --ocr <file>       # OCR a PDF or image and read aloud (works without GUI)
voxfox --status           # Print whether VoxFox is running
voxfox --quit             # Ask the running instance to quit
voxfox --setup            # Download Piper + voices + Whisper, then exit
voxfox --verbose          # Enable debug logging
```

## Keyboard shortcuts

VoxFox can register six global shortcuts for you, but never does so
automatically — some desktops already use these keys for other things. Open
**Settings → Shortcuts**, optionally change any combination (click it and press
the keys you want), then choose **Install shortcuts**. They are written to your
desktop on **Cinnamon, GNOME, LXQt, XFCE and KDE Plasma** (on Cinnamon the desktop is
briefly reloaded so the new keys take effect immediately). **Reset to defaults**
restores the originals, and you can always change or remove them later in your
desktop's own keyboard settings.

The six installable actions and their defaults:

| Action          | Command                   | Default   |
|-----------------|---------------------------|-----------|
| Read            | `voxfox --read`           | `Super+Z` |
| Stop            | `voxfox --stop`           | `Super+X` |
| Switch language | `voxfox --toggle-slot`    | `Super+C` |
| Dictate         | `voxfox --whisper-toggle` | `Super+W` |
| OCR select      | `voxfox --ocr-select`     | `Super+A` |
| Read web page   | `voxfox --read-page`      | `Super+V` |

You can also run `voxfox --install-shortcuts` from a terminal. Other commands
(`voxfox --pause`, `voxfox --hover-toggle`) aren't in the installer but can be
bound by hand in your desktop's keyboard settings — every press calls the
running instance via the CLI flags above.

## Reading a web page (experimental)

Select the page's address — `Ctrl+L` in the browser highlights the address
bar — and press `Super+V` (or run `voxfox --read-page`). VoxFox fetches the
page itself and reads the article aloud; the page title appears in the status
line so it is always clear which page is being read. Any selected text
containing a URL works, so a link in an e-mail or document is fine too.

Extraction happens in two stages:

1. The main content is extracted structurally: menus, banners, sidebars,
   footers and scripts are skipped, and a `<main>`/`<article>` section wins
   when the page marks one up. No AI involved, nothing is ever invented.
2. Optionally an **AI (Ollama)** refines what is left, configured under
   **Settings → Web page**: *Filter only* keeps the original sentences and
   strips leftover adverts and snippets of other articles; *Summarize* reads
   a spoken-friendly summary instead.

Stage 2 needs a running [Ollama](https://ollama.com) with a downloaded model
(for example `ollama pull llama3.2`). The URL, an optional **API key** (sent
as a Bearer token, for Ollama behind a reverse proxy on another machine) and
the model name are configurable; *Test connection* lists the models it finds.
If Ollama is unreachable, VoxFox falls back to the stage-1 text.

Notes: the fetch sees the page as an anonymous visitor, so content behind a
login can differ from what the browser shows. Pages that only render with
JavaScript are retried automatically in a headless (invisible) Chromium when
one is installed — Chromium, Chrome, Brave and Edge are detected.
Without a selected URL, VoxFox falls back to reading the focused tab over
AT-SPI (needs the accessibility bus; Chromium needs
`--force-renderer-accessibility`).

## Adjusting speed

Each language slot has its own speed slider (0.5x–2.0x), so you can keep Slot 1
at 1.0x for careful reading and Slot 2 faster for skimming. 1.3x is comfortable
speed-listening for most people once you're used to the voice.

## Interface language

The interface follows **Slot 1's language**: set it to German and the buttons,
tooltips, menus and status messages switch to German; set it to French and
everything switches to French. English, Dutch, German, French, Spanish, Italian,
Portuguese, Chinese, Arabic and Greek ship out of the box. Choosing Arabic also flips
the whole interface to right-to-left. Chinese, Arabic and Greek have Piper
speech voices and work for dictation and OCR too — for OCR install the
matching Tesseract pack (`tesseract-ocr-chi-sim`, `tesseract-ocr-ara` or
`tesseract-ocr-ell`).

Translation files live in `~/.piper/locales/`, one JSON per language. To improve
a translation or add a language: copy `en.json` to `<code>.json`, set
`_meta.name` to the native language name, translate the right-hand side of each
entry (leave the English keys on the left alone), and restart VoxFox. Missing
entries fall back to English, so partial translations work fine.

## Accessibility

Buttons carry accessible names and tooltips, the status line is a live region,
and labels avoid emoji (which some screen readers read out character by
character). Hover-to-read and switching on the accessibility bus (via the
*Set up VoxFox…* window) are described above.

## Dependencies

Installed by the package:

- `python3-gi`, `gir1.2-gtk-4.0` — the GTK4 interface
- `python3-pyatspi`, `at-spi2-core` — hover-to-read

Recommended (enable specific features): `tesseract-ocr` + language packs and
`poppler-utils` (OCR), `xdotool` (typing dictation on X11), `wmctrl`
(always-on-top), `gnome-screenshot` (region select), `python3-pip` (installing
faster-whisper), and audio libraries.

Downloaded per user on first use: the Piper engine and voices, and
`faster-whisper` for local dictation.

## Where things live

| Path                              | Contents                          |
|-----------------------------------|-----------------------------------|
| `~/.piper/`                       | Piper engine and downloaded voices|
| `~/.piper/locales/`               | Interface translation files       |
| `~/.config/voxfox_state.json`     | Your settings                     |
| `~/.config/voxfox_history.json`   | Read/dictation history            |
| `~/.cache/huggingface/`           | Cached Whisper models             |
| `~/.cache/voxfox.log`             | Log file                          |
| `/usr/lib/voxfox/`                | Program code                      |
| `/usr/share/voxfox/locales/`      | Bundled translations              |

## Supported systems

Debian, Ubuntu, Linux Mint and derivatives with GTK4 (via the `.deb`), and
Fedora (via the `.rpm`, tested on Fedora Workstation; other RPM-based
distributions such as openSUSE may need different dependency names and are
untested). X11 gives the full
feature set (hover, always-on-top, region select via `xdotool`/screenshot
tools). Wayland works for the core reading and dictation, but always-on-top and
parts of hover depend on the compositor and may be limited.

## For developers

The code is split into a UI-agnostic backend (the `voxfox_core/` package —
`tts.py`, `stt.py`, `ocr.py`, `ipc.py`, `state.py`, `a11y.py`, `common.py`) and
a GTK4 front-end (`voxfox_gtk.py`, which also holds the CLI). Translations are
plain JSON files under `locales/`, key-aligned across all languages. See
`CHANGELOG.md` for the version history.

Packaging and release helpers live in `packaging/`:

- `VERSION=x.y bash packaging/build-deb.sh` builds the Debian package, and
  `VERSION=x.y bash packaging/build-rpm.sh` the RPM (Fedora). Both mirror the
  same file layout and bundle `locales/` and, when present, `dicts/`.
- The Piper engine download is pinned to `PIPER_VERSION` in `voxfox_gtk.py`
  and verified against the SHA-256 sums in `PIPER_SHA256` before extraction.
  When bumping `PIPER_VERSION`, regenerate those sums by running
  `python3 packaging/pin_piper_hashes.py` on a machine with internet access
  and pasting its output over the `PIPER_SHA256` block.
- `packaging/merge_dict.py` merges community pronunciation submissions (a CSV
  of `taal;woord;uitspraak`) into the bundled dictionaries in `dicts/`.

## Troubleshooting

**"No speech detected" after dictating** — mic muted at the OS level, the wrong
input device selected in the Dictation tab, speaking too softly (Whisper drops
near-silence), or a clip under ~0.3 s.

**Read does nothing / "Nothing selected"** — VoxFox reads the X11 *primary*
selection on X11/XWayland and the *clipboard* on pure Wayland. On Wayland with
an app that doesn't sync the clipboard, copy explicitly (`Ctrl+C`) first.

**Hover doesn't trigger in some apps** — hover relies on AT-SPI events; some
apps (notably Electron ones) emit them sparsely or not at all. Use Read on a
selection instead.

**Select does nothing** — no screenshot tool is installed. Install
`gnome-screenshot`, `spectacle`, `scrot` (X11) or `grim`+`slurp` (Wayland).

**Remote Whisper times out** — the remote backend has a 60-second per-request
timeout. Use a faster model on the server, or make shorter recordings.

**OCR returns gibberish** — the Tesseract language pack for the active slot
isn't installed. Check `tesseract --list-langs`; install e.g.
`sudo apt install tesseract-ocr-nld`.

**Reading pauses oddly / merges things it shouldn't** — toggle *Settings → Misc
→ Merge wrapped lines into paragraphs* off (or on) to match the text you're
reading.

**Everything else** — VoxFox logs to `~/.cache/voxfox.log`; start with
`voxfox --verbose` for debug-level messages.

## Uninstall

```bash
sudo apt remove voxfox
```

Per-user data (settings, history, downloaded voices, cached Whisper models)
lives under your home directory and is left untouched; remove it manually if you
want a clean slate:

```bash
rm -rf ~/.piper ~/.config/voxfox_state.json ~/.config/voxfox_history.json
```

## License

VoxFox is free software under the GNU General Public License v3 (or later).
Copyright (C) 2025 Daniël Vos. See `licence.txt` for the full text.

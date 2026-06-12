# Changelog

All notable changes to VoxFox (GTK4 / Debian package). This covers the GTK4
build; the original Tk version is no longer maintained.

Format loosely follows Keep a Changelog. Dates are left for you to fill in.

## 2.0.5

- Default desktop keyboard shortcuts for Cinnamon and GNOME, registered on
  first start (and on demand via `voxfox --install-shortcuts`):
  Super+Z read, Super+X stop, Super+C switch voice/language,
  Super+W dictation, Super+A OCR region select. Registered once, so changes
  or removals you make in the system keyboard settings are respected.
- Stability fix for Cinnamon: focus/selection events coming from the desktop
  shell itself (cinnamon, nemo-desktop, …) are now ignored, and selection
  events are rate-limited. Querying the shell synchronously while it emits
  events could stall it, which Cinnamon's watchdog answers by restarting into
  fallback mode.
- Much snappier paragraph and sentence transitions while reading: the next
  chunk is now synthesized in the background while the current one plays.
  Previously Piper's synthesis time (roughly half a second to a second) was
  audible as a gap at every paragraph break.
- Portable/VoxMob support folded into the main build: the Piper directory can
  be redirected with the VOXFOX_PIPER_DIR environment variable, and the Whisper
  model cache respects HF_HOME. Without these variables nothing changes.
- Saving settings/history now works on FAT32/exFAT drives (e.g. a VoxMob USB
  stick): file-permission tightening is best-effort there instead of aborting
  the save. Same for the Piper install and data migration.
- Internal cleanup (duplicate import, unused variables/globals); recorder
  errors now include the recorder's exit code in the log.

## 2.0.4

- The window position is now remembered: VoxFox reopens where you left it.
  (X11 only; saved on close and restored on the next start.)
- More reliable hover-to-read in browsers: VoxFox now switches on the desktop
  accessibility stack at startup, the way a screen reader does, so Firefox and
  Chromium-based browsers expose their page content for reading.
- VoxFox now reads the selected item as you move through lists, file managers
  and trees by keyboard or click — following focus and selection, not only the
  mouse pointer.
- Robustness: a window disappearing while it is being read can no longer crash
  VoxFox (stray X errors are handled instead of being fatal).

## 2.0.3

- Housekeeping: removed three unused imports left over from the 2.0 package
  split (`_have` in tts, `app` in ipc, a stray `pyatspi` in a11y). No behaviour
  change.
- Accessibility: the speed and pitch sliders now carry explicit accessible
  names, so screen readers announce them as "Speed"/"Pitch" (translated)
  instead of an unlabelled slider.

## 2.0.2

- Fixed the pitch control: in 2.0.1 it changed the speaking tempo instead of the
  pitch. paplay/aplay read the sample rate from the WAV header and ignore a
  `--rate` flag, so the pitch shift now rewrites the header's sample rate before
  playback (the tempo compensation via Piper's length_scale is unchanged).
  Speed and pitch are now independent, and pitch 0 is byte-for-byte unchanged.

## 2.0.1

- Added a per-voice **pitch** control (Settings → Language 1 / Language 2),
  shown in semitones just below the speed slider: 0 is the voice's natural
  pitch, negative is lower, positive is higher (range -12 … +12). Pitch is
  independent of speaking speed — it is applied by shifting the playback sample
  rate and compensating the tempo through Piper's length_scale, so no extra
  audio tools are required.

## 2.0.0

The 2.0 line is an internal modernisation done in careful, separately
verifiable steps; no user-facing behaviour change is intended.

- **Step 1 — encapsulated runtime state.** The i18n and config module globals
  (active UI language + translation tables, the per-language pronunciation
  dictionary, and the line-merging flag) now live in a single `AppState` object
  in the backend. The public functions (`set_language`, `_`, `available_ui_languages`,
  `set_pronunciations`, `set_merge_lines`, plus a new `merge_enabled()`) delegate
  to it, so behaviour is unchanged.
- **Step 2a — removed cross-module mutation hooks.** The GTK front-end used to
  assign attributes directly on the backend module (`_get_slot_config`,
  `_hover_running`, `LOCALES_DIR`, and a recording stop-event). Those are now
  proper functions (`set_slot_config_provider`, `set_hover_running`,
  `set_locales_dir`, plus `hover_running()`/`locales_dir()` getters) and the
  recording event lives on the window; a dead module-level event global was
  removed. No behaviour change — this is what makes splitting the backend into
  modules (step 2b) safe, since a package re-export would otherwise swallow
  those direct assignments.
- **Step 2b — split the backend into a package.** The single ~2,600-line
  `voxfox_core.py` is now a `voxfox_core/` package with focused modules:
  `common` (logging, paths, `AppState`/i18n, Piper-language tables), `state`,
  `tts`, `stt`, `ocr`, `a11y`, and `ipc`. The public API is unchanged
  (`import voxfox_core` re-exports everything), so the GTK front-end is
  untouched apart from the step-2a accessor calls. The Debian package now ships
  the module directory instead of a single file.
- **Step 3 — XDG Base Directory layout with non-destructive migration.**
  Configuration moves to `~/.config/voxfox/` (state.json, history.json), data
  to `~/.local/share/voxfox/` (locale overrides), and a rotating log to
  `~/.cache/voxfox/voxfox.log`. The Piper engine and voices stay in `~/.piper`
  (large and conventional). On first run `init_storage()` creates the new
  directories and copies any 1.x / Tk-era files forward; originals are left in
  place and an existing new file is never overwritten.
- **Step 4 — OCR paragraphs from layout geometry.** When line-merging is on and
  pytesseract is available, OCR now reconstructs paragraphs from Tesseract's own
  block/paragraph/line structure (via `image_to_data`) instead of guessing wrap
  points from line length. Separate columns land in separate blocks, so
  multi-column and justified text are no longer glued together. The text
  heuristic stays as the fallback (the tesseract-CLI path, or when geometry
  returns nothing), and with line-merging off the raw line-by-line text is
  returned unchanged.

## 1.0.19

- Removed 50 unused translation keys (leftovers from the Tk version) from all
  seven locale files. No functional change; every string still used by the code
  is kept and the locales remain aligned (151 strings each).

## 1.0.18

- Internal cleanup, no functional change: removed dead code (an unused
  pronunciation-test handler and the never-used `compact_mode`/`theme` state
  fields), translated three remaining Dutch log messages to English, and merged
  the two duplicated progress-bar helpers into one shared function.

## 1.0.17

- **No more pausing mid-paragraph.** When reading OCR output (the Select-region
  button) or selected text (e.g. copied from a PDF), lines that are merely
  word-wrapped are now joined into flowing paragraphs, so speech only pauses at
  real paragraph breaks. Hyphenated words split across a line break are
  re-joined; bullet/numbered lines stay separate. A new **Settings → Misc**
  toggle ("Merge wrapped lines into paragraphs", on by default) turns it off for
  line-by-line reading of lists or code.
- **Import / export settings** (back from the old version) under Settings → Misc.
- **Per-word test** in the pronunciation dictionary: each rule has its own ▶
  button, so you can hear a single word instead of the whole list.

## 1.0.16

- **History is back.** The read/dictation history (kept by the backend all
  along, but with no UI since the GTK port) is reachable again from
  **Menu → History**: re-read any past item or copy it to the clipboard, and
  Clear all to empty the list. (Copy rather than re-type: VoxFox stays on top
  and holds focus, so typed text would land in the wrong window — copy lets you
  paste it where you want.)
- **Settings tabs renamed** Slot 1 / Slot 2 → Language 1 / Language 2.
- **More translations.** "Hover" and the history-window labels were still in
  English; a value-level audit (not just key presence) confirmed every
  translatable string is now translated in all seven languages. Remaining
  identical strings are correct cognates or technical terms (CPU, URL:, Menu,
  Stop, Pause, ...).

## 1.0.15

- **Always-on-top fixed.** The window now re-asserts "stay on top" several
  times after launch (to beat a window-title timing race) and again whenever it
  loses focus, so opening another application no longer pushes VoxFox behind it.
  Note: this works on X11 via `wmctrl`; under a Wayland session the compositor
  controls stacking and it may not apply.
- **Translations completed.** Audited every translatable string used in the
  code: 22 strings (button/menu/About/tooltip labels plus the OCR status and
  error messages, which were previously hard-coded in Dutch) were missing from
  the catalogue and fell back to English. They are now translated into all
  seven languages, which are aligned again.

## 1.0.14

- **Pronunciation dictionary.** A per-language dictionary that re-spells words
  before they are spoken (for names, abbreviations and loanwords). Edited under
  Settings → Pronunciation for slot 1's language, with a Test button. Matching
  is whole-word and case-insensitive; rules apply to everything spoken in that
  language (Read, Hover, OCR).
- **Tabbed Settings.** The Settings window is now split into tabs (Slot 1 /
  Slot 2 / Dictation / Pronunciation), each scrollable, so it stays usable on
  small screens.

## 1.0.13

- **Download progress bar.** A progress indicator now appears just below the
  status line while a download runs, so you can see how far along it is. It
  covers Whisper model downloads (the Settings download button and the first
  dictation) and the Piper engine/voices during setup.
- Packaging: the source now lives in `src/`; `build-deb.sh` writes the built
  `.deb` to the project root (so `packaging/` holds only the build scripts);
  `apt install` prints two first-run hints; bilingual `AFTER-INSTALL` notes are
  shipped in the package and bundle.

## 1.0.12

- **Whisper on older NVIDIA GPUs.** Detects the GPU compute capability and uses
  `int8` on Pascal cards (e.g. the Tesla P40) instead of `float16`, which would
  crash or run very slowly. Loading cascades through compute types and falls
  back to the CPU if the GPU can't be used. Documented the CUDA/cuBLAS/cuDNN
  requirement.

## 1.0.11

- Row 1 (Read / Stop / Pause) restored to full width; row 2 stays content-sized
  and centred.

## 1.0.10

- Completed all seven UI languages: the new GTK strings are translated into
  German, Spanish, French, Italian and Portuguese (English at parity).
- Buttons made content-sized and the window more compact (no truncation of
  longer, multilingual labels).

## 1.0.9

- About dialog expanded: author, copyright, a list of shortcut commands and a
  clickable manual link. Added an `APP_VERSION` constant kept in sync with the
  package version.

## 1.0.8

- Window widened so the program name shows in the title bar; the language
  switcher moved out of the title bar into the second button row; tighter
  margins.

## 1.0.7

- Removed emoji from button labels (screen readers read them out as Unicode
  code points). Plain-text labels with tooltips throughout; the download and
  refresh buttons became symbolic icon buttons.

## 1.0.6

- Fixed the UI staying in English: translations are now loaded at startup, the
  interface follows slot 1's language and re-renders live when it changes.
- Accessibility: explicit accessible names and tooltips on every button; the
  status line is exposed as a live region so screen readers announce it.

## 1.0.5

- Accent buttons recoloured to the logo orange (#F26A1F) instead of the desktop
  theme's accent colour.
- Whisper GPU support: Settings → Compute (Auto / CPU / GPU) with NVIDIA
  auto-detection and automatic fall-back to the CPU.

## 1.0.4

- Always-on-top via `wmctrl` (X11); status-line handling improvements.
- Added `wmctrl` and `python3-pip` to the recommended packages.

## 1.0.3

- Added the "Enable accessibility (system-wide)" menu action (sets the GNOME
  toolkit-accessibility bus).
- Hardened accessibility dependencies (`python3-pyatspi` + `at-spi2-core` made
  required).

## 1.0.2

- OCR now works without the `pytesseract`/Pillow Python packages, via a
  `tesseract` command-line fallback (only the `tesseract-ocr` package is
  needed).
- Small UI tweaks (tooltips, default window size).

## 1.0.1

- Packaging fix (no functional code change).

## 1.0.0

- Initial GTK4 release. Full port of the original Tk application to
  GTK4/PyGObject, split into a UI-agnostic backend (`voxfox_core.py`) and a
  GTK front-end (`voxfox_gtk.py`), packaged as a Debian `.deb`.
- Features: read selected text aloud (Piper), Stop/Pause, two language slots
  with an NL/EN switcher, Whisper dictation (local + remote API, model picker
  with download, microphone picker, confirm-before-typing), OCR of a file or a
  selected screen region (X11 + Wayland), hover reading via AT-SPI,
  always-on-top, a first-run setup flow, CLI commands with a single-instance
  lock, and system-fallback locales.
- Carried over earlier backend fixes: shebang on line 1, deep-copied default
  state, atomic state/history writes, and the `--ocr-select` command.

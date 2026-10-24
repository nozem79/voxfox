# How VoxFox is put together

This is a map of the source code for people who want to change VoxFox.
It describes the layout since 6.1.

## Two layers

    src/
      voxfox_gtk.py      launcher: XWayland restart, GTK 4.10 check, then voxfox_ui.app.main()
      quickshot.py       stand-alone region screenshot tool (voxfox-quickshot)
      voxfox_core/       everything that is not the window: speech, dictation, OCR, settings
      voxfox_ui/         the GTK 4 interface

`voxfox_core` never imports GTK. That keeps it testable without a
display: everything under `tests/` exercises `voxfox_core`.

`import voxfox_core as vf` gives the whole public API in one namespace:
`voxfox_core/__init__.py` star-imports every module, and every module
lists what it offers in `__all__`. Names starting with `_` are internal
to their module; nothing outside a module uses them (tests excepted).

## voxfox_core

| Module | What it does |
|---|---|
| `common.py` | Logging, paths (XDG), translations (`app`, `_()`), language tables, `have_command()` |
| `state.py` | Settings file and history: defaults, loading with migration, atomic saving |
| `voices.py` | Piper voices: online catalogue, voices on disk, friendly names, best voice per language, download |
| `textprep.py` | Text before speaking: pronunciation dictionary, chunking, positions within the text |
| `piper.py` | The Piper process kept running between utterances |
| `tts.py` | Speaking: `speak()`, pause, stop, progress, and the workers for Piper and speech-dispatcher |
| `sdengine.py` | speech-dispatcher as second engine (Voxin, espeak-ng, RHVoice ...) |
| `stt.py` | Dictation: recording, the Whisper model, transcription (local or remote) |
| `ocr.py` | Text from images and PDFs (Tesseract), joining wrapped lines |
| `docreader.py` | Text from Word, LibreOffice, RTF and plain text files |
| `documents.py` | The document library and reading positions |
| `textio.py` | The selected text, the clipboard, typing or pasting into other programs |
| `pointer.py` | Mouse position and the window under it (python-xlib or xdotool) |
| `a11y.py` | Hover reading through AT-SPI: text under the mouse, focus, selection and caret events |
| `webread.py` | Reading a web page (experimental) |
| `translate.py` | Translating through Ollama or another OpenAI-compatible server |
| `typespeak.py` | Logic of Type and speak: words, recent sentences, tiles, tile pictures |
| `colorscheme.py` | Which GTK theme gives light or dark |
| `ipc.py` | One running instance, the command socket, and `voxfox --read` and friends |

### State that lives between calls

Module-level state is kept in one small object per module instead of
loose global variables, so it is clear what belongs together and tests
can replace one attribute:

| Object | Module | Holds |
|---|---|---|
| `_speech` | `tts` | the speaking thread, stop/pause events, progress, position |
| `_voice_cache` | `voices` | the downloaded voice catalogue and when it was fetched |
| `_whisper` | `stt` | the loaded model, its name and device, the recorder process |
| `_hover` | `a11y` | hover on/off, last thing said, the event listener, own-window reader |
| `_roles` | `a11y` | AT-SPI role sets, filled on first use |
| `_xlib` | `pointer` | the python-xlib connection |
| `_locales` | `common` | the folder translations are read from |
| `_singleton` | `ipc` | the lock file of the running instance |

A test that replaces a function must replace it in the module that
calls it: `tts._speak_worker` looks up `find_voice_dir` in `tts`, so a
test patches `tts.find_voice_dir`, not `voices.find_voice_dir`.

## voxfox_ui

| Module | What it does |
|---|---|
| `app.py` | The `Gtk.Application`, menu actions, command-line options, `main()` |
| `main_window/` | The small main window (see below) |
| `preferences/` | The Settings window (see below) |
| `typespeak.py` | The Type and speak window, including the tile board and full screen |
| `tiledialog.py` | The dialog for changing one tile |
| `tilepics.py` | Tile pictures: the folder, shrinking to 50 kB, choosing a picture |
| `library.py`, `history.py`, `live.py` | Library, History and Live transcription windows |
| `setup.py` | Setup assistant and installing components |
| `shortcuts.py` | Installing desktop keyboard shortcuts (Cinnamon, GNOME, KDE, XFCE, LXQt) |
| `screenshot.py` | Capturing a screen region for OCR |
| `selfread.py` | Hover reading for VoxFox's own windows (without AT-SPI) |
| `theme.py` | Applying light or dark |
| `common.py`, `widgets.py` | Toolbar button list, icons, small widget helpers |

### main_window/ and preferences/

Both windows are one class built from mixins: each module holds one part
as a plain class, and the window class inherits from all of them. A
method in one mixin can call a method in another through `self`.

    main_window/window.py     VoxFoxWindow: start-up, other windows, quitting
                layout.py     building the toolbar, sizes, tooltips
                status.py     status line, progress bars, active language
                placement.py  window position, staying on top
                reading.py    read, translate, web page, stop, pause, hover
                dictation.py  dictation
                ocr.py        screen region and file OCR

    preferences/window.py         PreferencesWindow: the list of sections, saving
                languages.py      Taal 1 and Taal 2
                pronunciation.py  Uitspraak
                dictation.py      Dicteren
                ai.py             Vertalen en AI
                shortcuts.py      Sneltoetsen
                appearance.py     Weergave
                general.py        Algemeen
                helpers.py        small shared functions

The `do_*` methods of `VoxFoxWindow` are also what keyboard shortcuts
end up calling: `voxfox --read` sends `read` over the socket, and
`voxfox_core/ipc.py` calls `do_read` on the main thread.

## Rules of thumb

- Anything that touches a widget runs on the GTK main thread. Work in a
  thread hands results back with `GLib.idle_add`.
- New user-facing text goes through `_()` and into all files in
  `locales/` (the keys are the English text).
- VoxFox needs GTK 4.10 or newer (`Gtk.FileDialog`, `Gtk.AlertDialog`).
- Packaging copies every folder with an `__init__.py` under `voxfox_core/`
  and `voxfox_ui/`, so new sub-packages need no packaging change.

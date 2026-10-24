## 6.2.0

First release of the 6.2 series: everything from 6.2.0~dev1 to ~dev3
below, plus:

- **Clear list** in Type and speak also removes those sentences from
  History. Sentences said there are stored in History as "Type and
  speak" (with their own icon), so they can be found and removed;
  sentences from 6.1 are matched by their text.
- Removing a tile asks first ("Remove the tile 'Ja'?"); Enter or Escape
  keeps the tile.
- The packages name a maintainer address: Daniël Vos
  <info@voxfox.nl>.

In short, since 6.1.0:

- Pictograms on all ready-made tiles in Dutch, English, German, French
  and Spanish (50 SVG pictures in `icons/tiles/`); a changed 6.1 board
  gets them once.
- Tiles can be dragged to another place while Change tiles is on; the
  board scrolls along at the edges.
- Fixes from a second code review: tile board bugs, the RTF reader
  (quotes, dashes, accents, code pages), size limits when reading
  documents and pictures, a safer Piper and Ollama install, package and
  CI checks, Python 3.10 or newer.

## 6.2.0~dev3

Fixes from a second code review.

Tiles
- A pictogram removed from the ready-made board ("No picture") came
  back once, right after saving. It now stays removed at once.
- Switching language (for example with the shortcut) while a tile
  dialog was open saved the tiles into the other language's board. The
  board is now fixed when the dialog opens.
- "Move earlier/later" with an empty text box no longer lets the tile
  disappear; it keeps the text it had.
- Loading, the one-time pictograms and saving a board moved from the
  window to `voxfox_core.typespeak` (`load_board`, `save_board`), with
  tests.
- Changing the tile pictures folder after a language switch no longer
  proposes a second folder with the name in the other language.
- Enter and Escape no longer interrupt an input method that is still
  composing (Japanese, Chinese, ...) in Type and speak.

Reading documents
- RTF: curly quotes, apostrophes and dashes from Word (`\rquote`,
  `\emdash`, ...) are kept ("zo’n", not "zon"); the fallback after
  `\uN` is skipped ("café", not "caféé"); `\'hh` bytes use the
  document's code page (cp1252 by default), so “ and ” and € come out
  right; pictures, field codes and `{\*...}` groups are not read aloud.
- Word, LibreOffice, RTF and text files have an upper size (64 MB inside
  a .docx/.odt, 32 MB for RTF and text), so a "zip bomb" cannot fill the
  memory. Tile pictures: the size is read from the file header first,
  and a picture is never decoded larger than 1536 pixels.

Installing and packaging
- Piper is only unpacked with a known SHA-256 (it was already pinned for
  all three architectures; now a missing checksum stops the install),
  and with Python's `data` filter for tar files.
- The Ollama installer unpacks and checks the download before it
  replaces the installed copy, so a broken download leaves the old one
  working. Downloads are HTTPS only, also after redirects.
- The .deb refreshes the icon and menu caches also on upgrades and on
  systems without pip; the .rpm uses `python3 -m pip` and says when the
  install failed instead of hiding it.
- A failed copy of `icons/` now stops the package build; CI builds the
  .deb and checks the pictograms are in it, and runs the tests on Python
  3.10, 3.12 and 3.13.
- Python 3.10 or newer (was: 3.9); packages are built with umask 022.
- `packaging/pin_piper_hashes.py` reads the Piper version from
  `voxfox_ui/common.py` again.
- README-deb: supported systems corrected (GTK 4.10: Ubuntu 24.04,
  Mint 22, Debian 13, Fedora 38 or newer).

Smaller
- The history file is checked when read (a damaged file gives an empty
  history instead of an error), and adding to it is done one at a time.
- An error in a shortcut action is logged as an error instead of only
  at debug level.
- Tile picture names use SHA-1 with `usedforsecurity=False` (FIPS).

## 6.2.0~dev2

- Tiles can be dragged to another place while Change tiles is on: drag a
  tile onto the tile whose place it should take. The tile being moved
  fades and the place it goes gets a blue border. Near the top or bottom
  of the board it scrolls along, so a tile can be moved to a place that
  is out of view. Move earlier / Move later in Change tile still work,
  also with the keyboard.

## 6.2.0~dev1

- Pictograms on the ready-made tiles: every tile of the standard boards
  (Dutch, English, German, French and Spanish) has its own picture, on
  the left of the text. The 50 pictures are SVG files in
  `icons/tiles/`, shared by all five languages.
- A board you changed in 6.1 gets the pictograms once: every tile that
  still has its ready-made text and no picture of its own. A picture you
  remove afterwards (No picture) stays removed.
- A pictogram can be moved (Left, Right, Middle), removed or replaced by
  your own picture in Change tile, like any other tile picture.
  "Standard tiles" puts the board back with its pictograms.

## 6.1.0

First release of the 6.1 series: everything from 6.1.0~dev1 to ~dev4
below, with two changes:

- The Type button is hidden by default (also after an update). Type and
  speak is always in the menu; the button can be switched on under
  Settings, Appearance, Buttons.
- Choosing a picture for a tile opens in the folder the previous picture
  came from (also after restarting VoxFox), instead of always starting
  in Pictures.

In short, since 6.0.1:

- Type and speak: a window where you type a text and VoxFox says it
  (Enter), with recently said sentences, word-by-word echo and a large,
  adjustable text size. Also `voxfox --type-speak` and an optional
  keyboard shortcut.
- Tiles: a board of word and sentence tiles to build a sentence
  ("Ik" + "heb" + "dorst"), with colours per kind of word, ready-made
  boards for Dutch, English, German, French and Spanish, and tiles you
  can change, move, remove and add. Each language has its own board.
- Pictures on tiles (icon or photo, left, right or above the text), at
  most 50 kB each and scaled down automatically, kept in a folder you
  choose.
- Full screen (F11). While Type and speak fills the screen the main
  VoxFox window is minimised.
- VoxFox needs GTK 4.10 or newer.
- The code is split into smaller modules, internal functions have
  ordinary names and there are no global variables any more; see
  docs/STRUCTURE.md.

## 6.1.0~dev4

Under the hood; nothing changes in how VoxFox works.

- VoxFox now needs GTK 4.10 or newer (Ubuntu 24.04, Linux Mint 22,
  Debian 13, Fedora 38 or newer). Older versions crashed as soon as a
  dialog that uses Gtk.FileDialog or Gtk.AlertDialog opened; now VoxFox
  says which GTK it found and does not start. The .deb asks for
  gir1.2-gtk-4.0 (>= 4.10), the .rpm for gtk4 >= 4.10.
- The code is split into smaller modules (see docs/STRUCTURE.md):
  - Settings: voxfox_ui/preferences/, one module per section (was one
    file of 2264 lines).
  - Main window: voxfox_ui/main_window/, one module per kind of action
    (was 1435 lines).
  - Speech: voxfox_core/tts.py split into voices.py (catalogue and
    downloads), textprep.py (pronunciation and chunks), piper.py (the
    Piper process) and tts.py (speaking).
  - Hover: voxfox_core/a11y.py split into textio.py (selection,
    clipboard, typing), pointer.py (mouse and windows) and a11y.py.
  - The tile dialog moved from typespeak.py to tiledialog.py.
- Functions one module used from another now have ordinary names instead
  of "internal" ones with a leading underscore (vf._have became
  vf.have_command, vf._clipboard_set vf.clipboard_set, widgets._a11y
  widgets.set_accessible_label, and so on).
- No more global variables: state that lives between calls is kept in one
  small object per module (tts._speech, stt._whisper, a11y._hover, ...).
- Packaging copies sub-packages (.deb, .rpm and Nix).
- 234 tests.

## 6.1.0~dev3

Type and speak, tiles:

- Tiles can have a picture: an icon or a photo (PNG, JPEG, SVG, WebP,
  GIF). Choose it under Change tiles; the picture goes left of the text
  (standard), right of it, or in the middle above it. The text on a tile
  with a picture is a little smaller so both fit.
- Pictures are at most 50 kB. A bigger one is scaled down when it is
  added: icons with transparency stay PNG as long as possible, photos
  become JPEG. Files that only look like pictures are refused.
- The pictures live in a folder of their own. The first time, VoxFox
  asks where that folder should go (standard: the VoxFox documents
  folder) and makes it ("Tegelafbeeldingen" in Dutch). It can be changed
  later under Settings, General; the pictures are copied along.
- A tile only stores the picture's file name; the name comes from the
  picture's contents, so the same picture used on several tiles is
  stored once.
- 234 tests (9 more).

## 6.1.0~dev2

Type and speak:

- Tiles (button Tiles at the top of the window, on or off). The text box
  shrinks to about two lines and the rest of the window is a board of
  tiles. Pressing "Ik", "heb", "dorst" builds "Ik heb dorst"; Speak or
  Enter says it. Each tile is said when pressed (can be switched off).
  - Ready-made boards for Dutch, English, German, French and Spanish
    (other languages get the English one), with example sentences at the
    top and colours per kind of word, as on many communication boards:
    people yellow, actions green, describing words blue, things and
    feelings orange, social words pink, questions purple.
  - Change tiles: click a tile to change its text or kind, move it
    earlier or later, or remove it; New tile adds one; Standard tiles
    puts the ready-made board back (after asking). Each language keeps
    its own board, so switching language switches the board.
  - Remove word takes the last word off the sentence. After speaking,
    the next tile starts a new sentence.
  - A-/A+ change the tiles too.
- Full screen (button at the top right, or F11). While the window is in
  full screen or maximised, the main VoxFox window is minimised, so it
  does not sit on top; it comes back when the window leaves full screen,
  is made smaller again or is closed.
- The window's buttons moved from the title bar into the window, so they
  stay reachable in full screen.
- 225 tests (7 more).

## 6.1.0~dev1

- New window: Type and speak (button Type, or in the menu). Type a text
  and press Enter: VoxFox says it with the voice of the current language.
  Shift+Enter starts a new line, Escape stops. For people who cannot
  speak (or not right now), and to hear how a text sounds.
  - After speaking, the text stays selected: typing starts a new text,
    Enter says the same one again. Optionally the box is emptied instead.
  - Select part of the text to say only that part.
  - "Say each word while typing" (off by default) says every word as it
    is finished, once, also when a comma or full stop follows it.
  - Said earlier: the last 10 sentences, newest first. Click one to say
    it again, or the pencil to put it back in the box. Kept between
    sessions; Clear list empties it.
  - A-/A+ (or Ctrl+plus/minus) for the text size, and a language button
    in the title bar.
  - Also `voxfox --type-speak`, and a shortcut you can set under
    Settings, Shortcuts (none by default).
- The Type button is shown by default, also after an update; it can be
  hidden under Settings, Appearance, Buttons.
- Translated into all 23 languages. Dutch "Speak" is now "Uitspreken".
- 218 tests (11 more).

## 6.0.1

First release of the 6.0 series; it contains everything from 6.0.0~dev1
to 6.0.0~dev8 below (6.0.0 itself was never released), plus:

- New Dictate icon: a microphone next to lines of text. The old one (a pair
  of lips) looked like a plain oval at button size.
- Nix: speech-dispatcher can be used on NixOS too (`withSpeechd`, on by
  default). nixpkgs has no python3Packages.speechd; the Python client
  that ships inside the speechd package is put on PYTHONPATH. VoxFox
  also looks for speech-dispatcher modules next to the speech-dispatcher
  program, not only in /usr, so the Pied check works outside /usr.
- Nix: the VoxFox icons were no longer found in the Nix package. The
  6.0.0~dev3 fix for running from a source checkout looked for icons/ two
  levels up; the Nix package puts it one level up. Both are searched now.
- 207 tests (1 more).

In short, since 5.0.7:

- Speech-dispatcher as a second speech engine per language slot, next to
  the built-in Piper (Voxin, espeak-ng, RHVoice...), including a fix for
  modules hidden by Pied's speech-dispatcher config.
- A voice preview in the settings, in the slot's own language.
- One menu instead of a menu plus a gear; Settings reorganised as a list
  of sections with technical options under "Advanced"; languages shown in
  their own language; readable voice names; plain explanations of the
  dictation models; light / dark / follow the system.
- Main window: short button names, plain tooltips with their shortcut,
  Read that turns into Pause / Resume, a reading progress bar, a blinking
  button while dictating, and a "bigger buttons" step in the setup
  assistant.
- Hover reading now works on VoxFox's own windows, menu and settings, and
  reads the item that is actually under the pointer.
- 206 tests.

## 6.0.0~dev8

Hover reading in VoxFox's menu and settings: the right item, on time

- In the settings, hovering read the section ABOVE the one under the
  pointer. The Settings window gets its title bar from the window manager
  (the main window draws its own), and xdotool's getwindowgeometry counts
  that title bar into the window's position, so every position was one
  title bar too high. Window positions now come from the X server directly
  (python-xlib); xdotool remains only as a fallback.
- With hover on, AT-SPI focus and selection events from VoxFox's own
  windows were answered by asking VoxFox itself over AT-SPI -- from its
  own main thread, which then had to wait for itself. The window stalled
  and speech lagged behind the pointer. Those events are now ignored;
  keyboard focus inside VoxFox (Tab, arrow keys, menu items under the
  pointer) is read directly with GTK instead, so menu items are spoken the
  moment the pointer reaches them.
- An element that LOSES focus or selection also sends a focus/selection
  event (with detail 0); that one was read too, which could announce the
  item just left. Only gaining focus is read now. This applies to every
  program, not only VoxFox.
- 206 tests (2 more). Also run in the real program with a real AT-SPI bus
  and hover switched on normally, with and without a window manager,
  several times: every menu item and every settings section read
  correctly, nothing read from the item next to it.

## 6.0.0~dev7

Hover reading over VoxFox itself

- Hovering over VoxFox's own buttons, menu and settings said nothing. Hover
  reading asks AT-SPI which element is at a screen position, and GTK 4
  (which VoxFox uses) cannot answer that: it reports positions relative to
  its own window. Reproduced with a plain GTK 4 window: only the top
  button at the very top-left of the screen was found, and nothing at all
  once the window was moved. Worse, the search could then fall through to
  a window lying behind VoxFox and read that instead.
- VoxFox now reads its own windows directly with GTK: buttons and menu
  items by their text, icon-only buttons by their description (the menu
  button says "Menu"), dropdowns by their current choice, the list of
  settings sections, fields and sliders.
- It reads only the VoxFox window that is actually on top under the
  pointer: a window of another program covering VoxFox, or the settings
  window over the main window, is never read through. Under a window
  manager this uses python-xlib (already a recommended package) to
  recognise the frame around a window.
- Other programs are read exactly as before. Other GTK 4 programs have the
  same AT-SPI limitation; that is not changed here.
- 204 tests (3 more). Also run in the real program with a real AT-SPI bus,
  with and without a window manager: main window buttons, the menu button
  and menu items, the settings sidebar, a dropdown, a button, the settings
  window over the main window, a foreign window over VoxFox, and the hover
  loop itself speaking "Stop".

## 6.0.0~dev6

Main window

- Short, plain button names: Dictate (was Speak), Mouse (was Hover),
  Screen (was Select), File (was OCR). In Dutch: Dicteren, Muis, Scherm,
  Bestand.
- Tooltips say in an ordinary sentence what a button does, followed by
  its keyboard shortcut when it has one: "Reads the text you selected
  aloud (Super+Z)". No more "AT-SPI" or "OCR" in them.
- The Read button becomes Pause while VoxFox is reading and Resume while
  paused, so the separate Pause button is hidden by default on new
  installs (it can still be switched on under Settings -> Appearance; an
  existing setup keeps its buttons as they were). The Read shortcut is
  unchanged: it always reads the current selection.
- A thin bar under the buttons shows how far VoxFox has got in a longer
  text (from about 300 characters).
- While dictating, the red Stop button's icon blinks, so a microphone that
  is still on is hard to miss.
- The status line names the voice by its short name ("Alex") instead of
  the file name.

Setup assistant

- New step "Bigger buttons and text": a switch that sets the window to
  125%. The same choice remains under Settings -> Appearance.

- 201 tests. Also run in the real program on a virtual display: the
  labels, the tooltips with their shortcuts, Read -> Pause -> Resume ->
  Read, the reading bar, the dictation button and the setup switch.

## 6.0.0~dev5

- Settings -> Appearance has a new choice "Light or dark": Same as the
  system (the default), Light or Dark. It changes only VoxFox, and applies
  straight away and at every start. Linux Mint, Yaru and similar themes
  come as a light and a dark theme side by side ("Mint-Y-Aqua" and
  "Mint-Y-Dark-Aqua"); VoxFox switches to the matching sibling when it is
  installed, and otherwise asks GTK for the theme's dark variant. A dark
  theme without a light sibling falls back to GTK's own light theme.
- The Settings menu item no longer has a keyboard shortcut. Its label
  ("Control+,") did not fit and made the item hard to read. Quit keeps
  Ctrl+Q.
- 201 tests (8 more, for picking the light or dark theme).

## 6.0.0~dev4

- Switching a slot to another language now picks the best voice for it:
  VoxFox's own default voice for that language when it is downloaded,
  otherwise the best downloaded voice (the language's home region first,
  then the highest quality), otherwise the default voice to download.
  Before, the first downloaded voice in alphabetical order won, which for
  Dutch could be a very-low-quality Flemish voice.
- The documents folder moved from Appearance to General.
- 193 tests (5 more, for the voice choice).

## 6.0.0~dev3

One menu

- The title bar has a single menu button instead of two (a gear for
  Settings next to the menu). Settings is the first item; then Library,
  History and Live transcription; then Setup assistant and About VoxFox;
  Quit on its own at the bottom. The narrow button column also has just
  the one menu button now.
- "Set up VoxFox…" is now called "Setup assistant…", so it is no longer
  confused with Settings.
- Shortcut, shown in the menu: Ctrl+Q quits. (6.0.0~dev3 also had Ctrl+,
  for Settings; removed in dev5.)

Settings, reorganised

- A list of sections on the left replaces the nine tabs along the top,
  three of which only appeared after clicking an arrow: Language 1,
  Language 2, Pronunciation, Dictation, Translation and AI, Shortcuts,
  Appearance, General. A language section shows its language in the list
  ("Language 1: Nederlands") and follows a change straight away.
- Languages are shown in their own language ("Nederlands", "Deutsch")
  instead of in English. Saved settings are unchanged.
- Piper voices have readable names: "Alex (NL, medium quality)" instead of
  "nl_NL-alex-medium". The announcement when switching language uses the
  short name too.
- Dictation: each model has one plain sentence saying what it is good for
  and how big it is. Compute device, maximum recording length and backend
  are under "Advanced", closed by default.
- Translation and Web page are one section, since both use Ollama.
  The model, installing Ollama and the model suggestions come first; the
  server address, API key and connection test are under "Advanced: server
  and API key".
- Interface is now called Appearance, Misc is now General.

Fixes

- The "Install speech recognition" button covered the status text next to
  it; it has its own row now.
- Some settings groups had no inner margin, so their text touched the
  frame; every group now has the same margin.
- Started straight from a source checkout, VoxFox looked for its icons in
  src/icons instead of icons/ and showed broken-image icons. The installed
  packages were not affected.

Tests

- 188 tests. Also run in the real program on a virtual display: the menu
  items and their shortcuts, every settings section, choosing a language
  and a voice by their new names (the right Piper key is stored), the model
  explanation, the Advanced sections, and the speech-dispatcher section
  with a Pied configuration and a spoken preview.

## 6.0.0~dev2

Voice preview

- Settings -> Language 1/2 has a Preview row: a text field and a Play
  button that speak with the slot's current engine, voice, speed and
  pitch. The text starts as "This is a sample voice. Does this sound
  good?" in the slot's language (all 23 languages), can be changed, and
  follows the language until you type your own. Enter in the field plays
  too; Play becomes Stop while speaking.

Speech modules hidden by Pied

- Pied (the Piper voice manager) replaces ~/.config/speech-dispatcher/
  speechd.conf with a file that names only its own "piper" module. When a
  speechd.conf names modules, speech-dispatcher loads only those, so
  espeak-ng, Voxin and every other installed module disappear -- for every
  program, Orca included. Pied's module also offers a single voice
  ("Piper"); Pied switches voices by rewriting its config.
- VoxFox now notices this and names the installed modules that are hidden.
  "Make them available" adds AddModule lines for them to the end of that
  file, saves a copy of the original next to it first, keeps Pied's lines
  and marker (so Pied leaves the file alone), and restarts
  speech-dispatcher so the modules appear.
- For Piper voices, VoxFox's own Piper engine remains the better choice:
  every installed Piper voice is selectable there.

Fixes

- Connecting to a speech-dispatcher that accepts the connection but never
  answers no longer blocks forever; VoxFox gives up after 5 seconds. Before,
  this could stop all speech until VoxFox was restarted.
- A long status message in the language settings no longer makes the
  settings window wider than the screen.

Tests

- 186 tests (10 more): the hung-server case, finding installed modules,
  detecting Pied's config and adding the hidden modules. Also run against a
  real speech-dispatcher with Pied's generated config: only "piper" was
  listed before, espeak-ng and openjtalk appeared after the button, and the
  preview spoke through espeak-ng.

## 6.0.0~dev1

Speech-dispatcher as a second speech engine

- Each language slot can now speak through speech-dispatcher instead of
  Piper. Settings -> Language 1/2 has a new "Speech engine" choice: Piper
  (built-in, the default) or Speech-dispatcher, followed by the module
  (voxin, espeak-ng, rhvoice...) and its voices for the slot's language.
  This makes every synthesizer with a speech-dispatcher module usable from
  VoxFox, including commercial voices such as Voxin that VoxFox cannot
  ship itself.
- The slot's language still drives dictation, OCR and the interface
  language; only the voice changes. Speed, pitch and the pronunciation
  dictionary apply to both engines.
- Reading works the same as with Piper: documents remember their place,
  reading can start halfway, the skip buttons work, and pause stops the
  current piece of text and says it again from its start on resume.
- Only VoxFox's own speech is cancelled when you stop; other programs
  using speech-dispatcher (Orca) are left alone. A piece of text that
  another program interrupts is said again, at most three times.
- If speech-dispatcher restarts or crashes while reading, VoxFox
  reconnects once and continues; if it stops answering altogether,
  reading stops instead of waiting forever.
- The choice only appears when python3-speechd is installed. A slot set to
  speech-dispatcher on a machine without it speaks with its Piper voice.
- Packaging: python3-speechd is a recommended dependency of the .deb and
  .rpm. The Nix package does not include it yet, so the choice does not
  appear there.

Tests

- 176 tests (25 more): the speech-dispatcher engine and its worker against
  a stand-in for the python3-speechd client.
- Also run against a real speech-dispatcher 0.12 with espeak-ng: reading a
  document to the end, pause and resume, stop, starting halfway, and
  killing speech-dispatcher mid-sentence. Not tested with Voxin itself.

## 5.0.7

Dictation broke on fresh installs

- Dictation failed with "Transcribe error: open() got an unexpected keyword
  argument 'metadata_errors'" on any machine where faster-whisper had been
  installed recently, FoxOS included. Cause: faster-whisper decodes audio
  files with PyAV and calls `av.open(..., metadata_errors="ignore")`; PyAV 19
  removed that argument, while faster-whisper 1.2.1 (the newest release) still
  only requires `av>=11`, so a plain `pip install faster-whisper` pulls in a
  PyAV it cannot use.
- VoxFox now hands Whisper the recording as an array of samples instead of a
  file path (it records 16 kHz mono 16-bit, which is exactly what Whisper
  wants), and faster-whisper never calls PyAV for an array. Dictation and
  live transcription therefore work whichever PyAV is installed, including
  on machines that already have the broken combination: updating VoxFox is
  enough. A WAV in any other format still goes by path, and its error now
  names the fix.
- Every install path (first-run setup, the Install speech recognition
  button, the .deb and .rpm scripts) now also installs `av<19`.
  If you set up dictation by hand: `pip install "av<19"`.

Ollama install button

- Settings -> Translate & read now has an **Install Ollama** button for
  people who want local translation but have no Ollama yet. It appears only
  when the URL points at this computer and nothing answers there; it asks
  for confirmation, then for your administrator password (through pkexec,
  with a named prompt rather than a generic "run a program as root" one),
  and shows download progress. Afterwards the existing "Pull" buttons
  fetch a model. Until now VoxFox never installed Ollama and could only
  talk to one you had set up yourself.
- It deliberately does NOT run Ollama's own install.sh. Reading that
  script: when it finds an NVIDIA card without the proprietary driver it
  adds NVIDIA's package repository and installs the cuda-drivers stack
  (DKMS, kernel headers, sometimes a reboot), and for an AMD card it
  downloads a separate ROCm bundle. Changing someone's graphics drivers
  because they pressed a translation button is not what the button
  promises. VoxFox's helper (/usr/lib/voxfox/install-ollama.sh) does only
  what Ollama documents as its manual install: unpack the release into
  /usr, create the ollama user and a systemd service. Translation models
  run fine on the CPU; anyone who wants GPU acceleration can run Ollama's
  own script afterwards, knowing what it does.
- Missing curl, zstd or pkexec is reported before anyone is asked for a
  password. Where there is no automatic route (no pkexec, no packaged
  helper) the dialog shows the terminal command instead. On NixOS the
  button is replaced by a pointer to `services.ollama.enable = true;`.
- Packaging: the .deb and .rpm ship the helper and its polkit policy;
  curl, zstd and polkit are now recommended dependencies.
- Run for real on one machine: the install went through ollama.com,
  PolicyKit and systemd and Ollama was installed afterwards. The rest was
  tested against stand-ins: the helper's download, unpack, user and
  service steps ran against a stand-in release with the system-changing
  commands stubbed, the failure paths (bad download, corrupt archive,
  missing binary, missing tools) were exercised, and the settings page was
  run under a virtual display.

The Ollama install seemed to hang

- On that first real run the progress bar kept saying "Installing Ollama..."
  although the installation had finished. Four problems that produce exactly
  that were found by reproducing them against stand-ins, and all four are
  fixed:
  - The text was set once and never changed, and the bar stopped moving as
    soon as a download percentage had been seen. The bar now follows what
    the installer is doing: Downloading (with a percentage), Installing,
    Starting, Waiting for Ollama to start, and keeps moving during every
    phase except the download.
  - After the installer finished, VoxFox waited for the Ollama server to
    answer for up to 12 tries of 10 seconds each, still showing "Installing".
    A server that accepted the connection but never answered could keep the
    page busy for two and a half minutes. The wait is now capped at 30
    seconds in total (a single check is at most 2 seconds).
  - VoxFox read the installer's output until the pipe was closed, not until
    the installer had exited. A program the installer left running in the
    background (for example when a service start leaves a process behind)
    held the pipe open and delayed the end by as long as it lived. VoxFox now stops reading
    once the installer has exited and nothing more is waiting.
  - When Ollama was installed but not answering yet, the page re-checked
    and could hide the install button without saying anything. It now always
    ends with a clear message: "Ollama installed. Pick a model below and
    press Pull.", or, if the server is not up within 30 seconds, "Ollama is
    installed but not running. Start it with: systemctl start ollama".
- list_models() takes an optional timeout (default 10 seconds, as before).

Keyboard shortcuts that quietly reset

- On Cinnamon (and GNOME), the shortcut for switching voice (Super+C)
  could silently revert to the desktop's own binding after a restart or
  resuming from standby, and VoxFox never noticed because it deliberately
  does not reinstall shortcuts on its own. While running, VoxFox now checks
  once a minute that the shortcuts it installed still point at VoxFox and
  puts them back if the desktop reset them. A key you rebound yourself in
  the desktop's keyboard settings is left alone: only a slot that vanished
  or lost its command counts as a reset. KDE, XFCE and LXQt are untouched
  (they read a file once at login instead of keeping a live setting).

Tests

- 151 tests (48 more): the Ollama decisions, the installer's output
  handling against stub pkexec/helper scripts (including a helper that
  leaves a child process holding its output, a server that never answers,
  and a late-starting server, all with a fake clock), and a check that the
  polkit policy is bound to the exact path the code runs.

## 5.0.6

A Nix/NixOS package: `flake.nix`, `default.nix`, and `packaging/nix/`.
Untested against a real Nix installation (none was available while
writing it) -- see `packaging/nix/NIXOS.md` for a build checklist and
the couple of package-name details worth confirming on a real machine
before relying on it.

A second, independent review of the 5.0.6 changes above found five more
issues (all confirmed by reproducing them before fixing, the same standard
as the first pass; one of its own claims -- that the checksum-mismatch fix
had no test -- turned out to be already covered and is noted as such
rather than acted on).

- Fixed: downloading a Piper voice failed on RHEL/Fedora systems running
  in FIPS mode. hashlib.md5(), used here purely as a checksum and not for
  anything security-sensitive, raises under FIPS unless told so
  explicitly.
- Fixed: quitting VoxFox within half a second of the last keystroke into
  a debounced settings field (an API key, a server address) could discard
  that edit. Closing the Settings window now flushes any pending save
  immediately.
- Fixed: a symlinked or wrong-owner runtime directory now gets its own
  clear message at startup, instead of being reported as "VoxFox is
  already running" with the real reason visible only in the log --
  a dead end for a screen reader user with no other feedback channel.
- Fixed: on a pure Wayland session with no XWayland, hover mode's
  pointer-position check tried a fresh Xlib connection on every single
  poll (about 6-7 times a second) before falling back to xdotool. A
  missing $DISPLAY is now recognised as permanent and remembered, while a
  connection that merely breaks is still retried, since the server could
  come back.
- Fixed: a genuine pointer position of exactly (0, 0) read via Xlib was
  treated the same as a failure and triggered a needless xdotool fallback
  call -- a leftover of xdotool's own design, where (0, 0) doubles as
  both a real reading and "it didn't work".
- Three more reads of a JSON/text file without an explicit encoding=,
  beyond the ones already fixed above, found by scanning every open()
  call in voxfox_core rather than trusting either review's list as
  complete.
- Added `--strict-markers` to the pytest configuration and 4 more tests
  covering the Xlib fixes above (103 tests total). A suggestion to also
  enforce `ruff format` in CI was not taken: the existing ~14,000 lines
  were never written against ruff's formatter, so turning that on now
  would fail immediately on pre-existing style rather than catching a
  real regression, and reformatting the whole codebase in one pass is a
  separate, much larger piece of work than this review round.

An external code review of the whole codebase, and everything it found
that held up under verification (each claim was checked against the real
code and reproduced before being fixed; two review claims turned out to be
imprecise -- a wrong file citation and an inexact comparison -- corrected
during verification rather than taken at face value).

Crashes and data exposure

- Fixed a crash: a pronunciation entry could silently stop VoxFox mid-read
  when the recognised text contained certain non-ASCII capital letters
  (confirmed with Turkish dotted İ) that don't case-fold symmetrically.
  The failure happened inside the speech worker thread, so reading just
  stopped with no error shown.
- Exporting settings no longer leaves the translation service's API key in
  the file. The export already scrubbed the Whisper and web-reading keys;
  the translation one was added later and had been missed.
- The suggested local-translation-model descriptions now update when you
  change the interface language, instead of staying in English forever
  (they were translated once at import time, before the language was
  known).

Security hardening

- Downloaded Piper voices are now verified against the checksum Piper
  publishes for each file, the same way the Piper engine binary itself
  already was.
- A symlink or wrong-owner runtime directory now stops VoxFox from
  starting its IPC socket or its instance lock there, instead of only
  logging a warning and proceeding anyway.
- Every user-configurable server address (remote Whisper, translation,
  and web-page-reading endpoints) now rejects non-http(s) URLs before
  making a request, closing off file:// and similar schemes a stray
  character could turn a typo into.

Performance

- Checking whether a command-line tool is installed no longer spawns a
  "which" subprocess on every call; the small, stable result is cached.
  This alone touches roughly three dozen call sites, several in paths
  used every time text is read aloud.
- Reading the current text selection could block the interface for
  several seconds (several clipboard tools tried in turn, each with its
  own timeout); it now happens off the main thread in all three places
  that read a selection.
- Hover mode's mouse-position check, which runs about six times a second
  while hovering is on, no longer has to start a new xdotool process each
  time on systems with python3-xlib installed; it falls back to the
  previous behaviour automatically when that isn't available.
- Removed three redundant module imports from a function that walks the
  accessibility tree recursively.

Smaller fixes

- A corrupted or unreadable settings file is now preserved (renamed with
  a .bad suffix) and the failure logged, instead of being silently
  replaced with defaults on the next save.
- Typing into an API-key or server-address field in Settings no longer
  writes the whole settings file to disk on every keystroke; saving is
  now debounced.
- Image file handles opened for OCR are now closed explicitly rather than
  left for garbage collection.
- Moving the document library to a new folder now uses the standard
  library's own cross-filesystem move instead of a hand-rolled,
  text-mode-only fallback.
- A few Dutch strings printed by the command-line OCR mode, mixed in with
  otherwise-English output, are now translated like everything else.
- Fixed a variable name in the IPC server that shadowed the translation
  function.
- Removed a duplicate dictionary key (harmless -- both entries had the
  same value) in the OCR language table, found by adding a linter.
- Removed ten internal names from voxfox_core's public export lists that
  were never meant to be used from outside their own module (two more
  such names stay, since dozens of call sites across the UI layer
  genuinely depend on them).

Testing

- Added a pytest suite (99 tests) covering voxfox_core's pure,
  GTK-free functions: text chunking and reading positions, document
  reading (.docx/.odt/.rtf/.txt), the document library, pronunciation
  replacement, settings migration, and every fix above that could be
  meaningfully tested without a live desktop.
- Added a GitHub Actions workflow that runs the linter and the full test
  suite on every push and pull request.

## 5.0.5

Fedora installation conflict

- The bundled screenshot helper is now installed as
  /usr/bin/voxfox-quickshot instead of the generic /usr/bin/quickshot.
  On a Fedora test machine, installing VoxFox's RPM failed outright
  because an unrelated package already installed there also owned
  /usr/bin/quickshot. Beyond fixing that specific conflict, claiming a
  generic name on the system PATH always carried a quieter risk: if some
  other package with the same name got installed first, VoxFox could end
  up running that program instead of its own.

Code review fixes

- A footnote or a margin comment in an .odt file no longer leaks into the
  middle of the sentence it is anchored to, and is no longer read twice.
  Both are now skipped entirely, the same choice already made for headers,
  footers, comments and footnotes in .docx.
- Pronunciation replacements are cached instead of being recompiled for
  every chunk of every document. Applying them per chunk (rather than once
  for the whole text) was needed to keep saved reading positions accurate;
  caching removes the extra cost that came with doing it that way -- about
  a 7x speed-up on a realistic pronunciation dictionary, measured across
  the roughly 500 chunks a longer document produces.
- Removed a dead constant in the new document reader that duplicated,
  and could have drifted from, the file-type list actually used to decide
  which files VoxFox explains it cannot open.

Startup crash on NVIDIA graphics cards

- VoxFox now uses GTK4's software (cairo) renderer instead of the default
  OpenGL one. On NVIDIA's proprietary driver, GTK4's GL renderer talks to
  the X Present extension in a way that can throw a BadDrawable error
  during startup, which GDK treats as fatal -- even with VoxFox's own
  non-fatal X error handler installed, something in GL context setup
  appears to save and later restore the handler that was active before it,
  undoing the override. Confirmed on an RTX 3090. VoxFox's interface is a
  plain toolbar with no need for GPU-accelerated drawing, so there is no
  downside to always using the software renderer.

Reading documents, not just PDFs and photographs

- VoxFox can now open and read Word (.docx), OpenDocument (.odt), RTF and
  plain-text (.txt, .md) files, alongside the existing PDF and image
  support. The "OCR" button opens the same file dialog as before, now also
  listing document formats.
- Documents keep their own paragraph structure, since the file format
  states it directly (unlike a scanned page, where paragraph breaks have
  to be guessed at). The OCR line-merging and sentence-rejoining logic --
  built to repair the ambiguous line breaks of a scan -- is not applied to
  them, so a real short paragraph or list item is never fused into its
  neighbour.
- .docx and .odt are read with Python's standard library only (no new
  package dependency): both formats are zipped XML under the hood.
- The old binary .doc format (Word 97-2003) and WordPerfect files are
  recognised but not read; VoxFox explains why and suggests saving as
  .docx, .odt, or plain text instead.
- Every opened document, of any of these types, is filed in the Library
  exactly like an opened PDF or image: with its own reading position, its
  own entry, never merged with an earlier one.

## 5.0.4

Dictation on FoxOS and other fresh installs

- Downloading a model works on systems that set HF_HUB_OFFLINE=1
  system-wide, such as FoxOS. A model already on disk is loaded strictly
  from disk; a missing one is fetched with the offline switch lifted for
  that call only.
- Models are looked for both in the configured location (HF_HOME) and in
  the user's own cache, and are downloaded into whichever is writable. A
  distribution can ship models under /usr and a user can still add their
  own without needing write access there.
- When faster-whisper itself is missing, the Dictation tab shows an
  Install button that installs it for your user account, with a progress
  indicator. The old hint told you to run pip by hand, which Ubuntu 24.04
  and everything built on it refuses (PEP 668).
- The package's post-install step installs the dictation libraries
  system-wide when there is no interactive user -- which is the case
  inside an image build such as FoxOS. Previously they went to /root,
  where the person who later logged in never saw them.

## 5.0.3

Reading PDFs and documents laid out in text boxes

- PDFs are read as flowing paragraphs instead of line by line. The wrap
  width is estimated from the median length of running-text lines rather
  than the longest line, so a table row, header or footer can no longer
  make every ordinary line look like the end of a paragraph. pdftotext no
  longer runs with -layout, which padded lines with spaces to imitate the
  printed columns.
- Documents made of separate text boxes -- proposals, brochures, slide
  exports -- no longer stutter. Short fragments are packed back together
  up to the normal chunk size, and a sentence broken across a box or page
  boundary is rejoined when the first part does not end like a sentence and
  the second starts in lower case. Bullets, numbered items, headings and
  paragraphs of ordinary length keep their pauses.
- A word hyphenated across a page break is joined without the hyphen.

Library

- A document read to its end is marked as finished and starts from the
  beginning next time. Positions are also saved when speech ends for any
  other reason: the hotkey, the command line, or speech replaced by
  something else.
- Pronunciation replacements are applied per chunk at synthesis time, so
  saved positions always refer to the document's own text.
- The Library refreshes its list when playback stops or moves on, so the
  percentages never show a stale number, and its empty-state message says
  files you open are kept there.

Also

- quickshot's X11 detection no longer depends on the GdkX11 typelib.
- Old settings files get the stay-on-top and documents-folder keys filled
  in on load.

## 5.0.2

- Only files you open end up in the Library. Scanning a region of the
  screen goes to the History alone, as it did before: a scan is a one-off
  look at something, not a document to come back to.
- A document opened from a file is named after that file instead of after
  its first line of text.

## 5.0.1

- python3-pyatspi is a recommendation instead of a requirement. On Pop!_OS
  24.04 the newer gir1.2-atspi-2.0 conflicts with the python3-pyatspi in
  the archive, which made VoxFox impossible to install there. Without it
  everything works except Hover, which needs AT-SPI.

## 5.0.0

The window can now stay above other windows on Wayland. Wayland itself has
no always-on-top protocol, so VoxFox restarts as an XWayland client, where
the compositor does honour the request. Confirmed on KDE Plasma and GNOME.
A new setting under Interface turns this off; it is read at startup, so a
change takes effect the next time VoxFox starts. Without XWayland, VoxFox
keeps its Wayland window rather than failing to start.

Also:
- Remembering the window position now works on Wayland too, which was not
  possible before.
- A saved window position that falls outside every connected monitor is
  ignored and forgotten, instead of putting the window out of reach.
- On Wayland, a dictation is always shown for confirmation first. Text
  cannot be typed into another application there, so it goes to the
  clipboard; the setting is switched on and greyed out, and the stored
  preference is kept for X11 sessions.
- quickshot now covers the whole desktop on Wayland instead of just one
  monitor, so a selection may cross from one screen to the next.
- On X11, region selection for OCR uses maim or scrot again, with
  quickshot only as a last resort. quickshot works around a Wayland
  restriction that does not exist on X11, where dragging happens on the
  live screen with no capture step in between.
- Text captured with OCR is now kept as a document. A new Library window,
  next to History, lists them with how far they have been read, and offers
  continue, start over and delete. Pausing or stopping records the place;
  a document read to the end starts from the beginning next time.
- Every OCR run is a separate document; the same page scanned twice gives
  two documents.
- Documents are plain .txt files in a folder you choose under Settings,
  by default a VoxFox folder inside your Documents folder. Changing the
  folder takes the existing documents and their positions along.
- Reading positions are character positions in the text, so they keep
  pointing at the right sentence even if the way text is split for speech
  changes later.
- OCR text now goes through the "merge wrapped lines" setting as well, so
  a scanned paragraph is read as a paragraph instead of a stack of short
  lines.
- Each document in the Library has one play/pause button, plus skip back
  and skip forward buttons that move thirty seconds at a time, scaled to
  the voice's speaking speed.
- Speaking can now start at any character instead of snapping to the start
  of the surrounding chunk, which is what makes small jumps possible. The
  starting point is nudged back to a word boundary.
- Twenty-one new interface strings in all 23 languages.

## 4.0.5

OCR-select on Wayland now tries, in order: quickshot (bundled as
/usr/bin/quickshot -- captures the screen non-interactively, then handles
region selection itself in an ordinary window instead of asking the
desktop's portal for one), spectacle directly, the xdg-desktop-portal
Screenshot interface, then gnome-screenshot/flameshot/grim+slurp as
further fallbacks. X11 (maim/scrot) is unchanged.

Also:
- The window no longer stays oversized on Wayland after a status message
  or progress bar disappears; it shrinks back to fit, same as on X11.
- Dictation now shows a clear message when it could only copy to the
  clipboard instead of typing automatically, rather than the same
  checkmark as a full success.
- gnome-screenshot, spectacle, wl-clipboard, wtype, grim, and quickshot's
  own dependencies (GTK3, cairo, gdk-pixbuf typelibs) are recommended by
  both the .deb and .rpm, which previously disagreed on a few of these.
- Code cleanup: shortened several overly long comments, removed an
  unused import.

## 4.0.4

Six more interface languages -- Danish, Hungarian, Turkish, Persian, Indonesian,
and Japanese -- for 23 interface languages total. Persian is right-to-left,
like Arabic; the interface now flips correctly for both. Voice names were
verified against the live Piper catalogue rather than the (outdated) VOICES.md
documentation page, which is what caught that Turkish's "fahrettin" voice has
since been removed upstream (using "dfki" instead) and confirmed Korean has no
official Piper voice at all (only an unrelated, non-commercially-licensed
third-party model, so it wasn't added).

This release also closes out a substantial round of Wayland support work,
prompted by real testing on Ubuntu, Fedora, and KDE/GNOME sessions rather
than assumptions:

- OCR-select now uses the xdg-desktop-portal Screenshot interface on
  Wayland, after tracing several layers of platform-specific failures:
  X11-only tools (maim/scrot) could silently "succeed" with a blank
  capture instead of erroring; gnome-screenshot itself doesn't work under
  GNOME 26.04/Wayland at all (confirmed on real hardware, not just a VM);
  and calling GNOME Shell's own Screenshot D-Bus interface directly is
  refused outright as a deliberate security boundary. The portal is the
  sanctioned, cross-desktop way to ask for this, confirmed working on
  both GNOME and KDE Wayland sessions. The portal saves a real file to
  the system Screenshots folder as a side effect; that source file is now
  cleaned up once VoxFox's own copy exists.
- Hover reading is hidden on Wayland (toolbar button and its Settings
  checkbox) and refuses cleanly if triggered via IPC/CLI regardless: it
  needs the mouse position outside VoxFox's own window, which Wayland's
  security model doesn't let any app query -- a hard platform limit, not
  a missing dependency.
- wl-clipboard, wtype, gnome-screenshot, and spectacle are now in both the
  .deb's and .rpm's Recommends (the .deb was missing gnome-screenshot
  entirely, and neither had the other three), giving the Select feature's
  existing Wayland clipboard fallback and OCR-select's screenshot tools
  something to actually find.
- Dictation could silently fail to install on a fresh, minimal system
  without python3-pip (increasingly common on newer Ubuntu/Debian): both
  the post-install script and "Set up VoxFox" now check for pip first and
  show a clear "sudo apt install python3-pip" message instead of a
  generic failure or, previously, no message at all.

Also fixed: the "VoxFox" title text in the header bar didn't shrink with
the Interface size setting, since the header bar's built-in title label
doesn't reliably inherit the scaled font size in every GTK theme; and
toolbar icons rendered incorrectly on Fedora KDE (only the top-left
portion of each icon visible) because every icon's SVG declared
conflicting width/height/viewBox values -- removing the redundant
width/height attributes, leaving only viewBox, is the standard way to
mark an SVG as fully scalable and resolves the ambiguity.

## 4.0.3

- Fixed: `_warmup_piper()` in app.py still hardcoded `~/.piper` instead of
  using the layered `find_voice_dir()` lookup added in 4.0.2, so a voice
  found via a system or migrated location silently skipped its warmup at
  startup -- no crash, just a slower first Read after launch. Found via a
  separate FoxOS build session that ran into it in practice; confirmed
  here directly against the actual code (not just the report) before
  fixing. Same fix pattern as the other two call sites already using
  find_voice_dir() (synthesis, sample-rate lookup); a repo-wide check
  confirms no other hardcoded PIPER_DIR + voice-name path remains.

## 4.0.2

VoxFox voices can now be shared system-wide (for example by FoxOS, which
bundles voices once for every user instead of each user downloading their
own copy). A voice is looked up across four layers, first match wins:
~/.local/share/voxfox/voices (current, writable) -> ~/.config/voxfox/voices
(legacy) -> ~/.piper (legacy; still holds the Piper engine itself,
unchanged) -> /usr/share/voxfox/voices (system). Only the first layer is
ever written to, so VoxFox never tries to write into a read-only system
image; a personal copy always wins over a system one of the same name.
Existing voices in a legacy location are moved (not copied, so large files
aren't duplicated on disk) into the new location once, automatically, the
first time VoxFox starts after upgrading -- a failed move leaves the
original untouched and voice resolution keeps working exactly as before.
Whisper models already respected $HF_HOME/$HF_HUB_OFFLINE and still do,
unchanged -- confirmed, no code change was needed there.

- New default Dutch voice: nl_NL-alex-medium (was nl_NL-pim-medium), with
  1.10 speed and -2 pitch as its defaults. Fresh installs only -- an
  existing user's own settings are never changed.
- Fixed: reinstalling shortcuts on KDE Plasma after they had already been
  installed once could fail entirely with "Could not install shortcuts on
  this desktop". kglobalaccel rewrites a freshly-written shortcut group in
  kglobalshortcutsrc into its own nested form the first time it reloads;
  VoxFox's own reader was misparsing that nested form as belonging to a
  different, unknown application and skipping its own shortcuts as false
  collisions. Fixed and confirmed against a reconstructed file matching
  the exact format from a real KDE session, without weakening genuine
  cross-application collision detection.
- New: packaging/uninstall-clean.sh removes the installed package plus all
  settings, voices, the Piper engine, and logs, for testing a genuinely
  clean install. Asks for confirmation first; --with-whisper additionally
  removes VoxFox's own faster-whisper models without touching any other
  Hugging Face cache content.

## 4.0.1

- New: seven more interface languages -- Norwegian, Swedish, Finnish,
  Romanian, Czech, Polish, and Portuguese (Portugal) as a distinct option
  alongside the existing (Brazilian) Portuguese, sharing the same interface
  text since the difference is purely which Piper voice is used. All are
  fully wired: default Piper voice, native display name, Tesseract OCR
  mapping, and Whisper dictation language hint. All 17 locales carry an
  identical key set, verified the same way Ukrainian's addition was
  (placeholder consistency, code-string coverage), plus a state-migration
  check confirming an old (pre-4.0) state file still loads correctly.
- Settings -> Translation: suggested models can now be selected as the
  active model directly, not just pulled. The button reads "Use" once a
  model is installed (rather than a disabled "Installed" label) and picks
  it as the active model with one click; a freshly pulled model is
  selected automatically too.
- The bundled community pronunciation dictionary (dicts/*.json) is now
  always active automatically for every user, instead of something you had
  to opt into loading -- and it no longer appears in Settings ->
  Pronunciation's editable word list, so that list stays short no matter
  how many community words get added over time. A rule you add yourself
  for a word always overrides the built-in one, so you can still correct
  any pronunciation you disagree with; that correction can be folded into
  the bundled dictionary itself in a future release. Import/export of your
  own dictionary file is unchanged. dicts/nl.json's first batch of
  voxfox.nl submissions (Apple, ok, Opdrachtregel, schermlezer,
  subsidieregelingen, Thee, voorlezen, XI) is included.
- Docs: README.md/README.nl.md's Pronunciation dictionary section explains
  the two layers above, with a new diagram
  (docs/img/pronunciation-layers[-nl].svg).

## 4.0

The interface has been split from one 4160-line file into the `voxfox_ui`
package (common, widgets, setup, screenshot, history, preferences, live,
main_window, shortcuts, app) for maintainability; `voxfox_gtk.py` remains a
thin launcher, so packaging and the `voxfox` command are unchanged.

- New: Translate & read. Select text in any language, translate it into the
  language of Language 1 via any OpenAI-compatible endpoint (a local Ollama
  server or a remote API), and read it aloud with that voice. The button is
  hidden by default (enable it under Settings → Interface) and its shortcut
  has no default binding — assign your own, the same as live transcription.
  Long selections are translated paragraph by paragraph with progress shown
  in the status bar; translations are saved to History.
- New: OCR select & translate. A shortcut-only sibling of Select (OCR): OCRs
  a screen region, translates the result, and reads it aloud — for text
  that isn't selectable (images, scanned pages, video subtitles) in another
  language. No toolbar button by design: a button would move keyboard focus
  to VoxFox before the result could be read back into the originating
  window's context, so a global shortcut is the only thing that works here.
- New: Settings → Translation can discover models already available on the
  configured endpoint — merged into the existing Model field as autocomplete
  suggestions rather than a second picker — and offers a short, curated list
  of lightweight translation models (a translation-specialised 1B model plus
  two small general multilingual ones) with one-click Ollama pull and
  streaming progress. VoxFox never installs Ollama itself; that remains a
  one-time manual step at ollama.com.
- New: Ukrainian, VoxFox's 11th interface language, with a default Piper
  voice, native display name for the language-switch button, and Tesseract
  OCR language mapping.
- Fixed: on KDE Plasma, a new shortcut could silently fail to fire whenever
  its key was already bound to something else — another application, or
  Plasma itself. KGlobalAccel drops a clashing global shortcut on reload
  with nothing surfaced to the user; installing a shortcut now checks it
  against everything already registered first, skips any that would
  collide, and reports which shortcut(s) were skipped and what they
  collided with.
- Hardening: dictation's recording-length safety cap (120s by default) was
  previously enforced only by VoxFox's own process polling the recorder. If
  that process ever died or hung mid-recording, the recorder had nothing
  left to stop it and would keep writing to a RAM-backed temp file
  (ram_tmpdir()) until the system ran out of memory. The recorder is now
  also wrapped with the `timeout` command, so the OS itself guarantees an
  end regardless of VoxFox's own process. The limit is now a visible,
  adjustable Settings → Dictation option (10–600s) instead of a hidden
  constant.
- Settings → Web page: the AI (Ollama) sub-options (mode, URL, API key,
  model, test, status) now collapse behind "Use AI (Ollama) to clean up the
  page text" instead of always showing.
- New icons for Translate (overlapping speech bubbles) and the
  language-switch button (exchange arrows, replacing the old single-stroke
  version).
- All 11 interface languages carry an identical, complete set of interface
  strings. Dutch and English are fully reviewed; the other nine —
  including Ukrainian — are machine-translated and would benefit from a
  native-speaker pass.

## 3.12

- New: live transcription. A separate, freely resizable window shows speech
  transcribed sentence by sentence in large, adjustable text (14-56 px) —
  useful as personal captions for anyone who follows written language more
  easily than spoken, including some forms of aphasia or hearing loss.
  Speech detection uses a self-recovering noise floor (the minimum level
  over the last few seconds) with hysteresis and an adjustable Sensitivity
  (High/Medium/Low), so it copes with quiet laptop microphones as well as
  noisy places (tested against a moving train). A pause of 2.5s or more
  starts a new paragraph. Content is ephemeral — not saved to History — with
  Copy provided for anyone who wants to keep it. A CLI flag
  (`voxfox --live-toggle`) and an installable keyboard shortcut (no default
  key, assign your own) toggle it.
- Fixed KDE Plasma shortcuts not actually launching their command when
  assigned to a brand-new action: a shortcut only works once KDE's service
  database (sycoca) knows the underlying .desktop file, which now gets an
  explicit rebuild after installing.
- Fixed `voxfox --live-toggle` (and any future CLI-forwarded action) being
  silently swallowed instead of reaching the running instance.
- Temporary audio now lives in RAM instead of on disk: synthesised sentences
  from the speech engine, dictation recordings, the microphone test and OCR
  scratch files are written to a tmpfs location (XDG_RUNTIME_DIR or
  /dev/shm) with a plain temp-dir fallback. This makes reading aloud
  noticeably smoother on slow SSDs/eMMC and avoids needless disk writes.

## 3.10

- The toolbar buttons now have icons. Eight bundled symbolic icons (speaker,
  filled stop square, solid pause bars, a mouth for dictation, pointer,
  dashed selection frame, document with text lines, and a two-arrow language
  switch) recolour automatically with light and dark themes.
- New in Settings -> Interface: **Button display** (icon only / icon and
  text / text only) and **Orientation** (horizontal rows or a narrow vertical
  column). In the narrowest form (vertical + icon only) the title bar shrinks
  to just a close button, the Settings and Menu buttons move to the bottom of
  the column, and the window pins its width to the button column so status
  messages never widen it.
- Hover reading now announces a whole button as one unit wherever the pointer
  is (icon or text), in VoxFox and in other applications with composite
  buttons.

## 3.9.1

- Hotfix: 3.9 was missing an import in the IPC module (caught by CI), which
  could crash VoxFox at startup when creating the fallback runtime directory.

## 3.9

- After installing the speech engine from the "Set up VoxFox" window, the
  main window now refreshes itself: the "Piper is not installed" notice
  disappears and the voice lists reload, so no restart is needed.
- Fixed the main window becoming invisible on a first install under KDE: an
  early size measurement could come back near-zero and the auto-shrink then
  resized the window to a few pixels. Suspicious measurements are now skipped
  and the window never shrinks below a sane minimum size.
- Remaining fixes from the external code review: a settings file with one
  corrupted section now keeps all other settings (only the broken section is
  reset); settings export no longer includes API keys; and the fallback
  runtime directory in /tmp is created with strict permissions and verified
  against symlink tricks.

## 3.8.1

- Fixed KDE Plasma shortcuts so they now correctly overwrite an existing
  binding. VoxFox writes the bindings straight into kglobalshortcutsrc via
  kwriteconfig (the previous .desktop-only method never updated an existing
  shortcut) and asks kglobalaccel to reload so the change usually takes
  effect without a re-login.
- Documentation: the install examples use version-independent file names, and
  the shortcut docs list KDE Plasma alongside GNOME, Cinnamon, XFCE and LXQt.

## 3.8

- Added global keyboard shortcut support for KDE Plasma. VoxFox registers its
  six shortcuts as .desktop files with X-KDE-Shortcuts lines (the stable route
  on Plasma 5 and 6); the Super key maps to Meta. A newly installed shortcut
  may only become active after logging out and back in. This adds to the
  existing GNOME, Cinnamon, XFCE and LXQt support.

## 3.7

- The first-run setup now shows clear progress: a step counter ("[2/3]
  Downloading voices…") and a progress bar that fills during the Piper and
  voice downloads and pulses during the dictation install, so it is obvious
  the installation is working and how far along it is. The progress bar also
  appears in the "Set up VoxFox" window itself.
- Fixed installation on some systems (e.g. Kubuntu 26.04) where the hardened
  Piper extraction wrongly rejected Piper's own internal symlink
  (libpiper_phonemize.so). Internal links are now allowed; only links that
  point outside the target directory are refused.
- Security and reliability fixes from an external code review: the Piper
  download now extracts safely (no path traversal) with a pinned version and
  optional checksum verification, and setup failures are reported honestly
  with a non-zero exit code instead of always claiming success.
- "Confirm transcription before typing" now actually works: when enabled, a
  preview dialog lets you review and edit the text, then copy it to the
  clipboard to paste yourself with Ctrl+V.
- Fixed the manual clipboard fallback so a dictated text you need to paste by
  hand is no longer overwritten; fixed a remote-test status that vanished
  after 8 ms; the web-page reader now enforces its own chunk-size limit and
  bounds gzip decompression; the OCR file picker no longer offers GIF (the
  backend can't read it); refreshing the microphone list keeps your current
  selection.
- Pronunciation dictionaries can now be exported and imported as files
  (Settings → Pronunciation), so users can share their word lists. Imports
  merge: new words are added, existing ones updated, and the file's own
  language is respected.
- VoxFox ships community pronunciation dictionaries (collected via the form
  on voxfox.nl) in /usr/share/voxfox/dicts; a "Load bundled dictionary"
  button merges the one for the current language with one click.
- The settings tabs are reordered: Shortcuts, Web page and Interface moved
  forward and Misc is now the last tab.

## 3.6

- Development version; its changes were released together with 3.7.

## 3.5

- An experimental RPM package (voxfox-x.y-1.noarch.rpm, built with
  packaging/build-rpm.sh) brings VoxFox to Fedora; tested on Fedora
  Workstation. The .deb remains the primary package.
- Added Greek as the tenth interface language, with Piper speech
  (el_GR-rapunzelina), dictation and OCR support (install the
  tesseract-ocr-ell pack for OCR).
- Read web page now works from a selected URL: select the page's address
  (Ctrl+L in the browser) and press Super+V — VoxFox fetches the page itself
  and reads the article, showing the page title in the status line so it is
  always clear which page is being read. This route does not need the
  accessibility bus at all; the AT-SPI extraction of the focused tab remains
  as fallback when no URL is selected.
- The built-in extractor strips menus, banners, sidebars, footers and scripts
  from fetched pages and prefers the page's main/article section, using only
  the Python standard library (no new dependencies).
- Pages that only render with JavaScript are retried automatically in a
  headless Chromium (Chromium, Chrome, Brave or Edge, when installed), so
  single-page apps and some bot walls work too. The plain fetch stays the
  fast first attempt.
- Settings → Web page gained an optional API key, sent as a Bearer token, so
  an Ollama instance behind a reverse proxy on another machine can be used.

- New experimental feature: read the current web page aloud with `Super+V` or
  `voxfox --read-page`. The article is extracted from the focused browser tab
  over AT-SPI, using the page's landmarks to skip menus, banners, sidebars and
  footers. Optionally a local AI (Ollama) refines the result — configured in
  the new Settings → Web page tab as either *Filter only* (keep the original
  sentences, drop leftover adverts and snippets of other articles) or
  *Summarize*. If Ollama is unreachable VoxFox falls back to the structurally
  cleaned text. Requires the accessibility bus; Chromium-based browsers need
  --force-renderer-accessibility.
- The shortcut set grows from five to six actions (the new "Read web page" on
  Super+V by default); keys remain fully customizable under Settings →
  Shortcuts and are still never installed automatically.

## 3.4

- Added Chinese and Arabic, bringing the interface to nine languages. Pick
  either as a slot language and the toolbar, menus and messages switch over;
  Arabic also flips the whole interface to right-to-left. Speech uses Piper's
  Chinese and Arabic voices, dictation and OCR work in both (install the
  tesseract-ocr-chi-sim or tesseract-ocr-ara pack for OCR), and long Chinese
  text now breaks into sentences correctly for natural-sounding pacing.
- The toolbar buttons now stretch to fill the full width of the window, so both
  rows line up edge to edge instead of sitting in a narrower centred block.
- New "Set up VoxFox" window gathers everything needed for first use in one
  place: installing the speech engine, voices, dictation and OCR helpers;
  switching on system-wide accessibility; and registering the keyboard
  shortcuts. Each step shows whether it is already done. It opens automatically
  the first time you run VoxFox and is always available from the menu.
- Tidied the menu: the separate "Install / repair components" and "Enable
  accessibility" items are replaced by the single "Set up VoxFox…" entry.
- VoxFox no longer crashes at startup when the AT-SPI accessibility bus is
  broken or permission-denied (for example a stale root-owned
  /root/.cache/at-spi/bus_0). It now detects an unreachable bus and skips the
  accessibility bridge instead of aborting, and hover reading refuses with a
  clear message rather than taking the whole app down.

## 3.3

- Keyboard shortcuts are now configurable from Settings → Shortcuts. Each of the
  five VoxFox actions shows its current key; click it and press the combination
  you want to change it. Pick your keys, then Install shortcuts writes them to
  the desktop in one go, and Reset to defaults restores the originals. A
  combination already used by another VoxFox action is refused, and capture
  briefly inhibits the desktop's own global shortcuts so you can even reassign a
  key that is already taken.
- Shortcuts are no longer installed automatically on first start. Some desktops
  already use these keys, so VoxFox now waits until you choose to install them.
- Installing shortcuts now works across Cinnamon, GNOME, LXQt and XFCE, and
  correctly replaces a key you changed instead of leaving the old one bound. On
  Cinnamon the desktop is briefly reloaded after installing so the new keys take
  effect immediately, without logging out.
- Added python3-pip as a dependency so the speech-to-text component
  (faster-whisper) can be installed on a fresh system.

## 3.2

- The default global shortcuts (Super+Z/X/C/W/A) can now be installed on XFCE.
  `voxfox --install-shortcuts` writes them via xfconf-query into the
  xfce4-keyboard-shortcuts channel, keeping any shortcut you set by hand and
  never creating duplicates. No-op when xfconf-query is unavailable.

## 3.1.1

- Fixed OCR region select ("Kies/Select") triggering two screenshot captures on
  every use. A leftover Tkinter worker from an old VoxMob code path was still
  present alongside the GTK4 worker, causing two selections to be requested in
  sequence. Now only the correct GTK4 worker runs.

## 3.1

- Hover reading now falls back through several accessibility properties instead
  of going silent on unlabelled controls. When an element has no accessible name,
  VoxFox tries its labelling relation, its description and its image description,
  and as a last resort announces the control type (button, checkbox, slider, ...)
  with its checked or expanded state. Icon-only buttons that previously read
  nothing now at least announce what they are, across GTK and Qt apps alike.
- The default global shortcuts (Super+Z/X/C/W/A) can now be installed on LXQt,
  not just GNOME and Cinnamon. `voxfox --install-shortcuts` writes them to LXQt's
  globalkeyshortcuts.conf as Meta+ command entries, keeping any shortcut you set
  by hand and never creating duplicates.

## 3.0

This release reworks the main window into a modular, scalable toolbar.

- The seven action buttons (Read, Stop, Pause, Speak, Hover, Select, OCR) and
  the language switcher can now each be shown or hidden and reordered, from a
  new Interface tab in the settings. People who only dictate, or who use a
  single language, can pare the toolbar down to just what they need. Choices are
  remembered, and the settings panel and menus stay fixed.
- A global interface scale of 75%, 100% or 125% scales the whole main window —
  title, buttons, text, icons and spacing together — and applies live without a
  restart. The scale is remembered across restarts.
- The window now sizes itself to its content: exactly wide enough for the
  visible buttons (up to five on one row, six or more split over two rows) and
  exactly tall enough, with no empty filler. It stays resizable, and the unused
  maximize button has been removed. Button labels are always shown in full, so
  the toolbar can never shrink small enough to clip the text.

## 2.0.9

- Fresh-install language seeding now works properly. On a brand-new install
  Slot 1 is set from the system language ($LANG) for both the interface and the
  first voice, and Slot 2 becomes English (or Dutch if the system is already
  English), so there is always a second language to switch to. Unknown system
  languages keep the English default.
- Voice download now also fetches the voices the two slots currently point at,
  not just the bundled English and Dutch ones, so e.g. a German system pulls
  its German voice during setup.
- maim is now a package dependency. It is the preferred screenshot tool for OCR
  region select (tried before scrot), so it should be present rather than
  optional.

## 2.0.8

- Keyboard shortcuts no longer break Cinnamon's "Add custom shortcut" button.
  VoxFox previously registered its shortcuts under named entries (voxfox-read,
  ...) in the desktop's custom-shortcut list; Cinnamon expects that list to be
  a clean numeric sequence (custom0, custom1, ...) and silently stops letting
  you add your own shortcuts when it contains other names. VoxFox now uses
  numeric slots and tracks which ones it owns, so the list stays valid.
  Upgraders are migrated automatically on first start; the visible labels in
  the settings panel are unchanged.
- The application icon now ships in the package again. The build looked for the
  logo in the wrong directory, so the icon was missing and the menu and taskbar
  fell back to a generic gear. The logo is now installed at all standard
  hicolor sizes plus a /usr/share/pixmaps fallback, and the icon cache is
  refreshed on install and removal.
- VoxFox now appears under Utility in the application menu and groups correctly
  in the taskbar. The window's WM_CLASS is now org.voxfox.VoxFox instead of
  python3, so the panel can match the running window to its launcher and show
  the right icon.
- OCR region select ("Kies") is more reliable when triggered from its Super+A
  shortcut. It now prefers maim/scrot (gnome-screenshot fails silently on
  Cinnamon) and retries briefly when the window manager still holds the
  hotkey's pointer grab, fixing the "scrot: couldn't grab pointer" failure. A
  user cancelling the selection (Escape) is still detected and not retried.

## 2.0.7

- On a fresh install VoxFox now picks a sensible first language automatically
  from $LANG / the system locale, instead of always defaulting to one voice.
- The application logo/icon was restored to the package (hicolor icon theme,
  with a /usr/share/voxfox/ fallback for the About dialog before voices are
  downloaded).
- Region OCR select ("Kies") was made reliable on Cinnamon. gnome-screenshot
  fails silently there, so maim/scrot are tried first. Also fixed an empty
  temp file from tempfile.mkstemp() that newer scrot refused to overwrite, by
  unlinking it before invoking the screenshot tool.

## 2.0.6

- Piper now stays loaded between sentences. Previously the voice model was
  loaded from disk on every utterance, causing a half-second to one-second
  delay before the first word. Now Piper runs as a persistent background
  process; the model is loaded once (on the first call, or when you switch
  voice/speed/pitch) and all subsequent calls answer in synthesis time only
  (~100 ms). The first sentence of a new utterance is also faster because
  of the prefetch pipeline added in 2.0.5.

## 2.0.5

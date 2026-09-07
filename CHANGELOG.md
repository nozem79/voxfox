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

Whisper models

- Downloading a model works on systems that set HF_HUB_OFFLINE=1
  system-wide, such as FoxOS. A model already on disk is loaded strictly
  from disk; a missing one is fetched with the offline switch lifted for
  that call only.
- Models are looked for both in the configured location (HF_HOME) and in
  the user's own cache, and are downloaded into whichever is writable. A
  distribution can ship models under /usr and a user can still add their
  own without needing write access there.

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

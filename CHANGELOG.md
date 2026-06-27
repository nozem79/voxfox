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

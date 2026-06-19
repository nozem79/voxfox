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

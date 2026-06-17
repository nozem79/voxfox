## 2.0.7

- First-run language now follows the system locale. On a fresh install the
  starting voice and interface language are picked from $LANG instead of
  always defaulting to English — e.g. a Dutch system starts in Dutch, a German
  system in German. The second voice slot defaults to English (or Dutch if the
  system is already English) so there's always a sensible language to toggle to.
- The application logo/icon is now bundled in the package again. It ships to
  the hicolor icon theme (so the launcher and menu show the VoxFox icon) and to
  /usr/share/voxfox (so the About dialog has a logo before any voices are
  downloaded). On install the icon cache and desktop database are refreshed so
  the icon appears immediately on Linux Mint Cinnamon and GNOME.
- faster-whisper, sounddevice and soundfile continue to be installed
  automatically on install (via the package's post-install step).

## 2.0.6

- Piper now stays loaded between sentences. Previously the voice model was
  loaded from disk on every utterance, causing a half-second to one-second
  delay before the first word. Now Piper runs as a persistent background
  process; the model is loaded once (on the first call, or when you switch
  voice/speed/pitch) and all subsequent calls answer in synthesis time only
  (~100 ms). The first sentence of a new utterance is also faster because
  of the prefetch pipeline added in 2.0.5.

## 2.0.5

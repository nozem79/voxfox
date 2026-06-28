# After installing VoxFox

On first launch VoxFox opens a **Set up VoxFox** window that gathers everything
in one place (reopen it any time from the menu). Each step shows whether it is
already done:

1. **Speech engine, voices and dictation.** Installs the Piper engine, the
   default voices, dictation (faster-whisper) and the OCR helpers. This needs an
   internet connection and `python3-pip`. You can also run `voxfox --setup`.

2. **Enable accessibility.** For hover reading — and so a screen reader can see
   text in other apps — switch on the accessibility bus. Then log out and back
   in (or restart the apps you want read). Chromium-based browsers also need to
   be started with `--force-renderer-accessibility`.

3. **Keyboard shortcuts.** Optionally register the five VoxFox shortcuts on your
   desktop. Change the keys first under Settings → Shortcuts if you like.

For OCR in other languages, install the matching Tesseract pack, e.g.
`sudo apt install tesseract-ocr-nld` (or `-chi-sim`, `-ara`, …).

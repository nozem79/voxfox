# After installing VoxFox

Two quick steps to get everything working:

1. **Install Piper (voices).** On first launch VoxFox shows a banner:
   *"Piper TTS is not installed yet — Install now."* Click it (or run
   `voxfox --setup`) to download the speech engine, the default voices and the
   dictation component. This needs an internet connection and `python3-pip`.

2. **Enable accessibility.** For hover reading — and so a screen reader can see
   text in other apps — turn on the accessibility bus via the menu:
   *"Enable accessibility (system-wide)."* Then log out and back in (or restart
   the apps you want read). Chromium-based browsers also need to be started with
   `--force-renderer-accessibility`.

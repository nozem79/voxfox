# Na het installeren van VoxFox

Twee korte stappen om alles werkend te krijgen:

1. **Installeer Piper (stemmen).** Bij de eerste start toont VoxFox een balk:
   *"Piper TTS is nog niet geïnstalleerd — Nu installeren."* Klik daarop (of voer
   `voxfox --setup` uit) om de spraak-engine, de standaardstemmen en het
   dicteeronderdeel te downloaden. Hiervoor heb je internet en `python3-pip`
   nodig.

2. **Zet toegankelijkheid aan.** Voor hover-lezen — en zodat een schermlezer
   tekst in andere programma's kan zien — schakel je de toegankelijkheidsbus in
   via het menu: *"Toegankelijkheid systeembreed inschakelen."* Log daarna uit
   en weer in (of herstart de programma's die je wilt laten voorlezen).
   Chromium-browsers moeten bovendien gestart worden met
   `--force-renderer-accessibility`.

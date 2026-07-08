# Na het installeren van VoxFox

Bij de eerste start opent VoxFox het venster **VoxFox instellen**, dat alles op
één plek samenbrengt (je kunt het altijd opnieuw openen via het menu). Elke stap
laat zien of die al gedaan is:

1. **Spraakengine, stemmen en dicteren.** Installeert de Piper-engine, de
   standaardstemmen, dicteren (faster-whisper) en de OCR-hulpprogramma's.
   Hiervoor heb je internet en `python3-pip` nodig. Je kunt ook `voxfox --setup`
   uitvoeren.

2. **Zet toegankelijkheid aan.** Voor hover-lezen — en zodat een schermlezer
   tekst in andere programma's kan zien — schakel je de toegankelijkheidsbus in.
   Log daarna uit en weer in (of herstart de programma's die je wilt laten
   voorlezen). Chromium-browsers moeten bovendien gestart worden met
   `--force-renderer-accessibility`.

3. **Sneltoetsen.** Registreer desgewenst de zes VoxFox-sneltoetsen op je
   bureaublad. Wijzig eerst de toetsen onder Instellingen → Sneltoetsen als je
   wilt.

Voor OCR in andere talen installeer je het bijbehorende Tesseract-pakket, bijv.
`sudo apt install tesseract-ocr-nld` (of `-chi-sim`, `-ara`, …).

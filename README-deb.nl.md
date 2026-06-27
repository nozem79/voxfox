# VoxFox (GTK4 / Debian-pakket)

VoxFox is een schermlezer en dicteerprogramma voor Linux. Het leest
geselecteerde tekst voor met Piper-stemmen, zet spraak om naar tekst met
Whisper, en kan een bestand of een geselecteerd schermgebied via OCR voorlezen.
Elke actie is ook een opdrachtregelcommando, zodat je elke knop aan een globale
sneltoets kunt koppelen.

Dit document beschrijft de **GTK4-versie die je installeert via het
`.deb`-pakket**. Die verschilt van de losse Tk-versie: hij installeert
systeembreed met `apt`, deelt een UI-onafhankelijke kern (`voxfox_core`), en
voegt GPU-detectie voor Whisper toe, een tesseract-CLI-terugval voor OCR, en
nette labels voor schermlezers.

## Installatie

```bash
sudo apt install ./voxfox_2.0.3_all.deb
```

`apt` haalt de afhankelijkheden automatisch op. Start VoxFox daarna via het
toepassingenmenu, of met het commando `voxfox` in een terminal.

> Als je vanuit je persoonlijke map installeert, kun je een melding krijgen dat
> de download "door root en niet in een sandbox gebeurt, omdat `_apt` het
> bestand niet kon benaderen". Dit is onschuldig — de installatie wordt gewoon
> voltooid. Wil je de melding voorkomen, installeer dan vanaf een map die voor
> iedereen leesbaar is, bijvoorbeeld `sudo cp voxfox_2.0.3_all.deb /tmp/ &&
> sudo apt install /tmp/voxfox_2.0.3_all.deb`.

### Wat het pakket installeert

Het `.deb` installeert alleen het programma zelf (in `/usr/lib/voxfox`, met een
starter in `/usr/bin/voxfox`, een menu-item, een pictogram en de vertalingen).
De zwaardere, gebruikersgebonden onderdelen worden bij de eerste start
opgehaald — zie Eerste installatie.

## Eerste installatie

Piper (de TTS-engine en de stemmen), `faster-whisper` (dicteren) en
`pytesseract` (optionele OCR-helper) zijn **geen** Debian-pakketten en worden
daarom per gebruiker geïnstalleerd. Als Piper bij de eerste start ontbreekt,
toont het venster een balk:

> Piper TTS is nog niet geïnstalleerd. **[Nu installeren]**

Klik daarop, of doe hetzelfde vanaf de opdrachtregel:

```bash
voxfox --setup
```

Dit downloadt de Piper-engine voor jouw processorarchitectuur, twee
standaardstemmen (`en_GB-alba-medium` en `nl_NL-pim-medium`) naar `~/.piper`, en
installeert `faster-whisper` en `pytesseract` met pip. Je mag dit veilig opnieuw
uitvoeren; het is ook beschikbaar via het menu als *Onderdelen installeren /
herstellen*.

> De setup heeft `python3-pip` nodig (een aanbevolen afhankelijkheid). OCR werkt
> ook zonder `pytesseract`, omdat VoxFox terugvalt op de `tesseract`-opdrachtregel.

## Het venster

De titelbalk toont de programmanaam, met **Instellingen** (tandwiel) en het
**menu** rechts. Twee rijen knoppen:

- **Rij 1:** Voorlezen · Stop · Pauze
- **Rij 2:** Spreek · Hover · Kies · OCR · NL/EN (de taalwisselaar)

Onder de knoppen verschijnt een statusregel zolang er iets gebeurt; daarna
verbergt die zich weer. De statusregel is gemarkeerd als live-gebied, zodat een
schermlezer meldingen als "Aan het voorlezen…" automatisch voorleest. Terwijl
een Whisper-model of een Piper-stem wordt gedownload, verschijnt er net onder de
statusregel een voortgangsbalk, zodat je ziet hoe ver de download is.

## Tekst voorlezen

Selecteer tekst in een willekeurige toepassing en druk op **Voorlezen** (of voer
`voxfox --read` uit). VoxFox leest de tekst voor met de stem van het actieve
slot. **Stop** stopt het afspelen; **Pauze** pauzeert en hervat.

## Twee taalslots

VoxFox houdt twee stem-/taalslots bij, zodat je snel kunt wisselen tussen
bijvoorbeeld Nederlands en Engels. De **NL/EN**-knop (en `voxfox --toggle-slot`)
wisselt het actieve slot. De taal, stem en snelheid van elk slot stel je in bij
**Instellingen** (het tandwiel). Wanneer je de taal van slot 1 wijzigt, wordt de
hele interface meteen in die taal opnieuw weergegeven.

## Geschiedenis

VoxFox onthoudt je laatste 20 voorgelezen en gedicteerde items. Open **Menu →
Geschiedenis** om ze te zien: elk item kun je opnieuw laten voorlezen (▶) of naar
het klembord kopiëren om het te plakken waar je wilt. **Alles wissen** leegt de
lijst.

## Uitspraakwoordenboek

VoxFox kan woorden herschrijven voordat ze worden uitgesproken — handig voor
namen, afkortingen en leenwoorden die de stem verkeerd uitspreekt. Open
**Instellingen → Uitspraak**; daar bewerk je het woordenboek voor de taal van
slot 1. Voeg regels toe als *woord → uitspreken als* (bijv. `VoxFox →
Voks-foks`, `GUI → goe-wie`) en gebruik **Test** om ze te beluisteren. Matching
gebeurt op hele woorden en hoofdletterongevoelig, en de regels gelden voor alles
wat in die taal wordt voorgelezen (Voorlezen, Hover, OCR).

## Afgebroken tekst voorlezen, en Instellingen → Overig

Bij het voorlezen van OCR-tekst of geselecteerde tekst (bijvoorbeeld gekopieerd
uit een pdf) voegt VoxFox regels die alleen zijn afgebroken samen tot echte
alinea's, zodat hij niet meer middenin een zin pauzeert. Je schakelt dit onder
**Instellingen → Overig** ("Afgebroken regels samenvoegen tot alinea's") — zet
het uit om elke regel apart voor te lezen (handig voor lijsten of code). Op het
tabblad Overig staat ook **Instellingen importeren/exporteren** om je
configuratie te bewaren of te verplaatsen.

## Dicteren (spraak naar tekst)

Druk op **Spreek** (of `voxfox --whisper-toggle`) om de opname te starten; druk
nogmaals om te stoppen. VoxFox transcribeert de audio en typt het resultaat in
de toepassing die de focus heeft. Onder **Instellingen → Whisper** kies je het
model, de microfoon, en of de tekst eerst bevestigd moet worden voordat hij
getypt wordt.

### Lokaal versus extern (API)

- **Lokaal** draait Whisper op je eigen machine via `faster-whisper`. Kies een
  model (`tiny` → `large-v3`) en gebruik de downloadknop om het vooraf op te
  halen; grotere modellen zijn nauwkeuriger maar trager en groter.
- **Externe API** stuurt de audio naar een OpenAI-compatibel transcriptie-eindpunt.
  Vul de URL, het model en (optioneel) de API-sleutel in en gebruik
  **Verbinding testen**.

### GPU-versnelling

Whisper kan een NVIDIA-GPU gebruiken. Onder **Instellingen → Compute**:

- **Auto** (standaard) gebruikt de GPU zodra er een CUDA-runtime gedetecteerd
  wordt, anders de CPU. Mislukt de GPU-initialisatie, dan valt hij automatisch
  terug op de CPU.
- **CPU** / **GPU** forceren een keuze.

Een GPU helpt vooral bij de grotere modellen. Het vereist de NVIDIA-driver plus
de CUDA-runtime, cuBLAS en cuDNN, die niet met het pakket worden meegeleverd. De
eenvoudigste manier om de bibliotheken te krijgen is via pip:

```bash
pip install --user nvidia-cublas-cu12 nvidia-cudnn-cu12
```

Oudere Pascal-kaarten (zoals de Tesla P40, compute capability 6.1) kunnen geen
efficiënte float16 aan — VoxFox detecteert dat en gebruikt op zulke GPU's
automatisch `int8` (float16 zou crashen of erg traag zijn). int8 heeft
verwaarloosbare invloed op de nauwkeurigheid. Volta-kaarten en nieuwer gebruiken
float16. Piper TTS gebruikt de meegeleverde CPU-build — die is al sneller dan
realtime, dus daar is geen GPU-build voor.

## OCR — tekst uit afbeeldingen en het scherm

- Met **Kies** (`voxfox --ocr-select`) trek je een rechthoek op het scherm; de
  tekst daarbinnen wordt via OCR gelezen en voorgelezen. Het gebruikt de eigen
  schermafdruktool van je bureaublad, dus het werkt op zowel X11 als Wayland.
- **OCR** opent een PDF- of afbeeldingsbestand en leest de tekst voor.

OCR gebruikt Tesseract. Het werkt al met alleen het pakket `tesseract-ocr` (plus
de taalgegevens, bijv. `tesseract-ocr-nld`); `pytesseract` is optioneel.

## Hover-modus

**Hover** (`voxfox --hover-toggle`) leest de interfacetekst onder de muisaanwijzer
voor, via de AT-SPI-toegankelijkheidsboom.

Hiervoor moet de toegankelijkheidsbus aanstaan. Het menu heeft **Toegankelijkheid
systeembreed inschakelen**, dat de GNOME-instelling `toolkit-accessibility` voor
je aanzet; herstart daarna de betreffende toepassing. Chromium-browsers moeten
bovendien gestart worden met `--force-renderer-accessibility`. Hover werkt het
betrouwbaarst op GTK- en Firefox-vensters.

## Altijd op de voorgrond

Het venster blijft boven andere vensters (net als de oude versie), via `wmctrl`.
Dit werkt op **X11**; op Wayland bepaalt de compositor de stapelvolgorde, dus
daar kan het zonder effect blijven.

## Sneltoetsen

VoxFox kan vijf globale sneltoetsen voor je installeren — open
**Instellingen → Sneltoetsen**, wijzig eventueel een combinatie door erop te
klikken en de toetsen in te drukken, en kies dan **Sneltoetsen installeren**.
Dit werkt op Cinnamon, GNOME, LXQt en XFCE; er wordt niets automatisch
geïnstalleerd. Standaardtoetsen:

| Commando                   | Actie                        | Standaard |
|----------------------------|------------------------------|-----------|
| `voxfox --read`            | Geselecteerde tekst voorlezen| `Super+Z` |
| `voxfox --stop`            | Voorlezen stoppen            | `Super+X` |
| `voxfox --toggle-slot`     | Taal wisselen                | `Super+C` |
| `voxfox --whisper-toggle`  | Dicteren (spraak naar tekst) | `Super+W` |
| `voxfox --ocr-select`      | Schermgebied voorlezen (OCR) | `Super+A` |

`voxfox --install-shortcuts` doet hetzelfde vanuit een terminal. Overige
commando's (`voxfox --pause`, `voxfox --hover-toggle`) kun je handmatig koppelen
in de toetsenbordinstellingen van je bureaublad.

Overige commando's: `voxfox --ocr <bestand>` (OCR op een bestand, werkt zonder
draaiende instantie), `voxfox --status`, `voxfox --quit`, `voxfox --setup`,
`voxfox --verbose`.

## Toegankelijkheid

VoxFox is gebouwd om met een schermlezer bruikbaar te zijn. Alle knoppen hebben
expliciete toegankelijke namen en tooltips, knoppen met alleen een pictogram
gebruiken symbolische iconen in plaats van emoji, en de statusregel is een
live-gebied. Getest met Orca.

## Afhankelijkheden

Worden automatisch geïnstalleerd:

- **Vereist:** `python3`, `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-glib-2.0`,
  `python3-pyatspi`, `at-spi2-core`
- **Aanbevolen (standaard meegenomen):** `xdotool`, `xclip`, `wl-clipboard`,
  `gnome-screenshot`, `wmctrl`, `python3-pip`, `tesseract-ocr`,
  `tesseract-ocr-eng`, `tesseract-ocr-nld`, `poppler-utils`, `python3-pil`,
  `ffmpeg`, `python3-numpy`, `python3-sounddevice`, `python3-soundfile`

Optioneel, voor Whisper op GPU: de NVIDIA-driver, de CUDA-runtime en cuDNN.

## Waar de bestanden staan

- Programma: `/usr/lib/voxfox/` (starter `/usr/bin/voxfox`)
- Piper-engine + stemmen: `~/.piper/`
- Whisper-modelcache: `~/.cache/huggingface/`
- Instellingen: `~/.config/voxfox_state.json`

## Voor ontwikkelaars / broncode

VoxFox is in Python geschreven, dus er is geen compilatie naar een binary — het
programma draait via de Python-interpreter, en het `.deb` levert de broncode als
platte tekst mee in `/usr/lib/voxfox/`. Reviewen, verbeteren en opnieuw bouwen is
daardoor eenvoudig.

**De broncode** bestaat uit twee bestanden plus assets:

- `voxfox_core.py` — de UI-onafhankelijke kern en het grootste deel van de
  logica: Piper-TTS, Whisper-STT (lokaal, externe API, GPU-detectie),
  Tesseract-OCR (met een CLI-terugval), de IPC-server, de opdrachtregel, het
  opslaan van instellingen/geschiedenis en de taaltabellen. Het importeert geen
  enkele GUI-toolkit.
- `voxfox_gtk.py` — de GTK4-frontend (venster, instellingen, knoppen); dit
  importeert `voxfox_core`.
- Assets: `locales/*.json` (vertalingen), `voxfox-logo.png`, `licence.txt`.
- `packaging/build-deb.sh` — stelt het `.deb` samen.

(De losse Tk-versie onder `tk-original/` is een aparte variant en is niet nodig
voor de GTK-/`.deb`-versie.)

**Reviewen** doe je door de twee `.py`-bestanden te lezen. **Draaien vanuit de
broncode** zonder pakket kan met `python3 voxfox_gtk.py` (GTK 4 en de
afhankelijkheden moeten aanwezig zijn). **Verbeteren** doe je door die bestanden
te bewerken.

**Het pakket bouwen** (geen compilatie; Python byte-compileert zichzelf bij het
draaien):

```bash
cd packaging
./build-deb.sh                 # maakt voxfox_<versie>_all.deb
VERSION=1.1.0 ./build-deb.sh   # bouw een specifieke versie
```

Voor het bouwen heb je alleen `dpkg-deb` nodig.

## Ondersteunde systemen

- **Besturingssysteem:** Debian-gebaseerde Linux (Debian, Ubuntu, Linux Mint,
  Pop!_OS, …) voor het `.deb`. Op andere distributies (Fedora, Arch) draait de
  broncode rechtstreeks met `python3 voxfox_gtk.py`; alleen het kant-en-klare
  pakket is Debian-specifiek. Niet voor Windows of macOS — het leunt op
  Linux-voorzieningen (AT-SPI, xdotool, de Linux-Piper-binary, …).
- **Bureaublad:** ontworpen voor GNOME. Sommige functies zijn sessie-afhankelijk:
  altijd-op-de-voorgrond (via `wmctrl`) werkt op X11, niet op Wayland; tekstselectie
  en schermafdrukken werken op beide; hover (AT-SPI) werkt het best op X11.
- **Python / GTK:** Python 3.9+ en GTK 4 (dus Debian 12+, Ubuntu 22.04+ of nieuwer).
- **Processorarchitectuur:** het pakket is `Architecture: all` (pure Python). De
  praktische beperking zit in de onderdelen die de setup ophaalt: de
  Piper-binary is er voor `x86_64`, `aarch64` en `armv7l`, en `faster-whisper`
  draait vooral op `x86_64` en `aarch64`.
- **GPU (optioneel):** een NVIDIA-GPU met de CUDA-runtime en cuDNN versnelt
  Whisper; anders draait alles op de CPU.

## Verwijderen

```bash
sudo apt remove voxfox
```

Gebruikersgegevens in `~/.piper`, `~/.config/voxfox_state.json` en de
Whisper-cache blijven staan; verwijder die handmatig als je helemaal schoon wilt
beginnen.

## Licentie

GPLv3 · © 2025 Daniël Vos · <https://voxfox.nl/manual>

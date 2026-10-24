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
sudo apt install ./voxfox_*_all.deb
```

`apt` haalt de afhankelijkheden automatisch op. Start VoxFox daarna via het
toepassingenmenu, of met het commando `voxfox` in een terminal.

> Als je vanuit je persoonlijke map installeert, kun je een melding krijgen dat
> de download "door root en niet in een sandbox gebeurt, omdat `_apt` het
> bestand niet kon benaderen". Dit is onschuldig — de installatie wordt gewoon
> voltooid. Wil je de melding voorkomen, installeer dan vanaf een map die voor
> iedereen leesbaar is, bijvoorbeeld `sudo cp voxfox_*_all.deb /tmp/ &&
> sudo apt install /tmp/voxfox_*_all.deb`.

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
uitvoeren; het is ook beschikbaar via *Installatiehulp…* in het menu.

> De setup heeft `python3-pip` nodig (een aanbevolen afhankelijkheid). OCR werkt
> ook zonder `pytesseract`, omdat VoxFox terugvalt op de `tesseract`-opdrachtregel.

## Het venster

De titelbalk toont de programmanaam, met rechts één **Menu**-knop (drie
streepjes): *Instellingen*, *Typen en uitspreken*, *Bibliotheek*,
*Geschiedenis*, *Live transcriptie*, *Installatiehulp…*, *Over VoxFox* en
*Afsluiten*. Twee rijen knoppen:

- **Rij 1:** Voorlezen · Stop · Dicteren · Muis
- **Rij 2:** Scherm · Bestand · NL/EN (de taalwisselaar)

*Pauze*, *Vertaal* en *Typen* staan standaard uit; zet ze aan bij
**Instellingen → Weergave → Knoppen**. Tijdens het voorlezen wordt
**Voorlezen** de knop **Pauze** / **Verder**.

Onder de knoppen verschijnt een statusregel zolang er iets gebeurt; daarna
verbergt die zich weer. De statusregel is gemarkeerd als live-gebied, zodat een
schermlezer meldingen als "Aan het voorlezen…" automatisch voorleest. Terwijl
een Whisper-model of een Piper-stem wordt gedownload, verschijnt er net onder de
statusregel een voortgangsbalk, zodat je ziet hoe ver de download is.

**Instellingen** is een lijst met onderdelen: Taal 1, Taal 2, Uitspraak,
Dicteren, Vertalen en AI, Sneltoetsen, Weergave (grootte, licht of donker,
knoppen) en Algemeen.

## Tekst voorlezen

Selecteer tekst in een willekeurige toepassing en druk op **Voorlezen** (of voer
`voxfox --read` uit). VoxFox leest de tekst voor met de stem van het actieve
slot. **Stop** stopt het afspelen; **Pauze** pauzeert en hervat.

## Twee taalslots

VoxFox houdt twee stem-/taalslots bij, zodat je snel kunt wisselen tussen
bijvoorbeeld Nederlands en Engels. De **NL/EN**-knop (en `voxfox --toggle-slot`)
wisselt het actieve slot. De taal, stem en snelheid van elk slot stel je in bij
**Instellingen**. Wanneer je de taal van slot 1 wijzigt, wordt de
hele interface meteen in die taal opnieuw weergegeven.

## Geschiedenis

VoxFox onthoudt je laatste 20 voorgelezen en gedicteerde items. Open **Menu →
Geschiedenis** om ze te zien: elk item kun je opnieuw laten voorlezen (▶) of naar
het klembord kopiëren om het te plakken waar je wilt. **Alles wissen** leegt de
lijst.

## Spraakmotor

Elk taalslot gebruikt **Piper** (ingebouwd, de standaard) of
**Speech-dispatcher**, waarmee VoxFox de stemmen van andere programma's
gebruikt, zoals espeak-ng, RHVoice of Voxin (installeer `python3-speechd`). Elk
slot heeft een voorbeeld: typ een zin en druk op **Afspelen**.

## Typen en uitspreken

**Menu → Typen en uitspreken** opent een venster waarin je een tekst typt en
VoxFox hem uitspreekt: druk op **Enter** of **Uitspreken**. Shift+Enter begint
een nieuwe regel, Escape stopt. De laatste 10 zinnen blijven staan onder
*Eerder gezegd*; klik op een zin om hem opnieuw te laten zeggen.
**Lijst wissen** haalt ze daar en uit Geschiedenis weg.

Zet **Tegels** aan voor een bord met woord- en zintegels: druk op *Ik*, *heb*,
*dorst* en VoxFox zegt "Ik heb dorst". Er zijn kant-en-klare tegels voor
Nederlands, Engels, Duits, Frans en Spaans, elk met een pictogram; bij **Tegels aanpassen** verander,
verplaats, verwijder of voeg je tegels toe, en geef je ze een afbeelding
(links, rechts of boven de tekst, hooguit 50 kB, vanzelf verkleind). Met
**F11** (of de knop rechtsboven) wordt het venster volledig scherm; het
hoofdvenster van VoxFox wordt dan geminimaliseerd.

## Uitspraakwoordenboek

VoxFox kan woorden herschrijven voordat ze worden uitgesproken — handig voor
namen, afkortingen en leenwoorden die de stem verkeerd uitspreekt. Open
**Instellingen → Uitspraak**; daar bewerk je het woordenboek voor de taal van
slot 1. Voeg regels toe als *woord → uitspreken als* (bijv. `VoxFox →
Voks-foks`, `GUI → goe-wie`) en gebruik **Test** om ze te beluisteren. Matching
gebeurt op hele woorden en hoofdletterongevoelig, en de regels gelden voor alles
wat in die taal wordt voorgelezen (Voorlezen, Muis, OCR).

## Afgebroken tekst voorlezen, en Instellingen → Algemeen

Bij het voorlezen van OCR-tekst of geselecteerde tekst (bijvoorbeeld gekopieerd
uit een pdf) voegt VoxFox regels die alleen zijn afgebroken samen tot echte
alinea's, zodat hij niet meer middenin een zin pauzeert. Je schakelt dit onder
**Instellingen → Algemeen** ("Afgebroken regels samenvoegen tot alinea's") — zet
het uit om elke regel apart voor te lezen (handig voor lijsten of code). Bij
Algemeen staat ook **Instellingen importeren/exporteren** om je configuratie te
bewaren of te verplaatsen, en de mappen voor documenten en tegelafbeeldingen.

## Dicteren (spraak naar tekst)

Druk op **Dicteren** (of `voxfox --whisper-toggle`) om de opname te starten; de
knop wordt rood en heet **Stop**; druk erop om te stoppen. VoxFox transcribeert
de audio en typt het resultaat in de toepassing die de focus heeft. Onder
**Instellingen → Dicteren** kies je het
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

Whisper kan een NVIDIA-GPU gebruiken. Onder **Instellingen → Dicteren →
Geavanceerd → Rekenen**:

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

- Met **Scherm** (`voxfox --ocr-select`) trek je een rechthoek op het scherm; de
  tekst daarbinnen wordt via OCR gelezen en voorgelezen. Het gebruikt de eigen
  schermafdruktool van je bureaublad, dus het werkt op zowel X11 als Wayland.
- **Bestand** opent een document, pdf of afbeelding en leest de tekst voor.

OCR gebruikt Tesseract. Het werkt al met alleen het pakket `tesseract-ocr` (plus
de taalgegevens, bijv. `tesseract-ocr-nld`); `pytesseract` is optioneel.

## Hover-modus

**Muis** (`voxfox --hover-toggle`) leest de interfacetekst onder de muisaanwijzer
voor, via de AT-SPI-toegankelijkheidsboom. Het werkt ook in de vensters van
VoxFox zelf.

Hiervoor moet de toegankelijkheidsbus aanstaan. De *Installatiehulp…* in het
menu kan die voor je aanzetten (het zet de GNOME-instelling
`toolkit-accessibility` aan); herstart daarna de betreffende toepassing.
Chromium-browsers moeten bovendien gestart worden met
`--force-renderer-accessibility`. Hover werkt het
betrouwbaarst op GTK- en Firefox-vensters.

## Altijd op de voorgrond

Het venster blijft boven andere vensters (net als de oude versie), via `wmctrl`.
Dit werkt op **X11**; op Wayland bepaalt de compositor de stapelvolgorde, dus
daar kan het zonder effect blijven.

## Sneltoetsen

VoxFox kan tot tien globale sneltoetsen voor je installeren — open
**Instellingen → Sneltoetsen**, wijzig eventueel een combinatie door erop te
klikken en de toetsen in te drukken, en kies dan **Sneltoetsen installeren**.
Dit werkt op Cinnamon, GNOME, LXQt, XFCE en KDE Plasma; er wordt niets
automatisch geïnstalleerd. Zes hebben een standaardtoets:

| Commando                   | Actie                        | Standaard |
|----------------------------|------------------------------|-----------|
| `voxfox --read`            | Geselecteerde tekst voorlezen| `Super+Z` |
| `voxfox --stop`            | Voorlezen stoppen            | `Super+X` |
| `voxfox --toggle-slot`     | Taal wisselen                | `Super+C` |
| `voxfox --whisper-toggle`  | Dicteren (spraak naar tekst) | `Super+W` |
| `voxfox --ocr-select`      | Schermgebied voorlezen (OCR) | `Super+A` |
| `voxfox --read-page`       | Webpagina voorlezen (experimenteel) | `Super+V` |

De andere vier hebben geen standaardtoets; geef ze eerst een toets als je ze
wilt gebruiken: OCR-selectie & vertaling (`voxfox --ocr-select-translate`),
Live transcriptie (`voxfox --live-toggle`), Vertaal & lees voor
(`voxfox --translate`) en Typen en uitspreken (`voxfox --type-speak`).

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

**De broncode** bestaat uit een backend-pakket plus een frontend en assets:

- `voxfox_core/` — de UI-onafhankelijke kern, een pakket met modules:
  `tts.py` (Piper-TTS), `stt.py` (Whisper-STT — lokaal, externe API,
  GPU-detectie), `ocr.py` (Tesseract-OCR met een CLI-terugval), `ipc.py` (de
  IPC-server), `state.py` (opslaan van instellingen/geschiedenis en de
  taaltabellen), `a11y.py` (toegankelijkheidshulp) en `common.py`. Het
  importeert geen enkele GUI-toolkit.
- `voxfox_gtk.py` — de GTK4-frontend (venster, instellingen, knoppen) plus de
  opdrachtregel; dit importeert `voxfox_core`.
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
- **Python / GTK:** Python 3.10+ en GTK 4.10+ (sinds 6.1): Ubuntu 24.04,
  Linux Mint 22, Debian 13, Fedora 38 of nieuwer. Ubuntu 22.04, Mint 21 en
  Debian 12 hebben een oudere GTK; daar kan het pakket niet geïnstalleerd
  worden.
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

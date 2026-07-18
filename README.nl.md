# VoxFox

Een schermlezer en dicteerprogramma voor Linux met een grafische (GTK4)
interface, stemkeuze en snelheidsregeling. Gebouwd op
[Piper](https://github.com/rhasspy/piper) (tekst-naar-spraak) en
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (spraak-naar-tekst).

VoxFox is bedoeld voor wie de computer met stem en oren wil *gebruiken* — een
lang artikel laten voorlezen tijdens de afwas, een e-mail dicteren zonder het
toetsenbord aan te raken, of een stuk code laten terugvoorlezen om een fout te
horen.

> De huidige versie is de GTK4-build, verpakt als Debian-`.deb`. De oudere
> Tkinter-versie wordt niet meer onderhouden.

## Installatie

**Debian, Ubuntu, Linux Mint** (en andere Debian-gebaseerde distributies):

```bash
sudo apt install ./voxfox_*_all.deb
```

**Fedora** (en andere RPM-gebaseerde distributies):

```bash
sudo dnf install ./voxfox-*.noarch.rpm
```

`apt` haalt de runtime-afhankelijkheden binnen (`python3-gi`,
`gir1.2-gtk-4.0`, `python3-pyatspi`, `at-spi2-core`) en beveelt de optionele
hulpmiddelen aan die sommige functies gebruiken (`tesseract-ocr`,
`poppler-utils`, `xdotool`, `wmctrl`, `gnome-screenshot`, `python3-pip`,
audiobibliotheken). Start via het programmamenu (onder *Toegankelijkheid*) of
met `voxfox`.

De `.deb` installeert alleen het programma. De Piper-engine, de standaardstemmen,
faster-whisper (dicteren) en de OCR-extra's worden **per gebruiker** bij het
eerste gebruik gedownload — klik op *Nu installeren* in de melding die de app
toont als Piper ontbreekt, of draai het headless:

```bash
voxfox --setup      # Piper-engine + standaardstemmen + faster-whisper + OCR-extra's
```

Terwijl een model of stem downloadt, verschijnt er onder de statusregel een
voortgangsbalk zodat je ziet hoe ver de download is.

## Eerste keer

Bij de eerste start merkt VoxFox dat Piper nog niet is geïnstalleerd en biedt
aan alles in te stellen. De setup downloadt:

- de Piper-binary naar `~/.piper/`
- twee standaardstemmen: Brits-Engels (`en_GB-alba-medium`) en Nederlands
  (`nl_NL-pim-medium`)
- `faster-whisper` (voor lokaal dicteren), via `pip --user`

Bij de eerste start wordt ook `~/.config/voxfox_state.json` aangemaakt (je
instellingen) en wordt er gelogd naar `~/.cache/voxfox.log`.

Voor hover-voorlezen moet de toegankelijkheidsbus aanstaan. Het venster
*VoxFox instellen…* in het menu kan die voor je aanzetten (het zet de
GNOME-instelling `toolkit-accessibility` om); herstart daarna het
betreffende programma (en start Chromium-browsers met
`--force-renderer-accessibility`).

## Het venster

Het hoofdvenster is bewust klein en omsluit zijn inhoud. Standaard zijn de
knoppen **Voorlezen**, **Stop**, **Pauzeren**, **Spreken** (dicteren),
**Zweven**, **Selecteren** en **OCR**, plus de taalwisselknop. Je kunt elke knop
tonen of verbergen en de volgorde wijzigen, en de hele interface schalen naar
75 %, 100 % of 125 % — beide onder **Instellingen → Interface** (zie hieronder).
De titelbalk heeft een **Instellingen**-knop (tandwiel) en een **Menu**-knop
(hamburger).

Onder de knoppen verschijnt een statusregel zolang er iets gebeurt; daarna
verbergt die zich weer. De statusregel is een live-gebied, zodat een schermlezer
meldingen als "Aan het voorlezen…" automatisch voorleest. Net daaronder toont
een voortgangsbalk de voortgang van een lopende download.

| Knop        | Functie                                                       |
|-------------|---------------------------------------------------------------|
| Voorlezen   | Lees de geselecteerde tekst voor                              |
| Stop        | Stop direct met voorlezen                                    |
| Pauzeren    | Pauzeer / hervat het voorlezen                               |
| Spreken     | Dicteren: neem je stem op; Whisper zet het om en typt het    |
| Zweven      | Hover-voorlezen aan/uit                                      |
| Selecteren  | Kies een schermgebied en lees de tekst voor (OCR)            |
| OCR         | Open een pdf of afbeelding en lees de tekst voor             |
| Taal        | Wissel tussen Taal 1 en Taal 2                               |
| Instellingen| Open instellingen (tabbladen: Taal 1/2, Dicteren, Uitspraak, Overig, Interface, Sneltoetsen) |
| Menu        | VoxFox instellen…, Geschiedenis, Over, Afsluiten |

## Tekst voorlezen

Selecteer tekst in een willekeurig programma en druk op **Voorlezen** (of je
sneltoets). De tekst wordt voorgelezen met de stem van het actieve slot. Lange
stukken worden in delen geknipt en achter elkaar voorgelezen, zodat je onderweg
kunt **Pauzeren** en **Stoppen**.

Wanneer de tekst uit OCR komt of uit een selectie die alleen is afgebroken
(bijvoorbeeld gekopieerd uit een pdf), voegt VoxFox die afgebroken regels eerst
samen tot echte alinea's, zodat hij niet middenin een zin pauzeert. Dat kun je
uitzetten onder *Instellingen → Overig* (zie hieronder).

## Twee taalslots

VoxFox houdt twee onafhankelijke stemslots bij — *Taal 1* en *Taal 2* — elk met
een eigen taal, stem en snelheid. De taalwisselknop schakelt er in één klik
tussen, veel sneller dan een keuzelijst heropenen als je regelmatig in twee
talen leest. De interfacetaal volgt slot 1.

## Uitspraakwoordenboek

VoxFox kan woorden herschrijven voordat ze worden uitgesproken — handig voor
namen, afkortingen en leenwoorden die de stem verkeerd uitspreekt. Open
*Instellingen → Uitspraak*; daar bewerk je het woordenboek voor de taal van
slot 1. Voeg regels toe als *woord → uitspreken als* (bijv. `VoxFox →
Voks-foks`, `GUI → goe-wie`), en gebruik de ▶-knop bij elke regel om dat ene
woord te beluisteren. Matching gebeurt op hele woorden en hoofdletterongevoelig,
en de regels gelden voor alles wat in die taal wordt voorgelezen (Voorlezen,
Zweven, OCR). Per taal opgeslagen in je instellingenbestand.

## Geschiedenis

VoxFox onthoudt je laatste 20 voorgelezen en gedicteerde items. Open *Menu →
Geschiedenis* om ze te zien: elk item kun je opnieuw laten voorlezen (▶) of naar
het klembord kopiëren om het te plakken waar je wilt. **Alles wissen** leegt de
lijst. Opgeslagen in `~/.config/voxfox_history.json`.

(Kopiëren in plaats van opnieuw typen: VoxFox staat altijd-bovenop en houdt
focus, dus getypte tekst zou in het verkeerde venster belanden — met kopiëren
plak je het waar je het echt wilt.)

## Instellingen → Overig

Het tabblad *Overig* bevat twee dingen:

- **Afgebroken regels samenvoegen tot alinea's** (standaard aan) — het
  samenvoeggedrag beschreven onder *Tekst voorlezen*. Zet het uit om elke regel
  apart voor te lezen, wat je wilt bij lijsten, code of adressen.
- **Instellingen importeren/exporteren** — sla de huidige configuratie op als
  JSON-bestand en zet 'm terug op een andere machine. Stemmen waarnaar een
  geïmporteerd bestand verwijst, worden bij het eerste gebruik automatisch
  gedownload.

```bash
# Op de bronmachine: Instellingen → Overig → Exporteren naar voxfox-settings.json
scp voxfox-settings.json andere-machine:~/
# Op de andere machine: open VoxFox, Instellingen → Overig → Importeren
```

## Instellingen → Interface

Met het tabblad *Interface* pas je de toolbar en de algehele grootte aan:

- **Interfacegrootte** — schaal het hele venster naar 75 %, 100 % of 125 %.
  Handig op high-DPI-schermen of als je grotere klikdoelen wilt.
- **Knopweergave** — toon de toolbarknoppen als *alleen icoon*, *icoon en
  tekst* of *alleen tekst*. Bij alleen-icoon blijft de tekst beschikbaar als
  tooltip, en schermlezers blijven in elke stand de knopnamen aankondigen.
- **Oriëntatie** — zet de knoppen *horizontaal* (rijen, de standaard) of
  *verticaal* (een smalle kolom die je aan de rand van je scherm kunt
  parkeren). Verticaal met alleen-icoon geeft de smalste vorm: de titelbalk
  krimpt tot alleen een sluitknop en de knoppen Instellingen en Menu
  verhuizen naar onderin de kolom.
- **Knoppen** — toon of verberg elke toolbarknop met een vinkje en wijzig de
  volgorde met de pijltjes omhoog/omlaag. Verberg de knoppen die je nooit
  gebruikt (bijvoorbeeld *Pauzeren* of *OCR*) om het venster compact te houden;
  de indeling wordt onthouden.

Het tabblad *Sneltoetsen* wordt behandeld onder **Sneltoetsen** hieronder.

## Spraak-naar-tekst (Whisper)

Klik op **Dicteren** om de opname te starten, klik nogmaals om te stoppen. De
omgezette tekst wordt dan getypt waar je cursor staat. Lange dictaten (meer dan
~200 tekens) worden via het klembord geplakt in plaats van getypt, zodat ze
direct verschijnen.

De instellingen staan op het tabblad *Dicteren*:

- **Model** — groter = nauwkeuriger maar trager en meer geheugen:
  - `tiny` — snelst, zwakke nauwkeurigheid
  - `base` — snel, prima voor Engels
  - `small` — aanbevolen standaard; goed meertalig
  - `medium` — beter, ~1,5 GB
  - `large-v3` — best, ~3 GB en traag op de CPU
- **Compute** — *Auto* gebruikt een NVIDIA-GPU als die wordt gevonden (CUDA +
  cuDNN), anders de CPU, en valt terug op de CPU als de GPU niet start
- **Microfoon** — kies een specifiek invoerapparaat of laat op *Standaard*
- **Transcriptie bevestigen voor het typen** — toon eerst een voorbeeldvenster met de transcriptie, zodat je die kunt nakijken en bewerken, en kopieer die daarna naar het klembord om zelf te plakken met Ctrl+V (in plaats van dat VoxFox het typt)
- **Backend** — *Lokaal* (draait faster-whisper hier) of *Remote API* (zie onder)

De taal van het actieve slot wordt als hint aan Whisper meegegeven, wat veel
betrouwbaarder is dan automatisch detecteren. Modellen worden bij het eerste
gebruik gedownload en gecachet onder `~/.cache/huggingface/`; gebruik de
downloadknop naast de modellijst om er vooraf één op te halen (met
voortgangsbalk).

### GPU-notities

*Auto* versnelt de grotere modellen als een CUDA-runtime en cuDNN aanwezig zijn.
Op oudere NVIDIA-kaarten (Pascal, bijv. een Tesla P40) gebruikt VoxFox het
`int8`-computetype in plaats van `float16` (dat zou crashen of traag zijn) en
loopt het de computetypes af voordat het terugvalt op de CPU. Piper TTS gebruikt
de meegeleverde CPU-build — die is al sneller dan realtime, dus daar is geen
GPU-build voor.

### Remote Whisper-API

Heb je een server met een GPU, stuur de transcriptie daar dan heen in plaats van
Whisper op de laptop te draaien. VoxFox spreekt de OpenAI Audio-API
(`POST /v1/audio/transcriptions`), die de meeste zelf-gehoste Whisper-servers
implementeren:

- [faster-whisper-server / Speaches](https://github.com/speaches-ai/speaches)
- [whisper.cpp server](https://github.com/ggerganov/whisper.cpp/tree/master/examples/server)
- [LocalAI](https://localai.io/) met de Whisper-backend
- de gehoste Whisper-API van OpenAI zelf

Zet **Backend** op *Remote API* en vul in:

- **URL** — de basis-URL, bijv. `http://gpu-box:8000/v1`. Schuine strepen aan
  het eind maken niet uit; VoxFox plakt er `/audio/transcriptions` achter.
- **Model** — de naam die je server verwacht (bijv.
  `Systran/faster-whisper-large-v3`, of `whisper-1` / `gpt-4o-transcribe` voor
  OpenAI).
- **API-sleutel** — optioneel; leeg voor de meeste zelf-gehoste servers.

Klik op **Test** om de verbinding te controleren zonder op te nemen. Is de
remote-server onbereikbaar of geeft die een fout tijdens het dicteren, dan valt
VoxFox terug op het lokale model zodat je de opname niet verliest, en de
statusregel meldt dat.

#### Voorbeeld: OpenAI

| Veld         | Waarde                             |
|--------------|------------------------------------|
| URL          | `https://api.openai.com/v1`        |
| Model        | `whisper-1` of `gpt-4o-transcribe` |
| API-sleutel  | `sk-...` (je OpenAI-API-sleutel)   |

#### Voorbeeld: faster-whisper-server (zelf-gehost op een GPU-machine)

```bash
docker run --gpus all -p 8000:8000 fedirz/faster-whisper-server:latest-cuda
```

| Veld         | Waarde                            |
|--------------|-----------------------------------|
| URL          | `http://gpu-box.local:8000/v1`    |
| Model        | `Systran/faster-whisper-large-v3` |
| API-sleutel  | (laat leeg)                       |

## OCR — pdf's, afbeeldingen en schermgebieden voorlezen

VoxFox kan tekst uit documenten en afbeeldingen halen en voorlezen:

- **OCR** opent een bestandskiezer. Kies een pdf of afbeelding (PNG, JPG, BMP,
  TIFF, WEBP). Pdf's met een echte tekstlaag worden direct gelezen via
  `pdftotext`; gescande pdf's en gewone afbeeldingen gaan automatisch via
  Tesseract-OCR.
- **Selecteren** maakt een schermafdruk, toont die schermvullend, en laat je een
  rechthoek om de gewenste tekst slepen (Escape annuleert). Het gebied wordt
  ge-OCR'd en voorgelezen met de actieve stem.

OCR-uitvoer krijgt de afgebroken regels samengevoegd tot alinea's (de
*Overig*-schakelaar), zodat het voorlezen vloeiend gaat in plaats van bij elke
regel te pauzeren.

De OCR-taal volgt het actieve slot. Staat slot 1 op Nederlands, dan gebruikt
Tesseract `nld+eng`. Installeer het bijbehorende taalpakket
(`tesseract-ocr-nld`, `tesseract-ocr-deu`, …).

### Vanaf de opdrachtregel

```bash
voxfox --ocr /pad/naar/document.pdf
voxfox --ocr /pad/naar/schermafdruk.png
```

Draait VoxFox, dan wordt de tekst ernaartoe gestuurd en voorgelezen. Zo niet,
dan wordt de tekst naar stdout geprint — handig voor scripts.

### OCR-afhankelijkheden

`apt` beveelt deze met het pakket aan; handmatig installeren:

```bash
sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-deu \
                 tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-ita \
                 tesseract-ocr-por poppler-utils gnome-screenshot
```

Voor **Selecteren** is een schermafdruktool nodig — `gnome-screenshot`,
`spectacle`, `scrot` (X11) of `grim`+`slurp` (Wayland). Voeg meer
`tesseract-ocr-<taal>`-pakketten toe voor extra talen.

## Hover-modus

Als de hover-modus aanstaat, wordt de tekst onder je muisaanwijzer automatisch
voorgelezen — zonder eerst te selecteren. Handig voor het doorlopen van lijsten,
menu's of slecht toegankelijke websites. Het werkt het best op X11 en XWayland;
op puur Wayland hangt het af van AT-SPI-gebeurtenissen, die niet elk programma
verstuurt, dus boven sommige vensters gebeurt er niets. Schakel met **Zweven**,
`--hover-toggle` of je sneltoets.

## Altijd op de voorgrond

Het venster blijft boven andere vensters. Dit gebeurt via `wmctrl` en geldt
alleen op X11; in een Wayland-sessie bepaalt de compositor de stapeling en kan
het niet worden afgedwongen. VoxFox dwingt de "boven"-status kort na de start af
en opnieuw zodra het de focus verliest, zodat een ander programma openen het niet
naar achteren duwt.

## Opdrachtregel

VoxFox draait als één instantie via een lokale Unix-socket. Als de GUI draait,
worden deze vlaggen ernaartoe doorgestuurd zodat een sneltoets direct werkt:

```
voxfox                    # Start de GUI (of focus de bestaande)
voxfox --read             # Lees de geselecteerde tekst voor
voxfox --pause            # Pauzeer / hervat het voorlezen
voxfox --stop             # Stop met voorlezen
voxfox --toggle-slot      # Wissel tussen Taal 1 en Taal 2
voxfox --hover-toggle     # Hover-modus aan/uit
voxfox --whisper-toggle   # Dicteren starten/stoppen (spraak-naar-tekst)
voxfox --ocr-select       # Kies een schermgebied en lees de tekst voor (OCR)
voxfox --ocr <bestand>    # OCR een pdf of afbeelding en lees voor (werkt zonder GUI)
voxfox --status           # Print of VoxFox draait
voxfox --quit             # Vraag de draaiende instantie te stoppen
voxfox --setup            # Download Piper + stemmen + Whisper, en stop
voxfox --verbose          # Debug-logging aanzetten
```

## Sneltoetsen

VoxFox kan zes globale sneltoetsen voor je instellen, maar doet dat nooit
automatisch — sommige bureaubladen gebruiken deze toetsen al voor iets anders.
Open **Instellingen → Sneltoetsen**, wijzig eventueel een combinatie (klik erop
en druk de gewenste toetsen in) en kies dan **Sneltoetsen installeren**. Ze
worden geschreven naar je bureaublad op **Cinnamon, GNOME, LXQt, XFCE en KDE Plasma** (op
Cinnamon wordt het bureaublad heel even herladen zodat de nieuwe toetsen meteen
werken). **Terug naar standaard** herstelt de originelen, en je kunt ze altijd
later wijzigen of verwijderen in de toetsenbordinstellingen van je bureaublad.

De zes installeerbare acties en hun standaardtoetsen:

| Actie           | Opdracht                  | Standaard |
|-----------------|---------------------------|-----------|
| Voorlezen       | `voxfox --read`           | `Super+Z` |
| Stop            | `voxfox --stop`           | `Super+X` |
| Taal wisselen   | `voxfox --toggle-slot`    | `Super+C` |
| Dicteren        | `voxfox --whisper-toggle` | `Super+W` |
| OCR-selectie    | `voxfox --ocr-select`     | `Super+A` |
| Webpagina voorlezen | `voxfox --read-page`  | `Super+V` |

Je kunt ook `voxfox --install-shortcuts` in een terminal draaien. Andere
opdrachten (`voxfox --pause`, `voxfox --hover-toggle`) zitten niet in de
installer maar kun je handmatig koppelen in de toetsenbordinstellingen van je
bureaublad — elke druk roept de draaiende instantie aan via de vlaggen
hierboven.

## Een webpagina voorlezen (experimenteel)

Selecteer het adres van de pagina — `Ctrl+L` in de browser selecteert de
adresbalk — en druk op `Super+V` (of voer `voxfox --read-page` uit). VoxFox
haalt de pagina zelf op en leest het artikel voor; de paginatitel verschijnt
in de statusregel zodat altijd duidelijk is welke pagina wordt voorgelezen.
Elke selectie met een URL erin werkt, dus een link in een e-mail of document
kan ook.

De extractie gaat in twee trappen:

1. De hoofdinhoud wordt structureel geëxtraheerd: menu's, banners, zijbalken,
   voetteksten en scripts worden overgeslagen, en een `<main>`/`<article>`-
   sectie wint als de pagina die markeert. Zonder AI, en er wordt nooit iets
   verzonnen.
2. Optioneel verfijnt een **AI (Ollama)** wat overblijft, in te stellen onder
   **Instellingen → Webpagina**: *Alleen filteren* behoudt de originele
   zinnen en haalt overgebleven reclame en snippers van andere artikelen weg;
   *Samenvatten* leest in plaats daarvan een spreekvriendelijke samenvatting.

Trap 2 vereist een draaiende [Ollama](https://ollama.com) met een gedownload
model (bijvoorbeeld `ollama pull llama3.2`). De URL, een optionele
**API-sleutel** (meegestuurd als Bearer-token, voor Ollama achter een reverse
proxy op een andere machine) en de modelnaam zijn instelbaar; *Test
verbinding* toont de gevonden modellen. Is Ollama niet bereikbaar, dan valt
VoxFox terug op de tekst uit trap 1.

Let op: het ophalen ziet de pagina als anonieme bezoeker, dus inhoud achter
een login kan afwijken van wat de browser toont. Pagina's die alleen met
JavaScript renderen worden automatisch opnieuw geprobeerd in een headless
(onzichtbare) Chromium als die geïnstalleerd is — Chromium, Chrome, Brave en
Edge worden herkend. Zonder geselecteerde URL valt VoxFox terug op het voorlezen van het
actieve tabblad via AT-SPI (vereist de toegankelijkheidsbus; Chromium heeft
`--force-renderer-accessibility` nodig).

## Snelheid aanpassen

Elk taalslot heeft een eigen snelheidsschuif (0,5x–2,0x), zodat je slot 1 op
1,0x kunt houden voor zorgvuldig lezen en slot 2 sneller voor scannen. 1,3x is
voor de meeste mensen prettig snellezen zodra je aan de stem gewend bent.

## Interfacetaal

De interface volgt **de taal van slot 1**: zet je die op Duits, dan schakelen de
knoppen, tooltips, menu's en meldingen naar het Duits; zet je 'm op Frans, dan
schakelt alles naar het Frans. Engels, Nederlands, Duits, Frans, Spaans,
Italiaans, Portugees, Chinees, Arabisch en Grieks zijn standaard aanwezig. Kies je
Arabisch, dan klapt de hele interface om naar rechts-naar-links. Chinees, Arabisch
en Grieks hebben ook Piper-stemmen en werken voor dicteren en OCR — voor OCR
installeer je het bijbehorende Tesseract-pakket (`tesseract-ocr-chi-sim`,
`tesseract-ocr-ara` of `tesseract-ocr-ell`).

De vertaalbestanden staan in `~/.piper/locales/`, één JSON per taal. Om een
vertaling te verbeteren of een taal toe te voegen: kopieer `en.json` naar
`<code>.json`, zet `_meta.name` op de eigen naam van de taal, vertaal de
rechterkant van elke regel (laat de Engelse sleutels links staan) en herstart
VoxFox. Ontbrekende regels vallen terug op het Engels, dus gedeeltelijke
vertalingen werken prima.

## Toegankelijkheid

Knoppen hebben toegankelijke namen en tooltips, de statusregel is een
live-gebied, en labels vermijden emoji (die sommige schermlezers teken voor
teken voorlezen). Hover-voorlezen en het aanzetten van de toegankelijkheidsbus
(via het venster *VoxFox instellen…*) staan hierboven beschreven.

## Afhankelijkheden

Door het pakket geïnstalleerd:

- `python3-gi`, `gir1.2-gtk-4.0` — de GTK4-interface
- `python3-pyatspi`, `at-spi2-core` — hover-voorlezen

Aanbevolen (schakelen specifieke functies in): `tesseract-ocr` + taalpakketten
en `poppler-utils` (OCR), `xdotool` (dicteren typen op X11), `wmctrl`
(altijd-bovenop), `gnome-screenshot` (schermgebied kiezen), `python3-pip`
(faster-whisper installeren) en audiobibliotheken.

Per gebruiker bij het eerste gebruik gedownload: de Piper-engine en -stemmen, en
`faster-whisper` voor lokaal dicteren.

## Waar dingen staan

| Pad                               | Inhoud                              |
|-----------------------------------|-------------------------------------|
| `~/.piper/`                       | Piper-engine en gedownloade stemmen |
| `~/.piper/locales/`               | Vertaalbestanden van de interface   |
| `~/.config/voxfox_state.json`     | Je instellingen                     |
| `~/.config/voxfox_history.json`   | Voorlees-/dicteergeschiedenis       |
| `~/.cache/huggingface/`           | Gecachete Whisper-modellen          |
| `~/.cache/voxfox.log`             | Logbestand                          |
| `/usr/lib/voxfox/`                | Programmacode                       |
| `/usr/share/voxfox/locales/`      | Meegeleverde vertalingen            |

## Ondersteunde systemen

Debian, Ubuntu, Linux Mint en afgeleiden met GTK4 (via de `.deb`), en Fedora
(via de `.rpm`, getest op Fedora Workstation; andere RPM-distributies zoals
openSUSE kunnen andere pakketnamen nodig hebben en zijn niet getest). X11 geeft
het volledige pakket aan functies (zweven, altijd-bovenop, schermgebied kiezen
via `xdotool`/schermafdruktools). Wayland werkt voor het kern-voorlezen en
dicteren, maar altijd-bovenop en delen van zweven hangen af van de compositor en
kunnen beperkt zijn.

## Voor ontwikkelaars

De code is gesplitst in een UI-onafhankelijke backend (het `voxfox_core/`-pakket
— `tts.py`, `stt.py`, `ocr.py`, `ipc.py`, `state.py`, `a11y.py`, `common.py`) en
een GTK4-frontend (`voxfox_gtk.py`, die ook de CLI bevat). Vertalingen zijn
gewone JSON-bestanden onder `locales/`, met uitgelijnde sleutels over alle talen.
Zie `CHANGELOG.md` voor de versiegeschiedenis.

Scripts voor verpakken en uitbrengen staan in `packaging/`:

- `VERSION=x.y bash packaging/build-deb.sh` bouwt het Debian-pakket en
  `VERSION=x.y bash packaging/build-rpm.sh` het RPM-pakket (Fedora). Beide
  spiegelen dezelfde bestandsindeling en bundelen `locales/` en, indien
  aanwezig, `dicts/`.
- De download van de Piper-engine is vastgezet op `PIPER_VERSION` in
  `voxfox_gtk.py` en wordt vóór het uitpakken gecontroleerd tegen de
  SHA-256-sommen in `PIPER_SHA256`. Bij het ophogen van `PIPER_VERSION`
  genereer je die sommen opnieuw met `python3 packaging/pin_piper_hashes.py`
  op een machine met internet, en plak je de uitvoer over het
  `PIPER_SHA256`-blok.
- `packaging/merge_dict.py` voegt aangedragen uitspraakwoorden (een CSV van
  `taal;woord;uitspraak`) samen in de meegeleverde woordenboeken in `dicts/`.

## Probleemoplossing

**"Geen spraak gedetecteerd" na dicteren** — microfoon gedempt op OS-niveau, het
verkeerde invoerapparaat gekozen op het tabblad Dicteren, te zacht gesproken
(Whisper laat bijna-stilte vallen), of een fragment korter dan ~0,3 s.

**Voorlezen doet niets / "Niets geselecteerd"** — VoxFox leest de X11-*primaire*
selectie op X11/XWayland en het *klembord* op puur Wayland. Op Wayland met een
programma dat het klembord niet synchroniseert: kopieer eerst expliciet
(`Ctrl+C`).

**Zweven reageert niet in sommige programma's** — zweven leunt op
AT-SPI-gebeurtenissen; sommige programma's (met name Electron-apps) versturen die
spaarzaam of niet. Gebruik dan Voorlezen op een selectie.

**Selecteren doet niets** — er is geen schermafdruktool geïnstalleerd. Installeer
`gnome-screenshot`, `spectacle`, `scrot` (X11) of `grim`+`slurp` (Wayland).

**Remote Whisper loopt vast** — de remote-backend heeft een time-out van 60
seconden per verzoek. Gebruik een sneller model op de server, of maak kortere
opnames.

**OCR geeft onzin** — het Tesseract-taalpakket voor het actieve slot is niet
geïnstalleerd. Controleer met `tesseract --list-langs`; installeer bijv.
`sudo apt install tesseract-ocr-nld`.

**Voorlezen pauzeert raar / voegt dingen samen die niet samen horen** — zet
*Instellingen → Overig → Afgebroken regels samenvoegen tot alinea's* uit (of aan)
naargelang de tekst die je leest.

**Al het andere** — VoxFox logt naar `~/.cache/voxfox.log`; start met
`voxfox --verbose` voor debug-meldingen.

## Verwijderen

```bash
sudo apt remove voxfox
```

Gebruikersgegevens (instellingen, geschiedenis, gedownloade stemmen, gecachete
Whisper-modellen) staan in je thuismap en blijven ongemoeid; verwijder ze
handmatig voor een schone start:

```bash
rm -rf ~/.piper ~/.config/voxfox_state.json ~/.config/voxfox_history.json
```

## Licentie

VoxFox is vrije software onder de GNU General Public License v3 (of later).
Copyright (C) 2025 Daniël Vos. Zie `licence.txt` voor de volledige tekst.

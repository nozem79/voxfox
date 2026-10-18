#!/usr/bin/env bash
# VoxFox -- volledige verwijdering, voor het testen van een schone installatie.
#
# Verwijdert:
#   - het geïnstalleerde pakket (apt remove --purge voxfox)
#   - ~/.config/voxfox/        (instellingen, geschiedenis)
#   - ~/.local/share/voxfox/   (gedownloade stemmen, migratiemarker)
#   - ~/.cache/voxfox/         (logbestand)
#   - ~/.piper/                (Piper-engine + eventuele niet-gemigreerde
#                                oude stemmen -- ja, ook de engine zelf, zodat
#                                de eerste-installatie-flow volledig opnieuw
#                                doorlopen wordt)
#   - losse instellingenbestanden van vóór de XDG-opschoning
#
# Whisper-modellen (via $HF_HOME, standaard ~/.cache/huggingface) worden NIET
# verwijderd -- die map kan door andere programma's gedeeld worden. Gebruik
# --with-whisper om ook VoxFox's eigen faster-whisper-modellen mee te wissen
# (raakt geen andere Hugging Face-modellen aan, alleen de
# modellen--Systran--faster-whisper-*-mappen).
#
# Niets wordt aangeraakt zonder expliciete bevestiging. Veilig om opnieuw te
# draaien als sommige dingen al weg zijn.

set -euo pipefail

CONFIG_DIR="$HOME/.config/voxfox"
DATA_DIR="$HOME/.local/share/voxfox"
CACHE_DIR="$HOME/.cache/voxfox"
PIPER_DIR="$HOME/.piper"
LEGACY_STATE="$HOME/.config/voxfox_state.json"
LEGACY_HISTORY="$HOME/.config/voxfox_history.json"
LEGACY_TK_STATE="$HOME/.config/hover_speak_gui_state.json"

WITH_WHISPER=0
if [ "${1:-}" = "--with-whisper" ]; then
    WITH_WHISPER=1
fi

echo "Dit verwijdert:"
echo "  - het VoxFox-pakket zelf (apt remove --purge voxfox)"
echo "  - $CONFIG_DIR   (instellingen, geschiedenis)"
echo "  - $DATA_DIR   (gedownloade stemmen, migratiemarker)"
echo "  - $CACHE_DIR   (logbestand)"
echo "  - $PIPER_DIR   (Piper-engine + eventuele niet-gemigreerde oude stemmen)"
echo "  - losse instellingenbestanden van vóór de XDG-opschoning"
echo
if [ "$WITH_WHISPER" = "1" ]; then
    echo "  - VoxFox's eigen faster-whisper-modellen (--with-whisper is gezet)"
else
    echo "Whisper-modellen worden NIET verwijderd (gebruik --with-whisper om dat wel te doen)."
fi
echo
read -rp "Doorgaan? Typ 'ja' om te bevestigen: " confirm
if [ "$confirm" != "ja" ]; then
    echo "Geannuleerd, niets is verwijderd."
    exit 0
fi

echo
echo "== Pakket verwijderen =="
if dpkg -s voxfox >/dev/null 2>&1; then
    sudo apt remove --purge -y voxfox
else
    echo "voxfox is niet als pakket geïnstalleerd (of al verwijderd), sla over."
fi

echo
echo "== Gebruikersbestanden verwijderen =="
for d in "$CONFIG_DIR" "$DATA_DIR" "$CACHE_DIR" "$PIPER_DIR"; do
    if [ -d "$d" ]; then
        echo "verwijderen: $d"
        rm -rf -- "$d"
    fi
done
for f in "$LEGACY_STATE" "$LEGACY_HISTORY" "$LEGACY_TK_STATE"; do
    if [ -f "$f" ]; then
        echo "verwijderen: $f"
        rm -f -- "$f"
    fi
done

if [ "$WITH_WHISPER" = "1" ]; then
    echo
    echo "== Whisper-modellen verwijderen =="
    hf_hub="${HF_HOME:-$HOME/.cache/huggingface}/hub"
    if [ -d "$hf_hub" ]; then
        found=0
        for m in "$hf_hub"/models--Systran--faster-whisper-*; do
            [ -d "$m" ] || continue
            echo "verwijderen: $m"
            rm -rf -- "$m"
            found=1
        done
        [ "$found" = "0" ] && echo "geen faster-whisper-modellen gevonden in $hf_hub"
    else
        echo "$hf_hub bestaat niet, niets te verwijderen"
    fi
fi

echo
echo "Klaar. VoxFox is volledig verwijderd, inclusief alle instellingen."
echo "Een nieuwe installatie (sudo dpkg -i voxfox_*.deb) start nu helemaal vers."

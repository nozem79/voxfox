#!/usr/bin/env python3
# Copyright (C) 2025 - Daniël Vos
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""voxfox_core.voices — Piper voices: the online catalogue, the voices on
disk, friendly names, choosing the best voice, and downloading.
"""

import hashlib, json, os, shutil, time, urllib.request
from .common import BASE_URL, CONFIG_DIR, DATA_DIR, PIPER_DIR, VOICES_URL, log


# ── Voice data ─────────────────────────────────────────────────────────────────
class _VoiceCache:
    """The downloaded voice list and when it was fetched."""

    def __init__(self):
        self.data = {}
        self.ts = 0


_voice_cache = _VoiceCache()
VOICES_CACHE_TTL = 300  # 5 minutes


def fetch_voices(force=False):
    now = time.monotonic()
    if not force and _voice_cache.data and (now - _voice_cache.ts) < VOICES_CACHE_TTL:
        return _voice_cache.data
    try:
        with urllib.request.urlopen(VOICES_URL, timeout=10) as r:
            _voice_cache.data    = json.loads(r.read().decode())
            _voice_cache.ts = now
    except Exception as e:
        log.error(f"Could not fetch voice list: {e}")
    return _voice_cache.data


def get_languages(voices):
    langs = set()
    for info in voices.values():
        name = info.get("language", {}).get("name_english", "")
        if name:
            langs.add(name)
    return sorted(langs)


def get_voices_for_lang(voices, lang):
    return {k: v for k, v in voices.items()
            if v.get("language", {}).get("name_english", "") == lang}


# Where a Piper voice's .onnx/.onnx.json is looked up, in priority order
# (first match wins). Only VOICES_USER_DIR (layer 1) is ever written to or
# deleted from; the rest are legacy or system locations, read-only as far
# as VoxFox is concerned. Mirrors the layered pattern already used for the
# bundled pronunciation dictionaries (see state.py's
# load_builtin_pronunciations() / AppState.pron_for()) -- personal always
# overrides system, for the same reason: a user's own choice should win,
# and the system layer may be a read-only squashfs (FoxOS) with nothing
# to gain from ever trying to write to it.
def _voice_search_dirs():
    return [
        os.path.join(DATA_DIR, "voices"),    # ~/.local/share/voxfox/voices (current, writable)
        os.path.join(CONFIG_DIR, "voices"),  # ~/.config/voxfox/voices (legacy, read-only)
        PIPER_DIR,                            # ~/.piper (legacy, read-only; also holds the engine)
        "/usr/share/voxfox/voices",           # system, e.g. bundled by FoxOS (read-only)
    ]


def _safe_move_file(src, dst):
    """Move `src` to `dst` without ever deleting `src` unless `dst` is
    first confirmed to be a complete copy. A failure partway through --
    permissions, a full disk, a cross-filesystem hiccup -- always leaves
    the original exactly where it was, with nothing lost and no partial
    file left behind at the destination. Returns True on success."""
    tmp = dst + ".migrating"
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            return False
        shutil.copy2(src, tmp)
        if os.path.getsize(tmp) != os.path.getsize(src):
            os.remove(tmp)
            return False
        os.replace(tmp, dst)   # atomic rename into place
        os.remove(src)         # only remove the original once dst is real
        return True
    except OSError as e:
        log.warning(f"Could not migrate {src} -> {dst}: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def migrate_legacy_voices():
    """One-time move of voice files from legacy locations
    (~/.config/voxfox/voices, ~/.piper) into the current
    ~/.local/share/voxfox/voices, so a live/read-only home doesn't force
    every session to redownload them. Moves rather than copies, so large
    voice files don't end up duplicated on disk -- but see
    _safe_move_file(): a failed move leaves the legacy file exactly where
    it was, and voice resolution simply keeps falling through to that
    legacy layer, same as if migration had never run. Gated by a marker
    file so this only ever runs once; never touches the read-only system
    layer, and never touches anything but .onnx/.onnx.json files, so the
    Piper engine itself (which also lives in the legacy ~/.piper) is left
    completely alone.
    """
    marker = os.path.join(DATA_DIR, ".migrated")
    if os.path.isfile(marker):
        return
    user_dir = voices_user_dir()
    moved = []
    for src_dir in (os.path.join(CONFIG_DIR, "voices"), PIPER_DIR):
        if not os.path.isdir(src_dir):
            continue
        try:
            names = os.listdir(src_dir)
        except OSError:
            continue
        for fname in names:
            if not (fname.endswith(".onnx") or fname.endswith(".onnx.json")):
                continue
            src = os.path.join(src_dir, fname)
            dst = os.path.join(user_dir, fname)
            if os.path.isfile(dst):
                continue  # user layer already has this one; leave the legacy copy alone
            if _safe_move_file(src, dst):
                moved.append(f"{src} -> {dst}")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: migrated "
                   f"{len(moved)} voice file(s)\n")
    except OSError as e:
        log.warning(f"Could not write migration marker {marker}: {e}")
    if moved:
        log.info("Migrated voice files:\n  " + "\n  ".join(moved))


def voices_user_dir():
    """The one directory a new voice is ever downloaded into. Always the
    first search layer, so a freshly downloaded voice is found again
    immediately and takes priority over any same-named system voice."""
    return os.path.join(DATA_DIR, "voices")


def find_voice_dir(voice_key):
    """The directory actually holding `voice_key`'s .onnx file, searched
    in priority order across _voice_search_dirs(), or None if it isn't in
    any of them. A voice present in more than one layer resolves to the
    highest-priority one -- a personal copy always wins over a system or
    other legacy one of the same name."""
    for d in _voice_search_dirs():
        if d and os.path.isfile(os.path.join(d, f"{voice_key}.onnx")):
            return d
    return None


_QUALITIES = ("x_low", "low", "medium", "high")


def voice_display_parts(voice_key):
    """Split a Piper voice key into the parts people care about.

    "nl_NL-alex-medium" -> ("Alex", "NL", "medium"), "en_US-lessac-high"
    -> ("Lessac", "US", "high"), "de_DE-mls_6892-low" -> ("Mls 6892", "DE",
    "low"). Anything that does not look like a Piper key comes back as
    (key, "", "") so it is still shown as it is."""
    parts = (voice_key or "").split("-")
    if len(parts) < 3 or parts[-1] not in _QUALITIES or "_" not in parts[0]:
        return (voice_key or "", "", "")
    region = parts[0].split("_", 1)[1].upper()
    name = " ".join(w.capitalize() for w in "-".join(parts[1:-1]).replace("_", " ").split())
    return (name or voice_key, region, parts[-1])


_QUALITY_RANK = {"x_low": 0, "low": 1, "medium": 2, "high": 3}


def best_voice_for_lang(keys, local, lang):
    """The voice to pick when a slot switches to `lang`.

    `keys` are the catalogue's voices for that language, `local` the voices
    already downloaded. Before, the first downloaded voice in alphabetical
    order won, which for Dutch could be a very-low-quality Flemish voice.

    Order of preference:
    1. VoxFox's own default voice for the language, if it is downloaded.
    2. The best downloaded voice: the language's home region first ("NL"
       for Dutch, "DE" for German), then the highest quality.
    3. Nothing downloaded: the default voice if the catalogue has it,
       otherwise the best voice of the catalogue (it will be downloaded).
    """
    from .common import DEFAULT_VOICE_FOR_LANG, PIPER_LANG_TO_CODE
    keys = list(keys or [])
    if not keys:
        return ""
    default = DEFAULT_VOICE_FOR_LANG.get(lang or "")
    home = (PIPER_LANG_TO_CODE.get(lang or "", "") or "").upper()

    def score(k):
        _name, region, quality = voice_display_parts(k)
        return (region == home and bool(home), _QUALITY_RANK.get(quality, -1))

    def best(pool):
        # max() keeps the first of equal scores; sorting first makes that
        # the alphabetically first, so the choice is always the same.
        return max(sorted(pool), key=score)

    downloaded = [k for k in keys if k in (local or ())]
    if default in downloaded:
        return default
    if downloaded:
        return best(downloaded)
    if default in keys:
        return default
    return best(keys)


def get_local_voices():
    """Every voice key available in ANY search layer (user, legacy, or
    system) -- used to decide whether a voice still needs downloading, so
    a voice already present system-wide is correctly treated as local."""
    found = set()
    for d in _voice_search_dirs():
        if not d or not os.path.isdir(d):
            continue
        try:
            found.update(f[:-5] for f in os.listdir(d) if f.endswith(".onnx"))
        except OSError:
            continue
    return found


def download_voice(voice_key, progress_cb=None, cancel_evt=None, frac_cb=None):
    """Download a Piper voice. Returns (ok, message).

    If cancel_evt is set during the download, the partial file is removed
    and (False, 'cancelled') is returned.
    frac_cb(fraction, label): optional per-file download-progress callback.
    """
    voices = fetch_voices()
    if voice_key not in voices:
        return False, f"Voice not found: {voice_key}"
    # Downloads always land in the user's own directory (layer 1) -- never
    # in a legacy or system location, which may not even be writable
    # (a read-only squashfs on FoxOS). ~/.local/share/voxfox/voices is a
    # normal part of the user's own home, so creating it is expected to
    # succeed; any failure here surfaces through the existing try/except
    # below exactly as a download failure already would.
    os.makedirs(voices_user_dir(), exist_ok=True)
    for filename in voices[voice_key].get("files", {}):
        if not (filename.endswith(".onnx") or filename.endswith(".onnx.json")):
            continue
        dest = os.path.join(voices_user_dir(), os.path.basename(filename))
        if os.path.isfile(dest):
            continue
        url = f"{BASE_URL}/{filename}"
        if progress_cb:
            progress_cb(f"Downloading: {os.path.basename(filename)}...")
        if cancel_evt is not None and cancel_evt.is_set():
            return False, "cancelled"

        tmp = dest + ".part"
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                hasher = hashlib.md5(usedforsecurity=False)
                while True:
                    if cancel_evt is not None and cancel_evt.is_set():
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        return False, "cancelled"
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if frac_cb and total:
                        frac_cb(done / total, os.path.basename(filename))
            # Verify against Piper's published digest when the voices.json
            # entry for this file has one. Best-effort, like install_piper's
            # own SHA-256 check: an entry without a digest is accepted as
            # before rather than treated as a failure.
            expected = voices[voice_key]["files"][filename].get("md5_digest")
            if expected and hasher.hexdigest() != expected:
                os.unlink(tmp)
                return False, (f"checksum mismatch for {filename}: "
                               f"expected {expected[:12]}\u2026, "
                               f"got {hasher.hexdigest()[:12]}\u2026")
            os.replace(tmp, dest)
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
            return False, str(e)
    return True, "Done"


__all__ = [
    "VOICES_CACHE_TTL",
    "fetch_voices",
    "get_languages",
    "get_voices_for_lang",
    "get_local_voices",
    "voice_display_parts",
    "best_voice_for_lang",
    "voices_user_dir",
    "find_voice_dir",
    "migrate_legacy_voices",
    "download_voice",
]

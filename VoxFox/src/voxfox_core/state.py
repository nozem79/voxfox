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


"""voxfox_core.state — Persistent state and history (load/save, atomic writes, migration)."""

import copy, json, locale, os, tempfile, time
from .common import HISTORY_FILE, HISTORY_SIZE, LEGACY_HISTORY_FILE, LEGACY_STATE_FILE, LEGACY_TK_STATE_FILE, STATE_FILE, log, set_language, ui_code_for_piper_lang


# Map a 2-letter system locale code to (Piper language name, default voice).
# Used only on a fresh install to pick the starting language from $LANG.
_LOCALE_TO_LANG_VOICE = {
    "en": ("English",    "en_GB-alba-medium"),
    "nl": ("Dutch",      "nl_NL-pim-medium"),
    "de": ("German",     "de_DE-thorsten-medium"),
    "fr": ("French",     "fr_FR-siwis-medium"),
    "es": ("Spanish",    "es_ES-davefx-medium"),
    "it": ("Italian",    "it_IT-riccardo-x_low"),
    "pt": ("Portuguese", "pt_PT-tugão-medium"),
}


def _system_locale_code():
    """Return the 2-letter language code from the system locale, or 'en'.
    Checks the standard environment variables first (most reliable on Linux),
    then falls back to Python's locale module."""
    for var in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        val = os.environ.get(var, "")
        if val and val not in ("C", "POSIX"):
            # e.g. "nl_NL.UTF-8" → "nl", "de_DE" → "de"
            code = val.split(".")[0].split("_")[0].lower()
            if code:
                return code
    try:
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
        if loc:
            return loc.split("_")[0].lower()
    except Exception:
        pass
    return "en"


def _system_default_slots():
    """Build slot1/slot2 for a fresh install based on the system language.
    slot1 = system language; slot2 = English (or Dutch if system is English),
    so there's always a sensible second slot to toggle to."""
    code = _system_locale_code()
    lang, voice = _LOCALE_TO_LANG_VOICE.get(code, _LOCALE_TO_LANG_VOICE["en"])
    slot1 = {"lang": lang, "voice": voice, "speed": 1.0, "pitch": 0.0}
    # Second slot: English by default, but Dutch if the system is already English
    if code == "en":
        slot2 = {"lang": "Dutch", "voice": "nl_NL-pim-medium",
                 "speed": 1.0, "pitch": 0.0}
    else:
        slot2 = {"lang": "English", "voice": "en_GB-alba-medium",
                 "speed": 1.0, "pitch": 0.0}
    log.info(f"Fresh install: system locale '{code}' → slot1 language '{lang}'")
    return slot1, slot2


# ── Default state ─────────────────────────────────────────────────────────────
DEFAULT_STATE = {
    "slot1": {"lang": "English", "voice": "en_GB-alba-medium", "speed": 1.0, "pitch": 0.0},
    "slot2": {"lang": "Dutch",   "voice": "nl_NL-pim-medium",  "speed": 1.0, "pitch": 0.0},
    "active_slot": "slot1",
    "whisper": {
        "model": "small",          # tiny / base / small / medium / large-v3
        "mic_id": "",              # PulseAudio source name; "" = system default
        "confirm_before_typing": False,  # ask before typing transcription
        # Remote API support. When backend == "remote", transcription is sent
        # to an OpenAI-compatible /v1/audio/transcriptions endpoint instead
        # of running locally. If the remote call fails (network, auth, 5xx),
        # we fall back to the local model so a dictation never silently
        # drops. The remote_* fields are ignored when backend == "local".
        "backend":        "local",   # "local" | "remote"
        "remote_url":     "",        # base URL, e.g. "http://gpu-box:8000/v1"
        "remote_model":   "Systran/faster-whisper-large-v3",
        "remote_api_key": "",        # optional; sent as "Authorization: Bearer ..."
    },
    # Join lines that are merely word-wrapped (OCR output, copied PDF text) into
    # flowing paragraphs before reading, so TTS only pauses at real paragraphs.
    "merge_lines": True,
    # Per-language pronunciation dictionary: { piper_language_name: {word: respelling} }.
    # Applied to text before it is sent to Piper TTS.
    "pronunciations": {},
    # ui_lang is kept here for backwards-compat with older state files,
    # but is now derived from slot1["lang"] at runtime and ignored on load.
    "ui_lang": "en",
    # Last on-screen window position [x, y], saved on close and restored on
    # the next start. X11 only (GTK4 has no portable window positioning).
    "win_pos": None,
    # Set once the default desktop shortcuts (Super+Z/X/C/W/A) have been
    # registered, so user edits/removals in the system settings stick.
    "shortcuts_installed": False,
}


def load_state():
    # init_storage() copies any legacy file to STATE_FILE on startup; this
    # read-only fallback keeps load_state() correct even if called on its own.
    path = STATE_FILE
    if not os.path.isfile(path):
        for old in (LEGACY_STATE_FILE, LEGACY_TK_STATE_FILE):
            if os.path.isfile(old):
                path = old
                break

    # No state file at all → fresh install. Build defaults from the system
    # language so the UI and first voice match the user's locale.
    if not os.path.isfile(path):
        s = copy.deepcopy(DEFAULT_STATE)
        slot1, slot2 = _system_default_slots()
        s["slot1"] = slot1
        s["slot2"] = slot2
        ui_code = ui_code_for_piper_lang(s["slot1"].get("lang", ""))
        set_language(ui_code)
        return s

    try:
        with open(path) as f:
            s = json.load(f)
            for slot in ["slot1", "slot2"]:
                if slot not in s:
                    s[slot] = copy.deepcopy(DEFAULT_STATE[slot])
                s[slot].setdefault("speed", 1.0)
                s[slot].setdefault("pitch", 0.0)
                s[slot].setdefault("lang", "")
            # Whisper config (added later; fill in for old state files)
            w = s.setdefault("whisper", {})
            w.setdefault("model",   DEFAULT_STATE["whisper"]["model"])
            w.setdefault("mic_id",  DEFAULT_STATE["whisper"]["mic_id"])
            w.setdefault("confirm_before_typing",
                         DEFAULT_STATE["whisper"]["confirm_before_typing"])
            s.setdefault("merge_lines",  DEFAULT_STATE["merge_lines"])
            s.setdefault("pronunciations", {})
            s.setdefault("win_pos", None)
            s.setdefault("shortcuts_installed", False)
            # UI language now follows Slot 1 automatically (the ui_lang field
            # in the state file is ignored — kept around only so older state
            # files don't crash).
            ui_code = ui_code_for_piper_lang(s["slot1"].get("lang", ""))
            set_language(ui_code)
            return s
    except Exception:
        s = copy.deepcopy(DEFAULT_STATE)
        ui_code = ui_code_for_piper_lang(s["slot1"].get("lang", ""))
        set_language(ui_code)
        return s


def _atomic_write_json(path, obj, mode=0o600):
    """Write JSON to `path` atomically and with restricted permissions.

    Writes to a uniquely-named temp file in the same directory, fsyncs it,
    sets the file mode, then os.replace()s it over the target. os.replace
    is atomic within one filesystem, so a crash or full disk mid-write
    leaves the previous file intact instead of a truncated/corrupt one.

    The 0o600 default keeps files that may contain private text (read/
    dictation history) or secrets (the remote Whisper API key) readable
    only by the owner — a plain open() would inherit the umask (often
    world-readable 0o644).
    """
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Best-effort: FAT32/exFAT (e.g. a VoxMob USB stick) don't support Unix
        # permissions and chmod can raise EPERM there. The restricted mode is a
        # hardening nicety, not a requirement — never let it block the save.
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_state(state):
    _atomic_write_json(STATE_FILE, state, mode=0o600)


def load_history():
    """Return list of {kind, text, ts} dicts, newest first."""
    path = HISTORY_FILE if os.path.isfile(HISTORY_FILE) else LEGACY_HISTORY_FILE
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def save_history(items):
    try:
        _atomic_write_json(HISTORY_FILE, items, mode=0o600)
    except Exception as e:
        log.warning(f"Could not save history: {e}")


def add_history(kind, text):
    """Prepend a {read,dictate} item. Returns the new list (capped at HISTORY_SIZE)."""
    if not text or not text.strip():
        return load_history()
    items = load_history()
    # Drop an immediate duplicate (same kind + same text as the most recent entry).
    if items and items[0].get("text") == text and items[0].get("kind") == kind:
        return items
    items.insert(0, {"kind": kind, "text": text, "ts": int(time.time())})
    items = items[:HISTORY_SIZE]
    save_history(items)
    return items


__all__ = [
    "DEFAULT_STATE",
    "load_state",
    "_atomic_write_json",
    "save_state",
    "load_history",
    "save_history",
    "add_history",
]

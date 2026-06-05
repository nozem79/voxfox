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

import copy, json, os, tempfile, time
from .common import HISTORY_FILE, HISTORY_SIZE, LEGACY_HISTORY_FILE, LEGACY_STATE_FILE, LEGACY_TK_STATE_FILE, STATE_FILE, log, set_language, ui_code_for_piper_lang



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
        os.chmod(tmp, mode)
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

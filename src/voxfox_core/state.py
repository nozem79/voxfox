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
from .common import HISTORY_FILE, HISTORY_SIZE, LEGACY_HISTORY_FILE, LEGACY_STATE_FILE, LEGACY_TK_STATE_FILE, STATE_FILE, log, set_language, ui_code_for_piper_lang, detect_system_piper_lang, DEFAULT_VOICE_FOR_LANG



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
    # Which numeric custom slots (customN) VoxFox owns in each desktop's
    # keybinding list, keyed by action ("read"/"stop"/"voice"/"whisper"/"ocr").
    # Tracked by slot rather than by a fixed name so the desktop's custom-list
    # stays a clean numeric sequence — Cinnamon's "Add custom shortcut" button
    # breaks when the list contains non-numeric names. Empty until installed.
    "cinnamon_shortcut_slots": {},
    "gnome_shortcut_slots": {},
    # One-time flag: set once the 2.0.8 numeric-slot migration has run, so
    # upgraders from <= 2.0.7 (who have non-numeric voxfox-* entries that jam
    # Cinnamon's add-shortcut button) get migrated exactly once on first start.
    "shortcuts_slot_migrated": False,
    # 3.0 modular toolbar: the user's chosen visibility and order for the seven
    # front-end buttons, plus the global UI scale (75/100/125). The list of
    # buttons that actually exist lives in the GTK layer; here we store only the
    # user's choices. "version" allows future layout migrations. An empty
    # "buttons" list means "not customised yet" — reconcile_toolbar_layout()
    # fills it from the app's default order on load.
    "ui_layout": {"version": 1, "scale": 100, "buttons": []},
    # 3.3 custom shortcuts: the user's chosen key binding per VoxFox action,
    # as accelerator strings ("<Super>z"). Empty/missing means "use the built-in
    # default" (see _SHORTCUT_ACTIONS in the GTK layer). Shortcuts are no longer
    # auto-installed; the user picks keys and installs them from the settings.
    "shortcut_bindings": {},
    # Experimental "read web page" (webread.py): stage 2 (Ollama) is off by
    # default; mode is "filter" (keep original sentences) or "summary".
    "webread": {
        "use_ollama": False,
        "mode": "filter",
        "url": "http://localhost:11434",
        "model": "llama3.2",
        "api_key": "",
    },
}


def _fresh_state():
    """A brand-new state for a first install, with Slot 1 seeded from the
    system language when we recognise it. A Dutch system therefore starts in
    Dutch (UI + first voice) instead of always defaulting to English; Slot 2
    becomes English so there's always a second language to switch to (or Dutch
    if the system itself is English). Unknown system languages keep the English
    default unchanged."""
    s = copy.deepcopy(DEFAULT_STATE)
    try:
        lang = detect_system_piper_lang()
        if lang:
            s["slot1"] = {"lang": lang,
                          "voice": DEFAULT_VOICE_FOR_LANG.get(lang, ""),
                          "speed": 1.0, "pitch": 0.0}
            second = "English" if lang != "English" else "Dutch"
            s["slot2"] = {"lang": second,
                          "voice": DEFAULT_VOICE_FOR_LANG.get(second, ""),
                          "speed": 1.0, "pitch": 0.0}
            log.info(f"Fresh install: seeded Slot 1 from system language ({lang})")
    except Exception as e:
        log.debug(f"system language detection skipped: {e}")
    return s


def load_state():
    # init_storage() copies any legacy file to STATE_FILE on startup; this
    # read-only fallback keeps load_state() correct even if called on its own.
    path = STATE_FILE
    if not os.path.isfile(path):
        for old in (LEGACY_STATE_FILE, LEGACY_TK_STATE_FILE):
            if os.path.isfile(old):
                path = old
                break
    # True fresh install: no state file anywhere. Seed from the system language
    # so a Dutch desktop starts in Dutch instead of defaulting to English.
    if not os.path.isfile(path):
        s = _fresh_state()
        set_language(ui_code_for_piper_lang(s["slot1"].get("lang", "")))
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
            s.setdefault("cinnamon_shortcut_slots", {})
            s.setdefault("gnome_shortcut_slots", {})
            s.setdefault("shortcuts_slot_migrated", False)
            s.setdefault("ui_layout",
                         copy.deepcopy(DEFAULT_STATE["ui_layout"]))
            s.setdefault("shortcut_bindings", {})
            s.setdefault("webread",
                         copy.deepcopy(DEFAULT_STATE["webread"]))
            for k, v in DEFAULT_STATE["webread"].items():
                s["webread"].setdefault(k, v)
            # UI language now follows Slot 1 automatically (the ui_lang field
            # in the state file is ignored — kept around only so older state
            # files don't crash).
            ui_code = ui_code_for_piper_lang(s["slot1"].get("lang", ""))
            set_language(ui_code)
            return s
    except Exception:
        s = _fresh_state()
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
        # Best-effort: some filesystems (e.g. FAT32/exFAT on removable media)
        # don't support Unix permissions and chmod can raise EPERM there. The
        # restricted mode is a hardening nicety, not a requirement — never let
        # it block the save.
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


# ── 3.0 modular toolbar: UI scale + button-layout reconciliation ──────────

UI_SCALES = (75, 100, 125)
DEFAULT_UI_SCALE = 100


def _snap_scale(value):
    """Clamp an arbitrary UI scale to the nearest supported step (75/100/125).
    Junk or missing values fall back to 100."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return DEFAULT_UI_SCALE
    return min(UI_SCALES, key=lambda s: abs(s - v))


def reconcile_toolbar_layout(layout, default_order):
    """Reconcile a stored ui_layout against the buttons the app actually has.

    Drops stored buttons whose id no longer exists (removed in an update),
    appends buttons that are new in this version (at the end, since the user
    may have reordered), keeps the user's order and per-button visibility for
    everything known, and snaps the UI scale to a supported step.

    `default_order` is the canonical id order (the GTK layer's TOOLBAR_IDS).
    This function is deliberately UI-agnostic — it knows no button names, only
    the id list it is handed — so voxfox_core stays free of UI specifics. It
    never mutates the input and always returns a fresh, valid layout dict."""
    layout = layout or {}
    valid = set(default_order)

    stored, order = {}, []
    for entry in layout.get("buttons", []):
        if not isinstance(entry, dict):
            continue
        bid = entry.get("id")
        if bid in valid and bid not in stored:
            stored[bid] = bool(entry.get("visible", True))
            order.append(bid)

    for bid in default_order:          # buttons new in this version: append, visible
        if bid not in stored:
            stored[bid] = True
            order.append(bid)

    return {
        "version": 1,
        "scale": _snap_scale(layout.get("scale", DEFAULT_UI_SCALE)),
        "buttons": [{"id": b, "visible": stored[b]} for b in order],
    }


__all__ = [
    "DEFAULT_STATE",
    "load_state",
    "_atomic_write_json",
    "save_state",
    "load_history",
    "save_history",
    "add_history",
    "UI_SCALES",
    "DEFAULT_UI_SCALE",
    "reconcile_toolbar_layout",
]

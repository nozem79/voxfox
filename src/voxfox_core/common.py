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


"""voxfox_core.common — Shared base: logging, paths, AppState/i18n, Piper-language tables."""

import json, logging, os, shutil, subprocess


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("voxfox")

# Quiet down third-party libraries that log every HTTP call.
# Note: we keep huggingface_hub on INFO so model downloads are visible.
for noisy in ("httpx", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

APP_NAME  = "VoxFox"

# Piper TTS engine, its voices, and the app logo stay in ~/.piper. That is the
# conventional location for the Piper engine, and the voice files are large, so
# VoxFox keeps them here rather than moving (and risking re-downloading) them
# under XDG dirs on upgrade.
PIPER_DIR = os.environ.get("VOXFOX_PIPER_DIR") or os.path.expanduser("~/.piper")
LOGO_PATH = os.path.join(PIPER_DIR, "voxfox-logo.png")
PIPER_BIN = os.path.join(PIPER_DIR, "piper")

# Everything else follows the XDG Base Directory spec (honouring the env vars,
# falling back to the usual ~/.config, ~/.local/share, ~/.cache).
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
XDG_DATA_HOME   = os.environ.get("XDG_DATA_HOME")   or os.path.expanduser("~/.local/share")
XDG_CACHE_HOME  = os.environ.get("XDG_CACHE_HOME")  or os.path.expanduser("~/.cache")
CONFIG_DIR = os.path.join(XDG_CONFIG_HOME, "voxfox")
DATA_DIR   = os.path.join(XDG_DATA_HOME, "voxfox")
CACHE_DIR  = os.path.join(XDG_CACHE_HOME, "voxfox")

# User locale overrides live in the data dir; legacy installs kept them in
# ~/.piper/locales (migrated on first run). Read-only defaults ship in
# /usr/share/voxfox/locales and are used as a fallback by the GUI.
LOCALES_DIR = os.path.join(DATA_DIR, "locales")
LEGACY_LOCALES_DIR = os.path.expanduser("~/.piper/locales")


def set_locales_dir(path):
    """Override where translation files are read from (the GTK front-end points
    this at the system locale dir when no per-user set exists)."""
    global LOCALES_DIR
    LOCALES_DIR = path


def locales_dir():
    return LOCALES_DIR

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/voxfox-{os.getuid()}"
SOCKET_PATH = os.path.join(RUNTIME_DIR, "voxfox.sock")
PID_FILE    = os.path.join(RUNTIME_DIR, "voxfox.pid")
LOCK_FILE   = os.path.join(RUNTIME_DIR, "voxfox.lock")

STATE_FILE   = os.path.join(CONFIG_DIR, "state.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")
LOG_FILE     = os.path.join(CACHE_DIR, "voxfox.log")

# Legacy locations, read once and copied forward by init_storage() (never
# deleted): VoxFox 1.x kept loose files in ~/.config, and the original Tk
# prototype used hover_speak_gui_state.json.
LEGACY_STATE_FILE    = os.path.join(XDG_CONFIG_HOME, "voxfox_state.json")
LEGACY_HISTORY_FILE  = os.path.join(XDG_CONFIG_HOME, "voxfox_history.json")
LEGACY_TK_STATE_FILE = os.path.join(XDG_CONFIG_HOME, "hover_speak_gui_state.json")

BASE_URL   = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/raw/main/voices.json"

MAX_TEXT_LEN  = 50000  # safety cap on total text length
CHUNK_SIZE    = 800    # how big to make per-chunk pieces fed to Piper
HOVER_DELAY   = 0.4   # seconds still before speaking
HOVER_POLL    = 0.15  # polling interval
MIN_MOVE_PX   = 8     # pixel movement that resets the hover timer
HISTORY_SIZE  = 20    # number of past read/dictate items to remember


# ── Internationalization ──────────────────────────────────────────────────────
# Translations live in ~/.piper/locales/<code>.json. The installer ships a few
# default languages there; users can edit them or drop in new ones without
# touching this script. Each file looks like:
#   {
#     "_meta": {"name": "Deutsch", "code": "de"},
#     "Read": "Vorlesen",
#     ...
#   }
# Keys are the original English strings as they appear in _("...") calls.
#
# Slot 1's language (Piper's English name like "Dutch", "German") drives the
# UI language via PIPER_LANG_TO_CODE below. So picking "German" in Slot 1
# automatically switches the UI to German if a de.json file is present.

class AppState:
    """Runtime configuration that used to live in module globals: the active UI
    language and its translation tables, the per-language pronunciation
    dictionary, and whether word-wrapped lines are merged into paragraphs.

    A single instance (`app`, below) is the source of truth; the module-level
    functions keep delegating to it, so the public API is unchanged.
    """

    def __init__(self):
        self.lang = "en"                 # active UI language code
        self.translations = {}           # {code: {english: translated}}
        self.ui_lang_names = {"en": "English"}
        self.pronunciations = {}         # {piper_lang_name: {word: respelling}}
        self.merge_lines = True

    # ── i18n ──────────────────────────────────────────────────────────────
    def load_translations(self):
        """Scan LOCALES_DIR for *.json files and (re)build the translation
        tables. A malformed locale is logged and skipped — one broken file must
        never stop VoxFox from starting."""
        self.translations = {}
        self.ui_lang_names = {"en": "English"}
        if not os.path.isdir(LOCALES_DIR):
            return
        for fname in sorted(os.listdir(LOCALES_DIR)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(LOCALES_DIR, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                log.warning(f"Could not load locale {fname}: {e}")
                continue
            if not isinstance(data, dict):
                log.warning(f"Locale {fname} is not a JSON object — skipping")
                continue
            meta = data.get("_meta", {}) if isinstance(data.get("_meta"), dict) else {}
            code = meta.get("code") or os.path.splitext(fname)[0]
            name = meta.get("name") or code
            if code == "en":
                self.ui_lang_names["en"] = name
                continue
            self.translations[code] = {k: v for k, v in data.items() if k != "_meta"}
            self.ui_lang_names[code] = name

    def has_language(self, code):
        return code == "en" or code in self.translations

    def set_language(self, code):
        if self.has_language(code):
            self.lang = code
        else:
            log.info(f"No locale for '{code}' — UI staying in English")
            self.lang = "en"

    def tr(self, text):
        if self.lang == "en":
            return text
        return self.translations.get(self.lang, {}).get(text, text)

    def available_languages(self):
        out = [("en", self.ui_lang_names.get("en", "English"))]
        for code in sorted(self.translations.keys()):
            out.append((code, self.ui_lang_names.get(code, code)))
        return out

    # ── pronunciation + line merging ────────────────────────────────────────
    def set_pronunciations(self, mapping):
        self.pronunciations = mapping or {}

    def pron_for(self, lang):
        return self.pronunciations.get(lang, {})

    def set_merge_lines(self, enabled):
        self.merge_lines = bool(enabled)


app = AppState()


# Piper exposes languages by their English name in voices.json
# ("Dutch", "German", "French", ...). To switch UI language when Slot 1
# changes, we need to map that English name to a locale code. Only
# languages we actually ship locale files for are in this map; others
# fall through to English without complaint.
PIPER_LANG_TO_CODE = {
    "English":    "en",
    "Dutch":      "nl",
    "German":     "de",
    "French":     "fr",
    "Spanish":    "es",
    "Italian":    "it",
    "Portuguese": "pt",
    "Chinese":    "zh",
    "Arabic":     "ar",
}


# Native display names for Piper's language names. Used by the switch-slot
# button in the title bar so it can show "Deutsch" rather than "German"
# regardless of the current UI language. Falls back to the Piper name itself
# for languages without an entry (Polish, Czech, etc. — they show in their
# Piper English form, which is still recognisable).
PIPER_LANG_NATIVE = {
    "English":    "English",
    "Dutch":      "Nederlands",
    "German":     "Deutsch",
    "French":     "Français",
    "Spanish":    "Español",
    "Italian":    "Italiano",
    "Portuguese": "Português",
    "Chinese":    "中文",
    "Arabic":     "العربية",
}


def piper_lang_native(piper_lang_name):
    """Return the native display name for a Piper language, or the input
    unchanged if we don't have a native name for it."""
    return PIPER_LANG_NATIVE.get(piper_lang_name, piper_lang_name or "?")


# Korte tweeletterige codes voor compacte weergave in de titelbalk.
# Gebruikt door de slot-switch knop zodat hij niet teveel ruimte opslokt.
PIPER_LANG_SHORT = {
    "English":    "EN",
    "Dutch":      "NL",
    "German":     "DE",
    "French":     "FR",
    "Spanish":    "ES",
    "Italian":    "IT",
    "Portuguese": "PT",
    "Polish":     "PL",
    "Russian":    "RU",
    "Czech":      "CS",
    "Danish":     "DA",
    "Greek":      "EL",
    "Finnish":    "FI",
    "Hungarian":  "HU",
    "Norwegian":  "NO",
    "Romanian":   "RO",
    "Slovak":     "SK",
    "Swedish":    "SV",
    "Ukrainian":  "UK",
    "Turkish":    "TR",
    "Arabic":     "AR",
    "Chinese":    "ZH",
    "Japanese":   "JA",
    "Korean":     "KO",
    "Catalan":    "CA",
}


def piper_lang_short(piper_lang_name):
    """Geef een korte tweeletterige code voor een Piper-taal.
    Valt terug op de eerste twee letters in hoofdletters als de taal
    niet in de tabel staat — zo blijven onbekende talen ook compact."""
    if not piper_lang_name:
        return "?"
    if piper_lang_name in PIPER_LANG_SHORT:
        return PIPER_LANG_SHORT[piper_lang_name]
    return piper_lang_name[:2].upper()


def load_translations():
    app.load_translations()


def set_language(code):
    app.set_language(code)


def _(text):
    """Translate `text` to the current UI language (source string if English
    or untranslated)."""
    return app.tr(text)


def available_ui_languages():
    """List of (code, native_name) for UI languages we have translations for;
    English is always included."""
    return app.available_languages()


def ui_code_for_piper_lang(piper_lang_name):
    """Given a Piper language name like 'German', return the locale code
    we should switch the UI to, or 'en' if we don't have a locale for it."""
    code = PIPER_LANG_TO_CODE.get(piper_lang_name, "en")
    # Only honour codes we have an actual locale file for; otherwise English.
    return code if app.has_language(code) else "en"


# Reverse of PIPER_LANG_TO_CODE: locale code -> Piper language name.
_CODE_TO_PIPER_LANG = {code: name for name, code in PIPER_LANG_TO_CODE.items()}

# A sensible default Piper voice per language, used to seed Slot 1 on a fresh
# install once the system language is detected. English and Dutch are the
# voices we always bundle (DEFAULT_VOICES); the rest are reasonable medium
# voices that exist in the Piper voices catalogue. A wrong/unavailable key is
# harmless: voice download logs a warning and skips, and the user can pick
# another voice in the preferences.
DEFAULT_VOICE_FOR_LANG = {
    "English":    "en_GB-alba-medium",
    "Dutch":      "nl_NL-pim-medium",
    "German":     "de_DE-thorsten-medium",
    "French":     "fr_FR-siwis-medium",
    "Spanish":    "es_ES-davefx-medium",
    "Italian":    "it_IT-paola-medium",
    "Portuguese": "pt_BR-faber-medium",
    "Chinese":    "zh_CN-huayan-medium",
    "Arabic":     "ar_JO-kareem-medium",
}


def detect_system_piper_lang():
    """Return the Piper language NAME matching the system locale (e.g. 'Dutch'
    for nl_NL.UTF-8), or None if the system language isn't one we ship a UI
    translation for. Reads the standard locale environment variables in POSIX
    priority order; falls back to None so callers keep their existing default.

    Used only to seed Slot 1 on a fresh install, so a Dutch system starts in
    Dutch instead of always defaulting to English."""
    raw = ""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "").strip()
        if val:
            raw = val
            break
    if not raw or raw.upper() in ("C", "POSIX"):
        return None
    # Normalise "nl_NL.UTF-8" / "nl_NL@euro" / "nl" -> "nl".
    code = raw.split(".")[0].split("@")[0].split("_")[0].lower()
    name = _CODE_TO_PIPER_LANG.get(code)
    if name and app.has_language(code):
        return name
    return None


# ── State ──────────────────────────────────────────────────────────────────────
def _setup_file_logging():
    """Append VoxFox log output to ~/.cache/voxfox/voxfox.log (rotating). Best
    effort: a read-only home or any failure must never stop the app starting."""
    if getattr(_setup_file_logging, "_done", False):
        return
    try:
        import logging.handlers
        os.makedirs(CACHE_DIR, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        log.addHandler(fh)
        _setup_file_logging._done = True
    except Exception as e:
        log.debug(f"File logging unavailable: {e}")


def _migrate_file(new_path, *legacy_paths):
    """If `new_path` is missing, copy the first existing legacy file to it.
    Copies (never moves) so the old file stays intact, and tightens perms
    since state/history can hold private text or an API key."""
    if os.path.isfile(new_path):
        return
    for old in legacy_paths:
        if old and os.path.isfile(old):
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.copy2(old, new_path)
                try:
                    os.chmod(new_path, 0o600)  # best-effort; FAT32 lacks modes
                except OSError:
                    pass
                log.info(f"Migrated {os.path.basename(old)} -> {new_path}")
            except Exception as e:
                log.warning(f"Migration of {old} failed: {e}")
            return


def init_storage():
    """Create the XDG directories, migrate data from legacy (1.x and Tk-era)
    locations when the new ones don't exist yet, and start file logging.

    Idempotent and non-destructive: it never deletes or overwrites data that is
    already in the new locations, and never removes the old files."""
    for d in (CONFIG_DIR, DATA_DIR, CACHE_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            log.warning(f"Could not create {d}: {e}")

    _migrate_file(STATE_FILE, LEGACY_STATE_FILE, LEGACY_TK_STATE_FILE)
    _migrate_file(HISTORY_FILE, LEGACY_HISTORY_FILE)

    # User locale overrides used to live in ~/.piper/locales.
    if not os.path.isdir(LOCALES_DIR) and os.path.isdir(LEGACY_LOCALES_DIR):
        try:
            shutil.copytree(LEGACY_LOCALES_DIR, LOCALES_DIR)
            log.info(f"Migrated locale overrides -> {LOCALES_DIR}")
        except Exception as e:
            log.warning(f"Locale migration failed: {e}")

    _setup_file_logging()


# ── Display server detection ──────────────────────────────────────────────────
# Detect Wayland vs X11 once. Many of our integration tools (xclip/xdotool)
# are X11-only, so under Wayland we try wl-clipboard / ydotool / dbus fallbacks.
def _is_wayland():
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


IS_WAYLAND = _is_wayland()
log.info(f"Display server: {'Wayland' if IS_WAYLAND else 'X11'}")


def _have(cmd):
    """Return True if `cmd` is on PATH."""
    try:
        subprocess.run(["which", cmd], capture_output=True, timeout=1.0, check=True)
        return True
    except Exception:
        return False


__all__ = [
    "log",
    "APP_NAME",
    "PIPER_DIR",
    "LOGO_PATH",
    "PIPER_BIN",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "CONFIG_DIR",
    "DATA_DIR",
    "CACHE_DIR",
    "LOCALES_DIR",
    "LEGACY_LOCALES_DIR",
    "set_locales_dir",
    "locales_dir",
    "RUNTIME_DIR",
    "SOCKET_PATH",
    "PID_FILE",
    "LOCK_FILE",
    "STATE_FILE",
    "HISTORY_FILE",
    "LOG_FILE",
    "LEGACY_STATE_FILE",
    "LEGACY_HISTORY_FILE",
    "LEGACY_TK_STATE_FILE",
    "BASE_URL",
    "VOICES_URL",
    "MAX_TEXT_LEN",
    "CHUNK_SIZE",
    "HOVER_DELAY",
    "HOVER_POLL",
    "MIN_MOVE_PX",
    "HISTORY_SIZE",
    "AppState",
    "app",
    "PIPER_LANG_TO_CODE",
    "PIPER_LANG_NATIVE",
    "piper_lang_native",
    "PIPER_LANG_SHORT",
    "piper_lang_short",
    "load_translations",
    "set_language",
    "_",
    "available_ui_languages",
    "ui_code_for_piper_lang",
    "DEFAULT_VOICE_FOR_LANG",
    "detect_system_piper_lang",
    "_setup_file_logging",
    "_migrate_file",
    "init_storage",
    "_is_wayland",
    "IS_WAYLAND",
    "_have",
]

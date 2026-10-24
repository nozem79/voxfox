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

"""voxfox_core.typespeak — the logic behind the "Type and speak" window.

Kept free of GTK so it can be tested: which word was just finished (for
saying each word while typing) and the list of recently spoken sentences.
"""

__all__ = ["TYPE_RECENT_SIZE", "TYPE_FONT_MIN", "TYPE_FONT_MAX",
           "word_before", "finished_word", "push_recent", "clamp_type_font",
           "is_word_end", "TILE_KINDS", "TILE_MAX", "TILE_TEXT_MAX",
           "default_tiles", "normalize_tiles", "add_word", "remove_last_word",
           "move_tile", "move_tile_to", "IMAGE_MAX_BYTES", "IMAGE_POSITIONS", "IMAGE_EXTS",
           "is_safe_image_name", "image_file_name", "target_sides",
           "pick_encoding", "image_dir", "IMAGE_DIR_NAME",
           "picture_start_folder", "remember_picture_folder",
           "ICON_PREFIX", "is_icon_name", "default_icon", "add_default_icons",
           "load_board", "save_board"]

TYPE_RECENT_SIZE = 10
TYPE_FONT_MIN = 14
TYPE_FONT_MAX = 72

# Typing one of these finishes the word before it.
_WORD_END = set(" \t\n.,;:!?)]}\"'»”’…")


def is_word_end(ch):
    """True when typing `ch` finishes a word (a space or punctuation)."""
    return bool(ch) and ch[0] in _WORD_END


def word_before(text):
    """The last word in `text` (the text up to the cursor, before the
    space or punctuation that was just typed), or "" when there is none.
    Letters, digits, hyphens and apostrophes inside a word count as part
    of it: "zo'n", "e-mail", "2026"."""
    end = len(text)
    while end > 0 and text[end - 1] in _WORD_END:
        end -= 1
    start = end
    while start > 0:
        c = text[start - 1]
        if c.isalnum() or (c in "-'’" and start - 1 > 0
                           and text[start - 2].isalnum()):
            start -= 1
        else:
            break
    return text[start:end].strip("-'’")


def finished_word(before):
    """The word that typing a space or punctuation mark right after
    `before` finishes, or "" when `before` does not end in a word (a
    space after a comma finishes nothing: the word was already said)."""
    if not before or not before[-1].isalnum():
        return ""
    return word_before(before)


def push_recent(items, text, size=TYPE_RECENT_SIZE):
    """Put `text` at the front of the recent list (moving it there if it
    was already in it) and cap the list. Returns a new list; blank text
    leaves the list as it was."""
    items = [t for t in (items or []) if isinstance(t, str) and t.strip()]
    text = (text or "").strip()
    if not text:
        return items[:size]
    items = [t for t in items if t.strip() != text]
    return ([text] + items)[:size]


def clamp_type_font(px, default=26):
    try:
        px = int(px)
    except (TypeError, ValueError):
        px = default
    return max(TYPE_FONT_MIN, min(TYPE_FONT_MAX, px))


# ── Tile pictures (6.1) ──────────────────────────────────────────────────
# A tile can show an icon or photo, left of, right of or above its text.
# The pictures live in one folder the user chooses; a tile stores only the
# file name. Every picture is at most IMAGE_MAX_BYTES: a bigger one is
# scaled down (and, for photos, saved as JPEG) when it is added.

IMAGE_MAX_BYTES = 50 * 1024
IMAGE_POSITIONS = ("left", "right", "center")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")
# Folder name made inside the place the user picks (translated by the UI).
IMAGE_DIR_NAME = "Tile pictures"


def is_safe_image_name(name):
    """True for a plain file name in the pictures folder: no folders, no
    hidden files, a known picture extension. A tile can never point
    anywhere else on disk."""
    if not isinstance(name, str) or not name or len(name) > 120:
        return False
    if "/" in name or "\\" in name or name.startswith(".") or "\0" in name:
        return False
    return name.lower().endswith(IMAGE_EXTS)


def image_file_name(data, ext):
    """A name for a picture, from its contents: the same picture added
    twice is stored once."""
    import hashlib
    ext = (ext or ".png").lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext == ".jpeg":
        ext = ".jpg"
    return "tile-" + hashlib.sha1(data, usedforsecurity=False).hexdigest()[:16] + ext


def target_sides(width, height, steps=(384, 256, 192, 128, 96, 64)):
    """The sizes to try when a picture must shrink, largest first, never
    larger than the picture itself: [(w, h), ...] keeping the shape."""
    width, height = max(1, int(width)), max(1, int(height))
    out = []
    for side in steps:
        scale = min(1.0, side / max(width, height))
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        if size not in out:
            out.append(size)
    return out


def pick_encoding(sizes, encode, has_alpha, limit=IMAGE_MAX_BYTES,
                  qualities=(85, 70, 55), png_min_side=128):
    """Find the largest version of a picture that fits in `limit` bytes.

    `encode(w, h, fmt, quality)` returns the bytes of the picture at that
    size ("png" or "jpeg"). A picture with transparency (an icon) stays a
    PNG as long as one of at least `png_min_side` pixels fits, so the
    transparency survives; only then, and for photos straight away, JPEG
    is used. Returns (bytes, ext), or (None, None) when nothing fits."""
    if has_alpha:
        for w, h in sizes:
            if max(w, h) < png_min_side and (w, h) != sizes[0]:
                break
            data = encode(w, h, "png", None)
            if data is not None and len(data) <= limit:
                return data, ".png"
    for w, h in sizes:
        for q in qualities:
            data = encode(w, h, "jpeg", q)
            if data is not None and len(data) <= limit:
                return data, ".jpg"
    return None, None


def picture_start_folder(state, fallback=None):
    """Where the picture chooser opens: the folder the last picture came
    from while it still exists, otherwise `fallback` (the Pictures
    folder) when that exists, otherwise None (the chooser's own
    default)."""
    import os
    for path in ((state or {}).get("type_last_picture_dir"), fallback):
        if isinstance(path, str) and path and os.path.isdir(os.path.expanduser(path)):
            return os.path.expanduser(path)
    return None


def remember_picture_folder(state, picture_path):
    """Store the folder of a chosen picture, so the chooser opens there
    next time. Returns True when it changed (and needs saving)."""
    import os
    folder = os.path.dirname(os.path.abspath(picture_path or ""))
    if not folder or (state or {}).get("type_last_picture_dir") == folder:
        return False
    state["type_last_picture_dir"] = folder
    return True


def image_dir(state):
    """The pictures folder, or None while none has been chosen."""
    import os
    path = (state or {}).get("type_image_dir")
    return os.path.expanduser(path) if isinstance(path, str) and path else None


# ── Tiles (6.1) ──────────────────────────────────────────────────────────
# A tile is {"text": "heb", "kind": "action"}. Pressing it adds its text to
# the sentence. The kinds follow the colour scheme many communication
# boards use (people yellow, actions green, describing words blue, things
# orange, social words pink, questions purple), plus whole example
# sentences.

TILE_KINDS = ("phrase", "social", "person", "action", "describe", "thing",
              "question")
TILE_MAX = 200
TILE_TEXT_MAX = 80

_BOARDS = {
    "nl": {
        "phrase": ["Ik heb dorst", "Ik heb honger", "Ik heb pijn",
                   "Ik wil naar huis", "Kun je me helpen?",
                   "Ik wil iets zeggen"],
        "social": ["Ja", "Nee", "Hallo", "Dank je wel", "Alsjeblieft",
                   "Tot ziens", "Help!"],
        "person": ["Ik", "Jij", "Wij", "Hij", "Zij"],
        "action": ["wil", "heb", "ben", "ga", "kan", "eet", "drink",
                   "slaap"],
        "describe": ["niet", "graag", "meer", "klaar", "nu", "later",
                     "goed", "slecht"],
        "thing": ["dorst", "honger", "pijn", "moe", "koud", "warm",
                  "toilet", "water", "koffie", "thee", "naar huis"],
        "question": ["Wat", "Waar", "Wie", "Wanneer", "?"],
    },
    "en": {
        "phrase": ["I am thirsty", "I am hungry", "I am in pain",
                   "I want to go home", "Can you help me?",
                   "I want to say something"],
        "social": ["Yes", "No", "Hello", "Thank you", "Please", "Goodbye",
                   "Help!"],
        "person": ["I", "You", "We", "He", "She"],
        "action": ["want", "have", "am", "go", "can", "eat", "drink",
                   "sleep"],
        "describe": ["not", "more", "done", "now", "later", "good", "bad"],
        "thing": ["thirsty", "hungry", "in pain", "tired", "cold", "warm",
                  "toilet", "water", "coffee", "tea", "home"],
        "question": ["What", "Where", "Who", "When", "?"],
    },
    "de": {
        "phrase": ["Ich habe Durst", "Ich habe Hunger", "Ich habe Schmerzen",
                   "Ich will nach Hause", "Kannst du mir helfen?",
                   "Ich möchte etwas sagen"],
        "social": ["Ja", "Nein", "Hallo", "Danke", "Bitte", "Tschüss",
                   "Hilfe!"],
        "person": ["Ich", "Du", "Wir", "Er", "Sie"],
        "action": ["will", "habe", "bin", "gehe", "kann", "esse", "trinke",
                   "schlafe"],
        "describe": ["nicht", "gern", "mehr", "fertig", "jetzt", "später",
                     "gut", "schlecht"],
        "thing": ["Durst", "Hunger", "Schmerzen", "müde", "kalt", "warm",
                  "Toilette", "Wasser", "Kaffee", "Tee", "nach Hause"],
        "question": ["Was", "Wo", "Wer", "Wann", "?"],
    },
    "fr": {
        "phrase": ["J'ai soif", "J'ai faim", "J'ai mal",
                   "Je veux rentrer à la maison", "Pouvez-vous m'aider ?",
                   "Je veux dire quelque chose"],
        "social": ["Oui", "Non", "Bonjour", "Merci", "S'il vous plaît",
                   "Au revoir", "À l'aide !"],
        "person": ["Je", "J'ai", "Tu", "Nous", "Il", "Elle"],
        "action": ["veux", "suis", "vais", "peux", "mange", "bois", "dors"],
        "describe": ["pas", "encore", "fini", "maintenant", "plus tard",
                     "bien", "mal"],
        "thing": ["soif", "faim", "fatigué", "froid", "chaud", "toilettes",
                  "eau", "café", "thé", "à la maison"],
        "question": ["Quoi", "Où", "Qui", "Quand", "?"],
    },
    "es": {
        "phrase": ["Tengo sed", "Tengo hambre", "Tengo dolor",
                   "Quiero ir a casa", "¿Puedes ayudarme?",
                   "Quiero decir algo"],
        "social": ["Sí", "No", "Hola", "Gracias", "Por favor", "Adiós",
                   "¡Ayuda!"],
        "person": ["Yo", "Tú", "Nosotros", "Él", "Ella"],
        "action": ["quiero", "tengo", "estoy", "voy", "puedo", "como",
                   "bebo", "duermo"],
        "describe": ["no", "más", "listo", "ahora", "luego", "bien", "mal"],
        "thing": ["sed", "hambre", "dolor", "cansado", "frío", "calor",
                  "baño", "agua", "café", "té", "a casa"],
        "question": ["Qué", "Dónde", "Quién", "Cuándo", "?"],
    },
}


# ── Pictograms for the ready-made tiles (6.2) ───────────────────────────
# VoxFox ships one SVG per ready-made tile in icons/tiles/<name>.svg. A
# tile points at one as {"image": "icon:dorst"}; a picture the user added
# keeps its own file name in the pictures folder. The Dutch words are the
# file names; the other boards say which picture goes with which word.

ICON_PREFIX = "icon:"
_ICON_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")

# Tile text (per board) -> pictogram name, where it is not simply the
# Dutch word in lower case with spaces as hyphens.
_ICONS = {
    "nl": {"Help!": "help", "Kun je me helpen?": "kun-je-me-helpen",
           "?": "vraagteken"},
    "en": {"I am thirsty": "ik-heb-dorst", "I am hungry": "ik-heb-honger",
           "I am in pain": "ik-heb-pijn", "I want to go home": "ik-wil-naar-huis",
           "Can you help me?": "kun-je-me-helpen",
           "I want to say something": "ik-wil-iets-zeggen",
           "Yes": "ja", "No": "nee", "Hello": "hallo", "Thank you": "dank-je-wel",
           "Please": "alsjeblieft", "Goodbye": "tot-ziens", "Help!": "help",
           "I": "ik", "You": "jij", "We": "wij", "He": "hij", "She": "zij",
           "want": "wil", "have": "heb", "am": "ben", "go": "ga", "can": "kan",
           "eat": "eet", "drink": "drink", "sleep": "slaap",
           "not": "niet", "more": "meer", "done": "klaar", "now": "nu",
           "later": "later", "good": "goed", "bad": "slecht",
           "thirsty": "dorst", "hungry": "honger", "in pain": "pijn",
           "tired": "moe", "cold": "koud", "warm": "warm", "toilet": "toilet",
           "water": "water", "coffee": "koffie", "tea": "thee", "home": "naar-huis",
           "What": "wat", "Where": "waar", "Who": "wie", "When": "wanneer",
           "?": "vraagteken"},
    "de": {"Ich habe Durst": "ik-heb-dorst", "Ich habe Hunger": "ik-heb-honger",
           "Ich habe Schmerzen": "ik-heb-pijn",
           "Ich will nach Hause": "ik-wil-naar-huis",
           "Kannst du mir helfen?": "kun-je-me-helpen",
           "Ich möchte etwas sagen": "ik-wil-iets-zeggen",
           "Ja": "ja", "Nein": "nee", "Hallo": "hallo", "Danke": "dank-je-wel",
           "Bitte": "alsjeblieft", "Tschüss": "tot-ziens", "Hilfe!": "help",
           "Ich": "ik", "Du": "jij", "Wir": "wij", "Er": "hij", "Sie": "zij",
           "will": "wil", "habe": "heb", "bin": "ben", "gehe": "ga", "kann": "kan",
           "esse": "eet", "trinke": "drink", "schlafe": "slaap",
           "nicht": "niet", "gern": "graag", "mehr": "meer", "fertig": "klaar",
           "jetzt": "nu", "später": "later", "gut": "goed", "schlecht": "slecht",
           "Durst": "dorst", "Hunger": "honger", "Schmerzen": "pijn",
           "müde": "moe", "kalt": "koud", "warm": "warm", "Toilette": "toilet",
           "Wasser": "water", "Kaffee": "koffie", "Tee": "thee",
           "nach Hause": "naar-huis",
           "Was": "wat", "Wo": "waar", "Wer": "wie", "Wann": "wanneer",
           "?": "vraagteken"},
    "fr": {"J'ai soif": "ik-heb-dorst", "J'ai faim": "ik-heb-honger",
           "J'ai mal": "ik-heb-pijn", "Je veux rentrer à la maison": "ik-wil-naar-huis",
           "Pouvez-vous m'aider ?": "kun-je-me-helpen",
           "Je veux dire quelque chose": "ik-wil-iets-zeggen",
           "Oui": "ja", "Non": "nee", "Bonjour": "hallo", "Merci": "dank-je-wel",
           "S'il vous plaît": "alsjeblieft", "Au revoir": "tot-ziens",
           "À l'aide !": "help",
           "Je": "ik", "J'ai": "heb", "Tu": "jij", "Nous": "wij", "Il": "hij",
           "Elle": "zij",
           "veux": "wil", "suis": "ben", "vais": "ga", "peux": "kan",
           "mange": "eet", "bois": "drink", "dors": "slaap",
           "pas": "niet", "encore": "meer", "fini": "klaar", "maintenant": "nu",
           "plus tard": "later", "bien": "goed", "mal": "slecht",
           "soif": "dorst", "faim": "honger", "fatigué": "moe", "froid": "koud",
           "chaud": "warm", "toilettes": "toilet", "eau": "water",
           "café": "koffie", "thé": "thee", "à la maison": "naar-huis",
           "Quoi": "wat", "Où": "waar", "Qui": "wie", "Quand": "wanneer",
           "?": "vraagteken"},
    "es": {"Tengo sed": "ik-heb-dorst", "Tengo hambre": "ik-heb-honger",
           "Tengo dolor": "ik-heb-pijn", "Quiero ir a casa": "ik-wil-naar-huis",
           "¿Puedes ayudarme?": "kun-je-me-helpen",
           "Quiero decir algo": "ik-wil-iets-zeggen",
           "Sí": "ja", "No": "nee", "Hola": "hallo", "Gracias": "dank-je-wel",
           "Por favor": "alsjeblieft", "Adiós": "tot-ziens", "¡Ayuda!": "help",
           "Yo": "ik", "Tú": "jij", "Nosotros": "wij", "Él": "hij", "Ella": "zij",
           "quiero": "wil", "tengo": "heb", "estoy": "ben", "voy": "ga",
           "puedo": "kan", "como": "eet", "bebo": "drink", "duermo": "slaap",
           "no": "niet", "más": "meer", "listo": "klaar", "ahora": "nu",
           "luego": "later", "bien": "goed", "mal": "slecht",
           "sed": "dorst", "hambre": "honger", "dolor": "pijn",
           "cansado": "moe", "frío": "koud", "calor": "warm", "baño": "toilet",
           "agua": "water", "café": "koffie", "té": "thee", "a casa": "naar-huis",
           "Qué": "wat", "Dónde": "waar", "Quién": "wie", "Cuándo": "wanneer",
           "?": "vraagteken"},
}


def is_icon_name(name):
    """True for a pictogram VoxFox ships ("icon:dorst"): only lower-case
    letters, digits and hyphens after the prefix, so it can never point
    outside the pictogram folder."""
    if not isinstance(name, str) or not name.startswith(ICON_PREFIX):
        return False
    rest = name[len(ICON_PREFIX):]
    return 0 < len(rest) <= 40 and set(rest) <= _ICON_NAME_CHARS


def _board_code(code):
    code = (code or "en").split("_")[0].lower()
    return code if code in _BOARDS else "en"


def default_icon(code, text):
    """The pictogram ("icon:…") for a ready-made tile's text on the board
    of `code`, or None when that text has none."""
    code = _board_code(code)
    name = _ICONS.get(code, {}).get(text)
    if name is None and code == "nl" and any(
            text in words for words in _BOARDS["nl"].values()):
        name = text.lower().replace(" ", "-")
    name = ICON_PREFIX + name if name else None
    return name if is_icon_name(name) else None


def default_tiles(code):
    """The ready-made board for a UI language code ("nl", "en", ...);
    English for languages without a board of their own. Every tile has
    its pictogram, on the left."""
    code = _board_code(code)
    board = _BOARDS[code]
    tiles = []
    for kind in TILE_KINDS:
        for t in board.get(kind, []):
            tile = {"text": t, "kind": kind}
            icon = default_icon(code, t)
            if icon:
                tile["image"] = icon
                tile["image_pos"] = "left"
            tiles.append(tile)
    return tiles


def _icons_added(state):
    done = state.get("type_icons_added")
    return list(done) if isinstance(done, list) else []


def _mark_icons_added(state, code):
    done = _icons_added(state)
    if code not in done:
        state["type_icons_added"] = done + [code]


def load_board(state, code):
    """The tiles for board `code` from `state`: the saved board, or the
    ready-made one when none was saved. A board saved before 6.2 gets
    the pictograms once (add_default_icons). Returns (tiles, changed);
    when `changed` is true `state` was updated and should be saved."""
    boards = state.get("type_tiles")
    stored = boards.get(code) if isinstance(boards, dict) else None
    tiles = normalize_tiles(stored)
    if tiles is None:
        return default_tiles(code), False
    if code in _icons_added(state):
        return tiles, False
    tiles, _n = add_default_icons(tiles, code)
    boards = dict(boards)
    boards[code] = tiles
    state["type_tiles"] = boards
    _mark_icons_added(state, code)
    return tiles, True


def save_board(state, code, tiles):
    """Store `tiles` as board `code` in `state` (the caller saves state).
    A board saved from 6.2 on has the pictograms the user wants, so the
    one-time pictogram step is marked done for it: a pictogram removed
    from the ready-made board stays removed."""
    boards = state.get("type_tiles")
    boards = dict(boards) if isinstance(boards, dict) else {}
    boards[code] = normalize_tiles(tiles) or []
    state["type_tiles"] = boards
    _mark_icons_added(state, code)
    return boards[code]


def add_default_icons(tiles, code):
    """A board saved before 6.2 has no pictograms. Give the ready-made
    pictogram to every tile that still has a ready-made text and no
    picture of its own. Returns (new list, number of tiles changed)."""
    out, n = [], 0
    for t in tiles or []:
        t = dict(t)
        if not t.get("image"):
            icon = default_icon(code, t.get("text", ""))
            if icon:
                t["image"] = icon
                t["image_pos"] = t.get("image_pos") if t.get("image_pos") in IMAGE_POSITIONS else "left"
                n += 1
        out.append(t)
    return out, n


def normalize_tiles(data):
    """A clean tile list from whatever was stored: junk entries dropped,
    unknown kinds become "thing", text trimmed and capped. None when
    nothing usable was stored (so the caller can fall back to a default
    board), [] when the user deliberately removed every tile."""
    if not isinstance(data, list):
        return None
    out = []
    for t in data:
        if not isinstance(t, dict):
            continue
        text = t.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        kind = t.get("kind")
        tile = {"text": " ".join(text.split())[:TILE_TEXT_MAX],
                "kind": kind if kind in TILE_KINDS else "thing"}
        image = t.get("image")
        if is_safe_image_name(image) or is_icon_name(image):
            tile["image"] = image
            pos = t.get("image_pos")
            tile["image_pos"] = pos if pos in IMAGE_POSITIONS else "left"
        out.append(tile)
        if len(out) >= TILE_MAX:
            break
    return out


_GLUE = set(".,!?;:…")


def add_word(text, word):
    """The sentence with a tile's word added: separated by one space, but
    punctuation (?, !, ., ,) sticks to the word before it."""
    word = " ".join((word or "").split())
    if not word:
        return text or ""
    base = (text or "").rstrip()
    if not base:
        return word
    if all(c in _GLUE for c in word):
        return base + word
    return base + " " + word


def remove_last_word(text):
    """The sentence without its last word (or last punctuation mark)."""
    base = (text or "").rstrip()
    if not base:
        return ""
    if base[-1] in _GLUE:
        return base[:-1].rstrip()
    i = base.rfind(" ")
    return base[:i].rstrip() if i >= 0 else ""


def move_tile(tiles, index, delta):
    """A copy of `tiles` with the tile at `index` moved `delta` places
    (clamped at both ends). Returns (new_list, new_index)."""
    tiles = list(tiles)
    if not 0 <= index < len(tiles):
        return tiles, index
    new = max(0, min(len(tiles) - 1, index + delta))
    tiles.insert(new, tiles.pop(index))
    return tiles, new


def move_tile_to(tiles, src, dst):
    """A copy of `tiles` with the tile at `src` dragged onto the place of
    the tile at `dst`: it takes that place and the tiles in between
    shift up one. Returns the new list (unchanged when either index is
    out of range or they are the same)."""
    tiles = list(tiles)
    n = len(tiles)
    if not (0 <= src < n and 0 <= dst < n) or src == dst:
        return tiles
    tiles.insert(dst, tiles.pop(src))
    return tiles

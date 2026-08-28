# VoxFox — free accessibility tools for Linux
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""voxfox_core.documents — The OCR document library and its reading positions.

Every OCR run produces a new document: a plain .txt file in the library
folder, never merged with an earlier one, so scanning the same page twice
gives two documents. Alongside them sits one hidden index file recording
each document's title, when it was made, how long it is, and how far the
listener got.

The index lives *in* the library folder rather than in the config directory
so that moving or backing up the folder takes the reading positions along
with the text.

Positions are character offsets into the document text, produced by
tts.chunk_offsets(). They survive re-chunking, so a future change to how
text is split for speech will not send anyone back to the wrong paragraph.
"""

import json
import os
import re
import time

from .common import log
from .state import _atomic_write_json

INDEX_NAME = ".voxfox-index.json"

# Enough to tell documents apart in a list without wrapping onto two lines.
TITLE_MAX = 60


# ── Where the library lives ───────────────────────────────────────────────────

def _xdg_documents_dir():
    """The user's Documents folder, in their own language where possible.

    Reads ~/.config/user-dirs.dirs, which is what the desktop itself uses,
    so a Dutch install gets ~/Documenten and a French one ~/Documents. Falls
    back to ~/Documents when that file is missing or unreadable.
    """
    path = os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "user-dirs.dirs")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r'\s*XDG_DOCUMENTS_DIR\s*=\s*"(.*)"\s*$', line)
                if m:
                    value = m.group(1).replace("$HOME", os.path.expanduser("~"))
                    if value:
                        return value
    except OSError:
        pass
    return os.path.expanduser("~/Documents")


def default_dir():
    """Where documents go unless the user picks somewhere else."""
    return os.path.join(_xdg_documents_dir(), "VoxFox")


def library_dir(state):
    """The folder in use, honouring the docs_dir setting."""
    configured = (state or {}).get("docs_dir")
    return os.path.expanduser(configured) if configured else default_dir()


def _index_path(folder):
    return os.path.join(folder, INDEX_NAME)


# ── The index ─────────────────────────────────────────────────────────────────

def load_index(folder):
    """Every document in `folder`, newest first. Never raises.

    Entries whose text file has gone missing are dropped: the file is the
    document, the index only describes it.
    """
    try:
        with open(_index_path(folder), encoding="utf-8") as fh:
            items = json.load(fh)
        if not isinstance(items, list):
            return []
    except (OSError, ValueError):
        return []
    alive = [d for d in items
             if isinstance(d, dict) and d.get("file")
             and os.path.isfile(os.path.join(folder, d["file"]))]
    alive.sort(key=lambda d: d.get("ts", 0), reverse=True)
    return alive


def save_index(folder, items):
    try:
        os.makedirs(folder, exist_ok=True)
        _atomic_write_json(_index_path(folder), items, mode=0o600)
        return True
    except OSError as e:
        log.warning(f"documents: could not write the index: {e}")
        return False


def _make_title(text):
    """A readable title from the first line of the text."""
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if line:
            return line[:TITLE_MAX]
    return ""


def _unique_name(folder, stamp):
    """A filename that is not taken yet, without a counter in the common case."""
    name = f"{stamp}.txt"
    if not os.path.exists(os.path.join(folder, name)):
        return name
    for n in range(2, 100):
        name = f"{stamp}-{n}.txt"
        if not os.path.exists(os.path.join(folder, name)):
            return name
    return f"{stamp}-{int(time.time())}.txt"


def add(folder, text, title=None):
    """Store `text` as a new document. Returns its index entry, or None.

    Always a new document, even for text identical to an earlier one.
    """
    if not text or not text.strip():
        return None
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        name = _unique_name(folder, stamp)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(path, 0o600)
    except OSError as e:
        log.warning(f"documents: could not save the document: {e}")
        return None

    entry = {
        "file": name,
        "title": title or _make_title(text),
        "ts": int(time.time()),
        "length": len(text),
        "offset": 0,
    }
    items = load_index(folder)
    items.insert(0, entry)
    save_index(folder, items)
    log.debug(f"documents: saved {name} ({len(text)} characters)")
    return entry


def read_text(folder, entry):
    """The text of a document, or "" when it cannot be read."""
    try:
        with open(os.path.join(folder, entry["file"]), encoding="utf-8") as fh:
            return fh.read()
    except (OSError, KeyError, ValueError) as e:
        log.warning(f"documents: could not read the document: {e}")
        return ""


def set_position(folder, name, offset, length=None):
    """Record how far the listener got in the document called `name`.

    An offset at or past the end is stored as 0: a document that was read to
    the end should start from the beginning next time, not sit permanently
    on its last sentence.
    """
    items = load_index(folder)
    for entry in items:
        if entry.get("file") != name:
            continue
        total = length or entry.get("length") or 0
        entry["offset"] = 0 if (total and offset >= total) else max(0, offset)
        save_index(folder, items)
        return entry["offset"]
    return None


def progress(entry):
    """How far through a document the listener is, 0.0 to 1.0."""
    length = entry.get("length") or 0
    if length <= 0:
        return 0.0
    return min(1.0, max(0.0, entry.get("offset", 0) / float(length)))


def delete(folder, name):
    """Remove a document and its index entry."""
    try:
        os.unlink(os.path.join(folder, name))
    except OSError as e:
        log.debug(f"documents: could not delete the file: {e}")
    items = [d for d in load_index(folder) if d.get("file") != name]
    save_index(folder, items)


def move_library(old_folder, new_folder):
    """Move the documents and their positions to a new folder.

    Used when the user picks a different folder in the settings: the library
    follows them rather than appearing empty. Files that cannot be moved are
    left where they are and reported, so nothing is silently lost.

    Returns (moved, failed).
    """
    old_folder = os.path.abspath(os.path.expanduser(old_folder))
    new_folder = os.path.abspath(os.path.expanduser(new_folder))
    if old_folder == new_folder:
        return 0, 0
    items = load_index(old_folder)
    if not items:
        return 0, 0
    try:
        os.makedirs(new_folder, exist_ok=True)
    except OSError as e:
        log.warning(f"documents: could not create {new_folder}: {e}")
        return 0, len(items)

    kept, moved, failed = [], 0, 0
    for entry in items:
        name = entry.get("file")
        if not name:
            continue
        target = os.path.join(new_folder, name)
        if os.path.exists(target):
            # Do not overwrite something already there under the same name.
            name = _unique_name(new_folder, os.path.splitext(name)[0])
            target = os.path.join(new_folder, name)
        try:
            os.replace(os.path.join(old_folder, entry["file"]), target)
        except OSError:
            try:
                # os.replace fails across filesystems; copy and remove instead.
                with open(os.path.join(old_folder, entry["file"]),
                          encoding="utf-8") as src:
                    data = src.read()
                with open(target, "w", encoding="utf-8") as dst:
                    dst.write(data)
                os.chmod(target, 0o600)
                os.unlink(os.path.join(old_folder, entry["file"]))
            except OSError as e:
                log.warning(f"documents: could not move {entry['file']}: {e}")
                failed += 1
                continue
        entry["file"] = name
        kept.append(entry)
        moved += 1

    existing = load_index(new_folder)
    save_index(new_folder, kept + existing)
    save_index(old_folder, [d for d in load_index(old_folder)
                            if d.get("file") not in {e["file"] for e in kept}])
    log.info(f"documents: moved {moved} document(s) to {new_folder}"
             + (f", {failed} failed" if failed else ""))
    return moved, failed


__all__ = [
    "INDEX_NAME",
    "TITLE_MAX",
    "default_dir",
    "library_dir",
    "load_index",
    "save_index",
    "add",
    "read_text",
    "set_position",
    "progress",
    "delete",
    "move_library",
]

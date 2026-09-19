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


"""voxfox_core.tts — Text-to-speech: Piper voices, chunking, the speaking worker."""

import functools, json, os, re, shutil, subprocess, tempfile, threading, time, urllib.request
from .common import BASE_URL, CHUNK_SIZE, CONFIG_DIR, DATA_DIR, MAX_TEXT_LEN, PIPER_BIN, PIPER_DIR, VOICES_URL, app, log, ram_tmpdir



# ── Voice data ─────────────────────────────────────────────────────────────────
_voices_cache    = {}
_voices_cache_ts = 0
VOICES_CACHE_TTL = 300  # 5 minutes


def fetch_voices(force=False):
    global _voices_cache, _voices_cache_ts
    now = time.monotonic()
    if not force and _voices_cache and (now - _voices_cache_ts) < VOICES_CACHE_TTL:
        return _voices_cache
    try:
        with urllib.request.urlopen(VOICES_URL, timeout=10) as r:
            _voices_cache    = json.loads(r.read().decode())
            _voices_cache_ts = now
    except Exception as e:
        log.error(f"Could not fetch voice list: {e}")
    return _voices_cache


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
                    done += len(chunk)
                    if frac_cb and total:
                        frac_cb(done / total, os.path.basename(filename))
            os.rename(tmp, dest)
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
            return False, str(e)
    return True, "Done"


# ── Audio ──────────────────────────────────────────────────────────────────────
_speak_thread = None
_stop_event   = threading.Event()
_pause_event  = threading.Event()   # set = paused; cleared = playing
_speak_lock   = threading.Lock()

# Read-only progress (for the GUI). Updated by the worker, never written by GUI.
_progress = {"chunk": 0, "total": 0, "text": "", "offset": 0}

# Where the listener got to, kept after speaking ends so that pausing or
# stopping leaves something to save. _progress is reset when the worker
# finishes; this deliberately is not.
_position = {"offset": 0, "length": 0, "token": None}


def is_speaking():
    """True if a speech thread is actively playing."""
    return _speak_thread is not None and _speak_thread.is_alive()


def is_paused():
    """True if speech is currently paused."""
    return _pause_event.is_set()


def toggle_pause():
    """Toggle the pause state. Returns the new paused state (True/False).
    No-op if nothing is currently speaking."""
    if not is_speaking():
        return False
    if _pause_event.is_set():
        _pause_event.clear()
        return False
    else:
        _pause_event.set()
        return True


def _voice_sample_rate(voice_key):
    """Read the sample rate from a Piper voice's .onnx.json. Default 22050."""
    cfg_path = os.path.join(
        find_voice_dir(voice_key) or PIPER_DIR, f"{voice_key}.onnx.json")
    try:
        with open(cfg_path) as f:
            return int(json.load(f).get("audio", {}).get("sample_rate", 22050))
    except Exception:
        return 22050


def _retune_wav(path, new_rate):
    """Rewrite a PCM WAV header's sample rate (and the derived byte rate) so any
    player reproduces the existing samples at `new_rate`. Players such as paplay
    read the rate from the WAV header and ignore a --rate flag, so this is how we
    actually shift pitch; the matching tempo change is cancelled upstream via
    Piper's length_scale. Best-effort: on any problem the file is left untouched.
    """
    try:
        import struct
        with open(path, "r+b") as f:
            head = f.read(44)
            if len(head) < 44 or head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
                return
            channels = struct.unpack_from("<H", head, 22)[0] or 1
            bits     = struct.unpack_from("<H", head, 34)[0] or 16
            block_align = max(1, channels * (bits // 8))
            f.seek(24); f.write(struct.pack("<I", int(new_rate)))
            f.seek(28); f.write(struct.pack("<I", int(new_rate) * block_align))
    except Exception as e:
        log.debug(f"WAV retune failed: {e}")


# Per-language pronunciation dictionary, kept in sync with the saved state by
# the UI via set_pronunciations(). Keyed by the slot's piper language name.
def set_pronunciations(mapping):
    """Install the {language: {word: respelling}} dictionary used by speak()."""
    app.set_pronunciations(mapping)


@functools.lru_cache(maxsize=8)
def _compiled_pronunciation_pattern(items):
    """Build (compiled regex, lowercase-key lookup) for a pronunciation
    mapping, given as a hashable tuple of its (key, value) pairs.

    Cached because apply_pronunciations() runs once per chunk -- a few
    hundred times over a long document, all with the same mapping -- and
    rebuilding the same alternation regex from scratch every time was pure
    waste. Bounded to a handful of entries: in practice there is one
    mapping per language slot, and this only grows if the user edits their
    pronunciation dictionary mid-session."""
    keys = sorted((k for k, _v in items if k and k.strip()),
                  key=len, reverse=True)
    if not keys:
        return None, {}
    lower = {k.lower(): v for k, v in items if k and k.strip()}
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
        re.IGNORECASE)
    return pattern, lower


def apply_pronunciations(text, mapping):
    """Rewrite whole-word occurrences of each dictionary key with its respelling
    before the text goes to TTS. Case-insensitive, longest key first, single
    pass (so a replacement is never itself re-substituted)."""
    if not mapping:
        return text
    pattern, lower = _compiled_pronunciation_pattern(tuple(sorted(mapping.items())))
    if pattern is None:
        return text
    return pattern.sub(lambda m: lower[m.group(0).lower()], text)


def chunk_text(text, max_chars=CHUNK_SIZE):
    """Split `text` into speakable chunks for natural-sounding TTS pacing.

    The previous version returned the input as a single chunk when it
    fit under max_chars. That caused bullet lists and code blocks to be
    spoken without any pause between lines, because Piper has no idea
    those are separate items in the source.

    New strategy (top-down):
    1. Split on every newline (single or double). Each line becomes its
       own chunk, so the speech worker inserts a pause between them.
    2. For each line, split on sentence terminators (. ! ?) if the line
       is long enough to benefit.
    3. For sentences longer than max_chars, split on commas.
    4. As a last resort, hard-slice at max_chars.

    Returns a list of (chunk_text, ends_paragraph) tuples. ends_paragraph
    is True at the end of each blank-line-separated block, so a future
    enhancement can use it for variable-length pauses if desired.
    """
    if not text:
        return []
    text = text.strip()

    import re

    def _split_long_sentence(s):
        """Split a too-long sentence on commas, then hard-slice."""
        if len(s) <= max_chars:
            return [s]
        out = []
        buf = ""
        for part in s.split(", "):
            if len(buf) + 2 + len(part) <= max_chars:
                buf = (buf + ", " + part).strip(", ") if buf else part
            else:
                if buf:
                    out.append(buf)
                while len(part) > max_chars:
                    out.append(part[:max_chars])
                    part = part[max_chars:]
                buf = part
        if buf:
            out.append(buf)
        return out

    def _split_line(line):
        """Split one logical line (no internal newlines) into chunks."""
        line = line.strip()
        if not line:
            return []
        # Break on sentence terminators that are followed by whitespace.
        # The list comprehension keeps non-empty trimmed pieces. CJK
        # terminators (。！？) are also split on directly, since Chinese text
        # has no space after them — otherwise a whole paragraph would arrive
        # as one chunk and get hard-sliced mid-sentence.
        sentences = [s.strip()
                     for s in re.split(r'(?<=[.!?])\s+|(?<=[。！？])', line)
                     if s.strip()]
        if not sentences:
            return []
        chunks, buf = [], ""
        for s in sentences:
            if len(buf) + 1 + len(s) <= max_chars:
                buf = (buf + " " + s).strip() if buf else s
            else:
                if buf:
                    chunks.append(buf)
                if len(s) > max_chars:
                    chunks.extend(_split_long_sentence(s))
                    buf = ""
                else:
                    buf = s
        if buf:
            chunks.append(buf)
        return chunks

    def _looks_like_list_item(s):
        """Bullets and numbered items, which should keep their pause."""
        s = s.lstrip()
        if not s:
            return False
        if s[0] in "\u2022\u2023\u25e6*-\u2013\u2014\u00b7":
            return True
        return bool(re.match(r"^(\d{1,3}|[a-zA-Z]|[ivxIVX]{1,4})[.)]\s", s))

    def _pack_short(pairs):
        """Join runs of short fragments into chunks of a normal size.

        Every chunk is spoken as its own utterance, so a document laid
        out as headings, captions and table cells turns into hundreds
        of one-line utterances with a gap after each. Packing them back
        together restores the flow.

        Only genuinely short fragments are packed: anything already at
        a reasonable length is a real paragraph and keeps its pause, so
        ordinary prose is unaffected. List items are never packed --
        the pause between them is the whole point of having it.
        """
        # Deliberately well below max_chars: this should catch headings,
        # captions and table cells, not ordinary short paragraphs, which
        # have earned their pause.
        limit = max(60, max_chars // 8)
        packed, buf, buf_ends = [], "", False
        for chunk, ends in pairs:
            joinable = (len(chunk) < limit
                        and not _looks_like_list_item(chunk))
            if joinable and buf and len(buf) + 1 + len(chunk) <= max_chars:
                buf = buf + " " + chunk
                buf_ends = ends
                continue
            if buf:
                packed.append((buf, buf_ends))
                buf, buf_ends = "", False
            if joinable:
                buf, buf_ends = chunk, ends
            else:
                packed.append((chunk, ends))
        if buf:
            packed.append((buf, buf_ends))
        return packed

    # Walk over blocks separated by blank lines. Each block can contain
    # multiple inner lines (e.g. a bullet list). Mark ends_paragraph=True
    # only on the last chunk of each blank-line-delimited block.
    out = []
    # Normalize: collapse 3+ newlines to exactly 2, then split on \n\n.
    normalized = re.sub(r'\n{3,}', '\n\n', text)
    blocks = [b for b in normalized.split("\n\n") if b.strip()]
    for block in blocks:
        block_chunks = []
        for line in block.split("\n"):
            block_chunks.extend(_split_line(line))
        # Tag chunks: every chunk gets ends_paragraph=False except the very
        # last one in this blank-line block.
        for i, c in enumerate(block_chunks):
            out.append((c, i == len(block_chunks) - 1))
    return _pack_short(out)


def chunk_offsets(text, chunks):
    """Where each chunk starts, as a character position in `text`.

    Chunks are not reliably substrings of the original: sentences are
    rejoined with one space, comma-split parts with ", ", and blank
    lines are collapsed. What does survive is every non-whitespace
    character, in order. So we match on the whitespace-free stream and
    keep an index that maps each of those characters back to its
    position in the real text.

    A chunk that cannot be matched at all (a rewrite we did not
    anticipate) gets the position we had reached so far, which is off
    by a little rather than wrong by a lot.

    Returns a list of ints, one per chunk."""
    stripped = text.strip()
    if not stripped:
        return [0] * len(chunks)
    base = text.find(stripped)
    index = [i for i, ch in enumerate(stripped) if not ch.isspace()]
    dense = "".join(stripped[i] for i in index)

    offsets = []
    cursor = 0
    for chunk, _ends_paragraph in chunks:
        needle = "".join(ch for ch in chunk if not ch.isspace())
        if not needle:
            offsets.append(base + (index[cursor] if cursor < len(index)
                                   else len(stripped)))
            continue
        at = dense.find(needle, cursor)
        if at < 0:
            # Fall back to the opening of the chunk, which is enough to
            # place it even when the tail was reflowed.
            at = dense.find(needle[:12], cursor)
        if at < 0:
            at = cursor
        offsets.append(base + (index[at] if at < len(index)
                               else len(stripped)))
        cursor = min(at + len(needle), len(dense))
    return offsets


def chunk_index_for_offset(offsets, offset):
    """The chunk to resume at for a saved character position.

    Picks the last chunk that starts at or before `offset`, so a
    position recorded halfway through a sentence replays that sentence
    from its beginning rather than skipping it."""
    if offset <= 0:
        return 0
    found = 0
    for i, start in enumerate(offsets):
        if start <= offset:
            found = i
        else:
            break
    return found


# Rough speaking rate of the Piper voices at speed 1.0. Only used to
# turn the skip buttons' seconds into a distance in characters, where
# being a syllable out does not matter.
CHARS_PER_SECOND = 15.0


def seconds_to_chars(seconds, slot_config=None):
    """How many characters roughly correspond to `seconds` of speech.

    Scales with the slot's speed setting, so a skip covers the same
    amount of listening time whether the voice is set fast or slow."""
    speed = float((slot_config or {}).get("speed", 1.0) or 1.0)
    return max(1, int(seconds * CHARS_PER_SECOND * speed))


def _word_boundary_at_or_before(text, offset):
    """Move `offset` back to the start of the word it falls inside.

    Cutting the text at an arbitrary character would otherwise make a
    skip begin in the middle of a word, which sounds like a stutter."""
    if offset <= 0:
        return 0
    if offset >= len(text):
        return len(text)
    i = offset
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    return i


def speak(text, slot_config, start_offset=0, token=None):
    """Speak text. Long text is split into chunks played sequentially.
    Replaces any currently-playing speech.

    start_offset is a character position in `text`; speaking begins at
    the chunk containing it, so a document can be resumed where the
    listener stopped.

    token is passed straight through to get_position() and is never
    interpreted here. The interface uses it to label the speech with
    the document it came from, so that a reading position is only ever
    written back to the document that actually produced it."""
    global _speak_thread, _stop_event, _progress, _position
    text = text[:MAX_TEXT_LEN]
    # Pronunciation replacements are applied per chunk in the worker,
    # not here: they change the length of the text, and every position
    # we hand out must refer to the text the caller gave us, or a saved
    # bookmark would drift by the length of every replacement before it.
    # Cut the text at the starting point and chunk what is left, so any
    # character can be a starting point. Skipping back thirty seconds
    # lands thirty seconds back, not at the top of the sentence.
    start_offset = _word_boundary_at_or_before(text, max(0, start_offset))
    body = text[start_offset:] if start_offset else text
    chunks = chunk_text(body)
    offsets = [o + start_offset for o in chunk_offsets(body, chunks)]
    if start_offset:
        log.debug(f"speak: starting at character {start_offset} "
                  f"of {len(text)}")
    with _speak_lock:
        _stop_event.set()
        if _speak_thread and _speak_thread.is_alive():
            _speak_thread.join(timeout=2.0)
        _stop_event = threading.Event()
        _pause_event.clear()  # new speech starts unpaused
        _progress = {"chunk": 0, "total": len(chunks), "text": "",
                     "offset": start_offset}
        _position = {"offset": start_offset, "length": len(text),
                     "token": token}
        evt   = _stop_event
        pause = _pause_event
        _speak_thread = threading.Thread(
            target=_speak_worker,
            args=(chunks, slot_config, evt, pause, offsets, len(text),
                  token),
            daemon=True)
        _speak_thread.start()


def get_progress():
    """Return a snapshot of current playback progress."""
    return dict(_progress)


def get_position():
    """Where the listener got to, as {"offset", "length", "token"}.

    Survives stopping, so it can still be read when the user pauses or
    stops and the document needs to remember its place. offset is a
    character position in the text that was passed to speak()."""
    return dict(_position)


# ── Persistent Piper server ────────────────────────────────────────────────────

class _PiperServer:
    """Keep a Piper process alive between synthesis calls so the ONNX model
    stays loaded in memory. Without this, every call to speak() pays a
    ~0.5–1 s model-load penalty — audible as the gap before the first word.

    Protocol:
    - Piper is started with --output_dir pointing at a private temp directory
      and --json-input so we can pass per-line parameters (length_scale,
      sentence_silence) alongside the text.
    - We write one JSON line per chunk to stdin; Piper writes one WAV to the
      output dir and prints its filename to stdout. We block on that stdout
      line to know when the WAV is ready.
    - If Piper dies (crash, model swap, parameter change) the server restarts
      automatically on the next synthesis request.

    One server instance is kept per (voice, length_scale, sentence_silence)
    combination. When the slot changes (different voice or speed/pitch) the
    old process is replaced.
    """

    def __init__(self):
        self._proc   = None
        self._outdir = None
        self._lock   = threading.Lock()
        self._key    = None        # (model_path, length_scale, sentence_silence)
        self._env    = None

    def _build_env(self):
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"]  = PIPER_DIR + ":" + env.get("LD_LIBRARY_PATH", "")
        env["ESPEAK_DATA_PATH"] = os.path.join(PIPER_DIR, "espeak-ng-data")
        return env

    def _alive(self):
        return self._proc is not None and self._proc.poll() is None

    def _start(self, model, length_scale, sentence_silence):
        self._stop()
        self._outdir = tempfile.mkdtemp(prefix="voxfox_piper_",
                                        dir=ram_tmpdir())
        key = (model, length_scale, sentence_silence)
        cmd = [
            PIPER_BIN,
            "--model",            model,
            "--output_dir",       self._outdir,
            "--length_scale",     str(length_scale),
            "--sentence_silence", str(sentence_silence),
            "--json-input",
            "--quiet",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env or self._build_env(),
            )
            self._key = key
            log.debug(f"Piper server started (model={os.path.basename(model)})")
        except Exception as e:
            log.error(f"Piper server start failed: {e}")
            self._proc = None
            if self._outdir:
                try:
                    import shutil; shutil.rmtree(self._outdir, ignore_errors=True)
                except Exception:
                    pass
                self._outdir = None

    def _stop(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._key  = None
        if self._outdir:
            try:
                import shutil; shutil.rmtree(self._outdir, ignore_errors=True)
            except Exception:
                pass
            self._outdir = None

    def synth(self, text, model, length_scale, sentence_silence, stop_evt=None):
        """Synthesise `text` and return a WAV path (caller must delete it),
        or None on failure. Restarts Piper if the key changed or it crashed.
        Returns None immediately if stop_evt is set."""
        if stop_evt and stop_evt.is_set():
            return None
        key = (model, round(length_scale, 4), round(sentence_silence, 2))
        with self._lock:
            if self._key != key or not self._alive():
                self._env = self._build_env()
                self._start(model, round(length_scale, 4), round(sentence_silence, 2))
            if not self._alive():
                return None          # start failed
            import json as _json
            payload = _json.dumps({"text": text}) + "\n"
            try:
                self._proc.stdin.write(payload.encode("utf-8"))
                self._proc.stdin.flush()
            except OSError as e:
                log.debug(f"Piper stdin write failed: {e}; restarting")
                self._stop()
                return None
            # Read the filename Piper writes to stdout when done
            try:
                line = self._proc.stdout.readline()
            except OSError as e:
                log.debug(f"Piper stdout read failed: {e}")
                self._stop()
                return None
            if not line:
                log.debug("Piper server died (empty stdout)")
                self._stop()
                return None
            wav_path = line.decode("utf-8", errors="replace").strip()
            if not wav_path:
                # Piper sometimes writes extra blank lines; try one more
                try:
                    line = self._proc.stdout.readline()
                    wav_path = line.decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
            if not wav_path or not os.path.isfile(wav_path):
                log.debug(f"Piper returned bad path: {wav_path!r}")
                return None
            if os.path.getsize(wav_path) < 100:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
                return None
        return wav_path

    def shutdown(self):
        """Clean up on VoxFox exit."""
        with self._lock:
            self._stop()


_piper_server = _PiperServer()


def shutdown_piper():
    """Shut down the persistent Piper server (call on VoxFox exit)."""
    _piper_server.shutdown()


def _speak_worker(chunks, slot_config, stop_evt, pause_evt,
                  offsets=None, total_chars=0, token=None):
    """Play a list of (text, ends_paragraph) tuples sequentially.

    offsets holds the character position of each chunk in the original text
    (see chunk_offsets); it is what lets a document remember its place.

    Honors stop_evt (terminate immediately) and pause_evt:
    - Between chunks: wait while paused.
    - Mid-chunk: pause kills the current player; resume replays the chunk
      from the start. (Piper writes the whole WAV before playback, so we
      can't truly mid-stream pause without a more capable player.)

    The NEXT chunk is synthesized in the background while the current one
    plays (prefetch). Without this, every chunk was only synthesized after
    the previous one finished playing, which inserted Piper's synthesis
    time (roughly 0.5-1 s) as an audible gap at every paragraph break.
    """
    global _progress, _position
    if offsets is None:
        offsets = []
    voice = slot_config.get("voice", "")
    speed = slot_config.get("speed", 1.0)
    # Pitch in semitones (0 = the voice's natural pitch). Shifting the playback
    # sample rate moves the pitch but also the tempo; we cancel the tempo change
    # via Piper's length_scale so `speed` alone controls the speaking rate.
    # f = 2^(semitones/12): +12 = one octave up, -12 = one octave down.
    try:
        pitch_factor = 2.0 ** (float(slot_config.get("pitch", 0.0)) / 12.0)
    except (TypeError, ValueError):
        pitch_factor = 1.0
    model = os.path.join(find_voice_dir(voice) or PIPER_DIR, f"{voice}.onnx")
    if not os.path.isfile(model):
        log.error(f"Model not found: {model}")
        return

    rate = _voice_sample_rate(voice)
    play_rate = max(8000, min(48000, round(rate * pitch_factor)))

    def _wait_while_paused():
        """Block while paused. Returns True if interrupted by stop_evt."""
        while pause_evt.is_set():
            if stop_evt.is_set():
                return True
            time.sleep(0.1)
        return False

    def _responsive_sleep(seconds):
        """Sleep that bails out early on stop_evt. Used between chunks."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if stop_evt.is_set():
                return True
            time.sleep(0.05)
        return False

    pron = app.pron_for((slot_config or {}).get("lang", ""))

    def _synth(text):
        """Synthesise via the persistent Piper server (model stays loaded).
        Pronunciation replacements happen here, on the chunk, so that the
        positions reported by this worker stay true to the original text."""
        path = _piper_server.synth(
            apply_pronunciations(text, pron), model,
            length_scale=round(pitch_factor / speed, 4),
            sentence_silence=0.1,
            stop_evt=stop_evt,
        )
        if path and abs(pitch_factor - 1.0) > 1e-6:
            _retune_wav(path, play_rate)
        return path

    def _play(path):
        """Play one wav. Returns 'ok', 'failed' or 'stop'."""
        for player_cmd in [["paplay", path], ["aplay", "-q", path]]:
            while True:  # retry loop for pause/resume
                try:
                    p2 = subprocess.Popen(player_cmd,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    break  # player missing: try the next one
                paused_mid = False
                while p2.poll() is None:
                    if stop_evt.is_set():
                        p2.terminate()
                        p2.wait()
                        return "stop"
                    if pause_evt.is_set():
                        p2.terminate()
                        p2.wait()
                        paused_mid = True
                        break
                    time.sleep(0.05)
                if paused_mid:
                    if _wait_while_paused():
                        return "stop"
                    continue  # replay this chunk with the same player
                if p2.returncode == 0:
                    return "ok"
                break  # player error: try the next one
        return "failed"

    # --- Prefetch pipeline -------------------------------------------------
    next_holder = []
    next_thread = None

    def _start_prefetch(text):
        nonlocal next_holder, next_thread
        next_holder = []
        next_thread = threading.Thread(
            target=lambda: next_holder.append(_synth(text)), daemon=True)
        next_thread.start()

    def _collect_prefetch():
        nonlocal next_thread
        if next_thread is None:
            return None
        next_thread.join()
        next_thread = None
        return next_holder[0] if next_holder else None

    current = None
    try:
        for idx, (chunk, ends_paragraph) in enumerate(chunks):
            if stop_evt.is_set():
                break
            if _wait_while_paused():
                break

            here = offsets[idx] if idx < len(offsets) else 0
            _progress = {"chunk": idx + 1, "total": len(chunks),
                         "text": chunk[:80], "offset": here}
            _position = {"offset": here, "length": total_chars,
                         "token": token}

            # First chunk (or a failed prefetch): synthesize on the spot.
            if current is None:
                current = _synth(chunk)
            # Kick off synthesis of the NEXT chunk while this one plays.
            if idx + 1 < len(chunks):
                _start_prefetch(chunks[idx + 1][0])

            if current is not None:
                result = _play(current)
                try:
                    os.unlink(current)
                except Exception:
                    pass
                current = None
                if result == "stop":
                    break

            # Inter-chunk pause. Piper itself inserts a small natural pause
            # when a chunk ends in a punctuation mark (. ! ?), so we add
            # nothing on top of that. Lines without trailing punctuation
            # (bullets, code, CLI commands) get a tiny pause so they don't
            # smush together.
            if idx < len(chunks) - 1:
                ends_punctuated = chunk.rstrip().endswith((".", "!", "?", ":", ";"))
                gap = 0.0 if ends_punctuated else 0.025
                if gap and _responsive_sleep(gap):
                    break

            current = _collect_prefetch()
        else:
            # Every chunk played and nothing interrupted: the document
            # has been read to the end. Reporting the position as the
            # full length is what lets the bookmark reset to the start.
            _position = {"offset": total_chars, "length": total_chars,
                         "token": token}
    finally:
        # Clean up anything that never played (stop mid-way or an error).
        leftover = _collect_prefetch()
        for p in (current, leftover):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass
        # _position is left alone: it is the only record of where the
        # listener got to once this worker is gone.
        _progress = {"chunk": 0, "total": 0, "text": "", "offset": 0}


def stop_speaking():
    _stop_event.set()
    _pause_event.clear()


__all__ = [
    "_voices_cache",
    "_voices_cache_ts",
    "VOICES_CACHE_TTL",
    "fetch_voices",
    "get_languages",
    "get_voices_for_lang",
    "get_local_voices",
    "voices_user_dir",
    "find_voice_dir",
    "migrate_legacy_voices",
    "download_voice",
    "_speak_thread",
    "_stop_event",
    "_pause_event",
    "_speak_lock",
    "_progress",
    "is_speaking",
    "is_paused",
    "toggle_pause",
    "_voice_sample_rate",
    "_retune_wav",
    "set_pronunciations",
    "apply_pronunciations",
    "chunk_text",
    "chunk_offsets",
    "chunk_index_for_offset",
    "seconds_to_chars",
    "CHARS_PER_SECOND",
    "speak",
    "get_progress",
    "get_position",
    "_position",
    "_speak_worker",
    "stop_speaking",
    "_PiperServer",
    "_piper_server",
    "shutdown_piper",
]

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

"""voxfox_core.textprep — Preparing text for speech: the pronunciation
dictionary, cutting text into chunks, and positions within it.
"""

import functools, re
from .common import CHUNK_SIZE, app


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
    return pattern.sub(lambda m: lower.get(m.group(0).lower(), m.group(0)), text)


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


def word_boundary_at_or_before(text, offset):
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


__all__ = [
    "set_pronunciations",
    "apply_pronunciations",
    "chunk_text",
    "chunk_offsets",
    "chunk_index_for_offset",
    "seconds_to_chars",
    "CHARS_PER_SECOND",
]

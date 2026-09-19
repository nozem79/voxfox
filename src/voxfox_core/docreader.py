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

"""voxfox_core.docreader — Read Word, LibreOffice, RTF and plain-text files.

Unlike OCR, these formats carry their own paragraph structure, so there is
no line-by-line splitting to repair: a .docx paragraph is one XML element
regardless of how it wraps on screen. The text handed back already has one
blank line between paragraphs, in the same shape merge_wrapped_lines()
produces for OCR, so it feeds straight into the rest of VoxFox (chunking,
the pronunciation and merge settings, the document library) without special
casing anywhere else.

.docx and .odt are both zipped XML and are read with the standard library
only (zipfile + xml.etree) — no python-docx or odfpy dependency, so nothing
new to package. Legacy .doc (the pre-2007 binary format) is not read here;
doc_unsupported_hint() explains why and what to do instead.
"""

import os
import re
import zipfile
import xml.etree.ElementTree as ET

from .common import _, log

DOCUMENT_SUPPORTED_EXTS = {".docx", ".odt", ".txt", ".md", ".rtf"}

# Extensions VoxFox recognises but cannot read itself, each with a hint
# about why and what to do instead. Kept as the single place that lists
# them, so doc_unsupported_hint() cannot drift out of sync with it.
_KNOWN_UNSUPPORTED = {
    ".doc": lambda: _("The old .doc format (Word 97-2003) is not "
                      "supported. Open it in Word or LibreOffice and "
                      "save as .docx or .odt, or export it as plain text."),
    ".wpd": lambda: _("WordPerfect files are not supported. Open it in "
                      "your word processor and save as .docx, .odt or "
                      "plain text."),
}

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_ODT_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODT_OFFICE_NS = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


def _read_zip_member(path, member):
    """Bytes of one file inside a zip, or None if the zip or member is bad.

    Both .docx and .odt are zip archives; a file that merely has the right
    extension but is not actually one -- a renamed .doc, a corrupt download
    -- fails here rather than partway through XML parsing, which is where
    the error message is still clear enough to show the user.
    """
    try:
        with zipfile.ZipFile(path) as z:
            return z.read(member)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        log.debug(f"docreader: could not read {member} from {path}: {e}")
        return None


# ── .docx ──────────────────────────────────────────────────────────────────

def _docx_paragraph_text(p):
    """Join the runs of one <w:p> paragraph, honouring soft line breaks.

    A <w:br/> or <w:tab/> inside a paragraph is a break within the same
    paragraph (Shift+Enter, a tab stop), not a new one, so each becomes a
    single space here rather than ending the paragraph."""
    parts = []
    for node in p.iter():
        tag = node.tag
        if tag == f"{_W_NS}t":
            parts.append(node.text or "")
        elif tag in (f"{_W_NS}br", f"{_W_NS}tab", f"{_W_NS}cr"):
            parts.append(" ")
    return "".join(parts)


def read_docx(path):
    """Extract paragraph text from a .docx file, in reading order.

    Only the main document body (word/document.xml) is read: headers,
    footers, comments and footnotes live in separate parts and are left
    out, since reading a page header at the top of every page aloud would
    be far more disruptive on Wayland's clipboard-based dictation than
    simply omitting it.
    """
    data = _read_zip_member(path, "word/document.xml")
    if data is None:
        return "", _("Could not open this .docx file; it may be damaged "
                     "or not really a Word file.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return "", _("Could not read this .docx file: {error}").format(error=e)

    body = root.find(f"{_W_NS}body")
    if body is None:
        return "", _("No text found")

    paras = []
    for p in body.findall(f"{_W_NS}p"):
        text = _docx_paragraph_text(p).strip()
        if text:
            paras.append(text)
    return "\n\n".join(paras), None


# ── .odt ───────────────────────────────────────────────────────────────────

# Elements ODF treats as their own paragraph or list item; text.list-item
# wraps a nested text:p, so it never needs to be collected directly.
_ODT_BLOCK_TAGS = (f"{_ODT_TEXT_NS}p", f"{_ODT_TEXT_NS}h")

# A footnote/endnote (text:note) or a margin comment (office:annotation) is
# anchored inline inside the paragraph it refers to, but each is its own
# small document fragment -- including, for a footnote, its own nested
# text:p for the note body. Left alone, that nested paragraph would both
# leak into the surrounding sentence (read out of order, mid-clause) and
# be picked up a second time as a block of its own. Skipped entirely
# instead, the same choice already made for headers, footers, comments and
# footnotes in .docx (see read_docx).
_ODT_SKIP_SUBTREE_TAGS = (f"{_ODT_TEXT_NS}note", f"{_ODT_OFFICE_NS}annotation")


def _odt_iter_open(el):
    """Children of `el`, recursing into everything except a skipped
    subtree's own children (the skipped element itself is still visited,
    so callers can act on it, but nothing inside it is)."""
    for child in el:
        yield child
        if child.tag not in _ODT_SKIP_SUBTREE_TAGS:
            yield from _odt_iter_open(child)


def _odt_element_text(el):
    """All the character data under one paragraph/heading element, aside
    from any footnote or comment nested inside it (see
    _ODT_SKIP_SUBTREE_TAGS)."""
    parts = [el.text or ""]
    for child in el:
        if child.tag not in _ODT_SKIP_SUBTREE_TAGS:
            parts.append(_odt_element_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def read_odt(path):
    """Extract paragraph text from an .odt file, in reading order."""
    data = _read_zip_member(path, "content.xml")
    if data is None:
        return "", _("Could not open this .odt file; it may be damaged "
                     "or not really an OpenDocument file.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return "", _("Could not read this .odt file: {error}").format(error=e)

    body = root.find(f".//{_ODT_OFFICE_NS}text")
    if body is None:
        return "", _("No text found")

    paras = []
    for el in _odt_iter_open(body):
        if el.tag in _ODT_BLOCK_TAGS:
            text = _odt_element_text(el).strip()
            if text:
                paras.append(text)
    return "\n\n".join(paras), None


# ── .rtf ───────────────────────────────────────────────────────────────────

_RTF_UNICODE = re.compile(r"\\u(-?\d+)\??")
_RTF_HEX     = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_CONTROL = re.compile(r"\\[a-zA-Z]+-?\d* ?")
_RTF_PAR     = re.compile(r"\\(?:par|line)\b")


def _strip_rtf_destination_groups(text, keywords):
    """Remove whole {\\keyword ...} groups, including any nested braces.

    A flat regex cannot do this: {\\fonttbl{\\f0 Arial;}} nests one group
    inside another, so the removal has to count braces rather than stop at
    the first closing one.
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{" and any(text.startswith(kw, i + 1) for kw in keywords):
            depth = 1
            j = i + 1
            while j < n and depth:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def read_rtf(path):
    """A pragmatic RTF-to-text reader: enough for text written by ordinary
    word processors, not a full RTF parser (tables, embedded objects and
    field codes are not reconstructed -- only their visible text, if any,
    survives).
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return "", _("Could not open this file: {error}").format(error=e)

    try:
        text = raw.decode("latin-1")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    if not text.lstrip().startswith("{\\rtf"):
        return "", _("This does not look like an RTF file.")

    # Skip the font/colour/stylesheet tables up front: their braces and
    # control words would otherwise be read as document text.
    text = _strip_rtf_destination_groups(
        text, (r"\fonttbl", r"\colortbl", r"\stylesheet",
               r"\*\generator", r"\info", r"\*\pgptbl"))

    text = _RTF_PAR.sub("\n\n", text)
    text = _RTF_UNICODE.sub(lambda m: chr(int(m.group(1)) & 0xFFFF), text)
    text = _RTF_HEX.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = _RTF_CONTROL.sub("", text)
    text = text.replace("{", "").replace("}", "").replace("\\", "")

    paras = [p.strip() for p in text.split("\n\n")]
    paras = [re.sub(r"[ \t]+", " ", p) for p in paras if p.strip()]
    return "\n\n".join(paras), None


# ── plain text ───────────────────────────────────────────────────────────────

def read_plain_text(path):
    """.txt and .md: read as-is. Markdown is not rendered -- the asterisks
    and hashes of ** and # are spoken as-is, same as any other plain text
    VoxFox is asked to read.
    """
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            with open(path, encoding=enc) as fh:
                text = fh.read()
            return text.strip(), None
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            return "", _("Could not open this file: {error}").format(error=e)
    return "", _("Could not determine this file's text encoding.")


# ── dispatch ─────────────────────────────────────────────────────────────────

def doc_unsupported_hint(ext):
    """Why a recognised-but-unreadable extension cannot be opened, if any."""
    make = _KNOWN_UNSUPPORTED.get(ext)
    return make() if make else None


def read_document(path):
    """Dispatch to the right reader by extension. Returns (text, error)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext == ".odt":
        return read_odt(path)
    if ext == ".rtf":
        return read_rtf(path)
    if ext in (".txt", ".md"):
        return read_plain_text(path)
    hint = doc_unsupported_hint(ext)
    if hint:
        return "", hint
    return "", _("Unsupported file type: {ext}").format(ext=ext)


__all__ = [
    "DOCUMENT_SUPPORTED_EXTS",
    "read_docx",
    "read_odt",
    "read_rtf",
    "read_plain_text",
    "read_document",
    "doc_unsupported_hint",
]

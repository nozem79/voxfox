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


"""voxfox_core.ocr — OCR for images and PDFs, plus wrapped-line/paragraph merging."""

import os, re, subprocess, tempfile
from .common import _, _have, app, log



# ── OCR ────────────────────────────────────────────────────────────────────────
# Ondersteunde bestandstypen voor OCR:
#   PDF  — eerst pdftotext proberen (snel, verliesvrij voor digitale PDFs);
#           bij een gescande PDF (geen tekstlaag) terugvallen op Tesseract via
#           pdftoppm (paginaconversie) + pytesseract.
#   Afbeeldingen (PNG/JPG/JPEG/BMP/TIFF/WEBP) — direct via Tesseract.
#
# Vereisten (worden via install.sh of handmatig geïnstalleerd):
#   sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-deu ...
#   sudo apt install poppler-utils          # pdftotext + pdftoppm
#   pip install pytesseract pillow          # Python-bindingen

OCR_SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
OCR_SUPPORTED_EXTS   = {".pdf"} | OCR_SUPPORTED_IMAGES

# Piper-taalnaam → Tesseract taalcode(s).  Tesseract accepteert meerdere
# codes gescheiden door '+', bijv. "nld+eng" voor betere resultaten op
# documenten met gemengde taal.
_TESS_LANG_MAP = {
    "Dutch":      "nld",
    "English":    "eng",
    "German":     "deu",
    "French":     "fra",
    "Spanish":    "spa",
    "Italian":    "ita",
    "Portuguese": "por",
    "Polish":     "pol",
    "Russian":    "rus",
    "Chinese":    "chi_sim",
    "Arabic":     "ara",
    "Greek":      "ell",
}


def _tess_lang(piper_lang_name):
    """Geeft de Tesseract-taalcode voor een Piper-taalnaam.
    Valt terug op 'eng' als de taal niet in de tabel staat.
    Voegt altijd 'eng' als tweede code toe zodat Engelse termen
    (bijv. in technische PDFs) correct herkend worden.
    """
    code = _TESS_LANG_MAP.get(piper_lang_name, "eng")
    if code != "eng":
        return f"{code}+eng"
    return "eng"


def _have_tesseract():
    """True als tesseract op het systeem staat."""
    return _have("tesseract")


def _have_pdftotext():
    """True als pdftotext (poppler-utils) beschikbaar is."""
    return _have("pdftotext")


def _have_pdftoppm():
    """True als pdftoppm (poppler-utils) beschikbaar is."""
    return _have("pdftoppm")


def _tesseract_cli(image_path, tess_lang="eng"):
    """Run the tesseract command-line tool directly. This is the fallback when
    the pytesseract/Pillow Python packages aren't installed, so OCR works with
    only the apt 'tesseract-ocr' package (plus language data). Returns the
    recognised text, or None on failure."""
    try:
        r = subprocess.run(["tesseract", image_path, "stdout", "-l", tess_lang],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return r.stdout
        log.warning(f"tesseract CLI exit {r.returncode}: "
                    f"{r.stderr.strip()[:200]}")
    except Exception as e:
        log.warning(f"tesseract CLI failed: {e}")
    return None


def _pdf_has_text_layer(pdf_path):
    """True als de PDF een extracteerbare tekstlaag heeft.

    Gebruik pdffonts (poppler-utils): een lege fonttabel betekent scan/raster.
    Als pdffonts niet aanwezig is, probeer pdftotext en kijk of er output is.
    """
    if _have("pdffonts"):
        try:
            r = subprocess.run(["pdffonts", pdf_path],
                               capture_output=True, text=True, timeout=10)
            # pdffonts-uitvoer: header (2 regels) + één regel per font.
            # Geen extra regels → geen fonts → scan.
            lines = [l for l in r.stdout.splitlines() if l.strip()]
            return len(lines) > 2
        except Exception:
            pass
    # Fallback: probeer pdftotext en kijk of er tekst uitkomt.
    if _have_pdftotext():
        try:
            r = subprocess.run(["pdftotext", pdf_path, "-"],
                               capture_output=True, text=True, timeout=15)
            return bool(r.stdout.strip())
        except Exception:
            pass
    return False


def ocr_pdf(pdf_path, tess_lang="eng", progress_cb=None):
    """Extraheer tekst uit een PDF-bestand.

    Strategie:
    1. Als de PDF een tekstlaag heeft → pdftotext (snel, perfect)
    2. Geen tekstlaag → pdftoppm (per pagina naar PNG) + Tesseract OCR

    Geeft (tekst, foutmelding) terug. Bij succes is foutmelding None.
    """
    if not os.path.isfile(pdf_path):
        return "", f"{_('File not found')}: {pdf_path}"

    # Stap 1: probeer pdftotext
    if _pdf_has_text_layer(pdf_path):
        if progress_cb:
            progress_cb(_("Extracting text from PDF..."))
        if _have_pdftotext():
            try:
                r = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                                   capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip(), None
            except Exception as e:
                log.warning(f"pdftotext failed: {e}")
        # pdftotext niet aanwezig of mislukt: probeer PyMuPDF als fallback
        try:
            import fitz  # PyMuPDF
            doc  = fitz.open(pdf_path)
            text = "\n\n".join(page.get_text() for page in doc)
            doc.close()
            if text.strip():
                return text.strip(), None
        except ImportError:
            pass
        except Exception as e:
            log.warning(f"PyMuPDF failed: {e}")

    # Stap 2: gescande PDF → OCR per pagina
    if not _have_tesseract():
        return "", _("Tesseract OCR not found. "
                     "Install it with: sudo apt install tesseract-ocr")
    if not _have_pdftoppm():
        return "", _("pdftoppm not found. "
                     "Install it with: sudo apt install poppler-utils")

    import importlib.util
    _use_pil = (importlib.util.find_spec("pytesseract") is not None
                and importlib.util.find_spec("PIL") is not None)
    if _use_pil:
        from PIL import Image  # used by the per-page geometry OCR below

    if progress_cb:
        progress_cb(_("Scanned PDF — running OCR (this can take a while)..."))

    with tempfile.TemporaryDirectory() as tmpdir:
        # Converteer alle pagina's naar PNG op 300 DPI (optimaal voor Tesseract)
        prefix = os.path.join(tmpdir, "page")
        try:
            r = subprocess.run(
                ["pdftoppm", "-r", "300", "-png", pdf_path, prefix],
                capture_output=True, timeout=300)
            if r.returncode != 0:
                return "", f"{_('pdftoppm error')}: {r.stderr.decode(errors='replace')[:200]}"
        except subprocess.TimeoutExpired:
            return "", _("pdftoppm timed out (PDF too large?)")
        except Exception as e:
            return "", f"{_('pdftoppm error')}: {e}"

        pages = sorted(f for f in os.listdir(tmpdir) if f.endswith(".png"))
        if not pages:
            return "", _("pdftoppm produced no page images")

        texts = []
        for i, fname in enumerate(pages, 1):
            if progress_cb:
                progress_cb(f"{_('OCR page')} {i}/{len(pages)}...")
            page_path = os.path.join(tmpdir, fname)
            try:
                if _use_pil:
                    texts.append(_tess_text_pil(Image.open(page_path), tess_lang))
                else:
                    text = _tesseract_cli(page_path, tess_lang) or ""
                    texts.append(_post_ocr(text))
            except Exception as e:
                log.warning(f"OCR error on page {i}: {e}")

    return "\n\n".join(t for t in texts if t), None


# When True, OCR output and selected text have merely word-wrapped lines joined
# into paragraphs before reading. Toggled from Settings → Misc.
def set_merge_lines(enabled):
    app.set_merge_lines(enabled)


def merge_enabled():
    return app.merge_lines


def _is_list_or_heading(s):
    """Heuristic: lines that should stay on their own (bullets, numbered items)."""
    if not s:
        return False
    if s[0] in "•‣◦*–—·":
        return True
    return bool(re.match(r"^(\d{1,3}|[a-zA-Z]|[ivxIVX]{1,4})[.)]\s", s))


def merge_wrapped_lines(text):
    """Join lines that are only word-wrapped into flowing paragraphs.

    A paragraph ends at a blank line, at a list/heading line, or after a line
    that is clearly shorter than the text's wrap width (the usual sign of the
    last line of a paragraph). Hyphenated words split across a line break are
    re-joined. Genuine paragraph breaks are preserved as blank lines, so the
    speech engine only pauses where it should.
    """
    if not text or not text.strip():
        return (text or "").strip()
    lines = [l.rstrip() for l in
             text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    widths = [len(l) for l in lines if l.strip()]
    if not widths:
        return text.strip()
    width = max(widths)
    threshold = max(12, int(width * 0.7))

    paras, cur = [], ""

    def flush():
        nonlocal cur
        if cur.strip():
            paras.append(cur.strip())
        cur = ""

    for l in lines:
        s = l.strip()
        if not s:
            flush()
            continue
        if _is_list_or_heading(s):
            flush()
            paras.append(s)
            continue
        if not cur:
            cur = s
        elif cur.endswith("-") and len(cur) >= 2 and cur[-2].isalpha():
            cur = cur[:-1] + s          # de-hyphenate across the wrap
        else:
            cur = cur + " " + s
        if len(l) < threshold:          # short line ⇒ end of paragraph
            flush()
    flush()
    return "\n\n".join(paras)


def _post_ocr(text):
    """Normalise OCR text, optionally merging word-wrapped lines."""
    return merge_wrapped_lines(text) if app.merge_lines else (text or "").strip()


def _paragraphs_from_tsv(data):
    """Reconstruct paragraphs from Tesseract's layout data (the dict returned by
    pytesseract.image_to_data). Tesseract already groups words into a
    block → paragraph → line → word hierarchy, so we honour that instead of
    guessing wrap points from line length. Words are grouped by (block, par),
    lines are joined within a paragraph (de-hyphenating across wraps), and each
    paragraph is separated by a blank line. Returns the text, or None if no
    usable words were found (caller falls back to the text heuristic).

    Because separate columns land in separate blocks, this keeps multi-column
    and justified text from being glued together the way the heuristic can.
    """
    try:
        from collections import OrderedDict
        n = len(data.get("text", []))
        if not n:
            return None
        paras = OrderedDict()
        for i in range(n):
            word = (data["text"][i] or "").strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:                       # -1 marks structure/non-text rows
                continue
            pkey = (int(data["block_num"][i]), int(data["par_num"][i]))
            lkey = int(data["line_num"][i])
            paras.setdefault(pkey, OrderedDict()).setdefault(lkey, []).append(word)
        if not paras:
            return None
        out = []
        for lines in paras.values():
            para = ""
            for words in lines.values():
                line = " ".join(words)
                if not para:
                    para = line
                elif para.endswith("-") and len(para) >= 2 and para[-2].isalpha():
                    para = para[:-1] + line    # de-hyphenate across the wrap
                else:
                    para = para + " " + line
            if para.strip():
                out.append(para.strip())
        return "\n\n".join(out) if out else None
    except Exception as e:
        log.debug(f"paragraph reconstruction from geometry failed: {e}")
        return None


def _ocr_image_geometry(img, tess_lang="eng"):
    """OCR a PIL image and rebuild paragraphs from Tesseract's geometry.
    Returns paragraph text, or None when geometry is unavailable so the caller
    can fall back to plain text + the wrap heuristic."""
    try:
        import pytesseract
        data = pytesseract.image_to_data(
            img, lang=tess_lang, output_type=pytesseract.Output.DICT)
    except Exception as e:
        log.debug(f"image_to_data unavailable, falling back: {e}")
        return None
    return _paragraphs_from_tsv(data)


def _tess_text_pil(img, tess_lang="eng"):
    """OCR a PIL image via pytesseract. With line-merging on, reconstruct
    paragraphs from Tesseract's geometry (text heuristic as fallback); with it
    off, return the raw line-by-line text."""
    import pytesseract
    if app.merge_lines:
        geo = _ocr_image_geometry(img, tess_lang)
        if geo and geo.strip():
            return geo.strip()
        return merge_wrapped_lines(pytesseract.image_to_string(img, lang=tess_lang))
    return (pytesseract.image_to_string(img, lang=tess_lang) or "").strip()


def ocr_image(image_path, tess_lang="eng", progress_cb=None):
    """Extraheer tekst uit een afbeelding via Tesseract OCR.

    Geeft (tekst, foutmelding) terug.
    """
    if not os.path.isfile(image_path):
        return "", f"{_('File not found')}: {image_path}"

    if not _have_tesseract():
        return "", _("Tesseract OCR not found. "
                     "Install it with: sudo apt install tesseract-ocr")
    if progress_cb:
        progress_cb(_("Running OCR on image..."))
    try:
        from PIL import Image
        img = Image.open(image_path)
        return _tess_text_pil(img, tess_lang), None
    except ImportError:
        # No pytesseract/Pillow: drive the tesseract CLI directly.
        text = _tesseract_cli(image_path, tess_lang)
        if text is None:
            return "", _("OCR via the tesseract CLI failed. Check that "
                         "tesseract-ocr and the language packs are installed.")
        return _post_ocr(text), None
    except Exception as e:
        return "", f"{_('OCR error')}: {e}"


def ocr_file(file_path, tess_lang="eng", progress_cb=None):
    """Hoofd-ingang: kies automatisch de juiste OCR-methode op basis van extensie.

    Geeft (tekst, foutmelding) terug.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return ocr_pdf(file_path, tess_lang=tess_lang, progress_cb=progress_cb)
    elif ext in OCR_SUPPORTED_IMAGES:
        return ocr_image(file_path, tess_lang=tess_lang, progress_cb=progress_cb)
    else:
        return "", (f"Niet-ondersteund bestandstype: {ext}. "
                    f"Ondersteund: {', '.join(sorted(OCR_SUPPORTED_EXTS))}")


__all__ = [
    "OCR_SUPPORTED_IMAGES",
    "OCR_SUPPORTED_EXTS",
    "_TESS_LANG_MAP",
    "_tess_lang",
    "_have_tesseract",
    "_have_pdftotext",
    "_have_pdftoppm",
    "_tesseract_cli",
    "_pdf_has_text_layer",
    "ocr_pdf",
    "set_merge_lines",
    "merge_enabled",
    "_is_list_or_heading",
    "merge_wrapped_lines",
    "_post_ocr",
    "_paragraphs_from_tsv",
    "_ocr_image_geometry",
    "_tess_text_pil",
    "ocr_image",
    "ocr_file",
]

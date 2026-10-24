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

"""voxfox_ui.main_window.ocr

Reading text from the screen or from a file (OCR), optionally
translated.
"""

import os
import threading
import tempfile

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.screenshot import grab_region_to_file  # noqa: E402


class OcrActions:
    """Reading text from the screen or from a file (OCR), optionally
    translated.
    """

    def do_ocr_file(self):
        dialog = Gtk.FileChooserNative(
            title=_("Open a document, PDF, or image"), transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        flt = Gtk.FileFilter()
        flt.set_name(_("Documents and images"))
        for pat in ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff",
                    "*.webp", "*.docx", "*.odt", "*.rtf", "*.txt", "*.md"):
            flt.add_pattern(pat)
        dialog.add_filter(flt)

        def on_response(dlg, resp):
            if resp == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile:
                    self._run_ocr_path(gfile.get_path())
            dlg.destroy()
            self._filechooser = None

        self._filechooser = dialog  # hold a ref so it is not GC'd
        dialog.connect("response", on_response)
        dialog.show()

    def do_ocr_select(self):
        tess = vf.tesseract_lang_code(self._active_cfg().get("lang", ""))
        self.set_status(_("Select a region..."), duration=0)

        def worker():
            tmp = None
            try:
                os.makedirs(vf.CACHE_DIR, exist_ok=True)
                fd, tmp = tempfile.mkstemp(suffix=".png", dir=vf.CACHE_DIR)
                os.close(fd)
                ok, err = grab_region_to_file(tmp)
                if not ok:
                    GLib.idle_add(self.set_status, err)
                    return
                GLib.idle_add(self.set_status, _("Reading text..."), 0)
                text, oerr = vf.ocr_image(tmp, tess_lang=tess)
                GLib.idle_add(self._after_ocr, text, oerr)
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _run_ocr_path(self, path):
        """Open a file for reading: OCR for PDFs and images, direct text
        extraction for Word/LibreOffice/RTF/plain-text documents. Both ends
        of this go through the same _after_ocr, since from there on -- merge
        setting, history, the document library -- a recognised page and an
        extracted paragraph are treated identically."""
        ext = os.path.splitext(path)[1].lower()
        if ext in vf.docreader.DOCUMENT_SUPPORTED_EXTS:
            self.set_status(_("Reading text..."), duration=0)

            def worker():
                text, err = vf.docreader.read_document(path)
                self.root.after(0, self._after_ocr, text, err, path)
            threading.Thread(target=worker, daemon=True).start()
            return

        tess = vf.tesseract_lang_code(self._active_cfg().get("lang", ""))
        self.set_status(_("Reading text..."), duration=0)

        def worker():
            text, err = vf.ocr_file(
                path, tess_lang=tess,
                progress_cb=lambda m: self.root.after(0, self.set_status, m, 0))
            self.root.after(0, self._after_ocr, text, err, path)
        threading.Thread(target=worker, daemon=True).start()

    def _after_ocr(self, text, err, source_path=None):
        """Handle recognised or extracted text.

        source_path is set when the text came from a file the user
        opened, and is what separates the two kinds of OCR. A file is
        something to come back to, so it is filed in the library. A
        region scan is a one-off look at part of the screen and only
        goes to the history -- otherwise every glance at a dialog box
        would pile up as a document."""
        if err:
            self.set_status(err)
            return
        if not text or not text.strip():
            self.set_status(_("No text found"))
            return
        ext = os.path.splitext(source_path)[1].lower() if source_path else ""
        if ext in vf.docreader.DOCUMENT_SUPPORTED_EXTS:
            # A Word/LibreOffice/RTF/plain-text paragraph break comes from
            # the file format itself and is never in doubt, unlike a page
            # scanned with OCR. merge_wrapped_lines() also rejoins a short
            # paragraph into the next one when it doesn't look like a
            # finished sentence -- built to recover a sentence OCR split
            # across a page or text-box boundary -- which would wrongly
            # fuse two genuinely separate list items or headings here.
            pass
        elif vf.merge_enabled():
            # OCR keeps the hard line breaks of the scan, so a paragraph
            # arrives as a stack of short lines and is read as such. Same
            # treatment as page text, under the same setting.
            text = vf.merge_wrapped_lines(text)
        vf.add_history("read", text)

        name = None
        if source_path:
            # Every opened file is a new document, never merged with an
            # earlier one: the same PDF twice is two documents.
            folder = vf.documents.library_dir(self.state)
            title = os.path.splitext(os.path.basename(source_path))[0]
            entry = vf.documents.add(folder, text, title=title)
            name = entry.get("file") if entry else None
            self.set_current_document(name, folder if entry else None)
        else:
            # Nothing to bookmark, and the previous document must not
            # collect this scan's position.
            self.set_current_document(None, None)

        threading.Thread(
            target=vf.speak,
            args=(text, self._active_cfg(), 0, name),
            daemon=True).start()
        self._sync_pause_btn()
        self.set_status(_("Reading..."), 1500)

    def do_ocr_select_translate(self):
        """Like Select (OCR), but translates the recognised text into the
        UI language before reading it aloud — for text that is not
        selectable (images, scanned pages, video subtitles) in another
        language. Shortcut-only, like live transcription: no toolbar
        button, since Select already has one and this is a variant of it,
        not a separate everyday action."""
        tess = vf.tesseract_lang_code(self._active_cfg().get("lang", ""))
        self.set_status(_("Select a region..."), duration=0)

        def worker():
            tmp = None
            try:
                os.makedirs(vf.CACHE_DIR, exist_ok=True)
                fd, tmp = tempfile.mkstemp(suffix=".png", dir=vf.CACHE_DIR)
                os.close(fd)
                ok, err = grab_region_to_file(tmp)
                if not ok:
                    GLib.idle_add(self.set_status, err)
                    return
                GLib.idle_add(self.set_status, _("Reading text..."), 0)
                text, oerr = vf.ocr_image(tmp, tess_lang=tess)
                GLib.idle_add(self._after_ocr_translate, text, oerr)
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _after_ocr_translate(self, text, err):
        if err:
            self.set_status(err)
            return
        if not text or not text.strip():
            self.set_status(_("No text found"))
            return
        self.set_status(_("Translating..."), duration=0)

        def worker():
            def prog(i, n):
                if n > 1:
                    GLib.idle_add(lambda: (self.set_status(
                        f"{_('Translating...')} {i}/{n}", duration=0),
                        False)[1])
            out, terr = vf.translate_text(
                text, self.state.get("translate", {}), progress=prog)

            def done():
                if terr or not out:
                    self.set_status(f"{_('Translation failed')}: {terr}"
                                    if terr else _("Translation failed"))
                    return False
                cfg = self.state["slot1"]
                vf.add_history("translate", out)
                threading.Thread(target=vf.speak, args=(out, cfg),
                                 daemon=True).start()
                self._sync_pause_btn()
                self.set_status(_("Reading translation..."), 1500)
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

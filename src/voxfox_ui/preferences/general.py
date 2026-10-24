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

"""voxfox_ui.preferences.general

Algemeen: line merging, settings import/export, and the documents and
tile pictures folders.
"""

import os

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.setup import apply_ui_language  # noqa: E402


class GeneralSection:
    """Algemeen: line merging, settings import/export, and the documents and
    tile pictures folders.
    """

    def _on_pick_docs_dir(self, _btn):
        """Choose a new folder for the document library.

        Existing documents move along with it, positions included, so
        the library does not appear to have emptied itself."""
        dlg = Gtk.FileDialog()
        dlg.set_title(_("Choose a folder for documents"))

        def done(source, result, *_a):
            try:
                folder = source.select_folder_finish(result)
            except Exception:
                return  # cancelled
            if folder is None or not folder.get_path():
                return
            new = folder.get_path()
            old = vf.documents.library_dir(self.state)
            if os.path.abspath(new) == os.path.abspath(old):
                return
            moved, failed = vf.documents.move_library(old, new)
            self.state["docs_dir"] = new
            vf.save_state(self.state)
            self.docs_lbl.set_text(new)
            if failed:
                self.win.set_status(
                    _("{failed} document(s) could not be moved")
                    .format(failed=failed))
            elif moved:
                self.win.set_status(
                    _("{moved} document(s) moved").format(moved=moved))

        dlg.select_folder(self, None, done)

    # ── misc: line merging + import/export ───────────────────────────────────
    # ── Documents folder (shown under General) ────────────────────────────
    def _documents_group(self):
        # Where OCR documents are kept.
        doc_frame = Gtk.Frame(label=_("Documents"))
        dbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top", "bottom", "start", "end"):
            getattr(dbox, f"set_margin_{m}")(10)
        drow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.docs_lbl = Gtk.Label(
            label=vf.documents.library_dir(self.state), xalign=0.0)
        self.docs_lbl.set_hexpand(True)
        self.docs_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        drow.append(self.docs_lbl)
        pick = Gtk.Button(label=_("Change..."))
        pick.connect("clicked", self._on_pick_docs_dir)
        drow.append(pick)
        dbox.append(drow)

        # Pictures on the tiles of Type and speak (6.1).
        plabel = Gtk.Label(label=_("Folder for tile pictures"), xalign=0.0)
        plabel.add_css_class("dim-label")
        dbox.append(plabel)
        prow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pics_lbl = Gtk.Label(xalign=0.0, hexpand=True)
        self.pics_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._show_pics_dir()
        prow.append(self.pics_lbl)
        ppick = Gtk.Button(label=_("Change..."))
        ppick.connect("clicked", self._on_pick_pics_dir)
        prow.append(ppick)
        dbox.append(prow)
        doc_frame.set_child(dbox)
        return doc_frame

    def _show_pics_dir(self):
        folder = vf.image_dir(self.state)
        self.pics_lbl.set_text(folder or _("Not chosen yet"))

    def _on_pick_pics_dir(self, *_a):
        from voxfox_ui import tilepics
        tilepics.FolderDialog(self, self.state,
                              lambda _f: self._show_pics_dir()).present()

    def _misc_group(self):
        frame = Gtk.Frame(label=_("General"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)

        self.merge_chk = Gtk.CheckButton(
            label=_("Merge wrapped lines into paragraphs"))
        self.merge_chk.set_active(bool(self.state.get("merge_lines", True)))
        self.merge_chk.connect("toggled", self._on_merge_toggled)
        box.append(self.merge_chk)

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("When reading OCR or selected text, join lines that are "
                        "only word-wrapped and pause only at real paragraphs. "
                        "Turn off to read every line separately (lists, code)."))
        box.append(desc)

        box.append(Gtk.Separator())

        slabel = Gtk.Label(xalign=0.0, label=_("Settings file"))
        box.append(slabel)
        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        imp = Gtk.Button(label=_("Import settings…"))
        imp.connect("clicked", self._on_import)
        exp = Gtk.Button(label=_("Export settings…"))
        exp.connect("clicked", self._on_export)
        btnrow.append(imp)
        btnrow.append(exp)
        box.append(btnrow)
        return frame

    def _on_merge_toggled(self, btn):
        on = btn.get_active()
        self.state["merge_lines"] = on
        vf.save_state(self.state)
        vf.set_merge_lines(on)

    def _on_export(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Export settings"), self, Gtk.FileChooserAction.SAVE, None, None)
        dlg.set_current_name("voxfox-settings.json")
        dlg.set_modal(True)
        dlg.connect("response", self._export_response)
        self._file_dlg = dlg
        dlg.show()

    def _export_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                import copy as _copy
                import json
                # Never write secrets into an export: exports get shared and
                # end up on other machines and in support mails. A list, not
                # three separate lines, so a future secret field can't be
                # added to state.py without also landing here.
                clean = _copy.deepcopy(self.state)
                for section, key in (("whisper", "remote_api_key"),
                                     ("webread", "api_key"),
                                     ("translate", "api_key")):
                    if isinstance(clean.get(section), dict):
                        clean[section][key] = ""
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(clean, f, ensure_ascii=False, indent=2)
                self.win.set_status(_("Settings exported"))
            except Exception as e:
                self.win.set_status(f"{_('Export failed')}: {e}")
        dlg.destroy()

    def _on_import(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Import settings"), self, Gtk.FileChooserAction.OPEN, None, None)
        flt = Gtk.FileFilter()
        flt.set_name("JSON")
        flt.add_pattern("*.json")
        dlg.add_filter(flt)
        dlg.set_modal(True)
        dlg.connect("response", self._import_response)
        self._file_dlg = dlg
        dlg.show()

    def _import_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                import json
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("not a settings object")
                vf.save_state(data)
                self.state = vf.load_state()
                self.win.state = self.state
                vf.set_pronunciations(self.state.get("pronunciations", {}))
                vf.set_merge_lines(self.state.get("merge_lines", True))
                apply_ui_language(self.state["slot1"].get("lang", ""))
                self.win.rebuild_ui()
                self.win.set_status(_("Settings imported"))
                dlg.destroy()
                self.close()
                return
            except Exception as e:
                self.win.set_status(f"{_('Import failed')}: {e}")
        dlg.destroy()

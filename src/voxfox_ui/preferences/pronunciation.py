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

"""voxfox_ui.preferences.pronunciation

Uitspraak: the pronunciation dictionary for the language of Taal 1.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import set_accessible_label  # noqa: E402


class PronunciationSection:
    """Uitspraak: the pronunciation dictionary for the language of Taal 1.
    """

    # ── pronunciation dictionary (slot 1's language) ─────────────────────────
    def _pronunciation_group(self):
        frame = Gtk.Frame(label=_("Pronunciation dictionary"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.set_child(box)

        self._pron_lang = self.state["slot1"].get("lang", "")
        native = vf.piper_lang_native(self._pron_lang) or self._pron_lang or "?"
        info = Gtk.Label(xalign=0.0)
        info.set_wrap(True)
        info.add_css_class("dim-label")
        info.set_text(
            _("Rules for slot 1's language (%s). Words are matched whole and "
              "case-insensitively, then re-spelled before they are spoken.")
            % native)
        box.append(info)

        hint = Gtk.Label(xalign=0.0, wrap=True)
        hint.add_css_class("dim-label")
        hint.set_text(
            _("VoxFox also applies some pronunciation fixes automatically; "
              "add your own rule here to override one."))
        box.append(hint)

        self.pron_list = Gtk.ListBox()
        self.pron_list.set_selection_mode(Gtk.SelectionMode.NONE)
        box.append(self.pron_list)
        self._pron_rows = []

        existing = self.state.get("pronunciations", {}).get(self._pron_lang, {})
        for word, repl in existing.items():
            self._add_pron_row(word, repl)
        if not self._pron_rows:
            self._add_pron_row("", "")

        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label=_("Add rule"))
        add_btn.connect("clicked", lambda *_a: self._add_pron_row("", ""))
        btnrow.append(add_btn)
        imp = Gtk.Button(label=_("Import dictionary…"))
        imp.connect("clicked", self._on_dict_import)
        btnrow.append(imp)
        exp = Gtk.Button(label=_("Export dictionary…"))
        exp.connect("clicked", self._on_dict_export)
        btnrow.append(exp)
        box.append(btnrow)

        share = Gtk.Label(xalign=0.0)
        share.set_wrap(True)
        share.add_css_class("dim-label")
        share.set_text(_("Export your dictionary to share it, or import one "
                         "from another user or from voxfox.nl."))
        box.append(share)
        return frame

    # ── dictionary files: import / export ─────────────────────────────────
    def _on_dict_export(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Export dictionary…"), self, Gtk.FileChooserAction.SAVE,
            None, None)
        code = vf.ui_code_for_piper_lang(self._pron_lang)
        dlg.set_current_name(f"voxfox-dict-{code}.json")
        dlg.set_modal(True)
        dlg.connect("response", self._dict_export_response)
        self._file_dlg = dlg
        dlg.show()

    def _dict_export_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                self._save_pron()
                rules = self.state.get("pronunciations", {}).get(
                    self._pron_lang, {})
                vf.save_dict_file(path, self._pron_lang, rules)
                self.win.set_status(_("Dictionary exported"))
            except Exception as e:
                self.win.set_status(f"{_('Export failed')}: {e}")
        dlg.destroy()

    def _on_dict_import(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Import dictionary…"), self, Gtk.FileChooserAction.OPEN,
            None, None)
        dlg.set_modal(True)
        dlg.connect("response", self._dict_import_response)
        self._file_dlg = dlg
        dlg.show()

    def _dict_import_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            self._merge_dict_file(dlg.get_file().get_path())
        dlg.destroy()

    def _merge_dict_file(self, path):
        """Merge a dictionary file into the state. Rules land under the
        language named in the file (falling back to slot 1's language); new
        words are added and existing words are updated, and the visible list
        refreshes when the current language was affected."""
        try:
            file_lang, rules = vf.load_dict_file(path)
        except Exception:
            self.win.set_status(_("Not a valid VoxFox dictionary file"))
            return
        # Capture unsaved edits in the visible rows first.
        self._save_pron()
        target = file_lang if file_lang in vf.PIPER_LANG_TO_CODE \
            else self._pron_lang
        pron = self.state.setdefault("pronunciations", {})
        cur = pron.setdefault(target, {})
        new = sum(1 for k in rules if k not in cur)
        upd = sum(1 for k in rules if k in cur and cur[k] != rules[k])
        cur.update(rules)
        if not cur:
            del pron[target]
        vf.save_state(self.state)
        vf.set_pronunciations(pron)
        if target == self._pron_lang:
            self._reload_pron_rows()
        self.win.set_status(
            _("Dictionary loaded: %s new, %s updated") % (new, upd))

    def _reload_pron_rows(self):
        """Rebuild the rule list from the state (after an import)."""
        while True:
            row = self.pron_list.get_row_at_index(0)
            if row is None:
                break
            self.pron_list.remove(row)
        self._pron_rows = []
        existing = self.state.get("pronunciations", {}).get(self._pron_lang, {})
        for word, repl in existing.items():
            self._add_pron_row(word, repl)
        if not self._pron_rows:
            self._add_pron_row("", "")

    def _add_pron_row(self, word, repl):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        we = Gtk.Entry()
        we.set_placeholder_text(_("Word"))
        we.set_text(word)
        we.set_hexpand(True)
        rep = Gtk.Entry()
        rep.set_placeholder_text(_("Pronounce as"))
        rep.set_text(repl)
        rep.set_hexpand(True)
        rm = Gtk.Button(icon_name="user-trash-symbolic")
        rm.set_tooltip_text(_("Remove rule"))
        test = Gtk.Button(icon_name="media-playback-start-symbolic")
        test.set_tooltip_text(_("Test this word"))
        set_accessible_label(we, _("Word"))
        set_accessible_label(rep, _("Pronounce as"))
        set_accessible_label(rm, _("Remove rule"))
        set_accessible_label(test, _("Test this word"))
        row.append(we)
        row.append(Gtk.Label(label="→"))
        row.append(rep)
        row.append(test)
        row.append(rm)
        lbrow = Gtk.ListBoxRow()
        lbrow.set_child(row)
        rec = {"word": we, "repl": rep, "lbrow": lbrow}

        def _test_one(*_a):
            txt = rep.get_text().strip() or we.get_text().strip()
            if txt:
                threading.Thread(target=vf.speak,
                                 args=(txt, self.state["slot1"]),
                                 daemon=True).start()
        test.connect("clicked", _test_one)

        def _remove(*_a):
            self.pron_list.remove(lbrow)
            if rec in self._pron_rows:
                self._pron_rows.remove(rec)
            self._save_pron()
        rm.connect("clicked", _remove)
        self.pron_list.append(lbrow)
        self._pron_rows.append(rec)

    def _collect_pron(self):
        d = {}
        for rec in self._pron_rows:
            w = rec["word"].get_text().strip()
            r = rec["repl"].get_text().strip()
            if w and r:
                d[w] = r
        return d

    def _save_pron(self):
        if not hasattr(self, "_pron_rows"):
            return
        d = self._collect_pron()
        pron = self.state.setdefault("pronunciations", {})
        if d:
            pron[self._pron_lang] = d
        elif self._pron_lang in pron:
            del pron[self._pron_lang]
        vf.save_state(self.state)
        vf.set_pronunciations(pron)

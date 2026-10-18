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

"""voxfox_ui.history — The reading/dictation history window.

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango    # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import _a11y  # noqa: E402


class HistoryWindow(Gtk.Window):
    """Recent read/dictated items, with re-read and copy-to-clipboard.

    Re-typing isn't offered here: VoxFox stays always-on-top and holds focus,
    so typed text would land in the wrong window. Copy lets you paste it
    wherever you actually want it.
    """
    def __init__(self, win):
        super().__init__(title=_("History"), transient_for=win)
        self.win = win
        self.set_default_size(460, 460)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{m}")(12)
        self.set_child(outer)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        sw.set_child(self.listbox)
        outer.append(sw)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_halign(Gtk.Align.END)
        clear = Gtk.Button(label=_("Clear all"))
        clear.connect("clicked", self._on_clear)
        bar.append(clear)
        outer.append(bar)

        self._reload()

    def _reload(self):
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

        items = vf.load_history()
        if not items:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            lbl = Gtk.Label(label=_("(empty)"))
            lbl.add_css_class("dim-label")
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
            row.set_child(lbl)
            self.listbox.append(row)
            return
        for it in items:
            self.listbox.append(self._row(it))

    def _row(self, it):
        kind = it.get("kind", "read")
        text = (it.get("text") or "").strip()
        oneline = " ".join(text.split())
        preview = oneline if len(oneline) <= 90 else oneline[:90] + "…"

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(6)

        is_dict = (kind == "dictate")
        icon = Gtk.Image.new_from_icon_name(
            "audio-input-microphone-symbolic" if is_dict
            else "audio-volume-high-symbolic")
        icon.set_tooltip_text(_("Dictate") if is_dict else _("Read"))
        box.append(icon)

        lbl = Gtk.Label(label=preview, xalign=0.0)
        lbl.set_hexpand(True)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_tooltip_text(oneline)
        box.append(lbl)

        read_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        read_btn.set_tooltip_text(_("Read"))
        _a11y(read_btn, _("Read"))
        read_btn.connect("clicked", lambda *_a, t=text: self._read(t))
        box.append(read_btn)

        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_btn.set_tooltip_text(_("Copy"))
        _a11y(copy_btn, _("Copy"))
        copy_btn.connect("clicked", lambda *_a, t=text: self._copy(t))
        box.append(copy_btn)

        row.set_child(box)
        return row

    def _read(self, text):
        threading.Thread(target=vf.speak, args=(text, self.win._active_cfg()),
                         daemon=True).start()
        self.win.set_status(_("Re-reading from history"))

    def _copy(self, text):
        ok = vf._clipboard_set(text)
        self.win.set_status(_("Copied to clipboard") if ok else _("Copy failed"))

    def _on_clear(self, _btn):
        vf.save_history([])
        self._reload()
        self.win.set_status(_("History cleared"))



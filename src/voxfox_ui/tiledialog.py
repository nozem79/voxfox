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

"""voxfox_ui.tiledialog — The dialog for one tile of Type and speak: its
text, kind, picture and place, moving it, and removing it.
"""


import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import set_accessible_label  # noqa: E402
from voxfox_ui import tilepics  # noqa: E402


# Plain-language names of the tile kinds, in TILE_KINDS order.
KIND_NAMES = {
    "phrase": "Sentence",
    "social": "Social",
    "person": "Person",
    "action": "Action",
    "describe": "Describing word",
    "thing": "Thing or feeling",
    "question": "Question",
}


class TileDialog(Gtk.Window):
    """Change one tile (text, kind, place, or remove it), or add a new one
    when `index` is None."""

    def __init__(self, owner, tiles, index, code):
        new = index is None
        super().__init__(title=_("New tile") if new else _("Change tile"),
                         transient_for=owner, modal=True)
        self.owner = owner
        self.tiles = list(tiles)
        self.index = index
        self.code = code            # the board these tiles belong to
        self.set_default_size(420, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(16)
        self.set_child(box)

        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        grid.attach(Gtk.Label(label=_("Text") + ":", xalign=0.0), 0, 0, 1, 1)
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.set_max_length(vf.TILE_TEXT_MAX)
        set_accessible_label(self.entry, _("Text"))
        grid.attach(self.entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Kind") + ":", xalign=0.0), 0, 1, 1, 1)
        self.kind = Gtk.DropDown.new_from_strings(
            [_(KIND_NAMES[k]) for k in vf.TILE_KINDS])
        set_accessible_label(self.kind, _("Kind"))
        grid.attach(self.kind, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label=_("Picture") + ":", xalign=0.0), 0, 2, 1, 1)
        prow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.preview = Gtk.Image()
        self.preview.set_pixel_size(56)
        prow.append(self.preview)
        choose = Gtk.Button(label=_("Choose picture…"),
                            valign=Gtk.Align.CENTER)
        choose.connect("clicked", self._on_choose_picture)
        prow.append(choose)
        self.drop_pic = Gtk.Button(label=_("No picture"),
                                   valign=Gtk.Align.CENTER)
        self.drop_pic.connect("clicked", lambda *_a: self._set_picture(None))
        prow.append(self.drop_pic)
        grid.attach(prow, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label=_("Place") + ":", xalign=0.0), 0, 3, 1, 1)
        self.pos = Gtk.DropDown.new_from_strings(
            [_("Left"), _("Right"), _("Middle")])
        self.pos.set_tooltip_text(_("Where the picture goes on the tile; "
                                    "Middle puts it above the text"))
        set_accessible_label(self.pos, _("Place"))
        grid.attach(self.pos, 1, 3, 1, 1)
        box.append(grid)
        self.pic_msg = Gtk.Label(xalign=0.0, wrap=True)
        self.pic_msg.add_css_class("dim-label")
        self.pic_msg.set_visible(False)
        box.append(self.pic_msg)

        self.image = None
        if new:
            self.entry.set_text("")
            self.kind.set_selected(vf.TILE_KINDS.index("thing"))
            self.pos.set_selected(0)
        else:
            t = self.tiles[index]
            self.entry.set_text(t["text"])
            self.kind.set_selected(vf.TILE_KINDS.index(t["kind"]))
            self.pos.set_selected(vf.IMAGE_POSITIONS.index(
                t.get("image_pos", "left")))
            self.image = t.get("image")
        self._set_picture(self.image)
        self.entry.connect("activate", lambda *_a: self._save())

        if not new:
            moves = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            earlier = Gtk.Button(label=_("Move earlier"))
            earlier.connect("clicked", lambda *_a: self._move(-1))
            later = Gtk.Button(label=_("Move later"))
            later.connect("clicked", lambda *_a: self._move(+1))
            remove = Gtk.Button(label=_("Remove tile"))
            remove.add_css_class("destructive-action")
            remove.connect("clicked", lambda *_a: self._remove())
            moves.append(earlier)
            moves.append(later)
            moves.append(Gtk.Box(hexpand=True))
            moves.append(remove)
            box.append(moves)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_a: self.close())
        save = Gtk.Button(label=_("Save"))
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_a: self._save())
        bottom.append(cancel)
        bottom.append(save)
        box.append(bottom)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a:
                     (self.close(), True)[1] if kv == Gdk.KEY_Escape else False)
        self.add_controller(keys)
        self.entry.grab_focus()

    def _tile(self):
        tile = {"text": self.entry.get_text(),
                "kind": vf.TILE_KINDS[self.kind.get_selected()]}
        if self.image:
            tile["image"] = self.image
            tile["image_pos"] = vf.IMAGE_POSITIONS[self.pos.get_selected()]
        return tile

    def _set_picture(self, name):
        self.image = name
        path = tilepics.picture_path(self.owner.state, name) if name else None
        if path:
            self.preview.set_from_file(path)
        else:
            self.preview.clear()
        self.preview.set_visible(bool(path))
        self.drop_pic.set_visible(bool(name))
        self.pos.set_sensitive(bool(name))

    def _on_choose_picture(self, *_a):
        def picked(name, size, shrunk):
            if name is None:
                self.pic_msg.set_text(size)       # the error message
            elif shrunk:
                self.pic_msg.set_text(
                    _("The picture was made smaller to fit (%d kB).")
                    % max(1, round(size / 1024)))
            else:
                self.pic_msg.set_text("")
            self.pic_msg.set_visible(bool(self.pic_msg.get_text()))
            if name:
                self._set_picture(name)
        tilepics.choose_picture(self, self.owner.state, picked)

    def _save(self):
        tile = self._tile()
        if not " ".join(tile["text"].split()):
            self.entry.grab_focus()
            return
        if self.index is None:
            self.tiles.append(tile)
        else:
            self.tiles[self.index] = tile
        self.owner.tiles_changed(self.tiles, self.code)
        self.close()

    def _move(self, delta):
        if self.index is None:
            return
        tile = self._tile()
        if not " ".join(tile["text"].split()):
            # An empty text box: move the tile with the text it had.
            tile["text"] = self.tiles[self.index]["text"]
        self.tiles[self.index] = tile
        self.tiles, self.index = vf.move_tile(self.tiles, self.index, delta)
        self.owner.tiles_changed(self.tiles, self.code)

    def _remove(self):
        if self.index is None:
            return
        dlg = Gtk.AlertDialog(message=_("Remove the tile \u201c{text}\u201d?").format(
            text=self.tiles[self.index]["text"]))
        dlg.set_buttons([_("Cancel"), _("Remove tile")])
        dlg.set_cancel_button(0)
        dlg.set_default_button(0)       # Enter keeps the tile

        def done(d, res):
            try:
                if d.choose_finish(res) != 1:
                    return
            except Exception as e:      # closed without choosing
                log.debug(f"tile dialog: remove question: {e}")
                return
            del self.tiles[self.index]
            self.owner.tiles_changed(self.tiles, self.code)
            self.close()
        dlg.choose(self, None, done)

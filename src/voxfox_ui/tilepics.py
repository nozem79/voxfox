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

"""voxfox_ui.tilepics — pictures on tiles (6.1).

The pictures folder: the user picks where it goes and VoxFox makes it.
Adding a picture: a file over 50 kB is scaled down (GdkPixbuf, part of
GTK) until it fits, and stored under a name made from its contents.
"""

import os
import shutil

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log


# ── files ────────────────────────────────────────────────────────────────────

_MAX_PIXELS = 100_000_000      # 100 megapixels: far above any camera photo
_LOAD_SIDE = 1536

def icon_dirs():
    """Where the pictograms of the ready-made tiles can be: installed
    packages ship icons/ under the system data folder, the Nix package
    puts it next to voxfox_ui/, a git checkout two levels up."""
    from voxfox_ui.common import SYSTEM_DATA_DIR
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(SYSTEM_DATA_DIR, "icons", "tiles"),
            os.path.normpath(os.path.join(here, "..", "icons", "tiles")),
            os.path.normpath(os.path.join(here, "..", "..", "icons", "tiles"))]


def icon_path(name):
    """Full path of a pictogram ("icon:dorst"), or None."""
    if not vf.is_icon_name(name):
        return None
    file = name[len(vf.ICON_PREFIX):] + ".svg"
    for d in icon_dirs():
        path = os.path.join(d, file)
        if os.path.isfile(path):
            return path
    return None


def picture_path(state, name):
    """Full path of a tile's picture (a pictogram VoxFox ships, or a
    picture the user added), or None when it is not there."""
    if vf.is_icon_name(name):
        return icon_path(name)
    folder = vf.image_dir(state)
    if not folder or not vf.is_safe_image_name(name):
        return None
    path = os.path.join(folder, name)
    return path if os.path.isfile(path) else None


def _encoder(pixbuf):
    has_alpha = pixbuf.get_has_alpha()

    def encode(w, h, fmt, quality):
        try:
            if fmt == "jpeg" and has_alpha:
                # JPEG has no transparency: put the picture on white.
                small = pixbuf.composite_color_simple(
                    w, h, GdkPixbuf.InterpType.BILINEAR, 255, 8,
                    0xFFFFFF, 0xFFFFFF)
            else:
                small = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
            keys, vals = ([], []) if quality is None else (["quality"],
                                                           [str(quality)])
            ok, data = small.save_to_bufferv(fmt, keys, vals)
            return bytes(data) if ok else None
        except GLib.Error as e:
            log.debug(f"tile picture: encoding {fmt} failed: {e}")
            return None
    return encode


def shrink_picture(path):
    """The picture at `path` as (bytes, ext, was_shrunk), at most
    vf.IMAGE_MAX_BYTES. Raises ValueError with a message for the user
    when it cannot be read or made small enough."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as fh:
            raw = fh.read(vf.IMAGE_MAX_BYTES + 1)
    except OSError as e:
        raise ValueError(_("Could not open the picture: %s") % e) from e
    # Always open it, also when it is small: a file that only has a
    # picture's name is refused here rather than showing an empty tile.
    # First only the header: a small file can still claim to be an
    # enormous picture, and decoding that whole would fill the memory.
    # The picture is then decoded at most _LOAD_SIDE pixels wide or high,
    # enough for a tile (target_sides stays below 400).
    fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
    if fmt is None or not w or not h:
        raise ValueError(_("This file is not a picture VoxFox can read."))
    if w * h > _MAX_PIXELS:
        raise ValueError(_("This file is not a picture VoxFox can read."))
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            path, min(w, _LOAD_SIDE), min(h, _LOAD_SIDE), True)
        pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
    except GLib.Error as e:
        raise ValueError(_("This file is not a picture VoxFox can read.")) from e
    if len(raw) <= vf.IMAGE_MAX_BYTES and ext in vf.IMAGE_EXTS:
        return raw, ext, False
    sizes = vf.target_sides(pixbuf.get_width(), pixbuf.get_height())
    data, new_ext = vf.pick_encoding(sizes, _encoder(pixbuf),
                                     pixbuf.get_has_alpha())
    if data is None:
        raise ValueError(_("The picture could not be made small enough."))
    return data, new_ext, True


def store_picture(state, path):
    """Copy (and if needed shrink) a picture into the pictures folder.
    Returns (file name, size in bytes, was_shrunk)."""
    folder = vf.image_dir(state)
    if not folder:
        raise ValueError(_("Choose a folder for tile pictures first."))
    data, ext, shrunk = shrink_picture(path)
    os.makedirs(folder, exist_ok=True)
    name = vf.image_file_name(data, ext)
    target = os.path.join(folder, name)
    if not os.path.exists(target):
        tmp = target + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    return name, len(data), shrunk


def _copy_pictures(old, new):
    """Bring the pictures along when the folder changes (copies; the old
    folder is left alone)."""
    if not old or not os.path.isdir(old) or os.path.abspath(old) == os.path.abspath(new):
        return 0
    n = 0
    for name in os.listdir(old):
        src = os.path.join(old, name)
        dst = os.path.join(new, name)
        if (vf.is_safe_image_name(name) and os.path.isfile(src)
                and not os.path.exists(dst)):
            try:
                shutil.copy2(src, dst)
                n += 1
            except OSError as e:
                log.warning(f"tile pictures: could not copy {name}: {e}")
    return n


# ── choosing the folder ─────────────────────────────────────────────────────

class FolderDialog(Gtk.Window):
    """Ask where the pictures folder goes; VoxFox then makes it.

    `on_done(path)` is called with the folder once it exists (not when
    the user cancels)."""

    def __init__(self, parent, state, on_done=None):
        super().__init__(title=_("Folder for tile pictures"),
                         transient_for=parent, modal=True)
        self.state = state
        self.on_done = on_done
        self.set_default_size(480, -1)
        current = vf.image_dir(state)
        self.parent_dir = (os.path.dirname(current) if current
                           else vf.documents.default_dir())
        # An existing folder keeps its own name. Taking the translated
        # name again would, after a language switch, propose a second
        # folder ("Tile pictures" next to "Tegelafbeeldingen").
        self.dir_name = (os.path.basename(current) if current
                         else _(vf.IMAGE_DIR_NAME))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(16)
        self.set_child(box)
        intro = Gtk.Label(
            label=_("VoxFox keeps the pictures of your tiles in a folder of "
                    "their own. Choose where that folder goes; VoxFox makes "
                    "it for you."), xalign=0.0, wrap=True)
        box.append(intro)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.path_lbl = Gtk.Label(xalign=0.0, hexpand=True, wrap=True)
        self.path_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.path_lbl.set_selectable(True)
        self.path_lbl.add_css_class("heading")
        row.append(self.path_lbl)
        other = Gtk.Button(label=_("Other place…"))
        other.connect("clicked", self._on_other)
        row.append(other)
        box.append(row)
        self.err = Gtk.Label(xalign=0.0, wrap=True)
        self.err.add_css_class("error")
        self.err.set_visible(False)
        box.append(self.err)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_a: self.close())
        make = Gtk.Button(label=_("Make folder"))
        make.add_css_class("suggested-action")
        make.connect("clicked", self._on_make)
        bottom.append(cancel)
        bottom.append(make)
        box.append(bottom)
        self._show_path()

    def _target(self):
        return os.path.join(self.parent_dir, self.dir_name)

    def _show_path(self):
        path, home = self._target(), os.path.expanduser("~")
        if path.startswith(home + os.sep):
            path = "~" + path[len(home):]
        self.path_lbl.set_text(path)

    def _on_other(self, *_a):
        dlg = Gtk.FileDialog(title=_("Where should the folder go?"))
        if os.path.isdir(self.parent_dir):
            dlg.set_initial_folder(Gio.File.new_for_path(self.parent_dir))

        def done(d, res):
            try:
                f = d.select_folder_finish(res)
            except GLib.Error:
                return          # cancelled
            if f is not None and f.get_path():
                self.parent_dir = f.get_path()
                self._show_path()
        dlg.select_folder(self, None, done)

    def _on_make(self, *_a):
        target = self._target()
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as e:
            self.err.set_text(_("Could not make the folder: %s") % e)
            self.err.set_visible(True)
            return
        old = vf.image_dir(self.state)
        copied = _copy_pictures(old, target)
        if copied:
            log.info(f"tile pictures: copied {copied} to {target}")
        self.state["type_image_dir"] = target
        vf.save_state(self.state)
        self.close()
        if self.on_done:
            self.on_done(target)


def ensure_folder(parent, state, then):
    """Run `then(folder)` once a pictures folder exists, asking for one
    first when none has been chosen (or it has gone)."""
    folder = vf.image_dir(state)
    if folder and os.path.isdir(folder):
        then(folder)
        return
    FolderDialog(parent, state, then).present()


def choose_picture(parent, state, on_picked):
    """Let the user pick a picture file; it is stored in the pictures
    folder and `on_picked(name, size, shrunk)` is called. Errors go to
    `on_picked(None, message, False)`."""
    def pick(_folder):
        dlg = Gtk.FileDialog(title=_("Choose a picture"))
        flt = Gtk.FileFilter()
        flt.set_name(_("Pictures"))
        for mime in ("image/png", "image/jpeg", "image/svg+xml",
                     "image/webp", "image/gif"):
            flt.add_mime_type(mime)
        for ext in vf.IMAGE_EXTS:
            flt.add_suffix(ext.lstrip("."))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        dlg.set_filters(filters)
        dlg.set_default_filter(flt)
        # Open where the last picture came from, so a folder of tile
        # pictures does not have to be looked up again for every tile.
        start = vf.picture_start_folder(
            state, GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES))
        if start:
            dlg.set_initial_folder(Gio.File.new_for_path(start))

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return          # cancelled
            path = f.get_path() if f is not None else None
            if not path:
                return
            if vf.remember_picture_folder(state, path):
                vf.save_state(state)
            try:
                name, size, shrunk = store_picture(state, path)
            except (ValueError, OSError) as e:
                on_picked(None, str(e), False)
                return
            on_picked(name, size, shrunk)
        dlg.open(parent, None, done)
    ensure_folder(parent, state, pick)

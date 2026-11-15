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

"""voxfox_ui.preferences.touchbutton

Settings for the floating touch button (6.3): on or off, its size, and
which action goes with each way of pressing it.
"""

import copy

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402
from voxfox_ui.widgets import set_accessible_label  # noqa: E402

log = vf.log


def _hint(text):
    lbl = Gtk.Label(label=text, xalign=0.0)
    lbl.set_wrap(True)
    lbl.add_css_class("dim-label")
    return lbl


class TouchButtonSection:
    """The Touch button page of the settings window."""

    def _touch_group(self):
        from voxfox_ui.touchbutton import action_labels, gesture_labels
        cfg = vf.normalize_touch_button(self.state.get("touch_button"))
        self.state["touch_button"] = cfg
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        frame = Gtk.Frame(label=_("Touch button"))
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.touch_chk = Gtk.CheckButton(label=_("Show the touch button"))
        self.touch_chk.set_active(cfg["enabled"])
        self.touch_chk.connect("toggled", self._on_touch_toggled)
        inner.append(self.touch_chk)
        inner.append(_hint(_(
            "A round button that stays on top of all windows. Tap it or "
            "hold it to read, pause or stop. Drag it to move it. Handy on "
            "a touchscreen.")))
        if vf.IS_WAYLAND and not vf.is_x11_client():
            inner.append(_hint(_(
                "On Wayland, VoxFox starts through XWayland to keep the "
                "button on top. Restart VoxFox after switching it on.")))

        srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        slbl = Gtk.Label(label=_("Size:"), xalign=0.0)
        srow.append(slbl)
        names = [_("Small"), _("Normal"), _("Large")]
        self.touch_size = Gtk.DropDown.new_from_strings(names)
        self.touch_size.set_selected(vf.SIZES.index(cfg["size"]))
        self.touch_size.connect("notify::selected", self._on_touch_size)
        set_accessible_label(self.touch_size, _("Size of the touch button"))
        srow.append(self.touch_size)
        inner.append(srow)

        self.touch_hide = Gtk.CheckButton(
            label=_("Hide the VoxFox window while the touch button is on"))
        self.touch_hide.set_active(cfg["hide_window"])
        self.touch_hide.connect("toggled", self._on_touch_hide)
        inner.append(self.touch_hide)
        inner.append(_hint(_(
            "The window goes away when you close Settings. Open VoxFox "
            "again from the app menu to see it, or give a gesture the "
            "action \"Show or hide the VoxFox window\".")))
        frame.set_child(inner)
        box.append(frame)

        aframe = Gtk.Frame(label=_("What the button does"))
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        acts = action_labels()
        self._touch_ids = [a for a, _n in acts]
        self._touch_drops = {}
        for row, (g, glabel) in enumerate(gesture_labels().items()):
            lbl = Gtk.Label(label=glabel + ":", xalign=0.0)
            grid.attach(lbl, 0, row, 1, 1)
            dd = Gtk.DropDown.new_from_strings([n for _a, n in acts])
            dd.set_selected(self._touch_ids.index(cfg["actions"][g]))
            dd.set_hexpand(True)
            dd.connect("notify::selected", self._on_touch_action, g)
            set_accessible_label(dd, glabel)
            grid.attach(dd, 1, row, 1, 1)
            self._touch_drops[g] = dd
        reset = Gtk.Button(label=_("Back to the standard actions"))
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", self._on_touch_reset)
        grid.attach(reset, 0, len(self._touch_drops), 2, 1)
        aframe.set_child(grid)
        box.append(aframe)
        return box

    def _touch_save(self):
        vf.save_state(self.state)
        try:
            self.win.apply_touch_button()
        except Exception as e:
            log.debug(f"touch button refresh failed: {e}")

    def _on_touch_toggled(self, chk):
        self.state["touch_button"]["enabled"] = chk.get_active()
        self._touch_want_hide()
        self._touch_save()

    def _on_touch_hide(self, chk):
        self.state["touch_button"]["hide_window"] = chk.get_active()
        self._touch_want_hide()
        self._touch_save()

    def _touch_want_hide(self):
        """Hide the main window once Settings closes, if the settings now
        say so (see TouchMixin.sync_main_window)."""
        tb = self.state["touch_button"]
        self.win._touch_hide_pending = bool(tb["enabled"] and
                                            tb["hide_window"])

    def _on_touch_size(self, dd, _pspec):
        i = dd.get_selected()
        if 0 <= i < len(vf.SIZES):
            self.state["touch_button"]["size"] = vf.SIZES[i]
            self._touch_save()

    def _on_touch_action(self, dd, _pspec, gesture):
        if getattr(self, "_touch_resetting", False):
            return
        i = dd.get_selected()
        if 0 <= i < len(self._touch_ids):
            self.state["touch_button"]["actions"][gesture] = self._touch_ids[i]
            self._touch_save()

    def _on_touch_reset(self, _btn):
        defaults = copy.deepcopy(vf.DEFAULT_TOUCH_BUTTON["actions"])
        self.state["touch_button"]["actions"] = defaults
        self._touch_resetting = True
        try:
            for g, dd in self._touch_drops.items():
                dd.set_selected(self._touch_ids.index(defaults[g]))
        finally:
            self._touch_resetting = False
        self._touch_save()

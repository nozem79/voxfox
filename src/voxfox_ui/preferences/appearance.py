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

"""voxfox_ui.preferences.appearance

Weergave: size, light or dark, button style and layout, and which
buttons show.
"""


import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import TOOLBAR_BUTTONS, TOOLBAR_DEFAULT_HIDDEN, TOOLBAR_IDS  # noqa: E402


class AppearanceSection:
    """Weergave: size, light or dark, button style and layout, and which
    buttons show.
    """

    # ── Interface: UI scale + modular toolbar (3.0) ──────────────────────────
    def _interface_group(self):
        layout = vf.reconcile_toolbar_layout(self.state.get("ui_layout"),
                                             TOOLBAR_IDS,
                                             TOOLBAR_DEFAULT_HIDDEN)
        self.state["ui_layout"] = layout

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        # Interface size: 75 / 100 / 125 % as a radio group.
        size_frame = Gtk.Frame(label=_("Interface size"))
        srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(srow, f"set_margin_{m}")(10)
        radios, leader = [], None
        for s in vf.UI_SCALES:
            rb = Gtk.CheckButton(label=f"{s}%")
            if leader is None:
                leader = rb
            else:
                rb.set_group(leader)
            radios.append((s, rb))
            srow.append(rb)
        for s, rb in radios:
            rb.set_active(s == layout["scale"])
        for s, rb in radios:
            rb.connect("toggled", self._on_scale_toggled, s)
        size_frame.set_child(srow)
        box.append(size_frame)

        # Light or dark, or whatever the desktop uses.
        scheme_frame = Gtk.Frame(label=_("Light or dark"))
        crow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(crow, f"set_margin_{m}")(10)
        cur_scheme = self.state.get("color_scheme", "system")
        cleader = None
        for val, lbl in (("system", _("Same as the system")),
                         ("light", _("Light")), ("dark", _("Dark"))):
            rb = Gtk.CheckButton(label=lbl)
            if cleader is None:
                cleader = rb
            else:
                rb.set_group(cleader)
            rb.set_active(val == cur_scheme)
            rb.connect("toggled", self._on_scheme_toggled, val)
            crow.append(rb)
        scheme_frame.set_child(crow)
        box.append(scheme_frame)

        # Button display: icons only / icon + text / text only.
        view_frame = Gtk.Frame(label=_("Button display"))
        vrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(vrow, f"set_margin_{m}")(10)
        view_labels = [("icons", _("Icon only")), ("both", _("Icon and text")),
                       ("text", _("Text only"))]
        vleader = None
        cur_view = self.state.get("ui_view", "both")
        for val, lbl in view_labels:
            rb = Gtk.CheckButton(label=lbl)
            if vleader is None:
                vleader = rb
            else:
                rb.set_group(vleader)
            rb.set_active(val == cur_view)
            rb.connect("toggled", self._on_view_toggled, val)
            vrow.append(rb)
        view_frame.set_child(vrow)
        box.append(view_frame)

        # Orientation: horizontal (rows) or vertical (a narrow column).
        or_frame = Gtk.Frame(label=_("Orientation"))
        orow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(orow, f"set_margin_{m}")(10)
        cur_or = self.state.get("ui_orientation", "horizontal")
        oleader = None
        for val, lbl in [("horizontal", _("Horizontal")),
                         ("vertical", _("Vertical"))]:
            rb = Gtk.CheckButton(label=lbl)
            if oleader is None:
                oleader = rb
            else:
                rb.set_group(oleader)
            rb.set_active(val == cur_or)
            rb.connect("toggled", self._on_orient_toggled, val)
            orow.append(rb)
        or_frame.set_child(orow)
        box.append(or_frame)

        # Stay on top. On Wayland this decides the GTK backend, which is
        # only chosen while starting up, hence the note about restarting.
        top_frame = Gtk.Frame(label=_("Window"))
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top", "bottom", "start", "end"):
            getattr(tbox, f"set_margin_{m}")(10)
        self.ontop_chk = Gtk.CheckButton(
            label=_("Stay on top of other windows"))
        self.ontop_chk.set_active(self.state.get("always_on_top", True))
        self.ontop_chk.connect("toggled", self._on_ontop_toggled)
        tbox.append(self.ontop_chk)
        if vf.IS_WAYLAND:
            hint = Gtk.Label(
                label=_("On Wayland, VoxFox starts through XWayland to do "
                        "this. The change takes effect the next time you "
                        "start VoxFox."))
            hint.set_wrap(True)
            hint.set_xalign(0.0)
            hint.add_css_class("dim-label")
            tbox.append(hint)
        top_frame.set_child(tbox)
        box.append(top_frame)


        # Buttons: per-button visibility toggle + up/down reordering.
        btn_frame = Gtk.Frame(label=_("Buttons"))
        self._iface_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=4)
        for m in ("top", "bottom", "start", "end"):
            getattr(self._iface_list, f"set_margin_{m}")(10)
        self._populate_button_list()
        btn_frame.set_child(self._iface_list)
        box.append(btn_frame)
        return box

    def _on_ontop_toggled(self, chk):
        self.state["always_on_top"] = chk.get_active()
        vf.save_state(self.state)
        # Switching it on mid-session works right away on X11 and on
        # XWayland; switching it off only stops us re-asserting it.
        if chk.get_active():
            self.win.set_always_on_top()

    def _on_orient_toggled(self, rb, val):
        if not rb.get_active():
            return
        self.state["ui_orientation"] = val
        vf.save_state(self.state)
        self.win._apply_ui_mode()

    def _on_view_toggled(self, rb, val):
        if not rb.get_active():
            return
        self.state["ui_view"] = val
        vf.save_state(self.state)
        self.win._apply_ui_mode()

    def _on_scheme_toggled(self, rb, val):
        if not rb.get_active():
            return
        self.state["color_scheme"] = val
        vf.save_state(self.state)
        from voxfox_ui import theme
        theme.apply(val)

    def _on_scale_toggled(self, rb, scale):
        if rb.get_active():
            self.win.apply_ui_scale(scale)

    def _populate_button_list(self):
        # Clear current rows.
        child = self._iface_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._iface_list.remove(child)
            child = nxt
        labels = {b[0]: b[2] for b in TOOLBAR_BUTTONS}
        labels["switch"] = "Switch language"
        buttons = self.state["ui_layout"]["buttons"]
        if vf.IS_WAYLAND:
            # Hover mode can't work under Wayland (see do_hover()); don't
            # even list a checkbox for it here, since toggling it "on"
            # wouldn't do anything -- the toolbar filters it out regardless.
            buttons = [e for e in buttons if e["id"] != "hover"]
        n = len(buttons)
        for i, entry in enumerate(buttons):
            bid = entry["id"]
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            chk = Gtk.CheckButton(label=_(labels.get(bid, bid)))
            chk.set_active(entry["visible"])
            chk.set_hexpand(True)
            chk.connect("toggled", self._on_btn_visible, bid)
            up = Gtk.Button(icon_name="go-up-symbolic")
            up.set_tooltip_text(_("Move up"))
            up.set_sensitive(i > 0)
            up.connect("clicked", self._on_btn_move, bid, -1)
            down = Gtk.Button(icon_name="go-down-symbolic")
            down.set_tooltip_text(_("Move down"))
            down.set_sensitive(i < n - 1)
            down.connect("clicked", self._on_btn_move, bid, 1)
            row.append(chk)
            row.append(up)
            row.append(down)
            self._iface_list.append(row)

    def _on_btn_visible(self, chk, bid):
        for e in self.state["ui_layout"]["buttons"]:
            if e["id"] == bid:
                e["visible"] = chk.get_active()
                break
        vf.save_state(self.state)
        self.win.rebuild_ui()

    def _on_btn_move(self, _btn, bid, delta):
        buttons = self.state["ui_layout"]["buttons"]
        idx = next((i for i, e in enumerate(buttons) if e["id"] == bid), None)
        if idx is None:
            return
        new = idx + delta
        if new < 0 or new >= len(buttons):
            return
        buttons[idx], buttons[new] = buttons[new], buttons[idx]
        vf.save_state(self.state)
        self._populate_button_list()
        self.win.rebuild_ui()

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


"""voxfox_ui.selfread — hover reading for VoxFox's own windows.

Hover reading asks AT-SPI which element is at a screen position. GTK 4
cannot answer that properly: it does not know where its windows are on
the screen, so the positions it reports are relative to the window. For
VoxFox's own windows that meant silence (or, worse, text from whatever
window was behind it). VoxFox does not need AT-SPI to look at itself:
this module finds the widget under the pointer directly with GTK and
reads its label.

The hover loop runs in a background thread; everything that touches GTK
runs on the main thread through GLib.idle_add, and the screen positions
of our windows are looked up in between, off the main thread.
"""

import os
import re
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # noqa: E402
except Exception:          # no X11 backend (Wayland): nothing to do here
    GdkX11 = None

import voxfox_core as vf  # noqa: E402

log = vf.log

# How long the hover thread waits for the main thread. Generous: the main
# loop is normally idle; if it is busy, giving up beats freezing hover.
_WAIT = 1.0

_CONTROL_TYPES = (Gtk.Button, Gtk.CheckButton, Gtk.Switch, Gtk.DropDown,
                  Gtk.Entry, Gtk.SpinButton, Gtk.Scale, Gtk.Expander,
                  Gtk.ListBoxRow, Gtk.MenuButton)
# Controls built out of other controls: a dropdown and a menu button hold
# an inner button, a spin button an inner entry. The outer one is what the
# user sees, so it wins over whatever inner part was hit.
_COMPOSITE_TYPES = (Gtk.DropDown, Gtk.MenuButton, Gtk.SpinButton)
# Menu items in a popover menu are GtkModelButton, which Python cannot name.
_CONTROL_TYPE_NAMES = {"GtkModelButton"}


def _on_main(fn, *args):
    """Run fn on the GTK main thread and return its result (or None after
    _WAIT seconds)."""
    box, done = {}, threading.Event()

    def run():
        try:
            box["r"] = fn(*args)
        except Exception as e:
            log.debug(f"selfread: {e}")
        done.set()
        return False
    GLib.idle_add(run)
    done.wait(_WAIT)
    return box.get("r")


def _our_surfaces():
    """(native widget, X window id) for every visible VoxFox window and
    popover, popovers first: they lie on top of the windows."""
    if GdkX11 is None:
        return []
    out, pops = [], []
    for win in Gtk.Window.list_toplevels():
        if not win.get_visible() or not win.get_mapped():
            continue
        _collect_popovers(win, pops)
        out.append(win)
    # Without help from the X server the stacking order is unknown; the
    # active window and dialogs (which sit on top of their parent) first.
    out.sort(key=lambda w: (not w.is_active(), w.get_transient_for() is None))
    result = []
    for native in pops + out:
        try:
            surface = native.get_surface()
            if surface is not None and isinstance(surface, GdkX11.X11Surface):
                result.append((native, surface.get_xid()))
        except Exception:
            continue
    return result


def _collect_popovers(widget, out):
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Popover) and child.get_mapped():
            out.append(child)
        _collect_popovers(child, out)
        child = child.get_next_sibling()


def _frame_of(xid):
    """The window directly below the root that contains `xid`: the window
    manager's frame around it (or `xid` itself without a window manager).
    None when python-xlib is not available."""
    try:
        from voxfox_core import pointer
        disp = pointer.get_xlib_display()
        if disp is None:
            return None
        win = disp.create_resource_object("window", xid)
        root = disp.screen().root.id
        while True:
            tree = win.query_tree()
            if tree.parent is None or tree.parent.id == root:
                return win.id
            win = tree.parent
    except Exception:
        return None


_GEOM = re.compile(r"Position:\s*(-?\d+),(-?\d+).*?Geometry:\s*(\d+)x(\d+)", re.S)


def _geometry(xid):
    """Screen position and size of an X window.

    Asked from the X server directly when python-xlib is there. xdotool's
    getwindowgeometry counts the window manager's title bar into the
    position of a window that has one (the Settings window does, the main
    window draws its own), which put every pointer position one row too
    high: hovering over a settings section read the one above it."""
    try:
        from voxfox_core import pointer
        disp = pointer.get_xlib_display()
        if disp is not None:
            win = disp.create_resource_object("window", xid)
            root = disp.screen().root
            origin = root.translate_coords(win, 0, 0)
            g = win.get_geometry()
            return (origin.x, origin.y, g.width, g.height)
    except Exception as e:
        log.debug(f"selfread: Xlib geometry failed: {e}")
    try:
        r = subprocess.run(["xdotool", "getwindowgeometry", str(xid)],
                           capture_output=True, text=True, timeout=1.0)
        m = _GEOM.search(r.stdout)
        if m:
            return tuple(int(v) for v in m.groups())
    except Exception:
        pass
    return None


def _labels_below(widget, out):
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label) and child.get_visible():
            t = child.get_text().strip()
            if t:
                out.append(t)
        elif child.get_visible():
            _labels_below(child, out)
        child = child.get_next_sibling()
    return out


def widget_text(widget):
    """What to say for the widget under the pointer: the control it belongs
    to (button, menu item, checkbox, dropdown, field, slider) by its visible
    text, or by its tooltip when it shows only an icon; otherwise the label
    that was hit."""
    chain = []
    w = widget
    while w is not None and not isinstance(w, (Gtk.Window, Gtk.Popover)):
        chain.append(w)
        w = w.get_parent()
    composite = next((a for a in reversed(chain) if isinstance(a, _COMPOSITE_TYPES)), None)
    control = composite or next(
        (a for a in chain if isinstance(a, _CONTROL_TYPES)
         or a.__gtype__.name in _CONTROL_TYPE_NAMES), None)
    if control is not None:
        return _control_text(control) or _tooltip_up(control)
    if isinstance(widget, Gtk.Label):
        return widget.get_text().strip()
    return _tooltip_up(widget)


def _tooltip_up(widget):
    """The nearest tooltip at or above `widget`: the description of an
    icon-only button lives there."""
    w = widget
    while w is not None and not isinstance(w, (Gtk.Window, Gtk.Popover)):
        tip = w.get_tooltip_text()
        if tip:
            return tip
        w = w.get_parent()
    return ""


def _control_text(w):
    if isinstance(w, Gtk.DropDown):
        item = w.get_selected_item()
        return item.get_string() if item is not None else ""
    if isinstance(w, Gtk.SpinButton):
        return str(w.get_value_as_int())
    if isinstance(w, Gtk.Entry):
        return w.get_text() or (w.get_placeholder_text() or "")
    if isinstance(w, Gtk.Scale):
        return f"{w.get_value():g}"
    if isinstance(w, Gtk.Expander):
        return w.get_label() or " ".join(_labels_below(w, []))
    if isinstance(w, Gtk.Switch):
        return w.get_tooltip_text() or ""
    text = " ".join(_labels_below(w, []))
    if not text and isinstance(w, Gtk.CheckButton):
        text = w.get_label() or ""
    return text or (w.get_tooltip_text() or "")


def _pick(native, local_x, local_y):
    """Text of the widget at a position inside one of our surfaces."""
    try:
        ox, oy = native.get_surface_transform()
    except Exception:
        ox, oy = 0.0, 0.0
    hit = native.pick(local_x - ox, local_y - oy, Gtk.PickFlags.DEFAULT)
    return widget_text(hit) if hit is not None else ""


def text_at(x, y):
    """Called from the hover thread. None when (x, y) is not on a VoxFox
    window or popover; otherwise the text to speak there ("" for nothing).

    The X server says which window is on top under the pointer; when that
    is one of ours, that one is read, so a VoxFox window covered by another
    window is never read by mistake. Without a window manager (or when the
    answer is unclear) the positions decide, popovers and the active window
    first."""
    top = vf.get_window_at(x, y)
    surfaces = _on_main(_our_surfaces) or []
    if top:
        # Under a window manager the window under the pointer is usually
        # the frame the window manager put around our window, not our
        # window itself.
        matches = [(n, xid) for n, xid in surfaces
                   if xid == top or _frame_of(xid) == top]
        if not matches:
            popovers = [(n, xid) for n, xid in surfaces if isinstance(n, Gtk.Popover)]
            if _frame_of(surfaces[0][1]) is not None if surfaces else False:
                # We can tell frames apart: a window that is not ours is on
                # top here. Only our popovers (no frame) may still be hit.
                matches = popovers
            else:
                # No way to tell (python-xlib missing): another program
                # owns the top window only if it says so.
                owner = vf.get_pid_for_window(top)
                matches = popovers if owner and owner != os.getpid() else surfaces
    else:
        matches = surfaces
    for native, xid in matches:
        geo = _geometry(xid)
        if not geo:
            continue
        gx, gy, gw, gh = geo
        if gx <= x < gx + gw and gy <= y < gy + gh:
            text = _on_main(_pick, native, x - gx, y - gy)
            return vf.trim_text(text or "")
    return None


_tracked = set()


def _on_focus_widget(win, _pspec):
    """Keyboard focus moved inside a VoxFox window (Tab, arrow keys in a
    menu or list, or a click): say the new control while hover reading is
    on. AT-SPI focus events from our own windows are ignored on purpose
    (see voxfox_core.a11y.event_from_self), so this takes their place."""
    if not vf.hover_running():
        return
    w = win.get_focus()
    if w is None:
        return
    text = vf.trim_text(widget_text(w) or "")
    if text:
        # speak() may wait for earlier speech to stop: not on this thread.
        threading.Thread(target=vf.speak_if_new, args=(text,), daemon=True).start()


def _track(win):
    if id(win) in _tracked:
        return
    _tracked.add(id(win))
    win.connect("notify::focus-widget", _on_focus_widget)
    win.connect("destroy", lambda w: _tracked.discard(id(w)))


def _track_all(*_a):
    model = Gtk.Window.get_toplevels()
    for i in range(model.get_n_items()):
        _track(model.get_item(i))


def install():
    """Let hover reading use this for VoxFox's own windows."""
    if GdkX11 is not None:
        vf.set_own_window_reader(text_at)
    # Keyboard focus works on every backend, Wayland included.
    try:
        Gtk.Window.get_toplevels().connect("items-changed", _track_all)
        _track_all()
    except Exception as e:
        log.debug(f"selfread focus tracking: {e}")

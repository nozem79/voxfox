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

"""voxfox_ui.touchbutton — the floating touch button (6.3).

A small round window with one button. Tap it once, twice or three times,
or hold it, and VoxFox runs the action chosen for that in Settings.
Drag it to move it; VoxFox remembers where it is. It lights up once for
each tap it understood, and pulses softly while VoxFox reads aloud.

Staying on top, the position and not taking the keyboard focus all need
an X server, like the main window's stay-on-top: a real X11 session, or
Wayland with VoxFox running through XWayland (voxfox_gtk.py restarts it
that way when the button is on). On plain Wayland it is an ordinary
small window.

Counting taps: GTK reports each press with how many came before it in
quick succession. After a release VoxFox waits TAP_WAIT_MS for another
tap before acting, so a single tap acts a moment later than a normal
button would. A hold or a drag cancels the taps.
"""

import math
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402
from voxfox_ui.widgets import set_accessible_label  # noqa: E402

log = vf.log

# The window manager finds the window by this exact title (wmctrl -F).
# Not translated, so it never changes under the user's language.
TITLE = "VoxFox Touch"

TOUCH_CSS = b"""
window.voxfox-touch-window, window.voxfox-touch-window.background {
  background: none;
  box-shadow: none;
}
/* Fading back to orange takes a moment; lighting up is quick (below). */
.voxfox-touch {
  background-color: #F26A1F;
  color: #ffffff;
  border: 2px solid #D9590F;
  border-radius: 9999px;
  transition: background-color 420ms ease-out;
}
.voxfox-touch.voxfox-touch-pressed {
  background-color: #D9590F;
  transition: background-color 60ms ease-in;
}
/* A gesture was recognised: light up, once per tap. */
.voxfox-touch.voxfox-touch-flash {
  background-color: #FFC896;
  transition: background-color 70ms ease-in;
}
/* VoxFox is reading aloud: a slow, soft pulse. Paused: lighter, still. */
@keyframes voxfox-touch-pulse {
  from { background-color: #F26A1F; }
  to   { background-color: #F9A066; }
}
.voxfox-touch.voxfox-touch-speaking {
  animation: voxfox-touch-pulse 900ms ease-in-out infinite alternate;
}
.voxfox-touch.voxfox-touch-paused {
  background-color: #F9A066;
}
"""

# The main-window method behind each action id (see voxfox_core.touchbutton).
ACTION_METHODS = {
    "ocr": "do_ocr_select",
    "read": "do_read",
    "pause": "do_pause",
    "stop": "do_stop",
    "page": "do_read_page",
    "whisper": "do_whisper",
    "translate": "do_translate",
    "ocr_translate": "do_ocr_select_translate",
    "voice": "do_toggle_slot",
    "type": "do_type_speak",
    "live": "do_live_toggle",
}


def action_labels():
    """The action ids with their names for the settings lists, in order."""
    names = {
        "none": _("Nothing"),
        "ocr": _("Choose a screen area and read it"),
        "read": _("Read the selected text"),
        "pause": _("Pause / resume"),
        "stop": _("Stop"),
        "stop_clear": _("Stop and clear the selection"),
        "page": _("Read web page"),
        "whisper": _("Dictate"),
        "translate": _("Translate & read"),
        "ocr_translate": _("OCR select & translate"),
        "voice": _("Switch language"),
        "type": _("Type and speak"),
        "live": _("Live transcription"),
        "window": _("Show or hide the VoxFox window"),
        "off": _("Switch off the touch button"),
    }
    return [(a, names[a]) for a in vf.ACTIONS]


def gesture_labels():
    return {"tap1": _("Tap once"), "tap2": _("Tap twice"),
            "tap3": _("Tap three times"), "tap4": _("Tap four times"),
            "tap5": _("Tap five times"), "long": _("Press and hold")}


_css_done = False


def _install_css():
    global _css_done
    if _css_done:
        return
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(TOUCH_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _css_done = True
    except Exception as e:
        log.debug(f"touch button CSS failed: {e}")


def _wmctrl(*args):
    """Run wmctrl on our window in the background (it can take a moment)."""
    if not vf.is_x11_client() or not vf.have_command("wmctrl"):
        return

    def worker():
        try:
            subprocess.run(["wmctrl", "-F", "-r", TITLE, *args], timeout=5,
                           capture_output=True)
        except Exception as e:
            log.debug(f"touch button wmctrl {args}: {e}")
    threading.Thread(target=worker, daemon=True).start()


class _FullscreenWatch:
    """Tells whether the active window is full screen (a video, a game, a
    presentation), so the button can step aside. X11 only.

    Uses python-xlib when it is there (one connection, two small property
    reads), else xprop. Runs on a background thread; nothing here touches
    GTK."""

    def __init__(self):
        self.d = None
        try:
            from Xlib import display as xdisplay
            self.d = xdisplay.Display()
            self.root = self.d.screen().root
            self.ACTIVE = self.d.intern_atom("_NET_ACTIVE_WINDOW")
            self.STATE = self.d.intern_atom("_NET_WM_STATE")
            self.FULL = self.d.intern_atom("_NET_WM_STATE_FULLSCREEN")
        except Exception as e:
            log.debug(f"touch button: no python-xlib display ({e}); "
                      f"using xprop")
            self.d = None
        self.xprop = vf.have_command("xprop")

    def usable(self):
        return self.d is not None or self.xprop

    def fullscreen_rect(self):
        """(x, y, w, h) of the active window when it is full screen, a
        rectangle covering everything when that is not known, or None."""
        if self.d is not None:
            try:
                from Xlib import X
                p = self.root.get_full_property(self.ACTIVE, X.AnyPropertyType)
                wid = p.value[0] if p and len(p.value) else 0
                if not wid:
                    return None
                w = self.d.create_resource_object("window", wid)
                st = w.get_full_property(self.STATE, X.AnyPropertyType)
                if not st or self.FULL not in st.value:
                    return None
                g = w.get_geometry()
                t = w.translate_coords(self.root, 0, 0)
                return (-t.x, -t.y, g.width, g.height)
            except Exception:
                # The window closed between the two reads; ask again later.
                return None
        if self.xprop:
            try:
                r = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                                   capture_output=True, text=True, timeout=2)
                wid = r.stdout.strip().split()[-1]
                if not wid.startswith("0x") or int(wid, 16) == 0:
                    return None
                r = subprocess.run(["xprop", "-id", wid, "_NET_WM_STATE"],
                                   capture_output=True, text=True, timeout=2)
                if "_NET_WM_STATE_FULLSCREEN" in r.stdout:
                    return (-10 ** 6, -10 ** 6, 10 ** 7, 10 ** 7)
            except Exception:
                pass
        return None

    def close(self):
        if self.d is not None:
            try:
                self.d.close()
            except Exception:
                pass
            self.d = None


def _read_pos():
    """(x, y) of the button window from the window manager, or None."""
    if not vf.is_x11_client() or not vf.have_command("wmctrl"):
        return None
    try:
        r = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True,
                           timeout=5)
        for line in r.stdout.splitlines():
            parts = line.split(None, 7)
            if len(parts) >= 8 and parts[7].strip() == TITLE:
                return int(parts[2]), int(parts[3])
    except Exception as e:
        log.debug(f"touch button position: {e}")
    return None


class TouchButton(Gtk.Window):
    """The floating button. `win` is the main window: it owns the state
    and the actions."""

    def __init__(self, win):
        super().__init__(title=TITLE, decorated=False, resizable=False)
        _install_css()
        self.win = win
        self.cfg = vf.normalize_touch_button(win.state.get("touch_button"))
        size = self.cfg["size"]
        self.add_css_class("voxfox-touch-window")

        face = Gtk.Box(accessible_role=Gtk.AccessibleRole.BUTTON)
        face.add_css_class("voxfox-touch")
        face.set_size_request(size, size)
        icon = Gtk.Image.new_from_icon_name("voxfox-read-symbolic")
        icon.set_pixel_size(max(16, size // 2))
        icon.set_hexpand(True)
        icon.set_vexpand(True)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        face.append(icon)
        self.face = face
        self.set_child(face)
        self._describe()

        self._taps = 0
        self._counted = 0      # taps of this series already acted on
        self._timer = 0
        self._held = False
        self._moving = False

        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._on_pressed)
        click.connect("released", self._on_released)
        click.connect("stopped", lambda *_a: self._unpress())
        face.add_controller(click)

        hold = Gtk.GestureLongPress()
        hold.connect("pressed", self._on_hold)
        hold.connect("cancelled", lambda *_a: self._unpress())
        face.add_controller(hold)

        drag = Gtk.GestureDrag()
        drag.set_button(Gdk.BUTTON_PRIMARY)
        drag.connect("drag-update", self._on_drag_update)
        face.add_controller(drag)
        self._gestures = (click, hold, drag)

        # Keyboard: Enter or Space runs the single-tap action, so the
        # button is usable without a pointer too.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        # GTK writes WM_HINTS again each time the window is shown (also
        # after it stepped aside for a full-screen video), with "accepts
        # focus" on. So set ours after every map, not only the first.
        self.connect("map", lambda *_a: GLib.timeout_add(50, self._no_focus))
        self._closed = False
        self._fs_hidden = False
        self._cur_pos = None
        self.connect("destroy", lambda *_a: setattr(self, "_closed", True))
        GLib.timeout_add(300, self._watch_speech)
        if vf.is_x11_client():
            threading.Thread(target=self._watch_fullscreen,
                             daemon=True).start()

    # ── showing and placing ──
    def show_button(self):
        self.present()
        for delay in (150, 700, 1600):
            GLib.timeout_add(delay, lambda: (self._place(), False)[1])

    def _place(self):
        pos = self.cfg.get("pos")
        if not pos or not self.win._pos_on_screen(pos[0], pos[1]):
            pos = self._default_pos()
        self._cur_pos = list(pos) if pos else None
        # wmctrl changes at most two of these per call.
        _wmctrl("-b", "add,above")
        _wmctrl("-b", "add,skip_taskbar,skip_pager")
        if pos:
            _wmctrl("-e", f"0,{pos[0]},{pos[1]},-1,-1")

    def keep_above(self):
        _wmctrl("-b", "add,above")

    def _default_pos(self):
        try:
            monitors = Gdk.Display.get_default().get_monitors()
            g = monitors.get_item(0).get_geometry()
            return vf.default_position(g.x, g.y, g.width, g.height,
                                       self.cfg["size"])
        except Exception:
            return None

    def _no_focus(self):
        """Ask the window manager not to give this window the keyboard
        focus when it is tapped, so the focus (and the selection) stays in
        the program the user is reading from. X11 only, best-effort."""
        if not vf.is_x11_client():
            return False
        try:
            gi.require_version("GdkX11", "4.0")
            from gi.repository import GdkX11
            xid = GdkX11.X11Surface.get_xid(self.get_surface())
            from Xlib import display as xdisplay, Xutil
            d = xdisplay.Display()
            w = d.create_resource_object("window", xid)
            hints = w.get_wm_hints() or {}
            flags = getattr(hints, "flags", 0) | Xutil.InputHint
            w.set_wm_hints(flags=flags, input=0)
            # GTK also lists WM_TAKE_FOCUS, which turns "no input" into
            # "the program decides" -- and GTK then takes the focus. Drop
            # it, so the window manager leaves the focus where it was.
            take = d.intern_atom("WM_TAKE_FOCUS")
            protocols = d.intern_atom("WM_PROTOCOLS")
            prop = w.get_full_property(protocols, 0)
            if prop is not None:
                keep = [a for a in prop.value if a != take]
                w.change_property(protocols, d.intern_atom("ATOM"), 32, keep)
            d.sync()
            d.close()
        except Exception as e:
            log.debug(f"touch button: focus hint not set: {e}")
        return False

    def _describe(self):
        acts = dict(action_labels())
        g = gesture_labels()
        lines = [f"{g[k]}: {acts.get(self.cfg['actions'][k], '')}"
                 for k in vf.GESTURES if self.cfg["actions"][k] != "none"]
        set_accessible_label(self.face, _("VoxFox touch button"))
        # No tooltip (it got in the way on a touchscreen); a screen reader
        # still reads what each gesture does.
        try:
            self.face.update_property([Gtk.AccessibleProperty.DESCRIPTION],
                                      ["; ".join(lines)])
        except Exception as e:
            log.debug(f"touch button description: {e}")

    # ── gestures ──
    def _cancel_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _unpress(self):
        self.face.remove_css_class("voxfox-touch-pressed")

    def _on_pressed(self, _g, n_press, _x, _y):
        self._cancel_timer()
        if n_press == 1:
            self._held = False
            self._moving = False
            self._counted = 0
        self.face.add_css_class("voxfox-touch-pressed")

    def _on_released(self, _g, n_press, _x, _y):
        self._unpress()
        if self._held or self._moving:
            return
        # GTK keeps counting presses for its double-click time (400 ms);
        # we act after TAP_WAIT_MS. A slow second tap therefore arrives as
        # press 2 of a series we already acted on: count only the new ones,
        # so it is a fresh single tap and not "one tap, then two".
        self._taps = n_press - self._counted
        self._cancel_timer()
        self._timer = GLib.timeout_add(vf.TAP_WAIT_MS, self._taps_done)

    def _taps_done(self):
        self._timer = 0
        if self._closed or self._taps < 1:
            return False
        self._counted += self._taps
        self._fire(vf.gesture_for_taps(self._taps))
        return False

    def _on_hold(self, _g, _x, _y):
        if self._moving:
            return
        self._held = True
        self._cancel_timer()
        self._unpress()
        self._fire("long")

    def _on_drag_update(self, drag, dx, dy):
        if self._moving or self._held:
            return
        if math.hypot(dx, dy) < vf.DRAG_THRESHOLD:
            return
        self._moving = True
        self._cancel_timer()
        self._unpress()
        ok, sx, sy = drag.get_start_point()
        surface = self.get_surface()
        if not ok or surface is None:
            return
        try:
            # The face fills the window, so its point is the window's
            # point; translate anyway in case a theme adds a margin.
            # (PyGObject returns (x, y) or (ok, x, y) depending on version.)
            res = self.face.translate_coordinates(self, sx, sy)
            nx, ny = (res[-2], res[-1]) if res else (sx, sy)
            tx, ty = self.get_surface_transform()
            surface.begin_move(drag.get_device(), drag.get_current_button(),
                               nx + tx, ny + ty,
                               drag.get_current_event_time())
        except Exception as e:
            log.debug(f"touch button move failed: {e}")
        for g in self._gestures:
            g.reset()
        self._watch_move()

    def _on_key(self, _ctl, keyval, _code, _state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self._fire("tap1")
            return True
        return False

    # ── remembering where it was put ──
    def _watch_move(self):
        """The window manager moves the window after begin_move; we are not
        told when it is done. Look every half second and save the place
        once it has stopped changing (or after 15 s)."""
        last = {"pos": None, "n": 0}

        def poll():
            last["n"] += 1
            pos = _read_pos()
            if pos and pos == last["pos"]:
                GLib.idle_add(self._save_pos, pos)
                return
            last["pos"] = pos
            if last["n"] < 30:
                threading.Timer(0.5, poll).start()
        threading.Timer(0.6, poll).start()

    def _save_pos(self, pos):
        if not self.win._pos_on_screen(pos[0], pos[1]):
            return False
        self.cfg["pos"] = [pos[0], pos[1]]
        self._cur_pos = [pos[0], pos[1]]
        tb = self.win.state.setdefault("touch_button", {})
        tb["pos"] = [pos[0], pos[1]]
        vf.save_state(self.win.state)
        return False

    # ── doing it ──
    def _fire(self, gesture):
        action = vf.action_for(self.win.state.get("touch_button"), gesture)
        log.debug(f"touch button: {gesture} -> {action}")
        if action == "none":
            return
        taps = int(gesture[3:]) if gesture.startswith("tap") else 1
        self._flash(taps, long=(gesture == "long"))
        if action == "off":
            # Let the flashes finish before the button goes away; never
            # destroy this window from inside its own gesture handler.
            GLib.timeout_add(taps * 280 + 150, lambda: (
                self.win.run_touch_action("off"), False)[1])
            return
        self.win.run_touch_action(action)

    def _flash(self, times, long=False):
        """Light the button up `times` times, so you can see which gesture
        it understood: once for one tap, twice for two, and so on. Holding
        gives one longer flash."""
        on_ms = 260 if long else 110
        off_ms = 170

        def step(n):
            if self._closed:
                return
            self.face.add_css_class("voxfox-touch-flash")

            def off():
                if self._closed:
                    return False
                self.face.remove_css_class("voxfox-touch-flash")
                if n > 1:
                    GLib.timeout_add(off_ms, lambda: (step(n - 1), False)[1])
                return False
            GLib.timeout_add(on_ms, off)
        step(times)

    # ── stepping aside for full-screen windows ──
    def _watch_fullscreen(self):
        """Hide the button while the active window is full screen on the
        button's monitor (a video, say), and bring it back afterwards.
        Looked at a little more than once a second."""
        import time
        watch = _FullscreenWatch()
        if not watch.usable():
            log.debug("touch button: cannot see full-screen windows "
                      "(no python-xlib or xprop)")
            return
        try:
            while not self._closed:
                rect = watch.fullscreen_rect()
                # Set on the GTK thread by _place / _save_pos.
                pos = self._cur_pos
                if pos is None:
                    time.sleep(0.8)
                    continue
                half = self.cfg["size"] // 2
                hide = bool(rect) and vf.point_in_rect(
                    pos[0] + half, pos[1] + half, *rect)
                if hide != self._fs_hidden:
                    GLib.idle_add(self._set_fs_hidden, hide)
                time.sleep(0.8)
        finally:
            watch.close()

    def _set_fs_hidden(self, hide):
        if self._closed or hide == self._fs_hidden:
            return False
        self._fs_hidden = hide
        log.debug("touch button: " + ("hidden, a window is full screen"
                                      if hide else "back"))
        if hide:
            self.set_visible(False)
        else:
            self.set_visible(True)
            for delay in (100, 600):
                GLib.timeout_add(delay, lambda: (self._place(), False)[1])
        return False

    # ── showing that VoxFox is reading ──
    def _watch_speech(self):
        """Pulse while VoxFox reads aloud, stay light while paused. Looked
        at a few times a second; checking costs next to nothing."""
        if self._closed:
            return False
        speaking = vf.is_speaking()
        paused = speaking and vf.is_paused()
        for cls, on in (("voxfox-touch-speaking", speaking and not paused),
                        ("voxfox-touch-paused", paused)):
            if on and not self.face.has_css_class(cls):
                self.face.add_css_class(cls)
            elif not on and self.face.has_css_class(cls):
                self.face.remove_css_class(cls)
        return True


__all__ = ["TouchButton", "TITLE", "ACTION_METHODS", "action_labels",
           "gesture_labels"]

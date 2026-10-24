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

"""voxfox_core.pointer — Where the mouse is and which window is under it
(python-xlib when available, xdotool otherwise).
"""

import subprocess, os


# Optional: python-xlib avoids spawning a subprocess for the pointer-position
# query that hover mode makes every HOVER_POLL seconds -- by far the hottest
# of the xdotool calls in this file. Recommended, not required: everything
# here falls back to the xdotool subprocess this always used, so a system
# without python3-xlib installed behaves exactly as before.
try:
    from Xlib import display as _xlib_display
    from Xlib.error import DisplayConnectionError as _XlibDisplayError
    _HAVE_XLIB = True
except Exception:
    _HAVE_XLIB = False

class _XlibState:
    """The python-xlib connection used for the pointer position.

    conn         lazily connected; a plain X11 socket, reused across calls
    unavailable  set once there is definitively no X server to try
                 (DISPLAY unset) -- distinct from a connection that merely
                 broke, which is worth retrying since the server could
                 come back
    """

    def __init__(self):
        self.conn = None
        self.unavailable = False


_xlib = _XlibState()

# _xlib.conn/_xlib.unavailable have no lock, and a
# python-xlib connection is not safe to share across threads. Only
# hover_loop's single background thread calls get_mouse_pos() today; if a
# second caller is ever added, it needs its own connection, not this one.


def get_xlib_display():
    """The cached Xlib connection, (re)connecting if it isn't open yet.
    None when python-xlib isn't installed, or there's definitively no X
    server to reach (DISPLAY unset -- a pure Wayland session with no
    XWayland), or the connection attempt itself failed for some other,
    possibly transient reason. Callers fall back to xdotool in every case."""
    if not _HAVE_XLIB or _xlib.unavailable:
        return None
    if _xlib.conn is None:
        try:
            _xlib.conn = _xlib_display.Display()
        except Exception:
            return None
    return _xlib.conn


def _get_mouse_pos_xlib():
    """Pointer position via a live Xlib connection: one small round-trip
    over an already-open socket, versus xdotool's fork+exec+argv-parse for
    the same QueryPointer request. Raises on any failure so the caller can
    fall back; also drops the cached connection on a connection-level
    error, so a later call reconnects instead of repeating a dead one --
    unless there is clearly no X server at all to reconnect to, which is
    remembered so we stop trying for the rest of this process."""
    if not os.environ.get("DISPLAY"):
        # Xlib.display.Display() with no argument reads $DISPLAY once, at
        # connect time; with it unset there is nothing to retry, ever, for
        # the life of this process. This is what actually happens on a
        # pure Wayland session with no XWayland.
        _xlib.unavailable = True
        raise RuntimeError("no DISPLAY set")
    d = get_xlib_display()
    if d is None:
        raise RuntimeError("no Xlib connection available")
    try:
        p = d.screen().root.query_pointer()
        return p.root_x, p.root_y
    except _XlibDisplayError:
        _xlib.conn = None
        raise
    except Exception:
        # Anything else (a stale connection after the X server restarted,
        # for instance) -- drop it too, so the next call tries fresh.
        _xlib.conn = None
        raise


def _get_mouse_pos_xdotool():
    """The original implementation, kept as-is as the fallback path."""
    try:
        r = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                           capture_output=True, text=True, timeout=1.0)
        pos = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                pos[k] = v.strip()
        x, y = int(pos.get("X", 0)), int(pos.get("Y", 0))
        if (x, y) != (0, 0):
            return x, y
    except Exception:
        pass
    # Wayland fallback: AT-SPI sometimes reports pointer position via the
    # event controller, but there's no portable subprocess for it. Returning
    # (0,0) means hover-mode is effectively disabled, which the GUI surfaces.
    return (0, 0)


# ── Mouse + window helpers ────────────────────────────────────────────────────
def get_mouse_pos():
    # xdotool (or, when available, the faster Xlib path below) works on X11
    # and on XWayland; on pure Wayland it returns 0,0.
    try:
        return _get_mouse_pos_xlib()
    except Exception:
        pass
    return _get_mouse_pos_xdotool()


def get_active_pid():
    try:
        r = subprocess.run(["xdotool", "getactivewindow", "getwindowpid"],
                           capture_output=True, text=True, timeout=1.0)
        if r.returncode == 0:
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


def get_window_at(x, y):
    """Return the X11 window ID at (x, y) using xdotool."""
    try:
        r = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=1.0)
        for line in r.stdout.splitlines():
            if line.startswith("WINDOW="):
                val = line.split("=", 1)[1].strip()
                return int(val) if val and val != "0" else None
    except Exception:
        pass
    return None


def get_pid_for_window(win_id):
    """Return the PID owning a given X11 window ID."""
    try:
        r = subprocess.run(
            ["xdotool", "getwindowpid", str(win_id)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=1.0)
        if r.returncode == 0:
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


# VoxFox's own windows are read without AT-SPI (see voxfox_ui.selfread):
# GTK 4 reports positions relative to its windows, so hit-testing VoxFox
# by screen position through AT-SPI found nothing. The front-end registers
# a reader that returns None when (x, y) is not on a VoxFox window.


__all__ = [
    "get_mouse_pos",
    "get_active_pid",
    "get_window_at",
    "get_pid_for_window",
    "get_xlib_display",
]

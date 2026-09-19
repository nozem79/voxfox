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

"""
VoxFox — GTK4 front-end entry point.

All UI code lives in the voxfox_ui package (split from this file in 4.0).
All TTS / STT / OCR / IPC / CLI logic lives in voxfox_core.

Run the GUI:        voxfox
Set up components:  voxfox --setup     (downloads Piper + voices + Whisper)
Forward a command:  voxfox --read      (and --stop, --pause, --ocr-select, ...)
"""
import json
import os
import shutil
import sys

# When run as a script (python3 /usr/lib/voxfox/voxfox_gtk.py), make sure the
# directory holding voxfox_ui/ and voxfox_core/ is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# GTK4 defaults to an OpenGL renderer that draws via GLX and the X Present
# extension. On NVIDIA's proprietary driver that combination has a known bug:
# a BadDrawable X error partway through startup that GDK treats as fatal and
# exits on, even with a custom X error handler installed (something in the
# GL/GLX context setup appears to save and later restore the handler that was
# active before ours, undoing it). Confirmed on an RTX 3090.
#
# VoxFox's own UI is a plain toolbar of buttons and text -- nothing that
# benefits from GPU-accelerated drawing -- so there is no downside to using
# GTK4's software (cairo) renderer everywhere. setdefault, not direct
# assignment: a user or packager who has their own GSK_RENDERER preference
# keeps it. Must happen before GTK is imported.
os.environ.setdefault("GSK_RENDERER", "cairo")


def _stay_on_top_wanted():
    """Read the always_on_top setting straight from the state file.

    Deliberately not via voxfox_core: this runs before anything else
    is imported, and importing the package here would set up logging
    and translations in a process we are about to replace."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    try:
        with open(os.path.join(base, "voxfox", "state.json"),
                  encoding="utf-8") as fh:
            return bool(json.load(fh).get("always_on_top", True))
    except Exception:
        return True


def _restart_on_xwayland():
    """Restart ourselves as an X11 client so the window can stay above
    other windows.

    Wayland has no always-on-top protocol, but an XWayland client is
    stacked by that same compositor and does honour _NET_WM_STATE_ABOVE,
    which is what wmctrl sets. Confirmed working on both KDE Plasma and
    GNOME under Wayland.

    It has to be a restart. Setting GDK_BACKEND from inside main() is
    already too late -- GDK has read it by then, and the window comes up
    as a Wayland surface regardless of what the variable says. The same
    variable passed in from outside works fine, so we hand ourselves a
    corrected environment and start over.

    This is the earliest possible point on purpose: no lock file taken,
    no socket bound, no GTK imported, so replacing the process costs
    nothing and cannot leave a second instance behind."""
    if os.environ.get("VOXFOX_BACKEND_SWITCHED"):
        return  # we are the restarted process
    if os.environ.get("GDK_BACKEND"):
        return  # the user chose a backend; leave it alone
    wayland = (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
               or bool(os.environ.get("WAYLAND_DISPLAY")))
    if not wayland:
        return  # a real X11 session already does what we need
    if not os.environ.get("DISPLAY"):
        # A Wayland session can run without XWayland. Forcing the X11
        # backend there leaves GTK unable to open any display at all,
        # so VoxFox would not start rather than merely not float.
        return
    if not shutil.which("wmctrl"):
        return  # nothing to raise the window with afterwards
    # Command-line actions forward to the running instance and exit.
    # They have no window, so there is nothing to keep on top.
    if [a for a in sys.argv[1:] if a not in ("-v", "--verbose")]:
        return
    if not _stay_on_top_wanted():
        return
    env = dict(os.environ)
    env["GDK_BACKEND"] = "x11"
    env["VOXFOX_BACKEND_SWITCHED"] = "1"
    try:
        os.execve(sys.executable,
                  [sys.executable, os.path.abspath(__file__)]
                  + sys.argv[1:], env)
    except Exception:
        # Better a window that does not float than one that never opens.
        pass


_restart_on_xwayland()

from voxfox_ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()

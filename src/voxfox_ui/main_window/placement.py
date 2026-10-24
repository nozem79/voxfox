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

"""voxfox_ui.main_window.placement

Where the window is: remembering and restoring its position, and staying
on top.
"""

import threading
import subprocess

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402

log = vf.log


class PlacementMixin:
    """Where the window is: remembering and restoring its position, and
    staying on top.
    """

    def _pos_on_screen(self, x, y):
        """True when (x, y) lands on one of the monitors we can see.

        A saved position can outlive the screen it was saved on: a
        second monitor unplugged, a laptop moved off its dock, or a
        position first recorded while restoring it was still a no-op.
        Putting the window back there leaves it somewhere the user
        cannot reach, and since this window is meant to float above
        everything, it just looks like VoxFox never started.

        Returns True when we cannot work it out, so an unexpected
        display setup never costs the user their saved position."""
        try:
            monitors = Gdk.Display.get_default().get_monitors()
            for i in range(monitors.get_n_items()):
                g = monitors.get_item(i).get_geometry()
                if g.x <= x < g.x + g.width and \
                        g.y <= y < g.y + g.height:
                    return True
        except Exception as e:
            log.debug(f"could not read monitor layout: {e}")
            return True
        return False

    def get_window_pos(self):
        """Return (x, y) of our window via wmctrl, or None. GTK4 has no
        portable get_position(), so we read it from the window manager.
        Matches our window by its exact title (APP_NAME). Needs an X
        server, so under Wayland only with the X11 backend."""
        if not vf.is_x11_client() or not vf.have_command("wmctrl"):
            return None
        try:
            r = subprocess.run(["wmctrl", "-lG"],
                               capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                parts = line.split(None, 7)
                if len(parts) >= 8 and parts[7].strip() == vf.APP_NAME:
                    return (int(parts[2]), int(parts[3]))
        except Exception as e:
            log.debug(f"could not read window position: {e}")
        return None

    def save_window_pos(self):
        """Remember the current window position so the next start reopens here."""
        try:
            pos = self.get_window_pos()
            if pos and self._pos_on_screen(pos[0], pos[1]):
                self.state["win_pos"] = [pos[0], pos[1]]
                vf.save_state(self.state)
        except Exception as e:
            log.debug(f"could not save window position: {e}")

    def restore_window_pos(self):
        """Move the window back to its saved position (best-effort). Size
        is left unchanged (-1,-1). Needs an X server, so under Wayland
        only with the X11 backend."""
        pos = (self.state or {}).get("win_pos")
        if not pos or not vf.is_x11_client() or not vf.have_command("wmctrl"):
            return
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError, IndexError):
            return
        if not self._pos_on_screen(x, y):
            # Forget it rather than keep failing on every start.
            log.info(f"Saved window position {x},{y} is not on any "
                     f"current monitor -- opening where the window "
                     f"manager puts us instead")
            self.state["win_pos"] = None
            vf.save_state(self.state)
            return

        def worker():
            try:
                subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                "-e", f"0,{x},{y},-1,-1"], timeout=5)
            except Exception as e:
                log.debug(f"restore window position failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def set_always_on_top(self):
        """Keep the window above others, like the old Tk build's -topmost.
        GTK4 dropped a native always-on-top API, so this is best-effort
        via wmctrl, which needs an X server: either a real X11 session, or
        a Wayland session started with the X11 backend (see _restart_on_xwayland
        in voxfox_gtk.py).
        A plain Wayland window cannot be raised by anyone but the user."""
        if not self.state.get("always_on_top", True):
            return
        if not vf.is_x11_client() or not vf.have_command("wmctrl"):
            return

        def worker():
            try:
                subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                "-b", "add,above"], timeout=5)
            except Exception as e:
                log.debug(f"always-on-top failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

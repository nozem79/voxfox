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

"""voxfox_ui.screenshot — Region capture for OCR (maim/scrot/gnome-screenshot/spectacle/flameshot).

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os
import time
import subprocess

import gi
gi.require_version("Gtk", "4.0")

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log


def _grab_region_to_file(dest_png):
    """Capture a user-drawn rectangle into dest_png using the desktop's native
    region-screenshot tool — which is what makes this work on X11 and Wayland.
    Returns (ok, error_message).

    Tool order is deliberate: maim/scrot first. gnome-screenshot fails
    *silently* on non-GNOME desktops (notably Cinnamon: no GNOME Shell DBus,
    broken X11 fallback), producing no file and no error, so it must not be
    preferred where maim/scrot are present.

    maim/scrot grab the pointer to draw the rectangle. When OCR-select is
    triggered from a Super-key shortcut, the window manager still holds the
    keybinding's pointer grab for a moment, so the first attempt can fail with
    'couldn't grab pointer'. That clears once the keys are released, so we
    retry briefly. A non-zero exit *without* a grab error means the user
    cancelled (Escape), which we report as such rather than retrying."""
    grabbers = [
        ("maim",  ["-s", dest_png]),
        ("scrot", ["-s", dest_png]),
    ]
    fallbacks = [
        ("gnome-screenshot", ["-a", "-f", dest_png]),
        ("spectacle",        ["-rbno", dest_png]),
        ("flameshot",        ["gui", "-r", "-p", dest_png]),
    ]

    def _run_grabber(binary, args, attempts=10, delay=0.12):
        """Run a pointer-grabbing tool, retrying only on grab contention."""
        last_err = ""
        for i in range(attempts):
            # Newer scrot refuses to overwrite an existing file, and mkstemp()
            # has already created an empty one. Remove it before every attempt
            # so the tool writes a fresh capture.
            try:
                if os.path.exists(dest_png):
                    os.unlink(dest_png)
            except OSError:
                pass
            try:
                r = subprocess.run([binary, *args], timeout=120,
                                   capture_output=True, text=True)
            except Exception as e:
                return False, str(e)
            if r.returncode == 0 and os.path.exists(dest_png) \
                    and os.path.getsize(dest_png) > 0:
                return True, ""
            stderr = (r.stderr or "").strip()
            last_err = stderr
            if "grab" in stderr.lower():
                # WM still holds the hotkey grab; wait for it to clear, retry.
                log.debug(f"{binary} grab busy (attempt {i+1}/{attempts}): {stderr}")
                time.sleep(delay)
                continue
            # Non-zero without a grab error → user cancelled the selection.
            return False, _("Selection cancelled")
        return False, last_err or _("Could not grab the screen for selection")

    for binary, args in grabbers:
        if not vf._have(binary):
            continue
        ok, err = _run_grabber(binary, args)
        if ok:
            return True, ""
        # Grab contention that never cleared, or a cancel — report it; don't
        # silently fall through to gnome-screenshot (which would fail quietly).
        return False, err

    for binary, args in fallbacks:
        if not vf._have(binary):
            continue
        try:
            if os.path.exists(dest_png):
                os.unlink(dest_png)
        except OSError:
            pass
        try:
            subprocess.run([binary, *args], check=True, timeout=120)
            if os.path.exists(dest_png) and os.path.getsize(dest_png) > 0:
                return True, ""
            # gnome-screenshot on Cinnamon: exit 0 but no file. Keep trying.
            log.debug(f"{binary} produced no file; trying next tool")
        except subprocess.CalledProcessError:
            return False, _("Selection cancelled")
        except Exception as e:
            return False, str(e)

    if vf._have("grim") and vf._have("slurp"):
        try:
            geom = subprocess.run(["slurp"], capture_output=True, text=True,
                                  timeout=120)
            if geom.returncode != 0 or not geom.stdout.strip():
                return False, _("Selection cancelled")
            subprocess.run(["grim", "-g", geom.stdout.strip(), dest_png],
                           check=True, timeout=120)
            if os.path.exists(dest_png) and os.path.getsize(dest_png) > 0:
                return True, ""
        except Exception as e:
            return False, str(e)
    return False, _("No screenshot tool found "
                    "(install gnome-screenshot, spectacle, scrot, or grim+slurp)")



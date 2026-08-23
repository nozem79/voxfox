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
import re
import time
import shutil
import secrets
import subprocess
from urllib.parse import urlparse, unquote

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

import gi
gi.require_version("Gtk", "4.0")

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log


def _grab_via_xdg_portal(dest_png):
    """Ask the xdg-desktop-portal Screenshot interface for an interactive,
    user-selected area capture. This is the sanctioned, cross-desktop
    replacement for calling GNOME Shell's own Screenshot D-Bus interface
    directly (see below): that direct call is refused outright
    ("AccessDenied: SelectArea is not allowed") because it bypasses the
    portal's consent model entirely, confirmed against a real GNOME
    26.04/Wayland session. The portal is the way apps are meant to ask for
    this, and "interactive" mode shows the same kind of selection overlay
    as the built-in Screenshot tool -- since the user has to draw the
    rectangle either way, this doesn't add a separate consent step beyond
    what OCR-select already requires.

    Portal calls are inherently asynchronous: this method returns a
    Request object path, and the actual result arrives later as a
    Request::Response signal on that path -- there's no single
    call-and-get-a-reply method the way the other tools here have. A
    temporary GLib.MainLoop bridges that async signal back into this
    (already background-threaded) synchronous function, with a timeout as
    a safety net in case the signal never arrives.
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        options = {
            "handle_token": GLib.Variant("s", f"voxfox{secrets.token_hex(8)}"),
            "modal": GLib.Variant("b", True),
            "interactive": GLib.Variant("b", True),
            "target": GLib.Variant("u", 4),  # Area (version 3+; ignored by older portals)
            # "interactive" must stay true: it's what enables the drag-to-
            # select UI here, not just an optional customization step on
            # top of it -- target=Area alone was not sufficient, and
            # removing this produced a full-screen capture with no way to
            # pick a region. The one downside is an extra confirm button
            # after drawing the rectangle; that's preferable to losing
            # area selection entirely.
        }
        call_result = bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            "Screenshot",
            GLib.Variant("(sa{sv})", ("", options)),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE, -1, None)
        handle_path = call_result.unpack()[0]
        log.debug(f"OCR-select: xdg-portal request handle {handle_path}")

        result = {}
        loop = GLib.MainLoop()

        def on_response(connection, sender, object_path, interface_name,
                        signal_name, parameters, *_a):
            result["response"], result["results"] = parameters.unpack()
            loop.quit()

        sub_id = bus.signal_subscribe(
            None, "org.freedesktop.portal.Request", "Response", handle_path,
            None, Gio.DBusSignalFlags.NONE, on_response)

        def on_timeout():
            loop.quit()
            return False
        timeout_id = GLib.timeout_add_seconds(120, on_timeout)

        loop.run()

        bus.signal_unsubscribe(sub_id)
        if "response" in result:
            # The timeout never fired, so its source is still pending and
            # needs explicit cleanup. If it *did* fire, returning False from
            # on_timeout already told GLib to drop it -- removing it again
            # here would log a harmless but noisy "source not found" warning.
            GLib.source_remove(timeout_id)

        if "response" not in result:
            log.debug("OCR-select: xdg-portal timed out waiting for a response")
            return False, _("Selection cancelled")
        if result["response"] != 0:
            log.debug(f"OCR-select: xdg-portal response code "
                     f"{result['response']} (cancelled or denied)")
            return False, _("Selection cancelled")

        uri = result["results"].get("uri")
        if not uri:
            log.debug(f"OCR-select: xdg-portal succeeded but returned no uri "
                     f"(results={result['results']!r})")
            return False, _("Selection cancelled")

        src_path = unquote(urlparse(uri).path)
        if not os.path.isfile(src_path):
            log.debug(f"OCR-select: xdg-portal uri doesn't resolve to a "
                     f"file: {uri!r} -> {src_path!r}")
            return False, _("Selection cancelled")

        shutil.copy2(src_path, dest_png)
        # The portal saves this as a real, permanent file (typically in the
        # user's Pictures/Screenshots folder) since that's the normal
        # "take a screenshot" behaviour it's built for -- clean it up now
        # that our own copy exists, so every OCR-select doesn't leave one
        # behind. Best-effort: a failed cleanup shouldn't fail the capture
        # that already succeeded.
        try:
            os.remove(src_path)
        except OSError as e:
            log.debug(f"OCR-select: could not remove portal's source file "
                     f"{src_path!r}: {e}")
        log.debug("OCR-select: xdg-desktop-portal succeeded")
        return True, ""
    except Exception as e:
        log.debug(f"OCR-select: xdg-portal raised: {e}")
        return False, str(e)


def _grab_region_to_file(dest_png):
    """Capture a user-drawn rectangle into dest_png using the desktop's native
    region-screenshot tool — which is what makes this work on X11 and Wayland.
    Returns (ok, error_message).

    Tool order is deliberate and differs by display server. On X11:
    maim/scrot first. gnome-screenshot fails *silently* on non-GNOME desktops
    (notably Cinnamon: no GNOME Shell DBus, broken X11 fallback), producing no
    file and no error, so it must not be preferred where maim/scrot are
    present. On Wayland, maim/scrot are skipped entirely (see below) and
    gnome-screenshot/spectacle/flameshot/grim+slurp are tried directly.

    maim/scrot grab the pointer to draw the rectangle. When OCR-select is
    triggered from a Super-key shortcut, the window manager still holds the
    keybinding's pointer grab for a moment, so the first attempt can fail with
    'couldn't grab pointer'. That clears once the keys are released, so we
    retry briefly. A non-zero exit *without* a grab error means the user
    cancelled (Escape), which we report as such rather than retrying."""
    if vf.IS_WAYLAND:
        # maim/scrot call into X11 directly and don't fail cleanly under
        # Wayland -- they can "succeed" with a blank/black capture (the
        # file exists, non-zero size) instead of erroring, which OCR then
        # reports as "no text found" with no hint that the capture itself
        # was the real problem. Skip them here so gnome-screenshot (uses
        # the compositor's own screenshot portal) actually gets a turn.
        grabbers = []
    else:
        grabbers = [
            ("maim",  ["-s", dest_png]),
            ("scrot", ["-s", dest_png]),
        ]
    fallbacks = [
        ("gnome-screenshot", ["-a", "-f", dest_png]),
        ("spectacle",        ["-rbno", dest_png]),
        ("flameshot",        ["gui", "-r", "-p", dest_png]),
    ]

    considered = [b for b, _a in grabbers + fallbacks] + ["grim", "slurp"]
    log.debug(f"OCR-select: Wayland={vf.IS_WAYLAND}, tools present: "
             f"{[b for b in considered if vf._have(b)]} (of {considered} "
             f"considered)")

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
        log.debug(f"OCR-select: trying grabber {binary}")
        ok, err = _run_grabber(binary, args)
        if ok:
            log.debug(f"OCR-select: {binary} succeeded")
            return True, ""
        log.debug(f"OCR-select: {binary} failed: {err}")
        # Grab contention that never cleared, or a cancel — report it; don't
        # silently fall through to gnome-screenshot (which would fail quietly).
        return False, err

    for binary, args in fallbacks:
        if not vf._have(binary):
            log.debug(f"OCR-select: {binary} not found, skipping")
            continue
        log.debug(f"OCR-select: trying fallback {binary}")
        try:
            if os.path.exists(dest_png):
                os.unlink(dest_png)
        except OSError:
            pass
        try:
            r = subprocess.run([binary, *args], check=True, timeout=120,
                               capture_output=True, text=True)
            if os.path.exists(dest_png) and os.path.getsize(dest_png) > 0:
                log.debug(f"OCR-select: {binary} succeeded")
                return True, ""
            # gnome-screenshot on Cinnamon: exit 0 but no file. Keep trying.
            log.debug(f"OCR-select: {binary} exited 0 but produced no file "
                     f"(stdout={r.stdout!r} stderr={r.stderr!r}); trying next tool")
        except subprocess.CalledProcessError as e:
            log.debug(f"OCR-select: {binary} failed (exit {e.returncode}): "
                     f"stdout={e.stdout!r} stderr={e.stderr!r}")
            return False, _("Selection cancelled")
        except Exception as e:
            log.debug(f"OCR-select: {binary} raised: {e}")
            return False, str(e)

    log.debug("OCR-select: trying xdg-desktop-portal Screenshot interface")
    ok, err = _grab_via_xdg_portal(dest_png)
    if ok:
        return True, ""
    log.debug(f"OCR-select: xdg-desktop-portal path failed: {err}")

    if vf._have("grim") and vf._have("slurp"):
        log.debug("OCR-select: trying grim+slurp")
        try:
            geom = subprocess.run(["slurp"], capture_output=True, text=True,
                                  timeout=120)
            if geom.returncode != 0 or not geom.stdout.strip():
                log.debug(f"OCR-select: slurp gave no geometry (exit "
                         f"{geom.returncode}): stderr={geom.stderr!r}")
                return False, _("Selection cancelled")
            r = subprocess.run(["grim", "-g", geom.stdout.strip(), dest_png],
                               capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and os.path.exists(dest_png) \
                    and os.path.getsize(dest_png) > 0:
                log.debug("OCR-select: grim+slurp succeeded")
                return True, ""
            log.debug(f"OCR-select: grim failed (exit {r.returncode}): "
                     f"stderr={r.stderr!r}")
        except Exception as e:
            log.debug(f"OCR-select: grim+slurp raised: {e}")
            return False, str(e)
    else:
        log.debug("OCR-select: grim+slurp not both present, skipping")
    log.debug("OCR-select: no working screenshot tool found")
    if vf.IS_WAYLAND:
        return False, _("No screenshot tool found "
                        "(install gnome-screenshot, spectacle, flameshot, or grim+slurp)")
    return False, _("No screenshot tool found "
                    "(install gnome-screenshot, spectacle, scrot, or grim+slurp)")



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
import shutil
import secrets
import subprocess
from urllib.parse import urlparse, unquote

import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib  # noqa: E402

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
            # Both required for a correct result: without "interactive",
            # area selection isn't possible at all (full-screen only);
            # without "target", the portal defaults to "Full screen" mode
            # on KDE. Neither controls step count -- some
            # xdg-desktop-portal-kde versions have no live drag-select
            # mode regardless (see _grab_region_to_file's docstring for
            # why spectacle is tried directly instead). Both have been
            # tried removed; each made things worse -- don't retry
            # without new evidence.
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
    """Capture a user-drawn rectangle into dest_png using the desktop's
    native region-screenshot mechanism -- works on X11 and Wayland. Every
    tool is launched with gui_child_env(), so a VoxFox running through
    XWayland does not drag them onto XWayland too.
    Returns (ok, error_message).

    Order, by display server:

    X11: maim/scrot, then gnome-screenshot/spectacle/flameshot, with
    quickshot only as a last resort. gnome-screenshot fails silently
    (exit 0, no file) on non-GNOME desktops like Cinnamon, so it must
    not be preferred over maim/scrot. quickshot is deliberately last
    here: it is a Wayland workaround, and its capture-first-then-select
    design buys nothing on X11 where maim can drag on the live screen.

    Wayland: quickshot (bundled, /usr/bin/quickshot) first -- it captures
    the screen non-interactively, then handles region selection itself in
    an ordinary window instead of asking the compositor's portal for an
    interactive one. That matters because some xdg-desktop-portal-kde
    versions have no live drag-to-select mode at all (an interactive Area
    request there goes through a mode-picker, then a separate capture-
    then-crop step instead). Then spectacle directly -- its -r flag goes
    straight into drag-to-select with no mode picker (KDE Bugzilla
    #473521), since it's a trusted first-party KDE component with its own
    access to KWin. Then the xdg-desktop-portal Screenshot interface
    (confirmed working on GNOME and KDE). Then gnome-screenshot/
    flameshot. maim/scrot are skipped entirely on Wayland: they can
    "succeed" with a blank capture instead of erroring. grim+slurp is
    last resort, wlroots-only -- slurp needs zwlr_layer_shell_v1, which
    neither GNOME's Mutter nor KDE's KWin implement.

    maim/scrot: a Super-key-triggered capture can briefly conflict with
    the WM's own pointer grab on the hotkey; retried briefly, and
    distinguished from a genuine user cancel (Escape) via "grab" in
    stderr."""
    if vf.IS_WAYLAND and vf._have("quickshot"):
        log.debug("OCR-select: trying quickshot")
        try:
            r = subprocess.run(["quickshot", dest_png], timeout=120,
                               capture_output=True, text=True,
                               env=vf.gui_child_env())
            if r.returncode == 0 and os.path.exists(dest_png) \
                    and os.path.getsize(dest_png) > 0:
                log.debug("OCR-select: quickshot succeeded")
                return True, ""
            # quickshot doesn't distinguish cancellation from failure in its
            # exit code (both are 1) -- always fall through rather than
            # trying to parse its (Dutch, potentially changing) stderr text.
            log.debug(f"OCR-select: quickshot exited {r.returncode} "
                     f"(stderr={r.stderr!r}), falling back")
        except Exception as e:
            log.debug(f"OCR-select: quickshot raised: {e}, falling back")

    fallbacks = [
        ("gnome-screenshot", ["-a", "-f", dest_png]),
        ("flameshot",        ["gui", "-r", "-p", dest_png]),
    ]

    if vf.IS_WAYLAND:
        considered = ["spectacle", "xdg-portal"] + [b for b, _a in fallbacks] + ["grim", "slurp"]
        log.debug(f"OCR-select: Wayland, tools present: "
                 f"{[b for b in considered if b == 'xdg-portal' or vf._have(b)]} "
                 f"(of {considered} considered)")

        if vf._have("spectacle"):
            log.debug("OCR-select: trying spectacle directly (bypassing the portal)")
            try:
                if os.path.exists(dest_png):
                    os.unlink(dest_png)
            except OSError:
                pass
            try:
                r = subprocess.run(["spectacle", "-rbno", dest_png],
                                   timeout=120, capture_output=True,
                                   text=True, env=vf.gui_child_env())
                if r.returncode == 0 and os.path.exists(dest_png) \
                        and os.path.getsize(dest_png) > 0:
                    log.debug("OCR-select: spectacle (direct) succeeded")
                    return True, ""
                log.debug(f"OCR-select: spectacle (direct) exited "
                         f"{r.returncode} with no usable file "
                         f"(stdout={r.stdout!r} stderr={r.stderr!r}); "
                         f"trying the portal instead")
            except Exception as e:
                log.debug(f"OCR-select: spectacle (direct) raised: {e}; "
                         f"trying the portal instead")

        log.debug("OCR-select: trying xdg-desktop-portal Screenshot interface")
        ok, err = _grab_via_xdg_portal(dest_png)
        if ok:
            log.debug("OCR-select: xdg-desktop-portal succeeded")
            return True, ""
        log.debug(f"OCR-select: xdg-desktop-portal failed: {err}")
        grabbers = []
    else:
        grabbers = [
            ("maim",  ["-s", dest_png]),
            ("scrot", ["-s", dest_png]),
        ]
        # Only if nothing else on this machine can select a region.
        fallbacks = fallbacks + [("quickshot", [dest_png])]
        considered = [b for b, _a in grabbers + fallbacks]
        log.debug(f"OCR-select: X11, tools present: "
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
                               capture_output=True, text=True,
                               env=vf.gui_child_env())
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

    if vf.IS_WAYLAND and vf._have("grim") and vf._have("slurp"):
        log.debug("OCR-select: trying grim+slurp")
        try:
            geom = subprocess.run(["slurp"], capture_output=True, text=True,
                                  timeout=120, env=vf.gui_child_env())
            if geom.returncode != 0 or not geom.stdout.strip():
                log.debug(f"OCR-select: slurp gave no geometry (exit "
                         f"{geom.returncode}): stderr={geom.stderr!r}")
                return False, _("Selection cancelled")
            r = subprocess.run(["grim", "-g", geom.stdout.strip(), dest_png],
                               capture_output=True, text=True, timeout=120,
                               env=vf.gui_child_env())
            if r.returncode == 0 and os.path.exists(dest_png) \
                    and os.path.getsize(dest_png) > 0:
                log.debug("OCR-select: grim+slurp succeeded")
                return True, ""
            log.debug(f"OCR-select: grim failed (exit {r.returncode}): "
                     f"stderr={r.stderr!r}")
        except Exception as e:
            log.debug(f"OCR-select: grim+slurp raised: {e}")
            return False, str(e)
    elif vf.IS_WAYLAND:
        log.debug("OCR-select: grim+slurp not both present, skipping")
    log.debug("OCR-select: no working screenshot tool found")
    if vf.IS_WAYLAND:
        return False, _("No screenshot tool found "
                        "(install gnome-screenshot, spectacle, flameshot, or grim+slurp)")
    return False, _("No screenshot tool found "
                    "(install gnome-screenshot, spectacle, scrot, or grim+slurp)")



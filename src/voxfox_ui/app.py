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

"""voxfox_ui.app — The Gtk.Application, CLI argument parser, X error handler and main().

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os
import argparse
import threading
import logging

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import ACCENT_CSS, APP_VERSION, MANUAL_URL, SYSTEM_ICON, SYSTEM_LOCALES  # noqa: E402
from voxfox_ui.history import HistoryWindow  # noqa: E402
from voxfox_ui.main_window import VoxFoxWindow  # noqa: E402
from voxfox_ui.setup import SetupDialog, apply_ui_language, run_setup  # noqa: E402
from voxfox_ui.shortcuts import _cinnamon_reload, _install_shortcuts  # noqa: E402


class VoxFoxApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.voxfox.VoxFox",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win        = None
        self.ipc_server = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        # GDK has opened its X display by now; make stray Xlib errors (e.g. a
        # window vanishing mid-query during hover) non-fatal so they can't crash us.
        _install_x_error_handler()
        for name, cb in (("about", self._on_about),
                         ("history", self._on_history),
                         ("first_run", self._on_first_run),
                         ("quit",  self._on_quit)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
        live = Gio.SimpleAction.new_stateful(
            "live_transcribe", None, GLib.Variant.new_boolean(False))
        live.connect("change-state", self._on_live_toggle)
        self.add_action(live)

    def _on_live_toggle(self, action, value):
        log.info(f"_on_live_toggle: new state={value.get_boolean()}, "
                 f"window present={self.win is not None}")
        action.set_state(value)
        if not self.win:
            return
        if value.get_boolean():
            self.win.open_live_window()
        else:
            self.win.close_live_window()

    def do_activate(self):
        if not self.win:
            self._apply_css()
            self.win = VoxFoxWindow(self)
            self.ipc_server = vf.IPCServer(self.win)
            self.ipc_server.start()
        self.win.present()
        # Restore the last on-screen position (X11), then re-assert always-on-top
        # after the window is mapped. Both are retried a few times because the
        # window title may not be set at the X level immediately, which would
        # make the wmctrl match miss on a single early attempt.
        for delay in (300, 1000):
            GLib.timeout_add(delay,
                             lambda: (self.win.restore_window_pos(), False)[1])
        for delay in (400, 1200, 2500):
            GLib.timeout_add(delay,
                             lambda: (self.win.set_always_on_top(), False)[1])
        # Shrink the window to its natural content size after it is mapped,
        # overriding any larger geometry the window manager may have remembered.
        for delay in (350, 1100):
            GLib.timeout_add(delay,
                             lambda: (self.win._fit_to_content(), False)[1])
        # Warm up the Piper server in the background so the voice model is
        # already loaded by the time the user first speaks. This eliminates
        # the ~1 s startup delay on the very first utterance.
        GLib.timeout_add(500, self._warmup_piper)
        # First run: when the engine is still missing, guide the user through
        # setup once instead of leaving them to find the menu.
        if not os.path.exists(vf.PIPER_BIN):
            GLib.timeout_add(700, self._maybe_first_run)

    def _maybe_first_run(self):
        if not getattr(self, "_first_run_shown", False) and self.win:
            self._first_run_shown = True
            SetupDialog(self.win).present()
        return False

    def _warmup_piper(self):
        """Start the Piper server in the background (fire-and-forget)."""
        try:
            slot = (self.win.state or {}).get("slot1", {})
            voice = slot.get("voice", "")
            if not voice:
                return False
            speed = float(slot.get("speed", 1.0))
            pitch = float(slot.get("pitch", 0.0))
            pitch_factor = 2.0 ** (pitch / 12.0)
            length_scale = round(pitch_factor / speed, 4)
            model = os.path.join(vf.PIPER_DIR, f"{voice}.onnx")
            if not os.path.isfile(model):
                return False

            def _do_warmup():
                try:
                    vf._piper_server.synth(
                        " ", model, length_scale, 0.1)
                    log.debug("Piper server warmed up")
                except Exception as e:
                    log.debug(f"Piper warmup failed: {e}")

            threading.Thread(target=_do_warmup, daemon=True).start()
        except Exception as e:
            log.debug(f"warmup_piper: {e}")
        return False  # don't repeat the GLib timeout

    def _apply_css(self):
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(ACCENT_CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as e:
            log.debug(f"CSS load failed: {e}")

    def _on_history(self, *_a):
        if not self.win:
            return
        self.hist_win = HistoryWindow(self.win)
        self.hist_win.present()

    def _on_first_run(self, *_a):
        if self.win:
            SetupDialog(self.win).present()

    def _on_about(self, *_a):
        dlg = Gtk.AboutDialog(transient_for=self.win, modal=True)
        dlg.set_program_name(vf.APP_NAME)
        dlg.set_version(APP_VERSION)
        dlg.set_authors(["Daniël Vos"])
        dlg.set_copyright("© 2025 Daniël Vos")
        dlg.set_website(MANUAL_URL)
        dlg.set_website_label(_("Manual — voxfox.nl/manual"))
        dlg.set_license_type(Gtk.License.GPL_3_0)

        commands = [
            ("voxfox --read",           _("Read selected text")),
            ("voxfox --stop",           _("Stop speaking")),
            ("voxfox --pause",          _("Pause / resume")),
            ("voxfox --toggle-slot",    _("Switch language slot")),
            ("voxfox --hover-toggle",   _("Toggle hover reading")),
            ("voxfox --whisper-toggle", _("Dictate (speech to text)")),
            ("voxfox --ocr-select",     _("Read a screen region (OCR)")),
            ("voxfox --read-page",      _("Read web page (experimental)")),
            ("voxfox --live-toggle",    _("Toggle live transcription")),
        ]
        shortcuts = [
            ("Super+Z", _("Read selected text")),
            ("Super+X", _("Stop speaking")),
            ("Super+C", _("Switch language slot")),
            ("Super+W", _("Dictation")),
            ("Super+A", _("OCR region select")),
            ("Super+V", _("Read web page (experimental)")),
        ]
        cmd_block = "\n".join(f"{cmd}  —  {desc}" for cmd, desc in commands)
        sc_block  = "\n".join(f"{key}  —  {desc}" for key, desc in shortcuts)
        dlg.set_comments(
            _("Screen reader and dictation tool") + "\n\n"
            + _("Default keyboard shortcuts — change them in "
                "Settings → Shortcuts:") + "\n"
            + sc_block + "\n\n"
            + _("Commands you can bind to keyboard shortcuts:") + "\n"
            + cmd_block + "\n\n"
            + _("Chromium / Brave / Chrome:") + "\n"
            + _("Add --force-renderer-accessibility to the browser's desktop "
                "file or launcher to enable hover reading in web pages."))

        # Credits section: selectable text for easy copy-paste.
        dlg.add_credit_section(_("Default shortcuts"),
                               [f"{key}  —  {desc}" for key, desc in shortcuts])
        dlg.add_credit_section(_("Shortcut commands"),
                               [f"{cmd}" for cmd, _desc in commands])
        dlg.add_credit_section(_("Chromium / Brave / Chrome"),
                               ["--force-renderer-accessibility",
                                _("Add this flag to the browser launcher "
                                  "to enable hover reading in web pages.")])

        logo = vf.LOGO_PATH if os.path.exists(vf.LOGO_PATH) else SYSTEM_ICON
        if os.path.exists(logo):
            try:
                dlg.set_logo(Gdk.Texture.new_from_filename(logo))
            except Exception:
                pass
        dlg.present()

    def _on_quit(self, *_a):
        if self.win:
            self.win.on_close()
        else:
            self.quit()


def _build_arg_parser():
    p = argparse.ArgumentParser(prog="voxfox", description=vf.APP_NAME + " (GTK4)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--read",          dest="read",          action="store_true")
    g.add_argument("--stop",          dest="stop",          action="store_true")
    g.add_argument("--pause",         dest="pause",         action="store_true")
    g.add_argument("--toggle-slot",   dest="toggle_slot",   action="store_true")
    g.add_argument("--hover-toggle",  dest="hover_toggle",  action="store_true")
    g.add_argument("--whisper-toggle", dest="whisper_toggle", action="store_true")
    g.add_argument("--ocr-select",    dest="ocr_select",    action="store_true")
    g.add_argument("--ocr-select-translate", dest="ocr_select_translate",
                   action="store_true",
                   help="OCR a screen region, translate it into the UI "
                        "language, and read it aloud")
    g.add_argument("--live-toggle",   dest="live_toggle",   action="store_true")
    g.add_argument("--translate",     dest="translate",     action="store_true",
                   help="Translate the selection into the UI language and read it")
    g.add_argument("--read-page",     dest="read_page",     action="store_true",
                   help="Read the focused browser page aloud (experimental)")
    g.add_argument("--ocr",           dest="ocr",           metavar="FILE")
    g.add_argument("--status",        dest="status",        action="store_true")
    g.add_argument("--quit",          dest="quit",          action="store_true")
    g.add_argument("--setup",         dest="setup",         action="store_true",
                   help="Download Piper engine + default voices + Whisper, then exit")
    g.add_argument("--install-shortcuts", dest="install_shortcuts", action="store_true",
                   help="(Re)install the Super+Z/X/C/W/A desktop shortcuts, then exit")
    p.add_argument("--verbose", action="store_true", help="Debug logging")
    return p


_X_ERROR_HANDLER_REF = None


def _install_x_error_handler():
    """Make Xlib errors non-fatal. By default libX11 prints the error and
    calls exit(), so a single BadWindow (a window that vanished while it was
    being queried) takes the whole app down. We install a handler that swallows
    such transient errors instead. Installed in do_startup, after GDK has opened
    its display, so this overrides GDK's default (last XSetErrorHandler wins)."""
    global _X_ERROR_HANDLER_REF
    try:
        import ctypes
        x11 = ctypes.CDLL("libX11.so.6")
        proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _handler(_display, _event):
            return 0  # ignore; do not abort the process

        _X_ERROR_HANDLER_REF = proto(_handler)  # keep a ref so it is not GC'd
        x11.XSetErrorHandler(_X_ERROR_HANDLER_REF)
        log.debug("Installed non-fatal X error handler")
    except Exception as e:
        log.debug(f"could not install X error handler: {e}")


# VoxFox's default global shortcuts, in a stable order. The first element is
# an internal action key (used to track which desktop slot we own); it is NOT
# the slot name written to the desktop. Fields: key, label, command, binding.
def _enable_accessibility():
    """Coax the desktop accessibility stack on at startup, the way a screen
    reader (Orca) does, so GTK apps and browsers build and keep their AT-SPI
    trees. Without this a browser may not populate its tree until a recognised
    assistive technology shows up, leaving hover with nothing to read.
    Best-effort: any failure is ignored."""
    try:
        from gi.repository import Gio
        src = Gio.SettingsSchemaSource.get_default()
        if src is None:
            return
        for schema in ("org.gnome.desktop.interface",
                       "org.cinnamon.desktop.interface",
                       "org.mate.interface"):
            try:
                sch = src.lookup(schema, True)
                if sch is None or not sch.has_key("toolkit-accessibility"):
                    continue
                s = Gio.Settings.new(schema)
                if not s.get_boolean("toolkit-accessibility"):
                    s.set_boolean("toolkit-accessibility", True)
                    log.info(f"Enabled toolkit-accessibility via {schema}")
            except Exception as e:
                log.debug(f"a11y enable via {schema} failed: {e}")
    except Exception as e:
        log.debug(f"accessibility warm-up skipped: {e}")


def main():
    # Force the program name so GTK4 under X11 stamps the window with
    # WM_CLASS "org.voxfox.VoxFox" instead of "python3". Without this the
    # panel/taskbar cannot match the running window to the .desktop launcher,
    # so it shows up as a separate, generic-icon window. Must run before any
    # GTK/GDK initialisation. StartupWMClass in voxfox.desktop must match this.
    GLib.set_prgname("org.voxfox.VoxFox")

    # Turn the accessibility stack on early (like a screen reader) so browsers
    # and GTK apps build their AT-SPI trees that hover-to-read depends on.
    _enable_accessibility()

    # Create XDG dirs and migrate any 1.x / Tk-era data forward (non-destructive).
    vf.init_storage()

    # Prefer system-installed locales when no per-user set exists.
    if not os.path.isdir(vf.locales_dir()) and os.path.isdir(SYSTEM_LOCALES):
        vf.set_locales_dir(SYSTEM_LOCALES)

    # Populate the translation tables, THEN switch the UI to slot 1's language.
    # (Without load_translations() the tables stay empty and the UI is stuck
    # on English regardless of the slot 1 setting.)
    vf.load_translations()
    try:
        st = vf.load_state()
        apply_ui_language(st["slot1"].get("lang", ""))
        vf.set_pronunciations(st.get("pronunciations", {}))
        vf.set_merge_lines(st.get("merge_lines", True))
    except Exception:
        pass

    args = _build_arg_parser().parse_args()
    if args.verbose:
        vf.log.setLevel(logging.DEBUG)

    # Headless component setup.
    if args.setup:
        ok, msg = run_setup(progress=lambda m: print(f"  {m}"))
        print("Setup complete." if ok else f"Setup failed: {msg}")
        return 0 if ok else 1

    # Manual (re)install of the desktop keyboard shortcuts.
    if args.install_shortcuts:
        st = vf.load_state()
        ok = _install_shortcuts(st)
        if ok:
            st["shortcuts_installed"] = True
        vf.save_state(st)
        if ok:
            _cinnamon_reload()
        print("Shortcuts installed." if ok
              else "Could not install shortcuts on this desktop "
                   "(no supported method found).")
        return 0 if ok else 1

    # Action flags → forward to the running instance and exit (no GUI).
    if any([args.read, args.stop, args.pause, args.toggle_slot,
            args.hover_toggle, args.whisper_toggle, args.ocr_select,
            args.ocr_select_translate,
            args.read_page, args.live_toggle, args.translate,
            args.ocr, args.status,
            args.quit]):
        vf.run_cli(args)
        return 0

    if vf.is_instance_running():
        vf.send_command("ping")
        print("VoxFox is already running.")
        return 0
    if not vf.acquire_singleton_lock():
        print("VoxFox is already running.")
        return 0

    # Shortcuts are no longer auto-installed on first start: some desktops ship
    # their own bindings for these keys, and silently overwriting them is rude.
    # The user picks keys and installs them from Settings → Shortcuts (or via
    # `voxfox --install-shortcuts`).

    # If the AT-SPI accessibility bus can't actually be reached (switched off,
    # missing, or a stale root-owned socket such as /root/.cache/at-spi/bus_0),
    # tell GTK NOT to load its accessibility bridge. Otherwise libatspi's dbind
    # layer responds to the failed connection with a hard abort() — a core dump
    # at startup — which no Python try/except can catch. Hover reading is guarded
    # separately (it reports the bus as unavailable instead of crashing). When
    # the bus works normally this branch is skipped and VoxFox stays accessible.
    if not vf.a11y_bus_reachable():
        os.environ.setdefault("GTK_A11Y", "none")
        os.environ.setdefault("NO_AT_BRIDGE", "1")
        log.debug("AT-SPI bus unreachable — disabled GTK a11y bridge for "
                  "this process to avoid a libatspi abort.")

    VoxFoxApplication().run(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

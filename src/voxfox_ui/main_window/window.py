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

"""voxfox_ui.main_window.window

The main VoxFox window: start-up, the live transcription and Type and
speak windows, settings and quitting.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import RootShim  # noqa: E402
from voxfox_ui.live import LiveTranscribeWindow  # noqa: E402
from voxfox_ui.preferences import PreferencesWindow  # noqa: E402
from voxfox_ui.setup import run_setup  # noqa: E402
from voxfox_ui.main_window.layout import LayoutMixin  # noqa: E402
from voxfox_ui.main_window.status import StatusMixin  # noqa: E402
from voxfox_ui.main_window.placement import PlacementMixin  # noqa: E402
from voxfox_ui.main_window.reading import ReadingActions  # noqa: E402
from voxfox_ui.main_window.dictation import DictationActions  # noqa: E402
from voxfox_ui.main_window.ocr import OcrActions  # noqa: E402


class VoxFoxWindow(LayoutMixin, StatusMixin, PlacementMixin, ReadingActions,
                   DictationActions, OcrActions,
                   Gtk.ApplicationWindow):
    """The main VoxFox window. Start-up, the live transcription and Type
    and speak windows, settings and quitting live here; everything else
    comes from the mixins."""

    def __init__(self, app):
        super().__init__(application=app, title=vf.APP_NAME)
        # No fixed default size: let the window size itself to the toolbar's
        # natural size, so it is exactly wide enough for the visible buttons
        # (4-5 on one row) and exactly tall enough (no empty filler below). It
        # stays resizable, and the maximize button is dropped via the header
        # decoration layout in _build_ui.
        self.state      = vf.load_state()
        self.whisper_on = False
        self._record_stop_event = None
        self.hover_on   = False
        self.root       = RootShim()
        # 3.0 UI scale: one CSS provider on the display whose root font-size we
        # swap to zoom the whole main window (see scale_css / apply_ui_scale).
        self._scale_provider = Gtk.CssProvider()
        try:
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self._scale_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as e:
            log.debug(f"scale provider add failed: {e}")
        self._load_scale_css()
        # Hover mode (in voxfox_core) asks this callback which voice to speak with.
        vf.set_slot_config_provider(self._active_cfg)
        # Hover reading over VoxFox's own windows, menus and settings.
        try:
            from voxfox_ui import selfread
            selfread.install()
        except Exception as e:
            log.debug(f"own-window hover reading unavailable: {e}")
        self._build_ui()
        self._sync_pause_btn()
        # Keep the window above others: re-assert "always on top" whenever it
        # stops being the active window (e.g. another app was opened). The
        # initial assert is done from do_activate once the window is mapped.
        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request",
                     lambda *_a: (self.do_quit_cleanup(), False)[1])

    def _on_active_changed(self, *_a):
        if not self.is_active():
            self.set_always_on_top()
        # The document currently being spoken, so pause and stop know
        # where to save the reading position. None for ordinary text.
        self.current_document = None
        self.current_document_dir = None

    def rebuild_ui(self):
        """Rebuild the whole window UI in place. Used to re-render every label
        in a new UI language when slot 1's language changes, and after the
        toolbar layout (visible buttons / order) changes."""
        self._build_ui()
        self._sync_pause_btn()
        self._fit_to_content()

    def do_live_toggle(self):
        """Toggle live transcription from a shortcut/CLI command; keeps the
        menu checkbox in sync either way."""
        try:
            app = self.get_application()
            act = app.lookup_action("live_transcribe") if app else None
            if act is None:
                log.info("do_live_toggle: 'live_transcribe' action not "
                         "found on the application")
                return
            cur = act.get_state().get_boolean()
            log.info(f"do_live_toggle: {cur} -> {not cur}")
            act.change_state(GLib.Variant.new_boolean(not cur))
        except Exception as e:
            log.debug(f"do_live_toggle failed: {e}")

    def open_live_window(self):
        """Open (or focus) the live transcription window and start listening."""
        if getattr(self, "_live_win", None) is not None:
            self._live_win.present()
            return
        self._live_win = LiveTranscribeWindow(self)
        self._live_win.present()

    def close_live_window(self):
        if getattr(self, "_live_win", None) is not None:
            self._live_win.shutdown()
            self._live_win = None

    def _live_window_closed(self):
        """Called by the window itself; sync the menu toggle back to off."""
        self._live_win = None
        try:
            app = self.get_application()
            act = app.lookup_action("live_transcribe") if app else None
            if act:
                act.set_state(GLib.Variant.new_boolean(False))
        except Exception:
            pass

    def open_preferences(self):
        self._prefs = PreferencesWindow(self)
        self._prefs.present()

    # ── setup ─────────────────────────────────────────────────────────────────
    def run_setup_async(self, on_done=None):
        self.set_status(_("Setting up..."), duration=0)

        def worker():
            ok, msg = run_setup(
                progress=lambda m: GLib.idle_add(self.set_status, m, 0),
                frac=lambda fr, lbl=None: GLib.idle_add(
                    self.set_progress, fr, lbl))
            def done():
                self.reload_active_controls()
                self.hide_progress()
                if ok:
                    self.set_status(_("Setup complete"))
                else:
                    self.set_status(
                        _("Setup incomplete: %s") % msg, duration=8000)
                self.refresh_setup_bar()
                if on_done:
                    on_done()
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def do_type_speak(self):
        """Open the window where a typed text is said aloud."""
        from voxfox_ui import typespeak
        typespeak.present(self)

    def on_close(self):
        self.do_quit_cleanup()
        app = self.get_application()
        if app:
            app.quit()

    def do_quit_cleanup(self):
        self.save_window_pos()
        vf.set_hover_running(False)
        try:
            vf.stop_speaking()
        except Exception:
            pass
        try:
            vf.shutdown_piper()
        except Exception:
            pass
        try:
            vf.shutdown_speechd()
        except Exception:
            pass
        srv = getattr(self.get_application(), "ipc_server", None)
        if srv:
            try:
                srv.stop()
            except Exception:
                pass

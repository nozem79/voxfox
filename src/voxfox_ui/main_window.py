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

"""voxfox_ui.main_window — The main VoxFox application window.

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os
import threading
import tempfile
import subprocess

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import TOOLBAR_BUTTONS, TOOLBAR_DEFAULT_HIDDEN, TOOLBAR_IDS, UI_ORIENTS, UI_VIEWS, _RootShim, _register_icon_path  # noqa: E402
from voxfox_ui.live import LiveTranscribeWindow  # noqa: E402
from voxfox_ui.preferences import PreferencesWindow  # noqa: E402
from voxfox_ui.screenshot import _grab_region_to_file  # noqa: E402
from voxfox_ui.setup import SetupDialog, run_setup  # noqa: E402
from voxfox_ui.widgets import _a11y, _btn_make_content, _btn_set_text, _hide_progress_bar, _scale_css, _set_progress_bar  # noqa: E402


class VoxFoxWindow(Gtk.ApplicationWindow):
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
        self.root       = _RootShim()
        # 3.0 UI scale: one CSS provider on the display whose root font-size we
        # swap to zoom the whole main window (see _scale_css / apply_ui_scale).
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

    def rebuild_ui(self):
        """Rebuild the whole window UI in place. Used to re-render every label
        in a new UI language when slot 1's language changes, and after the
        toolbar layout (visible buttons / order) changes."""
        self._build_ui()
        self._sync_pause_btn()
        self._fit_to_content()

    def _load_scale_css(self):
        """(Re)load the scale provider from the scale stored in ui_layout."""
        scale = (self.state.get("ui_layout") or {}).get("scale",
                                                         vf.DEFAULT_UI_SCALE)
        if scale not in vf.UI_SCALES:
            scale = vf.DEFAULT_UI_SCALE
        try:
            self._scale_provider.load_from_data(_scale_css(scale))
        except Exception as e:
            log.debug(f"scale css load failed: {e}")

    def apply_ui_scale(self, scale):
        """Set the global UI scale (75/100/125) live — no rebuild needed, the
        CSS cascade reflows the toolbar. Persists the choice and shrinks the
        window back to the new, smaller content size."""
        if scale not in vf.UI_SCALES:
            scale = vf.DEFAULT_UI_SCALE
        self.state.setdefault("ui_layout", {})["scale"] = scale
        vf.save_state(self.state)
        self._load_scale_css()
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

    def _apply_ui_mode(self, fit=True):
        """Apply the ui_view and ui_orientation settings: rebuild the button
        rows (horizontal: up to 5 per row; vertical: one per row), toggle the
        icon/label parts of every button, align content (left in vertical
        with text, centred otherwise), and switch the header to its slim
        logo-only form in the narrow vertical+icons mode. Tooltips and
        accessibility labels are unaffected in every mode, so screen readers
        keep announcing the button names."""
        mode = self.state.get("ui_view", "both")
        if mode not in UI_VIEWS:
            mode = "both"
        orient = self.state.get("ui_orientation", "horizontal")
        if orient not in UI_ORIENTS:
            orient = "horizontal"
        vertical = orient == "vertical"
        slim = vertical and mode == "icons"

        # 1. Per-button parts + alignment.
        for btn in self._toolbar_btns.values():
            if getattr(btn, "_icon", None) is None:
                continue
            btn._icon.set_visible(mode != "text")
            btn._lbl.set_visible(mode != "icons")
            box = btn._icon.get_parent()
            if box is not None:
                box.set_halign(Gtk.Align.START if vertical and mode != "icons"
                               else Gtk.Align.CENTER)

        # 2. Rebuild the rows.
        cont = self._toolbar_container
        child = cont.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            if isinstance(child, Gtk.Box):
                inner = child.get_first_child()
                while inner is not None:
                    inxt = inner.get_next_sibling()
                    child.remove(inner)
                    inner = inxt
            cont.remove(child)
            child = nxt

        layout = vf.reconcile_toolbar_layout(self.state.get("ui_layout"),
                                             TOOLBAR_IDS,
                                             TOOLBAR_DEFAULT_HIDDEN)
        visible_ids = [e["id"] for e in layout["buttons"] if e["visible"]]
        if vf.IS_WAYLAND:
            # Hover mode can't work under Wayland (see do_hover()) -- hide
            # the button rather than leave a control that looks clickable
            # but can never do anything.
            visible_ids = [bid for bid in visible_ids if bid != "hover"]
        if vertical:
            rows = [[bid] for bid in visible_ids]
        else:
            n = len(visible_ids)
            if n <= 5:
                rows = [visible_ids] if visible_ids else []
            else:
                half = (n + 1) // 2
                rows = [visible_ids[:half], visible_ids[half:]]
        for row_ids in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0,
                          homogeneous=True)
            row.set_halign(Gtk.Align.FILL)
            row.set_hexpand(True)
            for bid in row_ids:
                btn = self._toolbar_btns[bid]
                btn.set_hexpand(True)
                row.append(btn)
            cont.append(row)

        # 3. Column gear/menu at the bottom (only in slim mode), stacked
        # vertically so they never force the column wider than one button.
        cont.append(self._col_sep)
        cont.append(self._col_gear)
        cont.append(self._col_menu)
        self._col_sep.set_visible(slim)
        self._col_gear.set_visible(slim)
        self._col_menu.set_visible(slim)

        # 4. Slim header: only the logo (keeps the drag area), no name; the
        # normal header returns as soon as we leave the slim mode.
        try:
            if slim:
                # An empty title collapses the title area; only the close
                # button remains, so the header adds no width of its own.
                self._header.set_title_widget(Gtk.Label(label=""))
                self._header.set_decoration_layout(":close")
                self._header_gear.set_visible(False)
                self._header_menu.set_visible(False)
            else:
                if self._header_title is None:
                    self._header_title = Gtk.Label(label="VoxFox")
                    self._header_title.add_css_class("title")
                self._header.set_title_widget(self._header_title)
                self._header.set_decoration_layout(":minimize,close")
                self._header_gear.set_visible(True)
                self._header_menu.set_visible(True)
        except Exception as e:
            log.debug(f"slim header failed: {e}")

        # Two targeted attempts at a reported Fedora/KDE label-rendering
        # issue (ellipsize/width-chars, then the button-display mode) made
        # no visible difference at all -- not even a partial one -- which
        # means something more fundamental than a CSS/property tweak is
        # going on. Dump what each label actually has once layout has
        # settled (GLib.idle_add, since sizes aren't meaningful until
        # after the pending allocation pass) so --verbose can show whether
        # this is a visibility problem, a missing-text problem, a
        # zero-size-allocation problem, or something else (e.g. a colour
        # matching the background) that none of the above would explain.
        GLib.idle_add(self._debug_dump_button_sizes)

        if fit:
            self._fit_to_content()

    def _debug_dump_button_sizes(self):
        """One-shot diagnostic for --verbose: for every toolbar button, log
        whether its icon/label are visible, what text the label actually
        holds, and the allocated size of both the label and the button
        itself. Only meaningful after layout has settled (see the
        GLib.idle_add call site), since sizes are 0 beforehand."""
        for bid, btn in self._toolbar_btns.items():
            icon = getattr(btn, "_icon", None)
            lbl = getattr(btn, "_lbl", None)
            if icon is None or lbl is None:
                log.debug(f"UI-diag: {bid}: no _icon/_lbl attributes")
                continue
            log.debug(
                f"UI-diag: {bid}: icon_visible={icon.get_visible()} "
                f"lbl_visible={lbl.get_visible()} lbl_text={lbl.get_text()!r} "
                f"lbl_size={lbl.get_width()}x{lbl.get_height()} "
                f"btn_size={btn.get_width()}x{btn.get_height()}")
        return False  # one-shot; don't re-arm as a repeating source

    def _fit_to_content(self, keep_width=False):
        """Shrink the window to the toolbar's current natural size (X11, best-
        effort). GTK4 doesn't auto-shrink a window when its content gets smaller
        (after lowering the UI scale or hiding buttons), so we nudge it via
        wmctrl to keep the window as narrow/short as the visible buttons allow.
        The window stays resizable; this only removes leftover empty space.
        With keep_width=True only the height shrinks back (used after the
        status line hides), so a user-widened window keeps its width."""
        if not vf._have("wmctrl"):
            return

        def do_fit():
            try:
                _min, nat = self.get_preferred_size()
                # A measurement taken before the widgets are fully realized
                # (seen on KDE/KWin during the very first start) can come back
                # near-zero; resizing to that makes the window invisible.
                # Skip suspicious measurements and never shrink below a sane
                # floor, so the window always stays visible and grabbable.
                vertical = self.state.get("ui_orientation") == "vertical"
                if nat.height < 50 or nat.width < (40 if vertical else 120):
                    log.debug(f"fit skipped: suspicious size "
                              f"{nat.width}x{nat.height}")
                    return False
                if vertical:
                    # Pin the width to the button column and stay there: the
                    # natural width of the whole window includes status text,
                    # which would widen the narrow sidebar every time a
                    # status appears (e.g. toggling hover). Wrapping labels
                    # are fine with a narrow width, so cap on the column.
                    try:
                        _cm, cnat = self._toolbar_container.get_preferred_size()
                        w = max(64, cnat.width + 20)
                    except Exception:
                        w = max(64, self.get_width())
                    h = max(80, nat.height)
                else:
                    w, h = max(220, nat.width), max(80, nat.height)
                    if keep_width:
                        w = max(w, self.get_width())
            except Exception as e:
                log.debug(f"fit measure failed: {e}")
                return False

            def worker():
                try:
                    subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                    "-e", f"0,-1,-1,{w},{h}"], timeout=5)
                except Exception as e:
                    log.debug(f"fit-to-content failed: {e}")
            threading.Thread(target=worker, daemon=True).start()
            return False
        # Defer so the new CSS / layout has settled before we measure.
        GLib.timeout_add(50, do_fit)

    def _build_ui(self):
        header = Gtk.HeaderBar()
        header.add_css_class("voxfox-root")   # scale the title + header icons too
        # Drop the useless maximize button; keep minimize + close. The window
        # stays resizable by edge-drag.
        header.set_decoration_layout(":minimize,close")
        self.set_titlebar(header)

        # The language switcher lives at the end of the second button row
        # (added below), not in the header — that frees the title bar to show
        # the program name.
        self.switch_btn = Gtk.Button()
        _btn_make_content(self.switch_btn, "switch", "")
        self.switch_btn.set_tooltip_text(_("Switch language slot"))
        _a11y(self.switch_btn, _("Switch language slot"))
        self.switch_btn.connect("clicked", lambda *_a: self.do_toggle_slot())

        gear = Gtk.Button(icon_name="voxfox-gear-symbolic")
        gear.set_tooltip_text(_("Settings"))
        _a11y(gear, _("Settings"))
        gear.connect("clicked", lambda *_a: self.open_preferences())
        header.pack_end(gear)
        self._header = header
        self._header_title = None
        self._header_gear = gear

        menu = Gio.Menu()
        menu.append(_("Set up VoxFox…"), "app.first_run")
        menu.append(_("History"), "app.history")
        menu.append(_("Live transcription"), "app.live_transcribe")
        menu.append(_("About"), "app.about")
        menu.append(_("Quit"),  "app.quit")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        menu_btn.set_tooltip_text(_("Menu"))
        _a11y(menu_btn, _("Menu"))
        header.pack_end(menu_btn)
        self._header_menu = menu_btn
        self._menu_model = menu

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.add_css_class("voxfox-root")   # scopes the 3.0 UI-scale CSS
        outer.add_css_class("voxfox-pad")    # em-based padding, scales with size
        self.set_child(outer)

        # Setup banner — only shown when the Piper engine is missing.
        self.setup_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.setup_bar.add_css_class("card")
        lbl = Gtk.Label(label=_("Piper TTS is not installed yet."), xalign=0,
                        hexpand=True)
        setup_btn = Gtk.Button(label=_("Install now"))
        setup_btn.add_css_class("voxfox-accent")
        _a11y(setup_btn, _("Install Piper and components now"))
        setup_btn.connect("clicked", lambda *_a: SetupDialog(self).present())
        self.setup_bar.append(lbl)
        self.setup_bar.append(setup_btn)
        outer.append(self.setup_bar)

        # ── Modular toolbar (3.0) ────────────────────────────────────────────
        # The seven action buttons, shown and ordered per the user's ui_layout.
        # All seven are always instantiated (other code refers to self.read_btn,
        # self.whisper_btn, ...), but only the enabled ones are packed, in the
        # chosen order. The language switcher is fixed and always shown last.
        _register_icon_path()
        self._toolbar_btns = {}
        for bid, attr, label, tip, a11y_lbl, handler, css in TOOLBAR_BUTTONS:
            btn = Gtk.Button()
            _btn_make_content(btn, bid, _(label))
            btn.set_tooltip_text(_(tip))
            _a11y(btn, _(a11y_lbl))
            if css:
                btn.add_css_class(css)
            btn.connect("clicked", lambda *_a, h=handler: getattr(self, h)())
            setattr(self, attr, btn)
            self._toolbar_btns[bid] = btn
        # The language switcher is a modular button too (id "switch"); it is
        # built specially because its label is dynamic (the current language).
        self._toolbar_btns["switch"] = self.switch_btn
        # Note: labels are deliberately NOT ellipsized or width-capped. Showing
        # the full text means each button's minimum width is its full label, so
        # the window can never shrink small enough to clip the text — the
        # buttons stay fully readable at every scale. (The dictate button no
        # longer needs a width cap: its recording label is the short "Stop".)

        layout = vf.reconcile_toolbar_layout(self.state.get("ui_layout"),
                                             TOOLBAR_IDS,
                                             TOOLBAR_DEFAULT_HIDDEN)
        self.state["ui_layout"] = layout

        # Lay the visible buttons out in explicit rows rather than a FlowBox.
        # A FlowBox wraps on window width (so a narrow window split 4 buttons as
        # 3+1) and, worse, negotiates a tall minimum height as if every button
        # might stack in one column — which left empty vertical space the window
        # could not be shrunk below. Explicit rows give a predictable, compact
        # size: up to 5 buttons on one row, 6+ split evenly over two rows.
        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar.add_css_class("voxfox-toolbar")
        toolbar.set_halign(Gtk.Align.FILL)
        toolbar.set_hexpand(True)
        self._toolbar_container = toolbar

        # Column-mode settings/menu buttons: in the narrow vertical+icons
        # sidebar the header shows only the logo, so gear + menu move to the
        # bottom of the button column (hidden in every other mode).
        self._col_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._col_gear = Gtk.Button(icon_name="voxfox-gear-symbolic")
        self._col_gear.set_tooltip_text(_("Settings"))
        _a11y(self._col_gear, _("Settings"))
        self._col_gear.connect("clicked", lambda *_a: self.open_preferences())
        self._col_menu = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                        menu_model=self._menu_model)
        self._col_menu.set_tooltip_text(_("Menu"))
        _a11y(self._col_menu, _("Menu"))

        outer.append(toolbar)
        self._apply_ui_mode(fit=False)

        # STATUS role makes screen readers announce status changes (a live
        # region), so blind users hear "Reading...", errors, etc.
        self.status = Gtk.Label(label="", xalign=0.0,
                                accessible_role=Gtk.AccessibleRole.STATUS)
        self.status.add_css_class("dim-label")
        self.status.set_wrap(True)
        self.status.set_visible(False)
        outer.append(self.status)

        # Download progress, shown just below the status line. Hidden until a
        # download (Whisper model, Piper engine/voices) is running.
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_visible(False)
        outer.append(self.progress)

        self._sync_switch_btn()
        self.refresh_setup_bar()

    # ── helpers ───────────────────────────────────────────────────────────────
    def _active_slot(self):
        return self.state.get("active_slot", "slot1")

    def _active_cfg(self):
        return self.state[self._active_slot()]

    def set_status(self, msg, duration=2000):
        # Each new message bumps the sequence number, so a hide-timer from an
        # older message can't wipe a newer one early.
        self._status_seq = getattr(self, "_status_seq", 0) + 1
        if msg:
            self.status.set_text(msg)
            self.status.set_visible(True)
            if duration and duration > 0:
                GLib.timeout_add(duration, self._clear_status,
                                 self._status_seq)
        else:
            self._clear_status()

    def _clear_status(self, seq=None):
        if seq is not None and seq != getattr(self, "_status_seq", 0):
            return False   # replaced by a newer status in the meantime
        self.status.set_text("")
        self.status.set_visible(False)
        # Showing the status grew the window; GTK4 never shrinks it back by
        # itself, so nudge it back to its natural size once nothing transient
        # is visible any more.
        if not self.progress.get_visible():
            self._fit_to_content(keep_width=True)
        return False

    def set_progress(self, fraction, label=None):
        """Show/update the download progress bar (call on the GUI thread)."""
        if _set_progress_bar(self.progress, fraction, label) >= 1.0:
            GLib.timeout_add(800, self.hide_progress)
        return False

    def hide_progress(self):
        r = _hide_progress_bar(self.progress)
        if not self.status.get_visible():
            self._fit_to_content(keep_width=True)
        return r

    def refresh_setup_bar(self):
        self.setup_bar.set_visible(not os.path.exists(vf.PIPER_BIN))

    def get_window_pos(self):
        """Return (x, y) of our window via wmctrl (X11 only), or None.
        GTK4 has no portable get_position(), so we read it from the window
        manager. Matches our window by its exact title (APP_NAME)."""
        if not vf._have("wmctrl"):
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
            if pos:
                self.state["win_pos"] = [pos[0], pos[1]]
                vf.save_state(self.state)
        except Exception as e:
            log.debug(f"could not save window position: {e}")

    def restore_window_pos(self):
        """Move the window back to its saved position (X11 only, best-effort).
        Size is left unchanged (-1,-1)."""
        pos = (self.state or {}).get("win_pos")
        if not pos or not vf._have("wmctrl"):
            return
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError, IndexError):
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
        GTK4 dropped a native always-on-top API, so this is best-effort via
        wmctrl and only takes effect on X11 (Wayland leaves stacking to the
        compositor)."""
        if not vf._have("wmctrl"):
            return

        def worker():
            try:
                subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                "-b", "add,above"], timeout=5)
            except Exception as e:
                log.debug(f"always-on-top failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def reload_active_controls(self):
        """Re-sync the title-bar slot indicator and setup banner from state
        (called after the Settings window changes things)."""
        self._sync_switch_btn()
        self.refresh_setup_bar()

    def _sync_switch_btn(self):
        try:
            _btn_set_text(self.switch_btn, 
                vf.piper_lang_short(self._active_cfg().get("lang", "")))
        except Exception:
            _btn_set_text(self.switch_btn, "•")

    def _sync_pause_btn(self):
        _btn_set_text(self.pause_btn,
                      _("Resume") if vf.is_paused() else _("Pause"))

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

    # ── actions (also the IPCServer entry points) ─────────────────────────────
    def do_read(self):
        text = vf.get_selection()
        if vf.merge_enabled():
            text = vf.merge_wrapped_lines(text)
        if len(text) >= 2:
            cfg = self._active_cfg()
            vf.add_history("read", text)
            threading.Thread(target=vf.speak, args=(text, cfg),
                             daemon=True).start()
            GLib.timeout_add(50, lambda: (self._sync_pause_btn(), False)[1])
            self.set_status(f"{_('Reading...')} [{cfg.get('voice', '')}]", 1500)
        else:
            self.set_status(_("Nothing selected"))

    def do_translate(self):
        """Translate the selection into the UI language and speak it with
        the Slot 1 voice (the UI language follows Slot 1, so that voice
        matches the translated text)."""
        text = vf.get_selection()
        if vf.merge_enabled():
            text = vf.merge_wrapped_lines(text)
        if len(text) < 2:
            self.set_status(_("Nothing selected"))
            return
        self.set_status(_("Translating..."), duration=0)

        def worker():
            def prog(i, n):
                if n > 1:
                    GLib.idle_add(lambda: (self.set_status(
                        f"{_('Translating...')} {i}/{n}", duration=0),
                        False)[1])
            out, err = vf.translate_text(
                text, self.state.get("translate", {}), progress=prog)

            def done():
                if err or not out:
                    self.set_status(f"{_('Translation failed')}: {err}"
                                    if err else _("Translation failed"))
                    return False
                cfg = self.state["slot1"]
                vf.add_history("translate", out)
                threading.Thread(target=vf.speak, args=(out, cfg),
                                 daemon=True).start()
                GLib.timeout_add(
                    50, lambda: (self._sync_pause_btn(), False)[1])
                self.set_status(
                    f"{_('Reading translation...')} "
                    f"[{cfg.get('voice', '')}]", 2000)
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def do_stop(self):
        vf.stop_speaking()
        self._sync_pause_btn()
        self.set_status(_("Stopped"))

    def do_pause(self):
        if not vf.is_speaking():
            self.set_status(_("Nothing to pause"))
            return
        paused = vf.toggle_pause()
        self._sync_pause_btn()
        self.set_status(_("Paused") if paused else _("Resumed"))

    def do_toggle_slot(self):
        new = "slot2" if self._active_slot() == "slot1" else "slot1"
        self.state["active_slot"] = new
        vf.save_state(self.state)
        self.reload_active_controls()
        cfg  = self.state[new]
        name = cfg.get("voice", new)
        self.set_status(f"{_('Language')}: {name}")
        threading.Thread(target=vf.speak, args=(f"{_('Language')}: {name}", cfg),
                         daemon=True).start()

    def do_whisper(self):
        if self.whisper_on:
            if self._record_stop_event:
                self._record_stop_event.set()
            self.set_status(_("Stopping..."), duration=0)
            return
        self.whisper_on = True
        _btn_set_text(self.whisper_btn, _("Stop"))
        self.whisper_btn.add_css_class("destructive-action")
        self.set_status(_("Recording..."), duration=0)
        self._record_stop_event = threading.Event()
        threading.Thread(target=self._whisper_worker, daemon=True).start()

    def _whisper_worker(self):
        w = self.state["whisper"]
        lang_hint = vf._whisper_lang_code(self._active_cfg().get("lang", ""))
        wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                             dir=vf.ram_tmpdir()) as f:
                wav_path = f.name
            ok, msg = vf.record_audio(
                wav_path, mic_id=w.get("mic_id", ""),
                max_seconds=w.get("max_record_seconds", vf.WHISPER_MAX_SECONDS),
                stop_evt=self._record_stop_event)
            self.root.after(0, self.set_status, _("Transcribing..."), 0)
            if not ok:
                self.root.after(0, self.set_status, f"{_('Recording failed')}: {msg}")
                return
            text, err = vf.transcribe(
                wav_path, w.get("model", "small"), language_hint=lang_hint,
                progress_cb=lambda m: self.root.after(0, self.set_status, m, 0),
                whisper_cfg=w,
                frac_cb=lambda fr, lbl=None: self.root.after(
                    0, self.set_progress, fr, lbl))
            if err:
                self.root.after(0, self.set_status, err)
                return
            if not text:
                self.root.after(0, self.set_status, _("No speech detected"))
                return
            if w.get("confirm_before_typing", False):
                # Show the transcription for review before it is typed. The
                # dialog must run on the GUI thread.
                self.root.after(0, self._confirm_transcription, text)
            else:
                self._deliver_transcription(text)
        except Exception as e:
            log.error(f"Whisper worker: {e}")
            self.root.after(0, self.set_status, f"{_('Error')}: {e}")
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
            self.root.after(0, self.hide_progress)
            self.root.after(0, self._whisper_reset_btn)

    def _deliver_transcription(self, text):
        """Type or paste the (possibly edited) transcription and record it."""
        if not text:
            return
        ok2, msg2 = vf.type_or_paste_text(text)
        if not ok2:
            self.root.after(0, self.set_status,
                            f"{_('Type failed')}: {msg2}")
            return
        vf.add_history("dictate", text)
        preview = text if len(text) <= 40 else text[:40] + "..."
        self.root.after(0, self.set_status, f"✓ {preview}")

    def _confirm_transcription(self, text):
        """Preview dialog shown after dictation when 'Confirm transcription
        before typing' is on. The user can edit the text and copy it to the
        clipboard, then paste it wherever they want with Ctrl+V. Copying
        (rather than typing) avoids the window-focus problem where the text
        would otherwise land in VoxFox's own window."""
        dlg = Gtk.Dialog(title=_("Confirm transcription"), modal=True)
        try:
            dlg.set_transient_for(self)
        except Exception:
            pass
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        cp = dlg.add_button(_("Copy"), Gtk.ResponseType.OK)
        cp.add_css_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.OK)

        box = dlg.get_content_area()
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_spacing(8)
        box.append(Gtk.Label(
            label=_("Review the text, then copy it and paste with Ctrl+V:"),
            xalign=0.0))
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(text)
        tv.set_size_request(360, 120)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(tv)
        scroller.set_min_content_height(120)
        box.append(scroller)

        def on_response(d, resp):
            if resp == Gtk.ResponseType.OK:
                buf = tv.get_buffer()
                edited = buf.get_text(buf.get_start_iter(),
                                      buf.get_end_iter(), False).strip()
                d.destroy()
                if edited:
                    if vf._clipboard_set(edited):
                        vf.add_history("dictate", edited)
                        self.set_status(
                            _("Transcription copied — press Ctrl+V to paste"),
                            8000)
                    else:
                        self.set_status(_("Copy failed"))
                else:
                    self.set_status(_("Cancelled"))
            else:
                d.destroy()
                self.set_status(_("Cancelled"))
        dlg.connect("response", on_response)
        dlg.present()
        return False

    def _whisper_reset_btn(self):
        self.whisper_on = False
        _btn_set_text(self.whisper_btn, _("Speak"))
        self.whisper_btn.remove_css_class("destructive-action")

    def do_ocr_file(self):
        dialog = Gtk.FileChooserNative(
            title=_("Open a PDF or image"), transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        flt = Gtk.FileFilter()
        flt.set_name(_("Documents and images"))
        for pat in ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff",
                    "*.webp"):
            flt.add_pattern(pat)
        dialog.add_filter(flt)

        def on_response(dlg, resp):
            if resp == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile:
                    self._run_ocr_path(gfile.get_path())
            dlg.destroy()
            self._filechooser = None

        self._filechooser = dialog  # hold a ref so it is not GC'd
        dialog.connect("response", on_response)
        dialog.show()

    def do_read_page(self):
        """Experimental: read a web page aloud. Preferred route: the user
        selects the page's URL (Ctrl+L in the address bar) and VoxFox fetches
        it — bus-independent and always explicit about which page is read
        (the title lands in the status line). Fallback: AT-SPI extraction of
        the focused browser tab. Stage 2 (Ollama) per Settings → Web page."""
        wr = self.state.get("webread", {})
        sel_url = vf.url_from_text(vf.get_selection())

        def refine_and_speak(text, title=""):
            if wr.get("use_ollama"):
                mode = wr.get("mode", "filter")
                msg = (_("Summarizing page with AI...") if mode == "summary"
                       else _("Filtering page with AI..."))
                GLib.idle_add(self.set_status, msg, 0)
                refined = vf.ollama_refine(
                    text, mode=mode,
                    url=wr.get("url") or vf.DEFAULT_OLLAMA_URL,
                    model=wr.get("model") or vf.DEFAULT_OLLAMA_MODEL,
                    api_key=wr.get("api_key") or None,
                    progress=lambda i, n: GLib.idle_add(
                        self.set_status, f"{msg} {i}/{n}", 0))
                if refined is None:
                    GLib.idle_add(self.set_status,
                                  _("Ollama not reachable — reading the "
                                    "unfiltered text"), 4000)
                elif not refined.strip():
                    GLib.idle_add(self.set_status,
                                  _("Nothing left to read after filtering"))
                    return
                else:
                    text = refined
            GLib.idle_add(self._after_page_text, text, title)

        if sel_url:
            self.set_status(f"{_('Fetching page...')} {sel_url[:70]}",
                            duration=0)

            def worker_url():
                text, title, err = vf.fetch_page_text(sel_url)
                if not text and vf.headless_available():
                    # JS-rendered page or bot wall: retry with a real
                    # (headless) browser before giving up.
                    GLib.idle_add(self.set_status,
                                  _("Opening the page in a background "
                                    "browser..."), 0)
                    text, title, err2 = vf.fetch_page_text_headless(sel_url)
                    if not text and err2 != "no-browser":
                        err = f"{err}, {err2}"
                if not text:
                    detail = f" ({err})" if err else ""
                    GLib.idle_add(self.set_status,
                                  _("Could not fetch a readable page from "
                                    "the selected address") + detail, 6000)
                    return
                refine_and_speak(text, title)
            threading.Thread(target=worker_url, daemon=True).start()
            return

        # No URL selected → AT-SPI fallback (needs a working bus).
        if not vf.a11y_bus_reachable():
            self.set_status(
                _("Select the page's address first (Ctrl+L in the browser), "
                  "then press the shortcut again"), duration=6000)
            return
        self.set_status(_("Extracting page text..."), duration=0)

        def worker_atspi():
            text, err = vf.extract_page_text()
            if not text:
                GLib.idle_add(
                    self.set_status,
                    _("No web page found — focus a browser tab and make sure "
                      "accessibility is on (Chromium needs "
                      "--force-renderer-accessibility)"), 6000)
                return
            refine_and_speak(text)
        threading.Thread(target=worker_atspi, daemon=True).start()

    def _after_page_text(self, text, title=""):
        if vf.merge_enabled():
            text = vf.merge_wrapped_lines(text)
        vf.add_history("read", text)
        threading.Thread(target=vf.speak, args=(text, self._active_cfg()),
                         daemon=True).start()
        self._sync_pause_btn()
        status = _("Reading...")
        if title:
            status = f"{status} — {title[:60]}"
        self.set_status(status, 4000)

    def do_ocr_select(self):
        tess = vf._tess_lang(self._active_cfg().get("lang", ""))
        self.set_status(_("Select a region..."), duration=0)

        def worker():
            tmp = None
            try:
                os.makedirs(vf.CACHE_DIR, exist_ok=True)
                fd, tmp = tempfile.mkstemp(suffix=".png", dir=vf.CACHE_DIR)
                os.close(fd)
                ok, err = _grab_region_to_file(tmp)
                if not ok:
                    GLib.idle_add(self.set_status, err)
                    return
                GLib.idle_add(self.set_status, _("Reading text..."), 0)
                text, oerr = vf.ocr_image(tmp, tess_lang=tess)
                GLib.idle_add(self._after_ocr, text, oerr)
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _run_ocr_path(self, path):
        tess = vf._tess_lang(self._active_cfg().get("lang", ""))
        self.set_status(_("Reading text..."), duration=0)

        def worker():
            text, err = vf.ocr_file(
                path, tess_lang=tess,
                progress_cb=lambda m: self.root.after(0, self.set_status, m, 0))
            self.root.after(0, self._after_ocr, text, err)
        threading.Thread(target=worker, daemon=True).start()

    def _after_ocr(self, text, err):
        if err:
            self.set_status(err)
            return
        if not text or not text.strip():
            self.set_status(_("No text found"))
            return
        vf.add_history("read", text)
        threading.Thread(target=vf.speak, args=(text, self._active_cfg()),
                         daemon=True).start()
        self._sync_pause_btn()
        self.set_status(_("Reading..."), 1500)

    def do_ocr_select_translate(self):
        """Like Select (OCR), but translates the recognised text into the
        UI language before reading it aloud — for text that is not
        selectable (images, scanned pages, video subtitles) in another
        language. Shortcut-only, like live transcription: no toolbar
        button, since Select already has one and this is a variant of it,
        not a separate everyday action."""
        tess = vf._tess_lang(self._active_cfg().get("lang", ""))
        self.set_status(_("Select a region..."), duration=0)

        def worker():
            tmp = None
            try:
                os.makedirs(vf.CACHE_DIR, exist_ok=True)
                fd, tmp = tempfile.mkstemp(suffix=".png", dir=vf.CACHE_DIR)
                os.close(fd)
                ok, err = _grab_region_to_file(tmp)
                if not ok:
                    GLib.idle_add(self.set_status, err)
                    return
                GLib.idle_add(self.set_status, _("Reading text..."), 0)
                text, oerr = vf.ocr_image(tmp, tess_lang=tess)
                GLib.idle_add(self._after_ocr_translate, text, oerr)
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _after_ocr_translate(self, text, err):
        if err:
            self.set_status(err)
            return
        if not text or not text.strip():
            self.set_status(_("No text found"))
            return
        self.set_status(_("Translating..."), duration=0)

        def worker():
            def prog(i, n):
                if n > 1:
                    GLib.idle_add(lambda: (self.set_status(
                        f"{_('Translating...')} {i}/{n}", duration=0),
                        False)[1])
            out, terr = vf.translate_text(
                text, self.state.get("translate", {}), progress=prog)

            def done():
                if terr or not out:
                    self.set_status(f"{_('Translation failed')}: {terr}"
                                    if terr else _("Translation failed"))
                    return False
                cfg = self.state["slot1"]
                vf.add_history("translate", out)
                threading.Thread(target=vf.speak, args=(out, cfg),
                                 daemon=True).start()
                self._sync_pause_btn()
                self.set_status(_("Reading translation..."), 1500)
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def do_hover(self):
        """Toggle hover-to-read. Mirrors the Tk build: an AT-SPI focus-event
        listener plus a polling fallback, controlled via vf.set_hover_running()."""
        if vf.IS_WAYLAND:
            # Reading the mouse position outside our own window is an X11
            # thing; Wayland's security model doesn't let any app query it.
            # There's no missing dependency that would fix this, so refuse
            # cleanly here -- reachable via IPC/CLI too, not just the
            # toolbar button, so this guard has to live here, not just in
            # whether the button is shown.
            self.set_status(
                _("Hover reading isn't available on Wayland — it needs "
                  "the mouse position outside VoxFox's own window, which "
                  "Wayland doesn't allow apps to read. Try Select or Read "
                  "instead."),
                duration=6000)
            return
        if self.hover_on:
            vf.set_hover_running(False)
            self.hover_on = False
            self.hover_btn.remove_css_class("voxfox-accent")
            threading.Thread(target=vf._stop_event_listener, daemon=True).start()
            self.set_status(_("Hover off"))
        else:
            # Reading other apps over AT-SPI means calling into pyatspi/libatspi.
            # On a broken or permission-denied bus that call aborts the whole
            # process, so refuse up front when the bus can't be reached.
            if not vf.a11y_bus_reachable():
                self.set_status(
                    _("Accessibility bus unavailable — hover reading can't "
                      "start. Enable accessibility, then log out and back in."),
                    duration=6000)
                return
            vf.set_hover_running(True)
            self.hover_on = True
            self.hover_btn.add_css_class("voxfox-accent")
            self.set_status(_("Hover on"))
            threading.Thread(target=vf._start_event_listener, daemon=True).start()
            threading.Thread(target=vf.hover_loop, daemon=True).start()

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
        srv = getattr(self.get_application(), "ipc_server", None)
        if srv:
            try:
                srv.stop()
            except Exception:
                pass



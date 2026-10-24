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

"""voxfox_ui.main_window.layout

Building the window: the toolbar buttons, their layout and size,
tooltips and labels that change.
"""

import os
import threading
import subprocess

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import TOOLBAR_BUTTONS, TOOLBAR_SHORTCUTS, TOOLBAR_DEFAULT_HIDDEN, TOOLBAR_IDS, UI_ORIENTS, UI_VIEWS, register_icon_path  # noqa: E402
from voxfox_ui.setup import SetupDialog  # noqa: E402
from voxfox_ui.shortcuts import SHORTCUT_ACTIONS, binding_display, binding_for  # noqa: E402
from voxfox_ui.widgets import set_accessible_label, btn_make_content, btn_set_text, scale_css  # noqa: E402


class LayoutMixin:
    """Building the window: the toolbar buttons, their layout and size,
    tooltips and labels that change.
    """

    def _load_scale_css(self):
        """(Re)load the scale provider from the scale stored in ui_layout."""
        scale = (self.state.get("ui_layout") or {}).get("scale",
                                                         vf.DEFAULT_UI_SCALE)
        if scale not in vf.UI_SCALES:
            scale = vf.DEFAULT_UI_SCALE
        try:
            self._scale_provider.load_from_data(scale_css(scale))
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
        cont.append(self._col_menu)
        self._col_sep.set_visible(slim)
        self._col_menu.set_visible(slim)

        # 4. Slim header: only the logo (keeps the drag area), no name; the
        # normal header returns as soon as we leave the slim mode.
        try:
            if slim:
                # An empty title collapses the title area; only the close
                # button remains, so the header adds no width of its own.
                self._header.set_title_widget(Gtk.Label(label=""))
                self._header.set_decoration_layout(":close")
                self._header_menu.set_visible(False)
            else:
                if self._header_title is None:
                    self._header_title = Gtk.Label(label="VoxFox")
                    self._header_title.add_css_class("title")
                self._header.set_title_widget(self._header_title)
                self._header.set_decoration_layout(":minimize,close")
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
        """Shrink the window to the toolbar's current natural size. GTK4
        doesn't auto-shrink a window when its content gets smaller (after
        lowering the UI scale or hiding buttons), so we nudge it back to the
        computed w, h below: via wmctrl when we have an X server
        (best-effort, external tool), or via GTK4's own
        set_default_size(w, h) on a plain Wayland window, where wmctrl
        cannot reach us. The window stays resizable; this only removes
        leftover empty space. With keep_width=True only the height shrinks
        back (used after the status line hides), so a user-widened window
        keeps its width."""

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

            if not vf.is_x11_client():
                # set_default_size() is a GTK call and must happen on the
                # main thread (unlike the wmctrl subprocess below, which is
                # safe to run in a background thread since it never touches
                # GTK directly) -- called straight from do_fit(), which
                # itself already runs on the main thread via GLib.timeout_add.
                try:
                    self.set_default_size(w, h)
                    self.queue_resize()
                except Exception as e:
                    log.debug(f"fit-to-content (Wayland) failed: {e}")
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
        btn_make_content(self.switch_btn, "switch", "")
        self.switch_btn.set_tooltip_text(_("Switch to the other language"))
        set_accessible_label(self.switch_btn, _("Switch language slot"))
        self.switch_btn.connect("clicked", lambda *_a: self.do_toggle_slot())

        self._header = header
        self._header_title = None
        # One menu for everything that is not a toolbar button. It used to be
        # two buttons side by side (a gear for Settings and this menu), which
        # made people guess where something was; Settings is now the first
        # item here. Sections are drawn with a line between them.
        menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append(_("Settings"), "app.preferences")
        menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append(_("Type and speak"), "app.type_speak")
        sec.append(_("Library"), "app.library")
        sec.append(_("History"), "app.history")
        sec.append(_("Live transcription"), "app.live_transcribe")
        menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append(_("Setup assistant…"), "app.first_run")
        sec.append(_("About VoxFox"), "app.about")
        menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append(_("Quit"), "app.quit")
        menu.append_section(None, sec)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        menu_btn.set_tooltip_text(_("Menu"))
        set_accessible_label(menu_btn, _("Menu"))
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
        set_accessible_label(setup_btn, _("Install Piper and components now"))
        setup_btn.connect("clicked", lambda *_a: SetupDialog(self).present())
        self.setup_bar.append(lbl)
        self.setup_bar.append(setup_btn)
        outer.append(self.setup_bar)

        # ── Modular toolbar (3.0) ────────────────────────────────────────────
        # The seven action buttons, shown and ordered per the user's ui_layout.
        # All seven are always instantiated (other code refers to self.read_btn,
        # self.whisper_btn, ...), but only the enabled ones are packed, in the
        # chosen order. The language switcher is fixed and always shown last.
        register_icon_path()
        self._toolbar_btns = {}
        for bid, attr, label, tip, a11y_lbl, handler, css in TOOLBAR_BUTTONS:
            btn = Gtk.Button()
            btn_make_content(btn, bid, _(label))
            btn.set_tooltip_text(_(tip))
            set_accessible_label(btn, _(a11y_lbl))
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
        self._col_menu = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                        menu_model=self._menu_model)
        self._col_menu.set_tooltip_text(_("Menu"))
        set_accessible_label(self._col_menu, _("Menu"))

        outer.append(toolbar)

        # How far reading has got. Only shown while a longer text is being
        # read; a sentence or two is over before a bar would mean anything.
        self.reading_bar = Gtk.ProgressBar()
        self.reading_bar.add_css_class("voxfox-reading")
        self.reading_bar.set_visible(False)
        set_accessible_label(self.reading_bar, _("Reading progress"))
        outer.append(self.reading_bar)
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
        self._refresh_tooltips()
        self._read_btn_mode = None   # new buttons: let the tick set them
        if not getattr(self, "_reading_tick_id", None):
            self._reading_tick_id = GLib.timeout_add(250, self._tick_reading)

    def refresh_setup_bar(self):
        self.setup_bar.set_visible(not os.path.exists(vf.PIPER_BIN))

    def reload_active_controls(self):
        """Re-sync the title-bar slot indicator and setup banner from state
        (called after the Settings window changes things)."""
        self._sync_switch_btn()
        self.refresh_setup_bar()
        self._refresh_tooltips()

    def _refresh_tooltips(self):
        """Plain-language tooltip per button, with its keyboard shortcut
        when one is set ("Reads the text you selected aloud (Super+Z)")."""
        defaults = {key: default for key, _n, _c, default in SHORTCUT_ACTIONS}
        tips = {bid: tip for bid, _a, _l, tip, *_rest in TOOLBAR_BUTTONS}
        tips["switch"] = "Switch to the other language"
        for bid, btn in getattr(self, "_toolbar_btns", {}).items():
            text = _(tips.get(bid, ""))
            action = TOOLBAR_SHORTCUTS.get(bid)
            if action:
                key = binding_display(binding_for(self.state, action,
                                                    defaults.get(action, "")))
                if key:
                    text = f"{text} ({key})"
            btn.set_tooltip_text(text)

    def _sync_switch_btn(self):
        try:
            btn_set_text(self.switch_btn, 
                vf.piper_lang_short(self._active_cfg().get("lang", "")))
        except Exception:
            btn_set_text(self.switch_btn, "•")

    def _sync_pause_btn(self):
        btn_set_text(self.pause_btn,
                      _("Resume") if vf.is_paused() else _("Pause"))

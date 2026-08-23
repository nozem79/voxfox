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

"""voxfox_ui.preferences — The settings window.

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import TOOLBAR_BUTTONS, TOOLBAR_DEFAULT_HIDDEN, TOOLBAR_IDS  # noqa: E402
from voxfox_ui.setup import apply_ui_language  # noqa: E402
from voxfox_ui.shortcuts import _SHORTCUT_ACTIONS, _SHORTCUT_LABELS, _binding_display, _binding_for, _cinnamon_reload, _install_shortcuts  # noqa: E402
from voxfox_ui.widgets import _a11y, _dropdown, _dropdown_value, _hide_progress_bar, _set_dropdown_items, _set_progress_bar  # noqa: E402


class PreferencesWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title=_("Settings"), transient_for=win, modal=True)
        self.win   = win
        self.state = win.state
        self.set_default_size(460, 480)
        self._dl_cancellers = {}

        # Voice catalogue (cached online list); fall back gracefully offline.
        self.all_voices = {}
        try:
            self.all_voices = vf.fetch_voices() or {}
        except Exception as e:
            log.debug(f"fetch_voices failed: {e}")

        # Tabbed layout: each page is short and scrolls, so the window stays
        # usable on small screens.
        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)

        def _page(child):
            for m in ("top", "bottom", "start", "end"):
                getattr(child, f"set_margin_{m}")(14)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_vexpand(True)
            sw.set_child(child)
            return sw

        notebook.append_page(_page(self._slot_group("slot1", _("Language 1"))),
                             Gtk.Label(label=_("Language 1")))
        notebook.append_page(_page(self._slot_group("slot2", _("Language 2"))),
                             Gtk.Label(label=_("Language 2")))
        notebook.append_page(_page(self._whisper_group()),
                             Gtk.Label(label=_("Dictation")))
        notebook.append_page(_page(self._pronunciation_group()),
                             Gtk.Label(label=_("Pronunciation")))
        notebook.append_page(_page(self._shortcuts_group()),
                             Gtk.Label(label=_("Shortcuts")))
        notebook.append_page(_page(self._translate_group()),
                             Gtk.Label(label=_("Translation")))
        notebook.append_page(_page(self._webread_group()),
                             Gtk.Label(label=_("Web page")))
        notebook.append_page(_page(self._interface_group()),
                             Gtk.Label(label=_("Interface")))
        notebook.append_page(_page(self._misc_group()),
                             Gtk.Label(label=_("Misc")))
        self.set_child(notebook)

        self.connect("close-request", self._on_close)

    def _on_close(self, *_a):
        if getattr(self, "_shortcuts_inhibited", False):
            self._stop_capture()
        self._save_pron()
        self.win.reload_active_controls()
        return False

    # ── Interface: UI scale + modular toolbar (3.0) ──────────────────────────
    def _interface_group(self):
        layout = vf.reconcile_toolbar_layout(self.state.get("ui_layout"),
                                             TOOLBAR_IDS,
                                             TOOLBAR_DEFAULT_HIDDEN)
        self.state["ui_layout"] = layout

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        # Interface size: 75 / 100 / 125 % as a radio group.
        size_frame = Gtk.Frame(label=_("Interface size"))
        srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(srow, f"set_margin_{m}")(10)
        radios, leader = [], None
        for s in vf.UI_SCALES:
            rb = Gtk.CheckButton(label=f"{s}%")
            if leader is None:
                leader = rb
            else:
                rb.set_group(leader)
            radios.append((s, rb))
            srow.append(rb)
        for s, rb in radios:
            rb.set_active(s == layout["scale"])
        for s, rb in radios:
            rb.connect("toggled", self._on_scale_toggled, s)
        size_frame.set_child(srow)
        box.append(size_frame)

        # Button display: icons only / icon + text / text only.
        view_frame = Gtk.Frame(label=_("Button display"))
        vrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(vrow, f"set_margin_{m}")(10)
        view_labels = [("icons", _("Icon only")), ("both", _("Icon and text")),
                       ("text", _("Text only"))]
        vleader = None
        cur_view = self.state.get("ui_view", "both")
        for val, lbl in view_labels:
            rb = Gtk.CheckButton(label=lbl)
            if vleader is None:
                vleader = rb
            else:
                rb.set_group(vleader)
            rb.set_active(val == cur_view)
            rb.connect("toggled", self._on_view_toggled, val)
            vrow.append(rb)
        view_frame.set_child(vrow)
        box.append(view_frame)

        # Orientation: horizontal (rows) or vertical (a narrow column).
        or_frame = Gtk.Frame(label=_("Orientation"))
        orow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(orow, f"set_margin_{m}")(10)
        cur_or = self.state.get("ui_orientation", "horizontal")
        oleader = None
        for val, lbl in [("horizontal", _("Horizontal")),
                         ("vertical", _("Vertical"))]:
            rb = Gtk.CheckButton(label=lbl)
            if oleader is None:
                oleader = rb
            else:
                rb.set_group(oleader)
            rb.set_active(val == cur_or)
            rb.connect("toggled", self._on_orient_toggled, val)
            orow.append(rb)
        or_frame.set_child(orow)
        box.append(or_frame)

        # Buttons: per-button visibility toggle + up/down reordering.
        btn_frame = Gtk.Frame(label=_("Buttons"))
        self._iface_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=4)
        for m in ("top", "bottom", "start", "end"):
            getattr(self._iface_list, f"set_margin_{m}")(10)
        self._populate_button_list()
        btn_frame.set_child(self._iface_list)
        box.append(btn_frame)
        return box

    def _on_orient_toggled(self, rb, val):
        if not rb.get_active():
            return
        self.state["ui_orientation"] = val
        vf.save_state(self.state)
        self.win._apply_ui_mode()

    def _on_view_toggled(self, rb, val):
        if not rb.get_active():
            return
        self.state["ui_view"] = val
        vf.save_state(self.state)
        self.win._apply_ui_mode()

    def _on_scale_toggled(self, rb, scale):
        if rb.get_active():
            self.win.apply_ui_scale(scale)

    def _populate_button_list(self):
        # Clear current rows.
        child = self._iface_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._iface_list.remove(child)
            child = nxt
        labels = {b[0]: b[2] for b in TOOLBAR_BUTTONS}
        labels["switch"] = "Switch language"
        buttons = self.state["ui_layout"]["buttons"]
        if vf.IS_WAYLAND:
            # Hover mode can't work under Wayland (see do_hover()); don't
            # even list a checkbox for it here, since toggling it "on"
            # wouldn't do anything -- the toolbar filters it out regardless.
            buttons = [e for e in buttons if e["id"] != "hover"]
        n = len(buttons)
        for i, entry in enumerate(buttons):
            bid = entry["id"]
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            chk = Gtk.CheckButton(label=_(labels.get(bid, bid)))
            chk.set_active(entry["visible"])
            chk.set_hexpand(True)
            chk.connect("toggled", self._on_btn_visible, bid)
            up = Gtk.Button(icon_name="go-up-symbolic")
            up.set_tooltip_text(_("Move up"))
            up.set_sensitive(i > 0)
            up.connect("clicked", self._on_btn_move, bid, -1)
            down = Gtk.Button(icon_name="go-down-symbolic")
            down.set_tooltip_text(_("Move down"))
            down.set_sensitive(i < n - 1)
            down.connect("clicked", self._on_btn_move, bid, 1)
            row.append(chk)
            row.append(up)
            row.append(down)
            self._iface_list.append(row)

    def _on_btn_visible(self, chk, bid):
        for e in self.state["ui_layout"]["buttons"]:
            if e["id"] == bid:
                e["visible"] = chk.get_active()
                break
        vf.save_state(self.state)
        self.win.rebuild_ui()

    def _on_btn_move(self, _btn, bid, delta):
        buttons = self.state["ui_layout"]["buttons"]
        idx = next((i for i, e in enumerate(buttons) if e["id"] == bid), None)
        if idx is None:
            return
        new = idx + delta
        if new < 0 or new >= len(buttons):
            return
        buttons[idx], buttons[new] = buttons[new], buttons[idx]
        vf.save_state(self.state)
        self._populate_button_list()
        self.win.rebuild_ui()

    # ── Shortcuts: per-action key capture + one-shot install (3.3) ───────────
    def _shortcuts_group(self):
        self._capturing_key = None
        self._capture_btns = {}
        self._shortcuts_inhibited = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_text(_("Click a shortcut and press the key combination you "
                         "want. Then choose Install shortcuts to register them "
                         "with your desktop. Nothing is installed automatically."))
        box.append(intro)

        frame = Gtk.Frame(label=_("Shortcuts"))
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top", "bottom", "start", "end"):
            getattr(rows, f"set_margin_{m}")(10)

        for key, _label, _cmd, default in _SHORTCUT_ACTIONS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            name = Gtk.Label(label=_(_SHORTCUT_LABELS.get(key, key)), xalign=0)
            name.set_hexpand(True)
            row.append(name)

            cap = Gtk.Button(label=_binding_display(
                _binding_for(self.state, key, default)))
            cap.set_size_request(140, -1)
            cap.connect("clicked", self._on_capture_clicked, key)
            ctrl = Gtk.EventControllerKey()
            # CAPTURE phase: intercept keys before the button activates on Space.
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", self._on_capture_key, key, cap)
            cap.add_controller(ctrl)
            self._capture_btns[key] = cap
            row.append(cap)
            rows.append(row)

        frame.set_child(rows)
        box.append(frame)

        # Action row: reset + install, with a result label.
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset = Gtk.Button(label=_("Reset to defaults"))
        reset.connect("clicked", self._on_shortcuts_reset)
        install = Gtk.Button(label=_("Install shortcuts"))
        install.add_css_class("suggested-action")
        install.connect("clicked", self._on_shortcuts_install)
        actions.append(reset)
        actions.append(install)
        box.append(actions)

        self._shortcut_result = Gtk.Label(xalign=0, wrap=True)
        box.append(self._shortcut_result)
        return box

    def _begin_capture(self, key, btn):
        # Stop any capture already running on another row.
        if self._capturing_key and self._capturing_key != key:
            prev = self._capture_btns.get(self._capturing_key)
            if prev:
                self._refresh_capture_label(self._capturing_key, prev)
        self._capturing_key = key
        btn.set_label(_("Press keys…"))
        btn.add_css_class("suggested-action")
        btn.grab_focus()
        # Ask the compositor/WM to deliver system-grabbed combinations to this
        # window during capture, so a key that is already a global shortcut can
        # still be recorded here (otherwise the WM swallows it and we never see
        # the press). Best-effort: a no-op where the backend doesn't support it.
        try:
            surface = self.get_surface()
            if surface is not None and not self._shortcuts_inhibited:
                surface.inhibit_system_shortcuts(None)
                self._shortcuts_inhibited = True
        except Exception as e:
            log.debug(f"inhibit_system_shortcuts failed: {e}")

    def _stop_capture(self):
        self._capturing_key = None
        if self._shortcuts_inhibited:
            try:
                surface = self.get_surface()
                if surface is not None:
                    surface.restore_system_shortcuts()
            except Exception as e:
                log.debug(f"restore_system_shortcuts failed: {e}")
            self._shortcuts_inhibited = False

    def _refresh_capture_label(self, key, btn):
        default = next((d for k, _l, _c, d in _SHORTCUT_ACTIONS if k == key), "")
        btn.set_label(_binding_display(_binding_for(self.state, key, default)))
        btn.remove_css_class("suggested-action")

    def _on_capture_clicked(self, btn, key):
        self._begin_capture(key, btn)

    def _on_capture_key(self, _ctrl, keyval, _keycode, gtk_state, key, btn):
        if self._capturing_key != key:
            return False
        if keyval == Gdk.KEY_Escape:                 # cancel
            self._stop_capture()
            self._refresh_capture_label(key, btn)
            return True
        # Ignore bare modifier presses — wait for a real key.
        if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L,
                      Gdk.KEY_Alt_R, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
                      Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L,
                      Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift):
            return True
        mods = gtk_state & Gtk.accelerator_get_default_mod_mask()
        if not Gtk.accelerator_valid(keyval, mods):
            return True                              # not usable yet
        binding = Gtk.accelerator_name(keyval, mods)
        # Reject a combination already assigned to another VoxFox action, so two
        # actions can't fight over the same key.
        for k, _l, _c, d in _SHORTCUT_ACTIONS:
            if k != key and _binding_for(self.state, k, d) == binding:
                self._stop_capture()
                self._refresh_capture_label(key, btn)
                self._shortcut_result.set_text(
                    _("That key combination is already used by another "
                      "VoxFox shortcut."))
                return True
        self.state.setdefault("shortcut_bindings", {})[key] = binding
        vf.save_state(self.state)
        self._stop_capture()
        btn.set_label(_binding_display(binding))
        btn.remove_css_class("suggested-action")
        self._shortcut_result.set_text("")
        return True

    def _on_shortcuts_reset(self, _btn):
        self._stop_capture()
        self.state["shortcut_bindings"] = {}
        vf.save_state(self.state)
        for key, cap in self._capture_btns.items():
            self._refresh_capture_label(key, cap)
        self._shortcut_result.set_text(_("Shortcuts reset to defaults."))

    def _on_shortcuts_install(self, _btn):
        conflicts = []
        try:
            ok = _install_shortcuts(self.state, conflicts)
        except Exception as e:
            log.debug(f"install shortcuts (settings) failed: {e}")
            ok = False
        vf.save_state(self.state)
        if ok:
            if _cinnamon_reload():
                msg = _("Shortcuts installed. The desktop was reloaded to "
                       "activate them.")
            else:
                msg = _("Shortcuts installed. You can change or remove them "
                       "in your system keyboard settings.")
        else:
            msg = _("Could not install shortcuts on this desktop. Your "
                   "desktop may use a different method — set them manually "
                   "in its keyboard settings.")
        if conflicts:
            lines = [_("{action} ({key}) conflicts with: {owner}").format(
                        action=_(_SHORTCUT_LABELS.get(k, k)),
                        key=_binding_display(binding), owner=owner)
                     for (k, binding, owner) in conflicts]
            msg += ("\n\n" + _("Some shortcuts could not be installed "
                               "because the key is already in use:")
                    + "\n" + "\n".join(lines))
        self._shortcut_result.set_text(msg)

    # ── per-slot language + voice + speed ────────────────────────────────────
    def _slot_group(self, slot, title):
        cfg = self.state[slot]
        frame = Gtk.Frame(label=title)
        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(10)
        frame.set_child(grid)

        langs = vf.get_languages(self.all_voices)
        if not langs and cfg.get("lang"):
            langs = [cfg["lang"]]
        lang_dd = _dropdown(langs, cfg.get("lang", ""))
        _a11y(lang_dd, f"{title} — {_('Language')}")

        voices = sorted(vf.get_voices_for_lang(self.all_voices, cfg.get("lang", "")))
        if not voices:
            voices = sorted(v for v in vf.get_local_voices())
        voice_dd = _dropdown(voices, cfg.get("voice", ""))
        _a11y(voice_dd, f"{title} — {_('Voice')}")

        status = Gtk.Label(xalign=0.0)
        status.add_css_class("dim-label")

        grid.attach(Gtk.Label(label=_("Language:"), xalign=0), 0, 0, 1, 1)
        grid.attach(lang_dd, 1, 0, 1, 1)
        lang_dd.set_hexpand(True)
        grid.attach(Gtk.Label(label=_("Voice:"), xalign=0), 0, 1, 1, 1)
        grid.attach(voice_dd, 1, 1, 1, 1)
        grid.attach(status, 0, 2, 2, 1)

        speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.5, 2.0, 0.05)
        speed.set_value(float(cfg.get("speed", 1.0)))
        speed.set_hexpand(True)
        speed.set_draw_value(True)
        grid.attach(Gtk.Label(label=_("Speed:"), xalign=0), 0, 3, 1, 1)
        grid.attach(speed, 1, 3, 1, 1)
        _a11y(speed, _("Speed:").rstrip(": "))

        # Pitch in semitones: 0 = the voice's natural pitch, negative = lower,
        # positive = higher. Applied in the speech worker by playing at a shifted
        # sample rate and compensating the tempo via Piper's length_scale, so the
        # speaking rate above is unaffected.
        pitch = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -12, 12, 1)
        pitch.set_value(float(cfg.get("pitch", 0.0)))
        pitch.set_hexpand(True)
        pitch.set_draw_value(True)
        grid.attach(Gtk.Label(label=_("Pitch:"), xalign=0), 0, 4, 1, 1)
        grid.attach(pitch, 1, 4, 1, 1)
        _a11y(pitch, _("Pitch:").rstrip(": "))

        def on_lang(dd, _p):
            lang = _dropdown_value(dd)
            cfg["lang"] = lang
            keys = sorted(vf.get_voices_for_lang(self.all_voices, lang))
            local = vf.get_local_voices()
            chosen = next((k for k in keys if k in local),
                          keys[0] if keys else "")
            cfg["voice"] = chosen
            vf.save_state(self.state)
            _set_dropdown_items(voice_dd, keys, chosen)
            if slot == "slot1":
                apply_ui_language(lang)
                self.win.rebuild_ui()

        def on_voice(dd, _p):
            voice = _dropdown_value(dd)
            if not voice:
                return
            cfg["voice"] = voice
            vf.save_state(self.state)
            if voice not in vf.get_local_voices():
                self._download_voice_async(slot, voice, status)
            else:
                status.set_text("")

        def on_speed(sc):
            cfg["speed"] = round(sc.get_value(), 2)
            vf.save_state(self.state)

        def on_pitch(sc):
            cfg["pitch"] = round(sc.get_value(), 1)
            vf.save_state(self.state)

        lang_dd.connect("notify::selected", on_lang)
        voice_dd.connect("notify::selected", on_voice)
        speed.connect("value-changed", on_speed)
        pitch.connect("value-changed", on_pitch)
        return frame

    def _download_voice_async(self, slot, voice, status_label):
        prev = self._dl_cancellers.get(slot)
        if prev is not None:
            prev.set()
        cancel = threading.Event()
        self._dl_cancellers[slot] = cancel

        def worker():
            GLib.idle_add(status_label.set_text, f"⬇ {voice}...")
            ok, msg = vf.download_voice(voice, cancel_evt=cancel)
            def done():
                if ok:
                    status_label.set_text(f"✓ {voice}")
                elif msg != "cancelled":
                    status_label.set_text(f"✗ {msg}")
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    # ── Whisper: model + mic + confirm + backend + remote API ────────────────
    def _whisper_group(self):
        w = self.state["whisper"]
        frame = Gtk.Frame(label=_("Whisper (speech-to-text)"))
        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(10)
        frame.set_child(grid)
        r = 0

        # Model + download
        grid.attach(Gtk.Label(label=_("Model:"), xalign=0), 0, r, 1, 1)
        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.model_dd = _dropdown(vf.WHISPER_MODELS, w.get("model", "small"))
        self.model_dd.set_hexpand(True)
        _a11y(self.model_dd, _("Whisper model"))
        self.model_dd.connect("notify::selected", self._on_model_changed)
        dl_btn = Gtk.Button(icon_name="document-save-symbolic")
        dl_btn.set_tooltip_text(_("Download the selected model now"))
        _a11y(dl_btn, _("Download the selected Whisper model"))
        dl_btn.connect("clicked", self._on_model_download)
        model_box.append(self.model_dd)
        model_box.append(dl_btn)
        grid.attach(model_box, 1, r, 1, 1)
        self.model_status = Gtk.Label(xalign=0.0)
        self.model_status.add_css_class("dim-label")
        grid.attach(self.model_status, 0, r + 1, 2, 1)
        # Download progress for the model button, just below the status text.
        self.dl_progress = Gtk.ProgressBar(show_text=True)
        self.dl_progress.set_visible(False)
        grid.attach(self.dl_progress, 0, r + 2, 2, 1)
        self._refresh_model_status()
        r += 3

        # Compute device (Auto detects an NVIDIA GPU, else CPU).
        grid.attach(Gtk.Label(label=_("Compute:"), xalign=0), 0, r, 1, 1)
        dev = w.get("device", "auto")
        self._dev_values = ["auto", "cpu", "cuda"]
        dev_labels = [_("Auto (GPU if available)"), _("CPU"), _("GPU (NVIDIA)")]
        self.dev_dd = _dropdown(
            dev_labels, dev_labels[self._dev_values.index(dev)]
            if dev in self._dev_values else dev_labels[0])
        self.dev_dd.set_hexpand(True)
        _a11y(self.dev_dd, _("Compute device"))
        self.dev_dd.set_tooltip_text(
            _("Auto uses an NVIDIA GPU when detected (needs CUDA + cuDNN), "
              "otherwise the CPU. Falls back to CPU if GPU init fails."))
        self.dev_dd.connect("notify::selected", self._on_device_changed)
        grid.attach(self.dev_dd, 1, r, 1, 1)
        self.dev_status = Gtk.Label(xalign=0.0)
        self.dev_status.add_css_class("dim-label")
        self.dev_status.set_text(
            _("NVIDIA GPU detected") if vf._cuda_available()
            else _("no GPU detected — using CPU"))
        grid.attach(self.dev_status, 0, r + 1, 2, 1)
        r += 2

        # Microphone + refresh
        grid.attach(Gtk.Label(label=_("Mic:"), xalign=0), 0, r, 1, 1)
        mic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._mic_options = vf.list_microphones()
        self._mic_labels  = [lbl for (_id, lbl) in self._mic_options]
        cur_id = w.get("mic_id", "")
        cur_lbl = next((lbl for (mid, lbl) in self._mic_options if mid == cur_id),
                       self._mic_labels[0] if self._mic_labels else _("Default"))
        self.mic_dd = _dropdown(self._mic_labels, cur_lbl)
        self.mic_dd.set_hexpand(True)
        _a11y(self.mic_dd, _("Microphone"))
        self.mic_dd.connect("notify::selected", self._on_mic_changed)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text(_("Refresh microphone list"))
        _a11y(refresh, _("Refresh microphone list"))
        refresh.connect("clicked", self._on_mic_refresh)
        mic_box.append(self.mic_dd)
        mic_box.append(refresh)
        grid.attach(mic_box, 1, r, 1, 1)
        r += 1

        # Confirm before typing
        confirm = Gtk.CheckButton(label=_("Confirm transcription before typing"))
        confirm.set_active(bool(w.get("confirm_before_typing", False)))
        confirm.connect("toggled", self._on_confirm_toggled)
        grid.attach(confirm, 0, r, 2, 1)
        r += 1

        # Maximum recording length — a safety net if dictation is left
        # running by accident (recording then auto-stops on its own).
        grid.attach(Gtk.Label(label=_("Max. recording length:"), xalign=0),
                   0, r, 1, 1)
        max_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.max_rec_spin = Gtk.SpinButton.new_with_range(10, 600, 10)
        self.max_rec_spin.set_value(
            w.get("max_record_seconds", vf.WHISPER_MAX_SECONDS))
        _a11y(self.max_rec_spin, _("Maximum recording length in seconds"))
        self.max_rec_spin.connect("value-changed",
                                 self._on_max_record_changed)
        max_box.append(self.max_rec_spin)
        max_box.append(Gtk.Label(label=_("seconds")))
        grid.attach(max_box, 1, r, 1, 1)
        r += 1
        max_hint = Gtk.Label(xalign=0.0, wrap=True)
        max_hint.add_css_class("dim-label")
        max_hint.set_text(
            _("Recording stops automatically after this long, even if "
              "Speak/Stop is never pressed again — a safety net if "
              "dictation is left running by accident."))
        grid.attach(max_hint, 0, r, 2, 1)
        r += 1

        # Backend
        grid.attach(Gtk.Label(label=_("Backend:"), xalign=0), 0, r, 1, 1)
        self.backend_dd = _dropdown([_("Local"), _("Remote API")],
                                    _("Remote API") if w.get("backend") == "remote"
                                    else _("Local"))
        self.backend_dd.connect("notify::selected", self._on_backend_changed)
        _a11y(self.backend_dd, _("Whisper backend"))
        grid.attach(self.backend_dd, 1, r, 1, 1)
        r += 1

        # Remote API rows (shown only when backend == remote)
        self.remote_box = Gtk.Grid(row_spacing=6, column_spacing=8)
        grid.attach(self.remote_box, 0, r, 2, 1)

        self.url_entry = Gtk.Entry(hexpand=True)
        self.url_entry.set_text(w.get("remote_url", ""))
        self.url_entry.set_placeholder_text("http://host:8000/v1")
        self.url_entry.connect("changed",
                               lambda e: self._save_w("remote_url", e.get_text()))
        self.rmodel_entry = Gtk.Entry(hexpand=True)
        self.rmodel_entry.set_text(w.get("remote_model", ""))
        self.rmodel_entry.connect("changed",
                                  lambda e: self._save_w("remote_model", e.get_text()))
        self.key_entry = Gtk.Entry(hexpand=True)
        self.key_entry.set_text(w.get("remote_api_key", ""))
        self.key_entry.set_visibility(False)
        self.key_entry.set_placeholder_text(_("optional"))
        self.key_entry.connect("changed",
                               lambda e: self._save_w("remote_api_key", e.get_text()))
        test_btn = Gtk.Button(label=_("Test connection"))
        test_btn.connect("clicked", self._on_test_remote)
        self.test_result_lbl = Gtk.Label(xalign=0.0)
        self.test_result_lbl.set_wrap(True)
        self.test_result_lbl.set_selectable(True)

        self.remote_box.attach(Gtk.Label(label=_("URL:"), xalign=0),    0, 0, 1, 1)
        self.remote_box.attach(self.url_entry,                           1, 0, 1, 1)
        self.remote_box.attach(Gtk.Label(label=_("Model:"), xalign=0),  0, 1, 1, 1)
        self.remote_box.attach(self.rmodel_entry,                        1, 1, 1, 1)
        self.remote_box.attach(Gtk.Label(label=_("API key:"), xalign=0), 0, 2, 1, 1)
        self.remote_box.attach(self.key_entry,                           1, 2, 1, 1)
        self.remote_box.attach(test_btn,                                 1, 3, 1, 1)
        self.remote_box.attach(self.test_result_lbl,                     0, 4, 2, 1)
        self.remote_box.set_visible(w.get("backend") == "remote")
        return frame

    def _save_w(self, key, value):
        self.state["whisper"][key] = value
        vf.save_state(self.state)

    def _on_max_record_changed(self, spin):
        self._save_w("max_record_seconds", int(spin.get_value()))

    def _refresh_model_status(self):
        name = _dropdown_value(self.model_dd)
        if vf._whisper_model_is_cached(name):
            self.model_status.set_text(f"✓ {_('model downloaded')}")
        else:
            self.model_status.set_text(_("model not downloaded yet"))

    def _on_model_changed(self, dd, _p):
        self._save_w("model", _dropdown_value(dd))
        self._refresh_model_status()

    # ── pronunciation dictionary (slot 1's language) ─────────────────────────
    def _pronunciation_group(self):
        frame = Gtk.Frame(label=_("Pronunciation dictionary"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.set_child(box)

        self._pron_lang = self.state["slot1"].get("lang", "")
        native = vf.piper_lang_native(self._pron_lang) or self._pron_lang or "?"
        info = Gtk.Label(xalign=0.0)
        info.set_wrap(True)
        info.add_css_class("dim-label")
        info.set_text(
            _("Rules for slot 1's language (%s). Words are matched whole and "
              "case-insensitively, then re-spelled before they are spoken.")
            % native)
        box.append(info)

        hint = Gtk.Label(xalign=0.0, wrap=True)
        hint.add_css_class("dim-label")
        hint.set_text(
            _("VoxFox also applies some pronunciation fixes automatically; "
              "add your own rule here to override one."))
        box.append(hint)

        self.pron_list = Gtk.ListBox()
        self.pron_list.set_selection_mode(Gtk.SelectionMode.NONE)
        box.append(self.pron_list)
        self._pron_rows = []

        existing = self.state.get("pronunciations", {}).get(self._pron_lang, {})
        for word, repl in existing.items():
            self._add_pron_row(word, repl)
        if not self._pron_rows:
            self._add_pron_row("", "")

        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label=_("Add rule"))
        add_btn.connect("clicked", lambda *_a: self._add_pron_row("", ""))
        btnrow.append(add_btn)
        imp = Gtk.Button(label=_("Import dictionary…"))
        imp.connect("clicked", self._on_dict_import)
        btnrow.append(imp)
        exp = Gtk.Button(label=_("Export dictionary…"))
        exp.connect("clicked", self._on_dict_export)
        btnrow.append(exp)
        box.append(btnrow)

        share = Gtk.Label(xalign=0.0)
        share.set_wrap(True)
        share.add_css_class("dim-label")
        share.set_text(_("Export your dictionary to share it, or import one "
                         "from another user or from voxfox.nl."))
        box.append(share)
        return frame

    # ── dictionary files: import / export ─────────────────────────────────
    def _on_dict_export(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Export dictionary…"), self, Gtk.FileChooserAction.SAVE,
            None, None)
        code = vf.ui_code_for_piper_lang(self._pron_lang)
        dlg.set_current_name(f"voxfox-dict-{code}.json")
        dlg.set_modal(True)
        dlg.connect("response", self._dict_export_response)
        self._file_dlg = dlg
        dlg.show()

    def _dict_export_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                self._save_pron()
                rules = self.state.get("pronunciations", {}).get(
                    self._pron_lang, {})
                vf.save_dict_file(path, self._pron_lang, rules)
                self.win.set_status(_("Dictionary exported"))
            except Exception as e:
                self.win.set_status(f"{_('Export failed')}: {e}")
        dlg.destroy()

    def _on_dict_import(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Import dictionary…"), self, Gtk.FileChooserAction.OPEN,
            None, None)
        dlg.set_modal(True)
        dlg.connect("response", self._dict_import_response)
        self._file_dlg = dlg
        dlg.show()

    def _dict_import_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            self._merge_dict_file(dlg.get_file().get_path())
        dlg.destroy()

    def _merge_dict_file(self, path):
        """Merge a dictionary file into the state. Rules land under the
        language named in the file (falling back to slot 1's language); new
        words are added and existing words are updated, and the visible list
        refreshes when the current language was affected."""
        try:
            file_lang, rules = vf.load_dict_file(path)
        except Exception:
            self.win.set_status(_("Not a valid VoxFox dictionary file"))
            return
        # Capture unsaved edits in the visible rows first.
        self._save_pron()
        target = file_lang if file_lang in vf.PIPER_LANG_TO_CODE \
            else self._pron_lang
        pron = self.state.setdefault("pronunciations", {})
        cur = pron.setdefault(target, {})
        new = sum(1 for k in rules if k not in cur)
        upd = sum(1 for k in rules if k in cur and cur[k] != rules[k])
        cur.update(rules)
        if not cur:
            del pron[target]
        vf.save_state(self.state)
        vf.set_pronunciations(pron)
        if target == self._pron_lang:
            self._reload_pron_rows()
        self.win.set_status(
            _("Dictionary loaded: %s new, %s updated") % (new, upd))

    def _reload_pron_rows(self):
        """Rebuild the rule list from the state (after an import)."""
        while True:
            row = self.pron_list.get_row_at_index(0)
            if row is None:
                break
            self.pron_list.remove(row)
        self._pron_rows = []
        existing = self.state.get("pronunciations", {}).get(self._pron_lang, {})
        for word, repl in existing.items():
            self._add_pron_row(word, repl)
        if not self._pron_rows:
            self._add_pron_row("", "")

    def _add_pron_row(self, word, repl):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        we = Gtk.Entry()
        we.set_placeholder_text(_("Word"))
        we.set_text(word)
        we.set_hexpand(True)
        rep = Gtk.Entry()
        rep.set_placeholder_text(_("Pronounce as"))
        rep.set_text(repl)
        rep.set_hexpand(True)
        rm = Gtk.Button(icon_name="user-trash-symbolic")
        rm.set_tooltip_text(_("Remove rule"))
        test = Gtk.Button(icon_name="media-playback-start-symbolic")
        test.set_tooltip_text(_("Test this word"))
        _a11y(we, _("Word"))
        _a11y(rep, _("Pronounce as"))
        _a11y(rm, _("Remove rule"))
        _a11y(test, _("Test this word"))
        row.append(we)
        row.append(Gtk.Label(label="→"))
        row.append(rep)
        row.append(test)
        row.append(rm)
        lbrow = Gtk.ListBoxRow()
        lbrow.set_child(row)
        rec = {"word": we, "repl": rep, "lbrow": lbrow}

        def _test_one(*_a):
            txt = rep.get_text().strip() or we.get_text().strip()
            if txt:
                threading.Thread(target=vf.speak,
                                 args=(txt, self.state["slot1"]),
                                 daemon=True).start()
        test.connect("clicked", _test_one)

        def _remove(*_a):
            self.pron_list.remove(lbrow)
            if rec in self._pron_rows:
                self._pron_rows.remove(rec)
            self._save_pron()
        rm.connect("clicked", _remove)
        self.pron_list.append(lbrow)
        self._pron_rows.append(rec)

    def _collect_pron(self):
        d = {}
        for rec in self._pron_rows:
            w = rec["word"].get_text().strip()
            r = rec["repl"].get_text().strip()
            if w and r:
                d[w] = r
        return d

    def _save_pron(self):
        if not hasattr(self, "_pron_rows"):
            return
        d = self._collect_pron()
        pron = self.state.setdefault("pronunciations", {})
        if d:
            pron[self._pron_lang] = d
        elif self._pron_lang in pron:
            del pron[self._pron_lang]
        vf.save_state(self.state)
        vf.set_pronunciations(pron)

    # ── misc: line merging + import/export ───────────────────────────────────
    def _misc_group(self):
        frame = Gtk.Frame(label=_("Misc"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)

        self.merge_chk = Gtk.CheckButton(
            label=_("Merge wrapped lines into paragraphs"))
        self.merge_chk.set_active(bool(self.state.get("merge_lines", True)))
        self.merge_chk.connect("toggled", self._on_merge_toggled)
        box.append(self.merge_chk)

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("When reading OCR or selected text, join lines that are "
                        "only word-wrapped and pause only at real paragraphs. "
                        "Turn off to read every line separately (lists, code)."))
        box.append(desc)

        box.append(Gtk.Separator())

        slabel = Gtk.Label(xalign=0.0, label=_("Settings file"))
        box.append(slabel)
        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        imp = Gtk.Button(label=_("Import settings…"))
        imp.connect("clicked", self._on_import)
        exp = Gtk.Button(label=_("Export settings…"))
        exp.connect("clicked", self._on_export)
        btnrow.append(imp)
        btnrow.append(exp)
        box.append(btnrow)
        return frame

    def _webread_group(self):
        """Experimental 'read web page' settings: stage 1 (AT-SPI extraction)
        is always on; here the user configures stage 2 (Ollama) — off, filter
        (keep original sentences) or summarize — plus the server URL/model."""
        frame = Gtk.Frame(label=_("Web page"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)
        wr = self.state.setdefault("webread", {})

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("Reads a web page aloud (experimental). Select the "
                        "page's address (Ctrl+L in the browser) and press the "
                        "shortcut — VoxFox fetches the page itself. Menus, "
                        "banners and sidebars are always skipped; optionally "
                        "an AI (Ollama) filters the remaining text further or "
                        "summarizes it."))
        box.append(desc)

        self.webread_ai_chk = Gtk.CheckButton(
            label=_("Use AI (Ollama) to clean up the page text"))
        self.webread_ai_chk.set_active(bool(wr.get("use_ollama")))
        self.webread_ai_chk.connect("toggled", self._on_webread_changed)
        box.append(self.webread_ai_chk)

        # Everything below only matters once "Use AI" is on -- collapsed
        # into one box so it can be shown/hidden as a unit instead of
        # cluttering the tab with irrelevant fields when AI mode is off.
        self.webread_ai_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.webread_ai_box.set_visible(bool(wr.get("use_ollama")))
        box.append(self.webread_ai_box)

        mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mrow.append(Gtk.Label(label=_("AI mode:"), xalign=0))
        self.webread_mode_dd = Gtk.DropDown.new_from_strings(
            [_("Filter only (keep the original sentences)"), _("Summarize")])
        self.webread_mode_dd.set_selected(
            1 if wr.get("mode") == "summary" else 0)
        self.webread_mode_dd.connect("notify::selected",
                                     self._on_webread_changed)
        mrow.append(self.webread_mode_dd)
        self.webread_ai_box.append(mrow)

        urow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        urow.append(Gtk.Label(label=_("URL:"), xalign=0))
        self.webread_url = Gtk.Entry(hexpand=True)
        self.webread_url.set_text(wr.get("url") or vf.DEFAULT_OLLAMA_URL)
        self.webread_url.connect("changed", self._on_webread_changed)
        urow.append(self.webread_url)
        self.webread_ai_box.append(urow)

        krow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        krow.append(Gtk.Label(label=_("API key:"), xalign=0))
        self.webread_key = Gtk.Entry(hexpand=True)
        self.webread_key.set_visibility(False)
        self.webread_key.set_text(wr.get("api_key") or "")
        self.webread_key.set_placeholder_text(_("optional"))
        self.webread_key.connect("changed", self._on_webread_changed)
        krow.append(self.webread_key)
        self.webread_ai_box.append(krow)

        mdrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mdrow.append(Gtk.Label(label=_("Model:"), xalign=0))
        self.webread_model = Gtk.Entry(hexpand=True)
        self.webread_model.set_text(wr.get("model") or vf.DEFAULT_OLLAMA_MODEL)
        self.webread_model.connect("changed", self._on_webread_changed)
        mdrow.append(self.webread_model)
        test = Gtk.Button(label=_("Test connection"))
        test.connect("clicked", self._on_webread_test)
        mdrow.append(test)
        self.webread_ai_box.append(mdrow)

        self.webread_status = Gtk.Label(xalign=0.0, wrap=True)
        self.webread_status.add_css_class("dim-label")
        self.webread_ai_box.append(self.webread_status)

        hint = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        hint.add_css_class("dim-label")
        hint.set_text(_("Requires a running Ollama with a downloaded model, "
                        "e.g.: ollama pull llama3.2"))
        self.webread_ai_box.append(hint)
        return frame

    def _translate_group(self):
        """Translate & read: one OpenAI-compatible endpoint (a local Ollama
        server or a remote API) with a model name and an optional API key.
        The target language is always the UI language (follows Language 1)."""
        frame = Gtk.Frame(label=_("Translate & read"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)
        tr = self.state.setdefault("translate", {})

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("Translates the selected text into the language of "
                        "{lang1} and reads it aloud with that voice. Works "
                        "with a local Ollama server or any OpenAI-compatible "
                        "API.").format(lang1=_("Language 1")))
        box.append(desc)

        urow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        urow.append(Gtk.Label(label=_("URL:"), xalign=0))
        self.trans_url = Gtk.Entry(hexpand=True)
        self.trans_url.set_placeholder_text(vf.DEFAULT_TRANSLATE["url"])
        self.trans_url.set_text(tr.get("url") or vf.DEFAULT_TRANSLATE["url"])
        self.trans_url.connect("changed", self._on_translate_changed)
        urow.append(self.trans_url)
        box.append(urow)

        mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mrow.append(Gtk.Label(label=_("Model:"), xalign=0))
        self.trans_model = Gtk.Entry(hexpand=True)
        self.trans_model.set_text(tr.get("model")
                                  or vf.DEFAULT_TRANSLATE["model"])
        self.trans_model.connect("changed", self._on_translate_changed)
        mrow.append(self.trans_model)
        box.append(mrow)

        # "Discover" fills suggestions on this SAME field (via
        # Gtk.EntryCompletion) rather than a second, separate picker --
        # one place to set the model, whether typed or picked.
        self._trans_completion_store = Gtk.ListStore(str)
        trans_completion = Gtk.EntryCompletion()
        trans_completion.set_model(self._trans_completion_store)
        trans_completion.set_text_column(0)
        trans_completion.set_minimum_key_length(0)
        trans_completion.set_popup_completion(True)
        self.trans_model.set_completion(trans_completion)

        drow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        discover = Gtk.Button(label=_("Discover installed models"))
        discover.connect("clicked", self._on_translate_discover)
        drow.append(discover)
        box.append(drow)

        krow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        krow.append(Gtk.Label(label=_("API key:"), xalign=0))
        self.trans_key = Gtk.Entry(hexpand=True)
        self.trans_key.set_visibility(False)
        self.trans_key.set_placeholder_text(_("optional"))
        self.trans_key.set_text(tr.get("api_key") or "")
        self.trans_key.connect("changed", self._on_translate_changed)
        krow.append(self.trans_key)
        box.append(krow)

        trow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        test = Gtk.Button(label=_("Test connection"))
        test.connect("clicked", self._on_translate_test)
        trow.append(test)
        box.append(trow)
        self.trans_status = Gtk.Label(xalign=0.0, wrap=True)
        self.trans_status.add_css_class("dim-label")
        box.append(self.trans_status)

        sug_frame = Gtk.Frame(
            label=_("Suggested lightweight translation models"))
        sug_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sug_frame.set_child(sug_box)
        self.trans_suggest_rows = {}
        for m in vf.SUGGESTED_MODELS:
            srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            info = Gtk.Label(xalign=0.0, hexpand=True, wrap=True)
            info.set_markup(
                f"<b>{GLib.markup_escape_text(m['name'])}</b>  "
                f"<span alpha='70%'>{GLib.markup_escape_text(m['size'])} "
                f"\u2014 {GLib.markup_escape_text(m['note'])}</span>")
            srow.append(info)
            pull_btn = Gtk.Button(label=_("Pull"))
            pull_btn.connect("clicked", self._on_translate_pull, m["name"])
            srow.append(pull_btn)
            sug_box.append(srow)
            self.trans_suggest_rows[m["name"]] = pull_btn
        box.append(sug_frame)
        self.trans_pull_bar = Gtk.ProgressBar(show_text=True)
        self.trans_pull_bar.set_visible(False)
        box.append(self.trans_pull_bar)

        hint = Gtk.Label(xalign=0.0, wrap=True)
        hint.add_css_class("dim-label")
        hint.set_text(_("The Translate button is hidden by default; enable "
                        "it on the {iface} tab. Pick a keyboard shortcut on "
                        "the {sc} tab.").format(iface=_("Interface"),
                                                sc=_("Shortcuts")))
        box.append(hint)
        return frame

    def _on_translate_changed(self, *_a):
        tr = self.state.setdefault("translate", {})
        tr["url"] = (self.trans_url.get_text().strip()
                     or vf.DEFAULT_TRANSLATE["url"])
        tr["model"] = (self.trans_model.get_text().strip()
                       or vf.DEFAULT_TRANSLATE["model"])
        tr["api_key"] = self.trans_key.get_text().strip()
        vf.save_state(self.state)

    def _on_translate_test(self, *_a):
        self._on_translate_changed()
        self.trans_status.set_text(_("Testing connection..."))

        def worker():
            ok, msg = vf.translate_test(self.state.get("translate", {}))
            GLib.idle_add(lambda: (self.trans_status.set_text(
                ("\u2713 " if ok else "\u2717 ") + msg), False)[1])
        threading.Thread(target=worker, daemon=True).start()

    def _on_translate_discover(self, _btn):
        self._on_translate_changed()
        self.trans_status.set_text(_("Discovering models..."))

        def worker():
            ids, err = vf.list_models(self.state.get("translate", {}))
            GLib.idle_add(self._translate_discovered_done, ids, err)
        threading.Thread(target=worker, daemon=True).start()

    def _translate_discovered_done(self, ids, err):
        if err:
            self.trans_status.set_text(
                f"{_('Could not discover models')}: {err}")
            return False
        self._discovered_models = ids
        self._trans_completion_store.clear()
        for mid in ids:
            if vf.is_chat_model(mid):
                self._trans_completion_store.append([mid])
        if ids:
            self.trans_status.set_text(
                _("Found {n} installed model(s)").format(n=len(ids)))
        else:
            self.trans_status.set_text(_("No models found on this endpoint"))
        self._refresh_suggested_buttons()
        return False

    def _refresh_suggested_buttons(self):
        have = set(getattr(self, "_discovered_models", []) or [])
        have_base = {h.split(":")[0] for h in have}
        for name, btn in self.trans_suggest_rows.items():
            installed = name in have or name.split(":")[0] in have_base
            # Installed models get a "Use" button instead of a disabled
            # "Installed" label -- picking a suggestion should never require
            # retyping its exact name into the Model field by hand.
            btn.set_label(_("Use") if installed else _("Pull"))
            btn.set_sensitive(True)

    def _select_translate_model(self, model_name):
        """Make `model_name` the active translation model without a network
        call -- used both for an already-installed suggestion and right
        after a fresh pull succeeds."""
        self.trans_model.set_text(model_name)
        self._on_translate_changed()
        self.trans_status.set_text(
            _("{model} is now the active model").format(model=model_name))

    def _on_translate_pull(self, _btn, model_name):
        have = set(getattr(self, "_discovered_models", []) or [])
        have_base = {h.split(":")[0] for h in have}
        if model_name in have or model_name.split(":")[0] in have_base:
            # Already installed: this click means "use it", not "pull it
            # again" -- no network call needed.
            self._select_translate_model(model_name)
            return

        self._on_translate_changed()
        self.trans_pull_bar.set_visible(True)
        self.trans_pull_bar.set_fraction(0.0)
        self.trans_pull_bar.set_text(_("Starting..."))

        def worker():
            def frac(fr, label):
                GLib.idle_add(lambda: (_set_progress_bar(
                    self.trans_pull_bar, fr, label), False)[1])

            def prog(msg):
                GLib.idle_add(
                    lambda: (self.trans_pull_bar.set_text(msg), False)[1])
            ok, msg = vf.pull_model(model_name, self.state.get("translate", {}),
                                    progress=prog, frac=frac)
            GLib.idle_add(self._translate_pull_done, ok, msg, model_name)
        threading.Thread(target=worker, daemon=True).start()

    def _translate_pull_done(self, ok, msg, model_name):
        _hide_progress_bar(self.trans_pull_bar)
        if ok:
            self._discovered_models = list(
                set(getattr(self, "_discovered_models", []) or [])
                | {model_name})
            self._refresh_suggested_buttons()
            # A model someone just spent time downloading is, in every
            # realistic case, one they want to try immediately -- select it
            # rather than leaving them to type its exact name afterwards.
            self._select_translate_model(model_name)
        else:
            self.trans_status.set_text(
                f"{_('Could not pull')} {model_name}: {msg}")
        return False

    def _on_webread_changed(self, *_a):
        wr = self.state.setdefault("webread", {})
        wr["use_ollama"] = bool(self.webread_ai_chk.get_active())
        self.webread_ai_box.set_visible(wr["use_ollama"])
        wr["mode"] = ("summary" if self.webread_mode_dd.get_selected() == 1
                      else "filter")
        wr["url"] = self.webread_url.get_text().strip() or vf.DEFAULT_OLLAMA_URL
        wr["model"] = (self.webread_model.get_text().strip()
                       or vf.DEFAULT_OLLAMA_MODEL)
        wr["api_key"] = self.webread_key.get_text().strip()
        vf.save_state(self.state)

    def _on_webread_test(self, *_a):
        url = self.webread_url.get_text().strip() or vf.DEFAULT_OLLAMA_URL
        self.webread_status.set_text(_("Testing connection..."))

        api_key = self.webread_key.get_text().strip() or None

        def worker():
            models = vf.ollama_list_models(url, api_key=api_key)
            def done():
                if models is None:
                    self.webread_status.set_text(
                        _("Ollama not reachable — reading the unfiltered "
                          "text"))
                elif not models:
                    self.webread_status.set_text(
                        "✓ " + _("Connection OK") + " — " +
                        _("Requires a running Ollama with a downloaded "
                          "model, e.g.: ollama pull llama3.2"))
                else:
                    self.webread_status.set_text(
                        "✓ " + _("Connection OK") + ": "
                        + ", ".join(models[:8]))
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def _on_merge_toggled(self, btn):
        on = btn.get_active()
        self.state["merge_lines"] = on
        vf.save_state(self.state)
        vf.set_merge_lines(on)



    def _on_export(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Export settings"), self, Gtk.FileChooserAction.SAVE, None, None)
        dlg.set_current_name("voxfox-settings.json")
        dlg.set_modal(True)
        dlg.connect("response", self._export_response)
        self._file_dlg = dlg
        dlg.show()

    def _export_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                import copy as _copy
                import json
                # Never write secrets into an export: exports get shared and
                # end up on other machines and in support mails.
                clean = _copy.deepcopy(self.state)
                if isinstance(clean.get("whisper"), dict):
                    clean["whisper"]["remote_api_key"] = ""
                if isinstance(clean.get("webread"), dict):
                    clean["webread"]["api_key"] = ""
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(clean, f, ensure_ascii=False, indent=2)
                self.win.set_status(_("Settings exported"))
            except Exception as e:
                self.win.set_status(f"{_('Export failed')}: {e}")
        dlg.destroy()

    def _on_import(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Import settings"), self, Gtk.FileChooserAction.OPEN, None, None)
        flt = Gtk.FileFilter()
        flt.set_name("JSON")
        flt.add_pattern("*.json")
        dlg.add_filter(flt)
        dlg.set_modal(True)
        dlg.connect("response", self._import_response)
        self._file_dlg = dlg
        dlg.show()

    def _import_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                import json
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("not a settings object")
                vf.save_state(data)
                self.state = vf.load_state()
                self.win.state = self.state
                vf.set_pronunciations(self.state.get("pronunciations", {}))
                vf.set_merge_lines(self.state.get("merge_lines", True))
                apply_ui_language(self.state["slot1"].get("lang", ""))
                self.win.rebuild_ui()
                self.win.set_status(_("Settings imported"))
                dlg.destroy()
                self.close()
                return
            except Exception as e:
                self.win.set_status(f"{_('Import failed')}: {e}")
        dlg.destroy()

    def _set_dl_progress(self, fraction, label=None):
        if _set_progress_bar(self.dl_progress, fraction, label) >= 1.0:
            GLib.timeout_add(800, self._hide_dl_progress)
        return False

    def _hide_dl_progress(self):
        return _hide_progress_bar(self.dl_progress)

    def _on_model_download(self, _btn):
        name = _dropdown_value(self.model_dd)
        self.model_status.set_text(f"⬇ {name}...")

        def worker():
            try:
                _model, err = vf.load_whisper_model(
                    name,
                    progress_cb=lambda m: GLib.idle_add(
                        self.model_status.set_text, m),
                    frac_cb=lambda fr, lbl=None: GLib.idle_add(
                        self._set_dl_progress, fr, lbl))
                if err:
                    GLib.idle_add(self.model_status.set_text, f"✗ {err}")
                else:
                    GLib.idle_add(self._refresh_model_status)
            except Exception as e:
                GLib.idle_add(self.model_status.set_text, f"✗ {e}")
            finally:
                GLib.idle_add(self._hide_dl_progress)
        threading.Thread(target=worker, daemon=True).start()

    def _on_device_changed(self, dd, _p):
        idx = dd.get_selected()
        if 0 <= idx < len(self._dev_values):
            self._save_w("device", self._dev_values[idx])

    def _on_mic_changed(self, dd, _p):
        idx = dd.get_selected()
        if 0 <= idx < len(self._mic_options):
            self._save_w("mic_id", self._mic_options[idx][0])

    def _on_mic_refresh(self, _btn):
        cur_id = self.state["whisper"].get("mic_id", "")
        self._mic_options = vf.list_microphones()
        self._mic_labels  = [lbl for (_id, lbl) in self._mic_options]
        # Keep the current mic selected if it's still present; otherwise fall
        # back to the first entry and tell the user it's gone.
        keep = None
        for _id, lbl in self._mic_options:
            if _id == cur_id and cur_id:
                keep = lbl
                break
        _set_dropdown_items(self.mic_dd, self._mic_labels,
                            keep or (self._mic_labels[0]
                                     if self._mic_labels else None))
        if cur_id and keep is None:
            self._save_w("mic_id", self._mic_options[0][0]
                         if self._mic_options else "")
            self.win.set_status(
                _("Previous microphone not found — using the default"))

    def _on_confirm_toggled(self, btn):
        self._save_w("confirm_before_typing", btn.get_active())

    def _on_backend_changed(self, dd, _p):
        remote = dd.get_selected() == 1
        self._save_w("backend", "remote" if remote else "local")
        self.remote_box.set_visible(remote)

    def _on_test_remote(self, _btn):
        url   = self.url_entry.get_text().strip()
        model = self.rmodel_entry.get_text().strip()
        key   = self.key_entry.get_text().strip()
        if not url or not model:
            self.win.set_status(_("Set a URL and model first"))
            return
        self.win.set_status(_("Testing connection…"), duration=0)
        self.test_result_lbl.set_text(_("Testing connection…"))

        def worker():
            import wave
            tmp = os.path.join(vf.ram_tmpdir(), "voxfox_test.wav")
            ok_text = ""
            err = ""
            try:
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(b"\x00\x00" * 16000)
                txt, err = vf.transcribe_remote(tmp, url=url, api_key=key,
                                                model_name=model,
                                                language_hint=None)
                if not err:
                    ok_text = txt.strip() if txt and txt.strip() else _("(no transcription returned)")
            except Exception as e:
                err = str(e)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            if err:
                msg = f"✗ {err}"
            else:
                msg = f"✓ {_('Connection OK')} — {ok_text}"
            def _show(m=msg):
                self.test_result_lbl.set_text(m)
                self.win.set_status(m, 8000)
            GLib.idle_add(_show)
        threading.Thread(target=worker, daemon=True).start()



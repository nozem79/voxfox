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

"""voxfox_ui.preferences.shortcuts

Sneltoetsen: choosing keys per action and installing them on the
desktop.
"""


import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.shortcuts import SHORTCUT_ACTIONS, SHORTCUT_LABELS, binding_display, binding_for, cinnamon_reload, install_desktop_shortcuts  # noqa: E402


class ShortcutsSection:
    """Sneltoetsen: choosing keys per action and installing them on the
    desktop.
    """

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

        for key, _label, _cmd, default in SHORTCUT_ACTIONS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            name = Gtk.Label(label=_(SHORTCUT_LABELS.get(key, key)), xalign=0)
            name.set_hexpand(True)
            row.append(name)

            cap = Gtk.Button(label=binding_display(
                binding_for(self.state, key, default)))
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
        default = next((d for k, _l, _c, d in SHORTCUT_ACTIONS if k == key), "")
        btn.set_label(binding_display(binding_for(self.state, key, default)))
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
        for k, _l, _c, d in SHORTCUT_ACTIONS:
            if k != key and binding_for(self.state, k, d) == binding:
                self._stop_capture()
                self._refresh_capture_label(key, btn)
                self._shortcut_result.set_text(
                    _("That key combination is already used by another "
                      "VoxFox shortcut."))
                return True
        self.state.setdefault("shortcut_bindings", {})[key] = binding
        vf.save_state(self.state)
        self._stop_capture()
        btn.set_label(binding_display(binding))
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
            ok = install_desktop_shortcuts(self.state, conflicts)
        except Exception as e:
            log.debug(f"install shortcuts (settings) failed: {e}")
            ok = False
        vf.save_state(self.state)
        if ok:
            if cinnamon_reload():
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
                        action=_(SHORTCUT_LABELS.get(k, k)),
                        key=binding_display(binding), owner=owner)
                     for (k, binding, owner) in conflicts]
            msg += ("\n\n" + _("Some shortcuts could not be installed "
                               "because the key is already in use:")
                    + "\n" + "\n".join(lines))
        self._shortcut_result.set_text(msg)

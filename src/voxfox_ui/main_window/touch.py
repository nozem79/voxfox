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

"""voxfox_ui.main_window.touch

The floating touch button (6.3): showing or hiding it as Settings say,
and running the action a gesture asks for.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log


class TouchMixin:
    """Shows the touch button when it is switched on and runs its actions."""

    def apply_touch_button(self, startup=False):
        """Show, rebuild or hide the button to match the settings. Called
        at start-up (startup=True) and whenever its settings change."""
        cfg = vf.normalize_touch_button(self.state.get("touch_button"))
        self.state["touch_button"] = cfg
        old = getattr(self, "touch_btn", None)
        if old is not None:
            self.touch_btn = None
            old.destroy()
        if cfg["enabled"]:
            try:
                from voxfox_ui.touchbutton import TouchButton
                self.touch_btn = TouchButton(self)
                self.touch_btn.show_button()
            except Exception as e:
                log.warning(f"touch button could not be shown: {e}")
                self.touch_btn = None
        self.sync_main_window(startup=startup)

    def touch_hides_main(self):
        """True while the settings say VoxFox's own window should stay out
        of sight because the touch button is there instead."""
        cfg = vf.normalize_touch_button(self.state.get("touch_button"))
        return (cfg["enabled"] and cfg["hide_window"]
                and getattr(self, "touch_btn", None) is not None)

    def sync_main_window(self, startup=False):
        """Hide or show VoxFox's own window to match the touch-button
        settings. While Settings is open nothing is hidden (it would take
        Settings along on some window managers); closing Settings calls
        this again. After start-up the window is only ever shown here,
        except when the hide setting has just been switched on."""
        prefs = getattr(self, "_prefs", None)
        log.debug(f"touch: sync main window (startup={startup}, "
                  f"pending={self._touch_hide_pending}, "
                  f"prefs open={bool(prefs and prefs.get_visible())}, "
                  f"hide={self.touch_hides_main()})")
        if prefs is not None and prefs.get_visible():
            return
        if self.touch_hides_main():
            if startup or self._touch_hide_pending:
                self._touch_hide_pending = False
                self.set_visible(False)
        elif not self.get_visible():
            self.present()

    def close_touch_button(self):
        btn = getattr(self, "touch_btn", None)
        self.touch_btn = None
        if btn is not None:
            btn.destroy()

    def show_main_window(self):
        """Bring VoxFox's window up, also when the touch button hides it.
        Used when VoxFox is started again while it is running."""
        self.present()
        GLib.timeout_add(250, lambda: (self.restore_window_pos(), False)[1])
        GLib.timeout_add(400, lambda: (self.set_always_on_top(), False)[1])

    def switch_off_touch_button(self):
        """Switch the button off and bring back VoxFox's window with its
        ordinary buttons. Switch it on again in Settings."""
        self.state.setdefault("touch_button", {})["enabled"] = False
        vf.save_state(self.state)
        prefs = getattr(self, "_prefs", None)
        chk = getattr(prefs, "touch_chk", None) if prefs else None
        if chk is not None and prefs.get_visible():
            chk.set_active(False)          # keep an open Settings truthful
        self.apply_touch_button()
        self.show_main_window()
        self.set_status(_("Touch button switched off"))

    def toggle_touch_button(self):
        """Super+T (voxfox --touch-toggle): switch the button on or off."""
        cfg = vf.normalize_touch_button(self.state.get("touch_button"))
        if cfg["enabled"]:
            self.switch_off_touch_button()
            return
        cfg["enabled"] = True
        self.state["touch_button"] = cfg
        vf.save_state(self.state)
        prefs = getattr(self, "_prefs", None)
        chk = getattr(prefs, "touch_chk", None) if prefs else None
        if chk is not None and prefs.get_visible():
            chk.set_active(True)
        # Switched on on purpose: hide the window now if that is the setting.
        self._touch_hide_pending = cfg["hide_window"]
        self.apply_touch_button()
        if not vf.is_x11_client():
            self.set_status(_("Touch button switched on. Restart VoxFox to "
                              "keep it on top."), 6000)
        else:
            self.set_status(_("Touch button switched on"))

    def run_touch_action(self, action):
        """Run one action id from voxfox_core.touchbutton.ACTIONS."""
        if action == "window":
            if self.get_visible():
                self.set_visible(False)
            else:
                self.show_main_window()
            return
        if action == "off":
            self.switch_off_touch_button()
            return
        if action == "stop_clear":
            self.do_stop()
            vf.clear_selection()
            self.set_status(_("Stopped, selection cleared"))
            return
        from voxfox_ui.touchbutton import ACTION_METHODS
        name = ACTION_METHODS.get(action)
        method = getattr(self, name, None) if name else None
        if method is None:
            log.debug(f"touch button: unknown action {action!r}")
            return
        try:
            method()
        except Exception as e:
            log.warning(f"touch button action {action}: {e}")

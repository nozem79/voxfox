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

"""voxfox_ui.main_window.status

The status line, the download progress bar, the reading bar, and the
active language slot.
"""


import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import set_accessible_label, btn_set_text, hide_progress_bar, set_progress_bar  # noqa: E402


class StatusMixin:
    """The status line, the download progress bar, the reading bar, and the
    active language slot.
    """

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
        if set_progress_bar(self.progress, fraction, label) >= 1.0:
            GLib.timeout_add(800, self.hide_progress)
        return False

    def hide_progress(self):
        r = hide_progress_bar(self.progress)
        if not self.status.get_visible():
            self._fit_to_content(keep_width=True)
        return r

    def _tick_reading(self):
        """Four times a second: the Read button shows what pressing it
        would do now (Read / Pause / Resume), and the reading bar shows
        how far a longer text has got."""
        try:
            speaking, paused = vf.is_speaking(), vf.is_paused()
            want = ("resume" if paused else "pause") if speaking else "read"
            if want != getattr(self, "_read_btn_mode", None):
                self._read_btn_mode = want
                label = {"read": _("Read"), "pause": _("Pause"),
                         "resume": _("Resume")}[want]
                icon = {"read": "voxfox-read-symbolic",
                        "pause": "voxfox-pause-symbolic",
                        "resume": "voxfox-read-symbolic"}[want]
                btn_set_text(self.read_btn, label)
                if getattr(self.read_btn, "_icon", None) is not None:
                    self.read_btn._icon.set_from_icon_name(icon)
                set_accessible_label(self.read_btn, label)
            pos = vf.get_position()
            length = pos.get("length") or 0
            show = speaking and length >= 300
            if show:
                self.reading_bar.set_fraction(
                    max(0.0, min(1.0, (pos.get("offset") or 0) / length)))
            if self.reading_bar.get_visible() != show:
                self.reading_bar.set_visible(show)
        except Exception as e:
            log.debug(f"reading tick failed: {e}")
        return True

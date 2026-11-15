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

"""voxfox_ui.myna — the D-Bus side of dictating through Myna (6.3).

MynaClient watches whether Myna's dictation service is on the session
bus, can toggle it, and reports its State. See voxfox_core.myna for the
interface and the reasoning.
"""

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402

log = vf.log


class MynaClient:
    """Follows com.canonical.Myna.Dictation on the session bus.

    `on_change(state)` is called on the GTK main thread whenever Myna
    appears ("idle" or its current state), disappears (None) or changes
    state. Nothing here ever starts Myna: VoxFox only uses it when it is
    already running."""

    def __init__(self, on_change=None):
        self.on_change = on_change
        self.proxy = None
        self.state = None            # None = Myna not running
        self._watch = 0
        try:
            self._watch = Gio.bus_watch_name(
                Gio.BusType.SESSION, vf.MYNA_BUS_NAME,
                Gio.BusNameWatcherFlags.NONE,
                self._on_appeared, self._on_vanished)
        except GLib.Error as e:
            log.debug(f"myna: no session bus: {e}")

    @property
    def running(self):
        return self.state is not None

    def _on_appeared(self, _conn, _name, _owner):
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
            None, vf.MYNA_BUS_NAME, vf.MYNA_OBJECT_PATH, vf.MYNA_INTERFACE,
            None, self._on_proxy)

    def _on_proxy(self, _src, res):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error as e:
            log.warning(f"myna: proxy failed: {e}")
            return
        self.proxy.connect("g-properties-changed", self._on_props)
        self._set_state(self._read_state() or "idle")
        log.info("myna: dictation service found")

    def _on_vanished(self, _conn, _name):
        if self.proxy is not None or self.state is not None:
            log.info("myna: dictation service gone")
        self.proxy = None
        self._set_state(None)

    def _read_state(self):
        if self.proxy is None:
            return None
        v = self.proxy.get_cached_property("State")
        return v.unpack() if v is not None else None

    def _on_props(self, _proxy, changed, _invalidated):
        try:
            d = changed.unpack()
        except Exception:
            return
        if "State" in d:
            self._set_state(d["State"])

    def _set_state(self, state):
        if state == self.state:
            return
        self.state = state
        if self.on_change:
            try:
                self.on_change(state)
            except Exception as e:
                log.warning(f"myna: state handler: {e}")

    def toggle(self, done=None):
        """Start or stop a Myna dictation. `done(ok, message)` afterwards."""
        if self.proxy is None:
            if done:
                done(False, "Myna is not running")
            return

        def finish(proxy, res):
            try:
                proxy.call_finish(res)
                ok, msg = True, ""
            except GLib.Error as e:
                log.warning(f"myna: Toggle failed: {e}")
                ok, msg = False, e.message
            if done:
                done(ok, msg)
        self.proxy.call("Toggle", None, Gio.DBusCallFlags.NO_AUTO_START,
                        5000, None, finish)

    def close(self):
        if self._watch:
            Gio.bus_unwatch_name(self._watch)
            self._watch = 0
        self.proxy = None

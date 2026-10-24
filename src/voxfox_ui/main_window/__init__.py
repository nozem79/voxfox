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

"""voxfox_ui.main_window — the main VoxFox window, split by task.

window.py creates the window; the other modules each hold one kind of
action or one part of the window as a mixin class that VoxFoxWindow
inherits from. The do_* methods are also what the keyboard shortcuts
call (through voxfox_core.ipc).
"""

from voxfox_ui.main_window.window import VoxFoxWindow  # noqa: F401

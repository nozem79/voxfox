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


"""voxfox_core — VoxFox backend (screen reader + dictation engine).

This package was split out of a single module; the public API is
re-exported here so ``import voxfox_core as vf`` keeps working.
"""

from .common import *  # noqa: F401,F403
from .state import *  # noqa: F401,F403
from .tts import *  # noqa: F401,F403
from .stt import *  # noqa: F401,F403
from .ocr import *  # noqa: F401,F403
from .a11y import *  # noqa: F401,F403
from .webread import *  # noqa: F401,F403
from .ipc import *  # noqa: F401,F403

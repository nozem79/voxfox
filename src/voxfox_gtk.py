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

"""
VoxFox — GTK4 front-end entry point.

All UI code lives in the voxfox_ui package (split from this file in 4.0).
All TTS / STT / OCR / IPC / CLI logic lives in voxfox_core.

Run the GUI:        voxfox
Set up components:  voxfox --setup     (downloads Piper + voices + Whisper)
Forward a command:  voxfox --read      (and --stop, --pause, --ocr-select, ...)
"""
import os
import sys

# When run as a script (python3 /usr/lib/voxfox/voxfox_gtk.py), make sure the
# directory holding voxfox_ui/ and voxfox_core/ is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voxfox_ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()

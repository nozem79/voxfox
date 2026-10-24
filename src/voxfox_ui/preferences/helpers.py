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

"""voxfox_ui.preferences.helpers

Small functions shared by the settings sections.
"""


import gi
gi.require_version("Gtk", "4.0")

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log


def _voice_label(key):
    """How a Piper voice is shown: "Alex (NL, medium quality)" instead of
    the file name "nl_NL-alex-medium"."""
    name, region, quality = vf.voice_display_parts(key)
    if not quality:
        return name
    q = {"x_low": _("very low quality"), "low": _("low quality"),
         "medium": _("medium quality"), "high": _("high quality")}[quality]
    return f"{name} ({region}, {q})"


def _whisper_model_hint(name):
    """One plain sentence per dictation model: what it is good for."""
    hints = {
        "tiny": _("Smallest and fastest, but makes the most mistakes. About 75 MB."),
        "base": _("Fast, good enough for short sentences. About 145 MB."),
        "small": _("Good balance of speed and accuracy; the best choice for "
                   "most people. About 480 MB."),
        "medium": _("More accurate, but slower; needs a fast computer. "
                    "About 1.5 GB."),
        "large-v3": _("Most accurate, but slow without a graphics card (GPU). "
                      "About 3 GB."),
    }
    return hints.get(name, "")

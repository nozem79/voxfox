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

"""voxfox_core.myna — dictating through Canonical's Myna (6.3).

Myna (github.com/canonical/myna) is Ubuntu's offline dictation: it
records, recognises and types the text itself. When it is installed,
VoxFox can use it for Dictate instead of its own Whisper/Parakeet.

The coupling is the D-Bus service Myna publishes on the session bus for
its shortcut and its GNOME indicator:

    name / path / interface  com.canonical.Myna.Dictation
                             /com/canonical/Myna/Dictation
    method   Toggle()        start dictation when idle, else stop it
    property State (s)       idle, loading, recording, transcribing,
                             finalizing, notice, error; Myna may add more
                             (callers must ignore unknown values)
    property StatusMessage   a short label, never the transcript

Two separate programs talking over D-Bus: no code is shared, so Myna's
AGPL and VoxFox's GPL do not mix. This module holds what can be tested
without a bus; voxfox_ui.myna does the D-Bus part.
"""

from .common import _

MYNA_BUS_NAME = "com.canonical.Myna.Dictation"
MYNA_OBJECT_PATH = "/com/canonical/Myna/Dictation"
MYNA_INTERFACE = "com.canonical.Myna.Dictation"

# States in which a dictation is under way: the Dictate button shows Stop.
_BUSY = frozenset(("loading", "recording", "transcribing", "finalizing"))


def myna_is_busy(state):
    """True while Myna is loading, listening or still working on the text."""
    return state in _BUSY


def myna_status_text(state):
    """The status line for a Myna state, or "" for idle and unknown states."""
    texts = {
        "loading": _("Myna: loading the model..."),
        "recording": _("Myna: listening..."),
        "transcribing": _("Myna: transcribing..."),
        "finalizing": _("Myna: transcribing..."),
        "notice": _("Myna: no speech detected"),
        "error": _("Myna: something went wrong; see Myna Settings"),
    }
    return texts.get(state, "")


def use_myna(whisper_cfg, myna_running):
    """Whether Dictate should go to Myna: chosen in Settings and running."""
    return bool(myna_running) and (whisper_cfg or {}).get("engine") == "myna"


__all__ = ["MYNA_BUS_NAME", "MYNA_OBJECT_PATH", "MYNA_INTERFACE",
           "myna_is_busy", "myna_status_text", "use_myna"]

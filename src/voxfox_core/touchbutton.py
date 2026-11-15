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

"""voxfox_core.touchbutton — the floating touch button's settings (6.3).

A small round button that floats above every window, for touchscreens
(and for anyone who prefers one big button to keyboard shortcuts). Each
way of pressing it runs one VoxFox action:

    tap1   tap once            default: choose a screen area, read it
    tap2   tap twice           default: pause / resume
    tap3   tap three times     default: read the web page
    tap4   tap four times      default: show or hide VoxFox's window
    tap5   tap five times      default: switch the button off again
    long   press and hold      default: stop, and clear the selection

Which action goes with which gesture is set in Settings. This module
holds what can be tested without GTK: the action names, the defaults,
and cleaning up whatever is in the settings file. voxfox_ui.touchbutton
draws the button.
"""

import copy

GESTURES = ("tap1", "tap2", "tap3", "tap4", "tap5", "long")
MAX_TAPS = 5

# Action ids, in the order the settings list shows them. Each matches a
# method of the main window (see voxfox_ui.touchbutton.ACTION_METHODS).
ACTIONS = ("none", "ocr", "read", "pause", "stop", "stop_clear", "page",
           "whisper", "translate", "ocr_translate", "voice", "type", "live",
           "window", "off")

SIZES = (48, 64, 96)                 # small, normal, large (pixels)

DEFAULT_TOUCH_BUTTON = {
    "enabled": False,
    "size": 64,
    "pos": None,                     # [x, y] on screen, or None: bottom right
    # Hide VoxFox's own window while the button is on; opening VoxFox
    # again (app menu, or the "window" action) brings it back.
    "hide_window": False,
    "actions": {"tap1": "ocr", "tap2": "pause", "tap3": "page",
                "tap4": "window", "tap5": "off", "long": "stop_clear"},
}

# How long to wait after a tap for the next one before deciding it was a
# single tap. GTK's double-click time is 400 ms; a little less keeps a
# single tap from feeling slow, but not so little that people who tap
# more slowly never reach a double tap.
TAP_WAIT_MS = 350

# How far (pixels) a finger may move before a press counts as dragging
# the button rather than tapping it.
DRAG_THRESHOLD = 10


def normalize_touch_button(cfg):
    """A complete, valid touch-button config from whatever the settings
    file holds. Unknown actions and sizes fall back to the defaults."""
    out = copy.deepcopy(DEFAULT_TOUCH_BUTTON)
    if not isinstance(cfg, dict):
        return out
    out["enabled"] = bool(cfg.get("enabled", False))
    out["hide_window"] = bool(cfg.get("hide_window", False))
    try:
        size = int(cfg.get("size", out["size"]))
    except (TypeError, ValueError):
        size = out["size"]
    out["size"] = min(SIZES, key=lambda s: abs(s - size))
    pos = cfg.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        try:
            out["pos"] = [int(pos[0]), int(pos[1])]
        except (TypeError, ValueError):
            pass
    acts = cfg.get("actions")
    if isinstance(acts, dict):
        for g in GESTURES:
            if acts.get(g) in ACTIONS:
                out["actions"][g] = acts[g]
    return out


def gesture_for_taps(n):
    """The gesture for `n` quick taps: tap1 ... tap5 (more counts as 5)."""
    n = max(1, min(int(n), MAX_TAPS))
    return f"tap{n}"


def action_for(cfg, gesture):
    """The action id set for `gesture`, or "none"."""
    return normalize_touch_button(cfg)["actions"].get(gesture, "none")


def point_in_rect(px, py, rx, ry, rw, rh):
    """Whether the point lies inside the rectangle (used to hide the
    button only on the monitor where a window is full screen)."""
    return rx <= px < rx + rw and ry <= py < ry + rh


def default_position(monitor_x, monitor_y, monitor_w, monitor_h, size,
                     margin=40):
    """Bottom right of a monitor, `margin` pixels from the edges. That is
    out of the way of most windows' content, and easy to reach with a
    thumb on a tablet held in landscape."""
    return [monitor_x + monitor_w - size - margin,
            monitor_y + monitor_h - size - margin * 2]


__all__ = ["GESTURES", "MAX_TAPS", "ACTIONS", "SIZES", "DEFAULT_TOUCH_BUTTON",
           "TAP_WAIT_MS", "DRAG_THRESHOLD", "normalize_touch_button",
           "gesture_for_taps", "action_for", "default_position",
           "point_in_rect"]

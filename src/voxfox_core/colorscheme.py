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


"""voxfox_core.colorscheme — which GTK theme gives "light" or "dark".

No GTK in here, so it can be tested anywhere; voxfox_ui.theme applies the
result. See that module for why light and dark need two settings.
"""

import os
import re

COLOR_SCHEMES = ("system", "light", "dark")

_DARK = re.compile(r"[-_ ]?dark", re.IGNORECASE)


def theme_dirs():
    home = os.path.expanduser("~")
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return [os.path.join(home, ".themes"), os.path.join(data_home, "themes")] + \
        [os.path.join(d, "themes") for d in data_dirs if d]


def gtk4_theme_exists(name, dirs=None):
    """True when a theme folder with GTK 4 styling is installed."""
    if not name:
        return False
    return any(os.path.isdir(os.path.join(d, name, "gtk-4.0"))
               for d in (dirs or theme_dirs()))


def is_dark_name(name):
    return bool(_DARK.search(name or ""))


def light_variant(name, exists):
    """"Mint-Y-Dark-Aqua" -> "Mint-Y-Aqua", "Yaru-dark" -> "Yaru", when
    that theme exists; otherwise None."""
    if not is_dark_name(name):
        return None
    candidate = _DARK.sub("", name, count=1).strip("-_ ")
    return candidate if candidate and exists(candidate) else None


def dark_variant(name, exists):
    """"Mint-Y-Aqua" -> "Mint-Y-Dark-Aqua", "Yaru" -> "Yaru-dark", when
    that theme exists; otherwise None."""
    if not name or is_dark_name(name):
        return None
    parts = name.split("-")
    candidates = [name + "-dark", name + "-Dark"]
    for i in range(1, len(parts)):
        for word in ("Dark", "dark"):
            candidates.append("-".join(parts[:i] + [word] + parts[i:]))
    return next((c for c in candidates if exists(c)), None)


def choose_theme(mode, original_theme, original_dark, exists, builtin):
    """(theme name, prefer dark) for `mode`, given what the desktop had."""
    if mode == "light":
        if is_dark_name(original_theme):
            return (light_variant(original_theme, exists) or builtin, False)
        return (original_theme or builtin, False)
    if mode == "dark":
        if is_dark_name(original_theme):
            return (original_theme, True)
        return (dark_variant(original_theme, exists) or original_theme or builtin, True)
    return (original_theme, original_dark)


__all__ = ["COLOR_SCHEMES", "choose_theme", "gtk4_theme_exists",
           "is_dark_name", "light_variant", "dark_variant"]

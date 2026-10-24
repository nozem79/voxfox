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


"""voxfox_ui.theme — light, dark, or whatever the desktop uses.

GTK has no single "dark mode" switch that works with every theme. Two
things decide how VoxFox looks:

- the theme itself. Linux Mint ships light and dark as separate themes
  ("Mint-Y-Aqua" and "Mint-Y-Dark-Aqua"), and so do Yaru and others;
- GTK's prefer-dark setting, which makes a theme that has a dark variant
  inside it (GTK's own Default/Adwaita) use that variant.

So for "dark" VoxFox switches to the dark sibling of the desktop's theme
when there is one, and asks for the dark variant either way; for "light"
it does the reverse. Only VoxFox changes: these are VoxFox's own GTK
settings, the desktop's theme is left alone. "System" puts back what the
desktop had when VoxFox started.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from voxfox_core import log  # noqa: E402
from voxfox_core.colorscheme import (  # noqa: E402
    COLOR_SCHEMES as MODES, choose_theme, gtk4_theme_exists)

class _Desktop:
    """What the desktop gave us, captured before VoxFox changes anything:
    (theme name, prefer dark), or None until apply() first runs."""

    def __init__(self):
        self.original = None


_desktop = _Desktop()


def builtin_theme():
    """GTK's own theme: called "Default" since GTK 4.14, "Adwaita" before."""
    try:
        return "Default" if Gtk.get_minor_version() >= 14 else "Adwaita"
    except Exception:
        return "Default"


def apply(mode):
    """Switch VoxFox to `mode` ("system", "light" or "dark"). Safe to call
    repeatedly; returns the (theme, prefer_dark) that was set."""
    settings = Gtk.Settings.get_default()
    if settings is None:
        return None
    if _desktop.original is None:
        _desktop.original = (settings.props.gtk_theme_name,
                     bool(settings.props.gtk_application_prefer_dark_theme))
    if mode not in MODES:
        mode = "system"
    theme, dark = choose_theme(mode, _desktop.original[0], _desktop.original[1],
                               gtk4_theme_exists, builtin_theme())
    try:
        if settings.props.gtk_theme_name != theme:
            settings.props.gtk_theme_name = theme
        settings.props.gtk_application_prefer_dark_theme = dark
        log.info(f"Colour scheme: {mode} -> theme {theme!r}, prefer dark {dark}")
    except Exception as e:
        log.debug(f"colour scheme {mode} failed: {e}")
    return theme, dark

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

A theme can also be installed but unusable. On Ubuntu 26.10 the GTK 4
part of Yaru only imports a resource that is not there, so GTK ends up
with no styling at all and VoxFox's window has no background. VoxFox
therefore checks that a theme really gives CSS, and uses GTK's own
theme when it does not.

GTK 4.20 replaced the prefer-dark setting by gtk-interface-color-scheme;
VoxFox uses that one when it exists, so GTK does not warn.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from voxfox_core import log  # noqa: E402
from voxfox_core.colorscheme import (  # noqa: E402
    COLOR_SCHEMES as MODES, choose_theme, gtk4_theme_exists)

class _Desktop:
    """What the desktop gave us, captured before VoxFox changes anything:
    (theme name, prefer dark, raw colour-scheme value or None), or None
    until apply() first runs."""

    def __init__(self):
        self.original = None
        self.checked = {}            # theme name -> usable (bool)


_desktop = _Desktop()

# A real GTK 4 theme is hundreds of kilobytes of CSS; one that failed to
# import its contents is empty or nearly so.
_MIN_THEME_CSS = 2000


def builtin_theme():
    """GTK's own theme: called "Default" since GTK 4.14, "Adwaita" before."""
    try:
        return "Default" if Gtk.get_minor_version() >= 14 else "Adwaita"
    except Exception:
        return "Default"


def _is_builtin(name):
    return name in ("Default", "Adwaita", "HighContrast",
                    "HighContrastInverse")


def theme_usable(name):
    """True when GTK can load real styling for theme `name`. Remembered per
    name, because loading a theme takes a moment."""
    if not name or _is_builtin(name):
        return True
    if name in _desktop.checked:
        return _desktop.checked[name]
    errors = []
    try:
        provider = Gtk.CssProvider()
        provider.connect("parsing-error",
                         lambda _p, _sec, err: errors.append(err.message))
        provider.load_named(name, None)
        size = len(provider.to_string() or "")
    except Exception as e:
        log.debug(f"theme check {name!r} failed: {e}")
        size, errors = 0, [str(e)]
    ok = size >= _MIN_THEME_CSS
    if not ok:
        log.warning(f"GTK theme {name!r} gives no usable styling "
                    f"({errors[0] if errors else 'empty'}); "
                    f"using GTK's own theme")
    _desktop.checked[name] = ok
    return ok


def _has_color_scheme(settings):
    """GTK 4.20+: gtk-interface-color-scheme instead of prefer-dark."""
    return (hasattr(Gtk, "InterfaceColorScheme")
            and settings.find_property("gtk-interface-color-scheme")
            is not None)


def _read_dark(settings):
    """(prefer dark, raw colour-scheme value or None)."""
    if _has_color_scheme(settings):
        raw = settings.props.gtk_interface_color_scheme
        return raw == Gtk.InterfaceColorScheme.DARK, raw
    return bool(settings.props.gtk_application_prefer_dark_theme), None


def _write_dark(settings, mode, dark):
    if _has_color_scheme(settings):
        if mode == "system" and _desktop.original[2] is not None:
            value = _desktop.original[2]
        else:
            value = (Gtk.InterfaceColorScheme.DARK if dark
                     else Gtk.InterfaceColorScheme.LIGHT)
        if settings.props.gtk_interface_color_scheme != value:
            settings.props.gtk_interface_color_scheme = value
    elif bool(settings.props.gtk_application_prefer_dark_theme) != dark:
        settings.props.gtk_application_prefer_dark_theme = dark


def apply(mode):
    """Switch VoxFox to `mode` ("system", "light" or "dark"). Safe to call
    repeatedly; returns the (theme, prefer_dark) that was set."""
    settings = Gtk.Settings.get_default()
    if settings is None:
        return None
    if _desktop.original is None:
        dark, raw = _read_dark(settings)
        _desktop.original = (settings.props.gtk_theme_name, dark, raw)
    if mode not in MODES:
        mode = "system"
    theme, dark = choose_theme(mode, _desktop.original[0], _desktop.original[1],
                               gtk4_theme_exists, builtin_theme())
    if not theme_usable(theme):
        theme = builtin_theme()
    try:
        if settings.props.gtk_theme_name != theme:
            settings.props.gtk_theme_name = theme
        _write_dark(settings, mode, dark)
        log.info(f"Colour scheme: {mode} -> theme {theme!r}, prefer dark {dark}")
    except Exception as e:
        log.debug(f"colour scheme {mode} failed: {e}")
    return theme, dark

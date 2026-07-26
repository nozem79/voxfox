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

"""voxfox_ui.widgets — Small reusable widget helpers (buttons, dropdowns, progress bars, CSS).

Split out of voxfox_gtk.py in VoxFox 4.0.
"""


import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402

log = vf.log


def _btn_make_content(btn, icon_id, text):
    """Give a toolbar button an icon+label child. The parts are kept on the
    button (btn._icon / btn._lbl) so the view mode can toggle visibility and
    dynamic labels can be updated without Gtk.Button.set_label (which would
    replace our custom child with a plain label again)."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
    box.set_halign(Gtk.Align.CENTER)
    img = Gtk.Image.new_from_icon_name(f"voxfox-{icon_id}-symbolic")
    img.set_pixel_size(20)
    lbl = Gtk.Label(label=text)
    box.append(img)
    box.append(lbl)
    btn.set_child(box)
    btn._icon, btn._lbl = img, lbl


def _btn_set_text(btn, text):
    """Update the label of a toolbar button built by _btn_make_content."""
    if getattr(btn, "_lbl", None) is not None:
        btn._lbl.set_text(text)
    else:
        btn.set_label(text)


def _scale_css(scale):
    """CSS that scales the main window. .voxfox-root only sets the root
    font-size (which scales the title text and, via em, the header icons) so it
    can safely sit on the header without bloating the window-control or
    menu/settings buttons. Everything that contributes to the window's width —
    the toolbar button padding/min-width, the gaps between buttons, and the
    padding around the toolbar — is expressed in em and scoped to the toolbar,
    so the whole window shrinks proportionally at 75 % instead of keeping
    fixed-pixel slack. Only the main window and its header carry these classes;
    the settings dialog keeps the theme default."""
    return (f".voxfox-root {{ font-size: {scale}%; }}\n"
            ".voxfox-root button image { -gtk-icon-size: 1.1em; }\n"
            ".voxfox-pad { padding: 0.2em; }\n"
            ".voxfox-toolbar button { padding: 0.25em 0.4em; min-width: 2.6em; margin: 0.12em; }\n"
            ".voxfox-toolbar flowboxchild { margin: 0.12em; }\n").encode()


# ── GLib adapter so voxfox_core.IPCServer can schedule work on the UI thread ──
def _dropdown(items, selected_value=None):
    dd = Gtk.DropDown.new_from_strings(items or [""])
    if selected_value and selected_value in (items or []):
        dd.set_selected(items.index(selected_value))
    return dd


def _set_dropdown_items(dd, items, selected_value=None):
    dd.set_model(Gtk.StringList.new(items or [""]))
    if selected_value and items and selected_value in items:
        dd.set_selected(items.index(selected_value))
    else:
        dd.set_selected(0)


def _dropdown_value(dd):
    item = dd.get_selected_item()
    return item.get_string() if item is not None else ""


def _a11y(widget, label):
    """Give a widget an explicit accessible name for screen readers. Essential
    for icon-only / emoji buttons, whose visible glyph is not a usable label.
    An accessibility tool should itself be accessible."""
    try:
        widget.update_property([Gtk.AccessibleProperty.LABEL], [label])
    except Exception as e:
        log.debug(f"a11y label failed: {e}")


def _set_progress_bar(bar, fraction, label=None):
    """Show/update a Gtk.ProgressBar (call on the GUI thread). Returns the
    clamped fraction so callers can decide whether to auto-hide."""
    try:
        fr = max(0.0, min(1.0, float(fraction)))
    except (TypeError, ValueError):
        fr = 0.0
    bar.set_fraction(fr)
    pct = int(fr * 100)
    bar.set_text(f"{label} — {pct}%" if label else f"{pct}%")
    bar.set_visible(True)
    return fr


def _hide_progress_bar(bar):
    bar.set_visible(False)
    bar.set_fraction(0.0)
    return False


# ── Preferences window: per-slot language/voice + Whisper model + API ─────────

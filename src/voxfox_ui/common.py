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

"""voxfox_ui.common — Shared constants, icon path registration and the RootShim.

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402

log = vf.log


SYSTEM_DATA_DIR = "/usr/share/voxfox"
SYSTEM_LOCALES  = os.path.join(SYSTEM_DATA_DIR, "locales")
SYSTEM_ICON     = "/usr/share/icons/hicolor/256x256/apps/voxfox.png"

PIPER_VERSION = "2023.11.14-2"
PIPER_RELEASE = ("https://github.com/rhasspy/piper/releases/download/"
                 + PIPER_VERSION)
# SHA-256 per asset, verified before extraction when present. Fill these in
# once (they never change for a pinned release) by running, on a machine that
# can reach GitHub:
#   packaging/pin_piper_hashes.py
# An empty dict means "download without checksum verification" — extraction is
# still hardened against tar-slip, so this is safe but not supply-chain-proof.
PIPER_SHA256 = {
    "piper_linux_x86_64.tar.gz":  "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992",
    "piper_linux_aarch64.tar.gz": "fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb",
    "piper_linux_armv7l.tar.gz":  "c6946fcd57c705ed1d4666ea880f80ba0bbbd14de62ecbdd13460baf3bac8e37",
}


DEFAULT_VOICES = ["en_GB-alba-medium", "nl_NL-pim-medium"]
APP_VERSION = "6.2.1"
MANUAL_URL  = "https://voxfox.nl/manual"

# Logo orange, used for accent buttons instead of the theme's accent colour.
ACCENT_CSS = b"""
.voxfox-accent {
  background-image: none;
  background-color: #F26A1F;
  color: #ffffff;
  border-color: #D9590F;
}
.voxfox-accent:hover  { background-color: #F47E3A; }
.voxfox-accent:active { background-color: #D9590F; }
/* Dictation is recording: the button's icon blinks so a running
   microphone is hard to miss. */
@keyframes voxfox-blink { 0% { opacity: 1; } 50% { opacity: 0.15; } 100% { opacity: 1; } }
.voxfox-recording image { animation: voxfox-blink 1s ease-in-out infinite; }
/* How far reading has got: a thin bar under the buttons. */
progressbar.voxfox-reading trough, progressbar.voxfox-reading progress {
  min-height: 4px;
}
"""


# ── 3.0 modular toolbar registry ──────────────────────────────────────────
# The seven front-end action buttons. This is the single source of truth for
# which buttons exist; state.json (ui_layout) only stores the user's chosen
# visibility and order. Fields per button:
#   id       stable key, persisted in state — never rename, only add/remove
#   attr     the VoxFoxWindow attribute kept for the live widget (other code
#            still refers to self.read_btn, self.whisper_btn, ...)
#   label    English button text (run through _() at build time)
#   tooltip  English tooltip text (through _())
#   a11y     English accessible label (through _())
#   handler  name of the VoxFoxWindow method invoked on click
#   css      optional extra CSS class (e.g. the orange accent on Read)
TOOLBAR_BUTTONS = [
    # Labels are one short word; the tooltip says in a plain sentence what
    # the button does (and the shortcut is added to it at build time).
    # Read doubles as Pause/Resume while speaking (do_read_button), which is
    # why the separate Pause button now starts hidden.
    ("read",    "read_btn",    "Read",   "Reads the text you selected aloud",
     "Read selected text aloud", "do_read_button", "voxfox-accent"),
    ("stop",    "stop_btn",    "Stop",   "Stops reading aloud",
     "Stop", "do_stop", None),
    ("pause",   "pause_btn",   "Pause",  "Pauses reading, or carries on",
     "Pause or resume", "do_pause", None),
    ("dictate", "whisper_btn", "Dictate", "Speak, and VoxFox types what you say",
     "Dictate (speech to text)", "do_whisper", None),
    ("hover",   "hover_btn",   "Mouse",
     "Reads aloud whatever is under the mouse pointer",
     "Toggle hover reading", "do_hover", None),
    ("select",  "select_btn",  "Screen",
     "Draw a box around part of the screen to have it read aloud",
     "Select a screen region to read via OCR", "do_ocr_select", None),
    ("ocr",     "ocr_btn",     "File",
     "Open a document, PDF or picture and have it read aloud",
     "Open a document, PDF, or image to read aloud", "do_ocr_file", None),
    ("type",    "type_btn",    "Type",
     "Opens a window where you type a text and VoxFox says it",
     "Type a text and have it said aloud", "do_type_speak", None),
    ("translate", "translate_btn", "Translate",
     "Translates the selected text and reads it aloud",
     "Translate selection and read aloud", "do_translate", None),
]
# Toolbar button -> keyboard shortcut action, for the tooltips.
TOOLBAR_SHORTCUTS = {"read": "read", "stop": "stop", "dictate": "whisper",
                     "select": "ocr", "translate": "translate", "switch": "voice",
                     "type": "type"}
TOOLBAR_IDS = [b[0] for b in TOOLBAR_BUTTONS] + ["switch"]
# Buttons that ship hidden; the user enables them under Settings -> Interface.
TOOLBAR_DEFAULT_HIDDEN = {"translate", "pause", "type"}

# Button view modes (Settings -> Interface -> Button display).
UI_VIEWS = ["icons", "both", "text"]
UI_ORIENTS = ["horizontal", "vertical"]

def register_icon_path():
    """Make the bundled voxfox-*-symbolic icons findable. Installed packages
    ship them under /usr/share/voxfox/icons; a git checkout has them in
    ./icons next to src/. Symbolic SVGs are recoloured by GTK to match the
    theme, so they work in light and dark themes alike."""
    try:
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    except Exception as e:
        log.debug(f"icon theme unavailable: {e}")
        return
    here = os.path.dirname(os.path.abspath(__file__))
    # A git checkout keeps icons/ two levels up from src/voxfox_ui; the Nix
    # package puts it right next to voxfox_ui/ (one level up). Both looked.
    for base in ("/usr/share/voxfox/icons",
                 os.path.join(here, "..", "icons"),
                 os.path.join(here, "..", "..", "icons")):
        if os.path.isdir(base):
            try:
                theme.add_search_path(os.path.abspath(base))
            except Exception as e:
                log.debug(f"add_search_path {base}: {e}")


class RootShim:
    """IPCServer and worker threads call ``app.root.after(ms, fn)`` to bounce a
    callback onto the UI thread — the Tk idiom. We map it onto GLib's loop:
    idle_add for ms<=0, timeout_add otherwise. Each callback fires once."""

    @staticmethod
    def after(ms, fn, *args):
        def once():
            try:
                fn(*args)
            except Exception:
                # A shortcut (voxfox --read ...) ends up here; a failure
                # must be visible in the log, not hidden at debug level.
                log.exception(f"error in {getattr(fn, '__name__', fn)!s}")
            return False
        if ms and ms > 0:
            GLib.timeout_add(ms, once)
        else:
            GLib.idle_add(once)


# ── First-run component setup (Piper engine + voices + faster-whisper) ───────

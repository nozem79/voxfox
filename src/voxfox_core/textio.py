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

"""voxfox_core.textio — Text in and out of other programs: reading the
selected text, the clipboard, and typing or pasting text.
"""

import subprocess, threading, time
from .common import IS_WAYLAND, have_command, log
from .stt import WHISPER_TYPE_LIMIT


# ── Text selection (primary clipboard on X11, regular clipboard on Wayland) ──
def get_selection():
    """Read the currently selected text. Tries primary first (X11 + some Wayland
    compositors), then regular clipboard. Empty string when nothing usable."""
    # X11 / XWayland: primary selection is set automatically when you select text.
    if have_command("xclip"):
        try:
            r = subprocess.run(["xclip", "-selection", "primary", "-out"],
                               capture_output=True, text=True, timeout=1.0)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    # Wayland: many compositors support primary via wl-paste --primary.
    if have_command("wl-paste"):
        for args in (["wl-paste", "--primary", "--no-newline"],
                     ["wl-paste", "--no-newline"]):
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=1.0)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except Exception:
                continue
    return ""


def _clipboard_get():
    """Return current clipboard contents (best effort, empty string on failure)."""
    if IS_WAYLAND and have_command("wl-paste"):
        try:
            r = subprocess.run(["wl-paste", "--no-newline"],
                               capture_output=True, text=True, timeout=1.0)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
    if have_command("xclip"):
        try:
            r = subprocess.run(["xclip", "-selection", "clipboard", "-out"],
                               capture_output=True, text=True, timeout=1.0)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
    return ""


def clipboard_set(text):
    """Set clipboard. Returns True on success."""
    data = text.encode("utf-8")
    if IS_WAYLAND and have_command("wl-copy"):
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(data, timeout=3.0)
            return p.returncode == 0
        except Exception:
            pass
    if have_command("xclip"):
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard", "-in"],
                                 stdin=subprocess.PIPE)
            p.communicate(data, timeout=3.0)
            return p.returncode == 0
        except Exception:
            pass
    return False


def _type_text(text):
    """Type characters one by one at the keyboard focus. Returns True on success."""
    # X11 / XWayland: xdotool works everywhere xdotool is installed.
    if have_command("xdotool"):
        try:
            r = subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "1", "--", text],
                check=False, timeout=15.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    # Pure Wayland: wtype is the native equivalent of `xdotool type`.
    if have_command("wtype"):
        try:
            r = subprocess.run(["wtype", "--", text], check=False, timeout=15.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    # Last resort: ydotool. Requires the ydotoold service to be running.
    if have_command("ydotool"):
        try:
            r = subprocess.run(["ydotool", "type", "--", text],
                               check=False, timeout=15.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def _send_paste_shortcut():
    """Send Ctrl+V to the focused window. Returns True on success."""
    if have_command("xdotool"):
        try:
            r = subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                               check=False, timeout=3.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    if have_command("wtype"):
        try:
            r = subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
                               check=False, timeout=3.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    if have_command("ydotool"):
        try:
            # ydotool key codes: 29=Left Ctrl, 47=V. ":1" = down, ":0" = up.
            r = subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                               check=False, timeout=3.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def type_or_paste_text(text):
    """Type short text directly; paste longer text via clipboard for speed.

    Returns (ok, message). On Wayland-without-typer setups falls back to
    'clipboard only' so the user can paste manually.

    Clipboard discipline: we only touch the clipboard when paste mode is
    actually needed (long text, or typing failed). The previous clipboard
    is restored 100 ms after the paste — long enough for the target app
    to process Ctrl+V, short enough to avoid the bug where the user
    pastes the transcription somewhere by accident a moment later.
    """
    if not text:
        return False, "Empty"
    try:
        # Short text: prefer direct keystroke injection.
        if len(text) <= WHISPER_TYPE_LIMIT:
            if _type_text(text):
                return True, "ok"
            # Typing failed (likely pure Wayland without wtype/ydotool).
            # Fall through to clipboard mode.
            log.warning("type failed, falling back to clipboard")

        # Long text — or short text on a system without a typer — uses
        # the clipboard and sends Ctrl+V.
        old = _clipboard_get()
        if not clipboard_set(text):
            return False, "Could not set clipboard"
        pasted = _send_paste_shortcut()

        if pasted:
            # Restore the previous clipboard shortly after the paste so the
            # transcription doesn't linger and get pasted elsewhere later.
            def _restore():
                time.sleep(0.1)
                try:
                    clipboard_set(old)
                except Exception:
                    pass
            threading.Thread(target=_restore, daemon=True).start()
            return True, "ok"
        # Couldn't trigger the paste — leave the transcription on the
        # clipboard so the user can paste it manually. Deliberately do NOT
        # restore the old clipboard here; that would wipe the text the user
        # still needs.
        return True, "in clipboard (press Ctrl+V)"
    except Exception as e:
        return False, str(e)


__all__ = [
    "get_selection",
    "_clipboard_get",
    "clipboard_set",
    "_type_text",
    "_send_paste_shortcut",
    "type_or_paste_text",
]

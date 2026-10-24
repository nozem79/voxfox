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

"""voxfox_ui.preferences.window

The settings window: the list of sections on the left and the shared
save logic.
"""


import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import set_accessible_label  # noqa: E402
from voxfox_ui.preferences.languages import LanguagesSection  # noqa: E402
from voxfox_ui.preferences.pronunciation import PronunciationSection  # noqa: E402
from voxfox_ui.preferences.dictation import DictationSection  # noqa: E402
from voxfox_ui.preferences.ai import AiSection  # noqa: E402
from voxfox_ui.preferences.shortcuts import ShortcutsSection  # noqa: E402
from voxfox_ui.preferences.appearance import AppearanceSection  # noqa: E402
from voxfox_ui.preferences.general import GeneralSection  # noqa: E402


class PreferencesWindow(LanguagesSection, PronunciationSection,
                        DictationSection, AiSection, ShortcutsSection,
                        AppearanceSection, GeneralSection, Gtk.Window):
    """the settings window: the list of sections on the left and the shared
    save logic.
    """

    def __init__(self, win):
        super().__init__(title=_("Settings"), transient_for=win, modal=True)
        self.win   = win
        self.state = win.state
        self.set_default_size(460, 480)
        self._dl_cancellers = {}

        # Voice catalogue (cached online list); fall back gracefully offline.
        self.all_voices = {}
        try:
            self.all_voices = vf.fetch_voices() or {}
        except Exception as e:
            log.debug(f"fetch_voices failed: {e}")

        # A list of sections on the left instead of tabs along the top. Nine
        # tabs did not fit in the window, so the last ones (Web page,
        # Interface, Misc) hid behind a scroll arrow; a list always shows
        # every section, and reads naturally with a screen reader.
        self.set_default_size(820, 600)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.NONE)
        stack.set_hexpand(True)

        def _pad_frames(widget):
            """Give every frame the same inner margin. Some groups had
            none, so their text touched the frame's edge."""
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.Frame):
                    inner = child.get_child()
                    if inner is not None and inner.get_margin_start() == 0:
                        for m in ("top", "bottom", "start", "end"):
                            getattr(inner, f"set_margin_{m}")(10)
                _pad_frames(child)
                child = child.get_next_sibling()

        def _page(*children):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            for m in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{m}")(14)
            for c in children:
                box.append(c)
            _pad_frames(box)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_vexpand(True)
            sw.set_child(box)
            return sw

        def _lang_title(slot, n):
            lang = self.state[slot].get("lang", "")
            native = vf.piper_lang_native(lang) if lang else ""
            return f"{_('Language')} {n}: {native}" if native else f"{_('Language')} {n}"

        pages = [
            ("slot1", _lang_title("slot1", 1),
             _page(self._slot_group("slot1", _("Language 1")))),
            ("slot2", _lang_title("slot2", 2),
             _page(self._slot_group("slot2", _("Language 2")))),
            ("pron", _("Pronunciation"), _page(self._pronunciation_group())),
            ("dictation", _("Dictation"), _page(self._whisper_group())),
            ("ai", _("Translation and AI"),
             _page(self._translate_group(), self._webread_group())),
            ("shortcuts", _("Shortcuts"), _page(self._shortcuts_group())),
            ("look", _("Appearance"), _page(self._interface_group())),
            ("general", _("General"),
             _page(self._misc_group(), self._documents_group())),
        ]
        for name, title, page in pages:
            stack.add_titled(page, name, title)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(stack)
        sidebar.set_size_request(190, -1)
        set_accessible_label(sidebar, _("Settings sections"))

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.append(sidebar)
        root.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        root.append(stack)
        self._stack = stack
        self.set_child(root)

        self.connect("close-request", self._on_close)

    def _on_close(self, *_a):
        if getattr(self, "_shortcuts_inhibited", False):
            self._stop_capture()
        self._flush_pending_state_save()
        self._save_pron()
        self.win.reload_active_controls()
        return False

    def _save_state_debounced(self):
        """Write self.state to disk after a short pause in editing rather
        than on every single change. Typing into an API-key field fires a
        "changed" signal per keystroke; without this, that meant one full
        state-file write (with fsync) per character."""
        pending = getattr(self, "_save_state_timeout_id", None)
        if pending:
            GLib.source_remove(pending)

        def flush():
            self._save_state_timeout_id = None
            vf.save_state(self.state)
            return False
        self._save_state_timeout_id = GLib.timeout_add(500, flush)

    def _flush_pending_state_save(self):
        """Write immediately if a debounced save is still waiting.

        The pending GLib timeout itself would still fire even after this
        window closes (it lives on the main context, not on the window),
        so simply closing Settings never loses an edit. The gap this
        closes is narrower: quitting VoxFox entirely within that same
        500ms window ends the main loop before the timeout gets its turn,
        which would otherwise discard whatever was typed last."""
        pending = getattr(self, "_save_state_timeout_id", None)
        if pending:
            GLib.source_remove(pending)
            self._save_state_timeout_id = None
            vf.save_state(self.state)

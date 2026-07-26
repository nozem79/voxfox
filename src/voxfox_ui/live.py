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

"""voxfox_ui.live — The free-floating live transcription window.

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import _a11y  # noqa: E402


class LiveTranscribeWindow(Gtk.Window):
    """A freely resizable window that shows live speech transcription in
    large, adjustable text — usable as personal captions for people who
    understand written language better than spoken language (e.g. some
    forms of aphasia, or hearing loss). Content is ephemeral: nothing is
    saved to the history, and closing the window discards the text."""

    def __init__(self, parent):
        super().__init__(title=_("Live transcription"))
        self.parent = parent
        self.state = parent.state
        self.set_default_size(560, 340)
        self._stop_evt = threading.Event()

        header = Gtk.HeaderBar()
        smaller = Gtk.Button(label="A\u2212")
        smaller.set_tooltip_text(_("Smaller text"))
        _a11y(smaller, _("Smaller text"))
        smaller.connect("clicked", lambda *_a: self._change_font(-2))
        larger = Gtk.Button(label="A+")
        larger.set_tooltip_text(_("Larger text"))
        _a11y(larger, _("Larger text"))
        larger.connect("clicked", lambda *_a: self._change_font(+2))
        header.pack_end(larger)
        header.pack_end(smaller)
        self.set_titlebar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tv = Gtk.TextView(editable=False, cursor_visible=False,
                               wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for m in ("top", "bottom", "left", "right"):
            getattr(self.tv, f"set_{m}_margin")(14)
        self._css = Gtk.CssProvider()
        self.tv.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._apply_font()
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.tv)
        outer.append(scroller)

        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(foot, f"set_margin_{m}")(8)
        sens_lbl = Gtk.Label(label=_("Sensitivity"))
        sens_lbl.add_css_class("dim-label")
        self._sens = Gtk.DropDown.new_from_strings(
            [_("High"), _("Medium"), _("Low")])
        self._sens_keys = ["high", "medium", "low"]
        cur = self.state.get("live_sensitivity", "high")
        self._sens.set_selected(self._sens_keys.index(cur)
                                if cur in self._sens_keys else 0)
        self._sens.set_tooltip_text(
            _("How easily speech is detected. High suits quiet laptop "
              "microphones."))
        self._sens.connect("notify::selected", self._on_sensitivity)
        clear = Gtk.Button(label=_("Clear"))
        clear.connect("clicked",
                      lambda *_a: self.tv.get_buffer().set_text(""))
        copy = Gtk.Button(label=_("Copy"))
        copy.connect("clicked", self._on_copy)
        self.status = Gtk.Label(label=_("Listening..."), xalign=1.0)
        self.status.set_hexpand(True)
        self.status.add_css_class("dim-label")
        foot.append(clear)
        foot.append(copy)
        foot.append(sens_lbl)
        foot.append(self._sens)
        foot.append(self.status)
        outer.append(foot)
        self.set_child(outer)

        self.connect("close-request", self._on_close)
        threading.Thread(target=self._worker, daemon=True).start()

    # ── font ──
    def _apply_font(self):
        px = int(self.state.get("live_font_px", 22))
        px = max(14, min(56, px))
        self._css.load_from_data(
            f"textview, textview text {{ font-size: {px}px; }}".encode())

    def _change_font(self, delta):
        px = int(self.state.get("live_font_px", 22)) + delta
        self.state["live_font_px"] = max(14, min(56, px))
        vf.save_state(self.state)
        self._apply_font()

    def _on_sensitivity(self, *_a):
        key = self._sens_keys[self._sens.get_selected()]
        self.state["live_sensitivity"] = key
        vf.save_state(self.state)
        # Restart the listening loop so the new sensitivity applies at once.
        self._stop_evt.set()
        self._stop_evt = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    # ── worker ──
    def _worker(self):
        w = self.state.get("whisper", {})
        lang_hint = vf._whisper_lang_code(
            self.state.get(self.state.get("active_slot", "slot1"), {})
            .get("lang", ""))
        try:
            ok, msg = vf.live_transcribe_loop(
                on_text=lambda t, pause: GLib.idle_add(
                    self._append, t, pause),
                mic_id=w.get("mic_id", ""),
                model_name=w.get("model", "small"),
                language_hint=lang_hint,
                whisper_cfg=w,
                stop_evt=self._stop_evt,
                status_cb=lambda st: GLib.idle_add(self._set_state_label,
                                                   st),
                sensitivity=self.state.get("live_sensitivity", "high"))
        except Exception as e:
            # Never die silently: a crashed loop must be visible, not an
            # eternal "Listening..." with a dead microphone behind it.
            log.error(f"live transcription loop crashed: {e}")
            ok, msg = False, f"{_('Error')}: {e}"
        if not ok and not self._stop_evt.is_set():
            GLib.idle_add(self.status.set_text, msg)

    # Silence longer than this before a sentence starts a new paragraph,
    # so a long pause in speech reads like one in the transcript too.
    PARAGRAPH_PAUSE_S = 2.5

    def _append(self, text, pause_before=0.0):
        buf = self.tv.get_buffer()
        end = buf.get_end_iter()
        prefix = ""
        if buf.get_char_count() > 0:
            prefix = ("\n\n" if pause_before >= self.PARAGRAPH_PAUSE_S
                      else "")
        buf.insert(end, prefix + text + "\n")
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self.tv.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)
        buf.delete_mark(mark)
        return False

    def _set_state_label(self, st):
        if st == "skipped":
            self.status.set_text(_("Falling behind — a sentence was skipped"))
        elif st == "listening":
            self.status.set_text(_("Listening..."))
        else:
            self.status.set_text(_("Transcribing..."))
        return False

    def _on_copy(self, *_a):
        buf = self.tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if text.strip():
            vf._clipboard_set(text)

    # ── lifecycle ──
    def _on_close(self, *_a):
        self._stop_evt.set()
        self.parent._live_window_closed()
        return False

    def shutdown(self):
        """Programmatic close (menu toggled off)."""
        self._stop_evt.set()
        self.destroy()



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

"""voxfox_ui.main_window.dictation

Dictation: recording, transcribing, confirming and typing the text.
"""

import os
import threading
import tempfile

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import btn_set_text  # noqa: E402


class DictationActions:
    """Dictation: recording, transcribing, confirming and typing the text.
    """

    def do_whisper(self):
        if self.whisper_on:
            if self._record_stop_event:
                self._record_stop_event.set()
            self.set_status(_("Stopping..."), duration=0)
            return
        self.whisper_on = True
        btn_set_text(self.whisper_btn, _("Stop"))
        self.whisper_btn.add_css_class("destructive-action")
        self.whisper_btn.add_css_class("voxfox-recording")
        self.set_status(_("Recording..."), duration=0)
        self._record_stop_event = threading.Event()
        threading.Thread(target=self._whisper_worker, daemon=True).start()

    def _whisper_worker(self):
        w = self.state["whisper"]
        lang_hint = vf.whisper_lang_code(self._active_cfg().get("lang", ""))
        wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                             dir=vf.ram_tmpdir()) as f:
                wav_path = f.name
            ok, msg = vf.record_audio(
                wav_path, mic_id=w.get("mic_id", ""),
                max_seconds=w.get("max_record_seconds", vf.WHISPER_MAX_SECONDS),
                stop_evt=self._record_stop_event)
            self.root.after(0, self.set_status, _("Transcribing..."), 0)
            if not ok:
                self.root.after(0, self.set_status, f"{_('Recording failed')}: {msg}")
                return
            text, err = vf.transcribe(
                wav_path, w.get("model", "small"), language_hint=lang_hint,
                progress_cb=lambda m: self.root.after(0, self.set_status, m, 0),
                whisper_cfg=w,
                frac_cb=lambda fr, lbl=None: self.root.after(
                    0, self.set_progress, fr, lbl))
            if err:
                self.root.after(0, self.set_status, err)
                return
            if not text:
                self.root.after(0, self.set_status, _("No speech detected"))
                return
            if vf.confirm_typing_forced() or \
                    w.get("confirm_before_typing", False):
                # Show the transcription for review before it is typed. The
                # dialog must run on the GUI thread. On Wayland this is not
                # optional: nothing can be typed there, so the dialog is the
                # only place the text is ever shown.
                self.root.after(0, self._confirm_transcription, text)
            else:
                self._deliver_transcription(text)
        except Exception as e:
            log.error(f"Whisper worker: {e}")
            self.root.after(0, self.set_status, f"{_('Error')}: {e}")
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
            self.root.after(0, self.hide_progress)
            self.root.after(0, self._whisper_reset_btn)

    def _deliver_transcription(self, text):
        """Type or paste the (possibly edited) transcription and record it."""
        if not text:
            return
        ok2, msg2 = vf.type_or_paste_text(text)
        if not ok2:
            self.root.after(0, self.set_status,
                            f"{_('Type failed')}: {msg2}")
            return
        vf.add_history("dictate", text)
        preview = text if len(text) <= 40 else text[:40] + "..."
        if msg2 == "ok":
            self.root.after(0, self.set_status, f"✓ {preview}")
        else:
            # type_or_paste_text() couldn't type or auto-paste (e.g. on
            # Wayland without a working keystroke-injection path -- wtype
            # needs virtual-keyboard-unstable-v1, which neither GNOME's
            # Mutter nor KDE's KWin implement). The text IS safe, on the
            # clipboard and already in History; without this the status
            # bar showed the same checkmark either way, giving no hint
            # that a manual paste was actually needed.
            self.root.after(
                0, self.set_status,
                _("Couldn't type automatically — copied to clipboard, "
                  "press Ctrl+V to paste"),
                6000)

    def _confirm_transcription(self, text):
        """Preview dialog shown after dictation when 'Confirm transcription
        before typing' is on. The user can edit the text and copy it to the
        clipboard, then paste it wherever they want with Ctrl+V. Copying
        (rather than typing) avoids the window-focus problem where the text
        would otherwise land in VoxFox's own window."""
        dlg = Gtk.Dialog(title=_("Confirm transcription"), modal=True)
        try:
            dlg.set_transient_for(self)
        except Exception:
            pass
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        cp = dlg.add_button(_("Copy"), Gtk.ResponseType.OK)
        cp.add_css_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.OK)

        box = dlg.get_content_area()
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_spacing(8)
        box.append(Gtk.Label(
            label=_("Review the text, then copy it and paste with Ctrl+V:"),
            xalign=0.0))
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(text)
        tv.set_size_request(360, 120)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(tv)
        scroller.set_min_content_height(120)
        box.append(scroller)

        def on_response(d, resp):
            if resp == Gtk.ResponseType.OK:
                buf = tv.get_buffer()
                edited = buf.get_text(buf.get_start_iter(),
                                      buf.get_end_iter(), False).strip()
                d.destroy()
                if edited:
                    if vf.clipboard_set(edited):
                        vf.add_history("dictate", edited)
                        self.set_status(
                            _("Transcription copied — press Ctrl+V to paste"),
                            8000)
                    else:
                        self.set_status(_("Copy failed"))
                else:
                    self.set_status(_("Cancelled"))
            else:
                d.destroy()
                self.set_status(_("Cancelled"))
        dlg.connect("response", on_response)
        dlg.present()
        return False

    def _whisper_reset_btn(self):
        self.whisper_on = False
        btn_set_text(self.whisper_btn, _("Dictate"))
        self.whisper_btn.remove_css_class("destructive-action")
        self.whisper_btn.remove_css_class("voxfox-recording")

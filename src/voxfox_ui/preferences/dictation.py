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

"""voxfox_ui.preferences.dictation

Dicteren: speech recognition model, microphone, and the remote server.
"""

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.setup import pip_install, have_pip  # noqa: E402
from voxfox_ui.widgets import set_accessible_label, make_dropdown, dropdown_value, hide_progress_bar, set_dropdown_items, set_progress_bar  # noqa: E402
from voxfox_ui.preferences.helpers import _whisper_model_hint  # noqa: E402


class DictationSection:
    """Dicteren: speech recognition model, microphone, and the remote server.
    """

    # ── Whisper: model + mic + confirm + backend + remote API ────────────────
    def _whisper_group(self):
        w = self.state["whisper"]
        frame = Gtk.Frame(label=_("Whisper (speech-to-text)"))
        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(10)
        frame.set_child(grid)
        r = 0

        # Model + download
        grid.attach(Gtk.Label(label=_("Model:"), xalign=0), 0, r, 1, 1)
        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.model_dd = make_dropdown(vf.WHISPER_MODELS, w.get("model", "small"))
        self.model_dd.set_hexpand(True)
        set_accessible_label(self.model_dd, _("Whisper model"))
        self.model_dd.connect("notify::selected", self._on_model_changed)
        dl_btn = Gtk.Button(icon_name="document-save-symbolic")
        dl_btn.set_tooltip_text(_("Download the selected model now"))
        set_accessible_label(dl_btn, _("Download the selected Whisper model"))
        dl_btn.connect("clicked", self._on_model_download)
        model_box.append(self.model_dd)
        model_box.append(dl_btn)
        grid.attach(model_box, 1, r, 1, 1)
        # What the chosen model is good for, in plain words.
        self.model_hint = Gtk.Label(xalign=0.0)
        self.model_hint.set_wrap(True)
        self.model_hint.add_css_class("dim-label")
        self.model_hint.set_text(_whisper_model_hint(w.get("model", "small")))
        grid.attach(self.model_hint, 0, r + 1, 2, 1)
        r += 1
        self.model_status = Gtk.Label(xalign=0.0)
        self.model_status.add_css_class("dim-label")
        self.model_status.set_wrap(True)
        grid.attach(self.model_status, 0, r + 1, 2, 1)
        # Shown only while faster-whisper itself is missing. Runs the
        # same per-user pip install as the setup wizard, so nobody has
        # to open a terminal -- and the terminal route no longer works
        # as advertised on Ubuntu 24.04 anyway.
        self.install_btn = Gtk.Button(label=_("Install speech recognition"))
        self.install_btn.set_tooltip_text(
            _("Installs faster-whisper for your user account"))
        set_accessible_label(self.install_btn, _("Install speech recognition"))
        self.install_btn.set_halign(Gtk.Align.START)
        self.install_btn.connect("clicked", self._on_install_whisper)
        self.install_btn.set_visible(False)
        # On its own row: sharing the status text's row made the button
        # cover that text ("Speech recogn|Install speech recognition").
        grid.attach(self.install_btn, 0, r + 2, 2, 1)
        # Download progress for the model button, just below the status text.
        self.dl_progress = Gtk.ProgressBar(show_text=True)
        self.dl_progress.set_visible(False)
        grid.attach(self.dl_progress, 0, r + 3, 2, 1)
        self._refresh_model_status()
        r += 4

        # Everything below that is technical goes into an "Advanced"
        # expander at the end; microphone and confirmation stay in view.
        main_grid = grid
        adv_grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        adv_grid.set_margin_top(8)
        grid = adv_grid

        # Compute device (Auto detects an NVIDIA GPU, else CPU).
        grid.attach(Gtk.Label(label=_("Compute:"), xalign=0), 0, r, 1, 1)
        dev = w.get("device", "auto")
        self._dev_values = ["auto", "cpu", "cuda"]
        dev_labels = [_("Auto (GPU if available)"), _("CPU"), _("GPU (NVIDIA)")]
        self.dev_dd = make_dropdown(
            dev_labels, dev_labels[self._dev_values.index(dev)]
            if dev in self._dev_values else dev_labels[0])
        self.dev_dd.set_hexpand(True)
        set_accessible_label(self.dev_dd, _("Compute device"))
        self.dev_dd.set_tooltip_text(
            _("Auto uses an NVIDIA GPU when detected (needs CUDA + cuDNN), "
              "otherwise the CPU. Falls back to CPU if GPU init fails."))
        self.dev_dd.connect("notify::selected", self._on_device_changed)
        grid.attach(self.dev_dd, 1, r, 1, 1)
        self.dev_status = Gtk.Label(xalign=0.0)
        self.dev_status.add_css_class("dim-label")
        self.dev_status.set_text(
            _("NVIDIA GPU detected") if vf.cuda_available()
            else _("no GPU detected — using CPU"))
        grid.attach(self.dev_status, 0, r + 1, 2, 1)
        r += 2

        grid = main_grid
        # Microphone + refresh
        grid.attach(Gtk.Label(label=_("Mic:"), xalign=0), 0, r, 1, 1)
        mic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._mic_options = vf.list_microphones()
        self._mic_labels  = [lbl for (_id, lbl) in self._mic_options]
        cur_id = w.get("mic_id", "")
        cur_lbl = next((lbl for (mid, lbl) in self._mic_options if mid == cur_id),
                       self._mic_labels[0] if self._mic_labels else _("Default"))
        self.mic_dd = make_dropdown(self._mic_labels, cur_lbl)
        self.mic_dd.set_hexpand(True)
        set_accessible_label(self.mic_dd, _("Microphone"))
        self.mic_dd.connect("notify::selected", self._on_mic_changed)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text(_("Refresh microphone list"))
        set_accessible_label(refresh, _("Refresh microphone list"))
        refresh.connect("clicked", self._on_mic_refresh)
        mic_box.append(self.mic_dd)
        mic_box.append(refresh)
        grid.attach(mic_box, 1, r, 1, 1)
        r += 1

        # Confirm before typing. Locked on under Wayland, where nothing
        # can be typed into another application: the dialog is then the
        # only way the user sees the text. The stored preference is left
        # untouched, so it comes back on an X11 session.
        confirm = Gtk.CheckButton(label=_("Confirm transcription before typing"))
        forced = vf.confirm_typing_forced()
        confirm.set_active(forced or bool(w.get("confirm_before_typing", False)))
        if forced:
            confirm.set_sensitive(False)
        else:
            confirm.connect("toggled", self._on_confirm_toggled)
        grid.attach(confirm, 0, r, 2, 1)
        r += 1
        if forced:
            note = Gtk.Label(
                label=_("On Wayland, text cannot be typed into another "
                        "application. Dictation is copied to the clipboard, "
                        "so it is always shown for confirmation first."),
                xalign=0.0)
            note.set_wrap(True)
            note.add_css_class("dim-label")
            grid.attach(note, 0, r, 2, 1)
            r += 1

        grid = adv_grid
        # Maximum recording length — a safety net if dictation is left
        # running by accident (recording then auto-stops on its own).
        grid.attach(Gtk.Label(label=_("Max. recording length:"), xalign=0),
                   0, r, 1, 1)
        max_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.max_rec_spin = Gtk.SpinButton.new_with_range(10, 600, 10)
        self.max_rec_spin.set_value(
            w.get("max_record_seconds", vf.WHISPER_MAX_SECONDS))
        set_accessible_label(self.max_rec_spin, _("Maximum recording length in seconds"))
        self.max_rec_spin.connect("value-changed",
                                 self._on_max_record_changed)
        max_box.append(self.max_rec_spin)
        max_box.append(Gtk.Label(label=_("seconds")))
        grid.attach(max_box, 1, r, 1, 1)
        r += 1
        max_hint = Gtk.Label(xalign=0.0, wrap=True)
        max_hint.add_css_class("dim-label")
        max_hint.set_text(
            _("Recording stops automatically after this long, even if "
              "Speak/Stop is never pressed again — a safety net if "
              "dictation is left running by accident."))
        grid.attach(max_hint, 0, r, 2, 1)
        r += 1

        # Backend
        grid.attach(Gtk.Label(label=_("Backend:"), xalign=0), 0, r, 1, 1)
        self.backend_dd = make_dropdown([_("Local"), _("Remote API")],
                                    _("Remote API") if w.get("backend") == "remote"
                                    else _("Local"))
        self.backend_dd.connect("notify::selected", self._on_backend_changed)
        set_accessible_label(self.backend_dd, _("Whisper backend"))
        grid.attach(self.backend_dd, 1, r, 1, 1)
        r += 1

        # Remote API rows (shown only when backend == remote)
        self.remote_box = Gtk.Grid(row_spacing=6, column_spacing=8)
        grid.attach(self.remote_box, 0, r, 2, 1)

        self.url_entry = Gtk.Entry(hexpand=True)
        self.url_entry.set_text(w.get("remote_url", ""))
        self.url_entry.set_placeholder_text("http://host:8000/v1")
        self.url_entry.connect("changed",
                               lambda e: self._save_w("remote_url", e.get_text()))
        self.rmodel_entry = Gtk.Entry(hexpand=True)
        self.rmodel_entry.set_text(w.get("remote_model", ""))
        self.rmodel_entry.connect("changed",
                                  lambda e: self._save_w("remote_model", e.get_text()))
        self.key_entry = Gtk.Entry(hexpand=True)
        self.key_entry.set_text(w.get("remote_api_key", ""))
        self.key_entry.set_visibility(False)
        self.key_entry.set_placeholder_text(_("optional"))
        self.key_entry.connect("changed",
                               lambda e: self._save_w("remote_api_key", e.get_text()))
        test_btn = Gtk.Button(label=_("Test connection"))
        test_btn.connect("clicked", self._on_test_remote)
        self.test_result_lbl = Gtk.Label(xalign=0.0)
        self.test_result_lbl.set_wrap(True)
        self.test_result_lbl.set_selectable(True)

        self.remote_box.attach(Gtk.Label(label=_("URL:"), xalign=0),    0, 0, 1, 1)
        self.remote_box.attach(self.url_entry,                           1, 0, 1, 1)
        self.remote_box.attach(Gtk.Label(label=_("Model:"), xalign=0),  0, 1, 1, 1)
        self.remote_box.attach(self.rmodel_entry,                        1, 1, 1, 1)
        self.remote_box.attach(Gtk.Label(label=_("API key:"), xalign=0), 0, 2, 1, 1)
        self.remote_box.attach(self.key_entry,                           1, 2, 1, 1)
        self.remote_box.attach(test_btn,                                 1, 3, 1, 1)
        self.remote_box.attach(self.test_result_lbl,                     0, 4, 2, 1)
        self.remote_box.set_visible(w.get("backend") == "remote")
        adv = Gtk.Expander(label=_("Advanced"))
        adv.set_child(adv_grid)
        main_grid.attach(adv, 0, r + 1, 2, 1)
        return frame

    def _save_w(self, key, value):
        self.state["whisper"][key] = value
        self._save_state_debounced()

    def _on_max_record_changed(self, spin):
        self._save_w("max_record_seconds", int(spin.get_value()))

    def _refresh_model_status(self):
        name = dropdown_value(self.model_dd)
        if not vf.faster_whisper_available():
            self.model_status.set_text(
                f"\u2717 {_('Speech recognition is not installed yet')}")
            self.install_btn.set_visible(True)
            self.install_btn.set_sensitive(have_pip())
            if not have_pip():
                self.model_status.set_text(
                    f"\u2717 {_('Speech recognition is not installed yet')} "
                    f"({_('python3-pip is missing')})")
            return
        self.install_btn.set_visible(False)
        if vf.whisper_model_is_cached(name):
            self.model_status.set_text(f"✓ {_('model downloaded')}")
        else:
            self.model_status.set_text(_("model not downloaded yet"))

    def _on_model_changed(self, dd, _p):
        self._save_w("model", dropdown_value(dd))
        self.model_hint.set_text(_whisper_model_hint(dropdown_value(dd)))
        self._refresh_model_status()

    def _set_dl_progress(self, fraction, label=None):
        if set_progress_bar(self.dl_progress, fraction, label) >= 1.0:
            GLib.timeout_add(800, self._hide_dl_progress)
        return False

    def _hide_dl_progress(self):
        return hide_progress_bar(self.dl_progress)

    def _on_install_whisper(self, btn):
        """Install faster-whisper (plus the audio libraries dictation
        needs) into the user's own site-packages, with a pulsing bar."""
        btn.set_sensitive(False)
        self.dl_progress.set_visible(True)
        self.dl_progress.set_text(_("Installing..."))

        def worker():
            ok = pip_install(
                ["faster-whisper", "av<19", "sounddevice", "soundfile"],
                progress=lambda m: GLib.idle_add(self.model_status.set_text, m),
                pulse=lambda: GLib.idle_add(self.dl_progress.pulse))

            def done():
                self.dl_progress.set_visible(False)
                btn.set_sensitive(True)
                if ok:
                    # A fresh import picks up the new package; nothing
                    # is cached yet because the import kept failing.
                    self._refresh_model_status()
                    self.win.set_status(_("Speech recognition installed"))
                else:
                    self.model_status.set_text(
                        f"\u2717 {_('Installation failed; see the log')}")
                return False
            GLib.idle_add(done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_model_download(self, _btn):
        name = dropdown_value(self.model_dd)
        self.model_status.set_text(f"⬇ {name}...")

        def worker():
            try:
                _model, err = vf.load_whisper_model(
                    name,
                    progress_cb=lambda m: GLib.idle_add(
                        self.model_status.set_text, m),
                    frac_cb=lambda fr, lbl=None: GLib.idle_add(
                        self._set_dl_progress, fr, lbl))
                if err:
                    GLib.idle_add(self.model_status.set_text, f"✗ {err}")
                else:
                    GLib.idle_add(self._refresh_model_status)
            except Exception as e:
                GLib.idle_add(self.model_status.set_text, f"✗ {e}")
            finally:
                GLib.idle_add(self._hide_dl_progress)
        threading.Thread(target=worker, daemon=True).start()

    def _on_device_changed(self, dd, _p):
        idx = dd.get_selected()
        if 0 <= idx < len(self._dev_values):
            self._save_w("device", self._dev_values[idx])

    def _on_mic_changed(self, dd, _p):
        idx = dd.get_selected()
        if 0 <= idx < len(self._mic_options):
            self._save_w("mic_id", self._mic_options[idx][0])

    def _on_mic_refresh(self, _btn):
        cur_id = self.state["whisper"].get("mic_id", "")
        self._mic_options = vf.list_microphones()
        self._mic_labels  = [lbl for (_id, lbl) in self._mic_options]
        # Keep the current mic selected if it's still present; otherwise fall
        # back to the first entry and tell the user it's gone.
        keep = None
        for _id, lbl in self._mic_options:
            if _id == cur_id and cur_id:
                keep = lbl
                break
        set_dropdown_items(self.mic_dd, self._mic_labels,
                            keep or (self._mic_labels[0]
                                     if self._mic_labels else None))
        if cur_id and keep is None:
            self._save_w("mic_id", self._mic_options[0][0]
                         if self._mic_options else "")
            self.win.set_status(
                _("Previous microphone not found — using the default"))

    def _on_confirm_toggled(self, btn):
        self._save_w("confirm_before_typing", btn.get_active())

    def _on_backend_changed(self, dd, _p):
        remote = dd.get_selected() == 1
        self._save_w("backend", "remote" if remote else "local")
        self.remote_box.set_visible(remote)

    def _on_test_remote(self, _btn):
        url   = self.url_entry.get_text().strip()
        model = self.rmodel_entry.get_text().strip()
        key   = self.key_entry.get_text().strip()
        if not url or not model:
            self.win.set_status(_("Set a URL and model first"))
            return
        self.win.set_status(_("Testing connection…"), duration=0)
        self.test_result_lbl.set_text(_("Testing connection…"))

        def worker():
            import wave
            tmp = os.path.join(vf.ram_tmpdir(), "voxfox_test.wav")
            ok_text = ""
            err = ""
            try:
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(b"\x00\x00" * 16000)
                txt, err = vf.transcribe_remote(tmp, url=url, api_key=key,
                                                model_name=model,
                                                language_hint=None)
                if not err:
                    ok_text = txt.strip() if txt and txt.strip() else _("(no transcription returned)")
            except Exception as e:
                err = str(e)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            if err:
                msg = f"✗ {err}"
            else:
                msg = f"✓ {_('Connection OK')} — {ok_text}"
            def _show(m=msg):
                self.test_result_lbl.set_text(m)
                self.win.set_status(m, 8000)
            GLib.idle_add(_show)
        threading.Thread(target=worker, daemon=True).start()

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

"""voxfox_ui.preferences.languages

Taal 1 and Taal 2: language, speech engine, voice, speed, pitch and the
voice preview.
"""

import threading
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.setup import apply_ui_language  # noqa: E402
from voxfox_ui.widgets import set_accessible_label, make_dropdown, dropdown_value, set_dropdown_items  # noqa: E402
from voxfox_ui.preferences.helpers import _voice_label  # noqa: E402


class LanguagesSection:
    """Taal 1 and Taal 2: language, speech engine, voice, speed, pitch and
    the voice preview.
    """

    # ── per-slot language + engine + voice + speed ───────────────────────────
    def _slot_group(self, slot, title):
        cfg = self.state[slot]
        frame = Gtk.Frame(label=title)
        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(10)
        frame.set_child(grid)

        def row(label, widget, r):
            lbl = Gtk.Label(label=label, xalign=0)
            grid.attach(lbl, 0, r, 1, 1)
            grid.attach(widget, 1, r, 1, 1)
            widget.set_hexpand(True)
            return lbl

        langs = vf.get_languages(self.all_voices)
        if not langs and cfg.get("lang"):
            langs = [cfg["lang"]]
        # Shown in the language itself ("Nederlands", "Deutsch"), the way
        # people know their own language; stored by the English name as before.
        lang_names = [vf.piper_lang_native(lg) or lg for lg in langs]
        lang_dd = make_dropdown(lang_names, lang_names[langs.index(cfg["lang"])]
                            if cfg.get("lang") in langs else None)
        set_accessible_label(lang_dd, f"{title} — {_('Language')}")
        row(_("Language:"), lang_dd, 0)

        # Speech engine. Only offered when speech-dispatcher can be used, or
        # when this slot was already set to it (so the choice stays visible
        # and can be switched back after python3-speechd was removed).
        engines = [vf.ENGINE_PIPER, vf.ENGINE_SPEECHD]
        engine_names = [_("Piper (built-in)"), _("Speech-dispatcher")]
        engine = cfg.get("engine", vf.ENGINE_PIPER)
        if engine not in engines:
            engine = vf.ENGINE_PIPER
        engine_dd = make_dropdown(engine_names, engine_names[engines.index(engine)])
        set_accessible_label(engine_dd, f"{title} — {_('Speech engine')}")
        engine_lbl = row(_("Speech engine:"), engine_dd, 1)
        offer_engine = vf.available() or engine == vf.ENGINE_SPEECHD
        engine_lbl.set_visible(offer_engine)
        engine_dd.set_visible(offer_engine)

        # Piper voice
        voices = sorted(vf.get_voices_for_lang(self.all_voices, cfg.get("lang", "")))
        if not voices:
            voices = sorted(v for v in vf.get_local_voices())
        # The dropdown shows friendly names; voice_keys holds the matching
        # Piper keys in the same order, which is what gets stored.
        voice_keys = list(voices)
        voice_dd = make_dropdown([_voice_label(k) for k in voice_keys],
                             _voice_label(cfg.get("voice", ""))
                             if cfg.get("voice") in voice_keys else None)
        set_accessible_label(voice_dd, f"{title} — {_('Voice')}")
        voice_lbl = row(_("Voice:"), voice_dd, 2)

        # speech-dispatcher module + voice, filled in the background: asking
        # speech-dispatcher may first have to start it.
        sd_module_dd = make_dropdown([cfg.get("sd_module", "")] if cfg.get("sd_module") else [],
                                 cfg.get("sd_module", ""))
        set_accessible_label(sd_module_dd, f"{title} — {_('Module')}")
        sd_module_lbl = row(_("Module:"), sd_module_dd, 3)
        sd_voice_dd = make_dropdown([cfg.get("sd_voice", "")] if cfg.get("sd_voice") else [],
                                cfg.get("sd_voice", ""))
        set_accessible_label(sd_voice_dd, f"{title} — {_('Voice')}")
        sd_voice_lbl = row(_("Voice:"), sd_voice_dd, 4)
        sd_note = Gtk.Label(xalign=0.0)
        sd_note.set_wrap(True)
        sd_note.add_css_class("dim-label")
        grid.attach(sd_note, 0, 5, 2, 1)

        status = Gtk.Label(xalign=0.0)
        status.add_css_class("dim-label")
        # Wrap: a long message (a file path) must not widen the window.
        status.set_wrap(True)
        status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        grid.attach(status, 0, 6, 2, 1)

        speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.5, 2.0, 0.05)
        speed.set_value(float(cfg.get("speed", 1.0)))
        speed.set_draw_value(True)
        row(_("Speed:"), speed, 7)
        set_accessible_label(speed, _("Speed:").rstrip(": "))

        # Pitch in semitones: 0 = the voice's natural pitch, negative = lower,
        # positive = higher. For Piper this is applied in the speech worker by
        # playing at a shifted sample rate and compensating the tempo via
        # Piper's length_scale; speech-dispatcher gets it as its pitch setting.
        pitch = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -12, 12, 1)
        pitch.set_value(float(cfg.get("pitch", 0.0)))
        pitch.set_draw_value(True)
        row(_("Pitch:"), pitch, 8)
        set_accessible_label(pitch, _("Pitch:").rstrip(": "))

        # Preview: hear the slot's current voice, speed and pitch. The text
        # starts as a sample sentence in the slot's language and can be
        # changed; it follows the language for as long as nobody edited it.
        preview_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        preview = Gtk.Entry()
        preview.set_hexpand(True)
        preview.set_text(vf.sample_text_for_lang(cfg.get("lang", "")))
        set_accessible_label(preview, f"{title} — {_('Preview text')}")
        play_btn = Gtk.Button(label=_("Play"))
        set_accessible_label(play_btn, f"{title} — {_('Play preview')}")
        preview_box.append(preview)
        preview_box.append(play_btn)
        row(_("Preview:"), preview_box, 9)

        # Installed modules that the user's own speech-dispatcher settings
        # keep out (Pied writes such a file), with a button to add them.
        # Placed right under the module/voice rows.
        hidden_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hidden_lbl = Gtk.Label(xalign=0.0)
        hidden_lbl.set_wrap(True)
        hidden_btn = Gtk.Button(label=_("Make them available"))
        hidden_btn.set_halign(Gtk.Align.START)
        hidden_box.append(hidden_lbl)
        hidden_box.append(hidden_btn)
        hidden_box.set_visible(False)
        grid.insert_row(6)
        grid.attach(hidden_box, 0, 6, 2, 1)

        # While the code itself refills a dropdown, its "selected" signal
        # must not be taken for a choice by the user.
        filling = {"on": False}

        def fill(dd, items, value):
            filling["on"] = True
            try:
                set_dropdown_items(dd, items, value)
            finally:
                filling["on"] = False

        def using_sd():
            return cfg.get("engine", vf.ENGINE_PIPER) == vf.ENGINE_SPEECHD

        def show_engine_rows():
            sd = using_sd()
            for w in (voice_lbl, voice_dd):
                w.set_visible(not sd)
            for w in (sd_module_lbl, sd_module_dd, sd_voice_lbl, sd_voice_dd, sd_note):
                w.set_visible(sd)
            if not sd:
                hidden_box.set_visible(False)
            if sd:
                status.set_text("")

        gen = {"n": 0}

        hidden = {"names": []}

        def show_hidden(names):
            hidden["names"] = names
            if names and using_sd():
                hidden_lbl.set_text(
                    _("These speech modules are installed but hidden by your "
                      "speech-dispatcher settings: {names}. That happens when "
                      "another program, such as Pied, wrote its own settings "
                      "file.").format(names=", ".join(names)))
                hidden_box.set_visible(True)
            else:
                hidden_box.set_visible(False)

        def on_make_available(_b):
            ok, detail = vf.enable_hidden_modules(list(hidden["names"]))
            if not ok:
                hidden_lbl.set_text(_("Could not change the speech-dispatcher "
                                      "settings") + f": {detail}")
                return
            vf.restart_speechd()
            hidden_box.set_visible(False)
            status.set_text(_("Added to your speech-dispatcher settings. The "
                              "old settings were saved as {path}.").format(path=detail))
            # speech-dispatcher starts again on the next connection.
            GLib.timeout_add(800, lambda: (load_sd(), False)[1])

        hidden_btn.connect("clicked", on_make_available)

        def load_sd(only_voices=False):
            """Ask speech-dispatcher for modules and voices in a thread.
            A newer request makes the answer to an older one irrelevant."""
            gen["n"] += 1
            my = gen["n"]
            if not vf.available():
                sd_note.set_text(_("Speech-dispatcher cannot be used: its Python "
                                   "support (python3-speechd) is not installed. "
                                   "This slot speaks with Piper until it is."))
                return
            sd_note.set_text(_("Asking speech-dispatcher..."))
            lang = cfg.get("lang", "")
            module = cfg.get("sd_module", "")

            def work():
                modules = None if only_voices else vf.list_modules()
                if modules is not None:
                    names = vf.hidden_modules()
                    GLib.idle_add(lambda: (my == gen["n"] and show_hidden(names), False)[1])
                m = module
                if modules is not None:
                    if not modules:
                        GLib.idle_add(apply, my, [], "", [])
                        return
                    if m not in modules:
                        m = "voxin" if "voxin" in modules else (
                            "espeak-ng" if "espeak-ng" in modules else modules[0])
                GLib.idle_add(apply, my, modules, m, vf.list_voices(m, lang))
            threading.Thread(target=work, daemon=True).start()

        def apply(my, modules, module, voices_):
            if my != gen["n"]:
                return False
            if modules is not None:
                if not modules:
                    sd_note.set_text(_("Speech-dispatcher could not be reached, or "
                                       "it has no speech modules installed."))
                    fill(sd_module_dd, [], "")
                    fill(sd_voice_dd, [], "")
                    return False
                fill(sd_module_dd, modules, module)
            voice = cfg.get("sd_voice", "")
            if voice not in voices_:
                voice = voices_[0] if voices_ else ""
            fill(sd_voice_dd, voices_, voice)
            changed = (cfg.get("sd_module") != module or cfg.get("sd_voice") != voice)
            cfg["sd_module"], cfg["sd_voice"] = module, voice
            if changed:
                vf.save_state(self.state)
            sd_note.set_text(_("Speed and pitch are passed on to the speech "
                               "module. How strongly they work differs per "
                               "module."))
            return False

        preview_state = {"default": preview.get_text(), "playing": False,
                         "started": 0.0, "heard": False}

        def preview_done():
            if preview_state["playing"]:
                if vf.is_speaking():
                    preview_state["heard"] = True
                    return True           # keep polling
                # speak() can take a moment to begin (it first lets earlier
                # speech wind down), so not speaking YET is not "finished".
                if (not preview_state["heard"]
                        and time.monotonic() - preview_state["started"] < 3.0):
                    return True
            preview_state["playing"] = False
            play_btn.set_label(_("Play"))
            return False

        def on_play(_b):
            if preview_state["playing"]:
                vf.stop_speaking()
                preview_state["playing"] = False
                play_btn.set_label(_("Play"))
                return
            text = preview.get_text().strip() or preview_state["default"]
            if (not using_sd() and cfg.get("voice")
                    and cfg["voice"] not in vf.get_local_voices()):
                status.set_text(_("This voice has not been downloaded yet."))
                return
            preview_state.update(playing=True, heard=False,
                                 started=time.monotonic())
            play_btn.set_label(_("Stop"))
            # speak() may wait for earlier speech to wind down: off the GUI thread.
            threading.Thread(target=vf.speak, args=(text, dict(cfg)),
                             daemon=True).start()
            GLib.timeout_add(250, preview_done)

        play_btn.connect("clicked", on_play)
        preview.connect("activate", on_play)   # Enter in the text field plays too

        def follow_language(lang):
            """Switch the sample sentence to the new language, unless the
            user typed their own text."""
            if preview.get_text() == preview_state["default"]:
                preview_state["default"] = vf.sample_text_for_lang(lang)
                preview.set_text(preview_state["default"])
            else:
                preview_state["default"] = vf.sample_text_for_lang(lang)

        def on_lang(dd, _p):
            if filling["on"]:
                return
            idx = dd.get_selected()
            if not 0 <= idx < len(langs):
                return
            lang = langs[idx]
            cfg["lang"] = lang
            # Keep the section list on the left in step ("Language 1: ...").
            stack = getattr(self, "_stack", None)
            if stack is not None and stack.get_child_by_name(slot) is not None:
                n = 1 if slot == "slot1" else 2
                stack.get_page(stack.get_child_by_name(slot)).set_title(
                    f"{_('Language')} {n}: {vf.piper_lang_native(lang)}")
            follow_language(lang)
            keys = sorted(vf.get_voices_for_lang(self.all_voices, lang))
            local = vf.get_local_voices()
            chosen = vf.best_voice_for_lang(keys, local, lang)
            cfg["voice"] = chosen
            vf.save_state(self.state)
            voice_keys[:] = keys
            fill(voice_dd, [_voice_label(k) for k in keys],
                 _voice_label(chosen) if chosen else None)
            if chosen and chosen not in local and not using_sd():
                self._download_voice_async(slot, chosen, status)
            elif not using_sd():
                status.set_text("")
            if using_sd():
                load_sd(only_voices=True)
            if slot == "slot1":
                apply_ui_language(lang)
                self.win.rebuild_ui()

        def on_engine(dd, _p):
            if filling["on"]:
                return
            idx = dd.get_selected()
            new = engines[idx] if 0 <= idx < len(engines) else vf.ENGINE_PIPER
            if new == cfg.get("engine", vf.ENGINE_PIPER):
                return
            cfg["engine"] = new
            vf.save_state(self.state)
            show_engine_rows()
            if new == vf.ENGINE_SPEECHD:
                load_sd()
            elif cfg.get("voice") and cfg["voice"] not in vf.get_local_voices():
                self._download_voice_async(slot, cfg["voice"], status)

        def on_voice(dd, _p):
            if filling["on"]:
                return
            idx = dd.get_selected()
            voice = voice_keys[idx] if 0 <= idx < len(voice_keys) else ""
            if not voice:
                return
            cfg["voice"] = voice
            vf.save_state(self.state)
            if voice not in vf.get_local_voices():
                self._download_voice_async(slot, voice, status)
            else:
                status.set_text("")

        def on_sd_module(dd, _p):
            if filling["on"]:
                return
            module = dropdown_value(dd)
            if not module or module == cfg.get("sd_module"):
                return
            cfg["sd_module"] = module
            cfg["sd_voice"] = ""
            vf.save_state(self.state)
            load_sd(only_voices=True)

        def on_sd_voice(dd, _p):
            if filling["on"]:
                return
            voice = dropdown_value(dd)
            if voice and voice != cfg.get("sd_voice"):
                cfg["sd_voice"] = voice
                vf.save_state(self.state)

        def on_speed(sc):
            cfg["speed"] = round(sc.get_value(), 2)
            vf.save_state(self.state)

        def on_pitch(sc):
            cfg["pitch"] = round(sc.get_value(), 1)
            vf.save_state(self.state)

        lang_dd.connect("notify::selected", on_lang)
        engine_dd.connect("notify::selected", on_engine)
        voice_dd.connect("notify::selected", on_voice)
        sd_module_dd.connect("notify::selected", on_sd_module)
        sd_voice_dd.connect("notify::selected", on_sd_voice)
        speed.connect("value-changed", on_speed)
        pitch.connect("value-changed", on_pitch)

        show_engine_rows()
        if using_sd():
            load_sd()
        # For tests and for the rest of this page: the widgets of this slot.
        self._slot_widgets = getattr(self, "_slot_widgets", {})
        self._slot_widgets[slot] = {
            "lang": lang_dd, "engine": engine_dd, "voice": voice_dd,
            "sd_module": sd_module_dd, "sd_voice": sd_voice_dd,
            "sd_note": sd_note, "status": status,
            "preview": preview, "play": play_btn,
            "hidden_box": hidden_box, "hidden_label": hidden_lbl,
            "hidden_button": hidden_btn,
        }
        return frame

    def _download_voice_async(self, slot, voice, status_label):
        prev = self._dl_cancellers.get(slot)
        if prev is not None:
            prev.set()
        cancel = threading.Event()
        self._dl_cancellers[slot] = cancel

        def worker():
            GLib.idle_add(status_label.set_text, f"⬇ {voice}...")
            ok, msg = vf.download_voice(voice, cancel_evt=cancel)
            def done():
                if ok:
                    status_label.set_text(f"✓ {voice}")
                elif msg != "cancelled":
                    status_label.set_text(f"✗ {msg}")
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

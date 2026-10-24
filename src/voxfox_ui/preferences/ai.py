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

"""voxfox_ui.preferences.ai

Vertalen en AI: translation and web page reading through Ollama, and
installing Ollama.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import set_accessible_label, hide_progress_bar, set_progress_bar  # noqa: E402


class AiSection:
    """Vertalen en AI: translation and web page reading through Ollama, and
    installing Ollama.
    """

    def _webread_group(self):
        """Experimental 'read web page' settings: stage 1 (AT-SPI extraction)
        is always on; here the user configures stage 2 (Ollama) — off, filter
        (keep original sentences) or summarize — plus the server URL/model."""
        frame = Gtk.Frame(label=_("Web page"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)
        wr = self.state.setdefault("webread", {})

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("Reads a web page aloud (experimental). Select the "
                        "page's address (Ctrl+L in the browser) and press the "
                        "shortcut — VoxFox fetches the page itself. Menus, "
                        "banners and sidebars are always skipped; optionally "
                        "an AI (Ollama) filters the remaining text further or "
                        "summarizes it."))
        box.append(desc)

        self.webread_ai_chk = Gtk.CheckButton(
            label=_("Use AI (Ollama) to clean up the page text"))
        self.webread_ai_chk.set_active(bool(wr.get("use_ollama")))
        self.webread_ai_chk.connect("toggled", self._on_webread_changed)
        box.append(self.webread_ai_chk)

        # Everything below only matters once "Use AI" is on -- collapsed
        # into one box so it can be shown/hidden as a unit instead of
        # cluttering the tab with irrelevant fields when AI mode is off.
        self.webread_ai_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.webread_ai_box.set_visible(bool(wr.get("use_ollama")))
        box.append(self.webread_ai_box)

        mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mrow.append(Gtk.Label(label=_("AI mode:"), xalign=0))
        self.webread_mode_dd = Gtk.DropDown.new_from_strings(
            [_("Filter only (keep the original sentences)"), _("Summarize")])
        self.webread_mode_dd.set_selected(
            1 if wr.get("mode") == "summary" else 0)
        self.webread_mode_dd.connect("notify::selected",
                                     self._on_webread_changed)
        mrow.append(self.webread_mode_dd)
        self.webread_ai_box.append(mrow)

        urow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        urow.append(Gtk.Label(label=_("URL:"), xalign=0))
        self.webread_url = Gtk.Entry(hexpand=True)
        self.webread_url.set_text(wr.get("url") or vf.DEFAULT_OLLAMA_URL)
        self.webread_url.connect("changed", self._on_webread_changed)
        urow.append(self.webread_url)
        self.webread_ai_box.append(urow)

        krow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        krow.append(Gtk.Label(label=_("API key:"), xalign=0))
        self.webread_key = Gtk.Entry(hexpand=True)
        self.webread_key.set_visibility(False)
        self.webread_key.set_text(wr.get("api_key") or "")
        self.webread_key.set_placeholder_text(_("optional"))
        self.webread_key.connect("changed", self._on_webread_changed)
        krow.append(self.webread_key)
        self.webread_ai_box.append(krow)

        mdrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mdrow.append(Gtk.Label(label=_("Model:"), xalign=0))
        self.webread_model = Gtk.Entry(hexpand=True)
        self.webread_model.set_text(wr.get("model") or vf.DEFAULT_OLLAMA_MODEL)
        self.webread_model.connect("changed", self._on_webread_changed)
        mdrow.append(self.webread_model)
        test = Gtk.Button(label=_("Test connection"))
        test.connect("clicked", self._on_webread_test)
        mdrow.append(test)
        self.webread_ai_box.append(mdrow)

        self.webread_status = Gtk.Label(xalign=0.0, wrap=True)
        self.webread_status.add_css_class("dim-label")
        self.webread_ai_box.append(self.webread_status)

        hint = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        hint.add_css_class("dim-label")
        hint.set_text(_("Requires a running Ollama with a downloaded model, "
                        "e.g.: ollama pull llama3.2"))
        self.webread_ai_box.append(hint)
        return frame

    def _translate_group(self):
        """Translate & read: one OpenAI-compatible endpoint (a local Ollama
        server or a remote API) with a model name and an optional API key.
        The target language is always the UI language (follows Language 1)."""
        frame = Gtk.Frame(label=_("Translate & read"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)
        tr = self.state.setdefault("translate", {})

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("Translates the selected text into the language of "
                        "{lang1} and reads it aloud with that voice. Works "
                        "with a local Ollama server or any OpenAI-compatible "
                        "API.").format(lang1=_("Language 1")))
        box.append(desc)
        # Where the translation server is and how to reach it: needed only
        # for a remote server, so it sits under "Advanced" at the end.
        conn = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        conn.set_margin_top(8)

        urow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        urow.append(Gtk.Label(label=_("URL:"), xalign=0))
        self.trans_url = Gtk.Entry(hexpand=True)
        self.trans_url.set_placeholder_text(vf.DEFAULT_TRANSLATE["url"])
        self.trans_url.set_text(tr.get("url") or vf.DEFAULT_TRANSLATE["url"])
        self.trans_url.connect("changed", self._on_translate_changed)
        urow.append(self.trans_url)
        conn.append(urow)

        mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mrow.append(Gtk.Label(label=_("Model:"), xalign=0))
        self.trans_model = Gtk.Entry(hexpand=True)
        self.trans_model.set_text(tr.get("model")
                                  or vf.DEFAULT_TRANSLATE["model"])
        self.trans_model.connect("changed", self._on_translate_changed)
        mrow.append(self.trans_model)
        box.append(mrow)

        # "Discover" fills suggestions on this SAME field (via
        # Gtk.EntryCompletion) rather than a second, separate picker --
        # one place to set the model, whether typed or picked.
        self._trans_completion_store = Gtk.ListStore(str)
        trans_completion = Gtk.EntryCompletion()
        trans_completion.set_model(self._trans_completion_store)
        trans_completion.set_text_column(0)
        trans_completion.set_minimum_key_length(0)
        trans_completion.set_popup_completion(True)
        self.trans_model.set_completion(trans_completion)

        drow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        discover = Gtk.Button(label=_("Discover installed models"))
        discover.connect("clicked", self._on_translate_discover)
        drow.append(discover)
        box.append(drow)

        krow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        krow.append(Gtk.Label(label=_("API key:"), xalign=0))
        self.trans_key = Gtk.Entry(hexpand=True)
        self.trans_key.set_visibility(False)
        self.trans_key.set_placeholder_text(_("optional"))
        self.trans_key.set_text(tr.get("api_key") or "")
        self.trans_key.connect("changed", self._on_translate_changed)
        krow.append(self.trans_key)
        conn.append(krow)

        trow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        test = Gtk.Button(label=_("Test connection"))
        test.connect("clicked", self._on_translate_test)
        trow.append(test)
        conn.append(trow)
        self.trans_status = Gtk.Label(xalign=0.0, wrap=True)
        self.trans_status.add_css_class("dim-label")
        conn.append(self.trans_status)

        # Install helper for a *local* Ollama: only shown when the URL points
        # at this machine and nothing is there yet (see _refresh_ollama_row).
        # Hidden until the first probe has finished, so it never flashes up
        # for someone who already has Ollama running.
        self.ollama_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=6)
        # selectable: the terminal command shown when there is no
        # automatic route has to be copyable.
        self.ollama_info = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        self.ollama_info.add_css_class("dim-label")
        self.ollama_box.append(self.ollama_info)
        self.ollama_btn = Gtk.Button(label=_("Install Ollama"))
        set_accessible_label(self.ollama_btn, _("Install Ollama"))
        self.ollama_btn.set_halign(Gtk.Align.START)
        self.ollama_btn.connect("clicked", self._on_install_ollama)
        self.ollama_box.append(self.ollama_btn)
        self.ollama_bar = Gtk.ProgressBar(show_text=True)
        self.ollama_bar.set_visible(False)
        self.ollama_box.append(self.ollama_bar)
        self.ollama_box.set_visible(False)
        box.append(self.ollama_box)
        self._ollama_gen = 0
        self._ollama_installing = False
        self._refresh_ollama_row()

        sug_frame = Gtk.Frame(
            label=_("Suggested lightweight translation models"))
        sug_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sug_frame.set_child(sug_box)
        self.trans_suggest_rows = {}
        for m in vf.SUGGESTED_MODELS:
            srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            info = Gtk.Label(xalign=0.0, hexpand=True, wrap=True)
            info.set_markup(
                f"<b>{GLib.markup_escape_text(m['name'])}</b>  "
                f"<span alpha='70%'>{GLib.markup_escape_text(m['size'])} "
                f"\u2014 {GLib.markup_escape_text(m['note']())}</span>")
            srow.append(info)
            pull_btn = Gtk.Button(label=_("Pull"))
            pull_btn.connect("clicked", self._on_translate_pull, m["name"])
            srow.append(pull_btn)
            sug_box.append(srow)
            self.trans_suggest_rows[m["name"]] = pull_btn
        box.append(sug_frame)
        self.trans_pull_bar = Gtk.ProgressBar(show_text=True)
        self.trans_pull_bar.set_visible(False)
        box.append(self.trans_pull_bar)

        hint = Gtk.Label(xalign=0.0, wrap=True)
        hint.add_css_class("dim-label")
        hint.set_text(_("The Translate button is hidden by default; turn it "
                        "on under {iface}. Pick a keyboard shortcut under "
                        "{sc}.").format(iface=_("Appearance"),
                                        sc=_("Shortcuts")))
        box.append(hint)
        conn_exp = Gtk.Expander(label=_("Advanced: server and API key"))
        conn_exp.set_child(conn)
        box.append(conn_exp)
        return frame

    def _on_translate_changed(self, *_a):
        tr = self.state.setdefault("translate", {})
        tr["url"] = (self.trans_url.get_text().strip()
                     or vf.DEFAULT_TRANSLATE["url"])
        tr["model"] = (self.trans_model.get_text().strip()
                       or vf.DEFAULT_TRANSLATE["model"])
        tr["api_key"] = self.trans_key.get_text().strip()
        self._save_state_debounced()
        self._refresh_ollama_row()

    # ── Install Ollama ────────────────────────────────────────────────────
    def _refresh_ollama_row(self):
        """Decide what to offer for a local Ollama. Whether the URL is local
        is instant; whether a server answers is a network call, so that part
        runs in a thread, and a stale answer (the URL changed again while it
        was running) is dropped via the generation counter."""
        if not hasattr(self, "ollama_box") or self._ollama_installing:
            return
        self._ollama_gen += 1
        gen = self._ollama_gen
        cfg = dict(self.state.get("translate", {}))
        url = cfg.get("url") or ""
        if not vf.ollama_url_is_local(url):
            self._apply_ollama_state(gen, "remote")
            return

        def probe():
            _ids, err = vf.list_models(cfg)
            state = vf.ollama_install_state(
                url, err is None, vf.ollama_binary_present(), vf.is_nixos())
            GLib.idle_add(self._apply_ollama_state, gen, state)
        threading.Thread(target=probe, daemon=True).start()

    def _apply_ollama_state(self, gen, state):
        if gen != self._ollama_gen:
            return False
        texts = {
            "missing": _("Ollama is not installed on this computer. "
                         "Translation needs it, or a remote Ollama server."),
            "not-running": _("Ollama is installed but not running. "
                             "Start it with: systemctl start ollama"),
            "nixos": _("On NixOS, enable Ollama in your system "
                       "configuration instead: "
                       "services.ollama.enable = true;"),
        }
        text = texts.get(state)
        self.ollama_box.set_visible(text is not None)
        if text is not None:
            self.ollama_info.set_text(text)
        self.ollama_btn.set_visible(state == "missing")
        return False

    def _on_install_ollama(self, _btn):
        blocker = vf.ollama_install_blocker()
        if blocker and blocker.startswith("missing:"):
            self.ollama_info.set_text(
                _("Missing tools: {tools}. Install them with your package "
                  "manager and try again.").format(
                      tools=", ".join(blocker[len("missing:"):].split(","))))
            return
        if blocker:   # no packaged helper, or no pkexec: do it by hand
            self.ollama_info.set_text(
                _("VoxFox cannot start the installer automatically. Run "
                  "this in a terminal instead:") + "\n"
                + vf.OLLAMA_OFFICIAL_INSTALL)
            return
        # Administrator rights and a large download: ask first.
        dlg = Gtk.AlertDialog()
        dlg.set_message(_("Install Ollama?"))
        dlg.set_detail(_("VoxFox will download Ollama, a large file, and "
                         "install it with administrator rights, together "
                         "with a background service. Your graphics drivers "
                         "are not changed."))
        dlg.set_buttons([_("Cancel"), _("Install")])
        dlg.set_cancel_button(0)
        dlg.set_default_button(0)

        def done(source, result, *_a):
            try:
                choice = source.choose_finish(result)
            except Exception:
                return
            if choice == 1:
                self._start_ollama_install()
        dlg.choose(self, None, done)

    def _start_ollama_install(self):
        self._ollama_installing = True
        self.ollama_btn.set_sensitive(False)
        self.ollama_bar.set_fraction(0.0)
        self.ollama_bar.set_text(_("Installing Ollama..."))
        self.ollama_bar.set_visible(True)
        # Whether the bar should show a download percentage (a fraction) or
        # just keep moving (a pulse). Everything after the download -- unpack,
        # service, waiting for the server -- has no percentage, and a bar
        # that stands still there looks like a hang.
        self._ollama_pulsing = True

        def tick():
            if not self._ollama_installing:
                return False
            if self._ollama_pulsing:
                self.ollama_bar.pulse()
            return True
        GLib.timeout_add(120, tick)

        def set_phase(code):
            texts = {
                "download": _("Downloading Ollama..."),
                "install": _("Installing Ollama..."),
                "start": _("Starting Ollama..."),
                "wait": _("Waiting for Ollama to start..."),
            }
            text = texts.get(code)
            if text is None:
                return False
            self._ollama_pulsing = code != "download"
            self.ollama_bar.set_text(text)
            return False

        def on_frac(fraction, _label=""):
            def apply():
                if self._ollama_installing:
                    self._ollama_pulsing = False
                    self.ollama_bar.set_fraction(min(max(fraction, 0.0), 1.0))
                return False
            GLib.idle_add(apply)

        def worker():
            ok, detail = vf.install_ollama(
                frac=on_frac, phase=lambda c: GLib.idle_add(set_phase, c))
            GLib.idle_add(self._finish_ollama_install, ok, detail)
        threading.Thread(target=worker, daemon=True).start()

    def _finish_ollama_install(self, ok, detail):
        self._ollama_installing = False
        self.ollama_bar.set_visible(False)
        self.ollama_btn.set_sensitive(True)
        if ok and detail == "ok":
            self.ollama_btn.set_visible(False)
            self.ollama_info.set_text(
                _("Ollama installed. Pick a model below and press Pull."))
        elif ok:
            # Installed, but nothing answered in time. Say so in as many words,
            # and do not offer to install it again.
            self.ollama_btn.set_visible(False)
            self.ollama_info.set_text(
                _("Ollama is installed but not running. "
                  "Start it with: systemctl start ollama"))
        elif detail == "cancelled":
            self.ollama_info.set_text(_("Installation cancelled"))
        else:
            self.ollama_info.set_text(
                _("Ollama installation failed") + ": " + detail)
        return False

    def _on_translate_test(self, *_a):
        self._on_translate_changed()
        self.trans_status.set_text(_("Testing connection..."))

        def worker():
            ok, msg = vf.translate_test(self.state.get("translate", {}))
            GLib.idle_add(lambda: (self.trans_status.set_text(
                ("\u2713 " if ok else "\u2717 ") + msg), False)[1])
        threading.Thread(target=worker, daemon=True).start()

    def _on_translate_discover(self, _btn):
        self._on_translate_changed()
        self.trans_status.set_text(_("Discovering models..."))

        def worker():
            ids, err = vf.list_models(self.state.get("translate", {}))
            GLib.idle_add(self._translate_discovered_done, ids, err)
        threading.Thread(target=worker, daemon=True).start()

    def _translate_discovered_done(self, ids, err):
        if err:
            self.trans_status.set_text(
                f"{_('Could not discover models')}: {err}")
            return False
        self._discovered_models = ids
        self._trans_completion_store.clear()
        for mid in ids:
            if vf.is_chat_model(mid):
                self._trans_completion_store.append([mid])
        if ids:
            self.trans_status.set_text(
                _("Found {n} installed model(s)").format(n=len(ids)))
        else:
            self.trans_status.set_text(_("No models found on this endpoint"))
        self._refresh_suggested_buttons()
        return False

    def _refresh_suggested_buttons(self):
        have = set(getattr(self, "_discovered_models", []) or [])
        have_base = {h.split(":")[0] for h in have}
        for name, btn in self.trans_suggest_rows.items():
            installed = name in have or name.split(":")[0] in have_base
            # Installed models get a "Use" button instead of a disabled
            # "Installed" label -- picking a suggestion should never require
            # retyping its exact name into the Model field by hand.
            btn.set_label(_("Use") if installed else _("Pull"))
            btn.set_sensitive(True)

    def _select_translate_model(self, model_name):
        """Make `model_name` the active translation model without a network
        call -- used both for an already-installed suggestion and right
        after a fresh pull succeeds."""
        self.trans_model.set_text(model_name)
        self._on_translate_changed()
        self.trans_status.set_text(
            _("{model} is now the active model").format(model=model_name))

    def _on_translate_pull(self, _btn, model_name):
        have = set(getattr(self, "_discovered_models", []) or [])
        have_base = {h.split(":")[0] for h in have}
        if model_name in have or model_name.split(":")[0] in have_base:
            # Already installed: this click means "use it", not "pull it
            # again" -- no network call needed.
            self._select_translate_model(model_name)
            return

        self._on_translate_changed()
        self.trans_pull_bar.set_visible(True)
        self.trans_pull_bar.set_fraction(0.0)
        self.trans_pull_bar.set_text(_("Starting..."))

        def worker():
            def frac(fr, label):
                GLib.idle_add(lambda: (set_progress_bar(
                    self.trans_pull_bar, fr, label), False)[1])

            def prog(msg):
                GLib.idle_add(
                    lambda: (self.trans_pull_bar.set_text(msg), False)[1])
            ok, msg = vf.pull_model(model_name, self.state.get("translate", {}),
                                    progress=prog, frac=frac)
            GLib.idle_add(self._translate_pull_done, ok, msg, model_name)
        threading.Thread(target=worker, daemon=True).start()

    def _translate_pull_done(self, ok, msg, model_name):
        hide_progress_bar(self.trans_pull_bar)
        if ok:
            self._discovered_models = list(
                set(getattr(self, "_discovered_models", []) or [])
                | {model_name})
            self._refresh_suggested_buttons()
            # A model someone just spent time downloading is, in every
            # realistic case, one they want to try immediately -- select it
            # rather than leaving them to type its exact name afterwards.
            self._select_translate_model(model_name)
        else:
            self.trans_status.set_text(
                f"{_('Could not pull')} {model_name}: {msg}")
        return False

    def _on_webread_changed(self, *_a):
        wr = self.state.setdefault("webread", {})
        wr["use_ollama"] = bool(self.webread_ai_chk.get_active())
        self.webread_ai_box.set_visible(wr["use_ollama"])
        wr["mode"] = ("summary" if self.webread_mode_dd.get_selected() == 1
                      else "filter")
        wr["url"] = self.webread_url.get_text().strip() or vf.DEFAULT_OLLAMA_URL
        wr["model"] = (self.webread_model.get_text().strip()
                       or vf.DEFAULT_OLLAMA_MODEL)
        wr["api_key"] = self.webread_key.get_text().strip()
        self._save_state_debounced()

    def _on_webread_test(self, *_a):
        url = self.webread_url.get_text().strip() or vf.DEFAULT_OLLAMA_URL
        self.webread_status.set_text(_("Testing connection..."))

        api_key = self.webread_key.get_text().strip() or None

        def worker():
            models = vf.ollama_list_models(url, api_key=api_key)
            def done():
                if models is None:
                    self.webread_status.set_text(
                        _("Ollama not reachable — reading the unfiltered "
                          "text"))
                elif not models:
                    self.webread_status.set_text(
                        "✓ " + _("Connection OK") + " — " +
                        _("Requires a running Ollama with a downloaded "
                          "model, e.g.: ollama pull llama3.2"))
                else:
                    self.webread_status.set_text(
                        "✓ " + _("Connection OK") + ": "
                        + ", ".join(models[:8]))
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

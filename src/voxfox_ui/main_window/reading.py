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

"""voxfox_ui.main_window.reading

Reading aloud: the selection, translations, web pages, documents and
their reading position, stop, pause, language switch and hover.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log


class ReadingActions:
    """Reading aloud: the selection, translations, web pages, documents and
    their reading position, stop, pause, language switch and hover.
    """

    # ── actions (also the IPCServer entry points) ─────────────────────────────
    def do_read_button(self):
        """The Read button: reads the selection, or -- while VoxFox is
        speaking -- pauses and resumes, so a separate Pause button is not
        needed. The Read shortcut keeps reading the new selection, which
        is what someone selecting text and pressing the key expects."""
        if vf.is_speaking():
            self.do_pause()
        else:
            self.do_read()

    def do_read(self):
        """get_selection() can block the main loop for up to a few seconds
        (several clipboard tools tried in turn, each with its own timeout),
        so the read and the merge run off the main thread; everything that
        touches a widget runs afterwards via GLib.idle_add."""
        def worker():
            text = vf.get_selection()
            if vf.merge_enabled():
                text = vf.merge_wrapped_lines(text)
            GLib.idle_add(self._after_read_selection, text)
        threading.Thread(target=worker, daemon=True).start()

    def _after_read_selection(self, text):
        if len(text) >= 2:
            cfg = self._active_cfg()
            vf.add_history("read", text)
            threading.Thread(target=vf.speak, args=(text, cfg),
                             daemon=True).start()
            GLib.timeout_add(50, lambda: (self._sync_pause_btn(), False)[1])
            self.set_status(f"{_('Reading...')} [{vf.slot_voice_label(cfg)}]", 1500)
        else:
            self.set_status(_("Nothing selected"))
        return False

    def do_translate(self):
        """Translate the selection into the UI language and speak it with
        the Slot 1 voice (the UI language follows Slot 1, so that voice
        matches the translated text).

        get_selection() can block the main loop for a few seconds, so it
        now runs inside the same background thread as the translation
        call, rather than synchronously before that thread is started."""
        def worker():
            text = vf.get_selection()
            if vf.merge_enabled():
                text = vf.merge_wrapped_lines(text)
            if len(text) < 2:
                GLib.idle_add(self.set_status, _("Nothing selected"))
                return
            GLib.idle_add(self.set_status, _("Translating..."), 0)

            def prog(i, n):
                if n > 1:
                    GLib.idle_add(lambda: (self.set_status(
                        f"{_('Translating...')} {i}/{n}", duration=0),
                        False)[1])
            out, err = vf.translate_text(
                text, self.state.get("translate", {}), progress=prog)

            def done():
                if err or not out:
                    self.set_status(f"{_('Translation failed')}: {err}"
                                    if err else _("Translation failed"))
                    return False
                cfg = self.state["slot1"]
                vf.add_history("translate", out)
                threading.Thread(target=vf.speak, args=(out, cfg),
                                 daemon=True).start()
                GLib.timeout_add(
                    50, lambda: (self._sync_pause_btn(), False)[1])
                self.set_status(
                    f"{_('Reading translation...')} "
                    f"[{vf.slot_voice_label(cfg)}]", 2000)
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def set_current_document(self, name, folder):
        """Remember which document is playing, or None for loose text.

        While a document is set, a once-a-second check watches for the
        speech to end and saves the position when it does. That covers
        the cases the Stop button does not: a document read to its end,
        a stop from the hotkey or the command line, and speech replaced
        by something else entirely."""
        self.current_document = name
        self.current_document_dir = folder
        self._doc_watch_tries = 0
        if name and not getattr(self, "_doc_watch_id", None):
            self._doc_watch_id = GLib.timeout_add_seconds(
                1, self._watch_document_end)

    def _watch_document_end(self):
        if not self.current_document:
            self._doc_watch_id = None
            return False
        started = (vf.get_position().get("token") == self.current_document)
        if vf.is_speaking() or not started:
            # Still going -- or not yet going: speak() may spend up to
            # two seconds waiting for the previous speech to wind down,
            # and during that gap nothing is speaking yet. Do not mistake
            # that for the end. Give up only after a generous wait.
            self._doc_watch_tries = getattr(self, "_doc_watch_tries", 0) + 1
            if started or self._doc_watch_tries < 30:
                return True
        self._doc_watch_tries = 0
        self.save_reading_position()
        self._doc_watch_id = None
        return False

    def save_reading_position(self):
        """Write where the listener got to back to the document.

        Reads tts.get_position(), which survives stopping -- the live
        progress is cleared as soon as the speech worker finishes, so
        by the time a stop is handled there would be nothing left to
        save."""
        if not self.current_document or not self.current_document_dir:
            return
        pos = vf.get_position()
        # Speaking anything else replaces the speech but not this
        # bookmark, so check that what played really was this document.
        # Reading out a menu name or a translation must not move a
        # book's bookmark.
        if pos.get("token") != self.current_document:
            return
        saved = vf.documents.set_position(self.current_document_dir,
                                         self.current_document,
                                         pos.get("offset", 0),
                                         pos.get("length"))
        log.debug(f"library: saved position {saved} in "
                  f"{self.current_document}")

    def do_stop(self):
        vf.stop_speaking()
        self.save_reading_position()
        self._sync_pause_btn()
        self.set_status(_("Stopped"))

    def do_pause(self):
        if not vf.is_speaking():
            self.set_status(_("Nothing to pause"))
            return
        paused = vf.toggle_pause()
        if paused:
            self.save_reading_position()
        self._sync_pause_btn()
        self.set_status(_("Paused") if paused else _("Resumed"))

    def do_toggle_slot(self):
        new = "slot2" if self._active_slot() == "slot1" else "slot1"
        self.state["active_slot"] = new
        vf.save_state(self.state)
        self.reload_active_controls()
        cfg  = self.state[new]
        name = vf.slot_voice_label(cfg) or new
        self.set_status(f"{_('Language')}: {name}")
        threading.Thread(target=vf.speak, args=(f"{_('Language')}: {name}", cfg),
                         daemon=True).start()

    def do_read_page(self):
        """Experimental: read a web page aloud. Preferred route: the user
        selects the page's URL (Ctrl+L in the address bar) and VoxFox fetches
        it — bus-independent and always explicit about which page is read
        (the title lands in the status line). Fallback: AT-SPI extraction of
        the focused browser tab. Stage 2 (Ollama) per Settings → Web page.

        get_selection() itself can block the main loop for up to a few
        seconds (it may try several clipboard tools in turn, each with its
        own timeout), so it runs in its own short-lived thread; everything
        after it was already thread-based to begin with."""
        wr = self.state.get("webread", {})

        def get_url_then_continue():
            sel_url = vf.url_from_text(vf.get_selection())
            GLib.idle_add(self._continue_read_page, wr, sel_url)
        threading.Thread(target=get_url_then_continue, daemon=True).start()

    def _continue_read_page(self, wr, sel_url):
        """The rest of do_read_page(), once the selection has been read.
        Runs on the main thread (via GLib.idle_add); unchanged from before
        except for taking wr/sel_url as arguments instead of closing over
        them directly."""

        def refine_and_speak(text, title=""):
            if wr.get("use_ollama"):
                mode = wr.get("mode", "filter")
                msg = (_("Summarizing page with AI...") if mode == "summary"
                       else _("Filtering page with AI..."))
                GLib.idle_add(self.set_status, msg, 0)
                refined = vf.ollama_refine(
                    text, mode=mode,
                    url=wr.get("url") or vf.DEFAULT_OLLAMA_URL,
                    model=wr.get("model") or vf.DEFAULT_OLLAMA_MODEL,
                    api_key=wr.get("api_key") or None,
                    progress=lambda i, n: GLib.idle_add(
                        self.set_status, f"{msg} {i}/{n}", 0))
                if refined is None:
                    GLib.idle_add(self.set_status,
                                  _("Ollama not reachable — reading the "
                                    "unfiltered text"), 4000)
                elif not refined.strip():
                    GLib.idle_add(self.set_status,
                                  _("Nothing left to read after filtering"))
                    return
                else:
                    text = refined
            GLib.idle_add(self._after_page_text, text, title)

        if sel_url:
            self.set_status(f"{_('Fetching page...')} {sel_url[:70]}",
                            duration=0)

            def worker_url():
                text, title, err = vf.fetch_page_text(sel_url)
                if not text and vf.headless_available():
                    # JS-rendered page or bot wall: retry with a real
                    # (headless) browser before giving up.
                    GLib.idle_add(self.set_status,
                                  _("Opening the page in a background "
                                    "browser..."), 0)
                    text, title, err2 = vf.fetch_page_text_headless(sel_url)
                    if not text and err2 != "no-browser":
                        err = f"{err}, {err2}"
                if not text:
                    detail = f" ({err})" if err else ""
                    GLib.idle_add(self.set_status,
                                  _("Could not fetch a readable page from "
                                    "the selected address") + detail, 6000)
                    return
                refine_and_speak(text, title)
            threading.Thread(target=worker_url, daemon=True).start()
            return False

        # No URL selected → AT-SPI fallback (needs a working bus).
        if not vf.a11y_bus_reachable():
            self.set_status(
                _("Select the page's address first (Ctrl+L in the browser), "
                  "then press the shortcut again"), duration=6000)
            return False
        self.set_status(_("Extracting page text..."), duration=0)

        def worker_atspi():
            text, err = vf.extract_page_text()
            if not text:
                GLib.idle_add(
                    self.set_status,
                    _("No web page found — focus a browser tab and make sure "
                      "accessibility is on (Chromium needs "
                      "--force-renderer-accessibility)"), 6000)
                return
            refine_and_speak(text)
        threading.Thread(target=worker_atspi, daemon=True).start()
        return False

    def _after_page_text(self, text, title=""):
        if vf.merge_enabled():
            text = vf.merge_wrapped_lines(text)
        vf.add_history("read", text)
        threading.Thread(target=vf.speak, args=(text, self._active_cfg()),
                         daemon=True).start()
        self._sync_pause_btn()
        status = _("Reading...")
        if title:
            status = f"{status} — {title[:60]}"
        self.set_status(status, 4000)

    def do_hover(self):
        """Toggle hover-to-read. Mirrors the Tk build: an AT-SPI focus-event
        listener plus a polling fallback, controlled via vf.set_hover_running()."""
        if vf.IS_WAYLAND:
            # Reading the mouse position outside our own window is an X11
            # thing; Wayland's security model doesn't let any app query it.
            # There's no missing dependency that would fix this, so refuse
            # cleanly here -- reachable via IPC/CLI too, not just the
            # toolbar button, so this guard has to live here, not just in
            # whether the button is shown.
            self.set_status(
                _("Hover reading isn't available on Wayland — it needs "
                  "the mouse position outside VoxFox's own window, which "
                  "Wayland doesn't allow apps to read. Try Select or Read "
                  "instead."),
                duration=6000)
            return
        if self.hover_on:
            vf.set_hover_running(False)
            self.hover_on = False
            self.hover_btn.remove_css_class("voxfox-accent")
            threading.Thread(target=vf.stop_event_listener, daemon=True).start()
            self.set_status(_("Hover off"))
        else:
            # Reading other apps over AT-SPI means calling into pyatspi/libatspi.
            # On a broken or permission-denied bus that call aborts the whole
            # process, so refuse up front when the bus can't be reached.
            if not vf.a11y_bus_reachable():
                self.set_status(
                    _("Accessibility bus unavailable — hover reading can't "
                      "start. Enable accessibility, then log out and back in."),
                    duration=6000)
                return
            vf.set_hover_running(True)
            self.hover_on = True
            self.hover_btn.add_css_class("voxfox-accent")
            self.set_status(_("Hover on"))
            threading.Thread(target=vf.start_event_listener, daemon=True).start()
            threading.Thread(target=vf.hover_loop, daemon=True).start()

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

"""voxfox_ui.typespeak — the "Type and speak" window (6.1).

Someone types a text and VoxFox says it out loud: for people who cannot
speak (or not right now), to hear how a text sounds, or to practise. Enter
says the text, Shift+Enter starts a new line. Sentences said here are kept
in a short list so they can be said again with one click.

With Tiles switched on the text box shrinks to a line or two and the rest
of the window is a board of tiles: pressing "Ik", "heb", "dorst" builds
"Ik heb dorst". There is a ready-made board per language with example
sentences; every tile can be changed, moved or removed, and new ones added.
Each language keeps its own board.

In full screen (or maximised) the small main VoxFox window is minimised,
so it does not sit on top of the board; it comes back afterwards.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.widgets import set_accessible_label, btn_make_content  # noqa: E402
from voxfox_ui import tilepics  # noqa: E402
from voxfox_ui.tiledialog import TileDialog  # noqa: E402

_ENTER_KEYS = (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter)

# Light background + dark text in both light and dark mode, so a tile's
# colour always means the same and stays readable.
_TILE_CSS = """
button.vf-tile {
  background-image: none; color: #1d1d1d; border-radius: 10px;
  border: 1px solid rgba(0,0,0,0.25); padding: 6px 10px;
  font-size: %(px)dpx; min-height: %(h)dpx; min-width: %(w)dpx;
}
button.vf-tile label { color: #1d1d1d; }
button.vf-tile:hover { filter: brightness(0.94); }
button.vf-tile:active { filter: brightness(0.86); }
button.vf-tile-phrase   { background-color: #f1f1f1; }
button.vf-tile-social   { background-color: #f9cfe3; }
button.vf-tile-person   { background-color: #fff2a8; }
button.vf-tile-action   { background-color: #c9edbe; }
button.vf-tile-describe { background-color: #cfe3fb; }
button.vf-tile-thing    { background-color: #ffd9b3; }
button.vf-tile-question { background-color: #e2d4f6; }
button.vf-tile-edit { border: 2px dashed #555555; }
button.vf-tile-add  { background-color: transparent; color: inherit;
                      border: 2px dashed alpha(currentColor, 0.5); }
button.vf-tile-add label { color: inherit; }
/* A tile with a picture: the text is a bit smaller so both fit. */
button.vf-tile label.vf-tile-small { font-size: %(small)dpx; }
"""


def _lang_code(cfg):
    return vf.PIPER_LANG_TO_CODE.get((cfg or {}).get("lang", ""), "en")


class TypeSpeakWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title=_("Type and speak"))
        self.win = win
        self.state = win.state
        self.set_default_size(720, 560)
        self._hid_main = False
        self._board_code = None
        self._editing = False

        # ── controls ──
        # In the window itself rather than in the title bar: a window in
        # full screen has no title bar, and these must stay reachable.
        self.lang_btn = Gtk.Button()
        self.lang_btn.set_tooltip_text(_("Switch to the other language"))
        set_accessible_label(self.lang_btn, _("Switch language slot"))
        self.lang_btn.connect("clicked", self._on_switch_lang)
        self.tiles_btn = Gtk.ToggleButton(label=_("Tiles"))
        self.tiles_btn.set_tooltip_text(
            _("Show tiles you press to build a sentence"))
        set_accessible_label(self.tiles_btn, _("Tiles"))
        self.full_btn = Gtk.Button(icon_name="view-fullscreen-symbolic")
        self.full_btn.set_tooltip_text(_("Full screen (F11)"))
        set_accessible_label(self.full_btn, _("Full screen"))
        self.full_btn.connect("clicked", lambda *_a: self._toggle_fullscreen())
        larger = Gtk.Button(label="A+")
        larger.set_tooltip_text(_("Larger text"))
        set_accessible_label(larger, _("Larger text"))
        larger.connect("clicked", lambda *_a: self._change_font(+2))
        smaller = Gtk.Button(label="A\u2212")
        smaller.set_tooltip_text(_("Smaller text"))
        set_accessible_label(smaller, _("Smaller text"))
        smaller.connect("clicked", lambda *_a: self._change_font(-2))
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.append(self.lang_btn)
        controls.append(self.tiles_btn)
        controls.append(Gtk.Box(hexpand=True))
        controls.append(smaller)
        controls.append(larger)
        controls.append(self.full_btn)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{m}")(12)
        self.set_child(outer)
        outer.append(controls)

        self.hint = Gtk.Label(
            label=_("Type your text and press Enter to say it. "
                    "Shift+Enter starts a new line."),
            xalign=0.0, wrap=True)
        self.hint.add_css_class("dim-label")
        outer.append(self.hint)

        # ── the text box ──
        self.tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR,
                               accepts_tab=False)
        for m in ("top", "bottom", "left", "right"):
            getattr(self.tv, f"set_{m}_margin")(12)
        set_accessible_label(self.tv, _("Text to say"))
        self._css = Gtk.CssProvider()
        self.tv.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        frame = Gtk.Frame()
        self.text_sw = Gtk.ScrolledWindow()
        self.text_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.text_sw.set_child(self.tv)
        frame.set_child(self.text_sw)
        self.text_frame = frame
        outer.append(frame)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.tv.add_controller(keys)
        winkeys = Gtk.EventControllerKey()
        winkeys.connect("key-pressed", self._on_window_key)
        self.add_controller(winkeys)
        self.tv.get_buffer().connect_after("insert-text", self._on_inserted)

        # ── buttons ──
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.speak_btn = Gtk.Button()
        btn_make_content(self.speak_btn, "read", _("Speak"))
        self.speak_btn.add_css_class("voxfox-accent")
        self.speak_btn.set_tooltip_text(_("Says the text out loud (Enter)"))
        set_accessible_label(self.speak_btn, _("Speak"))
        self.speak_btn.connect("clicked", lambda *_a: self.speak_text())
        stop = Gtk.Button()
        btn_make_content(stop, "stop", _("Stop"))
        stop.set_tooltip_text(_("Stops speaking (Escape)"))
        set_accessible_label(stop, _("Stop"))
        stop.connect("clicked", lambda *_a: self._stop())
        self.back_btn = Gtk.Button(label=_("Remove word"))
        self.back_btn.set_tooltip_text(_("Removes the last word"))
        self.back_btn.connect("clicked", lambda *_a: self._remove_word())
        clear = Gtk.Button(label=_("Clear"))
        clear.set_tooltip_text(_("Empties the text box"))
        clear.connect("clicked", lambda *_a: self._clear())
        row.append(self.speak_btn)
        row.append(stop)
        row.append(self.back_btn)
        row.append(clear)
        self.voice_lbl = Gtk.Label(xalign=1.0, hexpand=True)
        self.voice_lbl.add_css_class("dim-label")
        self.voice_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(self.voice_lbl)
        outer.append(row)

        # ── typing mode: options and "said earlier" ──
        self.type_part = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                 spacing=8)
        self.clear_chk = Gtk.CheckButton(
            label=_("Empty the text box after speaking"))
        self.clear_chk.set_active(bool(self.state.get("type_clear_after", False)))
        self.clear_chk.connect("toggled", self._on_option, "type_clear_after")
        self.echo_chk = Gtk.CheckButton(label=_("Say each word while typing"))
        self.echo_chk.set_active(bool(self.state.get("type_echo_words", False)))
        self.echo_chk.connect("toggled", self._on_option, "type_echo_words")
        opts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        opts.append(self.clear_chk)
        opts.append(self.echo_chk)
        self.type_part.append(opts)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label=_("Said earlier"), xalign=0.0, hexpand=True)
        lbl.add_css_class("heading")
        head.append(lbl)
        self.clear_recent_btn = Gtk.Button(label=_("Clear list"))
        self.clear_recent_btn.add_css_class("flat")
        self.clear_recent_btn.connect("clicked", self._on_clear_recent)
        head.append(self.clear_recent_btn)
        self.type_part.append(head)

        self.recent = Gtk.ListBox()
        self.recent.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recent.add_css_class("boxed-list")
        self.recent.connect("row-activated", self._on_recent_activated)
        rsw = Gtk.ScrolledWindow()
        rsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rsw.set_min_content_height(110)
        rsw.set_max_content_height(200)
        rsw.set_propagate_natural_height(True)
        rsw.set_child(self.recent)
        self.type_part.append(rsw)
        outer.append(self.type_part)

        # ── tile mode ──
        self.tile_part = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                 spacing=8, vexpand=True)
        tbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.tile_say_chk = Gtk.CheckButton(
            label=_("Say a tile when it is pressed"))
        self.tile_say_chk.set_active(bool(self.state.get("type_tile_say", True)))
        self.tile_say_chk.connect("toggled", self._on_option, "type_tile_say")
        tbar.append(self.tile_say_chk)
        tbar.append(Gtk.Box(hexpand=True))
        self.add_tile_btn = Gtk.Button(label=_("New tile"))
        self.add_tile_btn.connect("clicked", lambda *_a: self._edit_tile(None))
        self.reset_btn = Gtk.Button(label=_("Standard tiles"))
        self.reset_btn.set_tooltip_text(
            _("Puts back the ready-made tiles for this language"))
        self.reset_btn.connect("clicked", self._on_reset_tiles)
        self.edit_btn = Gtk.ToggleButton(label=_("Change tiles"))
        self.edit_btn.set_tooltip_text(
            _("Click a tile to change, move or remove it"))
        self.edit_btn.connect("toggled", self._on_edit_toggled)
        tbar.append(self.add_tile_btn)
        tbar.append(self.reset_btn)
        tbar.append(self.edit_btn)
        self.tile_part.append(tbar)

        self.edit_hint = Gtk.Label(
            label=_("Click a tile to change it. Click Change tiles again "
                    "when you are done."), xalign=0.0, wrap=True)
        self.edit_hint.add_css_class("dim-label")
        self.tile_part.append(self.edit_hint)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_min_children_per_line(2)
        self.flow.set_max_children_per_line(30)
        self.flow.set_row_spacing(8)
        self.flow.set_column_spacing(8)
        self.flow.set_valign(Gtk.Align.START)
        fsw = Gtk.ScrolledWindow(vexpand=True)
        fsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        fsw.set_child(self.flow)
        self.tile_part.append(fsw)
        outer.append(self.tile_part)

        self.status = Gtk.Label(xalign=0.0,
                                accessible_role=Gtk.AccessibleRole.STATUS)
        self.status.add_css_class("dim-label")
        outer.append(self.status)

        self._tile_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._tile_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._apply_font()
        self._reload_recent()
        self._sync_voice()
        self.tiles_btn.set_active(bool(self.state.get("type_tiles_on", False)))
        self.tiles_btn.connect("toggled", self._on_tiles_toggled)
        self._apply_mode()
        # The language can be switched from the main window too.
        self.connect("notify::is-active", lambda *_a: self._sync_voice())
        self.connect("notify::fullscreened", lambda *_a: self._sync_main())
        self.connect("notify::maximized", lambda *_a: self._sync_main())
        self.connect("close-request", self._on_close)
        self.tv.grab_focus()

    # ── text size ──
    def _apply_font(self):
        px = vf.clamp_type_font(self.state.get("type_font_px", 26))
        self._css.load_from_data(
            f"textview, textview text {{ font-size: {px}px; }}".encode())
        tpx = max(14, int(px * 0.85))
        self._tile_css.load_from_data(
            (_TILE_CSS % {"px": tpx, "h": int(tpx * 2.6),
                          "w": int(tpx * 5),
                          "small": max(12, int(tpx * 0.9))}).encode())
        self._size_text_box()

    def _change_font(self, delta):
        px = vf.clamp_type_font(self.state.get("type_font_px", 26)) + delta
        self.state["type_font_px"] = vf.clamp_type_font(px)
        vf.save_state(self.state)
        self._apply_font()

    def _size_text_box(self):
        px = vf.clamp_type_font(self.state.get("type_font_px", 26))
        tiles = self.tiles_btn.get_active()
        self.text_frame.set_vexpand(not tiles)
        self.text_sw.set_vexpand(not tiles)
        if tiles:
            # Room for about two lines; more scrolls.
            line = int(px * 1.45)
            self.text_sw.set_min_content_height(line + 28)
            self.text_sw.set_max_content_height(line * 2 + 28)
            self.text_sw.set_propagate_natural_height(True)
        else:
            self.text_sw.set_propagate_natural_height(False)
            self.text_sw.set_max_content_height(-1)
            self.text_sw.set_min_content_height(140)

    # ── tiles on / off ──
    def _on_tiles_toggled(self, btn):
        self.state["type_tiles_on"] = btn.get_active()
        vf.save_state(self.state)
        self._apply_mode()

    def _apply_mode(self):
        tiles = self.tiles_btn.get_active()
        self.hint.set_visible(not tiles)
        self.type_part.set_visible(not tiles)
        self.tile_part.set_visible(tiles)
        self.back_btn.set_visible(tiles)
        if not tiles and self.edit_btn.get_active():
            self.edit_btn.set_active(False)
        self._sync_edit_widgets()
        self._size_text_box()
        if tiles:
            self._reload_tiles()

    # ── full screen ──
    def _toggle_fullscreen(self):
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _sync_main(self):
        """Minimise the main VoxFox window while this one fills the
        screen; bring it back afterwards."""
        full = self.is_fullscreen()
        self.full_btn.set_icon_name("view-restore-symbolic" if full
                                    else "view-fullscreen-symbolic")
        self.full_btn.set_tooltip_text(_("Leave full screen (F11)") if full
                                       else _("Full screen (F11)"))
        big = full or self.is_maximized()
        if big and not self._hid_main:
            self._hid_main = True
            try:
                self.win.minimize()
            except Exception as e:
                log.debug(f"type and speak: could not minimise: {e}")
        elif not big and self._hid_main:
            self._restore_main()

    def _restore_main(self):
        if self._hid_main:
            self._hid_main = False
            try:
                self.win.present()
            except Exception as e:
                log.debug(f"type and speak: could not restore: {e}")

    def _on_close(self, *_a):
        self._restore_main()
        try:
            Gtk.StyleContext.remove_provider_for_display(
                Gdk.Display.get_default(), self._tile_css)
        except Exception:
            pass
        return False

    # ── voice / language ──
    def _sync_voice(self):
        cfg = self.win._active_cfg()
        try:
            self.lang_btn.set_label(vf.piper_lang_short(cfg.get("lang", "")))
        except Exception:
            self.lang_btn.set_label("•")
        self.voice_lbl.set_text(vf.slot_voice_label(cfg) or "")
        if self.tiles_btn.get_active() and _lang_code(cfg) != self._board_code:
            self._reload_tiles()

    def _on_switch_lang(self, *_a):
        self.win.do_toggle_slot()
        self._sync_voice()
        self.tv.grab_focus()

    # ── keys and typing ──
    def _on_key(self, _ctl, keyval, _code, mods):
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        if keyval in _ENTER_KEYS and not (mods & Gdk.ModifierType.SHIFT_MASK):
            self.speak_text()
            return True
        if keyval == Gdk.KEY_Escape:
            self._stop()
            return True
        if ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self._change_font(+2)
            return True
        if ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self._change_font(-2)
            return True
        return False

    def _on_window_key(self, _ctl, keyval, _code, _mods):
        if keyval == Gdk.KEY_F11:
            self._toggle_fullscreen()
            return True
        if keyval == Gdk.KEY_Escape:
            self._stop()
            return True
        return False

    def _on_inserted(self, buf, it, text, _length):
        """Say the word that was just finished, when that option is on."""
        if not self.echo_chk.get_active() or len(text) != 1:
            return
        if not vf.is_word_end(text):
            return
        before = buf.get_text(buf.get_start_iter(), it, False)[:-1]
        word = vf.finished_word(before)
        if word:
            self._say(word)

    # ── speaking ──
    def _say(self, text):
        log.debug(f"type and speak: saying {len(text)} characters")
        threading.Thread(target=vf.speak, args=(text, self.win._active_cfg()),
                         daemon=True).start()

    def _buffer_text(self):
        buf = self.tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _set_text(self, text):
        buf = self.tv.get_buffer()
        buf.set_text(text)
        buf.place_cursor(buf.get_end_iter())

    def _current_text(self):
        """The selected part of the text, or all of it; and whether it
        was all of it."""
        buf = self.tv.get_buffer()
        sel = buf.get_selection_bounds()
        if sel:
            part = buf.get_text(sel[0], sel[1], False).strip()
            whole = part == self._buffer_text().strip()
            return part, whole
        return self._buffer_text().strip(), True

    def speak_text(self):
        text, whole = self._current_text()
        if not text:
            self.status.set_text(_("Type something first"))
            return
        self._sync_voice()
        self._say(text)
        vf.add_history("read", text)
        self._remember(text)
        self.status.set_text(_("Speaking..."))
        buf = self.tv.get_buffer()
        if whole and self.clear_chk.get_active():
            buf.set_text("")
        elif whole:
            # Select what was said: typing (or a tile) then starts a new
            # text, while Enter says the same text again.
            buf.select_range(buf.get_start_iter(), buf.get_end_iter())
        self.tv.grab_focus()

    def _stop(self):
        vf.stop_speaking()
        self.status.set_text(_("Stopped"))

    def _clear(self):
        self._set_text("")
        self.status.set_text("")
        self.tv.grab_focus()

    def _remove_word(self):
        self._set_text(vf.remove_last_word(self._buffer_text()))

    def _on_option(self, chk, key):
        self.state[key] = chk.get_active()
        vf.save_state(self.state)

    # ── tiles ──
    def _board(self):
        code = _lang_code(self.win._active_cfg())
        boards = self.state.get("type_tiles")
        stored = boards.get(code) if isinstance(boards, dict) else None
        tiles = vf.normalize_tiles(stored)
        return code, (vf.default_tiles(code) if tiles is None else tiles)

    def _save_board(self, tiles):
        code = _lang_code(self.win._active_cfg())
        boards = self.state.get("type_tiles")
        if not isinstance(boards, dict):
            boards = {}
        boards[code] = vf.normalize_tiles(tiles) or []
        self.state["type_tiles"] = boards
        vf.save_state(self.state)

    def _reload_tiles(self):
        child = self.flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.flow.remove(child)
            child = nxt
        code, tiles = self._board()
        self._board_code = code
        for i, tile in enumerate(tiles):
            btn = Gtk.Button()
            btn.set_child(self._tile_content(tile))
            btn.add_css_class("vf-tile")
            btn.add_css_class(f"vf-tile-{tile['kind']}")
            if self._editing:
                btn.add_css_class("vf-tile-edit")
                btn.set_tooltip_text(_("Click to change this tile"))
            set_accessible_label(btn, tile["text"])
            btn.connect("clicked", self._on_tile, i)
            self.flow.append(btn)
            btn.get_parent().set_focusable(False)
        if self._editing or not tiles:
            add = Gtk.Button(label="+ " + _("New tile"))
            add.add_css_class("vf-tile")
            add.add_css_class("vf-tile-add")
            add.connect("clicked", lambda *_a: self._edit_tile(None))
            self.flow.append(add)
            add.get_parent().set_focusable(False)

    def _tile_content(self, tile):
        """The inside of a tile: its text, with its picture to the left,
        to the right or above it when it has one."""
        lbl = Gtk.Label(label=tile["text"], wrap=True,
                        justify=Gtk.Justification.CENTER)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        path = tilepics.picture_path(self.state, tile.get("image"))
        if not path:
            return lbl
        pos = tile.get("image_pos", "left")
        tpx = max(14, int(vf.clamp_type_font(
            self.state.get("type_font_px", 26)) * 0.85))
        side = int(tpx * (2.4 if pos == "center" else 2.1))
        # Gtk.Image, not Gtk.Picture: a Picture asks for the full size of
        # a photo, which made every tile in the board as wide as the
        # biggest picture. An Image is exactly `side` pixels and fits the
        # picture inside, keeping its shape.
        pic = Gtk.Image.new_from_file(path)
        pic.set_pixel_size(side)
        lbl.add_css_class("vf-tile-small")
        if pos == "center":
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_halign(Gtk.Align.CENTER)
            box.append(pic)
            box.append(lbl)
        else:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl.set_hexpand(True)
            first, second = (pic, lbl) if pos == "left" else (lbl, pic)
            box.append(first)
            box.append(second)
        return box

    def _on_tile(self, _btn, index):
        _code, tiles = self._board()
        if not 0 <= index < len(tiles):
            return
        if self._editing:
            self._edit_tile(index)
            return
        word = tiles[index]["text"]
        buf = self.tv.get_buffer()
        sel = buf.get_selection_bounds()
        whole_selected = bool(sel) and (
            buf.get_text(sel[0], sel[1], False).strip()
            == self._buffer_text().strip())
        # Just said (and still selected): a tile starts the next sentence.
        base = "" if whole_selected else self._buffer_text()
        self._set_text(vf.add_word(base, word))
        if self.tile_say_chk.get_active():
            self._say(word)

    def _on_edit_toggled(self, btn):
        self._editing = btn.get_active()
        self._sync_edit_widgets()
        self._reload_tiles()

    def _sync_edit_widgets(self):
        self.add_tile_btn.set_visible(self._editing)
        self.reset_btn.set_visible(self._editing)
        self.edit_hint.set_visible(self._editing)
        self.tile_say_chk.set_visible(not self._editing)

    def _edit_tile(self, index):
        _code, tiles = self._board()
        TileDialog(self, tiles, index).present()

    def tiles_changed(self, tiles):
        self._save_board(tiles)
        self._reload_tiles()

    def _on_reset_tiles(self, *_a):
        dlg = Gtk.AlertDialog(
            message=_("Put back the standard tiles?"),
            detail=_("Your own tiles for this language are replaced by "
                     "the ready-made ones."))
        dlg.set_buttons([_("Cancel"), _("Standard tiles")])
        dlg.set_cancel_button(0)
        dlg.set_default_button(0)

        def done(d, res):
            try:
                if d.choose_finish(res) == 1:
                    code = _lang_code(self.win._active_cfg())
                    self.tiles_changed(vf.default_tiles(code))
            except Exception as e:
                log.debug(f"type and speak: reset dialog: {e}")
        dlg.choose(self, None, done)

    # ── said earlier ──
    def _remember(self, text):
        self.state["type_recent"] = vf.push_recent(
            self.state.get("type_recent", []), text)
        vf.save_state(self.state)
        self._reload_recent()

    def _reload_recent(self):
        child = self.recent.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.recent.remove(child)
            child = nxt
        items = vf.push_recent(self.state.get("type_recent", []), "")
        self.clear_recent_btn.set_sensitive(bool(items))
        if not items:
            row = Gtk.ListBoxRow(activatable=False)
            lbl = Gtk.Label(label=_("Sentences you say appear here. "
                                    "Click one to say it again."),
                            xalign=0.0, wrap=True)
            lbl.add_css_class("dim-label")
            for m in ("top", "bottom", "start", "end"):
                getattr(lbl, f"set_margin_{m}")(8)
            row.set_child(lbl)
            self.recent.append(row)
            return
        for text in items:
            row = Gtk.ListBoxRow()
            row._text = text
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            for m in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{m}")(6)
            oneline = " ".join(text.split())
            lbl = Gtk.Label(label=oneline, xalign=0.0, hexpand=True)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_tooltip_text(_("Click to say it again"))
            box.append(lbl)
            edit = Gtk.Button(icon_name="document-edit-symbolic")
            edit.add_css_class("flat")
            edit.set_tooltip_text(_("Put this sentence in the text box"))
            set_accessible_label(edit, _("Put this sentence in the text box"))
            edit.connect("clicked", lambda *_a, t=text: self._to_box(t))
            box.append(edit)
            row.set_child(box)
            self.recent.append(row)

    def _on_recent_activated(self, _lb, row):
        text = getattr(row, "_text", None)
        if not text:
            return
        self._say(text)
        vf.add_history("read", text)
        self._remember(text)
        self.status.set_text(_("Speaking..."))

    def _to_box(self, text):
        self._set_text(text)
        self.tv.grab_focus()

    def _on_clear_recent(self, *_a):
        self.state["type_recent"] = []
        vf.save_state(self.state)
        self._reload_recent()
        self.tv.grab_focus()



def present(win):
    """Show the window, reusing it when it is already open."""
    tw = getattr(win, "_type_win", None)
    if tw is not None:
        tw.present()
        return tw
    tw = TypeSpeakWindow(win)

    def closed(*_a):
        win._type_win = None
        return False
    tw.connect("close-request", closed)
    win._type_win = tw
    tw.present()
    return tw

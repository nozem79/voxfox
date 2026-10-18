# VoxFox — free accessibility tools for Linux
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""voxfox_ui.library — The OCR document library window.

Sits alongside the history window rather than replacing it: the history
keeps the last twenty short items, while the library holds whole documents
that are meant to be kept and read over several sittings.

Each row offers continue, start over, and delete. Continue is the point of
the whole thing, so it is the first button and is the only one that changes
appearance: on an untouched document it says start instead.
"""

import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core.common import _  # noqa: E402

log = vf.log

# How far the skip buttons jump. Thirty seconds is roughly a paragraph:
# enough to be worth pressing, short enough to land near what you missed.
SKIP_SECONDS = 30
from voxfox_ui.widgets import _a11y  # noqa: E402


class LibraryWindow(Gtk.Window):
    """Files the user opened, with their reading positions."""

    def __init__(self, win):
        super().__init__(title=_("Library"), transient_for=win)
        self.win = win
        self.set_default_size(520, 480)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{m}")(12)
        self.set_child(outer)

        self.folder = vf.documents.library_dir(self.win.state)
        # name -> (play button, progress label, index entry)
        self._rows = {}
        self._tick_id = None
        path_lbl = Gtk.Label(label=self.folder, xalign=0.0)
        path_lbl.add_css_class("dim-label")
        path_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        path_lbl.set_tooltip_text(self.folder)
        outer.append(path_lbl)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        sw.set_child(self.listbox)
        outer.append(sw)

        self._reload()

        # Kept fresh while the window is open: the play/pause button and the
        # percentages follow whatever is actually being spoken.
        self._tick_id = GLib.timeout_add_seconds(1, self._tick)
        self.connect("close-request", self._on_close)

    def _on_close(self, *_a):
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        return False

    # ── list ─────────────────────────────────────────────────────────────

    def _reload(self):
        self._rows.clear()
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

        items = vf.documents.load_index(self.folder)
        if not items:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            lbl = Gtk.Label(
                label=_("No documents yet. Files you open are kept here."))
            lbl.add_css_class("dim-label")
            lbl.set_wrap(True)
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
            row.set_child(lbl)
            self.listbox.append(row)
            return
        for entry in items:
            self.listbox.append(self._row(entry))

    def _row(self, entry):
        title = (entry.get("title") or "").strip() or _("Untitled document")
        name = entry.get("file")

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(6)

        box.append(Gtk.Image.new_from_icon_name("x-office-document-symbolic"))

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        lbl = Gtk.Label(label=title, xalign=0.0)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_tooltip_text(title)
        text_box.append(lbl)
        sub_lbl = Gtk.Label(label="", xalign=0.0)
        sub_lbl.add_css_class("dim-label")
        text_box.append(sub_lbl)
        box.append(text_box)

        # One button for both starting and pausing, like any music player:
        # two buttons that are never both usable is just more to aim at.
        play = Gtk.Button(icon_name="media-playback-start-symbolic")
        play.connect("clicked", lambda *_a, e=entry: self._on_play(e))
        box.append(play)

        back = Gtk.Button(icon_name="media-seek-backward-symbolic")
        back.set_tooltip_text(_("Back {seconds} seconds").format(
            seconds=SKIP_SECONDS))
        _a11y(back, _("Back {seconds} seconds").format(seconds=SKIP_SECONDS))
        back.connect("clicked", lambda *_a, e=entry: self._skip(e, -SKIP_SECONDS))
        box.append(back)

        fwd = Gtk.Button(icon_name="media-seek-forward-symbolic")
        fwd.set_tooltip_text(_("Forward {seconds} seconds").format(
            seconds=SKIP_SECONDS))
        _a11y(fwd, _("Forward {seconds} seconds").format(seconds=SKIP_SECONDS))
        fwd.connect("clicked", lambda *_a, e=entry: self._skip(e, SKIP_SECONDS))
        box.append(fwd)

        restart = Gtk.Button(icon_name="media-skip-backward-symbolic")
        restart.set_tooltip_text(_("Start over"))
        _a11y(restart, _("Start over"))
        restart.connect("clicked", lambda *_a, e=entry: self._read(e, resume=False))
        box.append(restart)

        rm = Gtk.Button(icon_name="user-trash-symbolic")
        rm.set_tooltip_text(_("Delete"))
        _a11y(rm, _("Delete"))
        rm.connect("clicked", lambda *_a, e=entry: self._confirm_delete(e))
        box.append(rm)

        self._rows[name] = (play, sub_lbl, entry)
        self._refresh_row(name)
        row.set_child(box)
        return row

    # ── live state ───────────────────────────────────────────────────────

    def _playing_name(self):
        """The document being spoken right now, or None."""
        if not vf.is_speaking():
            return None
        return vf.get_position().get("token")

    def _refresh_row(self, name):
        """Point the play/pause button at whatever this row can do next."""
        widgets = self._rows.get(name)
        if not widgets:
            return
        play, sub_lbl, entry = widgets
        active = (self._playing_name() == name)
        paused = active and vf.is_paused()

        if active and not paused:
            play.set_icon_name("media-playback-pause-symbolic")
            label = _("Pause")
        elif paused:
            play.set_icon_name("media-playback-start-symbolic")
            label = _("Resume")
        elif entry.get("offset", 0) > 0:
            play.set_icon_name("media-playback-start-symbolic")
            label = _("Continue")
        else:
            play.set_icon_name("media-playback-start-symbolic")
            label = _("Read")
        play.set_tooltip_text(label)
        _a11y(play, label)

        # While this document is playing, follow the speech rather than the
        # saved bookmark, which only moves on pause or stop.
        offset = entry.get("offset", 0)
        if active:
            offset = vf.get_position().get("offset", offset)
        length = entry.get("length") or 0
        if offset > 0 and length > 0:
            percent = int(min(1.0, offset / float(length)) * 100)
            sub_lbl.set_text(_("{percent}% read").format(percent=percent))
        else:
            sub_lbl.set_text(_("Not started"))

    def _tick(self):
        # When playback stops or moves to another document, the saved
        # positions on disk are newer than the copies these rows hold,
        # so rebuild the list from disk rather than showing stale numbers.
        playing = self._playing_name()
        if playing != getattr(self, "_last_playing", playing):
            self._reload()
        self._last_playing = playing
        for name in list(self._rows):
            self._refresh_row(name)
        return True

    # ── actions ──────────────────────────────────────────────────────────

    def _on_play(self, entry):
        """Start, pause or resume, depending on what this document is doing."""
        name = entry.get("file")
        if self._playing_name() == name:
            self.win.do_pause()          # also saves the position when pausing
        else:
            self._read(entry, resume=True)
        self._refresh_row(name)

    def _skip(self, entry, seconds):
        """Jump `seconds` forward or back and carry on reading from there.

        Works off the live position when this document is playing, and off
        its saved bookmark otherwise, so the buttons do something sensible
        whether or not you are listening at that moment.
        """
        name = entry.get("file")
        playing = (self._playing_name() == name)
        here = (vf.get_position().get("offset", 0) if playing
                else entry.get("offset", 0))
        step = vf.seconds_to_chars(abs(seconds), self.win._active_cfg())
        target = max(0, here + (step if seconds > 0 else -step))

        text = vf.documents.read_text(self.folder, entry)
        if not text:
            self.win.set_status(_("Could not open that document"))
            self._reload()
            return
        if target >= len(text):
            # Past the end: treat it as finished rather than starting a
            # sentence that is not there.
            self.win.do_stop()
            vf.documents.set_position(self.folder, name, 0, len(text))
            self._reload()
            self.win.set_status(_("End of document"))
            return

        self.win.set_current_document(name, self.folder)
        vf.documents.set_position(self.folder, name, target, len(text))
        entry["offset"] = target
        threading.Thread(
            target=vf.speak,
            args=(text, self.win._active_cfg(), target, name),
            daemon=True).start()
        self.win._sync_pause_btn()
        self._refresh_row(name)

    def _read(self, entry, resume):
        text = vf.documents.read_text(self.folder, entry)
        if not text:
            self.win.set_status(_("Could not open that document"))
            self._reload()
            return
        offset = entry.get("offset", 0) if resume else 0
        name = entry.get("file")
        # Tell the main window which document is playing, so that pausing or
        # stopping knows where to write the position back to. The same name
        # goes to speak() as its token, so a position can never land on a
        # document that did not produce the speech.
        self.win.set_current_document(name, self.folder)
        threading.Thread(
            target=vf.speak,
            args=(text, self.win._active_cfg(), offset, name),
            daemon=True).start()
        self.win._sync_pause_btn()
        self.win.set_status(_("Reading...") if not resume or not offset
                            else _("Continuing where you left off"))

    def _confirm_delete(self, entry):
        """Ask first: a document is the only copy of that text."""
        dlg = Gtk.AlertDialog()
        dlg.set_message(_("Delete this document?"))
        dlg.set_detail(entry.get("title") or entry.get("file", ""))
        dlg.set_buttons([_("Cancel"), _("Delete")])
        dlg.set_cancel_button(0)
        dlg.set_default_button(0)

        def done(source, result, *_a):
            try:
                choice = source.choose_finish(result)
            except Exception:
                return
            if choice == 1:
                self._delete(entry)

        dlg.choose(self, None, done)

    def _delete(self, entry):
        name = entry.get("file")
        if self.win.current_document == name:
            self.win.set_current_document(None, None)
        vf.documents.delete(self.folder, name)
        self._reload()
        self.win.set_status(_("Document deleted"))


__all__ = ["LibraryWindow"]

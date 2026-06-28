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

"""
VoxFox — GTK4 front-end.

The UI only. All TTS / STT / OCR / IPC / CLI logic lives in voxfox_core,
which carries no GUI-toolkit imports and is shared with the Tk front-end.

Run the GUI:        voxfox
Set up components:  voxfox --setup     (downloads Piper + voices + Whisper)
Forward a command:  voxfox --read      (and --stop, --pause, --ocr-select, ...)
"""

import os
import sys
import time
import platform
import tarfile
import argparse
import threading
import tempfile
import subprocess
import urllib.request
import logging

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio, Gdk, Pango  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log

# When installed from the .deb, shared data lives here. The per-user ~/.piper
# paths that voxfox_core defaults to still win when present, so a hand-installed
# setup keeps working unchanged.
SYSTEM_DATA_DIR = "/usr/share/voxfox"
SYSTEM_LOCALES  = os.path.join(SYSTEM_DATA_DIR, "locales")
SYSTEM_ICON     = "/usr/share/icons/hicolor/256x256/apps/voxfox.png"

PIPER_RELEASE = "https://github.com/rhasspy/piper/releases/latest/download"
DEFAULT_VOICES = ["en_GB-alba-medium", "nl_NL-pim-medium"]
APP_VERSION = "3.4"
MANUAL_URL  = "https://voxfox.nl/manual"

# Logo orange, used for accent buttons instead of the theme's accent colour.
ACCENT_CSS = b"""
.voxfox-accent {
  background-image: none;
  background-color: #F26A1F;
  color: #ffffff;
  border-color: #D9590F;
}
.voxfox-accent:hover  { background-color: #F47E3A; }
.voxfox-accent:active { background-color: #D9590F; }
"""


# ── 3.0 modular toolbar registry ──────────────────────────────────────────
# The seven front-end action buttons. This is the single source of truth for
# which buttons exist; state.json (ui_layout) only stores the user's chosen
# visibility and order. Fields per button:
#   id       stable key, persisted in state — never rename, only add/remove
#   attr     the VoxFoxWindow attribute kept for the live widget (other code
#            still refers to self.read_btn, self.whisper_btn, ...)
#   label    English button text (run through _() at build time)
#   tooltip  English tooltip text (through _())
#   a11y     English accessible label (through _())
#   handler  name of the VoxFoxWindow method invoked on click
#   css      optional extra CSS class (e.g. the orange accent on Read)
TOOLBAR_BUTTONS = [
    ("read",    "read_btn",    "Read",   "Read selected text aloud",
     "Read selected text aloud", "do_read", "voxfox-accent"),
    ("stop",    "stop_btn",    "Stop",   "Stop speaking",
     "Stop", "do_stop", None),
    ("pause",   "pause_btn",   "Pause",  "Pause or resume speech",
     "Pause or resume", "do_pause", None),
    ("dictate", "whisper_btn", "Speak",  "Dictate: record speech and type it",
     "Dictate (speech to text)", "do_whisper", None),
    ("hover",   "hover_btn",   "Hover",
     "Read UI text under the mouse pointer aloud (AT-SPI)",
     "Toggle hover reading", "do_hover", None),
    ("select",  "select_btn",  "Select",
     "Select a screen region and read its text aloud via OCR",
     "Select a screen region to read via OCR", "do_ocr_select", None),
    ("ocr",     "ocr_btn",     "OCR",
     "OCR: open a PDF or image and read the text aloud",
     "Open a PDF or image to read via OCR", "do_ocr_file", None),
]
TOOLBAR_IDS = [b[0] for b in TOOLBAR_BUTTONS] + ["switch"]


def _scale_css(scale):
    """CSS that scales the main window. .voxfox-root only sets the root
    font-size (which scales the title text and, via em, the header icons) so it
    can safely sit on the header without bloating the window-control or
    menu/settings buttons. Everything that contributes to the window's width —
    the toolbar button padding/min-width, the gaps between buttons, and the
    padding around the toolbar — is expressed in em and scoped to the toolbar,
    so the whole window shrinks proportionally at 75 % instead of keeping
    fixed-pixel slack. Only the main window and its header carry these classes;
    the settings dialog keeps the theme default."""
    return (f".voxfox-root {{ font-size: {scale}%; }}\n"
            ".voxfox-root button image { -gtk-icon-size: 1.1em; }\n"
            ".voxfox-pad { padding: 0.2em; }\n"
            ".voxfox-toolbar button { padding: 0.25em 0.4em; min-width: 2.6em; margin: 0.12em; }\n"
            ".voxfox-toolbar flowboxchild { margin: 0.12em; }\n").encode()


# ── GLib adapter so voxfox_core.IPCServer can schedule work on the UI thread ──
class _RootShim:
    """IPCServer and worker threads call ``app.root.after(ms, fn)`` to bounce a
    callback onto the UI thread — the Tk idiom. We map it onto GLib's loop:
    idle_add for ms<=0, timeout_add otherwise. Each callback fires once."""

    @staticmethod
    def after(ms, fn, *args):
        def once():
            try:
                fn(*args)
            except Exception as e:
                log.debug(f"after() callback error: {e}")
            return False
        if ms and ms > 0:
            GLib.timeout_add(ms, once)
        else:
            GLib.idle_add(once)


# ── First-run component setup (Piper engine + voices + faster-whisper) ───────
def _piper_asset():
    m = platform.machine()
    return {
        "x86_64":  "piper_linux_x86_64.tar.gz",
        "aarch64": "piper_linux_aarch64.tar.gz",
        "armv7l":  "piper_linux_armv7l.tar.gz",
    }.get(m)


def install_piper(progress=lambda m: None, frac=lambda *_a: None):
    """Download the Piper binary for this architecture into ~/.piper."""
    if os.path.exists(vf.PIPER_BIN):
        progress(_("Piper already installed"))
        return True, "ok"
    asset = _piper_asset()
    if not asset:
        return False, f"Unsupported architecture: {platform.machine()}"
    os.makedirs(vf.PIPER_DIR, exist_ok=True)
    url = f"{PIPER_RELEASE}/{asset}"
    progress(_("Downloading Piper engine..."))
    try:
        tmp = os.path.join(tempfile.gettempdir(), asset)
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    frac(done / total, "Piper")
        progress(_("Extracting Piper..."))
        # The tarball has a leading "piper/" directory; strip it.
        with tarfile.open(tmp, "r:gz") as tar:
            for member in tar.getmembers():
                parts = member.name.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                member.name = parts[1]
                tar.extract(member, vf.PIPER_DIR)
        os.unlink(tmp)
        if os.path.exists(vf.PIPER_BIN):
            try:
                os.chmod(vf.PIPER_BIN, 0o755)
            except OSError:
                # Some filesystems can't store the Unix exec bit (e.g. FAT32 on
                # removable media); such mounts usually expose files as
                # executable already, so don't fail the whole install over it.
                pass
        return True, "ok"
    except Exception as e:
        return False, str(e)


def install_default_voices(progress=lambda m: None, frac=lambda *_a: None):
    # Always ensure the bundled English + Dutch voices, plus whatever voices
    # the two slots currently point at (on a fresh install these are seeded
    # from the system language, so a German system also pulls its German voice).
    keys = list(DEFAULT_VOICES)
    try:
        st = vf.load_state()
        for slot in ("slot1", "slot2"):
            v = st.get(slot, {}).get("voice", "")
            if v and v not in keys:
                keys.append(v)
    except Exception as e:
        log.debug(f"slot voice lookup skipped: {e}")
    for key in keys:
        if key in vf.get_local_voices():
            continue
        progress(f"{_('Downloading voice')}: {key}...")
        ok, msg = vf.download_voice(key, progress_cb=progress, frac_cb=frac)
        if not ok:
            log.warning(f"Voice {key} failed: {msg}")
    return True, "ok"


def _pip_install(pkgs, progress=lambda m: None):
    progress(f"{_('Installing')}: {', '.join(pkgs)}...")
    base = [sys.executable, "-m", "pip", "install", "--user"]
    for cmd in (base + ["--break-system-packages", *pkgs], base + [*pkgs]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if r.returncode == 0:
                return True
        except Exception as e:
            log.debug(f"pip attempt failed: {e}")
    return False


def install_python_extras(progress=lambda m: None):
    """Install the pip-only Python deps that aren't reliably packaged in Debian:
    faster-whisper (dictation) and pytesseract + Pillow (OCR). Each is skipped
    when already importable, so this is safe to re-run."""
    def have(mod):
        try:
            __import__(mod)
            return True
        except Exception:
            return False

    if not have("faster_whisper"):
        if not _pip_install(["faster-whisper"], progress):
            progress(_("faster-whisper install failed (dictation disabled)"))
    # Pillow usually comes from apt (python3-pil); pip-install only if missing.
    ocr_pkgs = []
    if not have("pytesseract"):
        ocr_pkgs.append("pytesseract")
    if not have("PIL"):
        ocr_pkgs.append("pillow")
    if ocr_pkgs and not _pip_install(ocr_pkgs, progress):
        progress(_("OCR Python packages failed to install"))
    return True, "ok"


def run_setup(progress=lambda m: None, want_extras=True, frac=lambda *_a: None):
    """Install everything needed on a fresh machine. Safe to re-run."""
    ok, msg = install_piper(progress, frac)
    if not ok:
        return False, f"Piper: {msg}"
    install_default_voices(progress, frac)
    if want_extras:
        install_python_extras(progress)
    progress(_("Setup complete"))
    return True, "ok"


def enable_accessibility():
    """Turn on the GNOME/AT-SPI accessibility bus system-wide for the current
    user, so hover mode can read text from any AT-SPI-aware app (GTK, Qt,
    Firefox, LibreOffice...). This is the canonical 'accessibility everywhere'
    switch. Returns (ok, message)."""
    if not vf._have("gsettings"):
        return False, _("gsettings not found (not a GNOME session?)")
    try:
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.interface",
             "toolkit-accessibility", "true"],
            check=True, timeout=10)
        return True, _("Accessibility enabled. Restart apps (and use "
                       "--force-renderer-accessibility for Chromium) to apply.")
    except Exception as e:
        return False, f"{e}"


# ── UI language + text direction ─────────────────────────────────────────────
# Locale codes whose script runs right-to-left. When the interface switches to
# one of these, the whole GTK layout (buttons, labels, menus) must flip.
_RTL_UI_CODES = {"ar"}


def apply_ui_language(piper_lang_name):
    """Switch the UI to the locale for the given Piper language name AND set the
    global text direction, so Arabic flips the interface to right-to-left and
    every other language stays left-to-right. Call this everywhere the UI
    language changes (slot 1 change, settings import, startup)."""
    code = vf.ui_code_for_piper_lang(piper_lang_name)
    vf.set_language(code)
    direction = (Gtk.TextDirection.RTL if code in _RTL_UI_CODES
                 else Gtk.TextDirection.LTR)
    Gtk.Widget.set_default_direction(direction)


def accessibility_enabled():
    """True if the GNOME/AT-SPI accessibility bus is already switched on, so the
    setup checklist can show it as done. Checks the same desktop schemas that
    _enable_accessibility() writes (GNOME, Cinnamon, MATE), so the status is
    accurate on each of them. Best-effort: returns False if gsettings isn't
    available."""
    if not vf._have("gsettings"):
        return False
    for schema in ("org.gnome.desktop.interface",
                   "org.cinnamon.desktop.interface",
                   "org.mate.interface"):
        try:
            r = subprocess.run(
                ["gsettings", "get", schema, "toolkit-accessibility"],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip().lower() == "true":
                return True
        except Exception:
            continue
    return False


# ── Region screenshot (used by "Select" / --ocr-select) ──────────────────────
def _grab_region_to_file(dest_png):
    """Capture a user-drawn rectangle into dest_png using the desktop's native
    region-screenshot tool — which is what makes this work on X11 and Wayland.
    Returns (ok, error_message).

    Tool order is deliberate: maim/scrot first. gnome-screenshot fails
    *silently* on non-GNOME desktops (notably Cinnamon: no GNOME Shell DBus,
    broken X11 fallback), producing no file and no error, so it must not be
    preferred where maim/scrot are present.

    maim/scrot grab the pointer to draw the rectangle. When OCR-select is
    triggered from a Super-key shortcut, the window manager still holds the
    keybinding's pointer grab for a moment, so the first attempt can fail with
    'couldn't grab pointer'. That clears once the keys are released, so we
    retry briefly. A non-zero exit *without* a grab error means the user
    cancelled (Escape), which we report as such rather than retrying."""
    grabbers = [
        ("maim",  ["-s", dest_png]),
        ("scrot", ["-s", dest_png]),
    ]
    fallbacks = [
        ("gnome-screenshot", ["-a", "-f", dest_png]),
        ("spectacle",        ["-rbno", dest_png]),
        ("flameshot",        ["gui", "-r", "-p", dest_png]),
    ]

    def _run_grabber(binary, args, attempts=10, delay=0.12):
        """Run a pointer-grabbing tool, retrying only on grab contention."""
        last_err = ""
        for i in range(attempts):
            # Newer scrot refuses to overwrite an existing file, and mkstemp()
            # has already created an empty one. Remove it before every attempt
            # so the tool writes a fresh capture.
            try:
                if os.path.exists(dest_png):
                    os.unlink(dest_png)
            except OSError:
                pass
            try:
                r = subprocess.run([binary, *args], timeout=120,
                                   capture_output=True, text=True)
            except Exception as e:
                return False, str(e)
            if r.returncode == 0 and os.path.exists(dest_png) \
                    and os.path.getsize(dest_png) > 0:
                return True, ""
            stderr = (r.stderr or "").strip()
            last_err = stderr
            if "grab" in stderr.lower():
                # WM still holds the hotkey grab; wait for it to clear, retry.
                log.debug(f"{binary} grab busy (attempt {i+1}/{attempts}): {stderr}")
                time.sleep(delay)
                continue
            # Non-zero without a grab error → user cancelled the selection.
            return False, _("Selection cancelled")
        return False, last_err or _("Could not grab the screen for selection")

    for binary, args in grabbers:
        if not vf._have(binary):
            continue
        ok, err = _run_grabber(binary, args)
        if ok:
            return True, ""
        # Grab contention that never cleared, or a cancel — report it; don't
        # silently fall through to gnome-screenshot (which would fail quietly).
        return False, err

    for binary, args in fallbacks:
        if not vf._have(binary):
            continue
        try:
            if os.path.exists(dest_png):
                os.unlink(dest_png)
        except OSError:
            pass
        try:
            subprocess.run([binary, *args], check=True, timeout=120)
            if os.path.exists(dest_png) and os.path.getsize(dest_png) > 0:
                return True, ""
            # gnome-screenshot on Cinnamon: exit 0 but no file. Keep trying.
            log.debug(f"{binary} produced no file; trying next tool")
        except subprocess.CalledProcessError:
            return False, _("Selection cancelled")
        except Exception as e:
            return False, str(e)

    if vf._have("grim") and vf._have("slurp"):
        try:
            geom = subprocess.run(["slurp"], capture_output=True, text=True,
                                  timeout=120)
            if geom.returncode != 0 or not geom.stdout.strip():
                return False, _("Selection cancelled")
            subprocess.run(["grim", "-g", geom.stdout.strip(), dest_png],
                           check=True, timeout=120)
            if os.path.exists(dest_png) and os.path.getsize(dest_png) > 0:
                return True, ""
        except Exception as e:
            return False, str(e)
    return False, _("No screenshot tool found "
                    "(install gnome-screenshot, spectacle, scrot, or grim+slurp)")


def _dropdown(items, selected_value=None):
    dd = Gtk.DropDown.new_from_strings(items or [""])
    if selected_value and selected_value in (items or []):
        dd.set_selected(items.index(selected_value))
    return dd


def _set_dropdown_items(dd, items, selected_value=None):
    dd.set_model(Gtk.StringList.new(items or [""]))
    if selected_value and items and selected_value in items:
        dd.set_selected(items.index(selected_value))
    else:
        dd.set_selected(0)


def _dropdown_value(dd):
    item = dd.get_selected_item()
    return item.get_string() if item is not None else ""


def _a11y(widget, label):
    """Give a widget an explicit accessible name for screen readers. Essential
    for icon-only / emoji buttons, whose visible glyph is not a usable label.
    An accessibility tool should itself be accessible."""
    try:
        widget.update_property([Gtk.AccessibleProperty.LABEL], [label])
    except Exception as e:
        log.debug(f"a11y label failed: {e}")


def _set_progress_bar(bar, fraction, label=None):
    """Show/update a Gtk.ProgressBar (call on the GUI thread). Returns the
    clamped fraction so callers can decide whether to auto-hide."""
    try:
        fr = max(0.0, min(1.0, float(fraction)))
    except (TypeError, ValueError):
        fr = 0.0
    bar.set_fraction(fr)
    pct = int(fr * 100)
    bar.set_text(f"{label} — {pct}%" if label else f"{pct}%")
    bar.set_visible(True)
    return fr


def _hide_progress_bar(bar):
    bar.set_visible(False)
    bar.set_fraction(0.0)
    return False


# ── Preferences window: per-slot language/voice + Whisper model + API ─────────
class HistoryWindow(Gtk.Window):
    """Recent read/dictated items, with re-read and copy-to-clipboard.

    Re-typing isn't offered here: VoxFox stays always-on-top and holds focus,
    so typed text would land in the wrong window. Copy lets you paste it
    wherever you actually want it.
    """
    def __init__(self, win):
        super().__init__(title=_("History"), transient_for=win)
        self.win = win
        self.set_default_size(460, 460)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{m}")(12)
        self.set_child(outer)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        sw.set_child(self.listbox)
        outer.append(sw)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_halign(Gtk.Align.END)
        clear = Gtk.Button(label=_("Clear all"))
        clear.connect("clicked", self._on_clear)
        bar.append(clear)
        outer.append(bar)

        self._reload()

    def _reload(self):
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

        items = vf.load_history()
        if not items:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            lbl = Gtk.Label(label=_("(empty)"))
            lbl.add_css_class("dim-label")
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
            row.set_child(lbl)
            self.listbox.append(row)
            return
        for it in items:
            self.listbox.append(self._row(it))

    def _row(self, it):
        kind = it.get("kind", "read")
        text = (it.get("text") or "").strip()
        oneline = " ".join(text.split())
        preview = oneline if len(oneline) <= 90 else oneline[:90] + "…"

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(6)

        is_dict = (kind == "dictate")
        icon = Gtk.Image.new_from_icon_name(
            "audio-input-microphone-symbolic" if is_dict
            else "audio-volume-high-symbolic")
        icon.set_tooltip_text(_("Dictate") if is_dict else _("Read"))
        box.append(icon)

        lbl = Gtk.Label(label=preview, xalign=0.0)
        lbl.set_hexpand(True)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_tooltip_text(oneline)
        box.append(lbl)

        read_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        read_btn.set_tooltip_text(_("Read"))
        _a11y(read_btn, _("Read"))
        read_btn.connect("clicked", lambda *_a, t=text: self._read(t))
        box.append(read_btn)

        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_btn.set_tooltip_text(_("Copy"))
        _a11y(copy_btn, _("Copy"))
        copy_btn.connect("clicked", lambda *_a, t=text: self._copy(t))
        box.append(copy_btn)

        row.set_child(box)
        return row

    def _read(self, text):
        threading.Thread(target=vf.speak, args=(text, self.win._active_cfg()),
                         daemon=True).start()
        self.win.set_status(_("Re-reading from history"))

    def _copy(self, text):
        ok = vf._clipboard_set(text)
        self.win.set_status(_("Copied to clipboard") if ok else _("Copy failed"))

    def _on_clear(self, _btn):
        vf.save_history([])
        self._reload()
        self.win.set_status(_("History cleared"))


class PreferencesWindow(Gtk.Window):
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

        # Tabbed layout: each page is short and scrolls, so the window stays
        # usable on small screens.
        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)

        def _page(child):
            for m in ("top", "bottom", "start", "end"):
                getattr(child, f"set_margin_{m}")(14)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_vexpand(True)
            sw.set_child(child)
            return sw

        notebook.append_page(_page(self._slot_group("slot1", _("Language 1"))),
                             Gtk.Label(label=_("Language 1")))
        notebook.append_page(_page(self._slot_group("slot2", _("Language 2"))),
                             Gtk.Label(label=_("Language 2")))
        notebook.append_page(_page(self._whisper_group()),
                             Gtk.Label(label=_("Dictation")))
        notebook.append_page(_page(self._pronunciation_group()),
                             Gtk.Label(label=_("Pronunciation")))
        notebook.append_page(_page(self._misc_group()),
                             Gtk.Label(label=_("Misc")))
        notebook.append_page(_page(self._interface_group()),
                             Gtk.Label(label=_("Interface")))
        notebook.append_page(_page(self._shortcuts_group()),
                             Gtk.Label(label=_("Shortcuts")))
        self.set_child(notebook)

        self.connect("close-request", self._on_close)

    def _on_close(self, *_a):
        if getattr(self, "_shortcuts_inhibited", False):
            self._stop_capture()
        self._save_pron()
        self.win.reload_active_controls()
        return False

    # ── Interface: UI scale + modular toolbar (3.0) ──────────────────────────
    def _interface_group(self):
        layout = vf.reconcile_toolbar_layout(self.state.get("ui_layout"),
                                             TOOLBAR_IDS)
        self.state["ui_layout"] = layout

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        # Interface size: 75 / 100 / 125 % as a radio group.
        size_frame = Gtk.Frame(label=_("Interface size"))
        srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(srow, f"set_margin_{m}")(10)
        radios, leader = [], None
        for s in vf.UI_SCALES:
            rb = Gtk.CheckButton(label=f"{s}%")
            if leader is None:
                leader = rb
            else:
                rb.set_group(leader)
            radios.append((s, rb))
            srow.append(rb)
        for s, rb in radios:
            rb.set_active(s == layout["scale"])
        for s, rb in radios:
            rb.connect("toggled", self._on_scale_toggled, s)
        size_frame.set_child(srow)
        box.append(size_frame)

        # Buttons: per-button visibility toggle + up/down reordering.
        btn_frame = Gtk.Frame(label=_("Buttons"))
        self._iface_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=4)
        for m in ("top", "bottom", "start", "end"):
            getattr(self._iface_list, f"set_margin_{m}")(10)
        self._populate_button_list()
        btn_frame.set_child(self._iface_list)
        box.append(btn_frame)
        return box

    def _on_scale_toggled(self, rb, scale):
        if rb.get_active():
            self.win.apply_ui_scale(scale)

    def _populate_button_list(self):
        # Clear current rows.
        child = self._iface_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._iface_list.remove(child)
            child = nxt
        labels = {b[0]: b[2] for b in TOOLBAR_BUTTONS}
        labels["switch"] = "Switch language"
        buttons = self.state["ui_layout"]["buttons"]
        n = len(buttons)
        for i, entry in enumerate(buttons):
            bid = entry["id"]
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            chk = Gtk.CheckButton(label=_(labels.get(bid, bid)))
            chk.set_active(entry["visible"])
            chk.set_hexpand(True)
            chk.connect("toggled", self._on_btn_visible, bid)
            up = Gtk.Button(icon_name="go-up-symbolic")
            up.set_tooltip_text(_("Move up"))
            up.set_sensitive(i > 0)
            up.connect("clicked", self._on_btn_move, bid, -1)
            down = Gtk.Button(icon_name="go-down-symbolic")
            down.set_tooltip_text(_("Move down"))
            down.set_sensitive(i < n - 1)
            down.connect("clicked", self._on_btn_move, bid, 1)
            row.append(chk)
            row.append(up)
            row.append(down)
            self._iface_list.append(row)

    def _on_btn_visible(self, chk, bid):
        for e in self.state["ui_layout"]["buttons"]:
            if e["id"] == bid:
                e["visible"] = chk.get_active()
                break
        vf.save_state(self.state)
        self.win.rebuild_ui()

    def _on_btn_move(self, _btn, bid, delta):
        buttons = self.state["ui_layout"]["buttons"]
        idx = next((i for i, e in enumerate(buttons) if e["id"] == bid), None)
        if idx is None:
            return
        new = idx + delta
        if new < 0 or new >= len(buttons):
            return
        buttons[idx], buttons[new] = buttons[new], buttons[idx]
        vf.save_state(self.state)
        self._populate_button_list()
        self.win.rebuild_ui()

    # ── Shortcuts: per-action key capture + one-shot install (3.3) ───────────
    def _shortcuts_group(self):
        self._capturing_key = None
        self._capture_btns = {}
        self._shortcuts_inhibited = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_text(_("Click a shortcut and press the key combination you "
                         "want. Then choose Install shortcuts to register them "
                         "with your desktop. Nothing is installed automatically."))
        box.append(intro)

        frame = Gtk.Frame(label=_("Shortcuts"))
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("top", "bottom", "start", "end"):
            getattr(rows, f"set_margin_{m}")(10)

        for key, _label, _cmd, default in _SHORTCUT_ACTIONS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            name = Gtk.Label(label=_(_SHORTCUT_LABELS.get(key, key)), xalign=0)
            name.set_hexpand(True)
            row.append(name)

            cap = Gtk.Button(label=_binding_display(
                _binding_for(self.state, key, default)))
            cap.set_size_request(140, -1)
            cap.connect("clicked", self._on_capture_clicked, key)
            ctrl = Gtk.EventControllerKey()
            # CAPTURE phase: intercept keys before the button activates on Space.
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", self._on_capture_key, key, cap)
            cap.add_controller(ctrl)
            self._capture_btns[key] = cap
            row.append(cap)
            rows.append(row)

        frame.set_child(rows)
        box.append(frame)

        # Action row: reset + install, with a result label.
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset = Gtk.Button(label=_("Reset to defaults"))
        reset.connect("clicked", self._on_shortcuts_reset)
        install = Gtk.Button(label=_("Install shortcuts"))
        install.add_css_class("suggested-action")
        install.connect("clicked", self._on_shortcuts_install)
        actions.append(reset)
        actions.append(install)
        box.append(actions)

        self._shortcut_result = Gtk.Label(xalign=0, wrap=True)
        box.append(self._shortcut_result)
        return box

    def _begin_capture(self, key, btn):
        # Stop any capture already running on another row.
        if self._capturing_key and self._capturing_key != key:
            prev = self._capture_btns.get(self._capturing_key)
            if prev:
                self._refresh_capture_label(self._capturing_key, prev)
        self._capturing_key = key
        btn.set_label(_("Press keys…"))
        btn.add_css_class("suggested-action")
        btn.grab_focus()
        # Ask the compositor/WM to deliver system-grabbed combinations to this
        # window during capture, so a key that is already a global shortcut can
        # still be recorded here (otherwise the WM swallows it and we never see
        # the press). Best-effort: a no-op where the backend doesn't support it.
        try:
            surface = self.get_surface()
            if surface is not None and not self._shortcuts_inhibited:
                surface.inhibit_system_shortcuts(None)
                self._shortcuts_inhibited = True
        except Exception as e:
            log.debug(f"inhibit_system_shortcuts failed: {e}")

    def _stop_capture(self):
        self._capturing_key = None
        if self._shortcuts_inhibited:
            try:
                surface = self.get_surface()
                if surface is not None:
                    surface.restore_system_shortcuts()
            except Exception as e:
                log.debug(f"restore_system_shortcuts failed: {e}")
            self._shortcuts_inhibited = False

    def _refresh_capture_label(self, key, btn):
        default = next((d for k, _l, _c, d in _SHORTCUT_ACTIONS if k == key), "")
        btn.set_label(_binding_display(_binding_for(self.state, key, default)))
        btn.remove_css_class("suggested-action")

    def _on_capture_clicked(self, btn, key):
        self._begin_capture(key, btn)

    def _on_capture_key(self, _ctrl, keyval, _keycode, gtk_state, key, btn):
        if self._capturing_key != key:
            return False
        if keyval == Gdk.KEY_Escape:                 # cancel
            self._stop_capture()
            self._refresh_capture_label(key, btn)
            return True
        # Ignore bare modifier presses — wait for a real key.
        if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L,
                      Gdk.KEY_Alt_R, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
                      Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L,
                      Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift):
            return True
        mods = gtk_state & Gtk.accelerator_get_default_mod_mask()
        if not Gtk.accelerator_valid(keyval, mods):
            return True                              # not usable yet
        binding = Gtk.accelerator_name(keyval, mods)
        # Reject a combination already assigned to another VoxFox action, so two
        # actions can't fight over the same key.
        for k, _l, _c, d in _SHORTCUT_ACTIONS:
            if k != key and _binding_for(self.state, k, d) == binding:
                self._stop_capture()
                self._refresh_capture_label(key, btn)
                self._shortcut_result.set_text(
                    _("That key combination is already used by another "
                      "VoxFox shortcut."))
                return True
        self.state.setdefault("shortcut_bindings", {})[key] = binding
        vf.save_state(self.state)
        self._stop_capture()
        btn.set_label(_binding_display(binding))
        btn.remove_css_class("suggested-action")
        self._shortcut_result.set_text("")
        return True

    def _on_shortcuts_reset(self, _btn):
        self._stop_capture()
        self.state["shortcut_bindings"] = {}
        vf.save_state(self.state)
        for key, cap in self._capture_btns.items():
            self._refresh_capture_label(key, cap)
        self._shortcut_result.set_text(_("Shortcuts reset to defaults."))

    def _on_shortcuts_install(self, _btn):
        try:
            ok = _install_shortcuts(self.state)
        except Exception as e:
            log.debug(f"install shortcuts (settings) failed: {e}")
            ok = False
        vf.save_state(self.state)
        if ok:
            if _cinnamon_reload():
                self._shortcut_result.set_text(
                    _("Shortcuts installed. The desktop was reloaded to "
                      "activate them."))
            else:
                self._shortcut_result.set_text(
                    _("Shortcuts installed. You can change or remove them in "
                      "your system keyboard settings."))
        else:
            self._shortcut_result.set_text(
                _("Could not install shortcuts on this desktop. Your desktop "
                  "may use a different method — set them manually in its "
                  "keyboard settings."))

    # ── per-slot language + voice + speed ────────────────────────────────────
    def _slot_group(self, slot, title):
        cfg = self.state[slot]
        frame = Gtk.Frame(label=title)
        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        for m in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{m}")(10)
        frame.set_child(grid)

        langs = vf.get_languages(self.all_voices)
        if not langs and cfg.get("lang"):
            langs = [cfg["lang"]]
        lang_dd = _dropdown(langs, cfg.get("lang", ""))
        _a11y(lang_dd, f"{title} — {_('Language')}")

        voices = sorted(vf.get_voices_for_lang(self.all_voices, cfg.get("lang", "")))
        if not voices:
            voices = sorted(v for v in vf.get_local_voices())
        voice_dd = _dropdown(voices, cfg.get("voice", ""))
        _a11y(voice_dd, f"{title} — {_('Voice')}")

        status = Gtk.Label(xalign=0.0)
        status.add_css_class("dim-label")

        grid.attach(Gtk.Label(label=_("Language:"), xalign=0), 0, 0, 1, 1)
        grid.attach(lang_dd, 1, 0, 1, 1)
        lang_dd.set_hexpand(True)
        grid.attach(Gtk.Label(label=_("Voice:"), xalign=0), 0, 1, 1, 1)
        grid.attach(voice_dd, 1, 1, 1, 1)
        grid.attach(status, 0, 2, 2, 1)

        speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.5, 2.0, 0.05)
        speed.set_value(float(cfg.get("speed", 1.0)))
        speed.set_hexpand(True)
        speed.set_draw_value(True)
        grid.attach(Gtk.Label(label=_("Speed:"), xalign=0), 0, 3, 1, 1)
        grid.attach(speed, 1, 3, 1, 1)
        _a11y(speed, _("Speed:").rstrip(": "))

        # Pitch in semitones: 0 = the voice's natural pitch, negative = lower,
        # positive = higher. Applied in the speech worker by playing at a shifted
        # sample rate and compensating the tempo via Piper's length_scale, so the
        # speaking rate above is unaffected.
        pitch = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -12, 12, 1)
        pitch.set_value(float(cfg.get("pitch", 0.0)))
        pitch.set_hexpand(True)
        pitch.set_draw_value(True)
        grid.attach(Gtk.Label(label=_("Pitch:"), xalign=0), 0, 4, 1, 1)
        grid.attach(pitch, 1, 4, 1, 1)
        _a11y(pitch, _("Pitch:").rstrip(": "))

        def on_lang(dd, _p):
            lang = _dropdown_value(dd)
            cfg["lang"] = lang
            keys = sorted(vf.get_voices_for_lang(self.all_voices, lang))
            local = vf.get_local_voices()
            chosen = next((k for k in keys if k in local),
                          keys[0] if keys else "")
            cfg["voice"] = chosen
            vf.save_state(self.state)
            _set_dropdown_items(voice_dd, keys, chosen)
            if slot == "slot1":
                apply_ui_language(lang)
                self.win.rebuild_ui()

        def on_voice(dd, _p):
            voice = _dropdown_value(dd)
            if not voice:
                return
            cfg["voice"] = voice
            vf.save_state(self.state)
            if voice not in vf.get_local_voices():
                self._download_voice_async(slot, voice, status)
            else:
                status.set_text("")

        def on_speed(sc):
            cfg["speed"] = round(sc.get_value(), 2)
            vf.save_state(self.state)

        def on_pitch(sc):
            cfg["pitch"] = round(sc.get_value(), 1)
            vf.save_state(self.state)

        lang_dd.connect("notify::selected", on_lang)
        voice_dd.connect("notify::selected", on_voice)
        speed.connect("value-changed", on_speed)
        pitch.connect("value-changed", on_pitch)
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
        self.model_dd = _dropdown(vf.WHISPER_MODELS, w.get("model", "small"))
        self.model_dd.set_hexpand(True)
        _a11y(self.model_dd, _("Whisper model"))
        self.model_dd.connect("notify::selected", self._on_model_changed)
        dl_btn = Gtk.Button(icon_name="document-save-symbolic")
        dl_btn.set_tooltip_text(_("Download the selected model now"))
        _a11y(dl_btn, _("Download the selected Whisper model"))
        dl_btn.connect("clicked", self._on_model_download)
        model_box.append(self.model_dd)
        model_box.append(dl_btn)
        grid.attach(model_box, 1, r, 1, 1)
        self.model_status = Gtk.Label(xalign=0.0)
        self.model_status.add_css_class("dim-label")
        grid.attach(self.model_status, 0, r + 1, 2, 1)
        # Download progress for the model button, just below the status text.
        self.dl_progress = Gtk.ProgressBar(show_text=True)
        self.dl_progress.set_visible(False)
        grid.attach(self.dl_progress, 0, r + 2, 2, 1)
        self._refresh_model_status()
        r += 3

        # Compute device (Auto detects an NVIDIA GPU, else CPU).
        grid.attach(Gtk.Label(label=_("Compute:"), xalign=0), 0, r, 1, 1)
        dev = w.get("device", "auto")
        self._dev_values = ["auto", "cpu", "cuda"]
        dev_labels = [_("Auto (GPU if available)"), _("CPU"), _("GPU (NVIDIA)")]
        self.dev_dd = _dropdown(
            dev_labels, dev_labels[self._dev_values.index(dev)]
            if dev in self._dev_values else dev_labels[0])
        self.dev_dd.set_hexpand(True)
        _a11y(self.dev_dd, _("Compute device"))
        self.dev_dd.set_tooltip_text(
            _("Auto uses an NVIDIA GPU when detected (needs CUDA + cuDNN), "
              "otherwise the CPU. Falls back to CPU if GPU init fails."))
        self.dev_dd.connect("notify::selected", self._on_device_changed)
        grid.attach(self.dev_dd, 1, r, 1, 1)
        self.dev_status = Gtk.Label(xalign=0.0)
        self.dev_status.add_css_class("dim-label")
        self.dev_status.set_text(
            _("NVIDIA GPU detected") if vf._cuda_available()
            else _("no GPU detected — using CPU"))
        grid.attach(self.dev_status, 0, r + 1, 2, 1)
        r += 2

        # Microphone + refresh
        grid.attach(Gtk.Label(label=_("Mic:"), xalign=0), 0, r, 1, 1)
        mic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._mic_options = vf.list_microphones()
        self._mic_labels  = [lbl for (_id, lbl) in self._mic_options]
        cur_id = w.get("mic_id", "")
        cur_lbl = next((lbl for (mid, lbl) in self._mic_options if mid == cur_id),
                       self._mic_labels[0] if self._mic_labels else _("Default"))
        self.mic_dd = _dropdown(self._mic_labels, cur_lbl)
        self.mic_dd.set_hexpand(True)
        _a11y(self.mic_dd, _("Microphone"))
        self.mic_dd.connect("notify::selected", self._on_mic_changed)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text(_("Refresh microphone list"))
        _a11y(refresh, _("Refresh microphone list"))
        refresh.connect("clicked", self._on_mic_refresh)
        mic_box.append(self.mic_dd)
        mic_box.append(refresh)
        grid.attach(mic_box, 1, r, 1, 1)
        r += 1

        # Confirm before typing
        confirm = Gtk.CheckButton(label=_("Confirm transcription before typing"))
        confirm.set_active(bool(w.get("confirm_before_typing", False)))
        confirm.connect("toggled", self._on_confirm_toggled)
        grid.attach(confirm, 0, r, 2, 1)
        r += 1

        # Backend
        grid.attach(Gtk.Label(label=_("Backend:"), xalign=0), 0, r, 1, 1)
        self.backend_dd = _dropdown([_("Local"), _("Remote API")],
                                    _("Remote API") if w.get("backend") == "remote"
                                    else _("Local"))
        self.backend_dd.connect("notify::selected", self._on_backend_changed)
        _a11y(self.backend_dd, _("Whisper backend"))
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
        return frame

    def _save_w(self, key, value):
        self.state["whisper"][key] = value
        vf.save_state(self.state)

    def _refresh_model_status(self):
        name = _dropdown_value(self.model_dd)
        if vf._whisper_model_is_cached(name):
            self.model_status.set_text(f"✓ {_('model downloaded')}")
        else:
            self.model_status.set_text(_("model not downloaded yet"))

    def _on_model_changed(self, dd, _p):
        self._save_w("model", _dropdown_value(dd))
        self._refresh_model_status()

    # ── pronunciation dictionary (slot 1's language) ─────────────────────────
    def _pronunciation_group(self):
        frame = Gtk.Frame(label=_("Pronunciation dictionary"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.set_child(box)

        self._pron_lang = self.state["slot1"].get("lang", "")
        native = vf.piper_lang_native(self._pron_lang) or self._pron_lang or "?"
        info = Gtk.Label(xalign=0.0)
        info.set_wrap(True)
        info.add_css_class("dim-label")
        info.set_text(
            _("Rules for slot 1's language (%s). Words are matched whole and "
              "case-insensitively, then re-spelled before they are spoken.")
            % native)
        box.append(info)

        self.pron_list = Gtk.ListBox()
        self.pron_list.set_selection_mode(Gtk.SelectionMode.NONE)
        box.append(self.pron_list)
        self._pron_rows = []

        existing = self.state.get("pronunciations", {}).get(self._pron_lang, {})
        for word, repl in existing.items():
            self._add_pron_row(word, repl)
        if not self._pron_rows:
            self._add_pron_row("", "")

        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label=_("Add rule"))
        add_btn.connect("clicked", lambda *_a: self._add_pron_row("", ""))
        btnrow.append(add_btn)
        box.append(btnrow)
        return frame

    def _add_pron_row(self, word, repl):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        we = Gtk.Entry()
        we.set_placeholder_text(_("Word"))
        we.set_text(word)
        we.set_hexpand(True)
        rep = Gtk.Entry()
        rep.set_placeholder_text(_("Pronounce as"))
        rep.set_text(repl)
        rep.set_hexpand(True)
        rm = Gtk.Button(icon_name="user-trash-symbolic")
        rm.set_tooltip_text(_("Remove rule"))
        test = Gtk.Button(icon_name="media-playback-start-symbolic")
        test.set_tooltip_text(_("Test this word"))
        _a11y(we, _("Word"))
        _a11y(rep, _("Pronounce as"))
        _a11y(rm, _("Remove rule"))
        _a11y(test, _("Test this word"))
        row.append(we)
        row.append(Gtk.Label(label="→"))
        row.append(rep)
        row.append(test)
        row.append(rm)
        lbrow = Gtk.ListBoxRow()
        lbrow.set_child(row)
        rec = {"word": we, "repl": rep, "lbrow": lbrow}

        def _test_one(*_a):
            txt = rep.get_text().strip() or we.get_text().strip()
            if txt:
                threading.Thread(target=vf.speak,
                                 args=(txt, self.state["slot1"]),
                                 daemon=True).start()
        test.connect("clicked", _test_one)

        def _remove(*_a):
            self.pron_list.remove(lbrow)
            if rec in self._pron_rows:
                self._pron_rows.remove(rec)
            self._save_pron()
        rm.connect("clicked", _remove)
        self.pron_list.append(lbrow)
        self._pron_rows.append(rec)

    def _collect_pron(self):
        d = {}
        for rec in self._pron_rows:
            w = rec["word"].get_text().strip()
            r = rec["repl"].get_text().strip()
            if w and r:
                d[w] = r
        return d

    def _save_pron(self):
        if not hasattr(self, "_pron_rows"):
            return
        d = self._collect_pron()
        pron = self.state.setdefault("pronunciations", {})
        if d:
            pron[self._pron_lang] = d
        elif self._pron_lang in pron:
            del pron[self._pron_lang]
        vf.save_state(self.state)
        vf.set_pronunciations(pron)

    # ── misc: line merging + import/export ───────────────────────────────────
    def _misc_group(self):
        frame = Gtk.Frame(label=_("Misc"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.set_child(box)

        self.merge_chk = Gtk.CheckButton(
            label=_("Merge wrapped lines into paragraphs"))
        self.merge_chk.set_active(bool(self.state.get("merge_lines", True)))
        self.merge_chk.connect("toggled", self._on_merge_toggled)
        box.append(self.merge_chk)

        desc = Gtk.Label(xalign=0.0)
        desc.set_wrap(True)
        desc.add_css_class("dim-label")
        desc.set_text(_("When reading OCR or selected text, join lines that are "
                        "only word-wrapped and pause only at real paragraphs. "
                        "Turn off to read every line separately (lists, code)."))
        box.append(desc)

        box.append(Gtk.Separator())

        slabel = Gtk.Label(xalign=0.0, label=_("Settings file"))
        box.append(slabel)
        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        imp = Gtk.Button(label=_("Import settings…"))
        imp.connect("clicked", self._on_import)
        exp = Gtk.Button(label=_("Export settings…"))
        exp.connect("clicked", self._on_export)
        btnrow.append(imp)
        btnrow.append(exp)
        box.append(btnrow)
        return frame

    def _on_merge_toggled(self, btn):
        on = btn.get_active()
        self.state["merge_lines"] = on
        vf.save_state(self.state)
        vf.set_merge_lines(on)



    def _on_export(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Export settings"), self, Gtk.FileChooserAction.SAVE, None, None)
        dlg.set_current_name("voxfox-settings.json")
        dlg.set_modal(True)
        dlg.connect("response", self._export_response)
        self._file_dlg = dlg
        dlg.show()

    def _export_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                import json
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, ensure_ascii=False, indent=2)
                self.win.set_status(_("Settings exported"))
            except Exception as e:
                self.win.set_status(f"{_('Export failed')}: {e}")
        dlg.destroy()

    def _on_import(self, _btn):
        dlg = Gtk.FileChooserNative.new(
            _("Import settings"), self, Gtk.FileChooserAction.OPEN, None, None)
        flt = Gtk.FileFilter()
        flt.set_name("JSON")
        flt.add_pattern("*.json")
        dlg.add_filter(flt)
        dlg.set_modal(True)
        dlg.connect("response", self._import_response)
        self._file_dlg = dlg
        dlg.show()

    def _import_response(self, dlg, resp):
        if resp == Gtk.ResponseType.ACCEPT and dlg.get_file():
            path = dlg.get_file().get_path()
            try:
                import json
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("not a settings object")
                vf.save_state(data)
                self.state = vf.load_state()
                self.win.state = self.state
                vf.set_pronunciations(self.state.get("pronunciations", {}))
                vf.set_merge_lines(self.state.get("merge_lines", True))
                apply_ui_language(self.state["slot1"].get("lang", ""))
                self.win.rebuild_ui()
                self.win.set_status(_("Settings imported"))
                dlg.destroy()
                self.close()
                return
            except Exception as e:
                self.win.set_status(f"{_('Import failed')}: {e}")
        dlg.destroy()

    def _set_dl_progress(self, fraction, label=None):
        if _set_progress_bar(self.dl_progress, fraction, label) >= 1.0:
            GLib.timeout_add(800, self._hide_dl_progress)
        return False

    def _hide_dl_progress(self):
        return _hide_progress_bar(self.dl_progress)

    def _on_model_download(self, _btn):
        name = _dropdown_value(self.model_dd)
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
        self._mic_options = vf.list_microphones()
        self._mic_labels  = [lbl for (_id, lbl) in self._mic_options]
        _set_dropdown_items(self.mic_dd, self._mic_labels,
                            self._mic_labels[0] if self._mic_labels else None)

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
            tmp = os.path.join(tempfile.gettempdir(), "voxfox_test.wav")
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
                self.win.set_status(m, 8)
            GLib.idle_add(_show)
        threading.Thread(target=worker, daemon=True).start()


class VoxFoxWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=vf.APP_NAME)
        # No fixed default size: let the window size itself to the toolbar's
        # natural size, so it is exactly wide enough for the visible buttons
        # (4-5 on one row) and exactly tall enough (no empty filler below). It
        # stays resizable, and the maximize button is dropped via the header
        # decoration layout in _build_ui.
        self.state      = vf.load_state()
        self.whisper_on = False
        self._record_stop_event = None
        self.hover_on   = False
        self.root       = _RootShim()
        # 3.0 UI scale: one CSS provider on the display whose root font-size we
        # swap to zoom the whole main window (see _scale_css / apply_ui_scale).
        self._scale_provider = Gtk.CssProvider()
        try:
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self._scale_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as e:
            log.debug(f"scale provider add failed: {e}")
        self._load_scale_css()
        # Hover mode (in voxfox_core) asks this callback which voice to speak with.
        vf.set_slot_config_provider(self._active_cfg)
        self._build_ui()
        self._sync_pause_btn()
        # Keep the window above others: re-assert "always on top" whenever it
        # stops being the active window (e.g. another app was opened). The
        # initial assert is done from do_activate once the window is mapped.
        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request",
                     lambda *_a: (self.do_quit_cleanup(), False)[1])

    def _on_active_changed(self, *_a):
        if not self.is_active():
            self.set_always_on_top()

    def rebuild_ui(self):
        """Rebuild the whole window UI in place. Used to re-render every label
        in a new UI language when slot 1's language changes, and after the
        toolbar layout (visible buttons / order) changes."""
        self._build_ui()
        self._sync_pause_btn()
        self._fit_to_content()

    def _load_scale_css(self):
        """(Re)load the scale provider from the scale stored in ui_layout."""
        scale = (self.state.get("ui_layout") or {}).get("scale",
                                                         vf.DEFAULT_UI_SCALE)
        if scale not in vf.UI_SCALES:
            scale = vf.DEFAULT_UI_SCALE
        try:
            self._scale_provider.load_from_data(_scale_css(scale))
        except Exception as e:
            log.debug(f"scale css load failed: {e}")

    def apply_ui_scale(self, scale):
        """Set the global UI scale (75/100/125) live — no rebuild needed, the
        CSS cascade reflows the toolbar. Persists the choice and shrinks the
        window back to the new, smaller content size."""
        if scale not in vf.UI_SCALES:
            scale = vf.DEFAULT_UI_SCALE
        self.state.setdefault("ui_layout", {})["scale"] = scale
        vf.save_state(self.state)
        self._load_scale_css()
        self._fit_to_content()

    def _fit_to_content(self):
        """Shrink the window to the toolbar's current natural size (X11, best-
        effort). GTK4 doesn't auto-shrink a window when its content gets smaller
        (after lowering the UI scale or hiding buttons), so we nudge it via
        wmctrl to keep the window as narrow/short as the visible buttons allow.
        The window stays resizable; this only removes leftover empty space."""
        if not vf._have("wmctrl"):
            return

        def do_fit():
            try:
                _min, nat = self.get_preferred_size()
                w, h = max(1, nat.width), max(1, nat.height)
            except Exception as e:
                log.debug(f"fit measure failed: {e}")
                return False

            def worker():
                try:
                    subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                    "-e", f"0,-1,-1,{w},{h}"], timeout=5)
                except Exception as e:
                    log.debug(f"fit-to-content failed: {e}")
            threading.Thread(target=worker, daemon=True).start()
            return False
        # Defer so the new CSS / layout has settled before we measure.
        GLib.timeout_add(50, do_fit)

    def _build_ui(self):
        header = Gtk.HeaderBar()
        header.add_css_class("voxfox-root")   # scale the title + header icons too
        # Drop the useless maximize button; keep minimize + close. The window
        # stays resizable by edge-drag.
        header.set_decoration_layout(":minimize,close")
        self.set_titlebar(header)

        # The language switcher lives at the end of the second button row
        # (added below), not in the header — that frees the title bar to show
        # the program name.
        self.switch_btn = Gtk.Button()
        self.switch_btn.set_tooltip_text(_("Switch language slot"))
        _a11y(self.switch_btn, _("Switch language slot"))
        self.switch_btn.connect("clicked", lambda *_a: self.do_toggle_slot())

        gear = Gtk.Button(icon_name="emblem-system-symbolic")
        gear.set_tooltip_text(_("Settings"))
        _a11y(gear, _("Settings"))
        gear.connect("clicked", lambda *_a: self.open_preferences())
        header.pack_end(gear)

        menu = Gio.Menu()
        menu.append(_("Set up VoxFox…"), "app.first_run")
        menu.append(_("History"), "app.history")
        menu.append(_("About"), "app.about")
        menu.append(_("Quit"),  "app.quit")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        menu_btn.set_tooltip_text(_("Menu"))
        _a11y(menu_btn, _("Menu"))
        header.pack_end(menu_btn)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.add_css_class("voxfox-root")   # scopes the 3.0 UI-scale CSS
        outer.add_css_class("voxfox-pad")    # em-based padding, scales with size
        self.set_child(outer)

        # Setup banner — only shown when the Piper engine is missing.
        self.setup_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.setup_bar.add_css_class("card")
        lbl = Gtk.Label(label=_("Piper TTS is not installed yet."), xalign=0,
                        hexpand=True)
        setup_btn = Gtk.Button(label=_("Install now"))
        setup_btn.add_css_class("voxfox-accent")
        _a11y(setup_btn, _("Install Piper and components now"))
        setup_btn.connect("clicked", lambda *_a: SetupDialog(self).present())
        self.setup_bar.append(lbl)
        self.setup_bar.append(setup_btn)
        outer.append(self.setup_bar)

        # ── Modular toolbar (3.0) ────────────────────────────────────────────
        # The seven action buttons, shown and ordered per the user's ui_layout.
        # All seven are always instantiated (other code refers to self.read_btn,
        # self.whisper_btn, ...), but only the enabled ones are packed, in the
        # chosen order. The language switcher is fixed and always shown last.
        self._toolbar_btns = {}
        for bid, attr, label, tip, a11y_lbl, handler, css in TOOLBAR_BUTTONS:
            btn = Gtk.Button(label=_(label))
            btn.set_tooltip_text(_(tip))
            _a11y(btn, _(a11y_lbl))
            if css:
                btn.add_css_class(css)
            btn.connect("clicked", lambda *_a, h=handler: getattr(self, h)())
            setattr(self, attr, btn)
            self._toolbar_btns[bid] = btn
        # The language switcher is a modular button too (id "switch"); it is
        # built specially because its label is dynamic (the current language).
        self._toolbar_btns["switch"] = self.switch_btn
        # Note: labels are deliberately NOT ellipsized or width-capped. Showing
        # the full text means each button's minimum width is its full label, so
        # the window can never shrink small enough to clip the text — the
        # buttons stay fully readable at every scale. (The dictate button no
        # longer needs a width cap: its recording label is the short "Stop".)

        layout = vf.reconcile_toolbar_layout(self.state.get("ui_layout"),
                                             TOOLBAR_IDS)
        self.state["ui_layout"] = layout

        # Lay the visible buttons out in explicit rows rather than a FlowBox.
        # A FlowBox wraps on window width (so a narrow window split 4 buttons as
        # 3+1) and, worse, negotiates a tall minimum height as if every button
        # might stack in one column — which left empty vertical space the window
        # could not be shrunk below. Explicit rows give a predictable, compact
        # size: up to 5 buttons on one row, 6+ split evenly over two rows.
        visible_ids = [e["id"] for e in layout["buttons"] if e["visible"]]
        n = len(visible_ids)
        if n <= 5:
            rows = [visible_ids] if visible_ids else []
        else:
            half = (n + 1) // 2
            rows = [visible_ids[:half], visible_ids[half:]]
        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar.add_css_class("voxfox-toolbar")
        toolbar.set_halign(Gtk.Align.FILL)
        toolbar.set_hexpand(True)
        for row_ids in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0,
                          homogeneous=True)
            row.set_halign(Gtk.Align.FILL)
            row.set_hexpand(True)
            for bid in row_ids:
                btn = self._toolbar_btns[bid]
                btn.set_hexpand(True)
                row.append(btn)
            toolbar.append(row)
        outer.append(toolbar)

        # STATUS role makes screen readers announce status changes (a live
        # region), so blind users hear "Reading...", errors, etc.
        self.status = Gtk.Label(label="", xalign=0.0,
                                accessible_role=Gtk.AccessibleRole.STATUS)
        self.status.add_css_class("dim-label")
        self.status.set_wrap(True)
        self.status.set_visible(False)
        outer.append(self.status)

        # Download progress, shown just below the status line. Hidden until a
        # download (Whisper model, Piper engine/voices) is running.
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_visible(False)
        outer.append(self.progress)

        self._sync_switch_btn()
        self.refresh_setup_bar()

    # ── helpers ───────────────────────────────────────────────────────────────
    def _active_slot(self):
        return self.state.get("active_slot", "slot1")

    def _active_cfg(self):
        return self.state[self._active_slot()]

    def set_status(self, msg, duration=2000):
        if msg:
            self.status.set_text(msg)
            self.status.set_visible(True)
            if duration and duration > 0:
                GLib.timeout_add(duration, self._clear_status)
        else:
            self._clear_status()

    def _clear_status(self):
        self.status.set_text("")
        self.status.set_visible(False)
        return False

    def set_progress(self, fraction, label=None):
        """Show/update the download progress bar (call on the GUI thread)."""
        if _set_progress_bar(self.progress, fraction, label) >= 1.0:
            GLib.timeout_add(800, self.hide_progress)
        return False

    def hide_progress(self):
        return _hide_progress_bar(self.progress)

    def refresh_setup_bar(self):
        self.setup_bar.set_visible(not os.path.exists(vf.PIPER_BIN))

    def get_window_pos(self):
        """Return (x, y) of our window via wmctrl (X11 only), or None.
        GTK4 has no portable get_position(), so we read it from the window
        manager. Matches our window by its exact title (APP_NAME)."""
        if not vf._have("wmctrl"):
            return None
        try:
            r = subprocess.run(["wmctrl", "-lG"],
                               capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                parts = line.split(None, 7)
                if len(parts) >= 8 and parts[7].strip() == vf.APP_NAME:
                    return (int(parts[2]), int(parts[3]))
        except Exception as e:
            log.debug(f"could not read window position: {e}")
        return None

    def save_window_pos(self):
        """Remember the current window position so the next start reopens here."""
        try:
            pos = self.get_window_pos()
            if pos:
                self.state["win_pos"] = [pos[0], pos[1]]
                vf.save_state(self.state)
        except Exception as e:
            log.debug(f"could not save window position: {e}")

    def restore_window_pos(self):
        """Move the window back to its saved position (X11 only, best-effort).
        Size is left unchanged (-1,-1)."""
        pos = (self.state or {}).get("win_pos")
        if not pos or not vf._have("wmctrl"):
            return
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError, IndexError):
            return

        def worker():
            try:
                subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                "-e", f"0,{x},{y},-1,-1"], timeout=5)
            except Exception as e:
                log.debug(f"restore window position failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def set_always_on_top(self):
        """Keep the window above others, like the old Tk build's -topmost.
        GTK4 dropped a native always-on-top API, so this is best-effort via
        wmctrl and only takes effect on X11 (Wayland leaves stacking to the
        compositor)."""
        if not vf._have("wmctrl"):
            return

        def worker():
            try:
                subprocess.run(["wmctrl", "-F", "-r", vf.APP_NAME,
                                "-b", "add,above"], timeout=5)
            except Exception as e:
                log.debug(f"always-on-top failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def reload_active_controls(self):
        """Re-sync the title-bar slot indicator and setup banner from state
        (called after the Settings window changes things)."""
        self._sync_switch_btn()
        self.refresh_setup_bar()

    def _sync_switch_btn(self):
        try:
            self.switch_btn.set_label(
                vf.piper_lang_short(self._active_cfg().get("lang", "")))
        except Exception:
            self.switch_btn.set_label("•")

    def _sync_pause_btn(self):
        self.pause_btn.set_label(_("Resume") if vf.is_paused() else _("Pause"))

    def open_preferences(self):
        self._prefs = PreferencesWindow(self)
        self._prefs.present()

    # ── setup ─────────────────────────────────────────────────────────────────
    def run_setup_async(self, on_done=None):
        self.set_status(_("Setting up..."), duration=0)

        def worker():
            run_setup(progress=lambda m: GLib.idle_add(self.set_status, m, 0),
                      frac=lambda fr, lbl=None: GLib.idle_add(
                          self.set_progress, fr, lbl))
            def done():
                self.reload_active_controls()
                self.hide_progress()
                self.set_status(_("Setup complete"))
                self.refresh_setup_bar()
                if on_done:
                    on_done()
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    # ── actions (also the IPCServer entry points) ─────────────────────────────
    def do_read(self):
        text = vf.get_selection()
        if vf.merge_enabled():
            text = vf.merge_wrapped_lines(text)
        if len(text) >= 2:
            cfg = self._active_cfg()
            vf.add_history("read", text)
            threading.Thread(target=vf.speak, args=(text, cfg),
                             daemon=True).start()
            GLib.timeout_add(50, lambda: (self._sync_pause_btn(), False)[1])
            self.set_status(f"{_('Reading...')} [{cfg.get('voice', '')}]", 1500)
        else:
            self.set_status(_("Nothing selected"))

    def do_stop(self):
        vf.stop_speaking()
        self._sync_pause_btn()
        self.set_status(_("Stopped"))

    def do_pause(self):
        if not vf.is_speaking():
            self.set_status(_("Nothing to pause"))
            return
        paused = vf.toggle_pause()
        self._sync_pause_btn()
        self.set_status(_("Paused") if paused else _("Resumed"))

    def do_toggle_slot(self):
        new = "slot2" if self._active_slot() == "slot1" else "slot1"
        self.state["active_slot"] = new
        vf.save_state(self.state)
        self.reload_active_controls()
        cfg  = self.state[new]
        name = cfg.get("voice", new)
        self.set_status(f"{_('Language')}: {name}")
        threading.Thread(target=vf.speak, args=(f"{_('Language')}: {name}", cfg),
                         daemon=True).start()

    def do_whisper(self):
        if self.whisper_on:
            if self._record_stop_event:
                self._record_stop_event.set()
            self.set_status(_("Stopping..."), duration=0)
            return
        self.whisper_on = True
        self.whisper_btn.set_label(_("Stop"))
        self.whisper_btn.add_css_class("destructive-action")
        self.set_status(_("Recording..."), duration=0)
        self._record_stop_event = threading.Event()
        threading.Thread(target=self._whisper_worker, daemon=True).start()

    def _whisper_worker(self):
        w = self.state["whisper"]
        lang_hint = vf._whisper_lang_code(self._active_cfg().get("lang", ""))
        wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
            ok, msg = vf.record_audio(wav_path, mic_id=w.get("mic_id", ""),
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
            ok2, msg2 = vf.type_or_paste_text(text)
            if not ok2:
                self.root.after(0, self.set_status, f"{_('Type failed')}: {msg2}")
                return
            vf.add_history("dictate", text)
            preview = text if len(text) <= 40 else text[:40] + "..."
            self.root.after(0, self.set_status, f"✓ {preview}")
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

    def _whisper_reset_btn(self):
        self.whisper_on = False
        self.whisper_btn.set_label(_("Speak"))
        self.whisper_btn.remove_css_class("destructive-action")

    def do_ocr_file(self):
        dialog = Gtk.FileChooserNative(
            title=_("Open a PDF or image"), transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        flt = Gtk.FileFilter()
        flt.set_name(_("Documents and images"))
        for pat in ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff",
                    "*.gif", "*.webp"):
            flt.add_pattern(pat)
        dialog.add_filter(flt)

        def on_response(dlg, resp):
            if resp == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile:
                    self._run_ocr_path(gfile.get_path())
            dlg.destroy()
            self._filechooser = None

        self._filechooser = dialog  # hold a ref so it is not GC'd
        dialog.connect("response", on_response)
        dialog.show()

    def do_ocr_select(self):
        tess = vf._tess_lang(self._active_cfg().get("lang", ""))
        self.set_status(_("Select a region..."), duration=0)

        def worker():
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                ok, err = _grab_region_to_file(tmp)
                if not ok:
                    GLib.idle_add(self.set_status, err)
                    return
                GLib.idle_add(self.set_status, _("Reading text..."), 0)
                text, oerr = vf.ocr_image(tmp, tess_lang=tess)
                GLib.idle_add(self._after_ocr, text, oerr)
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _run_ocr_path(self, path):
        tess = vf._tess_lang(self._active_cfg().get("lang", ""))
        self.set_status(_("Reading text..."), duration=0)

        def worker():
            text, err = vf.ocr_file(
                path, tess_lang=tess,
                progress_cb=lambda m: self.root.after(0, self.set_status, m, 0))
            self.root.after(0, self._after_ocr, text, err)
        threading.Thread(target=worker, daemon=True).start()

    def _after_ocr(self, text, err):
        if err:
            self.set_status(err)
            return
        if not text or not text.strip():
            self.set_status(_("No text found"))
            return
        vf.add_history("read", text)
        threading.Thread(target=vf.speak, args=(text, self._active_cfg()),
                         daemon=True).start()
        self._sync_pause_btn()
        self.set_status(_("Reading..."), 1500)

    def do_hover(self):
        """Toggle hover-to-read. Mirrors the Tk build: an AT-SPI focus-event
        listener plus a polling fallback, controlled via vf.set_hover_running()."""
        if self.hover_on:
            vf.set_hover_running(False)
            self.hover_on = False
            self.hover_btn.remove_css_class("voxfox-accent")
            threading.Thread(target=vf._stop_event_listener, daemon=True).start()
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
            threading.Thread(target=vf._start_event_listener, daemon=True).start()
            threading.Thread(target=vf.hover_loop, daemon=True).start()

    def on_close(self):
        self.do_quit_cleanup()
        app = self.get_application()
        if app:
            app.quit()

    def do_quit_cleanup(self):
        self.save_window_pos()
        vf.set_hover_running(False)
        try:
            vf.stop_speaking()
        except Exception:
            pass
        try:
            vf.shutdown_piper()
        except Exception:
            pass
        srv = getattr(self.get_application(), "ipc_server", None)
        if srv:
            try:
                srv.stop()
            except Exception:
                pass


class SetupDialog(Gtk.Window):
    """One place that walks a new user through everything needed for first use:
    install the engine/voices/dictation/OCR components, switch on accessibility,
    and register the keyboard shortcuts. Each step shows whether it is already
    done and offers a single button to do it."""

    def __init__(self, parent):
        super().__init__(title=_("Set up VoxFox"), transient_for=parent,
                         modal=True)
        self.parent = parent
        self.set_default_size(460, -1)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{m}")(16)
        self.set_child(outer)

        intro = Gtk.Label(
            label=_("A few steps get VoxFox ready. You only need to do these "
                    "once; come back here any time from the menu."),
            xalign=0, wrap=True)
        intro.add_css_class("dim-label")
        outer.append(intro)

        self._rows = []

        # 1) Components: Piper engine + voices + faster-whisper + OCR python.
        self._comp_btn = Gtk.Button(label=_("Install now"))
        self._comp_btn.add_css_class("suggested-action")
        self._comp_btn.connect("clicked", self._on_install_components)
        outer.append(self._make_step(
            "components",
            _("Speech engine, voices and dictation"),
            _("Downloads Piper, the default voices, dictation (faster-whisper) "
              "and the OCR helpers. Needs an internet connection."),
            self._comp_btn))

        # 2) Accessibility bus (for hover reading across apps).
        self._a11y_btn = Gtk.Button(label=_("Enable"))
        self._a11y_btn.connect("clicked", self._on_enable_a11y)
        outer.append(self._make_step(
            "a11y",
            _("Enable accessibility (system-wide)"),
            _("Lets VoxFox read text in other apps and power hover reading. "
              "Restart those apps afterwards."),
            self._a11y_btn))

        # 3) Keyboard shortcuts (optional, never automatic).
        self._sc_btn = Gtk.Button(label=_("Install shortcuts"))
        self._sc_btn.connect("clicked", self._on_install_shortcuts)
        outer.append(self._make_step(
            "shortcuts",
            _("Keyboard shortcuts"),
            _("Registers the five VoxFox shortcuts on your desktop. Change the "
              "keys first under Settings → Shortcuts if you like."),
            self._sc_btn))

        # 4) OCR language packs — informational (installed via apt).
        info = Gtk.Label(
            label=_("For OCR in other languages, install the matching Tesseract "
                    "pack, e.g. sudo apt install tesseract-ocr-nld"),
            xalign=0, wrap=True, selectable=True)
        info.add_css_class("dim-label")
        outer.append(info)

        self._result = Gtk.Label(label="", xalign=0, wrap=True)
        outer.append(self._result)

        close = Gtk.Button(label=_("Close"))
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda *_a: self.close())
        outer.append(close)

        self._refresh_states()

    def _make_step(self, key, title, desc, button):
        frame = Gtk.Frame()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for m in ("top", "bottom", "start", "end"):
            getattr(row, f"set_margin_{m}")(10)
        status = Gtk.Label(label="", xalign=0.5)
        status.set_size_request(24, -1)
        textbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                          hexpand=True)
        t = Gtk.Label(label=title, xalign=0)
        t.add_css_class("heading")
        d = Gtk.Label(label=desc, xalign=0, wrap=True)
        d.add_css_class("dim-label")
        textbox.append(t)
        textbox.append(d)
        button.set_valign(Gtk.Align.CENTER)
        row.append(status)
        row.append(textbox)
        row.append(button)
        frame.set_child(row)
        self._rows.append((key, status))
        return frame

    def _refresh_states(self):
        done = {
            "components": os.path.exists(vf.PIPER_BIN),
            "a11y": accessibility_enabled(),
            "shortcuts": bool(self.parent.state.get("shortcuts_installed")),
        }
        for key, status in self._rows:
            status.set_text("✓" if done.get(key) else "•")
            status.set_tooltip_text(
                _("Done") if done.get(key) else _("Not done yet"))
        self._comp_btn.set_label(
            _("Reinstall / repair") if done["components"] else _("Install now"))

    def _on_install_components(self, _btn):
        self._result.set_text(_("Setting up..."))
        self.parent.run_setup_async(on_done=self._refresh_states)

    def _on_enable_a11y(self, _btn):
        ok, msg = enable_accessibility()
        self._result.set_text(msg)
        self._refresh_states()

    def _on_install_shortcuts(self, _btn):
        try:
            ok = _install_shortcuts(self.parent.state)
        except Exception as e:
            log.debug(f"setup-dialog shortcut install failed: {e}")
            ok = False
        if ok:
            self.parent.state["shortcuts_installed"] = True
        vf.save_state(self.parent.state)
        if ok and _cinnamon_reload():
            self._result.set_text(
                _("Shortcuts installed. The desktop was reloaded to "
                  "activate them."))
        elif ok:
            self._result.set_text(
                _("Shortcuts installed. You can change or remove them in "
                  "your system keyboard settings."))
        else:
            self._result.set_text(
                _("Could not install shortcuts on this desktop. Your desktop "
                  "may use a different method — set them manually in its "
                  "keyboard settings."))
        self._refresh_states()


class VoxFoxApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.voxfox.VoxFox",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win        = None
        self.ipc_server = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        # GDK has opened its X display by now; make stray Xlib errors (e.g. a
        # window vanishing mid-query during hover) non-fatal so they can't crash us.
        _install_x_error_handler()
        for name, cb in (("about", self._on_about),
                         ("history", self._on_history),
                         ("first_run", self._on_first_run),
                         ("quit",  self._on_quit)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

    def do_activate(self):
        if not self.win:
            self._apply_css()
            self.win = VoxFoxWindow(self)
            self.ipc_server = vf.IPCServer(self.win)
            self.ipc_server.start()
        self.win.present()
        # Restore the last on-screen position (X11), then re-assert always-on-top
        # after the window is mapped. Both are retried a few times because the
        # window title may not be set at the X level immediately, which would
        # make the wmctrl match miss on a single early attempt.
        for delay in (300, 1000):
            GLib.timeout_add(delay,
                             lambda: (self.win.restore_window_pos(), False)[1])
        for delay in (400, 1200, 2500):
            GLib.timeout_add(delay,
                             lambda: (self.win.set_always_on_top(), False)[1])
        # Shrink the window to its natural content size after it is mapped,
        # overriding any larger geometry the window manager may have remembered.
        for delay in (350, 1100):
            GLib.timeout_add(delay,
                             lambda: (self.win._fit_to_content(), False)[1])
        # Warm up the Piper server in the background so the voice model is
        # already loaded by the time the user first speaks. This eliminates
        # the ~1 s startup delay on the very first utterance.
        GLib.timeout_add(500, self._warmup_piper)
        # First run: when the engine is still missing, guide the user through
        # setup once instead of leaving them to find the menu.
        if not os.path.exists(vf.PIPER_BIN):
            GLib.timeout_add(700, self._maybe_first_run)

    def _maybe_first_run(self):
        if not getattr(self, "_first_run_shown", False) and self.win:
            self._first_run_shown = True
            SetupDialog(self.win).present()
        return False

    def _warmup_piper(self):
        """Start the Piper server in the background (fire-and-forget)."""
        try:
            slot = (self.win.state or {}).get("slot1", {})
            voice = slot.get("voice", "")
            if not voice:
                return False
            speed = float(slot.get("speed", 1.0))
            pitch = float(slot.get("pitch", 0.0))
            pitch_factor = 2.0 ** (pitch / 12.0)
            length_scale = round(pitch_factor / speed, 4)
            model = os.path.join(vf.PIPER_DIR, f"{voice}.onnx")
            if not os.path.isfile(model):
                return False

            def _do_warmup():
                try:
                    vf._piper_server.synth(
                        " ", model, length_scale, 0.1)
                    log.debug("Piper server warmed up")
                except Exception as e:
                    log.debug(f"Piper warmup failed: {e}")

            threading.Thread(target=_do_warmup, daemon=True).start()
        except Exception as e:
            log.debug(f"warmup_piper: {e}")
        return False  # don't repeat the GLib timeout

    def _apply_css(self):
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(ACCENT_CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as e:
            log.debug(f"CSS load failed: {e}")

    def _on_history(self, *_a):
        if not self.win:
            return
        self.hist_win = HistoryWindow(self.win)
        self.hist_win.present()

    def _on_first_run(self, *_a):
        if self.win:
            SetupDialog(self.win).present()

    def _on_about(self, *_a):
        dlg = Gtk.AboutDialog(transient_for=self.win, modal=True)
        dlg.set_program_name(vf.APP_NAME)
        dlg.set_version(APP_VERSION)
        dlg.set_authors(["Daniël Vos"])
        dlg.set_copyright("© 2025 Daniël Vos")
        dlg.set_website(MANUAL_URL)
        dlg.set_website_label(_("Manual — voxfox.nl/manual"))
        dlg.set_license_type(Gtk.License.GPL_3_0)

        commands = [
            ("voxfox --read",           _("Read selected text")),
            ("voxfox --stop",           _("Stop speaking")),
            ("voxfox --pause",          _("Pause / resume")),
            ("voxfox --toggle-slot",    _("Switch language slot")),
            ("voxfox --hover-toggle",   _("Toggle hover reading")),
            ("voxfox --whisper-toggle", _("Dictate (speech to text)")),
            ("voxfox --ocr-select",     _("Read a screen region (OCR)")),
        ]
        shortcuts = [
            ("Super+Z", _("Read selected text")),
            ("Super+X", _("Stop speaking")),
            ("Super+C", _("Switch language slot")),
            ("Super+W", _("Dictation")),
            ("Super+A", _("OCR region select")),
        ]
        cmd_block = "\n".join(f"{cmd}  —  {desc}" for cmd, desc in commands)
        sc_block  = "\n".join(f"{key}  —  {desc}" for key, desc in shortcuts)
        dlg.set_comments(
            _("Screen reader and dictation tool") + "\n\n"
            + _("Default keyboard shortcuts — change them in "
                "Settings → Shortcuts:") + "\n"
            + sc_block + "\n\n"
            + _("Commands you can bind to keyboard shortcuts:") + "\n"
            + cmd_block + "\n\n"
            + _("Chromium / Brave / Chrome:") + "\n"
            + _("Add --force-renderer-accessibility to the browser's desktop "
                "file or launcher to enable hover reading in web pages."))

        # Credits section: selectable text for easy copy-paste.
        dlg.add_credit_section(_("Default shortcuts"),
                               [f"{key}  —  {desc}" for key, desc in shortcuts])
        dlg.add_credit_section(_("Shortcut commands"),
                               [f"{cmd}" for cmd, _desc in commands])
        dlg.add_credit_section(_("Chromium / Brave / Chrome"),
                               ["--force-renderer-accessibility",
                                _("Add this flag to the browser launcher "
                                  "to enable hover reading in web pages.")])

        logo = vf.LOGO_PATH if os.path.exists(vf.LOGO_PATH) else SYSTEM_ICON
        if os.path.exists(logo):
            try:
                dlg.set_logo(Gdk.Texture.new_from_filename(logo))
            except Exception:
                pass
        dlg.present()

    def _on_quit(self, *_a):
        if self.win:
            self.win.on_close()
        else:
            self.quit()


def _build_arg_parser():
    p = argparse.ArgumentParser(prog="voxfox", description=vf.APP_NAME + " (GTK4)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--read",          dest="read",          action="store_true")
    g.add_argument("--stop",          dest="stop",          action="store_true")
    g.add_argument("--pause",         dest="pause",         action="store_true")
    g.add_argument("--toggle-slot",   dest="toggle_slot",   action="store_true")
    g.add_argument("--hover-toggle",  dest="hover_toggle",  action="store_true")
    g.add_argument("--whisper-toggle", dest="whisper_toggle", action="store_true")
    g.add_argument("--ocr-select",    dest="ocr_select",    action="store_true")
    g.add_argument("--ocr",           dest="ocr",           metavar="FILE")
    g.add_argument("--status",        dest="status",        action="store_true")
    g.add_argument("--quit",          dest="quit",          action="store_true")
    g.add_argument("--setup",         dest="setup",         action="store_true",
                   help="Download Piper engine + default voices + Whisper, then exit")
    g.add_argument("--install-shortcuts", dest="install_shortcuts", action="store_true",
                   help="(Re)install the Super+Z/X/C/W/A desktop shortcuts, then exit")
    p.add_argument("--verbose", action="store_true", help="Debug logging")
    return p


_X_ERROR_HANDLER_REF = None


def _install_x_error_handler():
    """Make Xlib errors non-fatal. By default libX11 prints the error and
    calls exit(), so a single BadWindow (a window that vanished while it was
    being queried) takes the whole app down. We install a handler that swallows
    such transient errors instead. Installed in do_startup, after GDK has opened
    its display, so this overrides GDK's default (last XSetErrorHandler wins)."""
    global _X_ERROR_HANDLER_REF
    try:
        import ctypes
        x11 = ctypes.CDLL("libX11.so.6")
        proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _handler(_display, _event):
            return 0  # ignore; do not abort the process

        _X_ERROR_HANDLER_REF = proto(_handler)  # keep a ref so it is not GC'd
        x11.XSetErrorHandler(_X_ERROR_HANDLER_REF)
        log.debug("Installed non-fatal X error handler")
    except Exception as e:
        log.debug(f"could not install X error handler: {e}")


# VoxFox's default global shortcuts, in a stable order. The first element is
# an internal action key (used to track which desktop slot we own); it is NOT
# the slot name written to the desktop. Fields: key, label, command, binding.
_SHORTCUT_ACTIONS = [
    ("read",    "VoxFox: read",         "voxfox --read",           "<Super>z"),
    ("stop",    "VoxFox: stop",         "voxfox --stop",           "<Super>x"),
    ("voice",   "VoxFox: switch voice", "voxfox --toggle-slot",    "<Super>c"),
    ("whisper", "VoxFox: dictation",    "voxfox --whisper-toggle", "<Super>w"),
    ("ocr",     "VoxFox: OCR select",   "voxfox --ocr-select",     "<Super>a"),
]

# Short, translatable names for the five actions, shown in the settings
# Shortcuts tab. Keyed by the action id from _SHORTCUT_ACTIONS.
_SHORTCUT_LABELS = {
    "read":    "Read",
    "stop":    "Stop",
    "voice":   "Switch language",
    "whisper": "Dictate",
    "ocr":     "OCR select",
}


def _binding_for(state, key, default):
    """The effective binding for an action: the user's chosen key from
    state["shortcut_bindings"], or the built-in default when unset."""
    chosen = (state.get("shortcut_bindings") or {}).get(key) if state else None
    return chosen or default


def _binding_display(binding):
    """Human-readable label for an accelerator string ('<Super>z' -> 'Super+Z').
    Falls back to the raw string if it can't be parsed."""
    if not binding:
        return ""
    try:
        ok, keyval, mods = Gtk.accelerator_parse(binding)
        if ok and keyval:
            return Gtk.accelerator_get_label(keyval, mods)
    except Exception:
        pass
    return binding


def _binding_to_lxqt(binding):
    """Convert an accelerator string to LXQt's section-name format:
    '<Super>z' -> 'Meta%2BZ', '<Control><Alt>x' -> 'Control%2BAlt%2BX'.
    Returns None if the binding can't be parsed."""
    try:
        ok, keyval, mods = Gtk.accelerator_parse(binding)
    except Exception:
        ok = False
    if not ok or not keyval:
        return None
    parts = []
    if mods & Gdk.ModifierType.SUPER_MASK:
        parts.append("Meta")
    if mods & Gdk.ModifierType.CONTROL_MASK:
        parts.append("Control")
    if mods & Gdk.ModifierType.ALT_MASK:
        parts.append("Alt")
    if mods & Gdk.ModifierType.SHIFT_MASK:
        parts.append("Shift")
    name = Gdk.keyval_name(Gdk.keyval_to_upper(keyval)) or ""
    if not name:
        return None
    parts.append(name)
    return "%2B".join(parts)

# Non-numeric entry names used by VoxFox <= 2.0.7. These broke Cinnamon's
# "Add custom shortcut" button: its settings panel computes the next free
# slot by walking a numeric customN sequence, and chokes on names like
# "voxfox-read". On install we migrate any of these away to numeric slots.
_LEGACY_SHORTCUT_NAMES = [
    "voxfox-read", "voxfox-stop", "voxfox-voice", "voxfox-whisper", "voxfox-ocr",
]


def _next_custom_slots(taken, count):
    """Return `count` fresh 'customN' slot names not already in `taken`,
    lowest indices first, so the desktop's custom-list stays a compact
    numeric sequence (which is what keeps the "Add shortcut" button working)."""
    taken = set(taken)
    out, n = [], 0
    while len(out) < count:
        name = f"custom{n}"
        if name not in taken:
            out.append(name)
            taken.add(name)
        n += 1
    return out


def _slot_sort_key(name):
    """Sort customN names numerically; anything else sorts last, by string."""
    if name.startswith("custom") and name[6:].isdigit():
        return (0, int(name[6:]))
    return (1, name)


def _install_cinnamon_shortcuts(src, state):
    """Cinnamon: custom-list holds slot NAMES; each is a relocatable schema
    under .../custom-keybindings/<name>/ with binding as a LIST. We allocate
    numeric customN slots (never literal names), migrate any legacy
    voxfox-* entries away, and remember our slots in state."""
    if src.lookup("org.cinnamon.desktop.keybindings", True) is None:
        return False
    SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
    base = Gio.Settings.new("org.cinnamon.desktop.keybindings")
    names = list(base.get_strv("custom-list"))

    def path_for(slot):
        return f"/org/cinnamon/desktop/keybindings/custom-keybindings/{slot}/"

    def slot_command(slot):
        try:
            return Gio.Settings.new_with_path(SCHEMA, path_for(slot)).get_string("command")
        except Exception:
            return ""

    # 1. Migrate: drop legacy non-numeric voxfox-* names and clear their values.
    for legacy in _LEGACY_SHORTCUT_NAMES:
        if legacy in names:
            names.remove(legacy)
        try:
            s = Gio.Settings.new_with_path(SCHEMA, path_for(legacy))
            s.reset("name"); s.reset("command"); s.reset("binding")
        except Exception as e:
            log.debug(f"clear legacy {legacy}: {e}")

    # 2. Remove every slot that currently holds a VoxFox command (old binding,
    #    duplicate, or a previous install), then create fresh slots below.
    #    Recreating the keybindings rather than overwriting a slot's binding in
    #    place is what makes cinnamon-settings-daemon re-grab the new keys — an
    #    in-place binding change is not reliably re-grabbed, which left changed
    #    shortcuts dead.
    for slot in list(names):
        if slot_command(slot).startswith("voxfox"):
            try:
                s = Gio.Settings.new_with_path(SCHEMA, path_for(slot))
                s.reset("name"); s.reset("command"); s.reset("binding")
            except Exception as e:
                log.debug(f"clear voxfox slot {slot}: {e}")
            names.remove(slot)

    # 2.5 Allocate fresh numeric slots for the five actions.
    name_set = set(names)
    keys = [a[0] for a in _SHORTCUT_ACTIONS]
    fresh = _next_custom_slots(name_set, len(keys))
    assigned = dict(zip(keys, fresh))

    # 3. Write each slot and ensure it is listed; keep the list numeric & sorted.
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        slot = assigned[key]
        s = Gio.Settings.new_with_path(SCHEMA, path_for(slot))
        s.set_string("name", label)
        s.set_string("command", cmd)
        s.set_strv("binding", [_binding_for(state, key, binding)])
        if slot not in name_set:
            names.append(slot)
            name_set.add(slot)
    # Flush the slot data to dconf *before* changing custom-list: the daemon
    # re-reads the listed slots the moment custom-list changes, so the binding
    # values must already be committed or it grabs nothing (and only a restart
    # fixes it).
    Gio.Settings.sync()
    names.sort(key=_slot_sort_key)
    base.set_strv("custom-list", names)
    Gio.Settings.sync()   # then flush the list itself
    state["cinnamon_shortcut_slots"] = assigned
    log.info("Installed Cinnamon keyboard shortcuts")
    return True


def _install_gnome_shortcuts(src, state):
    """GNOME: custom-keybindings holds entry PATHS; binding is a STRING. Same
    numeric-slot approach as Cinnamon so gnome-control-center's add button
    keeps working and upgraders' legacy voxfox-* paths get migrated."""
    if src.lookup("org.gnome.settings-daemon.plugins.media-keys", True) is None:
        return False
    SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
    base = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
    paths = list(base.get_strv("custom-keybindings"))

    def slot_of(p):
        return p[len(PREFIX):].strip("/") if p.startswith(PREFIX) else p.strip("/")

    def cmd_at(p):
        try:
            return Gio.Settings.new_with_path(SCHEMA, p).get_string("command")
        except Exception:
            return ""

    # 1. Migrate legacy voxfox-* paths.
    for legacy in _LEGACY_SHORTCUT_NAMES:
        lp = f"{PREFIX}{legacy}/"
        if lp in paths:
            paths.remove(lp)
        try:
            s = Gio.Settings.new_with_path(SCHEMA, lp)
            s.reset("name"); s.reset("command"); s.reset("binding")
        except Exception as e:
            log.debug(f"clear legacy gnome {legacy}: {e}")

    # 2. Remove every slot holding a VoxFox command (old binding, duplicate, or
    #    previous install), then create fresh slots below — recreating rather
    #    than overwriting in place is what makes the daemon re-grab the new keys.
    for p in list(paths):
        if cmd_at(p).startswith("voxfox"):
            try:
                s = Gio.Settings.new_with_path(SCHEMA, p)
                s.reset("name"); s.reset("command"); s.reset("binding")
            except Exception as e:
                log.debug(f"clear voxfox slot {slot_of(p)}: {e}")
            paths.remove(p)

    # 2.5 Allocate fresh numeric slots for the five actions.
    slot_set = {slot_of(p) for p in paths}
    keys = [a[0] for a in _SHORTCUT_ACTIONS]
    fresh = _next_custom_slots(slot_set, len(keys))
    assigned = dict(zip(keys, fresh))

    # 3. Write and list.
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        slot = assigned[key]
        p = f"{PREFIX}{slot}/"
        s = Gio.Settings.new_with_path(SCHEMA, p)
        s.set_string("name", label)
        s.set_string("command", cmd)
        s.set_string("binding", _binding_for(state, key, binding))
        if p not in paths:
            paths.append(p)
    Gio.Settings.sync()   # flush slot data before changing the list (see Cinnamon)
    paths.sort(key=lambda p: _slot_sort_key(slot_of(p)))
    base.set_strv("custom-keybindings", paths)
    Gio.Settings.sync()   # then flush the list itself
    state["gnome_shortcut_slots"] = assigned
    log.info("Installed GNOME keyboard shortcuts")
    return True


def _install_lxqt_shortcuts(src, state):
    """LXQt: global shortcuts live in a Qt-INI file read by lxqt-globalkeysd
    (~/.config/lxqt/globalkeyshortcuts.conf). A command shortcut is a section
    named '<KeySeq>.<N>', with '+' encoded as %2B and N a unique index, holding
    Comment / Enabled / Exec — where Exec is comma-separated ('voxfox, --read')
    and the Super key is spelled 'Meta'. On each install we drop our own old
    sections (matched by Exec) and write the current five, preserving any
    sections the user added themselves, then let the daemon's file-watcher
    reload. This makes changing a shortcut replace its old key. No-op outside
    LXQt. `src` is unused (LXQt doesn't use GSettings); kept for a uniform
    installer signature."""
    import re
    import configparser

    conf = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "lxqt", "globalkeyshortcuts.conf")
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    # The dispatcher runs every installer on every desktop, so only act when
    # this really is LXQt (or its config already exists).
    if "lxqt" not in desktop and not os.path.exists(conf):
        return False

    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # Qt keys are case-sensitive (Comment, Exec, path)

    our_cmds = {cmd for _k, _l, cmd, _b in _SHORTCUT_ACTIONS}
    max_idx = 0
    if os.path.exists(conf):
        try:
            cp.read(conf, encoding="utf-8")
        except Exception as e:
            log.debug(f"lxqt shortcuts: cannot parse conf: {e}")
            return False
        # Remove any section that runs one of our commands (old VoxFox bindings),
        # so a changed shortcut replaces its old key instead of piling up. Other
        # sections (the user's own shortcuts) are preserved.
        for sect in list(cp.sections()):
            ex = cp[sect].get("Exec", "")
            norm = " ".join(p.strip() for p in ex.split(",")) if ex else ""
            if norm in our_cmds:
                cp.remove_section(sect)
            else:
                m = re.search(r"\.(\d+)$", sect)
                if m:
                    max_idx = max(max_idx, int(m.group(1)))

    if not cp.has_section("General"):
        cp.add_section("General")
        cp["General"]["MultipleActionsBehaviour"] = "first"

    idx = max_idx
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        combo = _binding_to_lxqt(_binding_for(state, key, binding))
        if not combo:
            log.debug(f"LXQt: cannot convert binding for {key}, skipping")
            continue
        idx += 1
        sect = f"{combo}.{idx}"
        cp.add_section(sect)
        cp[sect]["Comment"] = label
        cp[sect]["Enabled"] = "true"
        cp[sect]["Exec"] = ", ".join(cmd.split())     # 'voxfox, --read'

    try:
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w", encoding="utf-8") as f:
            cp.write(f, space_around_delimiters=False)
    except Exception as e:
        log.debug(f"lxqt shortcuts write failed: {e}")
        return False
    log.info("Installed LXQt keyboard shortcuts")
    return True


def _install_xfce_shortcuts(state):
    """Install VoxFox's global shortcuts on XFCE via xfconf-query.

    XFCE stores custom keyboard shortcuts in the xfce4-keyboard-shortcuts
    channel under /commands/custom/<binding>. xfconf-query is the only stable
    interface (the XML file location varies between XFCE versions and is not
    meant for direct editing). The Super key maps to <Super> in XFCE bindings.

    The `state` parameter is unused (no numeric-slot tracking needed here);
    kept for a uniform installer signature. On each install we first remove any
    existing custom binding that runs one of our commands (whatever key it is
    on), then write the current five — so changing a shortcut replaces the old
    key instead of leaving it bound. No-op when not on XFCE or xfconf-query is
    unavailable."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    if "xfce" not in desktop:
        return False
    if not vf._have("xfconf-query"):
        log.debug("xfconf-query not found; skipping XFCE shortcut install")
        return False

    CHANNEL = "xfce4-keyboard-shortcuts"
    our_cmds = {cmd for _k, _l, cmd, _b in _SHORTCUT_ACTIONS}
    # List existing custom command properties.
    try:
        out = subprocess.run(
            ["xfconf-query", "-c", CHANNEL, "-l"],
            capture_output=True, text=True, timeout=5)
        props = [p.strip() for p in out.stdout.splitlines()
                 if p.strip().startswith("/commands/custom/")]
    except Exception as e:
        log.debug(f"xfconf-query list failed: {e}")
        return False

    # Remove any existing binding that runs one of our commands, so a changed
    # shortcut doesn't leave its previous key working.
    for prop in props:
        try:
            r = subprocess.run(
                ["xfconf-query", "-c", CHANNEL, "-p", prop],
                capture_output=True, text=True, timeout=5)
            if r.stdout.strip() in our_cmds:
                subprocess.run(
                    ["xfconf-query", "-c", CHANNEL, "-p", prop, "-r"],
                    capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    # Write the current five.
    written = 0
    for key, _label, cmd, binding in _SHORTCUT_ACTIONS:
        # XFCE uses the same accelerator format as the stored binding.
        prop = f"/commands/custom/{_binding_for(state, key, binding)}"
        try:
            subprocess.run(
                ["xfconf-query", "-c", CHANNEL, "-p", prop,
                 "--create", "-t", "string", "-s", cmd],
                capture_output=True, text=True, timeout=5, check=True)
            written += 1
        except Exception as e:
            log.debug(f"xfconf-query set {prop} failed: {e}")

    log.info(f"Installed {written} XFCE keyboard shortcuts")
    return True


def _cinnamon_reload():
    """Soft-restart the Cinnamon shell (windows are preserved) so it re-grabs
    freshly-installed custom keybindings. Cinnamon rebuilds its keybindings only
    on certain triggers that a plain settings write doesn't hit, so without this
    an install needs a manual Ctrl+Alt+Esc. Uses the same DBus call as Alt+F2 r.
    No-op off Cinnamon or if the call fails."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    if "cinnamon" not in desktop:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.Cinnamon", "/org/Cinnamon", "org.Cinnamon",
                      "RestartCinnamon", GLib.Variant("(b)", (False,)),
                      None, Gio.DBusCallFlags.NONE, 4000, None)
        log.info("Requested Cinnamon reload to activate shortcuts")
        return True
    except Exception as e:
        log.debug(f"cinnamon reload failed: {e}")
        return False


def _install_shortcuts(state):
    """Register VoxFox's global keyboard shortcuts with the desktop:

        Super+Z  read          (voxfox --read)
        Super+X  stop          (voxfox --stop)
        Super+C  switch voice  (voxfox --toggle-slot)
        Super+W  dictation     (voxfox --whisper-toggle)
        Super+A  OCR select    (voxfox --ocr-select)

    On GNOME and Cinnamon these are written as custom keybindings via GSettings
    (numeric customN slots tracked in `state`, legacy voxfox-* names migrated,
    idempotent). On LXQt they are appended to globalkeyshortcuts.conf as Meta+
    command entries. On XFCE they are written via xfconf-query into the
    xfce4-keyboard-shortcuts channel. Writing for several desktops is harmless;
    each installer is a no-op where its desktop isn't present. Mutates `state`
    (the caller persists it) and returns True if at least one desktop accepted
    them. Users can change or remove them in the system keyboard settings."""
    installed = False
    # LXQt and XFCE use config files / CLI tools, not GSettings; try them
    # independently (a pure LXQt/XFCE box may have no relevant GSettings schemas).
    try:
        if _install_lxqt_shortcuts(None, state):
            installed = True
    except Exception as e:
        log.debug(f"_install_lxqt_shortcuts failed: {e}")
    try:
        if _install_xfce_shortcuts(state):
            installed = True
    except Exception as e:
        log.debug(f"_install_xfce_shortcuts failed: {e}")
    try:
        src = Gio.SettingsSchemaSource.get_default()
        if src is not None:
            for fn in (_install_cinnamon_shortcuts, _install_gnome_shortcuts):
                try:
                    if fn(src, state):
                        installed = True
                except Exception as e:
                    log.debug(f"{fn.__name__} failed: {e}")
    except Exception as e:
        log.debug(f"shortcut install skipped: {e}")
    return installed


def _enable_accessibility():
    """Coax the desktop accessibility stack on at startup, the way a screen
    reader (Orca) does, so GTK apps and browsers build and keep their AT-SPI
    trees. Without this a browser may not populate its tree until a recognised
    assistive technology shows up, leaving hover with nothing to read.
    Best-effort: any failure is ignored."""
    try:
        from gi.repository import Gio
        src = Gio.SettingsSchemaSource.get_default()
        if src is None:
            return
        for schema in ("org.gnome.desktop.interface",
                       "org.cinnamon.desktop.interface",
                       "org.mate.interface"):
            try:
                sch = src.lookup(schema, True)
                if sch is None or not sch.has_key("toolkit-accessibility"):
                    continue
                s = Gio.Settings.new(schema)
                if not s.get_boolean("toolkit-accessibility"):
                    s.set_boolean("toolkit-accessibility", True)
                    log.info(f"Enabled toolkit-accessibility via {schema}")
            except Exception as e:
                log.debug(f"a11y enable via {schema} failed: {e}")
    except Exception as e:
        log.debug(f"accessibility warm-up skipped: {e}")


def main():
    # Force the program name so GTK4 under X11 stamps the window with
    # WM_CLASS "org.voxfox.VoxFox" instead of "python3". Without this the
    # panel/taskbar cannot match the running window to the .desktop launcher,
    # so it shows up as a separate, generic-icon window. Must run before any
    # GTK/GDK initialisation. StartupWMClass in voxfox.desktop must match this.
    GLib.set_prgname("org.voxfox.VoxFox")

    # Turn the accessibility stack on early (like a screen reader) so browsers
    # and GTK apps build their AT-SPI trees that hover-to-read depends on.
    _enable_accessibility()

    # Create XDG dirs and migrate any 1.x / Tk-era data forward (non-destructive).
    vf.init_storage()

    # Prefer system-installed locales when no per-user set exists.
    if not os.path.isdir(vf.locales_dir()) and os.path.isdir(SYSTEM_LOCALES):
        vf.set_locales_dir(SYSTEM_LOCALES)

    # Populate the translation tables, THEN switch the UI to slot 1's language.
    # (Without load_translations() the tables stay empty and the UI is stuck
    # on English regardless of the slot 1 setting.)
    vf.load_translations()
    try:
        st = vf.load_state()
        apply_ui_language(st["slot1"].get("lang", ""))
        vf.set_pronunciations(st.get("pronunciations", {}))
        vf.set_merge_lines(st.get("merge_lines", True))
    except Exception:
        pass

    args = _build_arg_parser().parse_args()
    if args.verbose:
        vf.log.setLevel(logging.DEBUG)

    # Headless component setup.
    if args.setup:
        ok, msg = run_setup(progress=lambda m: print(f"  {m}"))
        print("Setup complete." if ok else f"Setup failed: {msg}")
        return

    # Manual (re)install of the desktop keyboard shortcuts.
    if args.install_shortcuts:
        st = vf.load_state()
        ok = _install_shortcuts(st)
        if ok:
            st["shortcuts_installed"] = True
        vf.save_state(st)
        if ok:
            _cinnamon_reload()
        print("Shortcuts installed." if ok
              else "Could not install shortcuts on this desktop "
                   "(no supported method found).")
        return

    # Action flags → forward to the running instance and exit (no GUI).
    if any([args.read, args.stop, args.pause, args.toggle_slot,
            args.hover_toggle, args.whisper_toggle, args.ocr_select,
            args.ocr, args.status, args.quit]):
        vf.run_cli(args)
        return

    if vf.is_instance_running():
        vf.send_command("ping")
        print("VoxFox is already running.")
        return
    if not vf.acquire_singleton_lock():
        print("VoxFox is already running.")
        return

    # Shortcuts are no longer auto-installed on first start: some desktops ship
    # their own bindings for these keys, and silently overwriting them is rude.
    # The user picks keys and installs them from Settings → Shortcuts (or via
    # `voxfox --install-shortcuts`).

    # If the AT-SPI accessibility bus can't actually be reached (switched off,
    # missing, or a stale root-owned socket such as /root/.cache/at-spi/bus_0),
    # tell GTK NOT to load its accessibility bridge. Otherwise libatspi's dbind
    # layer responds to the failed connection with a hard abort() — a core dump
    # at startup — which no Python try/except can catch. Hover reading is guarded
    # separately (it reports the bus as unavailable instead of crashing). When
    # the bus works normally this branch is skipped and VoxFox stays accessible.
    if not vf.a11y_bus_reachable():
        os.environ.setdefault("GTK_A11Y", "none")
        os.environ.setdefault("NO_AT_BRIDGE", "1")
        log.debug("AT-SPI bus unreachable — disabled GTK a11y bridge for "
                  "this process to avoid a libatspi abort.")

    VoxFoxApplication().run(None)


if __name__ == "__main__":
    main()

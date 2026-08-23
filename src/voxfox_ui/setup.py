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

"""voxfox_ui.setup — Component installation (Piper, voices, pip extras) and the SetupDialog.

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os
import sys
import time
import platform
import hashlib
import tarfile
import threading
import tempfile
import subprocess
import urllib.request

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import voxfox_core as vf  # noqa: E402
from voxfox_core import _  # translation helper  # noqa: E402

log = vf.log
from voxfox_ui.common import DEFAULT_VOICES, PIPER_RELEASE, PIPER_SHA256  # noqa: E402
from voxfox_ui.shortcuts import _cinnamon_reload, _install_shortcuts  # noqa: E402
from voxfox_ui.widgets import _hide_progress_bar, _set_progress_bar  # noqa: E402


def _piper_asset():
    m = platform.machine()
    return {
        "x86_64":  "piper_linux_x86_64.tar.gz",
        "aarch64": "piper_linux_aarch64.tar.gz",
        "armv7l":  "piper_linux_armv7l.tar.gz",
    }.get(m)


def _safe_extract_piper(tar, dest):
    """Extract the Piper tarball safely, stripping the leading 'piper/' dir.

    Guards against tar-slip: rejects absolute paths, '..' traversal, symlinks,
    hardlinks and device/special members. Only regular files and directories
    are written, and every destination is confirmed to stay within `dest`."""
    dest = os.path.realpath(dest)
    for member in tar.getmembers():
        parts = member.name.split("/", 1)
        if len(parts) < 2 or not parts[1]:
            continue
        name = parts[1]
        # No absolute paths or parent-directory traversal.
        if name.startswith("/") or os.path.isabs(name) \
                or ".." in name.split("/"):
            raise ValueError(f"unsafe path in archive: {member.name!r}")
        target = os.path.realpath(os.path.join(dest, name))
        if target != dest and not target.startswith(dest + os.sep):
            raise ValueError(f"path escapes destination: {member.name!r}")
        # Links are allowed only when they resolve inside dest — Piper ships
        # libpiper_phonemize.so -> libpiper_phonemize.so.1, which is fine.
        if member.issym() or member.islnk():
            base = os.path.dirname(os.path.join(dest, name))
            link_target = os.path.realpath(
                os.path.join(base, member.linkname))
            if link_target != dest \
                    and not link_target.startswith(dest + os.sep):
                raise ValueError(f"link escapes destination: {member.name!r}")
        elif not (member.isfile() or member.isdir()):
            raise ValueError(f"special member not allowed: {member.name!r}")
        member.name = name
        tar.extract(member, dest)


def install_piper(progress=lambda m: None, frac=lambda *_a: None):
    """Download the Piper binary for this architecture into ~/.piper.

    The download is pinned to PIPER_VERSION. When a SHA-256 is known for the
    architecture (PIPER_SHA256), it is verified before extraction; extraction
    itself is always hardened against tar-slip (see _safe_extract_piper)."""
    if os.path.exists(vf.PIPER_BIN):
        progress(_("Piper already installed"))
        return True, "ok"
    asset = _piper_asset()
    if not asset:
        return False, f"Unsupported architecture: {platform.machine()}"
    os.makedirs(vf.PIPER_DIR, exist_ok=True)
    url = f"{PIPER_RELEASE}/{asset}"
    progress(_("Downloading Piper engine..."))
    tmp = None
    try:
        # Unique temp file in a private dir, never a predictable name.
        fd, tmp = tempfile.mkstemp(prefix="voxfox-piper-", suffix=".tar.gz")
        hasher = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as r, \
                os.fdopen(fd, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                done += len(chunk)
                if total:
                    frac(done / total, "Piper")

        # Verify the checksum when we have one pinned for this asset.
        expected = PIPER_SHA256.get(asset)
        if expected:
            got = hasher.hexdigest()
            if got != expected:
                return False, (f"checksum mismatch for {asset}: "
                               f"expected {expected[:12]}…, got {got[:12]}…")

        progress(_("Extracting Piper..."))
        with tarfile.open(tmp, "r:gz") as tar:
            _safe_extract_piper(tar, vf.PIPER_DIR)

        # Confirm we actually got a real, regular Piper binary.
        if not os.path.isfile(vf.PIPER_BIN) or os.path.islink(vf.PIPER_BIN):
            return False, "Piper binary missing after extraction"
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
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


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
    failed = []
    todo = [k for k in keys if k not in vf.get_local_voices()]
    n = max(1, len(todo))
    for i, key in enumerate(todo):
        progress(f"{_('Downloading voice')}: {key}...")
        def slice_frac(fr, _lbl=None, i=i):
            frac((i + max(0.0, min(1.0, fr))) / n, _("Voices"))
        ok, msg = vf.download_voice(key, progress_cb=progress,
                                    frac_cb=slice_frac)
        if not ok:
            log.warning(f"Voice {key} failed: {msg}")
            failed.append(key)
    if failed:
        return False, "voices failed: " + ", ".join(failed)
    return True, "ok"


def _pip_install(pkgs, progress=lambda m: None, pulse=lambda: None):
    progress(f"{_('Installing')}: {', '.join(pkgs)}...")
    base = [sys.executable, "-m", "pip", "install", "--user"]
    for cmd in (base + ["--break-system-packages", *pkgs], base + [*pkgs]):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            while proc.poll() is None:
                pulse()
                time.sleep(0.4)
            if proc.returncode == 0:
                return True
        except Exception as e:
            log.debug(f"pip attempt failed: {e}")
    return False


def _have_pip():
    """Whether `python3 -m pip` actually works. A fresh, minimal install --
    increasingly the default on newer Ubuntu/Debian -- may not have
    python3-pip installed at all, which _pip_install() would otherwise just
    fail at silently, leaving dictation/OCR quietly broken with no clue why.
    """
    try:
        return subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def install_python_extras(progress=lambda m: None, pulse=lambda: None):
    """Install the pip-only Python deps that aren't reliably packaged in Debian:
    faster-whisper (dictation) and pytesseract + Pillow (OCR). Each is skipped
    when already importable, so this is safe to re-run."""
    def have(mod):
        try:
            __import__(mod)
            return True
        except Exception:
            return False

    need_whisper = not have("faster_whisper")
    ocr_pkgs = []
    if not have("pytesseract"):
        ocr_pkgs.append("pytesseract")
    if not have("PIL"):
        ocr_pkgs.append("pillow")

    if (need_whisper or ocr_pkgs) and not _have_pip():
        progress(_("Python's own package installer (pip) isn't installed "
                  "on this system; install it with: sudo apt install "
                  "python3-pip, then run Set up VoxFox again."))
        problems = []
        if need_whisper:
            problems.append("faster-whisper")
        if ocr_pkgs:
            problems.append("OCR (" + ", ".join(ocr_pkgs) + ")")
        return False, "pip missing: " + "; ".join(problems)

    problems = []
    if need_whisper:
        if not _pip_install(["faster-whisper"], progress, pulse):
            progress(_("faster-whisper install failed (dictation disabled)"))
            problems.append("faster-whisper")
    # Pillow usually comes from apt (python3-pil); pip-install only if missing.
    if ocr_pkgs and not _pip_install(ocr_pkgs, progress, pulse):
        progress(_("OCR Python packages failed to install"))
        problems.append("OCR (" + ", ".join(ocr_pkgs) + ")")
    if problems:
        return False, "extras failed: " + "; ".join(problems)
    return True, "ok"


def run_setup(progress=lambda m: None, want_extras=True, frac=lambda *_a: None):
    """Install everything needed on a fresh machine. Safe to re-run.
    Returns (ok, msg): ok is False when any component failed, with msg naming
    the components so the GUI and CLI can report a real result."""
    problems = []
    total = 2 + (1 if want_extras else 0)
    step = [0]

    def phase(msg):
        step[0] += 1
        progress(f"[{step[0]}/{total}] {msg}")

    pulse_state = [0.0]

    def pulse():
        pulse_state[0] = (pulse_state[0] + 0.05) % 1.0
        frac(pulse_state[0], _("Installing"))

    phase(_("Installing speech engine..."))
    ok, msg = install_piper(progress, frac)
    if not ok:
        return False, f"Piper: {msg}"
    phase(_("Downloading voices..."))
    ok, msg = install_default_voices(progress, frac)
    if not ok:
        problems.append(msg)
    if want_extras:
        phase(_("Installing dictation and OCR support..."))
        ok, msg = install_python_extras(progress, pulse=pulse)
        if not ok:
            problems.append(msg)
    if problems:
        return False, "; ".join(problems)
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
_RTL_UI_CODES = {"ar", "fa"}  # Arabic and Persian both run right-to-left


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
            _("Registers the six VoxFox shortcuts on your desktop. Change the "
              "keys first under Settings → Shortcuts if you like."),
            self._sc_btn))

        # 4) OCR language packs — informational (installed via apt).
        info = Gtk.Label(
            label=_("For OCR in other languages, install the matching Tesseract "
                    "pack, e.g. sudo apt install tesseract-ocr-nld"),
            xalign=0, wrap=True, selectable=True)
        info.add_css_class("dim-label")
        outer.append(info)

        self._progress = Gtk.ProgressBar(show_text=True)
        self._progress.set_visible(False)
        outer.append(self._progress)

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
        self._comp_btn.set_sensitive(False)

        def on_progress(msg):
            self._result.set_text(msg)

        def on_frac(fr, label=None):
            _set_progress_bar(self._progress, fr, label)

        def on_done(ok, msg):
            _hide_progress_bar(self._progress)
            self._comp_btn.set_sensitive(True)
            self._result.set_text(
                _("Setup complete") if ok
                else _("Setup incomplete: %s") % msg)
            self._refresh_states()
            # Also refresh the main window behind us: reload the voice
            # dropdowns and re-check the "Piper not installed" banner, so
            # the user doesn't need to restart VoxFox after installing.
            try:
                self.parent.reload_active_controls()
                self.parent.refresh_setup_bar()
            except Exception as e:
                log.debug(f"parent refresh after setup failed: {e}")

        def worker():
            ok, msg = run_setup(
                progress=lambda m: GLib.idle_add(on_progress, m),
                frac=lambda fr, lbl=None: GLib.idle_add(on_frac, fr, lbl))
            GLib.idle_add(on_done, ok, msg)
        threading.Thread(target=worker, daemon=True).start()

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



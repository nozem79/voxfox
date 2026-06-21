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


"""voxfox_core.a11y — Desktop integration: AT-SPI hover-to-read, selection, typing/paste."""

import subprocess, threading, time
from .common import HOVER_DELAY, HOVER_POLL, IS_WAYLAND, MIN_MOVE_PX, _have, log
from .common import _ as tr
from .stt import WHISPER_TYPE_LIMIT
from .tts import speak, stop_speaking


# Background daemons — skip entirely in AT-SPI traversal
_DAEMON_PREFIXES = (
    "gsd-", "ibus-", "dbus-", "at-spi", "gnome-session", "xdg-",
    "evolution-", "tracker-", "goa-", "colord", "upowerd",
    "packagekit", "polkit", "gnome-keyring",
    "mutter-", "tracker3-", "csd-", "cinnamon-session",  # newer GNOME, Cinnamon
    "kded", "kactivitymanagerd", "krunner",              # KDE
)
_DAEMON_NAMES = {
    "gnome-shell", "gnome-panel", "kwin", "plasmashell",
    "xfce4-session", "xfwm4", "xfdesktop", "xfce4-panel",
    "at-spi-bus-launcher", "at-spi2-registryd",
    "cinnamon", "cinnamon-launcher", "muffin", "nemo-desktop",
    "kwin_x11", "kwin_wayland",
}

# Populated once after first successful pyatspi import
_CONTAINER_ROLES = None
# Interactive roles -> English control word (run through tr()). Used as a
# last-resort label for nameless icon-only controls so hover never goes silent.
_INTERACTIVE_ROLES = None


def _init_roles():
    global _CONTAINER_ROLES, _INTERACTIVE_ROLES
    if _CONTAINER_ROLES is not None:
        return
    try:
        import pyatspi
        _CONTAINER_ROLES = {
            pyatspi.ROLE_APPLICATION,
            pyatspi.ROLE_DESKTOP_FRAME,
            pyatspi.ROLE_FRAME,
            pyatspi.ROLE_WINDOW,
            pyatspi.ROLE_PANEL,
            pyatspi.ROLE_FILLER,
            pyatspi.ROLE_SEPARATOR,
            pyatspi.ROLE_SCROLL_BAR,
            pyatspi.ROLE_SCROLL_PANE,
            pyatspi.ROLE_VIEWPORT,
            pyatspi.ROLE_SPLIT_PANE,
            pyatspi.ROLE_ROOT_PANE,
            pyatspi.ROLE_GLASS_PANE,
            pyatspi.ROLE_LAYERED_PANE,
            pyatspi.ROLE_DRAWING_AREA,
            pyatspi.ROLE_DESKTOP_ICON,
            pyatspi.ROLE_DOCUMENT_WEB,
            pyatspi.ROLE_INTERNAL_FRAME,
            pyatspi.ROLE_GROUPING,
        }
        _INTERACTIVE_ROLES = {}
        for const, word in (
            ("ROLE_PUSH_BUTTON",     "button"),
            ("ROLE_TOGGLE_BUTTON",   "button"),
            ("ROLE_CHECK_BOX",       "checkbox"),
            ("ROLE_CHECK_MENU_ITEM", "checkbox"),
            ("ROLE_RADIO_BUTTON",    "radio button"),
            ("ROLE_RADIO_MENU_ITEM", "radio button"),
            ("ROLE_MENU_ITEM",       "menu item"),
            ("ROLE_COMBO_BOX",       "combo box"),
            ("ROLE_SLIDER",          "slider"),
            ("ROLE_SPIN_BUTTON",     "spin button"),
            ("ROLE_PAGE_TAB",        "tab"),
            ("ROLE_LINK",            "link"),
        ):
            r = getattr(pyatspi, const, None)
            if r is not None:
                _INTERACTIVE_ROLES[r] = word
    except Exception:
        _CONTAINER_ROLES = set()
        _INTERACTIVE_ROLES = {}


# ── Text selection (primary clipboard on X11, regular clipboard on Wayland) ──
def get_selection():
    """Read the currently selected text. Tries primary first (X11 + some Wayland
    compositors), then regular clipboard. Empty string when nothing usable."""
    # X11 / XWayland: primary selection is set automatically when you select text.
    if _have("xclip"):
        try:
            r = subprocess.run(["xclip", "-selection", "primary", "-out"],
                               capture_output=True, text=True, timeout=1.0)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    # Wayland: many compositors support primary via wl-paste --primary.
    if _have("wl-paste"):
        for args in (["wl-paste", "--primary", "--no-newline"],
                     ["wl-paste", "--no-newline"]):
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=1.0)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except Exception:
                continue
    return ""


# ── Mouse + window helpers ────────────────────────────────────────────────────
def get_mouse_pos():
    # xdotool works on X11 and on XWayland; on pure Wayland it returns 0,0.
    try:
        r = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                           capture_output=True, text=True, timeout=1.0)
        pos = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                pos[k] = v.strip()
        x, y = int(pos.get("X", 0)), int(pos.get("Y", 0))
        if (x, y) != (0, 0):
            return x, y
    except Exception:
        pass
    # Wayland fallback: AT-SPI sometimes reports pointer position via the
    # event controller, but there's no portable subprocess for it. Returning
    # (0,0) means hover-mode is effectively disabled, which the GUI surfaces.
    return (0, 0)


def get_active_pid():
    try:
        r = subprocess.run(["xdotool", "getactivewindow", "getwindowpid"],
                           capture_output=True, text=True, timeout=1.0)
        if r.returncode == 0:
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


# ── AT-SPI hover text ──────────────────────────────────────────────────────────
def _is_daemon(name: str) -> bool:
    if not name:
        return False
    low = name.lower()
    return (any(low.startswith(p) for p in _DAEMON_PREFIXES)
            or name in _DAEMON_NAMES)


def _trim_text(t: str, max_chars=300) -> str:
    """Return at most the first sentence, capped at max_chars."""
    t = t.strip()
    if len(t) <= max_chars:
        return t
    # Try to cut at sentence boundary
    for sep in (".", "!", "?", "\n"):
        idx = t.find(sep)
        if 0 < idx <= max_chars:
            return t[:idx + 1].strip()
    return t[:max_chars].strip()


def _label_for_role(node) -> str:
    """For an interactive but nameless node (e.g. an icon-only button), return
    a localized control-type label plus checked/expanded state. Returns "" for
    everything else, so structural nodes stay silent and the candidate-picking
    logic in _find_at_pos / _best_text keeps working unchanged."""
    _init_roles()
    try:
        role = node.getRole()
    except Exception:
        return ""
    word = (_INTERACTIVE_ROLES or {}).get(role)
    if not word:
        return ""
    label = tr(word)
    try:
        import pyatspi
        st = node.getState()
        if st.contains(pyatspi.STATE_CHECKED):
            label += ", " + tr("checked")
        elif st.contains(pyatspi.STATE_EXPANDED):
            label += ", " + tr("expanded")
    except Exception:
        pass
    return label


def _node_text(node) -> str:
    """Extract the best readable string from a single AT-SPI node.

    Order, specific to generic: accessible text, name, labelled-by relation,
    description, image description, and finally — for interactive controls
    only — a localized role label so a nameless icon button still announces
    "button" instead of going completely silent.
    """
    # 1. Accessible text (labels, entries, paragraphs)
    try:
        t = node.queryText().getText(0, -1)
        # Strip object-replacement characters (inline images/links in Firefox)
        t = t.replace("\uFFFC", "").strip()
        if t and len(t) > 1:
            return _trim_text(t)
    except Exception:
        pass

    # 2. node.name (buttons, icons, menu items)
    name = (node.name or "").strip()
    if name and len(name) > 1 and not _is_daemon(name):
        return name

    # 3. Labelled-by: the name sometimes lives in a separate label widget
    try:
        import pyatspi
        for rel in node.getRelationSet():
            if rel.getRelationType() == pyatspi.RELATION_LABELLED_BY:
                for i in range(rel.getNTargets()):
                    lt = (rel.getTarget(i).name or "").strip()
                    if lt and len(lt) > 1 and not _is_daemon(lt):
                        return lt
    except Exception:
        pass

    # 4. AccessibleDescription
    try:
        desc = (node.description or "").strip()
        if desc and len(desc) > 1:
            return _trim_text(desc)
    except Exception:
        pass

    # 5. Image description (occasionally set on icon-only buttons)
    try:
        idesc = (node.queryImage().imageDescription or "").strip()
        if idesc and len(idesc) > 1:
            return idesc
    except Exception:
        pass

    # 6. Last resort: name the control TYPE for interactive, nameless nodes
    return _label_for_role(node)


def _find_at_pos(node, x, y, depth=0) -> str:
    """Recursively find the deepest AT-SPI node at (x, y) with readable text."""
    if depth > 20 or node is None:
        return ""

    _init_roles()

    try:
        import pyatspi
    except Exception:
        return ""

    # Determine role early
    role = None
    try:
        role = node.getRole()
    except Exception:
        pass

    # Bounds check
    has_bounds       = False
    is_zero_size     = False
    try:
        ext = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
        if (ext.width == 0 or ext.height == 0) and ext.x >= 0 and ext.y >= 0:
            is_zero_size = True
        if ext.width > 0 and ext.height > 0:
            has_bounds = True
            if not (ext.x <= x < ext.x + ext.width and
                    ext.y <= y < ext.y + ext.height):
                return ""
    except Exception:
        pass

    # Menu containers with 0x0 bounds: their popup children may have real bounds
    menu_roles = (
        getattr(__import__("pyatspi"), "ROLE_MENU_BAR", None),
        getattr(__import__("pyatspi"), "ROLE_MENU", None),
        getattr(__import__("pyatspi"), "ROLE_POPUP_MENU", None),
    )
    is_menu = role in menu_roles
    is_zero_menu_passthrough = is_zero_size and is_menu

    # Skip zero-size nodes that aren't menu containers
    if is_zero_size and not is_zero_menu_passthrough:
        return ""

    is_container = role in _CONTAINER_ROLES if role is not None else False

    # Depth-first: deepest matching child wins
    for i in range(node.childCount):
        try:
            result = _find_at_pos(node.getChildAtIndex(i), x, y, depth + 1)
            if result:
                return result
        except Exception:
            pass

    # Pure containers and zero-size menu passthroughs never contribute text
    if is_container or is_zero_menu_passthrough:
        return ""

    # Don't return text from nodes without valid visible bounds
    if not has_bounds:
        return ""

    return _node_text(node)


def get_window_at(x, y):
    """Return the X11 window ID at (x, y) using xdotool."""
    try:
        r = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=1.0)
        for line in r.stdout.splitlines():
            if line.startswith("WINDOW="):
                val = line.split("=", 1)[1].strip()
                return int(val) if val and val != "0" else None
    except Exception:
        pass
    return None


def get_pid_for_window(win_id):
    """Return the PID owning a given X11 window ID."""
    try:
        r = subprocess.run(
            ["xdotool", "getwindowpid", str(win_id)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=1.0)
        if r.returncode == 0:
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


def get_text_at(x, y) -> str:
    """Return readable text of the UI element under (x, y) via AT-SPI."""
    try:
        import pyatspi

        win_id  = get_window_at(x, y)
        top_pid = get_pid_for_window(win_id) if win_id else get_active_pid()

        desktop = pyatspi.Registry.getDesktop(0)

        # Pass 1: try the app whose PID owns the window under the cursor
        if top_pid:
            for app in desktop:
                if app is None:
                    continue
                if _is_daemon(app.name or ""):
                    continue
                try:
                    if app.get_process_id() != top_pid:
                        continue
                except Exception:
                    continue
                text = _query_app(app, x, y)
                if text:
                    return text

        # Pass 2: GNOME menus/dialogs may be a separate process or have no window.
        # Scan all non-daemon apps and pick the deepest match.
        for app in desktop:
            if app is None:
                continue
            if _is_daemon(app.name or ""):
                continue
            try:
                if top_pid and app.get_process_id() == top_pid:
                    continue  # already tried
            except Exception:
                pass
            text = _query_app(app, x, y)
            if text:
                return text

    except Exception as e:
        log.debug(f"AT-SPI error: {e}")

    return ""


def _query_app(app, x, y) -> str:
    """Query a single AT-SPI app for text at (x,y).

    First tries getAccessibleAtPoint (fast path used by Orca), then falls
    back to manual depth-first traversal — needed for GNOME menus, settings
    dialogs and LibreOffice where getAccessibleAtPoint sometimes returns None.
    """
    import pyatspi
    for i in range(app.childCount):
        try:
            window = app.getChildAtIndex(i)

            # Fast path: getAccessibleAtPoint
            try:
                node = window.queryComponent().getAccessibleAtPoint(
                    x, y, pyatspi.DESKTOP_COORDS)
                if node is not None:
                    text = _best_text(node)
                    if text:
                        return text
            except Exception:
                pass

            # Fallback: manual traversal
            text = _find_at_pos(window, x, y)
            if text:
                return text
        except Exception:
            continue
    return ""


def _best_text(node) -> str:
    """Get the best text from a node, walking up to parent if needed."""
    # Try the node itself first
    t = _node_text(node)
    if t:
        return t
    # If empty, try the parent — but ONLY if parent is not a window/frame
    # (otherwise we'd return the window title instead of the hovered element)
    try:
        parent = node.parent
        if parent and parent.getRole() not in _CONTAINER_ROLES:
            t = _node_text(parent)
            if t:
                return t
    except Exception:
        pass
    return ""


def _clipboard_get():
    """Return current clipboard contents (best effort, empty string on failure)."""
    if IS_WAYLAND and _have("wl-paste"):
        try:
            r = subprocess.run(["wl-paste", "--no-newline"],
                               capture_output=True, text=True, timeout=1.0)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
    if _have("xclip"):
        try:
            r = subprocess.run(["xclip", "-selection", "clipboard", "-out"],
                               capture_output=True, text=True, timeout=1.0)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
    return ""


def _clipboard_set(text):
    """Set clipboard. Returns True on success."""
    data = text.encode("utf-8")
    if IS_WAYLAND and _have("wl-copy"):
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(data, timeout=3.0)
            return p.returncode == 0
        except Exception:
            pass
    if _have("xclip"):
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard", "-in"],
                                 stdin=subprocess.PIPE)
            p.communicate(data, timeout=3.0)
            return p.returncode == 0
        except Exception:
            pass
    return False


def _type_text(text):
    """Type characters one by one at the keyboard focus. Returns True on success."""
    # X11 / XWayland: xdotool works everywhere xdotool is installed.
    if _have("xdotool"):
        try:
            r = subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "1", "--", text],
                check=False, timeout=15.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    # Pure Wayland: wtype is the native equivalent of `xdotool type`.
    if _have("wtype"):
        try:
            r = subprocess.run(["wtype", "--", text], check=False, timeout=15.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    # Last resort: ydotool. Requires the ydotoold service to be running.
    if _have("ydotool"):
        try:
            r = subprocess.run(["ydotool", "type", "--", text],
                               check=False, timeout=15.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def _send_paste_shortcut():
    """Send Ctrl+V to the focused window. Returns True on success."""
    if _have("xdotool"):
        try:
            r = subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                               check=False, timeout=3.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    if _have("wtype"):
        try:
            r = subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
                               check=False, timeout=3.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    if _have("ydotool"):
        try:
            # ydotool key codes: 29=Left Ctrl, 47=V. ":1" = down, ":0" = up.
            r = subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                               check=False, timeout=3.0)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def type_or_paste_text(text):
    """Type short text directly; paste longer text via clipboard for speed.

    Returns (ok, message). On Wayland-without-typer setups falls back to
    'clipboard only' so the user can paste manually.

    Clipboard discipline: we only touch the clipboard when paste mode is
    actually needed (long text, or typing failed). The previous clipboard
    is restored 100 ms after the paste — long enough for the target app
    to process Ctrl+V, short enough to avoid the bug where the user
    pastes the transcription somewhere by accident a moment later.
    """
    if not text:
        return False, "Empty"
    try:
        # Short text: prefer direct keystroke injection.
        if len(text) <= WHISPER_TYPE_LIMIT:
            if _type_text(text):
                return True, "ok"
            # Typing failed (likely pure Wayland without wtype/ydotool).
            # Fall through to clipboard mode.
            log.warning("type failed, falling back to clipboard")

        # Long text — or short text on a system without a typer — uses
        # the clipboard and sends Ctrl+V.
        old = _clipboard_get()
        if not _clipboard_set(text):
            return False, "Could not set clipboard"
        pasted = _send_paste_shortcut()

        # Restore previous clipboard quickly so the transcription doesn't
        # linger in clipboard memory and risk being pasted elsewhere.
        def _restore():
            time.sleep(0.1)
            try:
                _clipboard_set(old)
            except Exception:
                pass
        threading.Thread(target=_restore, daemon=True).start()

        if pasted:
            return True, "ok"
        # Couldn't trigger paste either — clipboard is set, user can paste manually.
        # In this case we DO NOT restore: the user explicitly needs the
        # transcription there. Cancel the restore thread by overwriting old.
        return True, "in clipboard (press Ctrl+V)"
    except Exception as e:
        return False, str(e)


# ── Hover loop ─────────────────────────────────────────────────────────────────
_hover_running    = False


def set_hover_running(running):
    """Turn the hover-to-read loop on/off from the front-end."""
    global _hover_running
    _hover_running = bool(running)


def hover_running():
    return _hover_running
_hover_thread     = None
_get_slot_config  = None


def set_slot_config_provider(fn):
    """Register a callback returning the active slot's voice-config dict.
    Used by hover-to-read and slot-aware speech."""
    global _get_slot_config
    _get_slot_config = fn
_last_spoken      = None
_last_spoken_lock = threading.Lock()
_last_event_time  = 0.0  # timestamp of last event-based speak

# ── Event-based hover (Orca-style) ────────────────────────────────────────────
_event_listener = None


def _speak_if_new(text):
    """Speak text only if it differs from what we last announced, and record
    the time so the polling hover can stay quiet for a moment afterwards."""
    global _last_spoken, _last_event_time
    if not text:
        return
    with _last_spoken_lock:
        if text == _last_spoken:
            return
        _last_spoken     = text
        _last_event_time = time.monotonic()
    cfg = _get_slot_config() if _get_slot_config else {}
    speak(text, cfg)


def _event_from_daemon(event) -> bool:
    """True if an AT-SPI event originates from the desktop shell or another
    daemon (cinnamon, nemo-desktop, …). Their UI elements fire focus/selection
    events constantly, and querying the shell synchronously while it is
    emitting can stall its main loop — Cinnamon's watchdog then kills it
    ("fallback mode"). So: never even touch events from those processes."""
    try:
        app = getattr(event, "host_application", None)
        if app is None:
            src = event.source
            app = src.getApplication() if src is not None else None
        return app is not None and _is_daemon(app.name or "")
    except Exception:
        return False


def _on_focus_event(event):
    """Called by AT-SPI when an element gains focus (or its item is selected)."""
    if not _hover_running or _event_from_daemon(event):
        return
    try:
        node = event.source
        if node is None:
            return

        text = _node_text(node)

        if not text:
            try:
                parent = node.parent
                if parent and parent.getRole() not in (_CONTAINER_ROLES or set()):
                    text = _node_text(parent)
            except Exception:
                pass

        _speak_if_new(text)

    except Exception as e:
        log.debug(f"Focus event error: {e}")


_last_selection_ts = 0.0


def _on_selection_event(event):
    """A selection changed in a container (list, icon view, tree). Read the
    selected item itself, not the container — this is what makes Nemo's icon
    and list views speak while you arrow or click through them, the way a
    screen reader does on focus. Daemon/shell events are ignored and the
    handler is rate-limited: selection-changed can fire in rapid bursts
    (e.g. select-all), and answering every one with synchronous AT-SPI
    queries stresses the emitting app."""
    global _last_selection_ts
    if not _hover_running or _event_from_daemon(event):
        return
    now = time.monotonic()
    if now - _last_selection_ts < 0.15:
        return
    _last_selection_ts = now
    try:
        node = event.source
        if node is None:
            return
        sel = node.querySelection()
        if sel.nSelectedChildren < 1:
            return
        child = sel.getSelectedChild(0)
        if child is not None:
            _speak_if_new(_node_text(child))
    except Exception as e:
        log.debug(f"Selection event error: {e}")


def _on_caret_event(event):
    """The text caret moved (typing, arrow keys, clicking into text). Read the
    line at the new caret position. Deduplicated, so resting on a line is
    silent; moving to a new line reads it."""
    if not _hover_running:
        return
    try:
        import pyatspi
        node = event.source
        if node is None:
            return
        offset = int(getattr(event, "detail1", -1) or -1)
        if offset < 0:
            return
        txt = node.queryText()
        seg = txt.getTextAtOffset(offset, pyatspi.TEXT_BOUNDARY_LINE_START)
        line = (seg[0] if isinstance(seg, (tuple, list)) else seg.content)
        line = line.replace("\uFFFC", "").strip()
        if line and len(line) > 1:
            _speak_if_new(_trim_text(line))
    except Exception as e:
        log.debug(f"Caret event error: {e}")


def _start_event_listener():
    global _event_listener
    try:
        import pyatspi

        class Listener:
            def onFocus(self, event):
                _on_focus_event(event)
            def onStateChanged(self, event):
                if event.type.endswith(("focused", "selected")):
                    _on_focus_event(event)
            def onSelection(self, event):
                _on_selection_event(event)
            def onCaret(self, event):
                _on_caret_event(event)

        _event_listener = Listener()
        pyatspi.Registry.registerEventListener(_event_listener.onFocus, "focus")
        pyatspi.Registry.registerEventListener(_event_listener.onStateChanged,
                                               "object:state-changed:focused")
        pyatspi.Registry.registerEventListener(_event_listener.onSelection,
                                               "object:selection-changed")
        # Caret-following (onCaret) is intentionally NOT registered by default:
        # while dictating, VoxFox types into a field and the caret moves, which
        # would make it read back what is being typed. Left available for a
        # future opt-in toggle.
        log.info("AT-SPI event listener started")
        pyatspi.Registry.start(async_=False)
    except Exception as e:
        log.error(f"Event listener error: {e}")


def _stop_event_listener():
    global _event_listener
    try:
        import pyatspi
        if _event_listener:
            pyatspi.Registry.deregisterEventListener(
                _event_listener.onFocus, "focus")
            pyatspi.Registry.deregisterEventListener(
                _event_listener.onStateChanged, "object:state-changed:focused")
            pyatspi.Registry.deregisterEventListener(
                _event_listener.onSelection, "object:selection-changed")
        pyatspi.Registry.stop()
        log.info("AT-SPI event listener stopped")
    except Exception as e:
        log.debug(f"Stop event listener: {e}")
    _event_listener = None


# ── Polling hover (fallback) ───────────────────────────────────────────────────
# Only speaks when the event listener hasn't spoken recently
_EVENT_SILENCE = 0.8  # seconds: suppress polling after an event-based speak


def hover_loop():
    global _last_spoken
    last_pos    = (-999, -999)
    hover_start = None
    spoken_text = None
    spoken_pos  = None

    while _hover_running:
        time.sleep(HOVER_POLL)
        pos = get_mouse_pos()
        dx  = abs(pos[0] - last_pos[0])
        dy  = abs(pos[1] - last_pos[1])

        if dx > MIN_MOVE_PX or dy > MIN_MOVE_PX:
            hover_start = time.monotonic()
            spoken_text = None
            spoken_pos  = None
            stop_speaking()
            last_pos = pos
        else:
            if hover_start is None:
                hover_start = time.monotonic()
            if time.monotonic() - hover_start >= HOVER_DELAY:
                if pos != spoken_pos:
                    # Skip if event listener spoke very recently
                    if time.monotonic() - _last_event_time < _EVENT_SILENCE:
                        spoken_pos = pos
                        continue
                    text = get_text_at(pos[0], pos[1])
                    if not _hover_running:
                        return
                    if text and text != spoken_text:
                        with _last_spoken_lock:
                            _last_spoken = text
                        cfg = _get_slot_config() if _get_slot_config else {}
                        speak(text, cfg)
                        spoken_text = text
                    spoken_pos = pos


__all__ = [
    "_DAEMON_PREFIXES",
    "_DAEMON_NAMES",
    "_CONTAINER_ROLES",
    "_init_roles",
    "get_selection",
    "get_mouse_pos",
    "get_active_pid",
    "_is_daemon",
    "_trim_text",
    "_node_text",
    "_find_at_pos",
    "get_window_at",
    "get_pid_for_window",
    "get_text_at",
    "_query_app",
    "_best_text",
    "_clipboard_get",
    "_clipboard_set",
    "_type_text",
    "_send_paste_shortcut",
    "type_or_paste_text",
    "_hover_running",
    "set_hover_running",
    "hover_running",
    "_hover_thread",
    "_get_slot_config",
    "set_slot_config_provider",
    "_last_spoken",
    "_last_spoken_lock",
    "_last_event_time",
    "_event_listener",
    "_on_focus_event",
    "_start_event_listener",
    "_stop_event_listener",
    "_EVENT_SILENCE",
    "hover_loop",
]

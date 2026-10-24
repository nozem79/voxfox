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


"""voxfox_core.a11y — Hover reading through AT-SPI: what is under the
mouse, focus, selection and caret events, and the hover loop.

Reading the selection and typing text live in textio.py; the mouse
position and the window under it in pointer.py.
"""

import subprocess, threading, time, os, socket
from .common import HOVER_DELAY, HOVER_POLL, MIN_MOVE_PX, have_command, log
from .common import _ as tr
from .tts import speak, stop_speaking
from .pointer import get_active_pid, get_mouse_pos, get_pid_for_window, get_window_at


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

class _RoleSets:
    """AT-SPI role sets, filled once after the first successful pyatspi
    import (see _init_roles).

    container    roles that only hold other things (windows, panels)
    interactive  role -> English control word (run through tr()), the
                 last-resort label for nameless icon-only controls so
                 hover never goes silent
    """

    def __init__(self):
        self.container = None
        self.interactive = None


_roles = _RoleSets()


def _a11y_bus_address():
    """Discover the AT-SPI bus address the same way libatspi does, WITHOUT
    touching libatspi (which would abort the whole process on a broken bus).
    Returns the D-Bus address string (e.g. 'unix:path=/run/user/1000/at-spi/
    bus_0') or None."""
    addr = os.environ.get("AT_SPI_BUS_ADDRESS")
    if addr:
        return addr
    if not have_command("gdbus"):
        return None
    try:
        r = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.a11y.Bus",
             "--object-path", "/org/a11y/bus",
             "--method", "org.a11y.Bus.GetAddress"],
            capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        out = r.stdout.strip()           # e.g. ('unix:path=/run/user/1000/...',)
        i, j = out.find("unix:"), out.rfind("'")
        if i != -1 and j > i:
            return out[i:j]
        return out.strip("(),' ") or None
    except Exception as e:
        log.debug(f"a11y bus address lookup failed: {e}")
        return None


def a11y_bus_reachable():
    """True if the AT-SPI accessibility bus can actually be connected to. This
    is a plain unix-socket probe, so a misconfigured or permission-denied bus
    (e.g. a stale root-owned /root/.cache/at-spi/bus_0) is reported as False
    instead of hard-aborting the process inside libatspi's dbind. When this is
    False, hover must refuse rather than call into pyatspi."""
    addr = _a11y_bus_address()
    if not addr:
        return False
    # An address can list several transports separated by ';'. We only need one
    # unix socket we can open.
    for part in addr.split(";"):
        part = part.strip()
        path = abstract = None
        for tok in part.split(","):
            tok = tok.strip()
            if tok.startswith("unix:path=") or tok.startswith("path="):
                path = tok.split("=", 1)[1]
            elif tok.startswith("unix:abstract=") or tok.startswith("abstract="):
                abstract = tok.split("=", 1)[1]
        target = ("\0" + abstract) if abstract else path
        if not target:
            continue
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            s.connect(target)
            return True
        except OSError as e:
            log.debug(f"a11y bus not reachable at {part!r}: {e}")
        finally:
            s.close()
    return False


def _init_roles():
    if _roles.container is not None:
        return
    try:
        import pyatspi
        _roles.container = {
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
        _roles.interactive = {}
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
                _roles.interactive[r] = word
    except Exception:
        _roles.container = set()
        _roles.interactive = {}



# ── AT-SPI hover text ──────────────────────────────────────────────────────────
def _is_daemon(name: str) -> bool:
    if not name:
        return False
    low = name.lower()
    return (any(low.startswith(p) for p in _DAEMON_PREFIXES)
            or name in _DAEMON_NAMES)


def trim_text(t: str, max_chars=300) -> str:
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
    word = (_roles.interactive or {}).get(role)
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
            return trim_text(t)
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
            return trim_text(desc)
    except Exception:
        pass

    # 5. Image description (occasionally set on icon-only buttons)
    try:
        idesc = (node.queryImage().imageDescription or "").strip()
        if idesc and len(idesc) > 1:
            return idesc
    except Exception:
        pass

    # 6. Climb to a named interactive ancestor: composite buttons (an icon
    # plus a label in a box) hit-test on their inner parts, which have no
    # name of their own. Reading the parent button's name makes the whole
    # button announce as one unit wherever the pointer is.
    try:
        import pyatspi
        parent = node.parent
        hops = 0
        while parent is not None and hops < 3:
            role = parent.getRole()
            if role in (pyatspi.ROLE_PUSH_BUTTON, pyatspi.ROLE_TOGGLE_BUTTON,
                        pyatspi.ROLE_CHECK_BOX, pyatspi.ROLE_RADIO_BUTTON,
                        pyatspi.ROLE_MENU_ITEM):
                pname = (parent.name or "").strip()
                if pname and len(pname) > 1 and not _is_daemon(pname):
                    return pname
                break
            parent = parent.parent
            hops += 1
    except Exception:
        pass

    # 7. Last resort: name the control TYPE for interactive, nameless nodes
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
        getattr(pyatspi, "ROLE_MENU_BAR", None),
        getattr(pyatspi, "ROLE_MENU", None),
        getattr(pyatspi, "ROLE_POPUP_MENU", None),
    )
    is_menu = role in menu_roles
    is_zero_menu_passthrough = is_zero_size and is_menu

    # Skip zero-size nodes that aren't menu containers
    if is_zero_size and not is_zero_menu_passthrough:
        return ""

    is_container = role in _roles.container if role is not None else False

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


class _HoverState:
    """Everything hover reading keeps between calls. One instance, `_hover`.

    own_window_reader  set by the front-end (voxfox_ui.selfread): reads
                       VoxFox's own windows, returns None off them
    running            hover reading is switched on
    thread             the hover loop's thread
    slot_config        callback returning the active slot's voice config
    last_spoken        the last text said, so it is not repeated
    last_spoken_lock   guards last_spoken
    last_event_time    when an AT-SPI event last made us speak
    event_listener     the AT-SPI event listener, while it runs
    last_selection_ts  when a selection event was last answered
    """

    def __init__(self):
        self.own_window_reader = None
        self.running = False
        self.thread = None
        self.slot_config = None
        self.last_spoken = None
        self.last_spoken_lock = threading.Lock()
        self.last_event_time = 0.0
        self.event_listener = None
        self.last_selection_ts = 0.0


_hover = _HoverState()


def set_own_window_reader(fn):
    _hover.own_window_reader = fn


def get_text_at(x, y) -> str:
    """Return readable text of the UI element under (x, y) via AT-SPI."""
    if _hover.own_window_reader is not None:
        try:
            own = _hover.own_window_reader(x, y)
            if own is not None:
                return own        # on a VoxFox window: never ask AT-SPI
        except Exception as e:
            log.debug(f"own window reader failed: {e}")
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
        if parent and parent.getRole() not in _roles.container:
            t = _node_text(parent)
            if t:
                return t
    except Exception:
        pass
    return ""


# ── Hover loop ─────────────────────────────────────────────────────────────────


def set_hover_running(running):
    """Turn the hover-to-read loop on/off from the front-end."""
    _hover.running = bool(running)


def hover_running():
    return _hover.running


def set_slot_config_provider(fn):
    """Register a callback returning the active slot's voice-config dict.
    Used by hover-to-read and slot-aware speech."""
    _hover.slot_config = fn

# ── Event-based hover (Orca-style) ────────────────────────────────────────────


def _speak_if_new(text):
    """Speak text only if it differs from what we last announced, and record
    the time so the polling hover can stay quiet for a moment afterwards."""
    if not text:
        return
    with _hover.last_spoken_lock:
        if text == _hover.last_spoken:
            return
        _hover.last_spoken     = text
        _hover.last_event_time = time.monotonic()
    cfg = _hover.slot_config() if _hover.slot_config else {}
    speak(text, cfg)


def speak_if_new(text):
    """Public: speak `text` unless it was the last thing said (used for
    keyboard focus in VoxFox's own windows)."""
    _speak_if_new(text)


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


def event_from_self(event) -> bool:
    """True for AT-SPI events about VoxFox's own windows.

    AT-SPI delivers events on VoxFox's main thread. Answering one from our
    own window meant asking our own process, over AT-SPI, for the text --
    a call that waits for the very main thread it is running on. The
    window froze until the call gave up, and speech lagged behind the
    pointer: in menus and settings the previous item was read. VoxFox's
    own windows are read directly instead (voxfox_ui.selfread)."""
    try:
        app = getattr(event, "host_application", None)
        if app is None:
            return False
        return app.get_process_id() == os.getpid()
    except Exception:
        return False


def _on_focus_event(event):
    """Called by AT-SPI when an element gains focus (or its item is selected)."""
    if not _hover.running or event_from_self(event) or _event_from_daemon(event):
        return
    try:
        node = event.source
        if node is None:
            return

        text = _node_text(node)

        if not text:
            try:
                parent = node.parent
                if parent and parent.getRole() not in (_roles.container or set()):
                    text = _node_text(parent)
            except Exception:
                pass

        _speak_if_new(text)

    except Exception as e:
        log.debug(f"Focus event error: {e}")




def _on_selection_event(event):
    """A selection changed in a container (list, icon view, tree). Read the
    selected item itself, not the container — this is what makes Nemo's icon
    and list views speak while you arrow or click through them, the way a
    screen reader does on focus. Daemon/shell events are ignored and the
    handler is rate-limited: selection-changed can fire in rapid bursts
    (e.g. select-all), and answering every one with synchronous AT-SPI
    queries stresses the emitting app."""
    if not _hover.running or event_from_self(event) or _event_from_daemon(event):
        return
    now = time.monotonic()
    if now - _hover.last_selection_ts < 0.15:
        return
    _hover.last_selection_ts = now
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
    if not _hover.running or event_from_self(event):
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
            _speak_if_new(trim_text(line))
    except Exception as e:
        log.debug(f"Caret event error: {e}")


def start_event_listener():
    try:
        import pyatspi

        class Listener:
            def onFocus(self, event):
                _on_focus_event(event)
            def onStateChanged(self, event):
                # Only an element GAINING focus or selection (detail1 1).
                # The one that just lost it fires the same event with 0;
                # reading that one said the item the pointer had left.
                if event.type.endswith(("focused", "selected")) and \
                        getattr(event, "detail1", 1):
                    _on_focus_event(event)
            def onSelection(self, event):
                _on_selection_event(event)
            def onCaret(self, event):
                _on_caret_event(event)

        _hover.event_listener = Listener()
        pyatspi.Registry.registerEventListener(_hover.event_listener.onFocus, "focus")
        pyatspi.Registry.registerEventListener(_hover.event_listener.onStateChanged,
                                               "object:state-changed:focused")
        pyatspi.Registry.registerEventListener(_hover.event_listener.onSelection,
                                               "object:selection-changed")
        # Caret-following (onCaret) is intentionally NOT registered by default:
        # while dictating, VoxFox types into a field and the caret moves, which
        # would make it read back what is being typed. Left available for a
        # future opt-in toggle.
        log.info("AT-SPI event listener started")
        pyatspi.Registry.start(async_=False)
    except Exception as e:
        log.error(f"Event listener error: {e}")


def stop_event_listener():
    try:
        import pyatspi
        if _hover.event_listener:
            pyatspi.Registry.deregisterEventListener(
                _hover.event_listener.onFocus, "focus")
            pyatspi.Registry.deregisterEventListener(
                _hover.event_listener.onStateChanged, "object:state-changed:focused")
            pyatspi.Registry.deregisterEventListener(
                _hover.event_listener.onSelection, "object:selection-changed")
        pyatspi.Registry.stop()
        log.info("AT-SPI event listener stopped")
    except Exception as e:
        log.debug(f"Stop event listener: {e}")
    _hover.event_listener = None


# ── Polling hover (fallback) ───────────────────────────────────────────────────
# Only speaks when the event listener hasn't spoken recently
_EVENT_SILENCE = 0.8  # seconds: suppress polling after an event-based speak


def hover_loop():
    last_pos    = (-999, -999)
    hover_start = None
    spoken_text = None
    spoken_pos  = None

    while _hover.running:
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
                    if time.monotonic() - _hover.last_event_time < _EVENT_SILENCE:
                        spoken_pos = pos
                        continue
                    text = get_text_at(pos[0], pos[1])
                    if not _hover.running:
                        return
                    if text and text != spoken_text:
                        with _hover.last_spoken_lock:
                            _hover.last_spoken = text
                        cfg = _hover.slot_config() if _hover.slot_config else {}
                        speak(text, cfg)
                        spoken_text = text
                    spoken_pos = pos


__all__ = [
    "_DAEMON_PREFIXES",
    "_DAEMON_NAMES",
    "_init_roles",
    "_is_daemon",
    "trim_text",
    "_node_text",
    "_find_at_pos",
    "get_text_at",
    "set_own_window_reader",
    "_query_app",
    "_best_text",
    "set_hover_running",
    "hover_running",
    "set_slot_config_provider",
    "_on_focus_event",
    "event_from_self",
    "speak_if_new",
    "start_event_listener",
    "stop_event_listener",
    "_EVENT_SILENCE",
    "hover_loop",
    "_a11y_bus_address",
    "a11y_bus_reachable",
]

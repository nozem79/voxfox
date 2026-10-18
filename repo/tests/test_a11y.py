"""Tests for voxfox_core.a11y's Xlib-based mouse position query. No live X
server needed: the DISPLAY-unset case is testable purely by clearing the
environment variable, and the (0,0)-trust fix is testable by mocking the
Xlib call itself.
"""

import voxfox_core.a11y as a11y


def test_get_mouse_pos_xlib_raises_immediately_without_display(monkeypatch):
    """Regression: with $DISPLAY unset (a pure Wayland session with no
    XWayland), every hover poll used to attempt a fresh Xlib connection
    anyway -- roughly 6-7 times a second, forever -- before falling
    through to xdotool. Now it's remembered after the first check."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(a11y, "_xlib_unavailable", False)
    monkeypatch.setattr(a11y, "_xlib_conn", None)

    connect_attempts = []
    if a11y._HAVE_XLIB:
        def fake_display(*a, **kw):
            connect_attempts.append(1)
            raise RuntimeError("should never be called")
        monkeypatch.setattr(a11y._xlib_display, "Display", fake_display)

    import pytest
    for _ in range(5):
        with pytest.raises(Exception):
            a11y._get_mouse_pos_xlib()

    assert connect_attempts == []
    assert a11y._xlib_unavailable is True


def test_get_mouse_pos_xlib_retries_when_display_is_set_but_unreachable(
        monkeypatch):
    """A $DISPLAY that is set but points at nothing (or a connection that
    broke mid-session) is a different case from "no server at all", and
    should keep being retried -- the server could still come back."""
    monkeypatch.setenv("DISPLAY", ":199")  # does not exist
    monkeypatch.setattr(a11y, "_xlib_unavailable", False)
    monkeypatch.setattr(a11y, "_xlib_conn", None)

    if not a11y._HAVE_XLIB:
        return  # nothing to test without python-xlib installed

    attempts = []

    class _FailingDisplay:
        def __init__(self, *a, **kw):
            attempts.append(1)
            raise a11y._XlibDisplayError(":199", "connection refused")

    monkeypatch.setattr(a11y._xlib_display, "Display", _FailingDisplay)

    import pytest
    for _ in range(4):
        with pytest.raises(Exception):
            a11y._get_mouse_pos_xlib()

    assert len(attempts) == 4  # retried every time, never gave up
    assert a11y._xlib_unavailable is False


def test_get_mouse_pos_trusts_a_genuine_zero_zero_from_xlib(monkeypatch):
    """Regression: get_mouse_pos() used to treat *any* (0, 0) result the
    same as a failure and fall through to xdotool anyway -- a heuristic
    that only ever made sense for xdotool's own design, where (0, 0) is
    indistinguishable from "it didn't work". The Xlib path raises on real
    failure, so a plain return is trustworthy even when it's (0, 0)."""
    monkeypatch.setattr(a11y, "_get_mouse_pos_xlib", lambda: (0, 0))
    xdotool_called = []
    monkeypatch.setattr(a11y, "_get_mouse_pos_xdotool",
                        lambda: (xdotool_called.append(1), (9, 9))[1])

    assert a11y.get_mouse_pos() == (0, 0)
    assert xdotool_called == []


def test_get_mouse_pos_falls_back_to_xdotool_on_xlib_failure(monkeypatch):
    def boom():
        raise RuntimeError("no connection")
    monkeypatch.setattr(a11y, "_get_mouse_pos_xlib", boom)
    monkeypatch.setattr(a11y, "_get_mouse_pos_xdotool", lambda: (5, 6))

    assert a11y.get_mouse_pos() == (5, 6)


# ── VoxFox's own windows (read without AT-SPI) ────────────────────────────

def test_own_window_text_is_used_and_at_spi_is_not_asked(monkeypatch):
    import voxfox_core.a11y as a
    monkeypatch.setattr(a, "_own_window_reader", lambda x, y: "Voorlezen")
    monkeypatch.setattr(a, "get_window_at", lambda x, y: (_ for _ in ()).throw(
        AssertionError("AT-SPI path must not run")))
    assert a.get_text_at(10, 20) == "Voorlezen"


def test_nothing_to_say_on_our_window_stays_silent(monkeypatch):
    import voxfox_core.a11y as a
    monkeypatch.setattr(a, "_own_window_reader", lambda x, y: "")
    monkeypatch.setattr(a, "get_window_at", lambda x, y: (_ for _ in ()).throw(
        AssertionError("AT-SPI path must not run")))
    assert a.get_text_at(10, 20) == ""


def test_other_windows_still_go_through_at_spi(monkeypatch):
    import voxfox_core.a11y as a
    import sys
    import types
    asked = []
    fake = types.SimpleNamespace(Registry=types.SimpleNamespace(getDesktop=lambda n: []))
    monkeypatch.setitem(sys.modules, "pyatspi", fake)
    monkeypatch.setattr(a, "_own_window_reader", lambda x, y: None)
    monkeypatch.setattr(a, "get_window_at", lambda x, y: asked.append((x, y)) or None)
    a.get_text_at(10, 20)
    assert asked == [(10, 20)]


# ── AT-SPI events from VoxFox itself ──────────────────────────────────────

def _event(pid, detail1=1, type_="object:state-changed:focused"):
    import types
    app = types.SimpleNamespace(get_process_id=lambda: pid, name="voxfox")
    return types.SimpleNamespace(host_application=app, detail1=detail1, type=type_,
                                 source=None)


def test_events_from_our_own_windows_are_ignored(monkeypatch):
    # Answering them meant asking ourselves over AT-SPI from our own main
    # thread: the window froze and speech lagged a row behind.
    import os
    import voxfox_core.a11y as a
    monkeypatch.setattr(a, "_hover_running", True)
    touched = []
    monkeypatch.setattr(a, "_node_text", lambda n: touched.append(n) or "x")
    assert a._event_from_self(_event(os.getpid()))
    assert not a._event_from_self(_event(os.getpid() + 1))
    a._on_focus_event(_event(os.getpid()))
    a._on_selection_event(_event(os.getpid()))
    assert touched == []


def test_an_event_without_application_is_not_ours():
    import types
    import voxfox_core.a11y as a
    assert not a._event_from_self(types.SimpleNamespace(host_application=None))

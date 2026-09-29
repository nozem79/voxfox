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

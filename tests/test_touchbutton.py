"""The floating touch button's settings (6.3), and clearing the selection."""
import ast
import json
import os
import types

import voxfox_core as vf
import voxfox_core.common as common
import voxfox_core.state as state
from voxfox_core import textio


def test_defaults():
    cfg = vf.normalize_touch_button(None)
    assert cfg["enabled"] is False
    assert cfg["actions"] == {"tap1": "ocr", "tap2": "pause", "tap3": "page",
                              "tap4": "window", "tap5": "off",
                              "long": "stop_clear"}
    assert cfg["size"] in vf.SIZES and cfg["pos"] is None


def test_every_default_action_is_known():
    for a in vf.DEFAULT_TOUCH_BUTTON["actions"].values():
        assert a in vf.ACTIONS


def test_normalize_cleans_up_bad_values():
    cfg = vf.normalize_touch_button({
        "enabled": 1, "size": "70", "pos": ["12", 30],
        "actions": {"tap1": "read", "tap2": "explode", "long": None}})
    assert cfg["enabled"] is True
    assert cfg["size"] == 64                      # nearest allowed size
    assert cfg["pos"] == [12, 30]
    assert cfg["actions"]["tap1"] == "read"
    assert cfg["actions"]["tap2"] == "pause"      # unknown: default kept
    assert cfg["actions"]["long"] == "stop_clear"
    assert cfg["actions"]["tap3"] == "page"


def test_normalize_survives_rubbish():
    for junk in ("x", 3, [], {"pos": [1]}, {"pos": "a,b"}, {"size": None},
                 {"actions": "read"}):
        assert vf.normalize_touch_button(junk)["actions"]["tap1"] == "ocr"


def test_normalize_does_not_share_the_defaults():
    a = vf.normalize_touch_button(None)
    a["actions"]["tap1"] = "read"
    assert vf.DEFAULT_TOUCH_BUTTON["actions"]["tap1"] == "ocr"


def test_taps_to_gesture():
    assert vf.gesture_for_taps(1) == "tap1"
    assert vf.gesture_for_taps(2) == "tap2"
    assert vf.gesture_for_taps(3) == "tap3"
    assert vf.gesture_for_taps(4) == "tap4"
    assert vf.gesture_for_taps(5) == "tap5"
    assert vf.gesture_for_taps(8) == "tap5"       # a sixth tap is still five
    assert vf.gesture_for_taps(0) == "tap1"


def test_action_for():
    cfg = {"actions": {"long": "none", "tap2": "whisper"}}
    assert vf.action_for(cfg, "long") == "none"
    assert vf.action_for(cfg, "tap2") == "whisper"
    assert vf.action_for(cfg, "tap1") == "ocr"
    assert vf.action_for(None, "nonsense") == "none"


def test_default_position_bottom_right():
    x, y = vf.default_position(0, 0, 1920, 1080, 64)
    assert 1920 - 200 < x < 1920 - 64 and 1080 - 250 < y < 1080 - 64
    x2, _y2 = vf.default_position(1920, 0, 1280, 1024, 64)
    assert x2 > 1920                              # on the second monitor


def test_state_has_and_repairs_the_button(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    monkeypatch.setattr(common, "STATE_FILE", str(p))
    monkeypatch.setattr(state, "STATE_FILE", str(p))
    s = state.load_state()
    assert s["touch_button"]["enabled"] is False
    s["touch_button"] = {"enabled": True, "actions": {"tap1": "bogus"}}
    state.save_state(s)
    s2 = state.load_state()
    assert s2["touch_button"]["enabled"] is True
    assert s2["touch_button"]["actions"]["tap1"] == "ocr"


def test_touch_button_asks_for_xwayland(tmp_path, monkeypatch):
    """voxfox_gtk.py restarts on XWayland when stay-on-top is on; the touch
    button has to stay on top too, so it counts as well."""
    # voxfox_gtk.py starts GTK when imported, so take just the function.
    src = os.path.join(os.path.dirname(__file__), "..", "src", "voxfox_gtk.py")
    with open(src, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_stay_on_top_wanted")
    ns = {"os": os, "json": json}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), src, "exec"), ns)
    mod = types.SimpleNamespace(**ns)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "voxfox").mkdir()
    f = tmp_path / "voxfox" / "state.json"
    f.write_text(json.dumps({"always_on_top": False}))
    assert mod._stay_on_top_wanted() is False
    f.write_text(json.dumps({"always_on_top": False,
                             "touch_button": {"enabled": True}}))
    assert mod._stay_on_top_wanted() is True


class _Run:
    def __init__(self):
        self.calls = []

    def run(self, args, **_kw):
        self.calls.append(args)

        class R:
            returncode = 0
        return R()

    def popen(self, args, **_kw):
        self.calls.append(args)

        class P:
            returncode = 0

            def communicate(self, *_a, **_k):
                return b"", b""
        return P()


def test_clear_selection_wayland(monkeypatch):
    r = _Run()
    monkeypatch.setattr(textio, "IS_WAYLAND", True)
    monkeypatch.setattr(textio, "have_command", lambda c: c == "wl-copy")
    monkeypatch.setattr(textio.subprocess, "run", r.run)
    assert textio.clear_selection() is True
    assert r.calls == [["wl-copy", "--primary", "--clear"]]


def test_clear_selection_x11_leaves_the_clipboard_alone(monkeypatch):
    r = _Run()
    monkeypatch.setattr(textio, "IS_WAYLAND", False)
    monkeypatch.setattr(textio, "have_command", lambda c: c == "xclip")
    monkeypatch.setattr(textio.subprocess, "Popen", r.popen)
    assert textio.clear_selection() is True
    assert r.calls == [["xclip", "-selection", "primary", "-in"]]


def test_clear_selection_without_tools(monkeypatch):
    monkeypatch.setattr(textio, "have_command", lambda c: False)
    assert textio.clear_selection() is False


def test_bearer_header_removes_whitespace():
    """A key pasted with a newline made Python refuse the request
    ("Invalid header value b'Bearer ...\\n'")."""
    assert vf.bearer_header("abc123\n") == "Bearer abc123"
    assert vf.bearer_header("  ab c\r\n") == "Bearer abc"
    assert vf.bearer_header("") is None
    assert vf.bearer_header(None) is None
    assert vf.bearer_header(" \n ") is None


def test_xdotool_error_goes_to_the_log(monkeypatch, caplog):
    class R:
        returncode = 1
        stderr = b"X Error of failed request:  BadWindow (invalid Window)\n"
    monkeypatch.setattr(textio, "have_command", lambda c: c == "xdotool")
    monkeypatch.setattr(textio.subprocess, "run", lambda *a, **k: R())
    with caplog.at_level("WARNING", logger=vf.log.name):
        assert textio._type_text("hallo") is False
    assert "BadWindow" in caplog.text


def test_hide_window_setting():
    assert vf.normalize_touch_button(None)["hide_window"] is False
    assert vf.normalize_touch_button({"hide_window": 1})["hide_window"] is True
    assert "window" in vf.ACTIONS
    assert vf.action_for({"actions": {"tap3": "window"}}, "tap3") == "window"


def test_point_in_rect():
    assert vf.point_in_rect(10, 10, 0, 0, 1920, 1080)
    assert not vf.point_in_rect(1930, 10, 0, 0, 1920, 1080)   # other monitor
    assert vf.point_in_rect(1930, 10, 1920, 0, 1280, 1024)
    assert not vf.point_in_rect(1920, 10, 0, 0, 1920, 1080)  # right edge


def test_older_settings_get_tap4_and_tap5():
    """Settings saved by dev3-dev6 have no tap4/tap5; they get the defaults,
    so five taps switches the button off for them too."""
    cfg = vf.normalize_touch_button({"enabled": True, "actions": {
        "tap1": "read", "tap2": "pause", "tap3": "page", "long": "stop"}})
    assert cfg["actions"]["tap4"] == "window"
    assert cfg["actions"]["tap5"] == "off"
    assert cfg["actions"]["tap1"] == "read"

"""Which GTK theme VoxFox picks for "light" and "dark"."""

import voxfox_core.colorscheme as cs

MINT = {"Mint-Y-Aqua", "Mint-Y-Dark-Aqua", "Mint-Y", "Mint-Y-Dark"}
YARU = {"Yaru", "Yaru-dark"}


def has(names):
    return lambda n: n in names


def test_mint_light_desktop_can_go_dark_and_back():
    assert cs.choose_theme("dark", "Mint-Y-Aqua", False, has(MINT), "Default") == \
        ("Mint-Y-Dark-Aqua", True)
    assert cs.choose_theme("light", "Mint-Y-Aqua", False, has(MINT), "Default") == \
        ("Mint-Y-Aqua", False)


def test_mint_dark_desktop_can_go_light():
    assert cs.choose_theme("light", "Mint-Y-Dark-Aqua", True, has(MINT), "Default") == \
        ("Mint-Y-Aqua", False)
    assert cs.choose_theme("light", "Mint-Y-Dark", False, has(MINT), "Default") == \
        ("Mint-Y", False)


def test_yaru_style_names():
    assert cs.choose_theme("dark", "Yaru", False, has(YARU), "Default") == ("Yaru-dark", True)
    assert cs.choose_theme("light", "Yaru-dark", False, has(YARU), "Default") == ("Yaru", False)


def test_gtks_own_theme_uses_its_built_in_dark_variant():
    assert cs.choose_theme("dark", "Default", False, has(set()), "Default") == ("Default", True)
    assert cs.choose_theme("light", "Default", True, has(set()), "Default") == ("Default", False)


def test_a_dark_theme_without_light_sibling_falls_back_to_gtks_own():
    assert cs.choose_theme("light", "Some-Dark", True, has(set()), "Default") == \
        ("Default", False)


def test_system_puts_back_what_the_desktop_had():
    assert cs.choose_theme("system", "Mint-Y-Dark-Aqua", True, has(MINT), "Default") == \
        ("Mint-Y-Dark-Aqua", True)


def test_only_themes_with_gtk4_styling_count(tmp_path):
    (tmp_path / "Good" / "gtk-4.0").mkdir(parents=True)
    (tmp_path / "Gtk3Only" / "gtk-3.0").mkdir(parents=True)
    assert cs.gtk4_theme_exists("Good", [str(tmp_path)])
    assert not cs.gtk4_theme_exists("Gtk3Only", [str(tmp_path)])
    assert not cs.gtk4_theme_exists("", [str(tmp_path)])


def test_state_keeps_only_known_schemes(tmp_path, monkeypatch):
    import json
    import voxfox_core.common as common
    import voxfox_core.state as state
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"color_scheme": "purple"}))
    monkeypatch.setattr(common, "STATE_FILE", str(p))
    monkeypatch.setattr(state, "STATE_FILE", str(p))
    assert state.load_state()["color_scheme"] == "system"
    p.write_text(json.dumps({"color_scheme": "dark"}))
    assert state.load_state()["color_scheme"] == "dark"

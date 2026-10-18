"""Tests for voxfox_core.state: reconcile_toolbar_layout (a pure function
with no GTK involvement despite being about toolbar buttons) and
load_state's handling of an unreadable settings file.
"""

import json
import os

import voxfox_core.common as common
import voxfox_core.state as state


# ── reconcile_toolbar_layout ─────────────────────────────────────────────────

def test_reconcile_keeps_stored_order_and_visibility():
    layout = {"buttons": [{"id": "b", "visible": False},
                          {"id": "a", "visible": True}]}
    result = state.reconcile_toolbar_layout(layout, ["a", "b"])
    assert [b["id"] for b in result["buttons"]] == ["b", "a"]
    assert result["buttons"][0]["visible"] is False


def test_reconcile_drops_buttons_that_no_longer_exist():
    layout = {"buttons": [{"id": "removed-in-update", "visible": True},
                          {"id": "a", "visible": True}]}
    result = state.reconcile_toolbar_layout(layout, ["a"])
    assert [b["id"] for b in result["buttons"]] == ["a"]


def test_reconcile_appends_new_buttons_at_the_end():
    layout = {"buttons": [{"id": "a", "visible": True}]}
    result = state.reconcile_toolbar_layout(layout, ["a", "new-button"])
    assert [b["id"] for b in result["buttons"]] == ["a", "new-button"]


def test_reconcile_new_button_in_default_hidden_starts_invisible():
    layout = {"buttons": [{"id": "a", "visible": True}]}
    result = state.reconcile_toolbar_layout(
        layout, ["a", "optional"], default_hidden=("optional",))
    optional = next(b for b in result["buttons"] if b["id"] == "optional")
    assert optional["visible"] is False


def test_reconcile_ignores_duplicate_ids_in_stored_layout():
    layout = {"buttons": [{"id": "a", "visible": True},
                          {"id": "a", "visible": False}]}
    result = state.reconcile_toolbar_layout(layout, ["a"])
    assert len(result["buttons"]) == 1


def test_reconcile_ignores_malformed_entries():
    layout = {"buttons": ["not-a-dict", {"id": "a", "visible": True}]}
    result = state.reconcile_toolbar_layout(layout, ["a"])
    assert [b["id"] for b in result["buttons"]] == ["a"]


def test_reconcile_with_no_stored_layout_uses_defaults():
    result = state.reconcile_toolbar_layout(None, ["a", "b"])
    assert [b["id"] for b in result["buttons"]] == ["a", "b"]
    assert all(b["visible"] for b in result["buttons"])


def test_reconcile_never_mutates_its_input():
    layout = {"buttons": [{"id": "a", "visible": True}]}
    original = json.dumps(layout)
    state.reconcile_toolbar_layout(layout, ["a", "b"])
    assert json.dumps(layout) == original


# ── load_state error handling ────────────────────────────────────────────────

def test_load_state_preserves_a_corrupt_file_and_falls_back(tmp_path, monkeypatch):
    """Regression: a corrupt/unreadable settings file used to be silently
    discarded on the very next save. Now the broken file is renamed for
    inspection and the failure is logged, instead of vanishing."""
    p = tmp_path / "state.json"
    p.write_text("{dit is geen geldige json")
    monkeypatch.setattr(common, "STATE_FILE", str(p))
    monkeypatch.setattr(state, "STATE_FILE", str(p))

    s = state.load_state()

    assert isinstance(s, dict)
    assert "slot1" in s
    bad = str(p) + ".bad"
    assert os.path.isfile(bad)
    assert open(bad).read() == "{dit is geen geldige json"
    assert not os.path.isfile(str(p))


def test_load_state_recovers_after_the_bad_file_is_handled(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    p.write_text("not json at all")
    monkeypatch.setattr(common, "STATE_FILE", str(p))
    monkeypatch.setattr(state, "STATE_FILE", str(p))

    s = state.load_state()
    state.save_state(s)
    s2 = state.load_state()
    assert s2.get("slot1") == s.get("slot1")


def test_load_state_rejects_a_non_object_root(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    p.write_text('["dit is een lijst"]')
    monkeypatch.setattr(common, "STATE_FILE", str(p))
    monkeypatch.setattr(state, "STATE_FILE", str(p))

    s = state.load_state()
    assert isinstance(s, dict)
    assert os.path.isfile(str(p) + ".bad")

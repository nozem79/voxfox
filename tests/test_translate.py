"""Tests for voxfox_core.translate: the URL scheme guard added during code
review (bug 6) and the lambda-deferred translation fix for SUGGESTED_MODELS
(bug 3, the notes that used to be frozen in English forever).
"""

import voxfox_core as vf
import voxfox_core.translate as translate


# ── bug 6: URL scheme validation ──────────────────────────────────────────

def test_bad_url_scheme_rejects_non_http():
    assert translate._bad_url_scheme("file:///etc/passwd") is not None
    assert translate._bad_url_scheme("ftp://example.com") is not None


def test_bad_url_scheme_accepts_http_and_https():
    assert translate._bad_url_scheme("http://localhost:11434") is None
    assert translate._bad_url_scheme("https://api.example.com") is None


def test_bad_url_scheme_accepts_empty_url_via_default():
    # An empty/missing URL falls back to DEFAULT_TRANSLATE's http:// address.
    assert translate._bad_url_scheme("") is None
    assert translate._bad_url_scheme(None) is None


def test_translate_text_rejects_bad_scheme_before_any_network_call():
    result, err = translate.translate_text(
        "hallo", {"url": "file:///etc/passwd"})
    assert result is None
    assert "scheme" in err.lower()


def test_list_models_rejects_bad_scheme():
    ids, err = translate.list_models({"url": "ftp://example.com"})
    assert ids == []
    assert err is not None


def test_pull_model_rejects_bad_scheme_before_building_the_request():
    """Regression-relevant: pull_model builds its request object before its
    own try block, so a scheme check added in the wrong place would raise
    unhandled instead of returning (False, message) like the rest of the
    module's public functions."""
    ok, msg = translate.pull_model("model", {"url": "javascript:alert(1)"})
    assert ok is False
    assert "scheme" in msg.lower()


# ── bug 3: SUGGESTED_MODELS translation timing ────────────────────────────

def test_suggested_models_notes_are_callables_not_frozen_strings():
    """Each note is a lambda, evaluated at display time -- not a plain
    string frozen to whatever the UI language was at import time."""
    for model in translate.SUGGESTED_MODELS:
        assert callable(model["note"])
        assert isinstance(model["note"](), str)


def test_suggested_models_notes_follow_the_current_language():
    note_key = translate.SUGGESTED_MODELS[0]["note"]()
    original_lang = vf.app.lang
    try:
        vf.app.translations["--test--"] = {note_key: "VERTAALD"}
        vf.app.lang = "--test--"
        assert translate.SUGGESTED_MODELS[0]["note"]() == "VERTAALD"
    finally:
        vf.app.lang = original_lang
        vf.app.translations.pop("--test--", None)

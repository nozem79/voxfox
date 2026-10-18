"""Tests for voxfox_core.webread: the URL scheme guard on the three
user-configured Ollama entry points (bug 6).
"""

import voxfox_core.webread as webread


def test_check_ollama_url_rejects_bad_scheme():
    import pytest
    with pytest.raises(ValueError):
        webread._check_ollama_url("file:///etc/passwd")


def test_check_ollama_url_accepts_http():
    webread._check_ollama_url("http://localhost:11434")  # must not raise


def test_ollama_generate_rejects_bad_scheme():
    import pytest
    with pytest.raises(ValueError):
        webread._ollama_generate("gopher://example.com", "model", "prompt")


def test_ollama_list_models_rejects_bad_scheme():
    assert webread.ollama_list_models(url="ftp://example.com") is None


def test_ollama_refine_rejects_bad_scheme_via_broad_except():
    """ollama_refine wraps everything in try/except Exception and returns
    None on failure -- the scheme check must be caught there too, not
    propagate as an unhandled ValueError."""
    result = webread.ollama_refine("tekst", url="javascript:alert(1)")
    assert result is None

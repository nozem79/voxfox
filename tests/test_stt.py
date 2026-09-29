"""Tests for voxfox_core.stt: the URL scheme guard on the remote Whisper
endpoint (bug 6), and the multi-location model cache added to fix Whisper
models being unreachable on systems (like FoxOS) that point HF_HOME at a
read-only system folder.
"""

import os

import voxfox_core.stt as stt


def test_transcribe_remote_rejects_bad_scheme():
    text, err = stt.transcribe_remote(
        "/tmp/does-not-matter.wav", "file:///etc/passwd", "", "whisper-1")
    assert text == ""
    assert "scheme" in err.lower()


def test_transcribe_remote_rejects_empty_url():
    text, err = stt.transcribe_remote("/tmp/x.wav", "", "", "whisper-1")
    assert text == ""
    assert "not set" in err.lower()


# ── model cache: read from configured + user location, write to whichever
#    is writable ───────────────────────────────────────────────────────────

def test_writable_hub_cache_prefers_configured_location(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "configured"))
    assert stt._writable_hub_cache() == os.path.join(
        str(tmp_path / "configured"), "hub")


def test_writable_hub_cache_falls_back_when_configured_is_readonly(
        tmp_path, monkeypatch):
    """The FoxOS scenario: HF_HOME points at a system folder the user
    cannot write to. Downloads must land in the user's own cache instead
    of failing outright."""
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    monkeypatch.setenv("HF_HOME", str(readonly))
    real_access = os.access
    monkeypatch.setattr(
        os, "access",
        lambda p, m: False if str(p).startswith(str(readonly)) else real_access(p, m))
    result = stt._writable_hub_cache()
    assert not result.startswith(str(readonly))
    assert result == stt._user_hub_cache()


def test_cached_hub_for_finds_a_preinstalled_model(tmp_path, monkeypatch):
    """A model a distribution ships under a system HF_HOME must still be
    found, even though downloads would go elsewhere."""
    system_dir = tmp_path / "system"
    monkeypatch.setenv("HF_HOME", str(system_dir))
    snap = system_dir / "hub" / stt._repo_name("tiny") / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_text("x")

    assert stt._whisper_model_is_cached("tiny") is True
    assert stt._cached_hub_for("tiny") == str(system_dir / "hub")


def test_whisper_model_not_cached_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert stt._whisper_model_is_cached("does-not-exist") is False

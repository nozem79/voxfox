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

    assert stt.whisper_model_is_cached("tiny") is True
    assert stt._cached_hub_for("tiny") == str(system_dir / "hub")


def test_whisper_model_not_cached_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert stt.whisper_model_is_cached("does-not-exist") is False


# ── audio handed to Whisper as an array, not a path ───────────────────────
# PyAV 19 removed av.open(metadata_errors=...), which faster-whisper 1.2.1
# still passes when it decodes a file path; a fresh `pip install
# faster-whisper` therefore broke dictation with "open() got an unexpected
# keyword argument 'metadata_errors'". An array makes faster-whisper skip PyAV.

import sys
import wave

import pytest


def _write_wav(path, frames=b"\x00\x00", channels=1, width=2, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)
    return str(path)


def test_wav_as_float32_reads_a_16k_mono_wav(tmp_path):
    np = pytest.importorskip("numpy")
    # silence, +half scale, -full scale, +almost full scale
    frames = np.array([0, 16384, -32768, 32767], dtype="<i2").tobytes()
    arr = stt.wav_as_float32(_write_wav(tmp_path / "a.wav", frames))
    assert arr.dtype == np.float32
    assert arr.tolist() == pytest.approx([0.0, 0.5, -1.0, 32767 / 32768])


@pytest.mark.parametrize("channels,width,rate", [
    (2, 2, 16000),      # stereo
    (1, 2, 44100),      # wrong sample rate
    (1, 1, 16000),      # 8-bit
])
def test_wav_as_float32_declines_other_formats(tmp_path, channels, width, rate):
    pytest.importorskip("numpy")
    frames = b"\x00" * (channels * width * 4)
    path = _write_wav(tmp_path / "b.wav", frames, channels, width, rate)
    assert stt.wav_as_float32(path) is None


def test_wav_as_float32_declines_a_file_that_is_not_a_wav(tmp_path):
    pytest.importorskip("numpy")
    junk = tmp_path / "c.wav"
    junk.write_bytes(b"this is not a wav file")
    assert stt.wav_as_float32(str(junk)) is None
    assert stt.wav_as_float32(str(tmp_path / "missing.wav")) is None


def test_wav_as_float32_without_numpy_falls_back(tmp_path, monkeypatch):
    path = _write_wav(tmp_path / "d.wav")
    monkeypatch.setitem(sys.modules, "numpy", None)   # `import numpy` now fails
    assert stt.wav_as_float32(path) is None


class _FakeModel:
    def __init__(self, error=None):
        self.error, self.seen = error, None

    def transcribe(self, audio, **kwargs):
        if self.error:
            raise self.error
        self.seen = audio
        return [], None


def test_local_transcribe_gives_whisper_an_array(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    model = _FakeModel()
    monkeypatch.setattr(stt, "load_whisper_model", lambda *a, **k: (model, None))
    path = _write_wav(tmp_path / "e.wav", b"\x01\x00" * 100)
    text, err = stt._transcribe_local(path, "small")
    assert err is None
    assert isinstance(model.seen, np.ndarray)       # not the path: no PyAV


def test_local_transcribe_falls_back_to_the_path_for_other_wavs(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    model = _FakeModel()
    monkeypatch.setattr(stt, "load_whisper_model", lambda *a, **k: (model, None))
    path = _write_wav(tmp_path / "f.wav", b"\x00" * 16, channels=2)
    stt._transcribe_local(path, "small")
    assert model.seen == path


def test_av_too_new_error_names_the_fix(tmp_path, monkeypatch):
    err = TypeError("open() got an unexpected keyword argument 'metadata_errors'")
    monkeypatch.setattr(stt, "load_whisper_model",
                        lambda *a, **k: (_FakeModel(error=err), None))
    path = _write_wav(tmp_path / "g.wav", b"\x00" * 16, channels=2)  # takes the path route
    text, msg = stt._transcribe_local(path, "small")
    assert text == "" and "metadata_errors" in msg and 'av<19' in msg

"""Parakeet as second dictation model, and the Myna helpers (6.3)."""
import os

import voxfox_core as vf
from voxfox_core import parakeet as pk
from voxfox_core import stt


def _fake_model(path):
    os.makedirs(path, exist_ok=True)
    for name in ("encoder-model.int8.onnx", "decoder_joint-model.int8.onnx",
                 "vocab.txt", "config.json"):
        with open(os.path.join(path, name), "w") as f:
            f.write("x")


def test_parakeet_in_the_model_list():
    assert vf.PARAKEET_MODEL in vf.WHISPER_MODELS
    assert vf.is_parakeet("parakeet-v3") and not vf.is_parakeet("small")


def test_languages():
    assert vf.parakeet_supports("nl") and vf.parakeet_supports("uk")
    assert vf.parakeet_supports(None)            # unknown: Parakeet detects it
    assert not vf.parakeet_supports("ja")
    assert len(pk.PARAKEET_LANGS) == 25


def test_model_dir_needs_every_file(tmp_path, monkeypatch):
    d = tmp_path / "models" / pk.PARAKEET_DIR_NAME
    monkeypatch.setattr(pk, "_model_dirs", lambda: [str(d)])
    assert pk.parakeet_model_dir() is None
    _fake_model(str(d))
    os.unlink(d / "vocab.txt")
    assert pk.parakeet_model_dir() is None       # incomplete is no model
    (d / "vocab.txt").write_text("x")
    assert pk.parakeet_model_dir() == str(d)
    # the "_int8" spelling counts too
    os.rename(d / "encoder-model.int8.onnx", d / "encoder-model_int8.onnx")
    assert pk.parakeet_is_cached()


def test_download_goes_through_a_part_folder(tmp_path, monkeypatch):
    import sys
    import types
    final = tmp_path / "m" / pk.PARAKEET_DIR_NAME
    monkeypatch.setattr(pk, "_model_dirs", lambda: [str(final)])
    seen = {}

    def fake_snapshot(repo, local_dir, allow_patterns):
        seen["repo"], seen["dir"] = repo, local_dir
        assert os.environ.get("HF_HUB_OFFLINE") == "0"
        _fake_model(local_dir)
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(snapshot_download=fake_snapshot))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    fracs = []
    path, err = pk.download_parakeet(frac_cb=lambda f, _l=None: fracs.append(f))
    assert err is None and path == str(final)
    assert seen["repo"] == pk.PARAKEET_REPO and seen["dir"].endswith(".part")
    assert not os.path.exists(str(final) + ".part")
    assert fracs[-1] == 1.0
    assert os.environ["HF_HUB_OFFLINE"] == "1"   # put back


def test_failed_download_leaves_no_model(tmp_path, monkeypatch):
    import sys
    import types
    final = tmp_path / "m" / pk.PARAKEET_DIR_NAME
    monkeypatch.setattr(pk, "_model_dirs", lambda: [str(final)])

    def broken(repo, local_dir, allow_patterns):
        raise OSError("no network")
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(snapshot_download=broken))
    path, err = pk.download_parakeet()
    assert path is None and "no network" in err
    assert not pk.parakeet_is_cached()


def test_transcribe_routes_to_parakeet(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pk, "transcribe_parakeet",
                        lambda audio, p=None, f=None: (calls.append("pk"), ("hallo", None))[1])
    monkeypatch.setattr(stt, "load_whisper_model",
                        lambda *a, **k: (calls.append("whisper"), (None, "no"))[1])
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")
    assert stt._transcribe_local(str(wav), "parakeet-v3", "nl") == ("hallo", None)
    assert calls == ["pk"]


def test_unknown_language_falls_back_to_whisper(monkeypatch, tmp_path):
    used = []
    monkeypatch.setattr(stt, "faster_whisper_available", lambda: True)
    monkeypatch.setattr(pk, "transcribe_parakeet",
                        lambda *a, **k: (used.append("pk"), ("", None))[1])
    monkeypatch.setattr(stt, "load_whisper_model",
                        lambda name, *a, **k: (used.append(name), (None, "stop"))[1])
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")
    stt._transcribe_local(str(wav), "parakeet-v3", "ja")
    assert used == ["small"]


def test_myna_helpers():
    assert vf.myna_is_busy("recording") and vf.myna_is_busy("loading")
    assert not vf.myna_is_busy("idle") and not vf.myna_is_busy("notice")
    assert not vf.myna_is_busy("something-new")      # unknown states: ignore
    assert vf.myna_status_text("recording")
    assert vf.myna_status_text("idle") == "" == vf.myna_status_text("new")
    assert vf.use_myna({"engine": "myna"}, True)
    assert not vf.use_myna({"engine": "myna"}, False)
    assert not vf.use_myna({"engine": "voxfox"}, True)
    assert not vf.use_myna({}, True)

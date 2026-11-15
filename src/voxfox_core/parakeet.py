#!/usr/bin/env python3
# Copyright (C) 2025 - Daniël Vos
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""voxfox_core.parakeet — NVIDIA Parakeet as a second dictation model (6.3).

Parakeet-TDT-0.6B-v3 knows 25 European languages. For Dutch it makes a
few more mistakes than Whisper large-v3 (FLEURS word error rate about
7.5 % against 5.5 %) but far fewer than Whisper small (18.5 %), and on a
normal processor it is many times faster than either large model. So it
is the better choice for people without an NVIDIA graphics card.

It runs through onnx-asr (ONNX Runtime), int8, on the CPU. The model is
downloaded once into VoxFox's own data folder, not the Hugging Face
cache, so it is easy to find and to remove.
"""

import os
import threading

from .common import DATA_DIR, log

PARAKEET_MODEL = "parakeet-v3"                 # the name in VoxFox's model list
PARAKEET_ONNX_NAME = "nemo-parakeet-tdt-0.6b-v3"
PARAKEET_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
PARAKEET_QUANT = "int8"
PARAKEET_SIZE_MB = 670                         # int8 encoder + decoder + vocab
PARAKEET_DIR_NAME = "parakeet-tdt-0.6b-v3-int8"

# What the model card lists (ISO 639-1). Other languages go to Whisper.
PARAKEET_LANGS = frozenset((
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
    "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru",
    "uk"))

# Files of the int8 model; "?" stands for "." or "_" as the repository
# spells them (same patterns onnx-asr itself uses).
_FILES = ("encoder-model?int8.onnx", "decoder_joint-model?int8.onnx",
          "vocab.txt", "config.json")
# Optional extra ("external data") files next to an .onnx file.
_EXTRA = ("encoder-model?int8.onnx?data", "decoder_joint-model?int8.onnx?data")


def is_parakeet(model_name):
    return model_name == PARAKEET_MODEL


def parakeet_supports(lang_code):
    """True when Parakeet knows this language, or when the language is
    not known (None: Parakeet detects it itself)."""
    return lang_code is None or lang_code in PARAKEET_LANGS


def parakeet_available():
    """Whether onnx-asr and ONNX Runtime can be imported, without
    importing them."""
    import importlib.util
    try:
        return (importlib.util.find_spec("onnx_asr") is not None
                and importlib.util.find_spec("onnxruntime") is not None)
    except Exception:
        return False


def _model_dirs():
    """Where the model may be, most specific first: the user's own copy,
    then one a distribution ships (FoxOS)."""
    return [os.path.join(DATA_DIR, "models", PARAKEET_DIR_NAME),
            os.path.join("/usr/share/voxfox/models", PARAKEET_DIR_NAME)]


def _complete(path):
    """True when `path` holds every file the int8 model needs."""
    import fnmatch
    try:
        names = os.listdir(path)
    except OSError:
        return False
    return all(any(fnmatch.fnmatch(n, pat) for n in names)
               for pat in _FILES if pat != "config.json")


def parakeet_model_dir():
    """The folder with a complete copy of the model, or None."""
    for d in _model_dirs():
        if _complete(d):
            return d
    return None


def parakeet_is_cached():
    return parakeet_model_dir() is not None


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def download_parakeet(frac_cb=None):
    """Download the model into the user's data folder. Returns (path, error).

    It goes into a ".part" folder first and is renamed when complete, so
    an interrupted download is never mistaken for a model."""
    have = parakeet_model_dir()
    if have:
        return have, None
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return None, "huggingface_hub is not installed"
    final = _model_dirs()[0]
    part = final + ".part"
    os.makedirs(part, exist_ok=True)
    stop = threading.Event()
    if frac_cb:
        def poll():
            exp = PARAKEET_SIZE_MB * 1024 * 1024
            while not stop.is_set():
                try:
                    frac_cb(min(_dir_size(part) / exp, 0.99), PARAKEET_MODEL)
                except Exception:
                    pass
                stop.wait(0.5)
        threading.Thread(target=poll, daemon=True).start()
    # Hugging Face honours HF_HUB_OFFLINE from the environment (FoxOS sets
    # it); this download is asked for, so it is lifted for this call only.
    prev = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "0"
    try:
        snapshot_download(PARAKEET_REPO, local_dir=part,
                          allow_patterns=list(_FILES + _EXTRA))
        if not _complete(part):
            return None, "download incomplete"
        if os.path.isdir(final):
            import shutil
            shutil.rmtree(final, ignore_errors=True)
        os.replace(part, final)
        if frac_cb:
            frac_cb(1.0, PARAKEET_MODEL)
        return final, None
    except Exception as e:
        log.warning(f"Parakeet download failed: {e}")
        return None, f"Download failed: {e}"
    finally:
        stop.set()
        if prev is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev


class _ParakeetState:
    """The loaded model. One instance, `_parakeet`."""

    def __init__(self):
        self.model = None
        self.lock = threading.Lock()


_parakeet = _ParakeetState()


def _providers():
    """ONNX Runtime providers: CUDA first when onnxruntime-gpu is there,
    else the CPU. The normal pip install is CPU-only, which is the point
    of this model."""
    try:
        import onnxruntime as rt
        have = rt.get_available_providers()
    except Exception:
        return ["CPUExecutionProvider"]
    out = [p for p in ("CUDAExecutionProvider",) if p in have]
    return out + ["CPUExecutionProvider"]


def load_parakeet(progress_cb=None, frac_cb=None):
    """Load (downloading first if needed) the model. Returns (model, error)."""
    with _parakeet.lock:
        if _parakeet.model is not None:
            return _parakeet.model, None
        if not parakeet_available():
            return None, ("Parakeet is not installed. Use the Install button "
                          "in Settings, Dictation.")
        path = parakeet_model_dir()
        if path is None:
            if progress_cb:
                progress_cb(f"Downloading {PARAKEET_MODEL} "
                            f"({PARAKEET_SIZE_MB} MB) — first time only...")
            path, err = download_parakeet(frac_cb)
            if err:
                return None, err
        if progress_cb:
            progress_cb(f"Loading model: {PARAKEET_MODEL}...")
        try:
            import onnx_asr
            model = onnx_asr.load_model(PARAKEET_ONNX_NAME, path,
                                        quantization=PARAKEET_QUANT,
                                        providers=_providers())
        except Exception as e:
            log.warning(f"Parakeet load failed: {e}")
            return None, f"Could not load model: {e}"
        _parakeet.model = model
        return model, None


def release_parakeet():
    """Forget the loaded model (its memory is freed by Python)."""
    with _parakeet.lock:
        _parakeet.model = None


def transcribe_parakeet(audio, progress_cb=None, frac_cb=None):
    """Recognise `audio`: a float32 16 kHz mono numpy array or a WAV path.
    Returns (text, error)."""
    model, err = load_parakeet(progress_cb, frac_cb)
    if model is None:
        return "", err
    try:
        text = model.recognize(audio, sample_rate=16000) \
            if not isinstance(audio, str) else model.recognize(audio)
        return (text or "").strip(), None
    except Exception as e:
        return "", f"Transcribe error: {e}"


__all__ = [
    "PARAKEET_MODEL", "PARAKEET_LANGS", "PARAKEET_SIZE_MB",
    "is_parakeet", "parakeet_supports", "parakeet_available",
    "parakeet_model_dir", "parakeet_is_cached", "download_parakeet",
    "load_parakeet", "release_parakeet", "transcribe_parakeet",
]

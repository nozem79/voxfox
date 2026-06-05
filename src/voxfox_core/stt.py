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


"""voxfox_core.stt — Speech-to-text: Whisper model loading, recording, transcription."""

import json, os, subprocess, threading, time, urllib.error, urllib.request
from .common import _, log


# Whisper config
WHISPER_MODELS    = ["tiny", "base", "small", "medium", "large-v3"]
WHISPER_SAMPLE_RATE = 16000
WHISPER_TYPE_LIMIT  = 200          # chars: <= type, > paste via clipboard
WHISPER_MAX_SECONDS = 120          # safety cap on recording length


# ── Whisper (speech-to-text) ──────────────────────────────────────────────────
# Maps Piper-style language names to Whisper ISO codes. Fallback: auto-detect.
_WHISPER_LANG_MAP = {
    "Dutch": "nl", "Flemish": "nl", "Nederlands": "nl",
    "English": "en", "German": "de", "French": "fr", "Spanish": "es",
    "Italian": "it", "Portuguese": "pt", "Polish": "pl", "Russian": "ru",
    "Turkish": "tr", "Arabic": "ar", "Chinese": "zh", "Japanese": "ja",
    "Korean": "ko", "Catalan": "ca", "Czech": "cs", "Danish": "da",
    "Greek": "el", "Finnish": "fi", "Hungarian": "hu", "Norwegian": "no",
    "Romanian": "ro", "Slovak": "sk", "Swedish": "sv", "Ukrainian": "uk",
}

_whisper_model      = None
_whisper_model_name = None
_whisper_model_device = None
_whisper_lock       = threading.Lock()


def _cuda_available():
    """True if an NVIDIA GPU with a usable CUDA runtime is available to
    ctranslate2 (the engine under faster-whisper). Returns False quietly when
    ctranslate2 was built without CUDA or no GPU/driver is present."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _gpu_compute_cap():
    """Highest NVIDIA GPU compute capability as a float (e.g. 6.1 for a Tesla
    P40, 8.6 for an RTX 3090), or None if it can't be determined."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5)
        caps = [float(x.strip()) for x in r.stdout.splitlines() if x.strip()]
        return max(caps) if caps else None
    except Exception:
        return None


def _cuda_compute_candidates():
    """Compute types to try on the GPU, best first. float16 is only efficient
    on Volta and newer (compute capability >= 7.0); on Pascal cards like the
    Tesla P40 (6.1) it is crippled or crashes, so int8 leads there. Each is
    tried in turn and we fall back to CPU if none load."""
    cap = _gpu_compute_cap()
    if cap is not None and cap < 7.0:
        return ["int8", "float32"]          # Pascal and older
    return ["float16", "int8", "float32"]   # Volta+ (or unknown → try fp16)
_record_proc        = None


def _whisper_lang_code(piper_lang_name):
    """Translate a Piper language name to a Whisper ISO code, or None."""
    if not piper_lang_name:
        return None
    return _WHISPER_LANG_MAP.get(piper_lang_name)


# Approximate on-disk sizes of the faster-whisper models (MB), used to turn the
# growing cache directory into a download percentage.
WHISPER_SIZES_MB = {
    "tiny": 75, "tiny.en": 75, "base": 145, "base.en": 145,
    "small": 484, "small.en": 484, "medium": 1530, "medium.en": 1530,
    "large-v1": 3100, "large-v2": 3100, "large-v3": 3100,
}


def _hf_model_dir(name):
    return os.path.expanduser(
        f"~/.cache/huggingface/hub/models--Systran--faster-whisper-{name}")


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _whisper_model_is_cached(name):
    """Check if a faster-whisper model is already downloaded locally."""
    # HuggingFace stores models under ~/.cache/huggingface/hub/models--Systran--faster-whisper-<name>
    cache = os.path.expanduser("~/.cache/huggingface/hub")
    repo  = f"models--Systran--faster-whisper-{name}"
    path  = os.path.join(cache, repo, "snapshots")
    if not os.path.isdir(path):
        return False
    # Snapshots dir should contain at least one revision with model.bin
    try:
        for rev in os.listdir(path):
            if os.path.isfile(os.path.join(path, rev, "model.bin")):
                return True
    except OSError:
        pass
    return False


def load_whisper_model(name, progress_cb=None, device="auto", frac_cb=None):
    """Load a faster-whisper model. Cached across calls when name+device match.

    device: "auto" picks CUDA when an NVIDIA GPU is detected, else CPU.
    "cuda"/"cpu" force a choice. CUDA init that fails (e.g. missing cuDNN)
    falls back to CPU rather than erroring out.
    frac_cb(fraction, label): optional download-progress callback (0.0-1.0)."""
    global _whisper_model, _whisper_model_name, _whisper_model_device
    with _whisper_lock:
        if device == "auto":
            device = "cuda" if _cuda_available() else "cpu"

        if (_whisper_model is not None and _whisper_model_name == name
                and _whisper_model_device == device):
            return _whisper_model, None
        cached = _whisper_model_is_cached(name)
        if progress_cb:
            where = "GPU" if device == "cuda" else "CPU"
            if cached:
                progress_cb(f"Loading model: {name} ({where})...")
            else:
                sizes = {"tiny": "75 MB", "base": "140 MB", "small": "460 MB",
                         "medium": "1.5 GB", "large-v3": "3 GB"}
                size = sizes.get(name, "")
                progress_cb(f"Downloading {name} ({size}) — first time only...")
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return None, ("faster-whisper not installed. "
                          "Run: pip install --user faster-whisper")

        # First-time download: poll the cache directory growing toward the
        # model's expected size and report it as a fraction. Self-contained, so
        # it doesn't depend on huggingface_hub internals.
        stop_poll = threading.Event()
        if frac_cb and not cached:
            def _poll():
                exp = WHISPER_SIZES_MB.get(name, 500) * 1024 * 1024
                d = _hf_model_dir(name)
                while not stop_poll.is_set():
                    try:
                        frac_cb(min(_dir_size(d) / exp, 0.99), name)
                    except Exception:
                        pass
                    stop_poll.wait(0.5)
            threading.Thread(target=_poll, daemon=True).start()

        # Build the ordered list of (device, compute_type) attempts. On the GPU
        # we try the architecture-appropriate compute types first, then fall
        # back to the CPU so a missing cuDNN / unsupported card never hard-fails.
        if device == "cuda":
            attempts = [("cuda", c) for c in _cuda_compute_candidates()]
            attempts.append(("cpu", "int8"))
        else:
            attempts = [("cpu", "int8")]

        try:
            last_err = None
            for dev, comp in attempts:
                try:
                    model = WhisperModel(name, device=dev, compute_type=comp)
                    if dev != device and progress_cb:
                        progress_cb("GPU unavailable — using CPU...")
                    _whisper_model        = model
                    _whisper_model_name   = name
                    _whisper_model_device = dev
                    if frac_cb and not cached:
                        frac_cb(1.0, name)
                    return model, None
                except Exception as e:
                    last_err = e
                    log.warning(f"Whisper load failed on {dev}/{comp}: {e}")
            return None, f"Could not load model: {last_err}"
        finally:
            stop_poll.set()


def list_microphones():
    """Return [(id, label), ...] of available recording inputs.

    The strategy is intentionally lenient: we use `pactl list short sources`
    (the simpler API) and only skip `.monitor` sources (those record speaker
    output). Anything else is shown as a candidate input. If `pactl list
    sources` (the verbose API) is reachable we also enrich the labels with
    each source's Description for readability.

    Earlier versions filtered by `media.class = Audio/Source`, which sounds
    right but excludes valid mics on systems where that property isn't
    populated (older PulseAudio, some PipeWire configs). We learned the
    hard way that this leaves users with only "Default".

    First entry is always ("", _("Default")) so the user can keep system default.
    """
    results = [("", _("Default"))]
    seen_names = set()

    # First pass: collect descriptions from the verbose listing.
    descriptions = {}
    try:
        r = subprocess.run(["pactl", "list", "sources"],
                           capture_output=True, text=True, timeout=2.0)
        if r.returncode == 0:
            current_name = None
            for raw in r.stdout.splitlines():
                line = raw.strip()
                if line.startswith("Name: "):
                    current_name = line[6:].strip()
                elif line.startswith("Description: ") and current_name:
                    descriptions[current_name] = line[13:].strip()
    except Exception as e:
        log.debug(f"pactl list sources (verbose) failed: {e}")

    # Second pass: the simple, well-known listing. This is the same call your
    # earlier working code used, with only `.monitor` filtered out.
    try:
        r = subprocess.run(["pactl", "list", "short", "sources"],
                           capture_output=True, text=True, timeout=2.0)
        if r.returncode != 0:
            return results
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            if not name or name.endswith(".monitor"):
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
            label = descriptions.get(name, name)
            if len(label) > 50:
                label = label[:47] + "..."
            results.append((name, label))
    except Exception as e:
        log.debug(f"list_microphones failed: {e}")
    return results


def record_audio(wav_path, mic_id="", max_seconds=WHISPER_MAX_SECONDS, stop_evt=None):
    """Record from `mic_id` (or default) to wav_path as 16kHz mono PCM.

    Records until stop_evt is set or max_seconds elapses.
    Returns (ok, message).

    If a specific mic_id is given and recording with it fails (zero bytes
    captured after the user stops), we automatically retry once with the
    system default. This covers the case where the saved mic_id is stale
    after a USB unplug or a PipeWire reshuffle.
    """
    global _record_proc

    def _try_record(use_mic_id):
        # Build commands. Both parecord (--device) and arecord (-D) take mic IDs.
        parecord_cmd = ["parecord", "--rate", str(WHISPER_SAMPLE_RATE),
                        "--channels", "1", "--format", "s16le",
                        "--file-format=wav"]
        if use_mic_id:
            parecord_cmd += ["--device", use_mic_id]
        parecord_cmd.append(wav_path)

        arecord_cmd = ["arecord", "-q", "-r", str(WHISPER_SAMPLE_RATE),
                       "-c", "1", "-f", "S16_LE", "-t", "wav"]
        if use_mic_id:
            arecord_cmd += ["-D", use_mic_id]
        arecord_cmd.append(wav_path)

        # Capture stderr so we can see what went wrong if recording fails.
        proc = None
        used_cmd = None
        for cmd in (parecord_cmd, arecord_cmd):
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
                used_cmd = cmd
                break
            except FileNotFoundError:
                continue
        return proc, used_cmd

    proc, used_cmd = _try_record(mic_id)
    if proc is None:
        return False, "No recorder found (parecord or arecord)"
    _record_proc = proc
    log.debug(f"Recording with: {used_cmd}")

    start = time.monotonic()
    poll  = 0.1
    try:
        while True:
            if proc.poll() is not None:
                break
            elapsed = time.monotonic() - start
            if elapsed > max_seconds:
                break
            if stop_evt is not None and stop_evt.is_set():
                break
            time.sleep(poll)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _record_proc = None

    # Capture any stderr the recorder produced — vital for debugging
    # "why is my mic_id silently producing empty WAVs" issues.
    rc = proc.returncode
    try:
        err_bytes = proc.stderr.read() if proc.stderr else b""
    except Exception:
        err_bytes = b""
    err_text = err_bytes.decode("utf-8", errors="replace").strip()
    if err_text:
        log.warning(f"Recorder stderr: {err_text}")

    file_ok = os.path.isfile(wav_path) and os.path.getsize(wav_path) >= 1000

    # If we used a specific mic_id and got nothing, retry once with default.
    # This automatically recovers from a stale saved mic id (e.g. after a
    # USB unplug or a PipeWire reshuffle of source names).
    if not file_ok and mic_id:
        log.warning(f"Recording with mic_id={mic_id!r} failed; "
                    f"retrying with system default")
        try:
            if os.path.isfile(wav_path):
                os.unlink(wav_path)
        except Exception:
            pass
        proc, used_cmd = _try_record("")
        if proc is None:
            return False, "No recorder found (parecord or arecord)"
        _record_proc = proc
        # Do a short fixed-length capture as a sanity check — the user has
        # already stopped, so we can't ask them to talk again. We give it
        # 1 second to catch any tail audio still buffered.
        time.sleep(1.0)
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _record_proc = None
        file_ok = os.path.isfile(wav_path) and os.path.getsize(wav_path) >= 1000

    if not file_ok:
        return False, ("Recording too short or empty" +
                       (f" — {err_text}" if err_text else ""))
    return True, "ok"


def transcribe_remote(wav_path, url, api_key, model_name, language_hint=None):
    """Send a WAV file to an OpenAI-compatible /audio/transcriptions endpoint.

    Returns (text, error). Compatible with:
      - faster-whisper-server / Speaches
      - whisper.cpp server with --convert
      - OpenAI's hosted Whisper API
      - any other server that implements POST /v1/audio/transcriptions
        with multipart/form-data fields: file, model, language (optional).

    Times out at 60 seconds — long enough for ~2-minute recordings on a
    GPU server, short enough that a hung connection doesn't freeze the UI.
    """
    if not url:
        return "", "Remote URL not set"

    # Normalise: accept "http://host:8000", "http://host:8000/", or
    # "http://host:8000/v1" — all of those should resolve to the
    # transcriptions endpoint. We don't auto-append /v1 because some
    # servers (like whisper.cpp) don't use that prefix at all.
    url = url.rstrip("/")
    endpoint = url + "/audio/transcriptions"

    # Build a multipart/form-data body manually. We avoid `requests` so
    # this works on minimal installs without extra pip packages.
    boundary = "----VoxFoxBoundary" + os.urandom(8).hex()
    crlf = b"\r\n"
    body = []
    try:
        with open(wav_path, "rb") as f:
            audio_data = f.read()
    except Exception as e:
        return "", f"Could not read recording: {e}"

    def _field(name, value):
        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        body.append(b"")
        body.append(value.encode("utf-8") if isinstance(value, str) else value)

    _field("model", model_name or "whisper-1")
    # Send response_format=text so we get plain text back instead of JSON
    # with timestamps. Saves us from JSON parsing and works with every
    # OpenAI-compatible server.
    _field("response_format", "text")
    if language_hint:
        _field("language", language_hint)

    # File field
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="file"; filename="audio.wav"')
    body.append(b"Content-Type: audio/wav")
    body.append(b"")
    body.append(audio_data)
    body.append(f"--{boundary}--".encode())
    body.append(b"")
    payload = crlf.join(body)

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(endpoint, data=payload, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        # Try to surface the server's error body — many implementations
        # return useful text like "model not found: whisper-1".
        try:
            err_body = e.read().decode("utf-8", errors="replace").strip()
        except Exception:
            err_body = ""
        snippet = (": " + err_body[:200]) if err_body else ""
        return "", f"Remote API error {e.code}{snippet}"
    except urllib.error.URLError as e:
        return "", f"Remote API unreachable: {e.reason}"
    except Exception as e:
        return "", f"Remote API error: {e}"

    text = data.decode("utf-8", errors="replace").strip()
    # Some servers return JSON despite response_format=text. Detect and
    # extract the "text" field defensively.
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "text" in obj:
                text = str(obj["text"]).strip()
        except Exception:
            pass
    return text, None


def transcribe(wav_path, model_name, language_hint=None, progress_cb=None,
               whisper_cfg=None, frac_cb=None):
    """Transcribe a WAV file. Returns (text, error).

    Routes between local Whisper and remote API based on whisper_cfg['backend'].
    If whisper_cfg is None, behaves exactly like before (local only) — this
    keeps the function safe to call from anywhere that doesn't know about
    the new config.

    On remote failure, falls back to local Whisper rather than failing the
    whole dictation. The fallback is silent in the return value but the
    progress callback is notified so the status bar shows what happened.
    """
    backend = (whisper_cfg or {}).get("backend", "local")

    if backend == "remote":
        cfg = whisper_cfg or {}
        if progress_cb:
            progress_cb("Transcribing (remote)...")
        text, err = transcribe_remote(
            wav_path,
            url=cfg.get("remote_url", ""),
            api_key=cfg.get("remote_api_key", ""),
            model_name=cfg.get("remote_model", ""),
            language_hint=language_hint,
        )
        if err is None:
            return text, None
        # Remote failed — log and fall through to local. The user sees
        # the local-load message via progress_cb so they know what's
        # happening (no silent degradation).
        log.warning(f"Remote transcription failed, falling back to local: {err}")
        if progress_cb:
            progress_cb(f"Remote failed ({err}) — using local")

    return _transcribe_local(wav_path, model_name, language_hint, progress_cb,
                             device=(whisper_cfg or {}).get("device", "auto"),
                             frac_cb=frac_cb)


def _transcribe_local(wav_path, model_name, language_hint=None,
                      progress_cb=None, device="auto", frac_cb=None):
    """Local Whisper transcription. Extracted from the old transcribe()
    so the routing wrapper above can call it as a fallback."""
    model, err = load_whisper_model(model_name, progress_cb, device=device,
                                    frac_cb=frac_cb)
    if model is None:
        return "", err
    try:
        segments, _info = model.transcribe(
            wav_path,
            language=language_hint,         # None -> auto-detect
            beam_size=1,                    # speed over accuracy
            vad_filter=True,                # drop leading/trailing silence
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, None
    except Exception as e:
        return "", f"Transcribe error: {e}"


__all__ = [
    "WHISPER_MODELS",
    "WHISPER_SAMPLE_RATE",
    "WHISPER_TYPE_LIMIT",
    "WHISPER_MAX_SECONDS",
    "_WHISPER_LANG_MAP",
    "_whisper_model",
    "_whisper_model_name",
    "_whisper_model_device",
    "_whisper_lock",
    "_cuda_available",
    "_gpu_compute_cap",
    "_cuda_compute_candidates",
    "_record_proc",
    "_whisper_lang_code",
    "WHISPER_SIZES_MB",
    "_hf_model_dir",
    "_dir_size",
    "_whisper_model_is_cached",
    "load_whisper_model",
    "list_microphones",
    "record_audio",
    "transcribe_remote",
    "transcribe",
    "_transcribe_local",
]

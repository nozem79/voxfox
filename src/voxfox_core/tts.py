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


"""voxfox_core.tts — Text-to-speech: Piper voices, chunking, the speaking worker."""

import json, os, re, subprocess, tempfile, threading, time, urllib.request
from .common import BASE_URL, CHUNK_SIZE, MAX_TEXT_LEN, PIPER_BIN, PIPER_DIR, VOICES_URL, app, log



# ── Voice data ─────────────────────────────────────────────────────────────────
_voices_cache    = {}
_voices_cache_ts = 0
VOICES_CACHE_TTL = 300  # 5 minutes


def fetch_voices(force=False):
    global _voices_cache, _voices_cache_ts
    now = time.monotonic()
    if not force and _voices_cache and (now - _voices_cache_ts) < VOICES_CACHE_TTL:
        return _voices_cache
    try:
        with urllib.request.urlopen(VOICES_URL, timeout=10) as r:
            _voices_cache    = json.loads(r.read().decode())
            _voices_cache_ts = now
    except Exception as e:
        log.error(f"Could not fetch voice list: {e}")
    return _voices_cache


def get_languages(voices):
    langs = set()
    for info in voices.values():
        name = info.get("language", {}).get("name_english", "")
        if name:
            langs.add(name)
    return sorted(langs)


def get_voices_for_lang(voices, lang):
    return {k: v for k, v in voices.items()
            if v.get("language", {}).get("name_english", "") == lang}


def get_local_voices():
    if not os.path.isdir(PIPER_DIR):
        return set()
    return {f[:-5] for f in os.listdir(PIPER_DIR) if f.endswith(".onnx")}


def download_voice(voice_key, progress_cb=None, cancel_evt=None, frac_cb=None):
    """Download a Piper voice. Returns (ok, message).

    If cancel_evt is set during the download, the partial file is removed
    and (False, 'cancelled') is returned.
    frac_cb(fraction, label): optional per-file download-progress callback.
    """
    voices = fetch_voices()
    if voice_key not in voices:
        return False, f"Voice not found: {voice_key}"
    os.makedirs(PIPER_DIR, exist_ok=True)
    for filename in voices[voice_key].get("files", {}):
        if not (filename.endswith(".onnx") or filename.endswith(".onnx.json")):
            continue
        dest = os.path.join(PIPER_DIR, os.path.basename(filename))
        if os.path.isfile(dest):
            continue
        url = f"{BASE_URL}/{filename}"
        if progress_cb:
            progress_cb(f"Downloading: {os.path.basename(filename)}...")
        if cancel_evt is not None and cancel_evt.is_set():
            return False, "cancelled"

        tmp = dest + ".part"
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    if cancel_evt is not None and cancel_evt.is_set():
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        return False, "cancelled"
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if frac_cb and total:
                        frac_cb(done / total, os.path.basename(filename))
            os.rename(tmp, dest)
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
            return False, str(e)
    return True, "Done"


# ── Audio ──────────────────────────────────────────────────────────────────────
_speak_thread = None
_stop_event   = threading.Event()
_pause_event  = threading.Event()   # set = paused; cleared = playing
_speak_lock   = threading.Lock()

# Read-only progress (for the GUI). Updated by the worker, never written by GUI.
_progress = {"chunk": 0, "total": 0, "text": ""}


def is_speaking():
    """True if a speech thread is actively playing."""
    return _speak_thread is not None and _speak_thread.is_alive()


def is_paused():
    """True if speech is currently paused."""
    return _pause_event.is_set()


def toggle_pause():
    """Toggle the pause state. Returns the new paused state (True/False).
    No-op if nothing is currently speaking."""
    if not is_speaking():
        return False
    if _pause_event.is_set():
        _pause_event.clear()
        return False
    else:
        _pause_event.set()
        return True


def _voice_sample_rate(voice_key):
    """Read the sample rate from a Piper voice's .onnx.json. Default 22050."""
    cfg_path = os.path.join(PIPER_DIR, f"{voice_key}.onnx.json")
    try:
        with open(cfg_path) as f:
            return int(json.load(f).get("audio", {}).get("sample_rate", 22050))
    except Exception:
        return 22050


def _retune_wav(path, new_rate):
    """Rewrite a PCM WAV header's sample rate (and the derived byte rate) so any
    player reproduces the existing samples at `new_rate`. Players such as paplay
    read the rate from the WAV header and ignore a --rate flag, so this is how we
    actually shift pitch; the matching tempo change is cancelled upstream via
    Piper's length_scale. Best-effort: on any problem the file is left untouched.
    """
    try:
        import struct
        with open(path, "r+b") as f:
            head = f.read(44)
            if len(head) < 44 or head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
                return
            channels = struct.unpack_from("<H", head, 22)[0] or 1
            bits     = struct.unpack_from("<H", head, 34)[0] or 16
            block_align = max(1, channels * (bits // 8))
            f.seek(24); f.write(struct.pack("<I", int(new_rate)))
            f.seek(28); f.write(struct.pack("<I", int(new_rate) * block_align))
    except Exception as e:
        log.debug(f"WAV retune failed: {e}")


# Per-language pronunciation dictionary, kept in sync with the saved state by
# the UI via set_pronunciations(). Keyed by the slot's piper language name.
def set_pronunciations(mapping):
    """Install the {language: {word: respelling}} dictionary used by speak()."""
    app.set_pronunciations(mapping)


def apply_pronunciations(text, mapping):
    """Rewrite whole-word occurrences of each dictionary key with its respelling
    before the text goes to TTS. Case-insensitive, longest key first, single
    pass (so a replacement is never itself re-substituted)."""
    if not mapping:
        return text
    keys = sorted((k for k in mapping if k and k.strip()), key=len, reverse=True)
    if not keys:
        return text
    lower = {k.lower(): mapping[k] for k in keys}
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
        re.IGNORECASE)
    return pattern.sub(lambda m: lower[m.group(0).lower()], text)


def chunk_text(text, max_chars=CHUNK_SIZE):
    """Split `text` into speakable chunks for natural-sounding TTS pacing.

    The previous version returned the input as a single chunk when it
    fit under max_chars. That caused bullet lists and code blocks to be
    spoken without any pause between lines, because Piper has no idea
    those are separate items in the source.

    New strategy (top-down):
    1. Split on every newline (single or double). Each line becomes its
       own chunk, so the speech worker inserts a pause between them.
    2. For each line, split on sentence terminators (. ! ?) if the line
       is long enough to benefit.
    3. For sentences longer than max_chars, split on commas.
    4. As a last resort, hard-slice at max_chars.

    Returns a list of (chunk_text, ends_paragraph) tuples. ends_paragraph
    is True at the end of each blank-line-separated block, so a future
    enhancement can use it for variable-length pauses if desired.
    """
    if not text:
        return []
    text = text.strip()

    import re

    def _split_long_sentence(s):
        """Split a too-long sentence on commas, then hard-slice."""
        if len(s) <= max_chars:
            return [s]
        out = []
        buf = ""
        for part in s.split(", "):
            if len(buf) + 2 + len(part) <= max_chars:
                buf = (buf + ", " + part).strip(", ") if buf else part
            else:
                if buf:
                    out.append(buf)
                while len(part) > max_chars:
                    out.append(part[:max_chars])
                    part = part[max_chars:]
                buf = part
        if buf:
            out.append(buf)
        return out

    def _split_line(line):
        """Split one logical line (no internal newlines) into chunks."""
        line = line.strip()
        if not line:
            return []
        # Break on sentence terminators that are followed by whitespace.
        # The list comprehension keeps non-empty trimmed pieces.
        sentences = [s.strip()
                     for s in re.split(r'(?<=[.!?])\s+', line)
                     if s.strip()]
        if not sentences:
            return []
        chunks, buf = [], ""
        for s in sentences:
            if len(buf) + 1 + len(s) <= max_chars:
                buf = (buf + " " + s).strip() if buf else s
            else:
                if buf:
                    chunks.append(buf)
                if len(s) > max_chars:
                    chunks.extend(_split_long_sentence(s))
                    buf = ""
                else:
                    buf = s
        if buf:
            chunks.append(buf)
        return chunks

    # Walk over blocks separated by blank lines. Each block can contain
    # multiple inner lines (e.g. a bullet list). Mark ends_paragraph=True
    # only on the last chunk of each blank-line-delimited block.
    out = []
    # Normalize: collapse 3+ newlines to exactly 2, then split on \n\n.
    normalized = re.sub(r'\n{3,}', '\n\n', text)
    blocks = [b for b in normalized.split("\n\n") if b.strip()]
    for block in blocks:
        block_chunks = []
        for line in block.split("\n"):
            block_chunks.extend(_split_line(line))
        # Tag chunks: every chunk gets ends_paragraph=False except the very
        # last one in this blank-line block.
        for i, c in enumerate(block_chunks):
            out.append((c, i == len(block_chunks) - 1))
    return out


def speak(text, slot_config):
    """Speak text. Long text is split into chunks played sequentially.
    Replaces any currently-playing speech."""
    global _speak_thread, _stop_event, _progress
    text = text[:MAX_TEXT_LEN]
    text = apply_pronunciations(
        text, app.pron_for((slot_config or {}).get("lang", "")))
    chunks = chunk_text(text)
    with _speak_lock:
        _stop_event.set()
        if _speak_thread and _speak_thread.is_alive():
            _speak_thread.join(timeout=2.0)
        _stop_event = threading.Event()
        _pause_event.clear()  # new speech starts unpaused
        _progress = {"chunk": 0, "total": len(chunks), "text": ""}
        evt   = _stop_event
        pause = _pause_event
        _speak_thread = threading.Thread(
            target=_speak_worker, args=(chunks, slot_config, evt, pause),
            daemon=True)
        _speak_thread.start()


def get_progress():
    """Return a snapshot of current playback progress."""
    return dict(_progress)


def _speak_worker(chunks, slot_config, stop_evt, pause_evt):
    """Play a list of (text, ends_paragraph) tuples sequentially.

    Honors stop_evt (terminate immediately) and pause_evt:
    - Between chunks: wait while paused.
    - Mid-chunk: pause kills the current player; resume replays the chunk
      from the start. (Piper writes the whole WAV before playback, so we
      can't truly mid-stream pause without a more capable player.)

    The NEXT chunk is synthesized in the background while the current one
    plays (prefetch). Without this, every chunk was only synthesized after
    the previous one finished playing, which inserted Piper's synthesis
    time (roughly 0.5-1 s) as an audible gap at every paragraph break.
    """
    global _progress
    voice = slot_config.get("voice", "")
    speed = slot_config.get("speed", 1.0)
    # Pitch in semitones (0 = the voice's natural pitch). Shifting the playback
    # sample rate moves the pitch but also the tempo; we cancel the tempo change
    # via Piper's length_scale so `speed` alone controls the speaking rate.
    # f = 2^(semitones/12): +12 = one octave up, -12 = one octave down.
    try:
        pitch_factor = 2.0 ** (float(slot_config.get("pitch", 0.0)) / 12.0)
    except (TypeError, ValueError):
        pitch_factor = 1.0
    model = os.path.join(PIPER_DIR, f"{voice}.onnx")
    if not os.path.isfile(model):
        log.error(f"Model not found: {model}")
        return

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"]  = PIPER_DIR + ":" + env.get("LD_LIBRARY_PATH", "")
    env["ESPEAK_DATA_PATH"] = os.path.join(PIPER_DIR, "espeak-ng-data")
    rate = _voice_sample_rate(voice)
    # The playback rate carries the pitch shift; clamp to a sane device range.
    play_rate = max(8000, min(48000, round(rate * pitch_factor)))

    def _wait_while_paused():
        """Block while paused. Returns True if interrupted by stop_evt."""
        while pause_evt.is_set():
            if stop_evt.is_set():
                return True
            time.sleep(0.1)
        return False

    def _responsive_sleep(seconds):
        """Sleep that bails out early on stop_evt. Used between chunks."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if stop_evt.is_set():
                return True
            time.sleep(0.05)
        return False

    def _synth(text):
        """Run Piper on `text`; return the (pitch-retuned) wav path or None."""
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                path = f.name
            p = subprocess.Popen(
                [PIPER_BIN, "--model", model, "--output_file", path,
                 "--length_scale", str(round(pitch_factor / speed, 2)),
                 # Halve Piper's default inter-sentence silence (0.2s -> 0.1s).
                 # The default feels sluggish on paragraph breaks because each
                 # chunk ends with this silence baked into the WAV.
                 "--sentence_silence", "0.1",
                 "--quiet"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=env)
            p.stdin.write(text.encode("utf-8"))
            p.stdin.close()
            p.wait()
            if not os.path.isfile(path) or os.path.getsize(path) < 100:
                raise RuntimeError("empty wav")
            # Pitch shift: rewrite the WAV's sample rate so players reproduce
            # it higher/lower. (length_scale already cancelled the tempo side
            # effect.) Skip when pitch is 0 so output is byte-for-byte as before.
            if abs(pitch_factor - 1.0) > 1e-6:
                _retune_wav(path, play_rate)
            return path
        except Exception as e:
            log.debug(f"synthesis failed: {e}")
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass
            return None

    def _play(path):
        """Play one wav. Returns 'ok', 'failed' or 'stop'."""
        for player_cmd in [["paplay", path], ["aplay", "-q", path]]:
            while True:  # retry loop for pause/resume
                try:
                    p2 = subprocess.Popen(player_cmd,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    break  # player missing: try the next one
                paused_mid = False
                while p2.poll() is None:
                    if stop_evt.is_set():
                        p2.terminate()
                        p2.wait()
                        return "stop"
                    if pause_evt.is_set():
                        p2.terminate()
                        p2.wait()
                        paused_mid = True
                        break
                    time.sleep(0.05)
                if paused_mid:
                    if _wait_while_paused():
                        return "stop"
                    continue  # replay this chunk with the same player
                if p2.returncode == 0:
                    return "ok"
                break  # player error: try the next one
        return "failed"

    # --- Prefetch pipeline -------------------------------------------------
    next_holder = []
    next_thread = None

    def _start_prefetch(text):
        nonlocal next_holder, next_thread
        next_holder = []
        next_thread = threading.Thread(
            target=lambda: next_holder.append(_synth(text)), daemon=True)
        next_thread.start()

    def _collect_prefetch():
        nonlocal next_thread
        if next_thread is None:
            return None
        next_thread.join()
        next_thread = None
        return next_holder[0] if next_holder else None

    current = None
    try:
        for idx, (chunk, ends_paragraph) in enumerate(chunks):
            if stop_evt.is_set():
                break
            if _wait_while_paused():
                break

            _progress = {"chunk": idx + 1, "total": len(chunks),
                         "text": chunk[:80]}

            # First chunk (or a failed prefetch): synthesize on the spot.
            if current is None:
                current = _synth(chunk)
            # Kick off synthesis of the NEXT chunk while this one plays.
            if idx + 1 < len(chunks):
                _start_prefetch(chunks[idx + 1][0])

            if current is not None:
                result = _play(current)
                try:
                    os.unlink(current)
                except Exception:
                    pass
                current = None
                if result == "stop":
                    break

            # Inter-chunk pause. Piper itself inserts a small natural pause
            # when a chunk ends in a punctuation mark (. ! ?), so we add
            # nothing on top of that. Lines without trailing punctuation
            # (bullets, code, CLI commands) get a tiny pause so they don't
            # smush together.
            if idx < len(chunks) - 1:
                ends_punctuated = chunk.rstrip().endswith((".", "!", "?", ":", ";"))
                gap = 0.0 if ends_punctuated else 0.025
                if gap and _responsive_sleep(gap):
                    break

            current = _collect_prefetch()
    finally:
        # Clean up anything that never played (stop mid-way or an error).
        leftover = _collect_prefetch()
        for p in (current, leftover):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass
        _progress = {"chunk": 0, "total": 0, "text": ""}


def stop_speaking():
    _stop_event.set()
    _pause_event.clear()


__all__ = [
    "_voices_cache",
    "_voices_cache_ts",
    "VOICES_CACHE_TTL",
    "fetch_voices",
    "get_languages",
    "get_voices_for_lang",
    "get_local_voices",
    "download_voice",
    "_speak_thread",
    "_stop_event",
    "_pause_event",
    "_speak_lock",
    "_progress",
    "is_speaking",
    "is_paused",
    "toggle_pause",
    "_voice_sample_rate",
    "_retune_wav",
    "set_pronunciations",
    "apply_pronunciations",
    "chunk_text",
    "speak",
    "get_progress",
    "_speak_worker",
    "stop_speaking",
]

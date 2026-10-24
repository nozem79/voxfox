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


"""voxfox_core.tts — Speaking: speak(), pause, stop, progress and the
workers that send each chunk to Piper or speech-dispatcher.

The voices live in voices.py, text preparation in textprep.py and the
Piper process in piper.py.
"""

import json, os, subprocess, threading, time
from .common import MAX_TEXT_LEN, PIPER_DIR, app, log
from . import sdengine
from .piper import piper_server
from .textprep import apply_pronunciations, chunk_offsets, chunk_text, word_boundary_at_or_before
from .voices import find_voice_dir



# ── Audio ──────────────────────────────────────────────────────────────────────
class _SpeechState:
    """What is being said right now. One instance, `_speech`.

    thread       the worker thread speaking, or None
    stop_event   set to make the worker stop
    pause_event  set = paused; cleared = playing
    lock         held while one utterance replaces another
    progress     read-only for the GUI: chunk, total, text, offset; the
                 worker updates it and resets it when it finishes
    position     where the listener got to, kept after speaking ends so
                 that pausing or stopping leaves something to save
    """

    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.lock = threading.Lock()
        self.progress = {"chunk": 0, "total": 0, "text": "", "offset": 0}
        self.position = {"offset": 0, "length": 0, "token": None}


_speech = _SpeechState()


def is_speaking():
    """True if a speech thread is actively playing."""
    return _speech.thread is not None and _speech.thread.is_alive()


def is_paused():
    """True if speech is currently paused."""
    return _speech.pause_event.is_set()


def toggle_pause():
    """Toggle the pause state. Returns the new paused state (True/False).
    No-op if nothing is currently speaking."""
    if not is_speaking():
        return False
    if _speech.pause_event.is_set():
        _speech.pause_event.clear()
        return False
    else:
        _speech.pause_event.set()
        return True


def _voice_sample_rate(voice_key):
    """Read the sample rate from a Piper voice's .onnx.json. Default 22050."""
    cfg_path = os.path.join(
        find_voice_dir(voice_key) or PIPER_DIR, f"{voice_key}.onnx.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
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


def speak(text, slot_config, start_offset=0, token=None):
    """Speak text. Long text is split into chunks played sequentially.
    Replaces any currently-playing speech.

    start_offset is a character position in `text`; speaking begins at
    the chunk containing it, so a document can be resumed where the
    listener stopped.

    token is passed straight through to get_position() and is never
    interpreted here. The interface uses it to label the speech with
    the document it came from, so that a reading position is only ever
    written back to the document that actually produced it."""
    text = text[:MAX_TEXT_LEN]
    # Pronunciation replacements are applied per chunk in the worker,
    # not here: they change the length of the text, and every position
    # we hand out must refer to the text the caller gave us, or a saved
    # bookmark would drift by the length of every replacement before it.
    # Cut the text at the starting point and chunk what is left, so any
    # character can be a starting point. Skipping back thirty seconds
    # lands thirty seconds back, not at the top of the sentence.
    start_offset = word_boundary_at_or_before(text, max(0, start_offset))
    body = text[start_offset:] if start_offset else text
    chunks = chunk_text(body)
    offsets = [o + start_offset for o in chunk_offsets(body, chunks)]
    if start_offset:
        log.debug(f"speak: starting at character {start_offset} "
                  f"of {len(text)}")
    with _speech.lock:
        _speech.stop_event.set()
        if _speech.thread and _speech.thread.is_alive():
            _speech.thread.join(timeout=2.0)
        _speech.stop_event = threading.Event()
        _speech.pause_event.clear()  # new speech starts unpaused
        _speech.progress = {"chunk": 0, "total": len(chunks), "text": "",
                     "offset": start_offset}
        _speech.position = {"offset": start_offset, "length": len(text),
                     "token": token}
        evt   = _speech.stop_event
        pause = _speech.pause_event
        _speech.thread = threading.Thread(
            target=_speak_worker,
            args=(chunks, slot_config, evt, pause, offsets, len(text),
                  token),
            daemon=True)
        _speech.thread.start()


def get_progress():
    """Return a snapshot of current playback progress."""
    return dict(_speech.progress)


def get_position():
    """Where the listener got to, as {"offset", "length", "token"}.

    Survives stopping, so it can still be read when the user pauses or
    stops and the document needs to remember its place. offset is a
    character position in the text that was passed to speak()."""
    return dict(_speech.position)


def _speak_worker(chunks, slot_config, stop_evt, pause_evt,
                  offsets=None, total_chars=0, token=None):
    """Play a list of (text, ends_paragraph) tuples sequentially.

    offsets holds the character position of each chunk in the original text
    (see chunk_offsets); it is what lets a document remember its place.

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
    if offsets is None:
        offsets = []
    if sdengine.slot_uses_speechd(slot_config):
        if sdengine.available():
            return _speak_worker_speechd(chunks, slot_config, stop_evt,
                                         pause_evt, offsets, total_chars,
                                         token)
        # Better the slot's Piper voice than silence: the bindings were
        # removed after the slot was set up, for example.
        log.warning("Slot is set to speech-dispatcher, but its Python "
                    "bindings (python3-speechd) are missing; using Piper")
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
    model = os.path.join(find_voice_dir(voice) or PIPER_DIR, f"{voice}.onnx")
    if not os.path.isfile(model):
        log.error(f"Model not found: {model}")
        return

    rate = _voice_sample_rate(voice)
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

    pron = app.pron_for((slot_config or {}).get("lang", ""))

    def _synth(text):
        """Synthesise via the persistent Piper server (model stays loaded).
        Pronunciation replacements happen here, on the chunk, so that the
        positions reported by this worker stay true to the original text."""
        path = piper_server.synth(
            apply_pronunciations(text, pron), model,
            length_scale=round(pitch_factor / speed, 4),
            sentence_silence=0.1,
            stop_evt=stop_evt,
        )
        if path and abs(pitch_factor - 1.0) > 1e-6:
            _retune_wav(path, play_rate)
        return path

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

            here = offsets[idx] if idx < len(offsets) else 0
            _speech.progress = {"chunk": idx + 1, "total": len(chunks),
                         "text": chunk[:80], "offset": here}
            _speech.position = {"offset": here, "length": total_chars,
                         "token": token}

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
        else:
            # Every chunk played and nothing interrupted: the document
            # has been read to the end. Reporting the position as the
            # full length is what lets the bookmark reset to the start.
            _speech.position = {"offset": total_chars, "length": total_chars,
                         "token": token}
    finally:
        # Clean up anything that never played (stop mid-way or an error).
        leftover = _collect_prefetch()
        for p in (current, leftover):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass
        # _speech.position is left alone: it is the only record of where the
        # listener got to once this worker is gone.
        _speech.progress = {"chunk": 0, "total": 0, "text": "", "offset": 0}


def _speak_worker_speechd(chunks, slot_config, stop_evt, pause_evt,
                          offsets, total_chars, token):
    """The speech-dispatcher counterpart of the Piper loop above.

    Same chunks, same position bookkeeping, same pause behaviour (a paused
    chunk is said again from its start), so documents, bookmarks and the
    skip buttons work identically. speech-dispatcher plays the audio
    itself, so there is no WAV, no prefetch and no pitch trick here: speed
    and pitch go to the synthesizer as rate and pitch settings."""
    pron = app.pron_for((slot_config or {}).get("lang", ""))

    def _wait_while_paused():
        while pause_evt.is_set():
            if stop_evt.is_set():
                return True
            time.sleep(0.1)
        return False

    try:
        for idx, (chunk, _ends_paragraph) in enumerate(chunks):
            if stop_evt.is_set() or _wait_while_paused():
                break
            here = offsets[idx] if idx < len(offsets) else 0
            _speech.progress = {"chunk": idx + 1, "total": len(chunks),
                         "text": chunk[:80], "offset": here}
            _speech.position = {"offset": here, "length": total_chars,
                         "token": token}
            spoken = apply_pronunciations(chunk, pron)
            while True:
                result = sdengine.speak_chunk(spoken, slot_config,
                                              stop_evt, pause_evt)
                if result == "paused":
                    if _wait_while_paused():
                        result = "stop"
                        break
                    continue          # say this chunk again from its start
                break
            if result == "stop" or stop_evt.is_set():
                break
            if result == "failed":
                log.error("speech-dispatcher could not speak; stopping")
                break
        else:
            _speech.position = {"offset": total_chars, "length": total_chars,
                         "token": token}
    finally:
        _speech.progress = {"chunk": 0, "total": 0, "text": "", "offset": 0}


def stop_speaking():
    _speech.stop_event.set()
    _speech.pause_event.clear()


__all__ = [
    "is_speaking",
    "is_paused",
    "toggle_pause",
    "speak",
    "get_progress",
    "get_position",
    "stop_speaking",
]

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

"""voxfox_core.piper — The persistent Piper process that keeps a voice
model loaded between utterances.
"""

import os, subprocess, tempfile, threading
from .common import PIPER_BIN, PIPER_DIR, log, ram_tmpdir


# ── Persistent Piper server ────────────────────────────────────────────────────

class _PiperServer:
    """Keep a Piper process alive between synthesis calls so the ONNX model
    stays loaded in memory. Without this, every call to speak() pays a
    ~0.5–1 s model-load penalty — audible as the gap before the first word.

    Protocol:
    - Piper is started with --output_dir pointing at a private temp directory
      and --json-input so we can pass per-line parameters (length_scale,
      sentence_silence) alongside the text.
    - We write one JSON line per chunk to stdin; Piper writes one WAV to the
      output dir and prints its filename to stdout. We block on that stdout
      line to know when the WAV is ready.
    - If Piper dies (crash, model swap, parameter change) the server restarts
      automatically on the next synthesis request.

    One server instance is kept per (voice, length_scale, sentence_silence)
    combination. When the slot changes (different voice or speed/pitch) the
    old process is replaced.
    """

    def __init__(self):
        self._proc   = None
        self._outdir = None
        self._lock   = threading.Lock()
        self._key    = None        # (model_path, length_scale, sentence_silence)
        self._env    = None

    def _build_env(self):
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"]  = PIPER_DIR + ":" + env.get("LD_LIBRARY_PATH", "")
        env["ESPEAK_DATA_PATH"] = os.path.join(PIPER_DIR, "espeak-ng-data")
        return env

    def _alive(self):
        return self._proc is not None and self._proc.poll() is None

    def _start(self, model, length_scale, sentence_silence):
        self._stop()
        self._outdir = tempfile.mkdtemp(prefix="voxfox_piper_",
                                        dir=ram_tmpdir())
        key = (model, length_scale, sentence_silence)
        cmd = [
            PIPER_BIN,
            "--model",            model,
            "--output_dir",       self._outdir,
            "--length_scale",     str(length_scale),
            "--sentence_silence", str(sentence_silence),
            "--json-input",
            "--quiet",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env or self._build_env(),
            )
            self._key = key
            log.debug(f"Piper server started (model={os.path.basename(model)})")
        except Exception as e:
            log.error(f"Piper server start failed: {e}")
            self._proc = None
            if self._outdir:
                try:
                    import shutil; shutil.rmtree(self._outdir, ignore_errors=True)
                except Exception:
                    pass
                self._outdir = None

    def _stop(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._key  = None
        if self._outdir:
            try:
                import shutil; shutil.rmtree(self._outdir, ignore_errors=True)
            except Exception:
                pass
            self._outdir = None

    def synth(self, text, model, length_scale, sentence_silence, stop_evt=None):
        """Synthesise `text` and return a WAV path (caller must delete it),
        or None on failure. Restarts Piper if the key changed or it crashed.
        Returns None immediately if stop_evt is set."""
        if stop_evt and stop_evt.is_set():
            return None
        key = (model, round(length_scale, 4), round(sentence_silence, 2))
        with self._lock:
            if self._key != key or not self._alive():
                self._env = self._build_env()
                self._start(model, round(length_scale, 4), round(sentence_silence, 2))
            if not self._alive():
                return None          # start failed
            import json as _json
            payload = _json.dumps({"text": text}) + "\n"
            try:
                self._proc.stdin.write(payload.encode("utf-8"))
                self._proc.stdin.flush()
            except OSError as e:
                log.debug(f"Piper stdin write failed: {e}; restarting")
                self._stop()
                return None
            # Read the filename Piper writes to stdout when done
            try:
                line = self._proc.stdout.readline()
            except OSError as e:
                log.debug(f"Piper stdout read failed: {e}")
                self._stop()
                return None
            if not line:
                log.debug("Piper server died (empty stdout)")
                self._stop()
                return None
            wav_path = line.decode("utf-8", errors="replace").strip()
            if not wav_path:
                # Piper sometimes writes extra blank lines; try one more
                try:
                    line = self._proc.stdout.readline()
                    wav_path = line.decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
            if not wav_path or not os.path.isfile(wav_path):
                log.debug(f"Piper returned bad path: {wav_path!r}")
                return None
            if os.path.getsize(wav_path) < 100:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
                return None
        return wav_path

    def shutdown(self):
        """Clean up on VoxFox exit."""
        with self._lock:
            self._stop()


piper_server = _PiperServer()


def shutdown_piper():
    """Shut down the persistent Piper server (call on VoxFox exit)."""
    piper_server.shutdown()


__all__ = [
    "piper_server",
    "shutdown_piper",
]

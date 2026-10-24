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


"""voxfox_core.sdengine — speech-dispatcher as a second speech engine.

Piper stays the built-in engine. This lets a voice slot speak through
speech-dispatcher instead, which is what Orca uses too, so every synthesizer
that ships a speech-dispatcher module becomes available: espeak-ng, RHVoice,
Festival, and commercial ones such as Voxin (Cerence/Vocalizer, IBM TTS)
that VoxFox could never bundle itself.

It works one chunk at a time, exactly like the Piper path: the speech worker
in tts.py hands over a chunk and waits for speech-dispatcher to report that
it finished. That keeps everything that is built on chunks -- the reading
position, resuming a document, the skip buttons, pause -- working the same
way for both engines. Pause cancels the chunk being spoken and says it again
from its start on resume, which is also what the Piper path does.

Needs the Python bindings (Debian/Ubuntu: python3-speechd, Fedora:
python3-speechd). Without them the engine is simply not offered.
"""

import atexit, math, os, re, signal, shutil, threading, time
from .common import log

try:
    import speechd as _speechd
except Exception:          # not installed, or a broken install
    _speechd = None

ENGINE_PIPER = "piper"
ENGINE_SPEECHD = "speechd"

# Client name speech-dispatcher shows for us (spd-say -L, logs).
_CLIENT_NAME = "voxfox"

# A chunk that someone else's message cut off (a screen reader speaking with
# a higher priority, for example) is said again, but not forever: after this
# many tries it is skipped so VoxFox cannot end up fighting another program.
MAX_RETRIES = 3

# How long to wait for speech-dispatcher to start speaking a chunk, and the
# longest a chunk may take once it has started (per character, with a floor).
# Generous on purpose -- a slow voice at the lowest rate needs well under a
# third of a second per character -- they only exist so a server that died
# mid-sentence cannot leave the reader waiting forever.
START_TIMEOUT = 15.0
SECONDS_PER_CHAR = 0.6
MIN_CHUNK_TIMEOUT = 60.0


def available():
    """True when the speech-dispatcher Python bindings can be imported.

    Says nothing about whether the server runs: speech-dispatcher normally
    starts itself on the first connection (autospawn)."""
    return _speechd is not None


def lang_code(piper_lang_name):
    """The ISO 639-1 code for a slot's language name ("Dutch" -> "nl"),
    or "" if unknown. Same table the dictation side uses."""
    from .stt import WHISPER_LANG_MAP
    return WHISPER_LANG_MAP.get(piper_lang_name or "", "") or ""


def rate_for_speed(speed):
    """VoxFox speed (0.5 .. 2.0, 1.0 = normal) -> speech-dispatcher rate
    (-100 .. 100, 0 = the synthesizer's default).

    Logarithmic, so half speed and double speed land at the two ends and
    1.0 stays exactly at the synthesizer's own default."""
    try:
        s = float(speed)
    except (TypeError, ValueError):
        s = 1.0
    if s <= 0:
        s = 1.0
    return max(-100, min(100, round(100 * math.log2(s))))


def pitch_for_semitones(semitones):
    """VoxFox pitch (-12 .. 12 semitones) -> speech-dispatcher pitch
    (-100 .. 100). Synthesizers interpret this scale differently, so it is
    a relative setting, not an exact number of semitones."""
    try:
        p = float(semitones)
    except (TypeError, ValueError):
        p = 0.0
    return max(-100, min(100, round(p * 100 / 12)))


def _matches_lang(voice_lang, code):
    """Does a voice's language ("nl", "nl-NL", "nl_BE", "en-us") belong to
    the two-letter code? Compared on the primary subtag only."""
    if not code:
        return True
    primary = (voice_lang or "").replace("_", "-").split("-")[0].lower()
    return primary == code.lower()


# A speech-dispatcher that accepts the connection but never answers would
# otherwise block the bindings' constructor forever -- and with it the
# speech worker, so nothing could be spoken any more until a restart.
CONNECT_TIMEOUT = 5.0


def _connect(name=_CLIENT_NAME, timeout=None):
    """Open a client connection, giving up after CONNECT_TIMEOUT seconds.

    The bindings have no timeout of their own, so the constructor runs in
    a helper thread. If it is still stuck when we give up, a second thread
    waits for it and closes whatever it eventually returns."""
    if _speechd is None:
        raise RuntimeError("speech-dispatcher Python bindings not installed")
    box = {}

    def go():
        try:
            box["client"] = _speechd.SSIPClient(name)
        except Exception as e:
            box["error"] = e

    th = threading.Thread(target=go, daemon=True, name="voxfox-speechd-connect")
    th.start()
    th.join(CONNECT_TIMEOUT if timeout is None else timeout)
    if th.is_alive():
        def reap():
            th.join()
            c = box.get("client")
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        threading.Thread(target=reap, daemon=True).start()
        raise TimeoutError("speech-dispatcher did not answer")
    if "error" in box:
        raise box["error"]
    return box["client"]


# ── modules that are installed but hidden by the user's own config ─────────
#
# speech-dispatcher finds its modules by itself -- unless the user's
# speechd.conf names modules with AddModule. Then it loads only those.
# Pied (the Piper voice manager) writes exactly such a file, with only its
# "piper" module in it, which makes espeak-ng, Voxin and every other
# installed module disappear for every program, Orca included.

MODULE_DIRS = (
    "/usr/lib/speech-dispatcher-modules",           # Debian, Ubuntu, Mint
    "/usr/lib64/speech-dispatcher-modules",
    "/usr/libexec/speech-dispatcher-modules",       # Fedora
    "/usr/local/lib/speech-dispatcher-modules",
    "/usr/lib/x86_64-linux-gnu/speech-dispatcher-modules",
    "/usr/lib/aarch64-linux-gnu/speech-dispatcher-modules",
)
MODULE_CONF_DIRS = ("/etc/speech-dispatcher/modules",)

# Not a synthesizer of their own: sd_generic only works with a config that
# says what to run, sd_dummy plays a fixed sound.
_NOT_A_MODULE = {"generic", "dummy"}

_ADDMODULE = re.compile(r'^\s*AddModule\s+"([^"]+)"', re.MULTILINE)

_BLOCK_START = "# --- Added by VoxFox ---"


def user_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "speech-dispatcher", "speechd.conf")


def _prefix_dirs(sub):
    """`sub` under the install prefix of the speech-dispatcher program on
    PATH: on NixOS and other non-FHS systems the modules are not in /usr."""
    exe = shutil.which("speech-dispatcher")
    if not exe:
        return ()
    prefix = os.path.dirname(os.path.dirname(os.path.realpath(exe)))
    return tuple(os.path.join(prefix, s) for s in sub)


def installed_modules(dirs=None):
    """Names of the speech-dispatcher modules installed on this computer
    ("espeak-ng" for sd_espeak-ng), whether or not they are loaded."""
    found = set()
    for d in (dirs or MODULE_DIRS + _prefix_dirs(
            ("libexec/speech-dispatcher-modules", "lib/speech-dispatcher-modules"))):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for f in names:
            if not f.startswith("sd_"):
                continue
            name = f[3:]
            if name in _NOT_A_MODULE:
                continue
            if os.access(os.path.join(d, f), os.X_OK):
                found.add(name)
    return sorted(found)


def _listed_in_user_config(path=None):
    """The AddModule names in the user's speechd.conf, or None when that
    file does not exist or names no modules (speech-dispatcher then finds
    the modules by itself and nothing is hidden)."""
    try:
        with open(path or user_config_path(), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    names = _ADDMODULE.findall(text)
    return set(names) if names else None


def hidden_modules(path=None, dirs=None):
    """Installed modules that the user's speechd.conf keeps out, because it
    lists modules with AddModule and these are not among them."""
    listed = _listed_in_user_config(path)
    if listed is None:
        return []
    return [m for m in installed_modules(dirs) if m not in listed]


def _module_conf_name(name, path=None):
    """The config file to give AddModule ("espeak-ng.conf"), when there is
    one; speech-dispatcher looks in the user's modules/ folder first."""
    fname = f"{name}.conf"
    user_dir = os.path.join(os.path.dirname(path or user_config_path()), "modules")
    for d in (user_dir,) + MODULE_CONF_DIRS + _prefix_dirs(("etc/speech-dispatcher/modules",)):
        if os.path.isfile(os.path.join(d, fname)):
            return fname
    return ""


def enable_hidden_modules(names, path=None):
    """Add AddModule lines for `names` to the user's speechd.conf.

    Keeps everything already in the file, including the lines Pied wrote
    (and its marker, so Pied leaves the file alone afterwards). A copy of
    the original is saved next to it first. Returns (ok, detail): detail is
    the backup path on success, the error otherwise."""
    path = path or user_config_path()
    names = [n for n in names if n]
    if not names:
        return False, "nothing to add"
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        backup = f"{path}.voxfox-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, backup)
        lines = ["", _BLOCK_START,
                 "# With AddModule lines here, speech-dispatcher loads only the",
                 "# modules named in this file. These were installed but missing:"]
        for n in names:
            conf = _module_conf_name(n, path)
            lines.append(f'AddModule "{n}" "sd_{n}"' + (f' "{conf}"' if conf else ""))
        lines.append("# --- End of VoxFox addition ---")
        tmp = path + ".voxfox-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
        os.replace(tmp, path)
        return True, backup
    except OSError as e:
        return False, str(e)


def restart_speechd():
    """Stop this user's speech-dispatcher so it starts again, with the new
    config, on the next connection. Programs such as Orca reconnect by
    themselves. Returns the number of processes signalled."""
    _speaker.shutdown()
    uid = os.getuid()
    n = 0
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return 0
    for pid in pids:
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                comm = f.read().strip()
            if comm != "speech-dispatch":   # the kernel cuts names at 15 chars
                continue
            os.kill(int(pid), signal.SIGTERM)
            n += 1
        except (OSError, ValueError):
            continue
    return n


def list_modules():
    """Names of the output modules speech-dispatcher has (espeak-ng, voxin,
    rhvoice...). Empty list when it cannot be reached."""
    if _speechd is None:
        return []
    c = None
    try:
        c = _connect(_CLIENT_NAME + "-query")
        return sorted(str(m) for m in (c.list_output_modules() or ()))
    except Exception as e:
        log.info(f"speech-dispatcher: cannot list modules: {e}")
        return []
    finally:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


def list_voices(module, piper_lang_name=""):
    """Voices of `module` for the slot's language, as a sorted list of
    names. Falls back to every voice of the module when none match the
    language, so a module that labels its voices oddly is still usable.
    Empty list when speech-dispatcher cannot be reached."""
    if _speechd is None or not module:
        return []
    c = None
    try:
        c = _connect(_CLIENT_NAME + "-query")
        c.set_output_module(module)
        voices = c.list_synthesis_voices() or ()
    except Exception as e:
        log.info(f"speech-dispatcher: cannot list voices of {module}: {e}")
        return []
    finally:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
    code = lang_code(piper_lang_name)
    names = sorted({str(v[0]) for v in voices
                    if v and _matches_lang(v[1] if len(v) > 1 else "", code)})
    if not names:
        names = sorted({str(v[0]) for v in voices if v})
    return names


class _Speaker:
    """One long-lived connection used for speaking.

    Opening a connection per chunk would work but costs a round trip each
    time and shows up in speech-dispatcher's client list as a stream of
    short-lived clients. A connection that broke (server restarted) is
    replaced on the next chunk."""

    def __init__(self):
        self._client = None
        self._lock = threading.Lock()
        self._settings = None

    def _client_ok(self):
        if self._client is None:
            self._client = _connect()
            self._settings = None
        return self._client

    def _alive(self):
        """False once the bindings' reader thread has ended, which is
        what happens when speech-dispatcher closes the connection (it was
        restarted or crashed). Uses a private attribute, so anything
        unexpected counts as alive and the timeouts below remain the
        safety net."""
        try:
            return self._client._conn._communication_thread.is_alive()
        except Exception:
            return True

    def _drop(self):
        c, self._client, self._settings = self._client, None, None
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    def _apply(self, c, module, voice, lang, rate, pitch):
        wanted = (module, voice, lang, rate, pitch)
        if wanted == self._settings:
            return
        if module:
            c.set_output_module(module)
        if lang:
            c.set_language(lang)
        if voice:
            # After the language: setting a language may pick that
            # language's default voice and override this one otherwise.
            c.set_synthesis_voice(voice)
        c.set_rate(rate)
        c.set_pitch(pitch)
        self._settings = wanted

    def say(self, text, module, voice, lang, rate, pitch,
            stop_evt, pause_evt, poll=0.05):
        """Speak one chunk and wait until it is done.

        Returns "ok", "stop" (stop_evt was set), "paused" (pause_evt was
        set; the chunk was cut off and should be said again), "cut" (someone
        else cancelled it) or "failed" (no connection / server error)."""
        done = threading.Event()
        began = threading.Event()
        outcome = []

        def cb(event_type, index_mark=None):
            if event_type == "begin":
                began.set()
            elif event_type in ("end", "cancel"):
                outcome.append(event_type)
                done.set()

        with self._lock:
            try:
                c = self._client_ok()
                self._apply(c, module, voice, lang, rate, pitch)
                c.speak(text, callback=cb, event_types=(
                    _speechd.CallbackType.BEGIN, _speechd.CallbackType.END,
                    _speechd.CallbackType.CANCEL))
            except Exception as e:
                log.warning(f"speech-dispatcher: speak failed: {e}")
                self._drop()
                return "failed"

        reason = None
        sent = time.monotonic()
        started = None
        limit = max(MIN_CHUNK_TIMEOUT, len(text) * SECONDS_PER_CHAR)
        while not done.wait(poll):
            if stop_evt is not None and stop_evt.is_set():
                reason = "stop"
                break
            if pause_evt is not None and pause_evt.is_set():
                reason = "paused"
                break
            if not self._alive():
                log.warning("speech-dispatcher closed the connection")
                reason = "failed"
                break
            now = time.monotonic()
            if started is None and began.is_set():
                started = now
            if (started is None and now - sent > START_TIMEOUT) or \
                    (started is not None and now - started > limit):
                log.warning("speech-dispatcher stopped answering; "
                            "giving up on this chunk")
                reason = "failed"
                break
        if reason is None:
            return "ok" if outcome and outcome[0] == "end" else "cut"

        # Cut off our own message. cancel() only touches this client's
        # messages, never another program's (spd-say -C would).
        with self._lock:
            try:
                if self._client is not None:
                    self._client.cancel()
            except Exception as e:
                log.debug(f"speech-dispatcher: cancel failed: {e}")
                self._drop()
            if reason == "failed":
                # A fresh connection next time; this one is suspect.
                self._drop()
        if reason != "failed":
            done.wait(1.0)
        return reason

    def shutdown(self):
        with self._lock:
            self._drop()


_speaker = _Speaker()


def shutdown_speechd():
    """Close the speaking connection (call on VoxFox exit)."""
    _speaker.shutdown()


# The bindings close a connection that is still open when the interpreter
# shuts down from the client's __del__, and that can block forever waiting
# for its reader thread. Closing it explicitly before that point does not.
# So VoxFox can never hang on exit, also not on paths that skip the
# window's own clean-up (a signal, an error).
atexit.register(shutdown_speechd)


def speak_chunk(text, slot_config, stop_evt=None, pause_evt=None):
    """Speak one chunk with the slot's speech-dispatcher settings.

    A chunk cut off by another program is retried up to MAX_RETRIES times.
    Returns "ok", "stop", "paused" or "failed"."""
    cfg = slot_config or {}
    module = cfg.get("sd_module", "") or ""
    voice = cfg.get("sd_voice", "") or ""
    lang = lang_code(cfg.get("lang", ""))
    rate = rate_for_speed(cfg.get("speed", 1.0))
    pitch = pitch_for_semitones(cfg.get("pitch", 0.0))
    reconnected = False
    for attempt in range(MAX_RETRIES + 1):
        result = _speaker.say(text, module, voice, lang, rate, pitch,
                              stop_evt, pause_evt)
        if result == "failed" and not reconnected:
            # One fresh connection: speech-dispatcher starts itself again
            # when it was restarted or exited after being idle.
            reconnected = True
            continue
        if result != "cut":
            return result
        log.debug(f"speech-dispatcher: chunk cut off by another client "
                  f"(attempt {attempt + 1})")
        time.sleep(0.3)
    return "ok"   # give up on this chunk, carry on with the next


def slot_uses_speechd(slot_config):
    """True when the slot is set to speech-dispatcher."""
    return (slot_config or {}).get("engine", ENGINE_PIPER) == ENGINE_SPEECHD


def slot_voice_label(slot_config):
    """A short name for the slot's voice, for status messages."""
    cfg = slot_config or {}
    if slot_uses_speechd(cfg):
        return cfg.get("sd_voice") or cfg.get("sd_module") or "speech-dispatcher"
    from .voices import voice_display_parts
    return voice_display_parts(cfg.get("voice", ""))[0]


__all__ = [
    "ENGINE_PIPER",
    "ENGINE_SPEECHD",
    "available",
    "list_modules",
    "installed_modules",
    "hidden_modules",
    "enable_hidden_modules",
    "restart_speechd",
    "user_config_path",
    "list_voices",
    "rate_for_speed",
    "pitch_for_semitones",
    "speak_chunk",
    "shutdown_speechd",
    "slot_uses_speechd",
    "slot_voice_label",
]

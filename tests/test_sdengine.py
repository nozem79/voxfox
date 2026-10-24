"""Tests for voxfox_core.sdengine (speech-dispatcher as second engine) and
the speech-dispatcher branch of the speech worker in tts.py.

speech-dispatcher itself is replaced by a small fake of the python3-speechd
client, so this runs on a bare CI runner without the bindings, a server or
an audio device. The fake answers like the real one does: BEGIN shortly
after SPEAK, END when the text is "spoken", CANCEL after cancel().
"""

import threading
import time
import types

import pytest

import voxfox_core.sdengine as sd
import voxfox_core.tts as tts
import voxfox_core.textprep as textprep


# ── a fake python3-speechd ────────────────────────────────────────────────

class _CallbackType:
    BEGIN = "begin"
    END = "end"
    CANCEL = "cancel"


class FakeServer:
    """Shared state of all fake clients: what was said, with which settings."""

    def __init__(self):
        self.modules = ("espeak-ng", "voxin")
        self.voices = {
            "espeak-ng": (("Dutch", "nl", "none"), ("Dutch+Alex", "nl", "Alex"),
                          ("German", "de", "none")),
            "voxin": (("Xander", "nl-NL", ""), ("Claire", "nl_NL", ""),
                      ("Anna", "de-DE", "")),
        }
        self.said = []          # (text, settings dict) per SPEAK
        self.calls = []         # setter calls in order, per client
        self.seconds_per_char = 0.002
        self.silent = False     # never send any event (a hung server)
        self.cut_next = 0       # cancel this many messages "from elsewhere"
        self.clients = []
        self.fail_connect = False


SERVER = None


class FakeClient:
    def __init__(self, name):
        if SERVER.fail_connect:
            raise OSError("cannot connect")
        self.name = name
        self.settings = {}
        self.closed = False
        self._timer = None
        self._cb = None
        self._lock = threading.Lock()
        thread = types.SimpleNamespace(is_alive=lambda: not self.closed)
        self._conn = types.SimpleNamespace(_communication_thread=thread)
        SERVER.clients.append(self)

    # settings
    def set_output_module(self, m):
        self.settings["module"] = m
        SERVER.calls.append(("module", m))

    def set_language(self, lang):
        self.settings["lang"] = lang
        SERVER.calls.append(("lang", lang))

    def set_synthesis_voice(self, v):
        self.settings["voice"] = v
        SERVER.calls.append(("voice", v))

    def set_rate(self, r):
        self.settings["rate"] = r

    def set_pitch(self, p):
        self.settings["pitch"] = p

    # queries
    def list_output_modules(self):
        return SERVER.modules

    def list_synthesis_voices(self, language=None, variant=None):
        return SERVER.voices.get(self.settings.get("module"), ())

    # speaking
    def speak(self, text, callback=None, event_types=None):
        if self.closed:
            raise OSError("connection closed")
        SERVER.said.append((text, dict(self.settings)))
        self._cb = callback
        if SERVER.silent:
            return
        if SERVER.cut_next > 0:
            SERVER.cut_next -= 1
            threading.Timer(0.01, callback, args=("begin",)).start()
            threading.Timer(0.03, callback, args=("cancel",)).start()
            return
        callback("begin")
        with self._lock:
            self._timer = threading.Timer(len(text) * SERVER.seconds_per_char,
                                          callback, args=("end",))
            self._timer.start()

    def cancel(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._cb is not None and not SERVER.silent:
            self._cb("cancel")

    def close(self):
        self.closed = True
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()


@pytest.fixture
def server(monkeypatch):
    global SERVER
    SERVER = FakeServer()
    fake = types.SimpleNamespace(SSIPClient=FakeClient, CallbackType=_CallbackType)
    monkeypatch.setattr(sd, "_speechd", fake)
    # A fresh speaking connection per test.
    monkeypatch.setattr(sd, "_speaker", sd._Speaker())
    yield SERVER
    sd._speaker.shutdown()


def _cfg(**kw):
    cfg = {"engine": "speechd", "sd_module": "voxin", "sd_voice": "Xander",
           "lang": "Dutch", "speed": 1.0, "pitch": 0.0}
    cfg.update(kw)
    return cfg


def _run(text, cfg, start_offset=0, timeout=10):
    tts.speak(text, cfg, start_offset=start_offset, token="doc")
    end = time.monotonic() + timeout
    while tts.is_speaking() and time.monotonic() < end:
        time.sleep(0.01)
    assert not tts.is_speaking(), "speech worker did not finish"


def _wait_until(cond, timeout=5):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


PARA = ("Dit is een alinea die lang genoeg is om als een eigen stuk tekst te "
        "worden voorgelezen, met nog een paar woorden extra erbij voor de lengte. ")
TEXT = "\n\n".join(PARA * 2 for _ in range(3))


# ── mappings ──────────────────────────────────────────────────────────────

def test_speed_maps_to_rate_with_normal_speed_at_the_synthesizers_default():
    assert sd.rate_for_speed(1.0) == 0
    assert sd.rate_for_speed(2.0) == 100
    assert sd.rate_for_speed(0.5) == -100
    assert 0 < sd.rate_for_speed(1.3) < 100
    assert sd.rate_for_speed(4.0) == 100          # clamped
    assert sd.rate_for_speed("rubbish") == 0
    assert sd.rate_for_speed(0) == 0


def test_pitch_semitones_map_to_the_speechd_scale():
    assert sd.pitch_for_semitones(0) == 0
    assert sd.pitch_for_semitones(12) == 100
    assert sd.pitch_for_semitones(-6) == -50
    assert sd.pitch_for_semitones(-40) == -100    # clamped
    assert sd.pitch_for_semitones(None) == 0


def test_language_name_becomes_an_iso_code():
    assert sd.lang_code("Dutch") == "nl"
    assert sd.lang_code("German") == "de"
    assert sd.lang_code("") == ""
    assert sd.lang_code("Klingon") == ""


# ── listing modules and voices ────────────────────────────────────────────

def test_modules_are_listed_sorted(server):
    server.modules = ("voxin", "espeak-ng", "rhvoice")
    assert sd.list_modules() == ["espeak-ng", "rhvoice", "voxin"]


def test_voices_are_filtered_on_the_slots_language_in_any_spelling(server):
    # "nl-NL" and "nl_NL" both count as Dutch.
    assert sd.list_voices("voxin", "Dutch") == ["Claire", "Xander"]
    assert sd.list_voices("espeak-ng", "Dutch") == ["Dutch", "Dutch+Alex"]


def test_a_module_with_no_voice_for_the_language_still_offers_its_voices(server):
    assert sd.list_voices("voxin", "French") == ["Anna", "Claire", "Xander"]


def test_unreachable_server_gives_empty_lists_not_an_error(server):
    server.fail_connect = True
    assert sd.list_modules() == []
    assert sd.list_voices("voxin", "Dutch") == []


def test_query_connections_are_closed(server):
    sd.list_modules()
    sd.list_voices("voxin", "Dutch")
    assert server.clients and all(c.closed for c in server.clients)


def test_without_the_bindings_nothing_is_offered(monkeypatch):
    monkeypatch.setattr(sd, "_speechd", None)
    assert not sd.available()
    assert sd.list_modules() == []
    assert sd.list_voices("voxin", "Dutch") == []


# ── speaking through the worker ───────────────────────────────────────────

def test_a_document_is_read_to_the_end_with_the_slots_settings(server):
    _run(TEXT, _cfg(speed=2.0, pitch=-6))
    assert len(server.said) == len(textprep.chunk_text(TEXT)) > 1
    spoken = " ".join(t for t, _s in server.said)
    assert spoken.split() == TEXT.split()
    settings = server.said[0][1]
    assert settings == {"module": "voxin", "lang": "nl", "voice": "Xander",
                        "rate": 100, "pitch": -50}
    # Reached the end, so a bookmark resets to the start next time.
    assert tts.get_position() == {"offset": len(TEXT), "length": len(TEXT),
                                  "token": "doc"}


def test_language_is_set_before_the_voice(server):
    # Setting a language can select that language's default voice, so the
    # chosen voice has to come after it or it is silently replaced.
    _run("Korte zin.", _cfg())
    order = [k for k, _v in server.calls if k in ("lang", "voice")]
    assert order == ["lang", "voice"]


def test_settings_are_sent_once_not_for_every_chunk(server):
    _run(TEXT, _cfg())
    assert [k for k, _v in server.calls].count("voice") == 1


def test_pronunciations_apply_to_speechd_too(server, monkeypatch):
    monkeypatch.setattr(tts.app, "pron_for", lambda lang: {"VVD": "vee vee dee"})
    _run("Stem op de VVD.", _cfg())
    assert server.said[0][0] == "Stem op de vee vee dee."


def test_reading_can_start_halfway(server):
    start = TEXT.index("\n\n") + 2
    _run(TEXT, _cfg(), start_offset=start)
    spoken = " ".join(t for t, _s in server.said)
    assert spoken.split() == TEXT[start:].split()


def test_stop_cuts_off_the_current_chunk_and_keeps_the_position(server):
    server.seconds_per_char = 0.05          # each chunk takes seconds
    tts.speak(TEXT, _cfg(), token="doc")
    assert _wait_until(lambda: server.said)
    time.sleep(0.2)
    t0 = time.monotonic()
    tts.stop_speaking()
    assert _wait_until(lambda: not tts.is_speaking(), 3)
    assert time.monotonic() - t0 < 1.5
    assert len(server.said) == 1
    assert tts.get_position()["offset"] == 0


def test_pause_cuts_off_the_chunk_and_resume_says_it_again(server):
    server.seconds_per_char = 0.01
    tts.speak(TEXT, _cfg(), token="doc")
    assert _wait_until(lambda: server.said)
    time.sleep(0.1)
    assert tts.toggle_pause() is True
    time.sleep(0.3)
    assert len(server.said) == 1            # nothing new while paused
    server.seconds_per_char = 0.001         # the rest may go quickly
    assert tts.toggle_pause() is False
    assert _wait_until(lambda: not tts.is_speaking(), 30)
    texts = [t for t, _s in server.said]
    assert texts[0] == texts[1]             # the paused chunk, from its start
    assert len(texts) == len(textprep.chunk_text(TEXT)) + 1


def test_a_chunk_cut_off_by_another_program_is_said_again(server, monkeypatch):
    monkeypatch.setattr(sd.time, "sleep", lambda s: None)
    server.cut_next = 1
    _run("Eerste zin.", _cfg())
    assert [t for t, _s in server.said] == ["Eerste zin.", "Eerste zin."]


def test_but_not_forever(server, monkeypatch):
    monkeypatch.setattr(sd.time, "sleep", lambda s: None)
    server.cut_next = 100
    _run("Eerste zin.", _cfg())
    assert len(server.said) == sd.MAX_RETRIES + 1


def test_a_server_that_went_away_is_reconnected_once(server):
    _run("Eerste zin.", _cfg())
    server.clients[-1].closed = True        # speech-dispatcher restarted
    server.said.clear()
    _run("Tweede zin.", _cfg())
    assert [t for t, _s in server.said] == ["Tweede zin."]
    assert server.said[0][1]["voice"] == "Xander"   # settings sent again


def test_a_server_dying_mid_sentence_is_noticed_straight_away(server):
    server.seconds_per_char = 0.05          # a chunk takes several seconds
    tts.speak("Eerste zin die lang genoeg is om even te duren.", _cfg(), token="doc")
    assert _wait_until(lambda: server.said)
    time.sleep(0.2)
    server.seconds_per_char = 0.001
    server.clients[-1].close()              # gone, without a last event
    # Noticed through the dead connection, not after the 60 s chunk limit:
    # the chunk is said again on a fresh connection and reading ends.
    assert _wait_until(lambda: not tts.is_speaking(), 3)
    assert len(server.said) == 2 and server.said[0][0] == server.said[1][0]


def test_a_server_that_never_answers_cannot_hang_the_reader(server, monkeypatch):
    monkeypatch.setattr(sd, "START_TIMEOUT", 0.2)
    server.silent = True
    t0 = time.monotonic()
    _run(TEXT, _cfg(), timeout=5)
    assert time.monotonic() - t0 < 2
    # One try plus one fresh connection, then the worker stops reading.
    assert len(server.said) == 2


def test_missing_bindings_fall_back_to_piper(monkeypatch):
    monkeypatch.setattr(sd, "_speechd", None)
    called = []
    monkeypatch.setattr(sd, "speak_chunk", lambda *a, **k: called.append(a))
    # No Piper voice exists here either, so the Piper path just logs and
    # returns -- what matters is that it was the path taken.
    monkeypatch.setattr(tts, "find_voice_dir", lambda v: None)
    _run("Tekst.", _cfg(voice="nl_NL-test-medium"))
    assert called == []


def test_shutdown_closes_the_speaking_connection(server):
    _run("Zin.", _cfg())
    conn = server.clients[-1]
    sd.shutdown_speechd()
    assert conn.closed


# ── slot helpers and state ────────────────────────────────────────────────

def test_slot_helpers():
    assert not sd.slot_uses_speechd({})
    assert not sd.slot_uses_speechd({"engine": "piper"})
    assert sd.slot_uses_speechd({"engine": "speechd"})
    assert sd.slot_voice_label({"voice": "nl_NL-alex-medium"}) == "Alex"
    assert sd.slot_voice_label(_cfg()) == "Xander"
    assert sd.slot_voice_label(_cfg(sd_voice="")) == "voxin"


def test_state_gets_an_engine_per_slot(tmp_path, monkeypatch):
    import json
    import voxfox_core.state as state
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "slot1": {"lang": "Dutch", "voice": "nl_NL-alex-medium"},
        "slot2": {"lang": "English", "voice": "x", "engine": "something-odd"},
    }))
    import voxfox_core.common as common
    monkeypatch.setattr(common, "STATE_FILE", str(path))
    monkeypatch.setattr(state, "STATE_FILE", str(path))
    s = state.load_state()
    assert s["slot1"]["engine"] == "piper"
    assert s["slot2"]["engine"] == "piper"
    assert s["slot1"]["sd_module"] == "" and s["slot1"]["sd_voice"] == ""


# ── a server that accepts the connection but never answers ────────────────

def test_connecting_to_a_hung_server_gives_up(server, monkeypatch):
    release = threading.Event()

    class Hung(FakeClient):
        def __init__(self, name):
            release.wait(10)
            super().__init__(name)
    monkeypatch.setattr(sd._speechd, "SSIPClient", Hung)
    monkeypatch.setattr(sd, "CONNECT_TIMEOUT", 0.2)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        sd._connect()
    assert time.monotonic() - t0 < 1
    assert sd.list_modules() == []
    # Speaking gives up too, instead of blocking the worker for good.
    _run("Zin.", _cfg(), timeout=3)
    release.set()
    # The connection that arrived late is closed, not leaked.
    assert _wait_until(lambda: server.clients and all(c.closed for c in server.clients), 3)


# ── modules hidden by the user's own speechd.conf (Pied) ──────────────────

PIED_CONF = '''###
### THIS CONFIG WAS GENERATED BY PIED
###

SymbolsPreproc "char"
AddModule "piper" "sd_generic" "piper.conf"
DefaultModule "piper"
Include "clients/*.conf"
'''


@pytest.fixture
def modules_dir(tmp_path):
    d = tmp_path / "modules-bin"
    d.mkdir()
    for name in ("sd_espeak-ng", "sd_voxin", "sd_generic", "sd_dummy"):
        f = d / name
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    (d / "sd_not-executable").write_text("")
    (d / "README").write_text("")
    return str(d)


@pytest.fixture
def user_conf(tmp_path, monkeypatch):
    cfgdir = tmp_path / "config"
    (cfgdir / "speech-dispatcher").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfgdir))
    sysconf = tmp_path / "etc-modules"
    sysconf.mkdir()
    (sysconf / "espeak-ng.conf").write_text("")
    monkeypatch.setattr(sd, "MODULE_CONF_DIRS", (str(sysconf),))
    return cfgdir / "speech-dispatcher" / "speechd.conf"


def test_installed_modules_are_found_by_their_programs(modules_dir):
    assert sd.installed_modules([modules_dir]) == ["espeak-ng", "voxin"]


def test_nothing_is_hidden_without_a_user_config(user_conf, modules_dir):
    assert not user_conf.exists()
    assert sd.hidden_modules(dirs=[modules_dir]) == []


def test_nothing_is_hidden_when_the_user_config_names_no_modules(user_conf, modules_dir):
    user_conf.write_text('DefaultModule "espeak-ng"\n# AddModule "x" "sd_x"\n')
    assert sd.hidden_modules(dirs=[modules_dir]) == []


def test_pieds_config_hides_the_other_modules(user_conf, modules_dir):
    user_conf.write_text(PIED_CONF)
    assert sd.hidden_modules(dirs=[modules_dir]) == ["espeak-ng", "voxin"]


def test_making_them_available_keeps_pieds_lines_and_saves_a_copy(user_conf, modules_dir):
    user_conf.write_text(PIED_CONF)
    ok, backup = sd.enable_hidden_modules(["espeak-ng", "voxin"])
    assert ok
    with open(backup) as fh:
        assert fh.read() == PIED_CONF
    text = user_conf.read_text()
    assert text.startswith(PIED_CONF)          # nothing of Pied's removed
    assert "THIS CONFIG WAS GENERATED BY PIED" in text   # so Pied leaves it alone
    # A config file is named only where one exists.
    assert 'AddModule "espeak-ng" "sd_espeak-ng" "espeak-ng.conf"\n' in text
    assert 'AddModule "voxin" "sd_voxin"\n' in text
    assert sd.hidden_modules(dirs=[modules_dir]) == []


def test_a_missing_config_is_reported_not_created(user_conf):
    ok, detail = sd.enable_hidden_modules(["espeak-ng"])
    assert not ok and detail
    assert not user_conf.exists()


def test_modules_are_also_found_next_to_the_speech_dispatcher_program(tmp_path, monkeypatch):
    # NixOS: no /usr/lib/speech-dispatcher-modules; the modules live under
    # the package's own prefix, next to its bin/.
    (tmp_path / "bin").mkdir()
    exe = tmp_path / "bin" / "speech-dispatcher"
    exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)
    mods = tmp_path / "libexec" / "speech-dispatcher-modules"
    mods.mkdir(parents=True)
    m = mods / "sd_espeak-ng"; m.write_text(""); m.chmod(0o755)
    monkeypatch.setattr(sd, "MODULE_DIRS", ())
    monkeypatch.setattr(sd.shutil, "which", lambda name: str(exe) if name == "speech-dispatcher" else None)
    assert sd.installed_modules() == ["espeak-ng"]

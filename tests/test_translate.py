"""Tests for voxfox_core.translate: the URL scheme guard added during code
review (bug 6) and the lambda-deferred translation fix for SUGGESTED_MODELS
(bug 3, the notes that used to be frozen in English forever).
"""

import voxfox_core as vf
import voxfox_core.translate as translate


# ── bug 6: URL scheme validation ──────────────────────────────────────────

def test_bad_url_scheme_rejects_non_http():
    assert translate._bad_url_scheme("file:///etc/passwd") is not None
    assert translate._bad_url_scheme("ftp://example.com") is not None


def test_bad_url_scheme_accepts_http_and_https():
    assert translate._bad_url_scheme("http://localhost:11434") is None
    assert translate._bad_url_scheme("https://api.example.com") is None


def test_bad_url_scheme_accepts_empty_url_via_default():
    # An empty/missing URL falls back to DEFAULT_TRANSLATE's http:// address.
    assert translate._bad_url_scheme("") is None
    assert translate._bad_url_scheme(None) is None


def test_translate_text_rejects_bad_scheme_before_any_network_call():
    result, err = translate.translate_text(
        "hallo", {"url": "file:///etc/passwd"})
    assert result is None
    assert "scheme" in err.lower()


def test_list_models_rejects_bad_scheme():
    ids, err = translate.list_models({"url": "ftp://example.com"})
    assert ids == []
    assert err is not None


def test_pull_model_rejects_bad_scheme_before_building_the_request():
    """Regression-relevant: pull_model builds its request object before its
    own try block, so a scheme check added in the wrong place would raise
    unhandled instead of returning (False, message) like the rest of the
    module's public functions."""
    ok, msg = translate.pull_model("model", {"url": "javascript:alert(1)"})
    assert ok is False
    assert "scheme" in msg.lower()


# ── bug 3: SUGGESTED_MODELS translation timing ────────────────────────────

def test_suggested_models_notes_are_callables_not_frozen_strings():
    """Each note is a lambda, evaluated at display time -- not a plain
    string frozen to whatever the UI language was at import time."""
    for model in translate.SUGGESTED_MODELS:
        assert callable(model["note"])
        assert isinstance(model["note"](), str)


def test_suggested_models_notes_follow_the_current_language():
    note_key = translate.SUGGESTED_MODELS[0]["note"]()
    original_lang = vf.app.lang
    try:
        vf.app.translations["--test--"] = {note_key: "VERTAALD"}
        vf.app.lang = "--test--"
        assert translate.SUGGESTED_MODELS[0]["note"]() == "VERTAALD"
    finally:
        vf.app.lang = original_lang
        vf.app.translations.pop("--test--", None)


# ── Installing a local Ollama ─────────────────────────────────────────────
# The decisions (when to offer the button, what the installer reports) are
# plain functions in voxfox_core, so they run here without a display, a root
# prompt or a network: pkexec and the root-side helper are small shell stubs.

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.mark.parametrize("url,expected", [
    ("", True), (None, True),
    ("http://localhost:11434", True), ("http://localhost:11434/v1", True),
    ("http://127.0.0.1:11434", True), ("http://127.5.5.5:11434", True),
    ("http://[::1]:11434", True),
    ("https://api.openai.com/v1", False),
    ("http://192.168.1.20:11434", False),
    ("http://ollama.lan:11434", False),
])
def test_ollama_url_is_local(url, expected):
    assert translate.ollama_url_is_local(url) is expected


@pytest.mark.parametrize("url,reachable,binary,nixos,expected", [
    # a server already answers: nothing to install, whatever else is true
    ("", True, False, False, "running"),
    ("", True, True, True, "running"),
    # installed but silent: say how to start it, even on NixOS
    ("", False, True, False, "not-running"),
    ("", False, True, True, "not-running"),
    # not installed: NixOS gets a pointer, everyone else the button
    ("", False, False, True, "nixos"),
    ("", False, False, False, "missing"),
    # somebody else's server: never offer to install one here
    ("https://api.example.com/v1", False, False, False, "remote"),
    ("http://192.168.1.20:11434", False, False, True, "remote"),
])
def test_ollama_install_state(url, reachable, binary, nixos, expected):
    assert translate.ollama_install_state(
        url, reachable, binary, nixos) == expected


def test_ollama_binary_present(monkeypatch):
    monkeypatch.setattr(translate.shutil, "which", lambda t: None)
    monkeypatch.setattr(translate.os.path, "isfile", lambda p: False)
    assert translate.ollama_binary_present() is False
    monkeypatch.setattr(translate.os.path, "isfile",
                        lambda p: p == "/usr/local/bin/ollama")
    assert translate.ollama_binary_present() is True   # off-PATH install
    monkeypatch.setattr(translate.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(translate.shutil, "which", lambda t: "/opt/ollama")
    assert translate.ollama_binary_present() is True


def test_is_nixos(monkeypatch):
    monkeypatch.setattr(translate.os.path, "exists", lambda p: False)
    monkeypatch.setattr(translate.os.path, "isdir", lambda p: False)
    assert translate.is_nixos() is False
    monkeypatch.setattr(translate.os.path, "exists",
                        lambda p: p == "/etc/NIXOS")
    assert translate.is_nixos() is True


def test_helper_path_prefers_the_packaged_copy(tmp_path, monkeypatch):
    packaged = tmp_path / "install-ollama.sh"
    packaged.write_text("#!/bin/sh\n")
    monkeypatch.setattr(translate, "_OLLAMA_HELPER_PACKAGED", str(packaged))
    assert translate.ollama_helper_path() == str(packaged)


def test_helper_path_falls_back_to_the_source_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "_OLLAMA_HELPER_PACKAGED",
                        str(tmp_path / "does-not-exist"))
    found = translate.ollama_helper_path()
    assert found and found.endswith("install-ollama.sh")
    assert os.path.isfile(found)


def test_install_blocker_codes(monkeypatch):
    monkeypatch.setattr(translate, "ollama_helper_path", lambda: None)
    assert translate.ollama_install_blocker() == "no-helper"
    monkeypatch.setattr(translate, "ollama_helper_path", lambda: "/x")
    monkeypatch.setattr(translate.shutil, "which",
                        lambda t: None if t == "pkexec" else "/bin/" + t)
    assert translate.ollama_install_blocker() == "no-pkexec"
    monkeypatch.setattr(translate.shutil, "which",
                        lambda t: None if t == "zstd" else "/bin/" + t)
    assert translate.ollama_install_blocker() == "missing:zstd"
    monkeypatch.setattr(translate.shutil, "which", lambda t: "/bin/" + t)
    assert translate.ollama_install_blocker() is None


@pytest.fixture
def fake_installer(tmp_path, monkeypatch):
    """pkexec that just runs its argument, plus a helper whose body the test
    chooses. Nothing here needs root, a prompt, or the network."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    pkexec = bindir / "pkexec"
    pkexec.write_text('#!/bin/sh\nexec "$@"\n')
    pkexec.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(translate, "ollama_install_missing_tools", lambda: [])

    def make(body):
        helper = tmp_path / "helper.sh"
        helper.write_text("#!/bin/sh\n" + body)
        helper.chmod(0o755)
        monkeypatch.setattr(translate, "ollama_helper_path",
                            lambda: str(helper))
    return make


def test_install_reports_progress_and_download_percentage(fake_installer):
    fake_installer(
        'echo ">>> Downloading Ollama"\n'
        r"printf '######        12.5%%\r'" "\n"
        r"printf '################ 100.0%%\r'" "\n"
        'echo ">>> Install complete."\n')
    lines, fracs = [], []
    ok, detail = translate.install_ollama(
        lines.append, lambda f, _l: fracs.append(f), wait_ready=False)
    assert (ok, detail) == (True, "ok")
    assert ">>> Downloading Ollama" in lines
    assert ">>> Install complete." in lines
    assert fracs == [0.125, 1.0]            # the bar lines are not text
    assert not any("%" in line for line in lines)


@pytest.mark.parametrize("code", [126, 127])
def test_install_dismissed_prompt_is_cancelled_not_failed(fake_installer, code):
    """pkexec exits 126 when the password prompt is dismissed and 127 when
    authorisation fails; neither means the installation itself broke."""
    fake_installer(f"exit {code}\n")
    assert translate.install_ollama(wait_ready=False) == (False, "cancelled")


def test_install_returns_the_helpers_own_reason(fake_installer):
    fake_installer('echo "ERROR: download failed (https://x)" >&2\nexit 1\n')
    assert translate.install_ollama(wait_ready=False) == (
        False, "download failed (https://x)")


def test_install_failure_without_a_message(fake_installer):
    fake_installer("exit 3\n")
    assert translate.install_ollama(wait_ready=False) == (
        False, "exit code 3")


@pytest.fixture
def fake_clock(monkeypatch):
    """A clock that only moves when the code sleeps, so the waiting for the
    server can be tested without really waiting. Replaces the module's whole
    `time` rather than the real one, so nothing else in the process notices."""
    import types
    now = [1000.0]
    monkeypatch.setattr(translate, "time", types.SimpleNamespace(
        monotonic=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s)))
    return now


def test_install_waits_for_the_server_to_answer(fake_installer, fake_clock, monkeypatch):
    fake_installer("exit 0\n")
    answers = iter([([], "refused"), ([], "refused"), (["m"], None)])
    monkeypatch.setattr(translate, "list_models",
                        lambda cfg=None, timeout=None: next(answers))
    assert translate.install_ollama() == (True, "ok")


def test_install_succeeds_but_reports_a_silent_server(fake_installer, fake_clock, monkeypatch):
    fake_installer("exit 0\n")
    monkeypatch.setattr(translate, "list_models",
                        lambda cfg=None, timeout=None: ([], "refused"))
    assert translate.install_ollama() == (True, "not-running")


def test_the_wait_for_the_server_is_bounded(fake_installer, fake_clock, monkeypatch):
    """Whatever the server does, the wait ends at the deadline: a server that
    accepts the connection and never answers used to hold the progress bar on
    'installing' for over two minutes (12 attempts of 10 seconds each)."""
    fake_installer("exit 0\n")
    calls = []

    def slow(cfg=None, timeout=None):
        calls.append(timeout)
        fake_clock[0] += timeout          # each attempt uses up its timeout
        return [], "timed out"
    monkeypatch.setattr(translate, "list_models", slow)
    start = fake_clock[0]
    assert translate.install_ollama(ready_timeout=30) == (True, "not-running")
    assert fake_clock[0] - start <= 30 + 2 + 1      # deadline + one last attempt
    assert calls and all(t is not None and t <= 3 for t in calls)


def test_install_reports_what_it_is_doing(fake_installer, fake_clock, monkeypatch):
    fake_installer(
        'echo ">>> Downloading Ollama"\n'
        r"printf '################ 100.0%%\r'" "\n"
        'echo ">>> Installing Ollama to /usr"\n'
        'echo ">>> Creating the ollama user"\n'
        'echo ">>> Creating the ollama systemd service"\n'
        'echo ">>> Enabling and starting the ollama service"\n'
        'echo ">>> Install complete. The Ollama API is now available at 127.0.0.1:11434."\n')
    monkeypatch.setattr(translate, "list_models",
                        lambda cfg=None, timeout=None: (["m"], None))
    phases = []
    assert translate.install_ollama(phase=phases.append) == (True, "ok")
    # one report per change of step, the last one being the wait for the server
    assert phases[0] == "download"
    assert phases[-1] == "wait"
    assert "install" in phases and "start" in phases
    assert phases.index("install") < phases.index("start") < phases.index("wait")


def test_no_wait_phase_when_not_asked_to_wait(fake_installer):
    fake_installer('echo ">>> Downloading Ollama"\nexit 0\n')
    phases = []
    translate.install_ollama(phase=phases.append, wait_ready=False)
    assert phases == ["download"]


def test_a_child_that_keeps_the_output_open_cannot_hold_the_install_up(fake_installer):
    """The helper is finished, but something it started still holds its output
    open. Reading until the output closes made the progress bar wait for that
    something; reading until the helper ends does not."""
    import time as real_time
    fake_installer('echo ">>> Install complete."\n( sleep 6 ) &\nexit 0\n')
    t0 = real_time.monotonic()
    assert translate.install_ollama(wait_ready=False) == (True, "ok")
    assert real_time.monotonic() - t0 < 4


def test_output_arriving_just_before_the_helper_exits_is_not_lost(fake_installer):
    fake_installer('echo ">>> Creating the ollama user"\necho "ERROR: no space left"\nexit 1\n')
    lines = []
    ok, detail = translate.install_ollama(lines.append, wait_ready=False)
    assert (ok, detail) == (False, "no space left")
    assert ">>> Creating the ollama user" in lines


def test_list_models_takes_a_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        raise OSError("nope")
    monkeypatch.setattr(translate.urllib.request, "urlopen", fake_urlopen)
    translate.list_models({"url": "http://localhost:11434"}, timeout=2)
    assert seen["timeout"] == 2
    translate.list_models({"url": "http://localhost:11434"})
    assert seen["timeout"] == 10                   # default unchanged


def test_install_stops_at_a_blocker_without_running_anything(monkeypatch):
    monkeypatch.setattr(translate, "ollama_install_blocker",
                        lambda: "missing:zstd")
    assert translate.install_ollama() == (False, "missing:zstd")


# ── the root-side script and its polkit policy ────────────────────────────

def test_installer_script_is_valid_shell():
    import subprocess
    r = subprocess.run(["sh", "-n", str(_SRC / "install-ollama.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_polkit_policy_is_bound_to_the_path_the_code_runs():
    """If these two ever drift apart, pkexec silently falls back to a generic
    'run a program as root' prompt instead of the named one."""
    tree = ET.parse(_SRC / "nl.voxfox.install-ollama.policy")
    action = tree.getroot().find("action")
    assert action.get("id") == "nl.voxfox.install-ollama"
    annotate = {a.get("key"): a.text for a in action.findall("annotate")}
    assert (annotate["org.freedesktop.policykit.exec.path"]
            == translate._OLLAMA_HELPER_PACKAGED)

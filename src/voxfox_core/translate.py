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


"""voxfox_core.translate — Translate selected text via any OpenAI-compatible API.

One endpoint covers everything: a local Ollama server (which speaks the
OpenAI chat-completions dialect at /v1) as well as OpenAI itself or any other
compatible provider. Configured with just a URL, a model name and an optional
API key. The target language is VoxFox's current UI language (follows Slot 1).
Plain urllib — no extra dependencies. Long selections go chunk by chunk.
"""

import ipaddress
import json
import os
import re
import select
import shutil
import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse

from .common import _, log, app
from .webread import _split_paragraph_chunks

DEFAULT_TRANSLATE = {
    "url":     "http://localhost:11434/v1",   # local Ollama; or any /v1 API
    "model":   "llama3.2",
    "api_key": "",                            # optional (OpenAI etc.)
}

# A short, curated starting point for people who don't already know which
# model to pick -- small enough for an ordinary laptop, and either built
# specifically for translation or well regarded for multilingual work. Not
# an exhaustive ranking, just a reasonable "try one of these" default.
SUGGESTED_MODELS = [
    {"name": "zongwei/gemma3-translator:1b", "size": "~815 MB",
     "note": lambda: _("Purpose-built for translation, based on Gemma 3")},
    {"name": "gemma2:2b", "size": "~1.7 GB",
     "note": lambda: _("Fast, general-purpose, solid multilingual support")},
    {"name": "qwen2.5:1.5b", "size": "~1 GB",
     "note": lambda: _("Strong multilingual, especially Asian languages")},
]

# English names for the UI language codes, so small local models get an
# unambiguous target ("Dutch" beats "nl"). Unknown codes fall back to the
# native name from the locale files.
_LANG_EN_NAMES = {
    "en": "English", "nl": "Dutch", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "el": "Greek",
    "ar": "Arabic", "zh": "Chinese", "uk": "Ukrainian", "no": "Norwegian", "sv": "Swedish", "fi": "Finnish",
    "ro": "Romanian", "cs": "Czech", "pl": "Polish",
    "da": "Danish", "hu": "Hungarian", "tr": "Turkish", "fa": "Persian",
    "id": "Indonesian", "ja": "Japanese",
}

_CHUNK_CHARS = 3500

_PROMPT = (
    "You are a professional translator. Translate the text between the "
    "<text> markers into {lang}. Preserve paragraph breaks. Output ONLY the "
    "translation - no explanations, no notes, no quotation marks.\n\n"
    "<text>\n{payload}\n</text>"
)


def target_language():
    """(code, English-or-native name) of the current UI language."""
    code = app.lang or "en"
    name = _LANG_EN_NAMES.get(code) or app.ui_lang_names.get(code, code)
    return code, name


def _cfg(cfg):
    out = dict(DEFAULT_TRANSLATE)
    out.update(cfg or {})
    return out


def _base_url(url):
    """Normalise the endpoint: strip a trailing slash and append /v1 when the
    user typed a bare server address (e.g. http://localhost:11434)."""
    u = (url or DEFAULT_TRANSLATE["url"]).rstrip("/")
    if "/v1" not in u:
        u += "/v1"
    return u


def _bad_url_scheme(url):
    """None when the effective URL (after _base_url's default/normalising)
    is http(s), otherwise an error message. urllib.request accepts other
    schemes too -- file://, ftp:// -- which a stray character while typing
    a server address could turn into by accident; this is the user's own
    configuration, so the risk is a misconfiguration, not an attack, but a
    clear error beats a confusing one from deep inside urlopen."""
    scheme = urllib.parse.urlparse(_base_url(url)).scheme
    if scheme not in ("http", "https"):
        return f"Unsupported URL scheme {scheme!r}: only http:// and https:// are supported"
    return None


def _headers(api_key=""):
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _chat(url, model, prompt, api_key="", timeout=300):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        _base_url(url) + "/chat/completions", data=body,
        headers=_headers(api_key))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("unexpected API response shape")


def _err_str(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read(300).decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return f"HTTP {e.code} {e.reason} {detail}".strip()
    if isinstance(e, urllib.error.URLError):
        return f"connection failed: {e.reason}"
    return str(e) or e.__class__.__name__


def translate_text(text, cfg=None, target_code=None, progress=None):
    """Translate `text` into the current UI language (or `target_code`).

    Returns (translated_text, None) on success or (None, error_message) on
    failure. Never raises. Long texts are translated per paragraph chunk;
    `progress(i, n)` is called before each chunk when given.
    """
    c = _cfg(cfg)
    code, name = target_language()
    if target_code:
        code = target_code
        name = _LANG_EN_NAMES.get(code) or app.ui_lang_names.get(code, code)
    text = (text or "").strip()
    if not text:
        return None, "no text"
    bad = _bad_url_scheme(c.get("url"))
    if bad:
        return None, bad
    chunks = _split_paragraph_chunks(text, _CHUNK_CHARS) or [text]
    out = []
    try:
        for i, chunk in enumerate(chunks, 1):
            if progress:
                progress(i, len(chunks))
            piece = _chat(c.get("url"),
                          c.get("model") or DEFAULT_TRANSLATE["model"],
                          _PROMPT.format(lang=name, payload=chunk),
                          api_key=(c.get("api_key") or "").strip())
            if piece:
                out.append(piece)
        result = "\n\n".join(out).strip()
        if not result:
            return None, "empty reply from model"
        log.info(f"translate: {len(text)} chars -> {name} "
                 f"({len(chunks)} chunk(s) via {_base_url(c.get('url'))})")
        return result, None
    except Exception as e:
        msg = _err_str(e)
        log.warning(f"translate failed: {msg}")
        return None, msg


def list_models(cfg=None, timeout=10):
    """List model ids already available on the configured endpoint (a
    plain GET /models -- works for Ollama and any other OpenAI-compatible
    server). Returns (model_ids, error); model_ids is [] rather than None
    on failure, so callers can always iterate without a None check."""
    c = _cfg(cfg)
    try:
        bad = _bad_url_scheme(c.get("url"))
        if bad:
            return [], bad
        req = urllib.request.Request(
            _base_url(c.get("url")) + "/models",
            headers=_headers((c.get("api_key") or "").strip()))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return [], _err_str(e)
    ids = [m.get("id", "") for m in data.get("data", [])
           if isinstance(m, dict) and m.get("id")]
    return ids, None


def translate_test(cfg=None):
    """Quick connectivity test for the settings dialog. Returns (ok, message)."""
    c = _cfg(cfg)
    want = c.get("model") or DEFAULT_TRANSLATE["model"]
    ids, err = list_models(cfg)
    if err:
        return False, err
    if not ids:
        return True, "API reachable"
    base = {i.split(":")[0] for i in ids}
    if want in ids or want.split(":")[0] in base:
        return True, f"API reachable, model '{want}' available"
    return True, f"API reachable, but model '{want}' was not listed"


# Best-effort filter for the suggestion list only -- never blocks a
# manually typed name. OpenAI's /models list in particular mixes in
# embedding, audio, image and legacy-completion models alongside chat
# models with no way to tell them apart except the name itself.
_NON_CHAT_HINTS = ("embed", "whisper", "tts", "dall-e", "moderation",
                   "davinci-002", "babbage", "curie", "ada-", "image",
                   "audio", "realtime", "transcribe")


def is_chat_model(model_id):
    """Rough guess at whether `model_id` is usable for chat-style
    translation, based on its name. Used only to tidy the autocomplete
    suggestion list; the model field itself always accepts any value."""
    low = (model_id or "").lower()
    return not any(h in low for h in _NON_CHAT_HINTS)


def _ollama_native_base(url):
    """The plain Ollama server root (no /v1), for endpoints -- like
    /api/pull -- that are Ollama-native and have no OpenAI equivalent."""
    u = _base_url(url)
    if u.endswith("/v1"):
        u = u[:-3]
    return u.rstrip("/")


def pull_model(model, cfg=None, progress=None, frac=None):
    """Pull `model` on the configured endpoint's native Ollama API,
    streaming progress. `progress(text)` and `frac(fraction, label)`
    mirror install_piper()'s callback shape. Returns (ok, message).

    Only meaningful against a real (local or remote) Ollama server.
    VoxFox does not install Ollama as part of its normal setup; Settings
    offers an explicit "Install Ollama" button for a local one (see
    install_ollama()). Against a plain OpenAI-style API this simply
    fails with a clear error, the same as any other unsupported call."""
    c = _cfg(cfg)
    progress = progress or (lambda *_a: None)
    frac = frac or (lambda *_a: None)
    bad = _bad_url_scheme(c.get("url"))
    if bad:
        return False, bad
    body = json.dumps({"model": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        _ollama_native_base(c.get("url")) + "/api/pull", data=body,
        headers=_headers((c.get("api_key") or "").strip()))
    try:
        progress(_("Connecting..."))
        with urllib.request.urlopen(req, timeout=30) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("error"):
                    return False, ev["error"]
                total, done = ev.get("total"), ev.get("completed")
                if total and done is not None:
                    frac(done / total, model)
                elif ev.get("status"):
                    progress(f"{model}: {ev['status']}")
        log.info(f"translate: pulled model {model}")
        return True, "ok"
    except Exception as e:
        msg = _err_str(e)
        log.warning(f"translate: pull failed for {model}: {msg}")
        return False, msg


# ── Installing a local Ollama ──────────────────────────────────────────────
# Settings offers an "Install Ollama" button, but only in the one situation
# where it makes sense: the configured URL points at this very machine and
# nothing answers there yet. Everything that decides that is a plain function
# here (testable without a display); the GTK side only reacts to the result.
#
# What the button runs is /usr/lib/voxfox/install-ollama.sh, through pkexec --
# not Ollama's own install.sh. See the comment at the top of that script for
# why (short version: Ollama's script can install NVIDIA's driver stack).

# Shown to people who have to do it by hand (no pkexec, no packaged helper).
OLLAMA_OFFICIAL_INSTALL = "curl -fsSL https://ollama.com/install.sh | sh"
_OLLAMA_HELPER_PACKAGED = "/usr/lib/voxfox/install-ollama.sh"
_PERCENT_LINE = re.compile(r"^[#\s\d.%]+$")      # curl's --progress-bar
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def ollama_url_is_local(url):
    """True when `url` (empty means the default) points at this machine."""
    host = (urllib.parse.urlparse(_base_url(url)).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ollama_binary_present():
    """An ollama program is installed here (running or not). Checks the usual
    install locations too, since VoxFox may be started with a PATH that
    lacks /usr/local/bin."""
    return (shutil.which("ollama") is not None
            or os.path.isfile("/usr/bin/ollama")
            or os.path.isfile("/usr/local/bin/ollama"))


def is_nixos():
    """NixOS manages services declaratively; an imperative installer that
    writes into /usr and /etc/systemd does not belong there."""
    return os.path.exists("/etc/NIXOS") or os.path.isdir("/run/current-system")


def ollama_install_state(url, reachable, binary_present, nixos):
    """What Settings should offer for a local Ollama. One of:
      "remote"       the URL is another machine's -- nothing to install here
      "running"      a server already answers -- nothing to do
      "not-running"  installed but not answering -- tell them how to start it
      "nixos"        not installed, on NixOS -- point at services.ollama
      "missing"      not installed -- offer the Install button
    `reachable` comes from list_models(); a network probe, so the caller does
    it (in a thread) and hands the result in."""
    if not ollama_url_is_local(url):
        return "remote"
    if reachable:
        return "running"
    if binary_present:
        return "not-running"
    if nixos:
        return "nixos"
    return "missing"


def ollama_helper_path():
    """The root-side installer: the packaged copy, else the one next to the
    source tree (a git checkout). None when neither exists."""
    if os.path.isfile(_OLLAMA_HELPER_PACKAGED):
        return _OLLAMA_HELPER_PACKAGED
    here = os.path.dirname(os.path.abspath(__file__))
    dev = os.path.normpath(os.path.join(here, "..", "install-ollama.sh"))
    return dev if os.path.isfile(dev) else None


def ollama_install_missing_tools():
    """Tools the installer needs. Checked here, as the user, so a missing one
    is reported before anybody is asked for an administrator password."""
    return [t for t in ("curl", "zstd") if shutil.which(t) is None]


def ollama_install_blocker():
    """Why the installer cannot run right now, as a short code, or None when
    it can: "no-helper", "no-pkexec" or "missing:<tool>,<tool>"."""
    if not ollama_helper_path():
        return "no-helper"
    if shutil.which("pkexec") is None:
        return "no-pkexec"
    missing = ollama_install_missing_tools()
    if missing:
        return "missing:" + ",".join(missing)
    return None


# What the helper is doing, as short codes for the settings page to put into
# words. The helper prints English status lines; matching them here keeps
# that English out of the user interface.
_HELPER_PHASES = (
    ("Downloading", "download"),
    ("Installing", "install"),
    ("Creating", "install"),
    ("Enabling", "start"),
)


def install_ollama(progress=lambda _t: None, frac=lambda *_a: None,
                   wait_ready=True, phase=lambda _c: None,
                   ready_timeout=30.0):
    """Install a local Ollama via the packaged helper under pkexec.

    `progress(text)` gets the helper's status lines; `frac(fraction, label)`
    gets the download percentage parsed from curl's progress bar;
    `phase(code)` is told what is going on, one of "download", "install",
    "start" (the helper's own steps) and "wait" (the installation is done,
    waiting for the server to answer). Returns (ok, detail). detail is
    "ok" (installed and answering), "not-running" (installed, but nothing
    answered within `ready_timeout` seconds), a blocker code from
    ollama_install_blocker(), "cancelled" (the authentication prompt was
    dismissed or refused), or the reason the helper printed on its last
    "ERROR:" line.

    pkexec exits 126 when the prompt was dismissed and 127 when authorisation
    failed; the helper itself only ever exits 0 or 1, so neither can be
    mistaken for a failure of the installation proper.

    Nothing in here may be able to wait for ever: this runs behind a progress
    bar, and a bar that stays on "installing" after the installation is
    finished looks exactly like a hang. So the helper's output is read only
    until the helper itself has ended (a child it left running with the
    output open cannot hold us up), and the wait for the server has a
    deadline and short per-attempt timeouts."""
    blocker = ollama_install_blocker()
    if blocker:
        return False, blocker
    try:
        proc = subprocess.Popen(
            ["pkexec", ollama_helper_path()], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        return False, str(e)

    last_error = ""

    def handle(raw):
        nonlocal last_error
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            return
        if _PERCENT_LINE.match(text):
            m = _PERCENT.search(text)
            if m:
                frac(min(float(m.group(1)), 100.0) / 100.0, "Ollama")
            return
        if text.startswith("ERROR"):
            last_error = text.split(":", 1)[-1].strip()
        log.debug(f"ollama installer: {text}")
        progress(text)
        body = text.lstrip("> ").strip()
        for prefix, code in _HELPER_PHASES:
            if body.startswith(prefix):
                phase(code)
                break

    def feed(chunk, pending):
        pending += chunk
        # curl redraws its bar with \r, so split on that as well as \n.
        *lines, pending = re.split(rb"[\r\n]+", pending)
        for raw in lines:
            try:
                handle(raw)
            except Exception as e:
                log.debug(f"ollama installer output handler: {e}")
        return pending

    pending = b""
    fd = proc.stdout.fileno()
    while True:
        ready, _w, _x = select.select([fd], [], [], 0.5)
        if ready:
            chunk = os.read(fd, 4096)
            if not chunk:
                break                       # every writer has closed
            pending = feed(chunk, pending)
        elif proc.poll() is not None:
            break       # helper has ended and nothing more is buffered
    try:
        handle(pending)
    except Exception as e:
        log.debug(f"ollama installer output handler: {e}")
    proc.stdout.close()
    rc = proc.wait()
    log.info(f"Ollama installer finished with exit code {rc}")

    if rc in (126, 127):
        return False, "cancelled"
    if rc != 0:
        return False, last_error or f"exit code {rc}"
    if not wait_ready:
        return True, "ok"
    # The service is restarted as the very last step; give it a moment, but
    # never longer than `ready_timeout`.
    phase("wait")
    progress(_("Connecting..."))
    deadline = time.monotonic() + ready_timeout
    while True:
        _ids, err = list_models({"url": DEFAULT_TRANSLATE["url"]}, timeout=2)
        if err is None:
            return True, "ok"
        left = deadline - time.monotonic()
        if left <= 0:
            return True, "not-running"
        time.sleep(min(1.0, left))


__all__ = [
    "DEFAULT_TRANSLATE",
    "SUGGESTED_MODELS",
    "target_language",
    "translate_text",
    "translate_test",
    "list_models",
    "pull_model",
    "is_chat_model",
    "OLLAMA_OFFICIAL_INSTALL",
    "ollama_url_is_local",
    "ollama_binary_present",
    "is_nixos",
    "ollama_install_state",
    "ollama_helper_path",
    "ollama_install_missing_tools",
    "ollama_install_blocker",
    "install_ollama",
]

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

import json
import urllib.request
import urllib.error

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
     "note": _("Purpose-built for translation, based on Gemma 3")},
    {"name": "gemma2:2b", "size": "~1.7 GB",
     "note": _("Fast, general-purpose, solid multilingual support")},
    {"name": "qwen2.5:1.5b", "size": "~1 GB",
     "note": _("Strong multilingual, especially Asian languages")},
]

# English names for the UI language codes, so small local models get an
# unambiguous target ("Dutch" beats "nl"). Unknown codes fall back to the
# native name from the locale files.
_LANG_EN_NAMES = {
    "en": "English", "nl": "Dutch", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "el": "Greek",
    "ar": "Arabic", "zh": "Chinese", "uk": "Ukrainian",
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


def list_models(cfg=None):
    """List model ids already available on the configured endpoint (a
    plain GET /models -- works for Ollama and any other OpenAI-compatible
    server). Returns (model_ids, error); model_ids is [] rather than None
    on failure, so callers can always iterate without a None check."""
    c = _cfg(cfg)
    try:
        req = urllib.request.Request(
            _base_url(c.get("url")) + "/models",
            headers=_headers((c.get("api_key") or "").strip()))
        with urllib.request.urlopen(req, timeout=10) as resp:
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

    Only meaningful against a real (local or remote) Ollama server that
    the user already installed and is running themselves -- VoxFox never
    installs Ollama itself. Against a plain OpenAI-style API this simply
    fails with a clear error, the same as any other unsupported call."""
    c = _cfg(cfg)
    progress = progress or (lambda *_a: None)
    frac = frac or (lambda *_a: None)
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


__all__ = [
    "DEFAULT_TRANSLATE",
    "SUGGESTED_MODELS",
    "target_language",
    "translate_text",
    "translate_test",
    "list_models",
    "pull_model",
    "is_chat_model",
]

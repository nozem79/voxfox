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

"""webread — experimental "read the current web page" support.

Two ways to get the page, then two processing stages:

Getting the page (in order):
a. A selected URL. The user selects the page address (for example with
   Ctrl+L in the browser's address bar) and presses the shortcut; VoxFox
   fetches that URL itself. This needs no accessibility bus at all and it is
   always explicit which page is being read.
b. Fallback: the AT-SPI accessibility tree of the focused browser window
   (needs a working accessibility bus and, for Chromium, the
   --force-renderer-accessibility flag).

Stage 1 extracts the *main* content: for a fetched page a small stdlib HTML
parser keeps <main>/<article> and drops nav/aside/footer/script noise; for
AT-SPI the ARIA landmarks do the same. Deterministic, never invents text.

Stage 2 (ollama_refine) optionally pipes the text through an Ollama model as
a fine filter (keep original sentences, drop leftover ads / cross-promotion)
or a summarizer. Best-effort: failures return None and the caller falls back
to the stage-1 text. An optional API key is sent as a Bearer token for
Ollama instances behind a reverse proxy on another machine.

This module imports pyatspi lazily (inside functions), like a11y.py, so
importing voxfox_core never touches the accessibility stack. Callers must
check a11y_bus_reachable() before the AT-SPI path — on a broken bus, calling
into libatspi aborts the whole process.
"""

import html.parser
import json
import re
import shutil
import subprocess
import urllib.request
import urllib.error

from .common import log

DEFAULT_OLLAMA_URL   = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"

# ARIA landmark roles (the "xml-roles" AT-SPI attribute) whose entire subtree
# is skipped: they hold menus, mastheads, sidebars, footers and search UI.
_SKIP_LANDMARKS = {"navigation", "banner", "complementary", "contentinfo",
                   "search", "doc-pagelist", "doc-toc"}
# HTML tags (the "tag" AT-SPI attribute) treated the same way.
_SKIP_TAGS = {"nav", "aside", "footer", "iframe", "select", "style", "script"}
# Landmarks that mark the article itself; if present, only this subtree is read.
_MAIN_LANDMARKS = {"main", "article", "doc-abstract"}
_MAIN_TAGS = {"main", "article"}

_MAX_NODES = 30000       # hard cap on tree nodes visited
_MAX_CHARS = 200000      # hard cap on collected text


def _attrs(node):
    """AT-SPI attributes as a dict. pyatspi returns 'key:value' strings."""
    try:
        out = {}
        for item in node.getAttributes():
            k, _, v = item.partition(":")
            out[k] = v
        return out
    except Exception:
        return {}


def _xml_roles(node):
    return set(_attrs(node).get("xml-roles", "").split())


def _is_skipped(node):
    a = _attrs(node)
    if set(a.get("xml-roles", "").split()) & _SKIP_LANDMARKS:
        return True
    if a.get("tag", "").lower() in _SKIP_TAGS:
        return True
    return False


def _find_active_document():
    """Locate the web document of the focused browser window.

    Prefers the window whose PID matches the active X window (xdotool);
    falls back to any frame with STATE_ACTIVE. Returns the accessible with
    ROLE_DOCUMENT_WEB, or None."""
    import pyatspi
    from .a11y import get_active_pid

    active_pid = get_active_pid()
    desktop = pyatspi.Registry.getDesktop(0)

    def find_doc(root, budget=6000):
        """Breadth-first search for a web document below `root`."""
        queue = [root]
        seen = 0
        while queue and seen < budget:
            n = queue.pop(0)
            seen += 1
            try:
                if n.getRole() == pyatspi.ROLE_DOCUMENT_WEB:
                    return n
                # Don't descend into obviously wrong subtrees.
                for i in range(min(n.childCount, 200)):
                    c = n.getChildAtIndex(i)
                    if c is not None:
                        queue.append(c)
            except Exception:
                continue
        return None

    candidates = []
    try:
        for app in desktop:
            if app is None:
                continue
            try:
                pid = app.get_process_id()
            except Exception:
                pid = None
            for i in range(min(app.childCount, 50)):
                try:
                    frame = app.getChildAtIndex(i)
                    if frame is None:
                        continue
                    st = frame.getState()
                    active = st.contains(pyatspi.STATE_ACTIVE)
                except Exception:
                    continue
                score = 0
                if active_pid and pid == active_pid:
                    score += 2
                if active:
                    score += 1
                if score:
                    candidates.append((score, frame))
    except Exception as e:
        log.debug(f"webread: desktop scan failed: {e}")
        return None

    for _score, frame in sorted(candidates, key=lambda t: -t[0]):
        doc = find_doc(frame)
        if doc is not None:
            return doc
    return None


def _find_main(doc):
    """Return the 'main'/'article' landmark below doc, or doc itself."""
    queue = [doc]
    seen = 0
    best = None
    while queue and seen < 8000:
        n = queue.pop(0)
        seen += 1
        try:
            a = _attrs(n)
            roles = set(a.get("xml-roles", "").split())
            tag = a.get("tag", "").lower()
            if roles & _MAIN_LANDMARKS or tag in _MAIN_TAGS:
                # Prefer the first (outermost) main/article.
                best = n
                break
            for i in range(min(n.childCount, 200)):
                c = n.getChildAtIndex(i)
                if c is not None:
                    queue.append(c)
        except Exception:
            continue
    return best or doc


def _leaf_text(node):
    try:
        t = node.queryText().getText(0, -1)
        t = t.replace("\uFFFC", " ").strip()
        if t:
            return t
    except Exception:
        pass
    return ""


def _collect_text(root):
    """Depth-first text collection under `root`, honouring skip landmarks.

    Leaf text nodes are joined with spaces; block-level elements (headings,
    paragraphs, list items, quotes, cells) end with a newline so the TTS
    chunker can pause at real boundaries."""
    import pyatspi
    block_roles = {
        pyatspi.ROLE_HEADING, pyatspi.ROLE_PARAGRAPH, pyatspi.ROLE_LIST_ITEM,
        pyatspi.ROLE_BLOCK_QUOTE, pyatspi.ROLE_TABLE_CELL,
        pyatspi.ROLE_CAPTION, pyatspi.ROLE_SECTION,
    }
    out = []
    count = 0
    chars = 0

    def walk(node, depth):
        nonlocal count, chars
        if node is None or count >= _MAX_NODES or chars >= _MAX_CHARS \
                or depth > 60:
            return
        count += 1
        try:
            if _is_skipped(node):
                return
            role = node.getRole()
            nchild = node.childCount
        except Exception:
            return
        if nchild == 0:
            t = _leaf_text(node)
            if t:
                out.append(t)
                chars += len(t)
        else:
            for i in range(min(nchild, 500)):
                try:
                    walk(node.getChildAtIndex(i), depth + 1)
                except Exception:
                    continue
        if role in block_roles and out and out[-1] != "\n":
            out.append("\n")

    walk(root, 0)

    text = ""
    for piece in out:
        if piece == "\n":
            text = text.rstrip(" ") + "\n"
        else:
            text += piece + " "
    # Collapse whitespace noise but keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text():
    """Stage 1: return (text, error). text is None when nothing was found.

    Never call this without a reachable accessibility bus (see
    a11y_bus_reachable()); libatspi aborts the process on a broken bus."""
    try:
        doc = _find_active_document()
        if doc is None:
            return None, "no-document"
        main = _find_main(doc)
        text = _collect_text(main)
        if not text or len(text) < 40:
            # A bare main landmark can be empty (some SPAs); retry whole doc.
            if main is not doc:
                text = _collect_text(doc)
        if not text or len(text) < 40:
            return None, "no-text"
        return text, None
    except Exception as e:
        log.debug(f"webread: extraction failed: {e}")
        return None, "error"


# ── Fetched-page route: selected URL → HTML → main text ─────────────────────

_URL_RE = re.compile(
    r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+\.[a-z]{2,}[^\s<>\"']*)",
    re.IGNORECASE)


_BARE_DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+"
    r"(:\d+)?(/\S*)?$", re.IGNORECASE)


def url_from_text(text):
    """First usable http(s) URL in `text`, or None. Accepts bare www. hosts
    and — when the whole selection is a single address-like token — bare
    domains such as "nu.nl/artikel" (Chromium's address bar hides the
    scheme). https:// is prepended and trailing punctuation stripped."""
    if not text or len(text) > 4000:
        return None
    stripped = text.strip()
    m = _URL_RE.search(stripped)
    if m:
        url = m.group(0).rstrip(".,;:!?)]}>'\"")
        if url.lower().startswith("www."):
            url = "https://" + url
        return url
    # Whole selection = one token that looks like host[/path]? Then it is
    # almost certainly a scheme-less address from a browser address bar.
    token = stripped.rstrip(".,;:!?)]}>'\"")
    if " " not in token and "\n" not in token and _BARE_DOMAIN_RE.match(token):
        host = token.split("/", 1)[0].split(":", 1)[0]
        tld = host.rsplit(".", 1)[-1].lower()
        # Reject file-name lookalikes ("bestand.html", "notities.txt").
        not_tlds = {"html", "htm", "php", "asp", "aspx", "pdf", "txt", "md",
                    "png", "jpg", "jpeg", "gif", "svg", "webp", "json", "xml",
                    "csv", "zip", "deb", "py", "js", "css", "doc", "docx",
                    "odt", "mp3", "mp4", "wav", "ogg", "iso", "exe"}
        if 2 <= len(tld) <= 24 and not tld.isdigit() and tld not in not_tlds:
            return "https://" + token
    return None


class _PageExtractor(html.parser.HTMLParser):
    """Tiny readability-style extractor on the stdlib parser.

    Mirrors the AT-SPI landmark logic: subtree-skips script/style/nav/aside/
    footer/header/form noise, collects text with newlines at block elements,
    and keeps a separate buffer for <main>/<article> so the article wins when
    the page marks it up."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "nav",
             "aside", "footer", "header", "form", "iframe", "button",
             "select", "figure", "dialog"}
    _MAIN = {"main", "article"}
    _BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "tr",
              "blockquote", "div", "section", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        # Stack of [tag, nesting] for subtrees being skipped: pushing happens
        # on a skip-triggering start tag; same-name children bump `nesting`
        # so the matching close tag (not an inner one) pops the entry. This
        # also makes role="navigation" divs close correctly.
        self._skips = []
        self._main = 0
        self._in_title = False
        self._in_h1 = False
        self.title = ""
        self.h1 = ""
        self._all = []
        self._art = []

    def _skipping(self):
        return bool(self._skips)

    def handle_starttag(self, tag, attrs):
        if self._skips:
            if tag == self._skips[-1][0]:
                self._skips[-1][1] += 1
            return
        role = dict(attrs).get("role", "")
        # <header> inside <main>/<article> is the article's own header and
        # carries the headline — keep it. Only the page-level masthead
        # (header outside main) is navigation noise.
        skip_tag = tag in self._SKIP and not (tag == "header"
                                              and self._main > 0)
        if skip_tag or role in ("navigation", "banner",
                                "complementary", "contentinfo",
                                "search"):
            self._skips.append([tag, 0])
            return
        if tag in self._MAIN:
            self._main += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag):
        if self._skips:
            if tag == self._skips[-1][0]:
                if self._skips[-1][1]:
                    self._skips[-1][1] -= 1
                else:
                    self._skips.pop()
            return
        if tag in self._MAIN and self._main:
            self._main -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        if tag in self._BLOCK:
            self._all.append("\n")
            if self._main:
                self._art.append("\n")

    def handle_data(self, data):
        if self._skips:
            return
        if self._in_title and not self.title:
            self.title = data.strip()[:200]
            return
        t = data.strip()
        if not t:
            return
        if self._in_h1 and len(self.h1) < 300:
            self.h1 += t + " "
        self._all.append(t + " ")
        if self._main:
            self._art.append(t + " ")

    @staticmethod
    def _join(parts):
        text = ""
        for p in parts:
            if p == "\n":
                text = text.rstrip(" ") + "\n"
            else:
                text += p
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def result(self):
        art = self._join(self._art)
        full = self._join(self._all)
        # Prefer the marked-up article when it is substantial.
        if len(art) >= 300 or (art and len(art) >= 0.2 * len(full)):
            text = art
        else:
            text = full
        # Headline safety net: some pages put the <h1> just outside
        # <main>/<article>; without it the reader starts mid-story. If the
        # first heading is not already near the top, prepend it.
        h1 = self.h1.strip()
        if text and h1 and h1 not in text[:max(400, len(h1) + 50)]:
            text = h1 + "\n" + text
        return text


_FETCH_MAX_BYTES = 3 * 1024 * 1024
# A plain, current Firefox UA. Deliberately no VoxFox token: bot filters on
# news sites and CDNs 403 anything that does not look like a real browser.
_FETCH_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
             "Gecko/20100101 Firefox/128.0")


def fetch_page_text(url, timeout=20):
    """Fetch `url` and return (text, title, error). error is a short
    machine-readable string ('http-403', 'not-html', 'no-text',
    'fetch-failed') and text is None when extraction produced nothing
    usable. The fetch sees the page as an anonymous visitor: content behind
    logins or heavy client-side rendering may differ from the browser's
    view."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _FETCH_UA,
            "Accept": ("text/html,application/xhtml+xml,application/xml;"
                       "q=0.9,*/*;q=0.8"),
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US,en;q=0.7,nl;q=0.6",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            log.debug(f"webread: HTTP {e.code} for {url}")
            return None, "", f"http-{e.code}"
        with resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "xml" not in ctype and ctype:
                return None, "", "not-html"
            raw = resp.read(_FETCH_MAX_BYTES)
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip" \
                    or raw[:2] == b"\x1f\x8b":
                import gzip as _gzip
                try:
                    raw = _gzip.decompress(raw)
                except Exception:
                    pass
            m = re.search(r"charset=([\w-]+)", ctype)
            enc = m.group(1) if m else "utf-8"
        try:
            html_text = raw.decode(enc, errors="replace")
        except LookupError:
            html_text = raw.decode("utf-8", errors="replace")
        return _extract_from_html(html_text)
    except Exception as e:
        log.debug(f"webread: fetch failed for {url}: {e}")
        return None, "", "fetch-failed"


def _extract_from_html(html_text):
    """Run the readability extractor over an HTML string.
    Returns (text, title, error)."""
    parser = _PageExtractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as e:
        log.debug(f"webread: html parse hiccup: {e}")
    text = parser.result()
    if not text or len(text) < 40:
        return None, parser.title, "no-text"
    return text, parser.title, None


# ── Headless-browser fallback ────────────────────────────────────────────────
# The plain fetch cannot run JavaScript, so single-page apps come back empty
# ("no-text"), and some bot walls 403 anything that is not a real browser.
# When a Chromium-family browser is installed we can render the page headless
# — JavaScript included, with the browser's own network stack and TLS
# fingerprint — and feed the rendered DOM through the same extractor.

_CHROMIUM_BINS = ("chromium", "chromium-browser", "google-chrome",
                  "google-chrome-stable", "brave-browser", "microsoft-edge")


def _find_chromium():
    for b in _CHROMIUM_BINS:
        path = shutil.which(b)
        if path:
            return path
    return None


def headless_available():
    """True when a Chromium-family browser is installed for the fallback."""
    return _find_chromium() is not None


def fetch_page_text_headless(url, timeout=30):
    """Render `url` in a headless Chromium (JavaScript runs) and extract the
    main text. Returns (text, title, error); error 'no-browser' when no
    Chromium-family browser is installed. Slower than the plain fetch (a
    browser start costs a few seconds), so use it as a fallback only."""
    browser = _find_chromium()
    if not browser:
        return None, "", "no-browser"
    try:
        r = subprocess.run(
            [browser, "--headless", "--disable-gpu", "--mute-audio",
             "--hide-scrollbars", "--blink-settings=imagesEnabled=false",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--disable-sync",
             "--disable-background-networking",
             "--virtual-time-budget=8000", "--timeout=20000",
             "--dump-dom", url],
            capture_output=True, text=True, timeout=timeout)
        html_text = r.stdout or ""
        if len(html_text) < 100:
            log.debug(f"webread: headless render empty for {url}: "
                      f"{(r.stderr or '')[-200:]}")
            return None, "", "render-failed"
        return _extract_from_html(html_text)
    except subprocess.TimeoutExpired:
        return None, "", "render-timeout"
    except Exception as e:
        log.debug(f"webread: headless failed for {url}: {e}")
        return None, "", "render-failed"


# ── Stage 2: Ollama ──────────────────────────────────────────────────────────

_FILTER_PROMPT = (
    "You are a strict text filter, not a writer. Below is text extracted from "
    "a web page. Return ONLY the main article text, in its original language "
    "and original wording. Remove advertisements, cookie and consent notices, "
    "navigation labels, promotional blocks, newsletter prompts, related-article "
    "snippets, social-media buttons, image captions and comment sections. Do "
    "not rewrite, translate, summarize, shorten or add anything. Output plain "
    "text only, no markdown, no commentary.\n\n---\n{payload}\n---"
)

_SUMMARY_PROMPT = (
    "Summarize the main article in the web-page text below, in the article's "
    "original language, as flowing plain prose suitable for being read aloud. "
    "Ignore advertisements, navigation, promotional blocks and snippets of "
    "other articles. Do not add opinions or facts that are not in the text. "
    "Output plain text only, no markdown, no headings, no commentary.\n\n"
    "---\n{payload}\n---"
)

# Keep each request comfortably inside a small local model's context window.
_CHUNK_CHARS = 7000       # per filter-request payload
_SUMMARY_MAX_CHARS = 24000


def _split_paragraph_chunks(text, limit):
    chunks, cur = [], ""
    for para in text.split("\n"):
        candidate = (cur + "\n" + para) if cur else para
        if len(candidate) > limit and cur:
            chunks.append(cur)
            cur = para
        else:
            cur = candidate
    if cur.strip():
        chunks.append(cur)
    return chunks


def _ollama_headers(api_key=None):
    h = {"Content-Type": "application/json"}
    if api_key:
        # Ollama itself is unauthenticated; instances exposed on another
        # machine usually sit behind a reverse proxy that expects a Bearer
        # token (Open WebUI, ollama-proxy, nginx auth_request, ...).
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _ollama_generate(url, model, prompt, timeout=300, api_key=None):
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate", data=body,
        headers=_ollama_headers(api_key))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return (data.get("response") or "").strip()


def ollama_list_models(url=DEFAULT_OLLAMA_URL, timeout=5, api_key=None):
    """Names of locally available Ollama models, or None if unreachable."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags",
                                     headers=_ollama_headers(api_key))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception as e:
        log.debug(f"webread: ollama tags failed: {e}")
        return None


def ollama_refine(text, mode="filter", url=DEFAULT_OLLAMA_URL,
                  model=DEFAULT_OLLAMA_MODEL, progress=None, api_key=None):
    """Stage 2. mode 'filter' keeps original sentences and strips leftover ads
    and cross-promotional snippets; mode 'summary' produces a spoken-friendly
    summary. Returns the refined text, or None when Ollama is unreachable or
    errors out (caller should fall back to the stage-1 text)."""
    try:
        if mode == "summary":
            payload = text[:_SUMMARY_MAX_CHARS]
            if progress:
                progress(1, 1)
            return _ollama_generate(
                url, model, _SUMMARY_PROMPT.format(payload=payload),
                api_key=api_key)
        # filter mode: chunk-wise, so long pages fit the context window
        chunks = _split_paragraph_chunks(text, _CHUNK_CHARS)
        out = []
        for i, chunk in enumerate(chunks, 1):
            if progress:
                progress(i, len(chunks))
            piece = _ollama_generate(
                url, model, _FILTER_PROMPT.format(payload=chunk),
                api_key=api_key)
            if piece:
                out.append(piece)
        return "\n".join(out).strip()
    except Exception as e:
        log.debug(f"webread: ollama refine failed: {e}")
        return None


__all__ = [
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_OLLAMA_MODEL",
    "extract_page_text",
    "url_from_text",
    "fetch_page_text",
    "fetch_page_text_headless",
    "headless_available",
    "ollama_list_models",
    "ollama_refine",
]

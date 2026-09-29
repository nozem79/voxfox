"""Tests for voxfox_core.tts's pure functions: chunking, offsets, and
pronunciation replacement. No GTK, no AT-SPI, no network, no audio device --
these are the functions bug 1 (the Turkish-i crash) and the pronunciation
cache regression would have been caught by immediately.
"""

import voxfox_core.tts as tts


# ── apply_pronunciations ──────────────────────────────────────────────────

def test_apply_pronunciations_basic():
    assert (tts.apply_pronunciations("de VVD en het CDA",
                                     {"VVD": "vee vee dee", "CDA": "cee dee aa"})
            == "de vee vee dee en het cee dee aa")


def test_apply_pronunciations_case_insensitive_longest_first():
    # "CDA" must not be partially matched by a shorter key ("CD") first.
    result = tts.apply_pronunciations("een CDA-lid en een CD",
                                      {"CD": "cee dee", "CDA": "cee dee aa"})
    assert result == "een cee dee aa-lid en een cee dee"


def test_apply_pronunciations_empty_or_none_mapping():
    assert tts.apply_pronunciations("tekst", {}) == "tekst"
    assert tts.apply_pronunciations("tekst", None) == "tekst"


def test_apply_pronunciations_no_match_left_alone():
    assert tts.apply_pronunciations("niets hier van toepassing",
                                    {"VVD": "vee vee dee"}) == \
           "niets hier van toepassing"


def test_apply_pronunciations_unicode_casefold_does_not_crash():
    """Regression test for the crash found in code review: Turkish dotted
    I (U+0130) lowercases to 'i' + a combining dot above (U+0307), which is
    not equal to the plain 'i' the mapping's own key produces. Before the
    fix this raised KeyError and silently killed the speak worker thread."""
    result = tts.apply_pronunciations("İstanbul is nice",
                                      {"istanbul": "Istanboel"})
    assert isinstance(result, str)  # must not raise


def test_apply_pronunciations_cache_is_content_keyed():
    """The compiled-pattern cache is keyed on the mapping's *content*, not
    object identity, so a freshly-built dict with the same pronunciation
    rules still hits the cache instead of recompiling."""
    mapping = {"VVD": "vee vee dee"}
    before = tts._compiled_pronunciation_pattern.cache_info()
    for _ in range(50):
        tts.apply_pronunciations("de VVD", dict(mapping))  # new dict object
    after = tts._compiled_pronunciation_pattern.cache_info()
    assert after.hits - before.hits >= 49


# ── chunk_text / chunk_offsets ────────────────────────────────────────────

def test_chunk_text_splits_bullet_list_with_pauses():
    chunks = tts.chunk_text("Boodschappen.\n\n- brood\n- kaas\n- melk")
    assert len(chunks) == 4


def test_chunk_text_numbered_list_keeps_pauses():
    """Regression test: a doubled backslash in the list-item regex once
    made it match a literal backslash instead of a digit, silently packing
    numbered items together like ordinary short lines."""
    chunks = tts.chunk_text("Stappen.\n\n1. een\n2. twee\n3. drie\n\nKlaar.")
    assert len(chunks) == 5


def test_chunk_text_packs_short_fragments():
    """A document made of many short blocks (headings, captions -- as in a
    design proposal) should not turn into one chunk per fragment, or the
    speech stutters with a gap after every line."""
    text = "\n\n".join(f"Kopje {i}" for i in range(40))
    chunks = tts.chunk_text(text)
    assert len(chunks) < 10


def test_chunk_text_keeps_ordinary_paragraphs_separate():
    text = ("Dit is een alinea van gemiddelde lengte die netjes doorloopt "
            "en die als geheel wordt voorgelezen met een pauze erna.\n\n") * 4
    assert len(tts.chunk_text(text)) == 4


def test_chunk_text_splits_a_run_on_sentence_on_commas():
    """Exercises _split_long_sentence (a nested helper with no standalone
    name to import) through chunk_text's public behaviour: one sentence
    longer than the chunk size, with commas to split on."""
    sentence = ("Alfa, bravo, charlie, delta, echo, foxtrot, golf, hotel, "
                "india, juliet, kilo, lima, mike, november, oscar, papa, "
                "quebec, romeo, sierra, tango, uniform, victor, whiskey, "
                "xray, yankee, zulu, ") * 5 + "en het einde van de zin."
    assert len(sentence) > tts.CHUNK_SIZE
    chunks = tts.chunk_text(sentence)
    assert len(chunks) > 1
    for chunk, _ends in chunks:
        assert len(chunk) <= tts.CHUNK_SIZE


def test_chunk_offsets_point_at_the_right_characters():
    text = ("Dit is een zin die halverwege\n\nstopt en hier doorgaat.\n\n"
            "Nog een laatste alinea hier.")
    chunks = tts.chunk_text(text)
    offsets = tts.chunk_offsets(text, chunks)
    assert offsets == sorted(offsets)
    for (chunk, _ends), offset in zip(chunks, offsets):
        core = "".join(chunk.split())[:10]
        rest = "".join(text[offset:].split())[:10]
        assert core == rest


def test_chunk_offsets_empty_text():
    assert tts.chunk_offsets("", []) == []


def test_chunk_index_for_offset_resumes_at_sentence_start():
    text = "Eerste zin hier. Tweede zin hier. Derde zin hier."
    chunks = tts.chunk_text(text)
    offsets = tts.chunk_offsets(text, chunks)
    if len(offsets) > 1:
        middle = offsets[1] + 3
        assert tts.chunk_index_for_offset(offsets, middle) == 1
    assert tts.chunk_index_for_offset(offsets, 0) == 0


def test_seconds_to_chars_scales_with_speed():
    base = tts.seconds_to_chars(30, {"speed": 1.0})
    faster = tts.seconds_to_chars(30, {"speed": 1.10})
    assert faster > base
    assert base == 450  # 30 * CHARS_PER_SECOND(15) * 1.0


# ── download_voice: md5 verification (bug 4) ──────────────────────────────

import hashlib
import http.server
import threading


class _OneFileHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, root=None, **kwargs):
        self._root = root
        super().__init__(*args, directory=root, **kwargs)

    def log_message(self, *a):
        pass


def _serve_dir(directory):
    """A throwaway local HTTP server for one test, torn down at the end."""
    handler = lambda *a, **kw: _OneFileHandler(*a, root=directory, **kw)
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _voice_download_fixture(tmp_path, monkeypatch, digest):
    payload = b"nep-onnx-inhoud" * 50
    src_dir = tmp_path / "server_files"
    src_dir.mkdir()
    (src_dir / "voice.onnx").write_bytes(payload)

    srv = _serve_dir(str(src_dir))
    monkeypatch.setattr(tts, "BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}")

    files = {"voice.onnx": {"size_bytes": len(payload)}}
    if digest is not None:
        files["voice.onnx"]["md5_digest"] = digest
    monkeypatch.setattr(tts, "_voices_cache", {"stem": {"files": files}})
    monkeypatch.setattr(tts, "_voices_cache_ts", 1e18)

    dest_dir = tmp_path / "voices"
    monkeypatch.setattr(tts, "voices_user_dir", lambda: str(dest_dir))
    return payload, dest_dir, srv


def test_download_voice_accepts_matching_checksum(tmp_path, monkeypatch):
    payload = b"nep-onnx-inhoud" * 50
    real_md5 = hashlib.md5(payload).hexdigest()
    payload, dest_dir, srv = _voice_download_fixture(tmp_path, monkeypatch, real_md5)
    try:
        ok, msg = tts.download_voice("stem")
        assert ok is True
        assert (dest_dir / "voice.onnx").is_file()
    finally:
        srv.shutdown()


def test_download_voice_rejects_mismatched_checksum(tmp_path, monkeypatch):
    payload, dest_dir, srv = _voice_download_fixture(tmp_path, monkeypatch, "0" * 32)
    try:
        ok, msg = tts.download_voice("stem")
        assert ok is False
        assert "checksum" in msg.lower()
        assert not (dest_dir / "voice.onnx").is_file()
    finally:
        srv.shutdown()


def test_download_voice_without_a_digest_field_still_works(tmp_path, monkeypatch):
    """Best-effort verification: a voices.json entry with no md5_digest at
    all (a schema this hasn't seen, or an older cached list) must not
    suddenly refuse every download."""
    payload, dest_dir, srv = _voice_download_fixture(tmp_path, monkeypatch, None)
    try:
        ok, msg = tts.download_voice("stem")
        assert ok is True
        assert (dest_dir / "voice.onnx").is_file()
    finally:
        srv.shutdown()

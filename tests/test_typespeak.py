"""Tests for voxfox_core.typespeak (the Type and speak window's logic)."""
from voxfox_core import typespeak as ts


def test_word_before_plain():
    assert ts.word_before("Hallo daar") == "daar"


def test_word_before_trailing_space_and_punctuation():
    assert ts.word_before("Hallo daar ") == "daar"
    assert ts.word_before("Hoe gaat het?") == "het"
    assert ts.word_before("Ja, ") == "Ja"


def test_word_before_keeps_inner_hyphen_and_apostrophe():
    assert ts.word_before("stuur een e-mail") == "e-mail"
    assert ts.word_before("zo'n") == "zo'n"
    assert ts.word_before("het is 2026") == "2026"


def test_word_before_empty():
    assert ts.word_before("") == ""
    assert ts.word_before("   ") == ""
    assert ts.word_before("...") == ""


def test_word_before_accents():
    assert ts.word_before("café één") == "één"


def test_is_word_end():
    assert ts.is_word_end(" ")
    assert ts.is_word_end(".")
    assert ts.is_word_end("\n")
    assert not ts.is_word_end("a")
    assert not ts.is_word_end("")


def test_push_recent_newest_first_and_dedup():
    items = ts.push_recent([], "Goedemorgen")
    items = ts.push_recent(items, "Ik wil koffie")
    items = ts.push_recent(items, "Goedemorgen")
    assert items == ["Goedemorgen", "Ik wil koffie"]


def test_push_recent_cap_and_blank():
    items = []
    for i in range(15):
        items = ts.push_recent(items, f"zin {i}")
    assert len(items) == ts.TYPE_RECENT_SIZE
    assert items[0] == "zin 14"
    assert ts.push_recent(items, "   ") == items


def test_push_recent_ignores_junk():
    assert ts.push_recent([None, 3, "", "a"], "b") == ["b", "a"]


def test_clamp_type_font():
    assert ts.clamp_type_font(5) == ts.TYPE_FONT_MIN
    assert ts.clamp_type_font(500) == ts.TYPE_FONT_MAX
    assert ts.clamp_type_font("x") == 26
    assert ts.clamp_type_font(30) == 30


def test_finished_word_only_once_after_punctuation():
    # "zo," then a space: the comma finished "zo", the space finishes nothing
    assert ts.finished_word("goed zo") == "zo"
    assert ts.finished_word("goed zo,") == ""
    assert ts.finished_word("") == ""
    assert ts.finished_word("e-mail") == "e-mail"


# ── tiles ──

def test_default_tiles_dutch_example_sentence():
    tiles = ts.default_tiles("nl")
    words = [t["text"] for t in tiles]
    for w in ("Ik", "heb", "dorst"):
        assert w in words
    assert "Ik heb dorst" in words          # example sentence
    assert all(t["kind"] in ts.TILE_KINDS for t in tiles)


def test_default_tiles_fallback_and_variants():
    en = ts.default_tiles("en")
    assert ts.default_tiles("pl") == en
    assert ts.default_tiles(None) == en
    assert ts.default_tiles("de_DE")[0]["text"] == "Ich habe Durst"


def test_every_board_has_every_kind():
    for code in ("nl", "en", "de", "fr", "es"):
        kinds = {t["kind"] for t in ts.default_tiles(code)}
        assert kinds == set(ts.TILE_KINDS), code


def test_add_word_builds_sentence():
    s = ""
    for w in ("Ik", "heb", "dorst"):
        s = ts.add_word(s, w)
    assert s == "Ik heb dorst"
    assert ts.add_word("Wat wil je", "?") == "Wat wil je?"
    assert ts.add_word("Ja ", "  graag ") == "Ja graag"
    assert ts.add_word("x", "") == "x"


def test_remove_last_word():
    assert ts.remove_last_word("Ik heb dorst") == "Ik heb"
    assert ts.remove_last_word("Wat?") == "Wat"
    assert ts.remove_last_word("Ik ") == ""
    assert ts.remove_last_word("") == ""


def test_normalize_tiles():
    assert ts.normalize_tiles(None) is None
    assert ts.normalize_tiles("x") is None
    assert ts.normalize_tiles([]) == []
    got = ts.normalize_tiles([{"text": "  a   b ", "kind": "zzz"},
                              {"text": ""}, "junk", {"kind": "person"},
                              {"text": "Ik", "kind": "person"}])
    assert got == [{"text": "a b", "kind": "thing"},
                   {"text": "Ik", "kind": "person"}]
    long = ts.normalize_tiles([{"text": "x" * 500, "kind": "thing"}] * 500)
    assert len(long) == ts.TILE_MAX and len(long[0]["text"]) == ts.TILE_TEXT_MAX


def test_move_tile():
    tiles = ["a", "b", "c"]
    assert ts.move_tile(tiles, 0, 1) == (["b", "a", "c"], 1)
    assert ts.move_tile(tiles, 2, 1) == (["a", "b", "c"], 2)
    assert ts.move_tile(tiles, 1, -5) == (["b", "a", "c"], 0)
    assert ts.move_tile(tiles, 9, 1) == (tiles, 9)


# ── tile pictures ──

def test_safe_image_name():
    assert ts.is_safe_image_name("tile-abc.png")
    assert ts.is_safe_image_name("Foto.JPG")
    for bad in ("../x.png", "a/b.png", "a\\b.png", ".hidden.png", "x.exe",
                "", None, 5, "x" * 200 + ".png", "a\0.png"):
        assert not ts.is_safe_image_name(bad), bad


def test_image_file_name_from_contents():
    a = ts.image_file_name(b"abc", ".jpeg")
    assert a.startswith("tile-") and a.endswith(".jpg")
    assert a == ts.image_file_name(b"abc", "jpg")
    assert a != ts.image_file_name(b"abd", ".jpg")
    assert ts.is_safe_image_name(a)


def test_target_sides_keeps_shape_and_never_grows():
    sides = ts.target_sides(2000, 1000)
    assert sides[0] == (384, 192)
    assert all(w == 2 * h for w, h in sides)
    assert ts.target_sides(100, 50)[0] == (100, 50)      # small: not enlarged
    assert len(set(ts.target_sides(50, 50))) == len(ts.target_sides(50, 50))


def _fake_encoder(calls):
    def encode(w, h, fmt, q):
        calls.append((w, fmt, q))
        return b"x" * (w * h if fmt == "png" else w * h * q // 400)
    return encode


def test_pick_encoding_icon_stays_png_when_possible():
    calls = []
    data, ext = ts.pick_encoding([(384, 384), (256, 256), (128, 128)],
                                 _fake_encoder(calls), has_alpha=True,
                                 limit=20000)
    assert ext == ".png" and len(data) == 128 * 128
    assert all(fmt == "png" for _w, fmt, _q in calls)


def test_pick_encoding_icon_falls_back_to_jpeg():
    calls = []
    data, ext = ts.pick_encoding([(384, 384), (256, 256), (128, 128)],
                                 _fake_encoder(calls), has_alpha=True,
                                 limit=10000)
    assert ext == ".jpg" and len(data) <= 10000


def test_pick_encoding_photo_largest_jpeg_that_fits():
    calls = []
    data, ext = ts.pick_encoding([(384, 384), (256, 256), (128, 128)],
                                 _fake_encoder(calls), has_alpha=False,
                                 limit=20000)
    assert ext == ".jpg" and len(data) == 256 * 256 * 85 // 400
    assert all(fmt == "jpeg" for _w, fmt, _q in calls)


def test_pick_encoding_photo_skips_png_and_can_fail():
    seen = []

    def encode(w, h, fmt, q):
        seen.append(fmt)
        return b"x" * 10 ** 6
    assert ts.pick_encoding([(64, 64)], encode, has_alpha=False) == (None, None)
    assert "png" not in seen


def test_normalize_keeps_safe_picture_only():
    got = ts.normalize_tiles([
        {"text": "a", "kind": "thing", "image": "tile-1.png", "image_pos": "right"},
        {"text": "b", "kind": "thing", "image": "../etc/passwd.png"},
        {"text": "c", "kind": "thing", "image": "x.png", "image_pos": "up"}])
    assert got[0] == {"text": "a", "kind": "thing", "image": "tile-1.png",
                      "image_pos": "right"}
    assert "image" not in got[1]
    assert got[2]["image_pos"] == "left"


def test_image_dir():
    assert ts.image_dir({}) is None
    assert ts.image_dir({"type_image_dir": "~/x"}).endswith("/x")


def test_picture_start_folder_prefers_last_used(tmp_path):
    last, pics = tmp_path / "tegels", tmp_path / "Afbeeldingen"
    last.mkdir(); pics.mkdir()
    st = {}
    assert ts.picture_start_folder(st, str(pics)) == str(pics)
    assert ts.remember_picture_folder(st, str(last / "glas.png")) is True
    assert ts.remember_picture_folder(st, str(last / "huis.png")) is False
    assert ts.picture_start_folder(st, str(pics)) == str(last)


def test_picture_start_folder_when_last_is_gone(tmp_path):
    st = {"type_last_picture_dir": str(tmp_path / "weg")}
    assert ts.picture_start_folder(st, str(tmp_path)) == str(tmp_path)
    assert ts.picture_start_folder(st, None) is None


# ── pictograms on the ready-made tiles (6.2) ───────────────────────────────
import os as _os

_ICON_DIR = _os.path.join(_os.path.dirname(__file__), "..", "icons", "tiles")


def test_every_ready_made_tile_has_a_shipped_pictogram():
    shipped = {f[:-4] for f in _os.listdir(_ICON_DIR) if f.endswith(".svg")}
    for code in ("nl", "en", "de", "fr", "es"):
        for t in ts.default_tiles(code):
            assert ts.is_icon_name(t.get("image")), (code, t["text"])
            assert t["image"][len(ts.ICON_PREFIX):] in shipped, (code, t["text"])
            assert t["image_pos"] == "left"


def test_pictograms_shared_between_languages():
    assert ts.default_icon("nl", "dorst") == "icon:dorst"
    assert ts.default_icon("en", "thirsty") == "icon:dorst"
    assert ts.default_icon("de", "Durst") == "icon:dorst"
    assert ts.default_icon("es", "No") == "icon:nee"
    assert ts.default_icon("es", "no") == "icon:niet"
    assert ts.default_icon("nl", "?") == "icon:vraagteken"
    assert ts.default_icon("nl", "fiets") is None


def test_icon_names_cannot_leave_the_folder():
    for bad in ("icon:../x", "icon:", "icon:a/b", "icon:Dorst", "dorst",
                "icon:" + "a" * 41, None, 5):
        assert not ts.is_icon_name(bad)
    assert ts.normalize_tiles([{"text": "x", "image": "icon:../../etc"}]) \
        == [{"text": "x", "kind": "thing"}]
    assert ts.normalize_tiles([{"text": "x", "image": "icon:dorst"}]) \
        == [{"text": "x", "kind": "thing", "image": "icon:dorst",
             "image_pos": "left"}]


def test_add_default_icons_to_an_old_board():
    old = [{"text": "Ik", "kind": "person"},
           {"text": "fiets", "kind": "thing"},
           {"text": "dorst", "kind": "thing", "image": "tile-0123456789abcdef.png",
            "image_pos": "right"}]
    new, n = ts.add_default_icons(old, "nl")
    assert n == 1
    assert new[0]["image"] == "icon:ik" and new[0]["image_pos"] == "left"
    assert "image" not in new[1]
    assert new[2]["image"] == "tile-0123456789abcdef.png"   # own picture kept
    assert "image" not in old[0]                             # input untouched


def test_move_tile_to():
    t = [{"text": c, "kind": "thing"} for c in "abcde"]
    txt = lambda ts_: "".join(x["text"] for x in ts_)  # noqa: E731
    assert txt(ts.move_tile_to(t, 0, 3)) == "bcdae"
    assert txt(ts.move_tile_to(t, 4, 1)) == "aebcd"
    assert txt(ts.move_tile_to(t, 2, 2)) == "abcde"
    assert txt(ts.move_tile_to(t, 9, 1)) == "abcde"
    assert txt(ts.move_tile_to(t, 1, -1)) == "abcde"
    assert txt(t) == "abcde"


# ── loading and saving a board (6.2, review fixes) ─────────────────────────

def test_new_user_removed_pictogram_stays_removed():
    state = {}
    tiles, changed = ts.load_board(state, "nl")
    assert not changed and tiles[6]["text"] == "Ja" and tiles[6]["image"] == "icon:ja"
    tiles[6] = {"text": "Ja", "kind": "social"}          # "No picture"
    ts.save_board(state, "nl", tiles)
    again, changed = ts.load_board(state, "nl")
    assert not changed
    assert "image" not in again[6]


def test_board_from_6_1_gets_pictograms_once():
    state = {"type_tiles": {"nl": [{"text": "Ik", "kind": "person"},
                                   {"text": "fiets", "kind": "thing"}]}}
    tiles, changed = ts.load_board(state, "nl")
    assert changed and tiles[0]["image"] == "icon:ik"
    assert state["type_icons_added"] == ["nl"]
    assert state["type_tiles"]["nl"][0]["image"] == "icon:ik"
    tiles[0] = {"text": "Ik", "kind": "person"}
    ts.save_board(state, "nl", tiles)
    again, changed = ts.load_board(state, "nl")
    assert not changed and "image" not in again[0]


def test_boards_are_kept_per_language():
    state = {}
    ts.save_board(state, "nl", [{"text": "hoi", "kind": "social"}])
    ts.save_board(state, "en", [{"text": "hi", "kind": "social"}])
    assert ts.load_board(state, "nl")[0][0]["text"] == "hoi"
    assert ts.load_board(state, "en")[0][0]["text"] == "hi"
    assert ts.load_board(state, "de")[0] == ts.default_tiles("de")
    ts.save_board(state, "nl", [])
    assert ts.load_board(state, "nl")[0] == []           # all removed on purpose


# ── button icons must also work with GTK 4.22+ (6.2.1) ─────────────────────
# GTK 4.22 and newer read symbolic icons with their own parser, which
# ignores fill="none" and stroke="...": without these classes every outline
# became a filled blob (seen on Fedora). Each shape needs a class.

def test_symbolic_icons_have_gtk_classes():
    import re
    folder = _os.path.join(_os.path.dirname(__file__), "..", "icons",
                           "hicolor", "scalable", "actions")
    files = [f for f in _os.listdir(folder) if f.endswith("-symbolic.svg")]
    assert files
    for f in files:
        svg = open(_os.path.join(folder, f), encoding="utf-8").read()
        assert "<g" not in svg, f            # classes on <g> are not inherited
        for shape in re.findall(r"<(?:path|rect|circle)\b[^>]*>", svg):
            if 'stroke="' in shape:
                assert 'class="transparent-fill foreground-stroke"' in shape, f
            else:
                assert 'class="foreground-fill"' in shape, f

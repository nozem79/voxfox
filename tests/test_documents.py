"""Tests for voxfox_core.documents: the on-disk document library (adding a
document, tracking reading position, moving the whole library to a new
folder). Every test gets its own tmp_path, so nothing here touches the
real user's home directory.
"""

import os
import stat

import voxfox_core.documents as docs


def test_add_and_read_back(tmp_path):
    folder = str(tmp_path)
    entry = docs.add(folder, "Titelregel\ninhoud hier")
    assert entry is not None
    assert entry["title"] == "Titelregel"
    assert docs.read_text(folder, entry) == "Titelregel\ninhoud hier"


def test_add_uses_explicit_title_when_given(tmp_path):
    entry = docs.add(str(tmp_path), "Tekst", title="mijn-bestand")
    assert entry["title"] == "mijn-bestand"


def test_add_empty_text_returns_none(tmp_path):
    assert docs.add(str(tmp_path), "") is None
    assert docs.add(str(tmp_path), "   ") is None


def test_identical_text_is_always_a_new_document(tmp_path):
    folder = str(tmp_path)
    a = docs.add(folder, "Zelfde inhoud")
    b = docs.add(folder, "Zelfde inhoud")
    assert a["file"] != b["file"]
    assert len(docs.load_index(folder)) == 2


def test_load_index_on_empty_or_missing_folder():
    assert docs.load_index("/nonexistent/path/xyz") == []


def test_load_index_survives_a_corrupt_index_file(tmp_path):
    folder = str(tmp_path)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, docs.INDEX_NAME), "w") as f:
        f.write("{not valid json")
    assert docs.load_index(folder) == []


def test_load_index_survives_index_that_is_not_a_list(tmp_path):
    folder = str(tmp_path)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, docs.INDEX_NAME), "w") as f:
        f.write('{"not": "a list"}')
    assert docs.load_index(folder) == []


def test_a_manually_deleted_file_drops_out_of_the_index(tmp_path):
    folder = str(tmp_path)
    entry = docs.add(folder, "Wordt handmatig verwijderd")
    os.unlink(os.path.join(folder, entry["file"]))
    assert docs.load_index(folder) == []


def test_set_position_and_progress(tmp_path):
    folder = str(tmp_path)
    entry = docs.add(folder, "x" * 100)
    docs.set_position(folder, entry["file"], 40)
    idx = docs.load_index(folder)[0]
    assert idx["offset"] == 40
    assert docs.progress(idx) == 0.4


def test_position_past_the_end_resets_to_zero(tmp_path):
    """A document read to the end should start over next time, not sit on
    its last sentence forever."""
    folder = str(tmp_path)
    entry = docs.add(folder, "x" * 20)
    result = docs.set_position(folder, entry["file"], 999, 20)
    assert result == 0
    assert docs.load_index(folder)[0]["offset"] == 0


def test_set_position_on_unknown_document_is_a_safe_no_op(tmp_path):
    assert docs.set_position(str(tmp_path), "does-not-exist.txt", 5) is None


def test_progress_with_zero_length_is_zero():
    assert docs.progress({"offset": 10, "length": 0}) == 0.0


def test_delete_removes_file_and_index_entry(tmp_path):
    folder = str(tmp_path)
    entry = docs.add(folder, "Weg ermee")
    docs.delete(folder, entry["file"])
    assert docs.load_index(folder) == []
    assert not os.path.isfile(os.path.join(folder, entry["file"]))


def test_delete_of_unknown_file_does_not_raise(tmp_path):
    docs.delete(str(tmp_path), "bestaat-niet.txt")  # must not raise


def test_move_library_preserves_position_and_content(tmp_path):
    old = str(tmp_path / "oud")
    new = str(tmp_path / "nieuw")
    entry = docs.add(old, "Inhoud die moet blijven")
    docs.set_position(old, entry["file"], 5)

    moved, failed = docs.move_library(old, new)

    assert moved == 1
    assert failed == 0
    assert docs.load_index(old) == []
    new_entry = docs.load_index(new)[0]
    assert new_entry["offset"] == 5
    assert docs.read_text(new, new_entry) == "Inhoud die moet blijven"
    mode = stat.S_IMODE(os.stat(os.path.join(new, new_entry["file"])).st_mode)
    assert mode == 0o600


def test_move_library_to_same_folder_is_a_no_op(tmp_path):
    folder = str(tmp_path)
    docs.add(folder, "iets")
    assert docs.move_library(folder, folder) == (0, 0)


def test_move_library_avoids_overwriting_a_same_named_file(tmp_path):
    old = str(tmp_path / "oud")
    new = str(tmp_path / "nieuw")
    a = docs.add(old, "Bestand A")
    # Force a same-named file to already exist in the destination -- not
    # through docs.add(), so it is a plain file on disk, not a tracked
    # document; what matters is that move_library never overwrites it.
    os.makedirs(new, exist_ok=True)
    preexisting_path = os.path.join(new, a["file"])
    with open(preexisting_path, "w") as f:
        f.write("Al aanwezig, mag niet overschreven worden")

    moved, failed = docs.move_library(old, new)
    assert moved == 1
    assert failed == 0
    # The pre-existing file is untouched.
    assert open(preexisting_path).read() == "Al aanwezig, mag niet overschreven worden"
    # The moved document landed under a different name, with its content intact.
    idx = docs.load_index(new)
    assert len(idx) == 1
    assert idx[0]["file"] != a["file"]
    assert docs.read_text(new, idx[0]) == "Bestand A"


def test_move_library_when_source_is_empty(tmp_path):
    old = str(tmp_path / "leeg")
    new = str(tmp_path / "nieuw")
    assert docs.move_library(old, new) == (0, 0)


def test_default_dir_is_under_documents():
    d = docs.default_dir()
    assert d.endswith(os.path.join("VoxFox"))


def test_library_dir_honours_docs_dir_setting(tmp_path):
    custom = str(tmp_path / "eigen-map")
    assert docs.library_dir({"docs_dir": custom}) == custom
    assert docs.library_dir({"docs_dir": None}) == docs.default_dir()
    assert docs.library_dir({}) == docs.default_dir()

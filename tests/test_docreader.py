"""Tests for voxfox_core.docreader: reading Word/OpenDocument/RTF/plain-text
files directly (not via OCR). Builds real .docx/.odt files with the
standard library's own zipfile/xml tools rather than relying on fixture
binaries, so the tests show exactly what structure they exercise.
"""

import zipfile

import pytest

import voxfox_core.docreader as dr


# ── .docx ──────────────────────────────────────────────────────────────────

def _make_docx(path, document_xml):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                   'Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", document_xml)


_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_docx_basic_paragraphs(tmp_path):
    p = tmp_path / "voorbeeld.docx"
    _make_docx(p, f'''<?xml version="1.0"?><w:document {_W}><w:body>
        <w:p><w:r><w:t>Titel van het document</w:t></w:r></w:p>
        <w:p><w:r><w:t>Eerste alinea.</w:t></w:r></w:p>
    </w:body></w:document>''')
    text, err = dr.read_document(str(p))
    assert err is None
    assert text == "Titel van het document\n\nEerste alinea."


def test_docx_hard_line_break_becomes_a_space_not_a_new_paragraph():
    p_text = '<w:p><w:r><w:t>Regel een</w:t></w:r><w:br/><w:r><w:t>regel twee</w:t></w:r></w:p>'
    import tempfile, os
    tmp = os.path.join(tempfile.mkdtemp(), "t.docx")
    _make_docx(tmp, f'<?xml version="1.0"?><w:document {_W}><w:body>{p_text}</w:body></w:document>')
    text, err = dr.read_document(tmp)
    assert err is None
    assert text == "Regel een regel twee"


def test_docx_corrupt_file_gives_a_clean_error(tmp_path):
    p = tmp_path / "kapot.docx"
    p.write_text("dit is helemaal geen zip-bestand")
    text, err = dr.read_document(str(p))
    assert err is not None
    assert text == ""


# ── .odt ───────────────────────────────────────────────────────────────────

def _make_odt(path, content_xml):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content_xml)


_ODT_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')


def test_odt_heading_and_list_items(tmp_path):
    p = tmp_path / "voorbeeld.odt"
    _make_odt(p, f'''<?xml version="1.0"?>
        <office:document-content {_ODT_NS}><office:body><office:text>
        <text:h>Kop van het document</text:h>
        <text:p>Eerste alinea.</text:p>
        <text:list>
          <text:list-item><text:p>eerste punt</text:p></text:list-item>
          <text:list-item><text:p>tweede punt</text:p></text:list-item>
        </text:list>
        </office:text></office:body></office:document-content>''')
    text, err = dr.read_document(str(p))
    assert err is None
    assert text.split("\n\n") == [
        "Kop van het document", "Eerste alinea.", "eerste punt", "tweede punt"]


def test_odt_footnote_is_skipped_not_duplicated_or_inlined(tmp_path):
    """Regression test found during code review: a footnote is anchored
    inline inside the paragraph it belongs to, with its own nested <text:p>
    for the note body. Before the fix, that nested paragraph both leaked
    into the middle of the surrounding sentence AND was picked up a second
    time as a block of its own."""
    p = tmp_path / "voetnoot.odt"
    _make_odt(p, f'''<?xml version="1.0"?>
        <office:document-content {_ODT_NS}><office:body><office:text>
        <text:p>Hoofdtekst met een voetnoot<text:note text:note-class="footnote">
          <text:note-citation>1</text:note-citation>
          <text:note-body><text:p>De voetnoottekst zelf.</text:p></text:note-body>
        </text:note> erin, en gaat door.</text:p>
        <text:p>Tweede, gewone alinea.</text:p>
        </office:text></office:body></office:document-content>''')
    text, err = dr.read_document(str(p))
    assert err is None
    assert "De voetnoottekst zelf." not in text
    assert text == ("Hoofdtekst met een voetnoot erin, en gaat door."
                    "\n\nTweede, gewone alinea.")


def test_odt_comment_is_skipped(tmp_path):
    p = tmp_path / "opmerking.odt"
    _make_odt(p, f'''<?xml version="1.0"?>
        <office:document-content {_ODT_NS}><office:body><office:text>
        <text:p>Tekst met een<office:annotation><text:p>Kantlijnopmerking.</text:p>
        </office:annotation> opmerking erin.</text:p>
        </office:text></office:body></office:document-content>''')
    text, err = dr.read_document(str(p))
    assert err is None
    assert "Kantlijnopmerking" not in text
    assert text == "Tekst met een opmerking erin."


def test_odt_corrupt_file_gives_a_clean_error(tmp_path):
    p = tmp_path / "kapot.odt"
    p.write_text("ook geen zip-bestand")
    text, err = dr.read_document(str(p))
    assert err is not None
    assert text == ""


# ── .rtf ───────────────────────────────────────────────────────────────────

def test_rtf_strips_font_table_and_decodes_escapes(tmp_path):
    p = tmp_path / "voorbeeld.rtf"
    p.write_bytes((
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}{\colortbl;\red0\green0\blue0;}"
        r"\pard Titel met een \'e9 accent en een \u8364? euroteken.\par"
        r"\par Tweede alinea.\par}"
    ).encode("latin-1"))
    text, err = dr.read_document(str(p))
    assert err is None
    assert "Arial" not in text
    assert "Titel met een \u00e9 accent" in text
    assert "euroteken" in text
    assert "\\" not in text and "{" not in text and "}" not in text


def test_rtf_nested_braces_in_font_table_are_fully_skipped(tmp_path):
    """Regression: a flat regex couldn't handle a nested group like
    {\\fonttbl{\\f0 Arial;}} and left "Arial;" leaking into the text."""
    p = tmp_path / "genest.rtf"
    p.write_bytes((
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}{\f1 Times;}}"
        r"\pard Alleen deze tekst hoort over te blijven.\par}"
    ).encode("latin-1"))
    text, err = dr.read_document(str(p))
    assert err is None
    assert "Arial" not in text and "Times" not in text
    assert "Alleen deze tekst hoort over te blijven." in text


def test_rtf_destination_group_is_removed(tmp_path):
    p = tmp_path / "gen.rtf"
    p.write_bytes((
        r"{\rtf1\ansi\deff0{\*\generator VoxFoxTest;}\pard Zin een.\par}"
    ).encode("latin-1"))
    text, err = dr.read_document(str(p))
    assert err is None
    assert "VoxFoxTest" not in text
    assert "Zin een." in text


def test_rtf_rejects_a_non_rtf_file(tmp_path):
    p = tmp_path / "nep.rtf"
    p.write_text("dit begint niet met {\\rtf")
    text, err = dr.read_document(str(p))
    assert err is not None
    assert text == ""


# ── plain text ─────────────────────────────────────────────────────────────

def test_plain_txt(tmp_path):
    p = tmp_path / "voorbeeld.txt"
    p.write_text("Regel een.\n\nRegel twee.\n", encoding="utf-8")
    text, err = dr.read_document(str(p))
    assert err is None
    assert text == "Regel een.\n\nRegel twee."


def test_plain_md_is_read_as_is_not_rendered(tmp_path):
    p = tmp_path / "voorbeeld.md"
    p.write_text("# Kop\n\n**vet**", encoding="utf-8")
    text, err = dr.read_document(str(p))
    assert err is None
    assert text == "# Kop\n\n**vet**"


def test_empty_txt_file(tmp_path):
    p = tmp_path / "leeg.txt"
    p.write_text("")
    text, err = dr.read_document(str(p))
    assert err is None
    assert text == ""


# ── unsupported / dispatch ──────────────────────────────────────────────────

@pytest.mark.parametrize("ext", [".doc", ".wpd"])
def test_known_unsupported_extensions_explain_why(tmp_path, ext):
    p = tmp_path / f"oud{ext}"
    p.write_bytes(b"irrelevant")
    text, err = dr.read_document(str(p))
    assert err is not None
    assert text == ""


def test_fully_unknown_extension(tmp_path):
    p = tmp_path / "iets.xyz"
    p.write_bytes(b"irrelevant")
    text, err = dr.read_document(str(p))
    assert err is not None
    assert "xyz" in err

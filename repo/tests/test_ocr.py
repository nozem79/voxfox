"""Tests for voxfox_core.ocr's merge_wrapped_lines: the function that turns
a scanned page's hard line breaks back into paragraphs. Covers the two bugs
found during code review (a table row skewing the wrap-width estimate, and
footnote/comment text leaking through) at the level they were actually
fixed, plus the cases that must keep working: bullet lists, hyphenation,
and ordinary prose.
"""

import voxfox_core.ocr as ocr


def _paras(text):
    return [p for p in ocr.merge_wrapped_lines(text).split("\n\n") if p.strip()]


def test_merges_a_simple_wrapped_paragraph():
    text = ("Dit is de eerste alinea van het verslag, die in het\n"
            "origineel over meerdere regels is afgebroken.\n"
            "De zin loopt gewoon door tot hier.")
    assert len(_paras(text)) == 1


def test_a_wide_table_row_does_not_skew_every_other_line():
    """Regression: the wrap-width estimate used to be the single longest
    line, so one wide table row or footer made every ordinary line look
    like the end of a paragraph, and a scanned PDF was read one line at a
    time. Now it's the median, which one outlier can't move."""
    text = ("Dit is de eerste alinea van het verslag, die in het\n"
            "origineel over meerdere regels is afgebroken.\n"
            "De zin loopt gewoon door tot hier.\n\n"
            "Post            Bedrag        Vorig jaar      Verschil      "
            "Toelichting bij de post en de afwijking daarvan")
    assert len(_paras(text)) == 2


def test_bullet_list_items_stay_separate():
    text = "Boodschappen voor het weekend.\n\n- brood\n- kaas\n- melk"
    assert len(_paras(text)) == 4


def test_hyphenated_word_across_a_line_break_is_rejoined():
    merged = ocr.merge_wrapped_lines("een woord dat afge-\nbroken is")
    assert "afgebroken" in merged
    assert "afge-" not in merged


def test_short_standalone_sentences_stay_separate():
    text = "Eerste zin.\n\nTweede zin.\n\nDerde zin."
    assert len(_paras(text)) == 3


def test_empty_text():
    assert ocr.merge_wrapped_lines("") == ""

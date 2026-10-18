"""The voice preview's sample sentence: translated into every language, and
looked up in the slot's language rather than the interface language."""

import json
import os

import pytest

import voxfox_core.common as common

LOCALES = os.path.join(os.path.dirname(__file__), os.pardir, "locales")


@pytest.fixture
def translations(monkeypatch):
    monkeypatch.setattr(common, "LOCALES_DIR", os.path.abspath(LOCALES))
    common.app.load_translations()
    yield
    common.app.translations = {}
    common.app.lang = "en"


def test_every_locale_translates_the_sample_sentence():
    for fname in sorted(os.listdir(LOCALES)):
        if not fname.endswith(".json") or fname == "en.json":
            continue
        with open(os.path.join(LOCALES, fname), encoding="utf-8") as fh:
            value = json.load(fh).get(common.SAMPLE_TEXT, "")
        assert value.strip(), fname
        assert value != common.SAMPLE_TEXT, fname


def test_sample_follows_the_slot_language_not_the_interface(translations):
    common.app.set_language("de")          # interface in German
    assert common.sample_text_for_lang("Dutch") == \
        "Dit is een voorbeeldstem, klinkt dit goed?"
    assert common.sample_text_for_lang("English") == common.SAMPLE_TEXT


def test_language_without_a_locale_falls_back_to_english(translations):
    assert common.sample_text_for_lang("Klingon") == common.SAMPLE_TEXT
    assert common.sample_text_for_lang("") == common.SAMPLE_TEXT

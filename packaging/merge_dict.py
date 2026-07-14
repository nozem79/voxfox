#!/usr/bin/env python3
"""Merge community pronunciation submissions into the bundled dictionaries.

Workflow: submissions from the voxfox.nl form arrive by e-mail. Collect them
in a CSV file (one per line, ';' or ',' separated, header optional):

    taal;woord;uitspraak
    Dutch;GUI;goe wie
    nl;OCR;oo see er
    German;GUI;ge uu ie

The language may be the English Piper name (Dutch, German, ...) or the
two-letter code (nl, de, ...). Then run, from the repository root:

    python3 packaging/merge_dict.py inzendingen.csv

New words are added to dicts/<code>.json and existing words updated; the
script prints a report per language. Review the diff with git before
committing — submissions are community input, not gospel.
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DICTS = os.path.join(ROOT, "dicts")

# English Piper name → code, mirrored from voxfox_core.common.
LANGS = {
    "english": "en", "dutch": "nl", "german": "de", "french": "fr",
    "spanish": "es", "italian": "it", "portuguese": "pt", "chinese": "zh",
    "arabic": "ar", "greek": "el",
}
CODES = set(LANGS.values())
NAME_FOR_CODE = {v: k.capitalize() for k, v in LANGS.items()}


def norm_lang(raw):
    raw = (raw or "").strip().lower()
    if raw in CODES:
        return raw
    return LANGS.get(raw)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]

    per_lang = {}   # code -> {word: pron}
    skipped = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        for i, row in enumerate(csv.reader(f, delimiter=delim), 1):
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) < 3:
                skipped.append((i, "te weinig kolommen"))
                continue
            lang, word, pron = (c.strip() for c in row[:3])
            if i == 1 and lang.lower() in ("taal", "language"):
                continue    # header
            code = norm_lang(lang)
            if not code:
                skipped.append((i, f"onbekende taal {lang!r}"))
                continue
            if not word or not pron:
                skipped.append((i, "leeg woord of lege uitspraak"))
                continue
            per_lang.setdefault(code, {})[word] = pron

    os.makedirs(DICTS, exist_ok=True)
    for code, rules in sorted(per_lang.items()):
        dict_path = os.path.join(DICTS, f"{code}.json")
        if os.path.isfile(dict_path):
            data = json.load(open(dict_path, encoding="utf-8"))
            cur = data.get("rules", {})
        else:
            cur = {}
        new = sum(1 for k in rules if k not in cur)
        upd = sum(1 for k in rules if k in cur and cur[k] != rules[k])
        cur.update(rules)
        data = {
            "_meta": {"format": 1,
                      "language": NAME_FOR_CODE.get(code, code),
                      "generator": "VoxFox"},
            "rules": dict(sorted(cur.items(), key=lambda kv: kv[0].lower())),
        }
        with open(dict_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{dict_path}: +{new} nieuw, {upd} bijgewerkt, "
              f"totaal {len(cur)} regels")

    for line, reason in skipped:
        print(f"  overgeslagen (regel {line}): {reason}")


if __name__ == "__main__":
    main()

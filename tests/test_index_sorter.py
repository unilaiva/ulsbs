# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure record sorting, Unicode collation and actionable diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/ulsbs/assets/tex/ulsbs-index.lua"
RUNNER = r'''
local module = dofile(arg[1])
local records = dofile(arg[2])
local definitions = dofile(arg[3])
assert(os.setlocale(arg[5]))
local before = os.setlocale()
local open, locale = io.open, os.setlocale
io.open = function() error("sorter attempted filesystem access") end
os.setlocale = function() error("sorter attempted locale access") end
local ok, result = pcall(module.render, records, arg[4], definitions)
if ok then
  assert(result == module.render(records, arg[4], definitions), "render is not repeatable")
  module.render({{title="Unrelated", label="1", target="other", ordinal=1, line=1}}, "title")
  assert(result == module.render(records, arg[4], definitions), "sorter retained state")
end
io.open, os.setlocale = open, locale
assert(before == os.setlocale(), "sorter changed process locale")
if not ok then io.stderr:write(result, "\n"); os.exit(1) end
io.write(result)
'''


def lua_string(text):
    # JSON's string escapes match Lua for these inputs; emit Unicode literally.
    return json.dumps(text, ensure_ascii=False)


class IndexSorterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("texlua") is None:
            raise unittest.SkipTest("texlua is not installed")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-sorter-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.runner = self.work / "sorter.lua"
        self.runner.write_text(RUNNER, encoding="utf-8")

    def run_sorter(self, titles, kind="title", definitions=None, locale="C"):
        records = self.work / "records.lua"
        records.write_text("return {" + ",".join(
            "{title=" + lua_string(title) + ",label=" + lua_string(str(n))
            + ",target=" + lua_string(f"link-{n}") + f",ordinal={n},line={n}}}"
            for n, title in enumerate(titles, 1)) + "}", encoding="utf-8")
        path = self.work / "definitions.lua"
        path.write_text("return " + (lua_string(definitions) if definitions is not None else "nil"),
                        encoding="utf-8")
        return subprocess.run(
            ["texlua", str(self.runner), str(MODULE), str(records), str(path), kind, locale],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def render(self, titles, **kwargs):
        result = self.run_sorter(titles, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout.decode()

    def test_unicode_accents_punctuation_and_numeric_order_are_locale_independent(self):
        cases = (
            (["Öinen", "Äiti", "Åland", "Zulu", "Alpha"],
             ["Alpha", "Zulu", "Åland", "Äiti", "Öinen"]),
            (["10 Steps", "2 Steps", "1 Steps"], ["1 Steps", "2 Steps", "10 Steps"]),
            (["Zulu", "Éclair", "Alpha"], ["Alpha", "Éclair", "Zulu"]),
            (["Alpha!", "*Alpha", "Alpha"], ["Alpha!", "Alpha", "Alpha"]),
        )
        for titles, expected in cases:
            for locale in ("C", "C.utf8"):
                with self.subTest(titles=titles, locale=locale):
                    output = self.render(titles, locale=locale)
                    self.assertEqual(re.findall(r"\\ulIndexDisplay(?:Alt)?Entry\{([^}]*)\}", output), expected)
                    for n in range(1, len(titles) + 1):
                        self.assertIn(r"\ulSongLink{link-" + str(n) + "}{" + str(n) + "}", output)

    def test_duplicate_titles_group_links_and_alternate_entries_remain_distinct(self):
        output = self.render(["Apple", "Apple", "*Apple"])
        self.assertEqual(output.count(r"\ulIndexDisplayEntry{Apple}"), 1)
        self.assertIn(r"\ulSongLink{link-1}{1}\\\ulSongLink{link-2}{2}", output)
        self.assertIn(r"\ulIndexDisplayAltEntry{Apple}{\ulSongLink{link-3}{3}}", output)

    def test_tag_aliases_case_duplicates_and_definition_order(self):
        output = self.render(["sound, Z; zed, zeta", "a; SOUND", ""],
                             kind="tag", definitions=" # ordered tags\n zeta | Z | zed \n\n"
                             "% Finnish alias\n Ääni | sound \nalpha|a\n")
        self.assertEqual(re.findall(r"\\begin\{ulIndexBlock\}\{([^}]*)\}", output),
                         ["zeta", "Ääni", "alpha"])
        blocks = output.split(r"\begin{ulIndexBlock}")[1:]
        self.assertEqual(blocks[0].count(r"\ulSongLink{link-1}{1}"), 1)
        self.assertIn(r"\ulSongLink{link-1}{1}\\\ulSongLink{link-2}{2}", blocks[1])
        self.assertIn(r"\ulSongLink{link-2}{2}", blocks[2])
        self.assertNotIn("link-3", output)
        self.assertEqual(output.count("\\ulIndexDisplayEntry{}{"), 3)

    def test_tag_names_with_digits_and_spaces_are_literal_not_scripture_references(self):
        output = self.render(["fire 2; song 1:1, spaced tag"], kind="tag",
                             definitions="fire 2\nsong 1:1\nspaced tag\n")
        self.assertEqual(re.findall(r"\\begin\{ulIndexBlock\}\{([^}]*)\}", output),
                         ["fire 2", "song 1:1", "spaced tag"])
        self.assertEqual(output.count(r"\ulIndexDisplayEntry{}{\ulSongLink{link-1}{1}}"), 3)

    def test_first_alias_definition_wins_and_final_definition_has_empty_entry_text(self):
        output = self.render(["shared; last"], kind="tag",
                             definitions="first|shared\nsecond|SHARED\nlast\n")
        self.assertEqual(output, "\\begin{ulIndexBlock}{first}\n"
                         "\\ulIndexDisplayEntry{}{\\ulSongLink{link-1}{1}}\n"
                         "\\end{ulIndexBlock}\n\\begin{ulIndexBlock}{last}\n"
                         "\\ulIndexDisplayEntry{}{\\ulSongLink{link-1}{1}}\n"
                         "\\end{ulIndexBlock}\n")

    def test_plain_text_tag_headings_escape_tex_special_characters(self):
        output = self.render(["fire & light; under_score; name {literal}"], kind="tag",
                             definitions="fire & light\nunder_score\nname {literal}\n")
        for heading in (r"fire \& light", r"under\_score", r"name \{literal\}"):
            self.assertIn(r"\begin{ulIndexBlock}{" + heading + "}", output)
        self.assertEqual(output.count("\\ulIndexDisplayEntry{}{"), 3)

    def test_empty_indices_render_no_blocks(self):
        self.assertEqual(self.render([]), "")
        self.assertEqual(self.render([], kind="author"), "")
        self.assertEqual(self.render([], kind="tag", definitions="earth\n"), "")

    def test_actionable_errors_do_not_emit_partial_tex(self):
        cases = (
            ([], "invalid", None, "expected title, author or tag"),
            (["Ж"], "title", None, "unsupported collation character U+0416"),
            ([], "tag", None, "tag definitions bytes are required"),
            (["unknown"], "tag", "earth\n", "unknown tag"),
            (["fire x"], "tag", "fire\n", "unknown tag 'fire x'"),
            (["fire 2"], "tag", "fire\n", "unknown tag 'fire 2'"),
            ([], "tag", "# only comments\n", "no definitions"),
            ([], "tag", "earth|\n", "empty alias"),
            ([], "tag", "earth||ground\n", "empty alias"),
            ([], "tag", "|earth\n", "empty alias"),
            ([], "tag", "earth\n1\n", "ulsbs-migrate-syntax-v2"),
            ([], "tag", " 123 \n", "numeric definition"),
            ([], "tag", "earth,ground\n", "tag names cannot contain comma or semicolon"),
            (["fire,,fire"], "tag", "fire\n", "empty tag reference"),
        )
        for titles, kind, definitions, message in cases:
            with self.subTest(message=message):
                result = self.run_sorter(titles, kind, definitions)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr.decode())
                self.assertIn("ULSBS index:", result.stderr.decode())
                self.assertEqual(result.stdout, b"")

    def test_authors_preserve_written_names_and_use_finnish_natural_sort(self):
        names = ["Östen", "Ääni", "Åke", "Zulu", "alice", "Alice",
                 "Person 2001", "Person 1999", "Person 10", "Person 2", "*Alice"]
        for locale in ("C", "C.utf8"):
            output = self.render(names, kind="author", locale=locale)
            self.assertEqual(re.findall(r"\\ulIndexDisplayEntry\{([^}]*)\}", output),
                             ["alice", "Alice", "*Alice", "Person 2", "Person 10",
                              "Person 1999", "Person 2001", "Zulu", "Åke", "Ääni", "Östen"])
            self.assertNotIn("ulIndexDisplayAltEntry", output)

    def test_author_exact_display_groups_survive_interleaved_case_ties(self):
        output = self.render(["Alice", "alice", "Alice", "alice", "*Alice"], kind="author")
        self.assertEqual(output.count(r"\ulIndexDisplayEntry{Alice}"), 1)
        self.assertEqual(output.count(r"\ulIndexDisplayEntry{alice}"), 1)
        self.assertIn(r"\ulSongLink{link-1}{1}\\\ulSongLink{link-3}{3}", output)
        self.assertIn(r"\ulSongLink{link-2}{2}\\\ulSongLink{link-4}{4}", output)
        self.assertIn(r"\ulIndexDisplayEntry{*Alice}", output)

    def test_author_render_preserves_grouping_formatting_and_macro_tokens(self):
        output = self.render([r"{Family, Given}", r"\textbf {Alice and Bob}",
                              r"Eve\&Co.", r"\AuthorName", "The Author"], kind="author")
        for name in (r"{Family, Given}", r"\textbf {Alice and Bob}", r"Eve\&Co.",
                     r"\AuthorName", "The Author"):
            self.assertIn(r"\ulIndexDisplayEntry{" + name + "}", output)
        self.assertIn(r"\begin{ulIndexBlock}{\#}", output)
        self.assertNotIn("Author,~The", output)


if __name__ == "__main__":
    unittest.main()

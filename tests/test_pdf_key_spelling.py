# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Degree-aware spelling in actual PDF layers and isolated effective-text probes."""

from __future__ import annotations

import base64
import re
import shutil
import unittest

from test_pdf_transposition_layers import (
    OPTIONAL_CONTENT_START,
    PdfStructure,
    pdf_command,
    rendered_pages,
    words_and_geometry,
)
from test_tex_integration import compile_fixture


LETTERS = "CDEFGAB"
NATURAL = (0, 2, 4, 5, 7, 9, 11)
MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
MAJOR_TONICS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
MINOR_TONICS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "Bb", "B")
PROBE_KEYS = {
    "C": "C", "G": "G", "Am": "Am", "Fs": "F#", "Dsm": "D#m",
    "Df": "Db", "Bfm": "Bbm", "effectiveD": "D",
    "Cflats": "C", "Csharps": "C",
}


def pitch(note: str) -> int:
    return (NATURAL[LETTERS.index(note[0])] + note.count("#") - note.count("b")) % 12


def signed(value: int) -> int:
    return (value + 6) % 12 - 6


def target_key(key: str, offset: int) -> str:
    minor = key.endswith("m")
    tonic = key[:-1] if minor else key
    return (MINOR_TONICS if minor else MAJOR_TONICS)[(pitch(tonic) + offset) % 12] + ("m" if minor else "")


def degree_spelling(key: str, note: str, offset: int) -> str | None:
    """Independent letter/scale oracle; None denotes a double-accidental fallback."""
    minor = key.endswith("m")
    tonic = key[:-1] if minor else key
    target = target_key(key, offset).removesuffix("m")
    intervals = MINOR if minor else MAJOR
    degree = (LETTERS.index(note[0]) - LETTERS.index(tonic[0])) % 7
    alteration = signed(pitch(note) - pitch(tonic) - intervals[degree])
    letter = (LETTERS.index(target[0]) + degree) % 7
    accidental = signed(pitch(target) + intervals[degree] + alteration - NATURAL[letter])
    if abs(accidental) > 1:
        return None
    return LETTERS[letter] + ("#" if accidental == 1 else "b" if accidental == -1 else "")


def normalize(text: str) -> str:
    return text.replace("\u266f", "#").replace("\u266d", "b").replace("\u266e", "")


def notation_at(words: list[tuple], anchor: str) -> str:
    lyric = next(word for word in words if word[1] == anchor)
    notation = [word for word in words if word[0] == lyric[0] and word[1] != "page"
                and lyric[3] - 22 <= word[3] < lyric[3] - 1
                and lyric[2] - 1 <= word[2] < lyric[4] + 20
                and re.fullmatch(r"[A-GNa-g0-9#\u266f\u266d/()bmaj]+", word[1])]
    # Accidentals sit above the root baseline; horizontal order, not y order,
    # reconstructs the musical spelling from Poppler's split glyph words.
    return normalize("".join(word[1] for word in sorted(notation, key=lambda word: (word[2], word[3]))))


class DegreeSpellingReferenceTests(unittest.TestCase):
    def test_required_examples_and_enharmonic_tonic_tables(self) -> None:
        self.assertEqual(degree_spelling("C", "F", 5), "Bb")
        self.assertEqual(degree_spelling("C", "G#", 5), "C#")
        self.assertEqual(degree_spelling("G", "F", 10), "Eb")
        self.assertEqual([degree_spelling("Am", note, 3) for note in ("G#", "F#", "G", "F")],
                         ["B", "A", "Bb", "Ab"])
        self.assertEqual([target_key("C", offset) for offset in range(12)], list(MAJOR_TONICS))
        self.assertEqual([target_key("Am", offset) for offset in range(12)],
                         [MINOR_TONICS[(9 + offset) % 12] + "m" for offset in range(12)])


class PdfKeySpellingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [tool for tool in ("lualatex", "qpdf", "pdftotext", "pdftoppm")
                   if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest(f"PDF integration tools are not installed: {', '.join(missing)}")
        cls.output, cls.pdf = compile_fixture("pdf-key-spelling-visible", passes=3)
        cls.disabled_output, cls.disabled = compile_fixture(
            "pdf-key-spelling-visible", passes=3,
            preamble="\\def\\ulPdfTranspositionLayers{false}\n",
        )
        cls.probe_output, _ = compile_fixture("pdf-key-spelling-probes")
        cls.probes = {(case, int(offset), name): result.strip().replace("SHARP", "#").replace("FLAT", "b")
                      for case, offset, name, result in re.findall(
                          r"ULSPELL:([^:\n]+):(\d+):([^:\n]+):([^\n]*)", cls.probe_output)}
        cls.selected_words = {}
        for offset in range(12):
            selected = PdfStructure(cls.pdf).selected_pdf(
                cls.pdf, {song: offset for song in range(1, 9)},
            )
            cls.selected_words[offset] = words_and_geometry(selected)

    def test_exact_degree_spelling_probes_and_pitch_correct_single_accidental_fallback(self) -> None:
        self.assertEqual(len(self.probes), len(PROBE_KEYS) * 11 * 23)
        fallback_count = 0
        for case, key in PROBE_KEYS.items():
            for offset in range(1, 12):
                for letter in LETTERS:
                    for tag, accidental in (("", ""), ("s", "#"), ("f", "b")):
                        note = letter + accidental
                        actual = self.probes[case, offset, letter + tag]
                        with self.subTest(key=key, offset=offset, note=note):
                            self.assertRegex(actual, r"^[A-G][#b]?$")
                            self.assertEqual(pitch(actual), (pitch(note) + offset) % 12)
                            expected = degree_spelling(key, note, offset)
                            if expected is None:
                                fallback_count += 1
                            else:
                                self.assertEqual(actual, expected)
        self.assertGreater(fallback_count, 0, "Exercise degree spellings requiring double accidentals")

    def test_slash_chords_and_extensions_keep_exact_suffixes(self) -> None:
        for case, key in PROBE_KEYS.items():
            for offset in range(1, 12):
                for name, root, suffix, bass in (
                    ("slash", "F", "maj7", "G#"),
                    ("suffix", "G#", "m7(add9)", "F#"),
                ):
                    with self.subTest(key=key, offset=offset, name=name):
                        actual = self.probes[case, offset, name]
                        match = re.fullmatch(r"([A-G][#b]?)(.*)/([A-G][#b]?)", actual)
                        self.assertIsNotNone(match, actual)
                        self.assertEqual(match[2], suffix)
                        for source, result in ((root, match[1]), (bass, match[3])):
                            self.assertEqual(pitch(result), (pitch(source) + offset) % 12)
                            expected = degree_spelling(key, source, offset)
                            if expected is not None:
                                self.assertEqual(result, expected)

    def test_alternative_probes_preserve_source_factor_and_scoped_preferences(self) -> None:
        states = {case: (int(factor), preference, policy)
                  for case, factor, preference, policy in re.findall(
                      r"ULSTATE:([^:\n]+):(-?\d+),(sharp|flat),(auto|fixed)", self.probe_output)}
        self.assertEqual(set(states), set(PROBE_KEYS))
        for case, state in states.items():
            self.assertEqual(state[0], 2 if case == "effectiveD" else 0, case)
        self.assertEqual(states["Cflats"][1:], ("flat", "fixed"))
        self.assertEqual(states["Csharps"][1:], ("sharp", "fixed"))
        for offset in range(1, 12):
            for letter in LETTERS:
                for tag in ("", "s", "f"):
                    self.assertEqual(self.probes["Cflats", offset, letter + tag],
                                     self.probes["Csharps", offset, letter + tag])

    def test_original_default_is_pixel_and_geometry_identical_to_disabled(self) -> None:
        self.assertEqual(rendered_pages(self.pdf), rendered_pages(self.disabled))
        self.assertEqual(words_and_geometry(self.pdf), words_and_geometry(self.disabled))
        self.assertFalse(PdfStructure(self.disabled).layers)
        self.assertNotIn("ocgx2.sty", self.disabled_output)
        words = self.selected_words[0]
        for anchor, expected in (
            ("MajorFour", "F"), ("MajorRaisedFive", "G#"),
            ("MinorRaisedSeven", "G#"), ("MinorRaisedSix", "F#"),
            ("MinorSeven", "G"), ("MinorSix", "F"), ("EffectiveTonic", "D"),
        ):
            self.assertEqual(notation_at(words, anchor), expected, anchor)

    def test_visible_notation_all_twelve_offsets_uses_effective_song_key(self) -> None:
        cases = (
            ("MajorFour", "C", "F"), ("MajorRaisedFive", "C", "G#"),
            ("MajorRawFlat", "C", "Gb"), ("MajorGlyphFlat", "C", "Gb"),
            ("MajorFlatSeven", "G", "F"),
            ("MinorRaisedSeven", "Am", "G#"), ("MinorRaisedSix", "Am", "F#"),
            ("MinorSeven", "Am", "G"), ("MinorSix", "Am", "F"),
            ("EffectiveTonic", "D", "D"),
        )
        for offset, words in self.selected_words.items():
            for anchor, key, note in cases:
                with self.subTest(offset=offset, anchor=anchor):
                    expected = degree_spelling(key, note, offset) if offset else note
                    actual = notation_at(words, anchor)
                    self.assertRegex(actual, r"^[A-G][#b]?$")
                    self.assertEqual(pitch(actual), (pitch(note) + offset) % 12)
                    if expected is not None:
                        self.assertEqual(actual, expected)
            # Degree-preserving slash roots and bass must use the same policy.
            expected_root = degree_spelling("C", "F", offset) if offset else "F"
            expected_bass = degree_spelling("C", "G#", offset) if offset else "G#"
            if expected_root is not None and expected_bass is not None:
                self.assertEqual(notation_at(words, "MajorSlash"), expected_root + "maj7/" + expected_bass)

    def test_visible_melody_circle_and_replay_follow_same_spelling(self) -> None:
        for offset, words in self.selected_words.items():
            for anchor, key, note in (
                ("MajorMelody", "C", "F"), ("MajorAlteredMelody", "C", "G#"),
                ("MajorFlatSevenMelody", "G", "F"), ("EffectiveMelody", "D", "D"),
            ):
                expected = degree_spelling(key, note, offset) if offset else note
                if expected is not None:
                    self.assertEqual(notation_at(words, anchor), expected.lower(), (offset, anchor))
            self.assertEqual(notation_at(words, "MajorStored"), notation_at(words, "MajorReplayed"))
            minor = [degree_spelling("Am", note, offset) if offset else note
                     for note in ("G#", "F#", "G", "F")]
            if all(note is not None for note in minor):
                self.assertEqual(notation_at(words, "MinorMelody"), "".join(minor).lower(), offset)
        self.assertEqual(notation_at(self.selected_words[3], "MinorMelody"), "babbab")

    def test_preferred_major_minor_tonics_in_visible_prelude(self) -> None:
        for offset, words in self.selected_words.items():
            labels = []
            for key_word in (word for word in words if word[1] == "Key:"):
                line = [word for word in words if word[0] == key_word[0] and word[1] != "page"
                        and key_word[2] - 0.1 <= word[2] <= key_word[2] + 65
                        and word[3] < key_word[5] + 2 and word[5] > key_word[3] - 2]
                labels.append(normalize("".join(word[1] for word in sorted(line, key=lambda word: word[2]))))
            keys = ("C", "G", "Am", "D", "F#", "D#m")
            expected = ["Key:" + (target_key(key, offset) if offset else key) for key in keys]
            self.assertEqual(labels[:6], expected, offset)

    def test_absent_and_unsupported_keys_keep_existing_fallback(self) -> None:
        flat_chromatic = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
        for offset, words in self.selected_words.items():
            expected = (flat_chromatic[(5 + offset) % 12] + "maj7/" +
                        flat_chromatic[(8 + offset) % 12]) if offset else "Fmaj7/G#"
            for anchor in ("MissingFallback", "UnsupportedFallback"):
                self.assertEqual(notation_at(words, anchor), expected, (offset, anchor))
        self.assertIn("unsupported", self.output.lower())

    def test_source_transposition_uses_final_key_metadata_even_when_layers_disabled(self) -> None:
        _, enabled = compile_fixture("pdf-key-spelling-source", passes=3)
        _, disabled = compile_fixture(
            "pdf-key-spelling-source", passes=3,
            preamble="\\def\\ulPdfTranspositionLayers{false}\n",
        )
        self.assertEqual(rendered_pages(enabled), rendered_pages(disabled))
        self.assertEqual(words_and_geometry(enabled), words_and_geometry(disabled))
        effective = (
            ("SourceMajorFour", "F", "Bb"),
            ("SourceMajorRaisedFive", "F", "C#"),
            ("SourceMajorFlatSeven", "F", "Eb"),
            ("SourceMinorRaisedSeven", "Cm", "B"),
            ("SourceMinorRaisedSix", "Cm", "A"),
            ("SourceMinorSeven", "Cm", "Bb"),
            ("SourceMinorSix", "Cm", "Ab"),
        )
        for offset in range(12):
            selected = PdfStructure(enabled).selected_pdf(enabled, {1: offset, 2: offset, 3: offset})
            words = words_and_geometry(selected)
            for anchor, key, note in effective:
                with self.subTest(offset=offset, anchor=anchor):
                    actual = notation_at(words, anchor)
                    expected = degree_spelling(key, note, offset) if offset else note
                    self.assertRegex(actual, r"^[A-G][#b]?$")
                    self.assertEqual(pitch(actual), (pitch(note) + offset) % 12)
                    if expected is not None:
                        self.assertEqual(actual, expected)
        original = words_and_geometry(disabled)
        self.assertEqual(notation_at(original, "SourceMajorMelody"), "bbc#")
        self.assertEqual(notation_at(original, "SourceMajorFlatSevenMelody"), "eb")
        self.assertEqual(notation_at(original, "SourceMinorMelody"), "babbab")

    def test_unknown_uppercase_text_preserves_accidentals_without_adjacent_pitch_grammar(self) -> None:
        output, enabled = compile_fixture("pdf-key-spelling-unknown", passes=3)
        disabled_output, disabled = compile_fixture(
            "pdf-key-spelling-unknown", passes=3,
            preamble="\\def\\ulPdfTranspositionLayers{false}\n",
        )
        expected = {"CDs": "CD#", "CDf": "CDb", "NCs": "NC#", "NCf": "NCb", "Cs": "c#"}
        for mode, log in (("enabled", output), ("disabled", disabled_output)):
            probes = {(key, operation, int(factor), name):
                      result.strip().replace("SHARP", "#").replace("FLAT", "b")
                      for key, operation, factor, name, result in re.findall(
                          r"ULUNKNOWN:(known|missing):(source|alternate|zero):(-?\d+):([^:\n]+):([^\n]*)",
                          log)}
            self.assertEqual(len(probes), 2 * (4 * (3 + 12 + 12) + 12), mode)
            for (key, operation, factor, name), result in probes.items():
                with self.subTest(mode=mode, key=key, operation=operation, factor=factor, name=name):
                    self.assertEqual(result, expected[name])
        self.assertEqual(rendered_pages(enabled), rendered_pages(disabled))
        self.assertEqual(words_and_geometry(enabled), words_and_geometry(disabled))
        for offset in range(12):
            selected = PdfStructure(enabled).selected_pdf(enabled, {1: offset, 2: offset})
            words = words_and_geometry(selected)
            for key in ("Known", "Missing"):
                for suffix, result in (
                    ("SequenceSharp", "CD#"), ("SequenceFlat", "CDb"),
                    ("TextSharp", "NC#"), ("TextFlat", "NCb"),
                ):
                    self.assertEqual(notation_at(words, key + suffix), result, (offset, key, suffix))

    def test_all_layer_stream_references_are_real_and_original_only_is_default(self) -> None:
        structure = PdfStructure(self.pdf)
        self.assertEqual(len(structure.layers), 8 * 12)
        on = set(structure.resolve(structure.config.get("/ON", [])))
        off = set(structure.resolve(structure.config.get("/OFF", [])))
        base_on = structure.config.get("/BaseState", "/ON") == "/ON"
        self.assertEqual({name for ref, name in structure.names.items()
                          if ref in on or (base_on and ref not in off)},
                         {f"ulsbs:transpose:v1:id:fixture-{song}:t00" for song in range(1, 9)})
        used = set()
        for page in structure.data["pages"]:
            resources = structure.resolve(structure.resolve(page["object"])["/Resources"])
            properties = structure.resolve(resources.get("/Properties", {}))
            depth = 0
            for reference in page["contents"]:
                content = base64.b64decode(structure.objects[f"obj:{reference}"]["stream"]["data"])
                for match in OPTIONAL_CONTENT_START.finditer(content):
                    reference = properties[match[1].decode()]
                    self.assertIn(reference, structure.layers)
                    used.add(reference)
                for operator in re.findall(rb"\b(?:BDC|BMC|EMC)\b", content):
                    depth += -1 if operator == b"EMC" else 1
                    self.assertGreaterEqual(depth, 0)
            self.assertEqual(depth, 0)
        self.assertEqual(used, set(structure.layers))
        pdf_command(self.pdf, ["qpdf", "--check", "{pdf}"])


if __name__ == "__main__":
    unittest.main()

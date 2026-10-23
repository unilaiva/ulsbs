# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Score orchestration tests without invoking LilyPond or TeX."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pikepdf

from ulsbs import lilypond_scores as scores


class LilyPondScoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs scores ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ui = Mock()
        self.ui.fmt_doc.return_value = "[book]"
        self.job = SimpleNamespace(compile_dir=self.root)

    def pdf(self, path, size=(100, 50), pages=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        with pikepdf.Pdf.new() as pdf:
            for _ in range(pages):
                pdf.add_blank_page(page_size=size)
            pdf.save(path)

    def snippet(self, name="ab/lily-one", *, head="ulsbs-include-head.ly",
                tail="ulsbs-include-tail.ly", systems=1, extra=""):
        source = self.root / (name + ".ly")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            '% \\include "ignored.ly"\n'
            '\\include "lilypond-book-preamble.ly"\n'
            f'\\include "{head}"\n'
            "theMelody = { c'4 d'4 }\n"
            "theMelodyTwo = { e'4 f'4 }\n"
            "theChords = \\chordmode { c1 }\n"
            + extra + f'\\include "{tail}"\n', encoding="utf-8")
        graphics = [f"{name}-{index}" for index in range(1, systems + 1)]
        fragment = source.with_name(source.stem + "-systems.tex")
        fragment.write_text("\n\\betweenLilyPondSystem{17}\\linebreak\n".join(
            rf"\includegraphics{{{graphic}}}" for graphic in graphics
        ) + "\n\\endinput\n", encoding="utf-8")
        for graphic in graphics:
            self.pdf(self.root / (graphic + ".pdf"))
        if systems > 1:
            source.with_suffix(".ulsbs-boundaries").write_text("".join(
                f"{index} 0 {index + 1} 0\n" for index in range(systems)))
        return source, fragment

    def request(self, prepared, key=None):
        score = next(iter(prepared.values()))
        # Independent C-major tonic spelling policy, including F-sharp at +6.
        targets = [dict(letter=letter, pitch=pitch) for pitch, letter in enumerate(
            (0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6))]
        request = dict(snippet_id=score.identity,
                       layer_prefix="ulsbs:transpose:v1:id:test-song:o02",
                       title="Test song", key=key or dict(letter=0, pitch=0, minor=0),
                       targets=targets)
        (self.root / "book.ulsbs-scores.json").write_text(json.dumps(
            dict(schema_version=1, requests=[request])), encoding="utf-8")
        return request

    def generate(self, prepared, effect=None, *, verbose=False):
        def engrave(command, *, cwd, env, stdout_path, check):
            self.assertEqual(command[0], "lilypond")
            self.assertEqual(cwd, self.root)
            self.assertEqual(env, {"TEST": "1", "ULSBS_SCORE_CACHE_DIR": str(self.root / "cache"),
                                   "LC_ALL": "C", "LANGUAGE": "C"})
            self.assertFalse(check)
            self.assertIn("-Itest-assets", command)
            stem = Path(command[command.index("-o") + 1])
            source = stem.with_suffix(".ly").read_text(encoding="utf-8")
            stdout_path.write_text("warning: harmless font substitution\n", encoding="utf-8")
            self.pdf(stem.with_name(stem.name + "-1.pdf"))
            score = next(iter(prepared.values()))
            for index in range(2, len(score.graphics) + 1):
                self.pdf(stem.with_name(f"{stem.name}-{index}.pdf"))
            if score.boundaries:
                stem.with_suffix(".ulsbs-boundaries").write_text("".join(
                    " ".join(str(value) for value in row) + "\n" for row in score.boundaries))
            return effect(stem, source, stdout_path) if effect else SimpleNamespace(returncode=0)

        with patch.object(scores, "run_cmd", side_effect=engrave) as command, \
                patch.object(scores.cache, "toolchain_fingerprint", return_value=None):
            scores.generate_scores(self.ui, self.job, "book", prepared,
                                   {"TEST": "1", "ULSBS_SCORE_CACHE_DIR": str(self.root / "cache")},
                                   ["-Itest-assets"], verbose=verbose)
        report = json.loads((self.root / "book.ulsbs-score-results.json").read_text())
        self.assertIsInstance(report["elapsed_seconds"], float)
        self.assertGreaterEqual(report["elapsed_seconds"], 0)
        dispatch = (self.root / "book.ulsbs-score-variants.tex").read_text()
        return report, dispatch, command

    def test_recognized_heads_and_tails_insert_at_actual_tail(self):
        tails = ["ulsbs-include-tail" + suffix + clef + ".ly"
                 for suffix in ("", "-notab", "-notab-nolyrics", "-lyricsbetween",
                                "-multivoice-notab", "-multivoice-twotabs")
                 for clef in ("", "_bassclef")]
        for head in ("ulsbs-include-head.ly", "ulsbs-include-head-spacious.ly"):
            for index, tail in enumerate(tails):
                self.snippet(f"{head}/lily-{index}", head=head, tail=tail)
        prepared = scores.prepare_scores(self.root, "book")
        self.assertEqual(len(prepared), 24)
        for score in prepared.values():
            with self.subTest(source=score.source):
                self.assertIsNone(score.unsupported)
                self.assertTrue(score.source.read_text()[score.tail_position:].startswith(
                    '\\include "ulsbs-include-tail'))

    def test_minimum_scale_header_reads_current_policy(self):
        for minimum_scale in (scores.LILYPOND_SCORE_MIN_SCALE, 0.75):
            with self.subTest(minimum_scale=minimum_scale), \
                    patch.object(scores, "LILYPOND_SCORE_MIN_SCALE", minimum_scale):
                self.assertEqual(scores._minimum_scale_tex(),
                                 rf"\def\ulScoreMinimumScale{{{minimum_scale}}}" + "\n")

    def test_prepare_replaces_stale_dispatch_and_status_with_current_policy_header(self):
        self.snippet()
        dispatch = self.root / "book.ulsbs-score-variants.tex"
        for minimum_scale in (scores.LILYPOND_SCORE_MIN_SCALE, 0.75):
            with self.subTest(minimum_scale=minimum_scale), \
                    patch.object(scores, "LILYPOND_SCORE_MIN_SCALE", minimum_scale):
                dispatch.write_text("stale dispatch\n")
                for suffix in (".ulsbs-scores.json", ".ulsbs-score-results.json"):
                    (self.root / ("book" + suffix)).write_text("stale status\n")
                self.assertTrue(scores.prepare_scores(self.root, "book"))
                self.assertEqual(dispatch.read_text(), scores._minimum_scale_tex())
                for suffix in (".ulsbs-scores.json", ".ulsbs-score-results.json"):
                    self.assertFalse((self.root / ("book" + suffix)).exists())

    def test_changed_bundled_asset_warns_once_not_per_offset_or_occurrence(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        request = self.request(prepared)
        (self.root / "book.ulsbs-scores.json").write_text(json.dumps({
            "schema_version": 1, "requests": [request, {
                **request, "layer_prefix": "ulsbs:transpose:v1:id:test-song:o03"}]}))
        assets = self.root / "ulsbs-assets/ly"
        assets.mkdir(parents=True)
        tail = assets / "ulsbs-internal-common-tail.ly"
        original = (scores.cache._BUNDLED / tail.name).read_bytes()
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.ui.reset_mock()
                data = original + b'\n\\include "ulsbs-score-boundaries.ily"\n'
                if changed:
                    data += b"% unreviewed edit\n"
                tail.write_bytes(data)
                report, _, _ = self.generate(prepared)
                self.assertEqual(report["successful_offsets"], 22)
                self.assertEqual(self.ui.warning_line.call_count, int(changed))
                if changed:
                    warning = self.ui.warning_line.call_args.args[0]
                    self.assertIn(tail.name, warning)
                    self.assertIn(scores.cache._asset_digest(data), warning)
                    self.assertIn("ulsbs-score-cache-assets", warning)
                    self.assertIn("before rewriting the trusted-asset manifest", warning)

    def test_asset_audit_errors_are_nonfatal(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)
        (self.root / "ulsbs-assets/ly").mkdir(parents=True)
        with patch.object(scores.cache, "audit_assets", side_effect=PermissionError("unreadable")):
            report, _, _ = self.generate(prepared)
        self.assertEqual(report["successful_offsets"], 11)
        self.ui.warning_line.assert_called_once()
        self.assertIn("Cannot audit LilyPond cache assets", self.ui.warning_line.call_args.args[0])

    def test_wrapping_preserves_break_tokens_is_idempotent_and_distinguishes_paths(self):
        _, first = self.snippet("ab/lily-same", systems=2)
        _, second = self.snippet("cd/lily-same", systems=2)
        originals = {path: path.read_text() for path in (first, second)}
        prepared = scores.prepare_scores(self.root, "book")
        self.assertEqual(len(prepared), 2)
        self.assertEqual(len({score.identity for score in prepared.values()}), 2)
        wrapped = {path: path.read_text() for path in originals}
        for score in prepared.values():
            path = score.source.with_name(score.source.stem + "-systems.tex")
            expected = originals[path]
            for index, graphic in enumerate(score.graphics, 1):
                expected = expected.replace(rf"\includegraphics{{{graphic}}}",
                    rf"\ulScoreSystem{{{score.identity}}}{{{index}}}{{{graphic}}}")
            self.assertEqual(wrapped[path], expected)
            self.assertIsNone(score.unsupported)
            self.assertEqual(len(score.boundaries), 2)
        self.assertEqual(scores.prepare_scores(self.root, "book"), prepared)
        self.assertEqual({path: path.read_text() for path in originals}, wrapped)

    def test_custom_sources_and_extra_includes_are_unsupported(self):
        self.snippet("custom", extra="\\score { c'1 }\n")
        self.snippet("extra", extra='\\include "custom.ly"\n')
        self.snippet("unknown", tail="custom-tail.ly")
        source, _ = self.snippet("missing")
        source.unlink()
        prepared = scores.prepare_scores(self.root, "book")
        self.assertEqual(len(prepared), 4)
        self.assertTrue(all(score.unsupported for score in prepared.values()))

    def test_repeated_identical_heads_preserve_source_and_original_systems(self):
        source, _ = self.snippet(systems=2)
        source.write_text(source.read_text().replace(
            '\\include "ulsbs-include-head.ly"',
            '\\include "ulsbs-include-head.ly"\n% repeated header\n'
            '\\include "ulsbs-include-head.ly"'))
        original = source.read_bytes()
        prepared = scores.prepare_scores(self.root, "book")
        self.assertIsNone(next(iter(prepared.values())).unsupported)
        self.request(prepared)
        report, _, _ = self.generate(prepared)
        self.assertEqual(report["successful_offsets"], 11)
        self.assertEqual(source.read_bytes(), original)
        for graphic in next(iter(prepared.values())).graphics:
            self.assertEqual(scores._dimensions(self.root / (graphic + ".pdf")), (100, 50))

    def test_mixed_or_interleaved_headers_remain_unsupported(self):
        for extra in ('\\include "ulsbs-include-head-spacious.ly"\n',
                      '\\include "ulsbs-include-head.ly"\n'):
            with self.subTest(extra=extra):
                self.snippet(extra=extra)
                prepared = scores.prepare_scores(self.root, "book")
                self.assertIsNotNone(next(iter(prepared.values())).unsupported)

    def named_assembly(self, grouped=False):
        chords = r'\new ChordNames { \theChords }'
        staff = (r'\new Staff { \clef "treble" '
                 + (r"\transpose c' c " if grouped else '')
                 + r'\new Voice = "theVoice" { \theMelody } }')
        tab = r'\include "ulsbs-internal-scorepart-tabstaff.ly"'
        lyric = r'\new Lyrics \lyricsto "theVoice" { \theLyricsOne }'
        if grouped:
            body = (chords + r' \new StaffGroup \with { '
                    r'\override StaffGrouper.staffgroup-staff-spacing.padding = #4 } << '
                    + staff + ' ' + tab + r' \new TabStaff { \tabFullNotation \stemDown '
                    r'\clef "moderntab" \set minimumFret = #7 '
                    r"\transpose c' c \theMelody } >>")
        else:
            body = ' '.join((chords, staff, lyric, tab, lyric.replace('One', 'Two')))
        return ('\\score { << ' + body + ' >> \\layout { } }\n'
                '\\include "ulsbs-internal-score-midi.ly"\n')

    def test_named_score_assemblies_transpose_before_consumption_and_preserve_layout(self):
        for grouped in (False, True):
            with self.subTest(grouped=grouped):
                source, _ = self.snippet(systems=2)
                source.write_text(source.read_text().replace(
                    '\\include "ulsbs-include-tail.ly"\n', self.named_assembly(grouped)))
                original = source.read_bytes()
                prepared = scores.prepare_scores(self.root, "book")
                score = next(iter(prepared.values()))
                self.assertIsNone(score.unsupported)
                self.assertTrue(source.read_text()[score.tail_position:].startswith(r'\score'))
                originals = {path: path.read_bytes() for path in (
                    source.with_suffix(".ulsbs-boundaries"),
                    *(self.root / (graphic + ".pdf") for graphic in score.graphics))}
                self.request(prepared)

                def inspect(stem, transformed, log, grouped=grouped):
                    self.assertTrue(transformed.endswith(self.named_assembly(grouped)))
                    self.assertLess(transformed.index(r'theMelody = \transpose'),
                                    transformed.index(r'\score'))
                    self.assertEqual(transformed.count("(make-music 'LineBreakEvent"), 1)
                    return SimpleNamespace(returncode=0)

                report, _, _ = self.generate(prepared, inspect)
                self.assertEqual(report["successful_offsets"], 11)
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_unrecognized_score_assembly_expressions_remain_original_only(self):
        assembly = self.named_assembly()
        cases = [assembly.replace(r'\theMelody', "c'1"),
                 assembly.replace(r'\theMelody', r'\otherMelody'),
                 assembly.replace(r'\theMelody', r"#(make-music 'NoteEvent)"),
                 assembly.replace('ulsbs-internal-scorepart-tabstaff.ly', 'custom.ly'),
                 assembly + "\\score { c'1 }\n",
                 assembly.replace(r'\layout { }', r'\layout { #(custom-layout) }'),
                 assembly.replace(r'\theChords', r'\transpose c d \theChords')]
        for index, custom in enumerate(cases):
            with self.subTest(index=index):
                source, _ = self.snippet()
                source.write_text(source.read_text().replace(
                    '\\include "ulsbs-include-tail.ly"\n', custom))
                prepared = scores.prepare_scores(self.root, "book")
                self.assertIsNotNone(next(iter(prepared.values())).unsupported)
                self.request(prepared)
                report, dispatch, command = self.generate(prepared)
                command.assert_not_called()
                self.assertEqual(report["fallback_offsets"], 11)
                self.assertEqual(dispatch, scores._minimum_scale_tex())

    def test_repeated_graphic_references_preserve_placements_and_system_identity(self):
        _, fragment = self.snippet()
        fragment.write_text(fragment.read_text() * 2)
        prepared = scores.prepare_scores(self.root, "book")
        score = next(iter(prepared.values()))
        self.assertIsNone(score.unsupported)
        self.assertEqual(len(score.graphics), 1)
        self.assertEqual(fragment.read_text().count(rf"\ulScoreSystem{{{score.identity}}}{{1}}"), 2)
        self.assertEqual(scores.prepare_scores(self.root, "book"), prepared)

    def test_current_inventory_excludes_removed_snippets_even_if_their_files_remain(self):
        _, current = self.snippet("current")
        _, stale = self.snippet("removed")
        original_stale = stale.read_text()
        inventory = self.root / "book.ulsbs-lilypond-systems.json"
        inventory.write_text(json.dumps([current.relative_to(self.root).as_posix()]))
        prepared = scores.prepare_scores(self.root, "book")
        self.assertEqual(len(prepared), 1)
        self.assertEqual(next(iter(prepared.values())).source.stem, "current")
        self.assertEqual(stale.read_text(), original_stale)
        inventory.write_text("[]")
        self.assertEqual(scores.prepare_scores(self.root, "book"), {})

    def test_intervals_have_independently_expected_spelling_and_octaves(self):
        cases = [
            ((0, 0), (1, 1), 1, ("c", "des")),
            ((0, 0), (3, 6), 6, ("c", "fis")),
            ((5, 9), (6, 10), 1, ("a", "bes")),  # A minor -> B-flat minor
            ((6, 11), (0, 0), 1, ("b", "c'")),
            ((0, 0), (6, 11), -1, ("c", "b,")),
            ((0, 11), (0, 0), 1, ("ces", "c")),
            ((0, 11), (6, 11), 0, ("ces", "b,")),
            ((2, 5), (3, 6), 1, ("eis", "fis")),
            ((1, 1), (2, 3), 2, ("des", "ees")),
        ]
        for source, target, offset, expected in cases:
            with self.subTest(source=source, target=target, offset=offset):
                self.assertEqual(scores.interval(dict(letter=source[0], pitch=source[1]),
                    dict(letter=target[0], pitch=target[1]), offset), expected)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            scores.interval(dict(letter=0, pitch=0), dict(letter=1, pitch=2), 1)
        with self.assertRaisesRegex(ValueError, "accidental"):
            scores.interval(dict(letter=0, pitch=2), dict(letter=1, pitch=2), 0)

    def test_harmless_warnings_accepted_and_transposition_precedes_tail(self):
        self.snippet(extra="\\setStaffSize #15\n")
        prepared = scores.prepare_scores(self.root, "book")
        request = self.request(prepared)

        def inspect(stem, source, log):
            self.assertLess(source.index("theMelody = \\transpose"),
                            source.index('\\include "ulsbs-include-tail.ly"'))
            self.assertIn("theMelodyTwo = \\transpose", source)
            self.assertIn("theChords = \\transpose", source)
            self.assertIn(r"\autoLineBreaksOff", source)
            self.assertNotIn("(make-music 'LineBreakEvent", source)
            self.assertEqual(source.count(r"\setStaffSize #15"), 1)
            return SimpleNamespace(returncode=0)

        report, dispatch, command = self.generate(prepared, inspect)
        self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (11, 0))
        self.assertEqual(command.call_count, 11)
        self.assertEqual(dispatch.count("\\endcsname"), 11)
        self.assertIn(request["layer_prefix"], dispatch)
        self.assertIn(":0-0-0:t06", dispatch)
        self.assertTrue(dispatch.startswith(scores._minimum_scale_tex()))
        self.ui.warning_line.assert_not_called()

    def test_single_system_count_mismatch_still_falls_back_after_replay(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def extra_system(stem, source, log):
            if stem.name == "t01":
                self.pdf(stem.with_name(stem.name + "-2.pdf"))
            return SimpleNamespace(returncode=0)

        report, dispatch, command = self.generate(prepared, extra_system)
        self.assertEqual(command.call_count, 13)
        self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (10, 1))
        self.assertEqual(report["scores"][0]["offsets"][0]["reason"],
                         "alternative system count does not match original")
        self.assertNotIn(":t01\\endcsname", dispatch)

    def test_transposition_preserves_original_paper_and_layout_justification(self):
        for ragged in ("##f", "##t"):
            with self.subTest(ragged=ragged):
                self.snippet(extra=f"\\paper {{ ragged-right = {ragged} ragged-last = {ragged} }}\n"
                             "\\layout { ragged-last = ##f }\n")
                prepared = scores.prepare_scores(self.root, "book")
                score = next(iter(prepared.values()))
                original = score.source.read_text()
                prefix, suffix = original[:score.tail_position], original[score.tail_position:]
                self.request(prepared)

                def inspect(stem, source, log, prefix=prefix, suffix=suffix):
                    self.assertTrue(source.startswith(prefix))
                    self.assertTrue(source.endswith(suffix))
                    additions = source[len(prefix):-len(suffix)]
                    self.assertNotIn(r"\paper", additions)
                    self.assertNotIn(r"\layout", additions)
                    self.assertNotIn("ragged-", additions)
                    return SimpleNamespace(returncode=0)

                report, _, _ = self.generate(prepared, inspect)
                self.assertEqual(report["successful_offsets"], 11)

    def test_missing_string_warning_with_exit_zero_retries_other_octave(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def warn(stem, source, log):
            if "\\transpose #(ly:make-pitch 0 0 0/2) #(ly:make-pitch 0 1 -1/2) \\theMelody" in source:
                log.write_text("warning: No string for pitch #<Pitch des > (given frets ())\n")
            return SimpleNamespace(returncode=0)

        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                self.ui.reset_mock()
                report, _, command = self.generate(prepared, warn, verbose=verbose)
                first = report["scores"][0]["offsets"][0]
                self.assertEqual(first["status"], "transposed")
                self.assertEqual([item["interval"] for item in first["attempts"]], [1, -11])
                self.assertIn("No string for pitch", first["attempts"][0]["reason"])
                self.assertEqual(command.call_count, 12)
                self.assertEqual(report["successful_offsets"], 11)
                self.ui.warning_line.assert_not_called()
                self.ui.noexec_line.assert_not_called()
                messages = [call.args[0] for call in self.ui.debug_line.call_args_list]
                if verbose:
                    self.assertEqual(len(messages), 3)
                    self.assertIn("interval=1: No string for pitch", messages[0])
                    self.assertIn("octave-equivalent interval -11 accepted", messages[1])
                    self.assertIn("11 successful offsets, 0 fallbacks", messages[2])
                else:
                    self.assertEqual(messages, [])

    def test_all_octaves_unplayable_warn_once_with_all_affected_offsets(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def warn(stem, source, log):
            if stem.name in ("t01", "t04", "t07"):
                log.write_text("warning: No string for pitch #<Pitch des >\n")
            return SimpleNamespace(returncode=0)

        report, dispatch, command = self.generate(prepared, warn)
        self.assertEqual(command.call_count, 16)
        self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (8, 3))
        self.ui.warning_line.assert_called_once()
        warning = self.ui.warning_line.call_args.args[0]
        self.assertIn("No string for pitch; original notation substituted", warning)
        self.assertIn("affected transpositions: t01 (des), t04 (e), t07 (g)", warning)
        self.assertEqual(dispatch.count("\\endcsname"), 8)
        self.ui.debug_line.assert_not_called()

    def test_third_higher_octave_recovers_low_tab_pitches_without_skipping_validation(self):
        self.snippet(systems=2)
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def warn(stem, source, log):
            if stem.name in ("t01", "t02"):
                if "#(ly:make-pitch 1 1" not in source:
                    log.write_text("warning: No string for pitch\n")
                elif stem.name == "t02":
                    stem.with_suffix(".ulsbs-boundaries").write_text("0 0 1/2 0\n1/2 0 2 0\n")
            return SimpleNamespace(returncode=0)

        report, dispatch, command = self.generate(prepared, warn)
        first, second = report["scores"][0]["offsets"][:2]
        self.assertEqual([item["interval"] for item in first["attempts"]], [1, -11, 13])
        self.assertEqual(first["status"], "transposed")
        self.assertEqual([item["interval"] for item in second["attempts"]], [2, -10, 14])
        self.assertEqual(second["status"], "fallback")
        self.assertIn("boundaries", second["reason"])
        self.assertEqual(command.call_count, 15)
        self.assertIn(":t01\\endcsname", dispatch)
        self.assertNotIn(":t02\\endcsname", dispatch)

    def test_fallbacks_group_by_occurrence_and_reason_across_scores(self):
        self.snippet("first", extra="\\score { c'1 }\n")
        self.snippet("second", extra="\\score { c'1 }\n")
        self.snippet("third", extra='\\include "custom.ly"\n')
        prepared = scores.prepare_scores(self.root, "book")
        request = self.request(prepared)
        requests = [{**request, "snippet_id": identity, "layer_prefix": prefix}
                    for prefix in (request["layer_prefix"], "ulsbs:transpose:v1:id:test-song:o03")
                    for identity in prepared]
        (self.root / "book.ulsbs-scores.json").write_text(json.dumps({
            "schema_version": 1, "requests": requests}))
        report, _, command = self.generate(prepared)
        command.assert_not_called()
        self.assertEqual(report["fallback_offsets"], 66)
        self.assertEqual(self.ui.warning_line.call_count, 4)
        for call in self.ui.warning_line.call_args_list:
            warning = call.args[0]
            self.assertEqual(warning.count("t01 (des)"), 1)
            self.assertIn("t11 (b)", warning)
            if "custom or unrecognized" in warning:
                for score in prepared.values():
                    if score.source.stem in ("first", "second"):
                        self.assertIn(score.identity, warning)

    def test_unknown_targets_warn_once_without_engraving(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        request = self.request(prepared)
        request.update(key=None, targets=None)
        (self.root / "book.ulsbs-scores.json").write_text(json.dumps({
            "schema_version": 1, "requests": [request]}))
        report, _, command = self.generate(prepared)
        command.assert_not_called()
        self.assertEqual(report["fallback_offsets"], 11)
        self.ui.warning_line.assert_called_once()
        warning = self.ui.warning_line.call_args.args[0]
        self.assertIn("effective key metadata is unavailable", warning)
        self.assertIn("major/minor required", warning)
        for offset in range(1, 12):
            self.assertIn(f"t{offset:02d} (unknown)", warning)

    def test_one_failed_offset_keeps_other_successes(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def fail(stem, source, log):
            return SimpleNamespace(returncode=1 if stem.name == "t03" else 0)

        report, dispatch, command = self.generate(prepared, fail)
        self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (10, 1))
        self.assertEqual(command.call_count, 13)
        self.assertNotIn(":t03\\endcsname", dispatch)
        self.assertIn(":t02\\endcsname", dispatch)
        self.assertIn(":t04\\endcsname", dispatch)
        failed = report["scores"][0]["offsets"][2]
        self.assertEqual([item["interval"] for item in failed["attempts"]], [3, -9, 15])
        self.assertEqual(failed["status"], "fallback")
        self.ui.warning_line.assert_called_once()

    def test_explicit_open_string_warning_also_retries(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def warn(stem, source, log):
            if "\\transpose #(ly:make-pitch 0 0 0/2) #(ly:make-pitch 0 1 -1/2) \\theMelody" in source:
                log.write_text("warning: No open string for pitch #<Pitch des >\n")
            return SimpleNamespace(returncode=0)

        report, _, command = self.generate(prepared, warn)
        self.assertEqual(command.call_count, 12)
        self.assertEqual(report["successful_offsets"], 11)
        self.assertEqual([attempt["interval"] for attempt in report["scores"][0]["offsets"][0]["attempts"]], [1, -11])

    def test_scale_floor_rejected_but_smaller_graphic_not_enlarged(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def resize(stem, source, log):
            size = {"t01": (100 / (scores.LILYPOND_SCORE_MIN_SCALE - 0.01), 50),
                    "t02": (100, 50 / (scores.LILYPOND_SCORE_MIN_SCALE - 0.01)),
                    "t03": (100 / (scores.LILYPOND_SCORE_MIN_SCALE + 0.01), 50)
                    }.get(stem.name, (50, 25))
            self.pdf(stem.with_name(stem.name + "-1.pdf"), size=size)
            if stem.name == "t05":
                with pikepdf.Pdf.new() as pdf:
                    page = pdf.add_blank_page(page_size=size)
                    page.obj["/CropBox"] = pikepdf.Array([0, 0, 50])
                    pdf.save(stem.with_name(stem.name + "-1.pdf"))
            return SimpleNamespace(returncode=0)

        report, _, _ = self.generate(prepared, resize)
        offsets = report["scores"][0]["offsets"]
        for outcome in offsets[:2]:
            self.assertEqual(outcome["status"], "fallback")
            self.assertIn(f"below {scores.LILYPOND_SCORE_MIN_SCALE:.2f}", outcome["reason"])
        self.assertEqual(offsets[2]["status"], "transposed")
        self.assertEqual(offsets[3]["status"], "transposed")
        small = self.root / (offsets[3]["graphic"] + "-1.pdf")
        self.assertEqual(scores._dimensions(small), (50, 25))
        self.assertEqual(offsets[4]["status"], "fallback")
        self.assertIn("invalid system graphic box", offsets[4]["reason"])
        self.assertEqual(report["successful_offsets"], 8)

    def test_scale_boundary_and_intermediate_variants_are_accepted(self):
        self.snippet()
        self.pdf(self.root / "ab/lily-one-1.pdf", size=(100 * scores.LILYPOND_SCORE_MIN_SCALE, 50))
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def resize(stem, source, log):
            # Keep the intermediate case relative to the policy, not the old
            # threshold; it exercises a .70 fit with the current .60 minimum.
            scale = {"t01": scores.LILYPOND_SCORE_MIN_SCALE,
                     "t02": scores.LILYPOND_SCORE_MIN_SCALE - 0.01,
                     "t03": scores.LILYPOND_SCORE_MIN_SCALE + (1 - scores.LILYPOND_SCORE_MIN_SCALE) / 4}.get(stem.name, 1)
            self.pdf(stem.with_name(stem.name + "-1.pdf"),
                      size=(100 * scores.LILYPOND_SCORE_MIN_SCALE / scale, 50))
            return SimpleNamespace(returncode=0)

        report, dispatch, _ = self.generate(prepared, resize)
        offsets = report["scores"][0]["offsets"]
        self.assertEqual([outcome["status"] for outcome in offsets[:3]],
                         ["transposed", "fallback", "transposed"])
        self.assertIn(f"below {scores.LILYPOND_SCORE_MIN_SCALE:.2f}", offsets[1]["reason"])
        self.assertEqual(report["successful_offsets"], 10)
        self.assertIn(":t01\\endcsname", dispatch)
        self.assertNotIn(":t02\\endcsname", dispatch)
        self.assertIn(":t03\\endcsname", dispatch)

    def test_patched_policy_controls_validation_generation_and_cache_publication(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def resize(stem, source, log):
            scale = {"t01": scores.LILYPOND_SCORE_MIN_SCALE,
                     "t02": scores.LILYPOND_SCORE_MIN_SCALE - 0.01}.get(stem.name, 1)
            self.pdf(stem.with_name(stem.name + "-1.pdf"), size=(75 / scale, 50))
            return SimpleNamespace(returncode=0)

        self.pdf(self.root / "ab/lily-one-1.pdf", size=(75, 50))
        with patch.object(scores, "LILYPOND_SCORE_MIN_SCALE", 0.75), \
                patch.object(scores.cache, "publish", wraps=scores.cache.publish) as publish:
            report, dispatch, _ = self.generate(prepared, resize)
            self.assertTrue(dispatch.startswith(scores._minimum_scale_tex()))
            self.assertEqual(report["successful_offsets"], 10)
            offsets = report["scores"][0]["offsets"]
            self.assertEqual(offsets[0]["status"], "transposed")
            self.assertEqual(offsets[1]["status"], "fallback")
            self.assertIn(f"below {scores.LILYPOND_SCORE_MIN_SCALE:.2f}", offsets[1]["reason"])
            self.assertEqual(publish.call_count, 10)
            for call in publish.call_args_list:
                self.assertEqual(call.kwargs["minimum_scale"], scores.LILYPOND_SCORE_MIN_SCALE)

    def test_unknown_key_and_unsupported_score_keep_original_without_commands(self):
        for kind in ("unknown-key", "custom"):
            with self.subTest(kind=kind):
                source, fragment = self.snippet(systems=2 if kind == "multisystem" else 1,
                    extra="\\score { c'1 }\n" if kind == "custom" else "")
                prepared = scores.prepare_scores(self.root, "book")
                request = self.request(prepared)
                if kind == "unknown-key":
                    request["key"] = None
                    (self.root / "book.ulsbs-scores.json").write_text(json.dumps(
                        dict(schema_version=1, requests=[request])))
                original = (self.root / "ab/lily-one-1.pdf").read_bytes()
                report, dispatch, command = self.generate(prepared)
                command.assert_not_called()
                self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (0, 11))
                self.assertEqual(dispatch, scores._minimum_scale_tex())
                self.assertEqual((self.root / "ab/lily-one-1.pdf").read_bytes(), original)
                self.assertTrue(all(item["reason"] for item in report["scores"][0]["offsets"]))
                source.unlink()
                fragment.unlink()

    def test_multisystem_replays_exact_boundaries_and_validates_every_crop(self):
        self.snippet(systems=12)
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)

        def inspect(stem, source, log):
            self.assertEqual(source.count("(make-music 'LineBreakEvent"), 11)
            self.assertEqual(source.count("(ly:make-duration 0 0 1)"), 11)
            self.assertIn(r"\autoLineBreaksOff", source)
            if stem.name == "t01":
                # The same count with different musical boundaries is not safe.
                stem.with_suffix(".ulsbs-boundaries").write_text("0 0 2 0\n2 0 12 0\n")
            if stem.name == "t02":
                self.pdf(stem.with_name(stem.name + "-12.pdf"),
                          size=(100 / (scores.LILYPOND_SCORE_MIN_SCALE - 0.01), 50))
            return SimpleNamespace(returncode=0)

        report, dispatch, _ = self.generate(prepared, inspect)
        offsets = report["scores"][0]["offsets"]
        self.assertEqual(report["successful_offsets"], 9)
        self.assertIn("boundaries", offsets[0]["reason"])
        self.assertIn("system 12", offsets[1]["reason"])
        self.assertNotIn(":t01\\endcsname", dispatch)
        self.assertNotIn(":t02\\endcsname", dispatch)
        self.assertIn(":t03\\endcsname", dispatch)

    def test_missing_noncontiguous_positive_or_final_grace_boundaries_fall_back(self):
        source, _ = self.snippet(systems=2)
        for contents in ("", "0 0 1/0 0\n", "0 0 1 0\n2 0 3 0\n",
                         "0 0 1 1/8\n1 1/8 2 0\n", "0 -1/8 1 0\n1 0 2 -1/8\n"):
            with self.subTest(contents=contents):
                source.with_suffix(".ulsbs-boundaries").write_text(contents)
                prepared = scores.prepare_scores(self.root, "book")
                self.assertIsNotNone(next(iter(prepared.values())).unsupported)
                self.request(prepared)
                report, _, command = self.generate(prepared)
                command.assert_not_called()
                self.assertEqual(report["fallback_offsets"], 11)

    def test_initial_grace_is_supported_but_exact_grace_moments_are_still_validated(self):
        for systems in (1, 2):
            with self.subTest(systems=systems):
                source, _ = self.snippet(systems=systems)
                boundaries = ("0 -1/8 1 0\n" if systems == 1 else
                              "0 -1/8 1 0\n1 0 2 0\n")
                source.with_suffix(".ulsbs-boundaries").write_text(boundaries)
                prepared = scores.prepare_scores(self.root, "book")
                self.assertIsNone(next(iter(prepared.values())).unsupported)
                self.request(prepared)

                def mismatch(stem, source, log, boundaries=boundaries):
                    if stem.name == "t01":
                        stem.with_suffix(".ulsbs-boundaries").write_text(
                            boundaries.replace("0 -1/8", "0 -1/16"))
                    return SimpleNamespace(returncode=0)

                report, dispatch, _ = self.generate(prepared, mismatch)
                self.assertEqual(report["successful_offsets"], 10)
                self.assertEqual(report["fallback_offsets"], 1)
                self.assertIn("boundaries", report["scores"][0]["offsets"][0]["reason"])
                self.assertNotIn(":t01\\endcsname", dispatch)

    def test_grace_replay_groups_shared_main_time_and_validates_internal_grace(self):
        source, _ = self.snippet(systems=4)
        boundaries = "0 0 1 -1/8\n1 -1/8 1 -1/16\n1 -1/16 1 0\n1 0 2 0\n"
        source.with_suffix(".ulsbs-boundaries").write_text(boundaries)
        prepared = scores.prepare_scores(self.root, "book")
        self.assertIsNone(next(iter(prepared.values())).unsupported)
        self.request(prepared)

        def inspect(stem, source, log):
            self.assertEqual(source.count("(make-music 'GraceMusic"), 1)
            self.assertEqual(source.count("(make-music 'LineBreakEvent"), 3)
            self.assertEqual(source.count("(ly:make-duration 0 0 1)"), 1)
            self.assertEqual(source.count("(ly:make-duration 0 0 1/16)"), 2)
            if stem.name == "t01":
                stem.with_suffix(".ulsbs-boundaries").write_text(
                    boundaries.replace("1 -1/16", "1 -1/32"))
            return SimpleNamespace(returncode=0)

        report, dispatch, _ = self.generate(prepared, inspect)
        self.assertEqual(report["successful_offsets"], 10)
        self.assertIn("boundaries", report["scores"][0]["offsets"][0]["reason"])
        self.assertNotIn(":t01\\endcsname", dispatch)

    def test_invalid_later_original_system_is_fatal_not_variant_fallback(self):
        self.snippet(systems=2)
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)
        (self.root / "ab/lily-one-2.pdf").write_bytes(b"broken original system")
        with self.assertRaises(pikepdf.PdfError):
            self.generate(prepared)

    def test_stale_candidate_pdfs_are_not_accepted_after_zero_exit_without_output(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)
        self.generate(prepared)

        def no_output(command, *, stdout_path, **kwargs):
            stem = Path(command[command.index("-o") + 1])
            self.assertFalse(list(stem.parent.glob(stem.name + "-*.pdf")))
            stdout_path.write_text("Finished successfully\n")
            return SimpleNamespace(returncode=0)

        with patch.object(scores, "run_cmd", side_effect=no_output) as command:
            scores.generate_scores(self.ui, self.job, "book", prepared, {}, [])
        report = json.loads((self.root / "book.ulsbs-score-results.json").read_text())
        self.assertEqual(command.call_count, 28)
        self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (0, 11))
        self.assertEqual((self.root / "book.ulsbs-score-variants.tex").read_text(),
                         scores._minimum_scale_tex())

    def test_generation_reuses_only_validated_successes_and_reports_cache_hits(self):
        self.snippet(systems=2)
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)
        with patch.object(scores.cache, "source_fingerprint", return_value="a" * 64):
            cold, cold_dispatch, command = self.generate(prepared)
            self.assertEqual(command.call_count, 11)
            self.assertEqual((cold["engravings"], cold["cache_hits"]), (11, 0))
            warm, dispatch, command = self.generate(prepared)
            command.assert_not_called()
            self.assertEqual((warm["engravings"], warm["cache_hits"]), (0, 11))
            self.assertEqual(dispatch, cold_dispatch)
            entry = next((self.root / "cache").glob("*/artifact-2.pdf"))
            entry.write_bytes(b"interrupted or corrupt cache entry")
            repaired, dispatch, command = self.generate(prepared)
            self.assertEqual(command.call_count, 1)
            self.assertEqual((repaired["engravings"], repaired["cache_hits"]), (1, 10))
            self.assertEqual(dispatch, cold_dispatch)
        with patch.object(scores.cache, "source_fingerprint", return_value="b" * 64):
            changed, _, command = self.generate(prepared)
            self.assertEqual(command.call_count, 11)
            self.assertEqual(changed["cache_hits"], 0)

    def test_changed_minimum_scale_uses_distinct_cache_keys_and_preserves_warm_reuse(self):
        self.snippet()
        prepared = scores.prepare_scores(self.root, "book")
        self.request(prepared)
        with patch.object(scores.cache, "source_fingerprint", return_value="a" * 64), \
                patch.object(scores.cache, "candidate_key", wraps=scores.cache.candidate_key) as key:
            cold, _, command = self.generate(prepared)
            self.assertEqual(command.call_count, 11)
            self.assertEqual(cold["cache_hits"], 0)
            original_keys = {path.name for path in (self.root / "cache").iterdir()}
            for call in key.call_args_list:
                self.assertEqual(call.kwargs["extra"]["minimum_scale"], scores.LILYPOND_SCORE_MIN_SCALE)
            key.reset_mock()
            with patch.object(scores, "LILYPOND_SCORE_MIN_SCALE", 0.75):
                changed, changed_dispatch, command = self.generate(prepared)
                self.assertEqual(command.call_count, 11)
                self.assertEqual(changed["cache_hits"], 0)
                changed_keys = {path.name for path in (self.root / "cache").iterdir()} - original_keys
                self.assertEqual(len(changed_keys), 11)
                for call in key.call_args_list:
                    self.assertEqual(call.kwargs["extra"]["minimum_scale"], scores.LILYPOND_SCORE_MIN_SCALE)
                warm, dispatch, command = self.generate(prepared)
                command.assert_not_called()
                self.assertEqual(warm["cache_hits"], 11)
                self.assertEqual(dispatch, changed_dispatch)
            warm, _, command = self.generate(prepared)
            command.assert_not_called()
            self.assertEqual(warm["cache_hits"], 11)


if __name__ == "__main__":
    unittest.main()

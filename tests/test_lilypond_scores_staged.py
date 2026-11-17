# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mocked supplemental score scheduling, ownership, and synchronous parity tests."""

import copy
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import lilypond_scores as scores
from ulsbs.timing import Timings, collect, measure


class StagedScoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs staged scores ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = SimpleNamespace(compile_dir=self.root)
        self.ui = Mock()
        self.ui.fmt_doc.return_value = "[book]"
        source = self.root / "original.ly"
        source.write_text("theMelody = { c'1 }\n")
        self.score = scores.Score("score", source, ("original-1",), 0, None)
        self.prepared = {"score": self.score}
        self.request = {
            "snippet_id": "score", "layer_prefix": "ulsbs:transpose:v1:id:song:o01",
            "song_id": "song", "title": "Song", "key": {"letter": 0, "pitch": 0, "minor": 0},
            "targets": [{"letter": letter, "pitch": pitch} for pitch, letter in enumerate(
                (0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6))],
        }

    def write_requests(self, requests):
        """Write the private draft-pass request envelope."""
        (self.root / "book.ulsbs-scores.json").write_text(json.dumps({
            "schema_version": 1, "requests": requests,
        }))

    def output(self):
        """Read final artifacts, excluding the intentionally variable wall time."""
        report = json.loads((self.root / "book.ulsbs-score-results.json").read_text())
        self.assertGreaterEqual(report.pop("elapsed_seconds"), 0)
        return report, (self.root / "book.ulsbs-score-variants.tex").read_text()

    def test_serial_and_out_of_order_staged_outputs_match_with_exact_dedup(self):
        duplicate = copy.deepcopy(self.request)
        duplicate["layer_prefix"] = "ulsbs:transpose:v1:id:song:o02"
        # Extra metadata is deliberately absent from the historical rendered key.
        duplicate["targets"][1]["extra"] = "must not cause another engraving"
        respelled = copy.deepcopy(self.request)
        respelled["layer_prefix"] = "ulsbs:transpose:v1:id:song:o03"
        respelled["targets"][1]["letter"] = 0
        self.write_requests([self.request, None, {"snippet_id": "missing"}, duplicate, respelled])

        for verbose in (False, True):
            outputs, messages, executions = [], [], []
            for staged in (False, True):
                self.ui.reset_mock()
                calls = []
                private_stats = {}

                def engrave(score, key, target, signed, offset, dimensions, directory,
                            env, include_args, *, fingerprint, statistics,
                            calls=calls, private_stats=private_stats):
                    with measure("scores.candidate"):
                        self.assertEqual(fingerprint, "fingerprint")
                        self.assertEqual(dimensions, ((100, 50),))
                        self.assertNotIn("extra", target)
                        chain = (offset, target["letter"])
                        private_stats.setdefault(chain, statistics)
                        self.assertIs(private_stats[chain], statistics)
                        calls.append((offset, target["letter"], signed))
                        statistics["cache_hits" if offset == 3 else "engravings"] += 1
                        failure = (offset == 2 or (offset == 1 and signed != 13)
                                   or (offset == 7 and signed == -5))
                        stem = f"variant-{offset}-{target['letter']}-{signed}"
                        return (None if failure else stem, "unplayable" if failure else None,
                                stem + ".log")

                with patch.object(scores, "_dimensions", return_value=(100, 50)), \
                        patch.object(scores.cache, "toolchain_fingerprint", return_value="tools") as tools, \
                        patch.object(scores.cache, "source_fingerprint", return_value="fingerprint") as source, \
                        patch.object(scores, "_engrave", side_effect=engrave):
                    parent = Timings()
                    with collect(parent):
                        if staged:
                            generator = scores.generate_scores_staged(
                                self.ui, self.job, "book", self.prepared, {}, [], verbose=verbose)
                            tasks = next(generator)
                            self.assertEqual(len(tasks), 12)
                            self.assertEqual(calls, [])
                            self.ui.assert_not_called()
                            self.ui.debug_line.assert_not_called()
                            self.ui.warning_line.assert_not_called()
                            source.assert_called_once()
                            tools.assert_called_once()
                            before = list(self.ui.mock_calls)
                            # Complete in reverse submission order on worker threads.
                            with ThreadPoolExecutor(max_workers=1) as pool:
                                for task in reversed(tasks):
                                    child = Timings()

                                    def run(task=task, child=child):
                                        with collect(child):
                                            task()

                                    pool.submit(run).result()
                                    self.assertGreater(child.stages["scores.candidate"]["calls"], 0)
                            self.assertEqual(parent.stages, {})
                            self.assertEqual(self.ui.mock_calls, before)
                            with self.assertRaises(StopIteration):
                                next(generator)
                        else:
                            scores.generate_scores(self.ui, self.job, "book", self.prepared,
                                                   {}, [], verbose=verbose)
                            self.assertEqual(parent.stages["scores.generate"]["calls"], 1)
                    self.assertEqual(len({id(value) for value in private_stats.values()}), 12)
                outputs.append(self.output())
                messages.append(self.ui.mock_calls)
                executions.append(calls)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(messages[0], messages[1])
            self.assertNotEqual(executions[0], executions[1])
            report, dispatch = outputs[1]
            self.assertEqual(report["attempts"], 19)
            self.assertEqual((report["engravings"], report["cache_hits"]), (18, 1))
            self.assertEqual((report["successful_offsets"], report["fallback_offsets"]), (30, 3))
            self.assertEqual(dispatch.count(r"\endcsname"), 30)
            self.assertTrue(all(record["cache_eligible"] for record in report["scores"]))
            for record in report["scores"]:
                for offset, expected in ((1, [1, -11, 13]), (2, [2, -10, 14]), (7, [-5, 7])):
                    self.assertEqual([attempt["interval"] for attempt in record["offsets"][offset - 1]["attempts"]],
                                     expected)
            for letter in (0, 1):
                self.assertEqual([signed for offset, spelling, signed in executions[1]
                                  if offset == 1 and spelling == letter], [1, -11, 13])

    def test_real_candidate_path_keeps_tool_output_and_verbose_diagnostics_private(self):
        self.write_requests([self.request])

        def command(args, *, stdout_path, **kwargs):
            self.assertEqual(args[0], "lilypond")
            self.assertFalse(kwargs["check"])
            self.assertEqual(kwargs["env"]["LC_ALL"], "C")
            stdout_path.write_text("private compiler diagnostic\n")
            return SimpleNamespace(returncode=1)

        with patch.object(scores, "_dimensions", return_value=(100, 50)), \
                patch.object(scores.cache, "toolchain_fingerprint", return_value=None), \
                patch.object(scores.cache, "source_fingerprint", return_value=None), \
                patch.object(scores, "run_cmd", side_effect=command) as tool:
            generator = scores.generate_scores_staged(
                self.ui, self.job, "book", self.prepared, {}, [], verbose=True)
            tasks = next(generator)
            self.ui.reset_mock()
            stdout = io.StringIO()
            with redirect_stdout(stdout), ThreadPoolExecutor(max_workers=4) as pool:
                for future in [pool.submit(task) for task in tasks]:
                    future.result()
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(self.ui.mock_calls, [])
            self.assertEqual(tool.call_count, 28)
            self.assertFalse((self.root / "book.ulsbs-score-results.json").exists())
            with self.assertRaises(StopIteration):
                next(generator)
        report, dispatch = self.output()
        self.assertFalse(report["scores"][0]["cache_eligible"])
        self.assertEqual(report["attempts"], 28)
        self.assertEqual(report["fallback_offsets"], 11)
        self.assertEqual(dispatch, scores._minimum_scale_tex())
        self.assertEqual(self.ui.debug_line.call_count, 29)
        self.ui.warning_line.assert_called_once()

    def test_empty_tasks_still_require_resume_to_write_results(self):
        self.write_requests([])
        with patch.object(scores.cache, "toolchain_fingerprint") as tools:
            generator = scores.generate_scores_staged(self.ui, self.job, "book", {}, {}, [])
            self.assertEqual(next(generator), [])
            tools.assert_not_called()
            self.assertFalse((self.root / "book.ulsbs-score-results.json").exists())
            with self.assertRaises(StopIteration):
                next(generator)
        report, dispatch = self.output()
        self.assertEqual(report["scores"], [])
        self.assertEqual(report["attempts"], 0)
        self.assertEqual(dispatch, scores._minimum_scale_tex())

    def test_child_exceptions_escape_without_parent_finalization(self):
        self.write_requests([self.request])
        with patch.object(scores, "_dimensions", return_value=(100, 50)), \
                patch.object(scores.cache, "toolchain_fingerprint", return_value=None), \
                patch.object(scores.cache, "source_fingerprint", return_value=None), \
                patch.object(scores, "_engrave", side_effect=RuntimeError("child failed")):
            generator = scores.generate_scores_staged(
                self.ui, self.job, "book", self.prepared, {}, [])
            task = next(generator)[0]
            with self.assertRaisesRegex(RuntimeError, "child failed"):
                task()
            generator.close()
            self.assertFalse((self.root / "book.ulsbs-score-results.json").exists())
            with self.assertRaisesRegex(RuntimeError, "child failed"):
                scores.generate_scores(self.ui, self.job, "book", self.prepared, {}, [])

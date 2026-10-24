# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Job-local inventory transactions without compiler or scheduler dependencies."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

from ulsbs import resultlist
from ulsbs.constants import RESULTLIST_SEPARATOR, RESULT_TYPE_MAIN_PDF


class ResultlistTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        resultlist.initialize(self.root, "transactions")
        self.addCleanup(self.delete_resultlist)

    @staticmethod
    def delete_resultlist() -> None:
        if resultlist._initialized:
            resultlist.delete()

    @staticmethod
    def record(name: str) -> str:
        return f"{RESULT_TYPE_MAIN_PDF}{RESULTLIST_SEPARATOR}{name}"

    def append(self, name: str) -> None:
        resultlist.append_line(RESULT_TYPE_MAIN_PDF, name)

    def test_unscoped_calls_remain_immediate_and_persisted(self) -> None:
        self.assertFalse(resultlist.exists())
        with self.assertRaises(FileNotFoundError):
            resultlist.lines()
        resultlist.append_line_if_missing(RESULT_TYPE_MAIN_PDF, "legacy.pdf")
        resultlist.append_line_if_missing(RESULT_TYPE_MAIN_PDF, "legacy.pdf")
        self.append("direct.pdf")
        expected = [self.record("legacy.pdf"), self.record("direct.pdf")]
        self.assertTrue(resultlist.exists())
        self.assertEqual(resultlist.lines(), expected)
        self.assertEqual(resultlist._resultlist_file.read_text().splitlines(), expected)
        resultlist.initialize_with_file(resultlist._resultlist_file)
        self.assertEqual(resultlist.lines(), expected)

    def test_scope_sees_committed_and_only_its_own_pending(self) -> None:
        self.append("committed.pdf")
        with resultlist.job_scope("other"):
            self.append("other.pdf")
        with resultlist.job_scope("parent"):
            self.append("parent.pdf")
            self.assertEqual(resultlist.lines(), [
                self.record("committed.pdf"), self.record("parent.pdf"),
            ])
            with resultlist.job_scope("child"):
                self.append("child.pdf")
                self.assertEqual(resultlist.lines(), [
                    self.record("committed.pdf"), self.record("child.pdf"),
                ])
            self.assertEqual(resultlist.lines()[-1], self.record("parent.pdf"))
        self.assertEqual(resultlist.lines(), [self.record("committed.pdf")])

    def test_pending_only_scope_supports_validation_without_creating_file(self) -> None:
        with resultlist.job_scope(None):
            self.assertFalse(resultlist.exists())
            self.assertEqual(resultlist.lines(), [])
            self.append("canonical.pdf")
            self.assertTrue(resultlist.exists())
            self.assertEqual(resultlist.lines(), [self.record("canonical.pdf")])
            self.assertFalse(resultlist._resultlist_file.exists())
        self.assertFalse(resultlist.exists())
        resultlist.commit_job(None)
        self.assertEqual(resultlist.lines(), [self.record("canonical.pdf")])

    def test_separate_worker_phases_share_pending_until_commit(self) -> None:
        key = object()

        def compile_job():
            with resultlist.job_scope(key):
                self.append("canonical.pdf")

        def package_job():
            with resultlist.job_scope(key):
                self.assertEqual(resultlist.lines(), [self.record("canonical.pdf")])
                self.append("range.pdf")

        # Separate executor lifetimes ensure the two phases use different threads.
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(compile_job).result(timeout=5)
        self.assertFalse(resultlist.exists())
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(package_job).result(timeout=5)
        self.assertFalse(resultlist.exists())
        resultlist.commit_job(key)
        resultlist.commit_job(key)
        self.assertEqual(resultlist.lines(), [
            self.record("canonical.pdf"), self.record("range.pdf"),
        ])

    def test_discard_removes_partial_artifacts_only_for_failed_job(self) -> None:
        self.append("legacy.pdf")
        for key in ("failed", "blocked", "success"):
            with resultlist.job_scope(key):
                self.append(f"{key}.pdf")
        for key in ("failed", "blocked"):
            resultlist.discard_job(key)
            resultlist.discard_job(key)
            resultlist.commit_job(key)
        resultlist.commit_job("success")
        self.assertEqual(resultlist.lines(), [
            self.record("legacy.pdf"), self.record("success.pdf"),
        ])

    def test_scope_restores_context_after_exception_without_auto_commit(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "failed"):
            with resultlist.job_scope("failed"):
                self.append("partial.pdf")
                raise RuntimeError("failed")
        self.append("unscoped.pdf")
        self.assertEqual(resultlist.lines(), [self.record("unscoped.pdf")])
        with resultlist.job_scope("failed"):
            self.assertIn(self.record("partial.pdf"), resultlist.lines())
        resultlist.discard_job("failed")

    def test_optional_collision_does_not_reveal_or_suppress_another_job(self) -> None:
        self.append("committed.pdf")
        for key in ("failed", "success"):
            with resultlist.job_scope(key):
                resultlist.append_line_if_missing(RESULT_TYPE_MAIN_PDF, "shared.pdf")
                resultlist.append_line_if_missing(RESULT_TYPE_MAIN_PDF, "shared.pdf")
                resultlist.append_line_if_missing(RESULT_TYPE_MAIN_PDF, "committed.pdf")
                self.assertEqual(resultlist.lines(), [
                    self.record("committed.pdf"), self.record("shared.pdf"),
                ])
        resultlist.discard_job("failed")
        resultlist.commit_job("success")
        self.assertEqual(resultlist.lines(), [
            self.record("committed.pdf"), self.record("shared.pdf"),
        ])

    def test_concurrent_jobs_are_isolated_and_commits_are_contiguous(self) -> None:
        self.append("committed.pdf")
        workers = 8
        ready = Barrier(workers + 1)
        release = Barrier(workers + 1)

        def worker(key):
            with resultlist.job_scope(key):
                for index in range(20):
                    self.append(f"{key}-{index}.pdf")
                ready.wait(timeout=5)
                try:
                    self.assertEqual(resultlist.lines(), [self.record("committed.pdf")] + [
                        self.record(f"{key}-{index}.pdf") for index in range(20)
                    ])
                finally:
                    release.wait(timeout=5)
            if key % 2:
                resultlist.discard_job(key)
            else:
                resultlist.commit_job(key)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker, key) for key in range(workers)]
            ready.wait(timeout=5)
            self.assertEqual(resultlist.lines(), [self.record("committed.pdf")])
            release.wait(timeout=5)
            for future in futures:
                future.result(timeout=5)
        records = resultlist.lines()
        self.assertEqual(len(records), 81)
        for key in range(workers):
            first = self.record(f"{key}-0.pdf")
            if key % 2:
                self.assertNotIn(first, records)
            else:
                start = records.index(first)
                self.assertEqual(records[start:start + 20], [
                    self.record(f"{key}-{index}.pdf") for index in range(20)
                ])

    def test_concurrent_duplicate_commits_publish_once(self) -> None:
        with resultlist.job_scope("success"):
            self.append("success.pdf")
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(resultlist.commit_job, ["success"] * 20))
        self.assertEqual(resultlist.lines(), [self.record("success.pdf")])

    def test_abort_serializes_only_committed_and_drops_pending(self) -> None:
        self.append("success.pdf")
        with resultlist.job_scope("failed"):
            self.append("partial.pdf")
            resultlist.abort(self.root / "deploy")
            self.assertNotIn(self.record("partial.pdf"), resultlist.lines())
        resultlist.commit_job("failed")
        records = resultlist.lines()
        self.assertEqual(records[0], self.record("success.pdf"))
        self.assertEqual(len(records), 2)
        self.assertIn("Compilation ABORTED at:", records[-1])
        self.assertTrue(resultlist._finalized)
        self.assertTrue(resultlist._moved)

    def test_abort_without_existing_file_does_not_publish_pending(self) -> None:
        with resultlist.job_scope("failed"):
            self.append("partial.pdf")
        resultlist.abort()
        self.assertEqual(len(resultlist.lines()), 1)
        self.assertIn("Compilation ABORTED at:", resultlist.lines()[0])

    def test_finalize_status_and_same_directory_cleanup_preserve_active_file(self) -> None:
        self.append("success.pdf")
        stale = self.root / f"{Path(resultlist._resultlist_filename).stem}_old.txt"
        stale.write_text("stale\n", encoding="utf-8")
        runresult = SimpleNamespace(
            successes=[1], failures=[2], total_warnings=3, blocked=[4, 5], skipped=[6],
        )
        with resultlist.job_scope("failed"):
            self.append("partial.pdf")
            resultlist.finalize(self.root, runresult, True)
        records = resultlist.lines()
        self.assertFalse(stale.exists())
        self.assertEqual(records[0], self.record("success.pdf"))
        self.assertNotIn(self.record("partial.pdf"), records)
        for status in ("Jobs succeeded: 1 (with 3 warnings)", "Jobs failed: 1",
                       "Jobs blocked: 2", "Jobs skipped: 1"):
            self.assertTrue(any(status in line for line in records))
        self.assertTrue(resultlist._finalized)
        self.assertTrue(resultlist._moved)

    def test_finalize_accepts_legacy_result_and_move_preserves_inventory(self) -> None:
        self.append("success.pdf")
        resultlist.finalize(self.root / "deploy", SimpleNamespace(
            successes=[1], failures=[], total_warnings=0,
        ))
        self.assertEqual(resultlist.lines()[0], self.record("success.pdf"))
        self.assertTrue(resultlist._finalized)
        self.assertTrue(resultlist._moved)
        self.assertFalse(any("Jobs blocked:" in line for line in resultlist.lines()))

    def test_initialize_resets_transactions_and_completion_flags_not_file(self) -> None:
        self.append("persisted.pdf")
        resultlist.finalize(self.root / "deploy")
        for use_existing_file in (False, True):
            with self.subTest(use_existing_file=use_existing_file):
                with resultlist.job_scope("stale"):
                    self.append("stale.pdf")
                active_file = resultlist._resultlist_file
                before = active_file.read_text()
                resultlist._finalized = resultlist._moved = True
                if use_existing_file:
                    resultlist.initialize_with_file(active_file)
                else:
                    resultlist.initialize(active_file.parent, "transactions")
                resultlist.commit_job("stale")
                self.assertEqual(active_file.read_text(), before)
                self.assertFalse(resultlist._finalized)
                self.assertFalse(resultlist._moved)


if __name__ == "__main__":
    unittest.main()

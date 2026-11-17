# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qualify shared score scheduling with synthetic stages and real job locks.

Only the expensive compilation generator is replaced. The public worker,
handoffs, child execution, reporting, and coordinator remain real. Events bound
all waits; no ordering assertion depends on a sleep or an elapsed-time threshold.
"""

from __future__ import annotations

import io
import json
import os
import signal
import socket
import sys
import tempfile
import threading
import unittest
import warnings
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ulsbs import pipeline, resultlist, timing, util
from ulsbs.config import Config
from ulsbs.jobs import Job, build_job_basename
from ulsbs.lock import JobLock
from ulsbs.ui import UI


class SupplementalSchedulerTests(unittest.TestCase):
    """Exercise admission, worker-free suspension, and draining on every exit."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        result = self.root / "result"
        result.mkdir()
        resultlist.initialize(result, "supplemental-scheduler")
        self.addCleanup(lambda: resultlist.delete() if resultlist._initialized else None)
        self.addCleanup(pipeline.ABORT_EVENT.clear)
        paths = SimpleNamespace(project_root=self.root, host_project_root=self.root,
                                result_dir=result)
        self.cfg = replace(Config(), verbose=True, max_parallel=3,
                           runtime=SimpleNamespace(project_paths=paths, in_container=False))
        self.ui = UI(use_colors=False, use_spinner=False)
        self.condition = threading.Condition()
        self.active = set()
        self.history = []
        self.maximum = 0
        self.gates = []
        self.closed = set()

    def job(self, name):
        """Give each ordinary job its own source and lock directory."""
        directory = self.root / name
        directory.mkdir()
        return Job(self.root / (name + ".tex"), name, "default", directory)

    def gate(self):
        """Register a gate that controller cleanup always releases."""
        event = threading.Event()
        self.gates.append(event)
        return event

    def wait(self, event):
        """Turn a missed event into a bounded, diagnostic test failure."""
        self.assertTrue(event.wait(10), "Timed out waiting for scheduler event")

    def until(self, predicate):
        """Wait for a phase snapshot while holding its observation lock."""
        with self.condition:
            self.assertTrue(self.condition.wait_for(predicate, timeout=10),
                            f"Missing scheduler state; active={self.active}, history={self.history}")

    @contextmanager
    def phase(self, name):
        """Count actual running stages, excluding suspended generator frames."""
        with self.condition:
            self.assertNotIn(name, self.active)
            self.active.add(name)
            self.history.append(name)
            self.maximum = max(self.maximum, len(self.active))
            self.condition.notify_all()
        try:
            yield
        finally:
            with self.condition:
                self.active.remove(name)
                self.condition.notify_all()

    def assert_locked(self, job):
        """Probe the real advisory lock without changing its owner's descriptor."""
        probe = JobLock(job.compile_dir)
        try:
            with self.assertRaisesRegex(RuntimeError, "Locked"):
                probe.acquire()
        finally:
            probe.release()

    def assert_unlocked(self, job):
        """Reacquisition proves the generator's finally block released its lock."""
        probe = JobLock(job.compile_dir)
        try:
            probe.acquire()
        finally:
            probe.release()

    @contextmanager
    def locked(self, job):
        """Keep the production lock alive across a synthetic generator's yield."""
        lock = JobLock(job.compile_dir)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            self.closed.add(job)

    def run_scheduler(self, jobs, stages, *, capacity=3, control=None):
        """Run on the main thread, surfacing controller errors after safe cleanup."""
        errors = []

        def supervise():
            try:
                control()
            except BaseException as error:
                errors.append(error)
            finally:
                for gate in self.gates:
                    gate.set()

        controller = threading.Thread(target=supervise) if control else None
        output = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(output), \
                    patch.object(pipeline, "_compile_one_job", stages):
                if controller:
                    controller.start()
                self.outcome = pipeline.run_jobs_parallel(
                    self.ui, jobs, None, replace(self.cfg, max_parallel=capacity))
        finally:
            for gate in self.gates:
                gate.set()
            if controller:
                controller.join(15)
                self.assertFalse(controller.is_alive(), "Controller did not drain")
            self.output = output.getvalue()
            if errors:
                raise errors[0]

    def assert_successes(self, jobs, capacity):
        """Check final parent outcomes, shared capacity, and released ownership."""
        self.assertEqual(self.outcome.failures, [])
        self.assertCountEqual([item.job for item in self.outcome.successes], jobs)
        self.assertLessEqual(self.maximum, capacity)
        self.assertFalse(self.active)
        self.assertEqual(self.closed, set(jobs))
        for job in jobs:
            self.assert_unlocked(job)

    def test_one_slot_handoff_keeps_lock_without_keeping_worker(self):
        parent, normal = self.job("parent"), self.job("normal")

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                with self.phase(job.doc_stem + ":initial"):
                    if job == parent:
                        ui.warning_line("parent-only-warning")
                if job == parent:
                    def child():
                        with self.phase("child"):
                            self.assert_locked(parent)
                            self.assertIsNot(pipeline._active_job_ui.get(), ui)
                    yield (child,)
                    # Empty supplemental batches must also resume with one slot.
                    yield ()
                with self.phase(job.doc_stem + ":resume"):
                    self.assert_locked(job)
                return pipeline.CompilationResult(0, 7)

        self.run_scheduler([parent, normal], stages, capacity=1)
        self.assert_successes([parent, normal], 1)
        self.assertEqual(self.maximum, 1)
        self.assertEqual(self.output.count("parent-only-warning"), 1)
        self.assertNotIn("child", self.output)

    def test_fifo_children_drain_then_fifo_normals_make_progress(self):
        jobs = [self.job("parent")] + [self.job(f"normal{i}") for i in range(8)]

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                with self.phase(job.doc_stem):
                    pass
                if job == jobs[0]:
                    def child(index):
                        def run():
                            with self.phase(f"child{index}"):
                                self.assert_locked(job)
                        return run
                    yield tuple(child(i) for i in range(8))
                    with self.phase("parent:resume"):
                        pass
                return pipeline.CompilationResult(0, 1)

        self.run_scheduler(jobs, stages, capacity=1)
        self.assert_successes(jobs, 1)
        self.assertEqual(self.history, ["parent"] + [f"child{i}" for i in range(8)]
                         + ["parent:resume"] + [f"normal{i}" for i in range(8)])
        self.assertNotIn("child", self.output)

    def test_saturated_resume_precedes_queued_children_and_normal_starts(self):
        jobs = [self.job(name) for name in ("a", "b", "c", "d", "e", "f")]
        gates = {name: self.gate() for name in
                 ("a:initial", "b:initial", "c:initial",
                  "a:child0", "b:child0", "b:child1", "a:resume")}

        def stage(name):
            with self.phase(name):
                if name in gates:
                    self.wait(gates[name])

        def stages(ui, assets, cfg, job):
            name = job.doc_stem
            with self.locked(job):
                stage(name + ":initial")
                if name in ("a", "b"):
                    def child(index):
                        def run():
                            self.assert_locked(job)
                            stage(f"{name}:child{index}")
                        return run
                    yield tuple(child(i) for i in range(1 if name == "a" else 2))
                    stage(name + ":resume")
                return pipeline.CompilationResult(0, 1)

        def control():
            self.until(lambda: self.active == {"a:initial", "b:initial", "c:initial"})
            gates["a:initial"].set()
            self.until(lambda: "a:child0" in self.active)
            gates["b:initial"].set()
            self.until(lambda: "b:child0" in self.active)
            self.assertEqual(self.active, {"c:initial", "a:child0", "b:child0"})
            gates["a:child0"].set()
            self.until(lambda: "a:resume" in self.active)
            self.assertEqual(self.active, {"c:initial", "b:child0", "a:resume"})
            self.assertNotIn("b:child1", self.history)
            self.assertNotIn("d:initial", self.history)
            gates["a:resume"].set()
            self.until(lambda: "b:child1" in self.active)
            self.assertNotIn("d:initial", self.history)

        self.run_scheduler(jobs, stages, control=control)
        self.assert_successes(jobs, 3)
        self.assertEqual(self.maximum, 3)

    def test_spare_capacity_tail_expands_children_to_shared_maximum(self):
        jobs = [self.job(name) for name in ("parent", "normal0", "normal1")]
        normals = self.gate()
        children = self.gate()

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                with self.phase(job.doc_stem):
                    if job != jobs[0]:
                        self.wait(normals)
                if job == jobs[0]:
                    def child(index):
                        def run():
                            with self.phase(f"child{index}"):
                                self.assert_locked(job)
                                self.wait(children)
                        return run
                    yield tuple(child(i) for i in range(6))
                return pipeline.CompilationResult(0, 1)

        def control():
            self.until(lambda: "normal0" in self.active and "normal1" in self.active
                       and any(name.startswith("child") for name in self.active))
            normals.set()
            self.until(lambda: len(self.active) == 3
                       and all(name.startswith("child") for name in self.active))
            self.assert_locked(jobs[0])

        self.run_scheduler(jobs, stages, control=control)
        self.assert_successes(jobs, 3)
        self.assertEqual(self.maximum, 3)
        self.assertNotIn("child", self.output)

    def test_child_results_merge_in_submission_order_with_private_warnings_and_timings(self):
        parent, other = self.job("parent"), self.job("other")
        second_returned = self.gate()
        completion = []
        original = pipeline._run_score_chain

        def observed(chain, ui, job):
            result = original(chain, ui, job)
            completion.append(chain.index)
            if chain.index == 1:
                second_returned.set()
            return result

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                ui.warning_line(job.doc_stem + "-before")
                if job == parent:
                    def child(index):
                        def run():
                            with self.phase(f"child{index}"):
                                if index == 0:
                                    self.wait(second_returned)
                                self.assert_locked(parent)
                                warnings.warn(f"private-{index}", UserWarning, stacklevel=2)
                                timing._active.get().add("synthetic.child", index + 1)
                        run.index = index
                        return run
                    yield tuple(child(i) for i in range(2))
                ui.warning_line(job.doc_stem + "-after")
                return pipeline.CompilationResult(999, 23)

        with patch.object(pipeline, "_run_score_chain", observed):
            self.run_scheduler([parent, other], stages)
        self.assert_successes([parent, other], 3)
        self.assertEqual(completion, [1, 0])
        success = next(item for item in self.outcome.successes if item.job == parent)
        self.assertEqual([item.message.split(" (")[0] for item in success.diagnostics],
                         ["parent-before", "private-0", "private-1", "parent-after"])
        other_result = next(item for item in self.outcome.successes if item.job == other)
        self.assertEqual([item.message for item in other_result.diagnostics],
                         ["other-before", "other-after"])
        self.assertEqual(self.outcome.total_warnings, 6)
        for message in ("parent-before", "parent-after", "private-0", "private-1"):
            self.assertEqual(self.output.count(message), 1)
        self.assertNotIn("child", self.output)
        report = json.loads((parent.compile_dir /
                            (build_job_basename(parent) + ".ulsbs-timings.json")).read_text())
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["stages"]["synthetic.child"],
                         {"calls": 2, "elapsed_seconds": 3.0, "failures": 0})
        self.assertEqual(report["stages"]["scores.generate"]["calls"], 1)
        self.assertNotIn("synthetic.child", json.loads((other.compile_dir /
                         (build_job_basename(other) + ".ulsbs-timings.json")).read_text())["stages"])

    def test_unexpected_child_error_drops_unadmitted_siblings_and_drains_before_unlock(self):
        parent = self.job("parent")
        running, release, failed = self.gate(), self.gate(), self.gate()
        drained = threading.Event()
        started = []

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                ui.warning_line("retained-parent-warning")
                try:
                    def child(index):
                        def run():
                            with self.phase(f"child{index}"):
                                started.append(index)
                                self.assert_locked(job)
                                if index == 0:
                                    self.wait(running)
                                    failed.set()
                                    raise ValueError("unexpected-score-error")
                                self.assertEqual(index, 1, "Unadmitted sibling started after failure")
                                running.set()
                                self.wait(release)
                                self.assert_locked(job)
                                drained.set()
                        return run
                    yield tuple(child(i) for i in range(6))
                    self.fail("Failed parent resumed as success")
                finally:
                    self.assertTrue(drained.is_set(), "Parent closed before running child drained")
            return pipeline.CompilationResult(0, 1)

        def control():
            self.wait(failed)
            self.assert_locked(parent)
            self.assertNotIn(parent, self.closed)
            release.set()

        self.run_scheduler([parent], stages, capacity=2, control=control)
        self.assertEqual(sorted(started), [0, 1])
        self.assertEqual(self.outcome.successes, [])
        self.assertEqual(len(self.outcome.failures), 1)
        self.assertEqual(self.outcome.failures[0].reason, "unexpected-score-error")
        self.assertEqual(self.outcome.total_warnings, 1)
        self.assertEqual(self.output.count("unexpected-score-error"), 1)
        self.assertEqual(self.output.count("retained-parent-warning"), 1)
        self.assertNotIn("child", self.output)
        self.assertFalse(self.active)
        self.assertEqual(self.closed, {parent})
        self.assert_unlocked(parent)

    def test_interrupt_drains_admitted_jobs_and_closes_suspended_parent(self):
        for interrupt in ("sigint", "worker"):
            with self.subTest(interrupt=interrupt):
                parent, normal, pending = [self.job(interrupt + name)
                                           for name in ("parent", "normal", "pending")]
                child_started = self.gate()
                drained = threading.Event()
                started = set()
                old_handler = signal.getsignal(signal.SIGINT)

                def stages(ui, assets, cfg, job, *, normal=normal, parent=parent,
                           started=started, child_started=child_started,
                           interrupt=interrupt, drained=drained):
                    started.add(job)
                    with self.locked(job):
                        if job == normal:
                            with self.phase("interrupt-normal"):
                                self.wait(child_started)
                                if interrupt == "sigint":
                                    signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                                else:
                                    raise KeyboardInterrupt()
                        elif job == parent:
                            try:
                                def child():
                                    with self.phase("interrupt-child"):
                                        self.assert_locked(parent)
                                        child_started.set()
                                        self.wait(pipeline.ABORT_EVENT)
                                        self.assert_locked(parent)
                                        drained.set()
                                yield (child,) * 5
                                self.fail("Interrupted parent must not resume")
                            finally:
                                self.assertTrue(drained.is_set())
                        else:
                            self.fail("Pending normal admitted after interruption")
                        return pipeline.CompilationResult(0, 1)

                with self.assertRaises(KeyboardInterrupt):
                    self.run_scheduler([parent, normal, pending], stages, capacity=2)
                self.assertEqual(started, {parent, normal})
                self.assertTrue(drained.is_set())
                self.assertTrue({parent, normal}.issubset(self.closed))
                self.assertFalse(self.active)
                self.assertEqual(signal.getsignal(signal.SIGINT), old_handler)
                # An already-running normal may finish successfully after SIGINT;
                # the suspended parent must never claim completion.
                self.assertNotIn(self.ui.fmt_doc(parent), self.output)
                for job in (parent, normal, pending):
                    self.assert_unlocked(job)

    def test_abort_adopts_unconsumed_initial_handoff_and_explicitly_releases_lock(self):
        parent = self.job("unconsumed-parent")
        returned = []
        child_started = threading.Event()
        interrupted = threading.Event()
        old_handler = signal.getsignal(signal.SIGINT)
        original = pipeline.compile_one_job

        def retain_handoff(ui, assets, cfg, job):
            state = original(ui, assets, cfg, job)
            self.assertIsInstance(state, pipeline._CompilationHandoff)
            self.assertTrue(pipeline.ABORT_EVENT.is_set())
            self.assert_locked(parent)
            # Retain a strong reference beyond executor shutdown: GC must not be
            # what closes this generator or releases the suspended parent's lock.
            returned.append(state)
            return state

        def cleanup_retained():
            for state in returned:
                state.stages.close()

        self.addCleanup(cleanup_retained)

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                def child():
                    child_started.set()

                # The future cannot be consumed yet: its worker is still inside
                # next(stages), and has not constructed/returned the handoff.
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                try:
                    yield (child,)
                    self.fail("Unconsumed interrupted handoff resumed normally")
                except KeyboardInterrupt:
                    self.assertIs(pipeline._active_job_ui.get(), ui)
                    self.assert_locked(job)
                    interrupted.set()
                    raise
            return pipeline.CompilationResult(0, 1)

        with patch.object(pipeline, "compile_one_job", retain_handoff):
            with self.assertRaises(KeyboardInterrupt):
                self.run_scheduler([parent], stages, capacity=1)
        self.assertEqual(len(returned), 1)
        self.assertTrue(interrupted.is_set(), "Cleanup did not throw into the suspended parent")
        self.assertFalse(child_started.is_set())
        self.assertIsNone(returned[0].stages.gi_frame)
        self.assertEqual(self.closed, {parent})
        self.assert_unlocked(parent)
        report = json.loads((parent.compile_dir /
                            (build_job_basename(parent) + ".ulsbs-timings.json")).read_text())
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["stages"]["scores.generate"]["failures"], 1)
        self.assertEqual(signal.getsignal(signal.SIGINT), old_handler)
        self.assertNotIn("successful", self.output)

    def test_abort_after_resume_finishes_preserves_success_timing_and_keyboard_interrupt(self):
        parent = self.job("finished-resume")
        old_handler = signal.getsignal(signal.SIGINT)
        original = pipeline._advance_compilation
        states, calls, successful_reports = [], [], []
        report_path = parent.compile_dir / (build_job_basename(parent) + ".ulsbs-timings.json")

        def observe_advance(ui, assets, cfg, job, handoff=None):
            calls.append(handoff)
            result = original(ui, assets, cfg, job, handoff)
            if handoff is None:
                self.assertIsInstance(result, pipeline._CompilationHandoff)
                states.append(result)
            else:
                self.assertIsInstance(result, pipeline.CompilationResult)
                self.assertTrue(pipeline.ABORT_EVENT.is_set())
                self.assertIsNone(handoff.stages.gi_frame)
                self.assert_unlocked(parent)
                successful_reports.append(report_path.read_bytes())
            return result

        def stages(ui, assets, cfg, job):
            with self.locked(job):
                yield ()
                with self.phase("finishing-resume"):
                    self.assert_locked(job)
                    # Stop consumption before this resume future can complete,
                    # while allowing its already-running generator to finish.
                    signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                return pipeline.CompilationResult(0, 9)

        with patch.object(pipeline, "_advance_compilation", observe_advance):
            with self.assertRaises(KeyboardInterrupt):
                self.run_scheduler([parent], stages, capacity=1)
        self.assertEqual(len(calls), 2, "Abort cleanup advanced an exhausted generator")
        self.assertIsNone(calls[0])
        self.assertIs(calls[1], states[0])
        self.assertIsNone(states[0].stages.gi_frame)
        self.assertEqual(len(successful_reports), 1)
        self.assertEqual(report_path.read_bytes(), successful_reports[0])
        self.assertEqual(json.loads(successful_reports[0])["status"], "success")
        self.assertEqual(self.closed, {parent})
        self.assert_unlocked(parent)
        self.assertFalse(self.active)
        self.assertEqual(signal.getsignal(signal.SIGINT), old_handler)
        self.assertEqual(self.output.count("successful"), 1)

    def test_subprocess_abort_reaps_live_descendant_before_parent_unlock(self):
        parent, pending = self.job("process-parent"), self.job("process-pending")
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(10)
        port = listener.getsockname()[1]
        command_drained = threading.Event()
        release_child = self.gate()
        pids = {}
        old_handler = signal.getsignal(signal.SIGINT)

        # Readiness comes from the descendant itself, not a guessed startup delay.
        # The leader waits/reaps on TERM, so a passing test leaves no zombies even
        # in a container whose PID 1 does not reap orphaned grandchildren.
        descendant = "\n".join((
            "import json, os, signal, socket, sys",
            "signal.alarm(15)",
            "print('DESCENDANT-PRIVATE-OUTPUT', flush=True)",
            "with socket.create_connection(('127.0.0.1', int(sys.argv[1]))) as ready:",
            "    ready.sendall((json.dumps({'leader': os.getppid(), 'descendant': os.getpid(),",
            "                              'group': os.getpgrp()}) + '\\n').encode())",
            "signal.pause()",
        ))
        leader = "\n".join((
            "import signal, subprocess, sys",
            "signal.signal(signal.SIGTERM, lambda signum, frame: None)",
            "signal.alarm(15)",
            "child = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])",
            "print('LEADER-PRIVATE-OUTPUT', flush=True)",
            "child.wait()",
        ))

        def assert_reaped():
            for name in ("leader", "descendant"):
                with self.assertRaises(ProcessLookupError, msg=f"Unreaped {name}: {pids}"):
                    os.kill(pids[name], 0)

        def emergency_cleanup():
            # Only a failing test needs this; the normal path proves both PIDs gone.
            if "group" in pids:
                try:
                    os.killpg(pids["group"], signal.SIGKILL)
                except ProcessLookupError:
                    pass

        self.addCleanup(emergency_cleanup)

        def stages(ui, assets, cfg, job):
            self.assertEqual(job, parent, "Pending normal started after abort")
            with self.locked(job):
                try:
                    def child():
                        with self.phase("subprocess-child"):
                            try:
                                util.run_cmd([sys.executable, "-c", leader, descendant, str(port)])
                                self.fail("Aborted command returned normally")
                            except KeyboardInterrupt:
                                self.assert_locked(parent)
                                assert_reaped()
                                command_drained.set()
                                self.wait(release_child)
                                raise
                    yield (child,)
                    self.fail("Interrupted parent resumed")
                finally:
                    self.assertTrue(command_drained.is_set())
                    self.assert_locked(parent)
                    assert_reaped()
            return pipeline.CompilationResult(0, 1)

        def control():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(10)
                with connection.makefile("r") as ready:
                    pids.update(json.loads(ready.readline()))
            self.assertEqual(pids["group"], pids["leader"], "Command needs a private process group")
            self.assertNotEqual(pids["group"], os.getpgrp())
            for name in ("leader", "descendant"):
                os.kill(pids[name], 0)
            self.assert_locked(parent)
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            self.wait(command_drained)
            self.assert_locked(parent)
            self.assertNotIn(parent, self.closed)
            release_child.set()

        with self.assertRaises(KeyboardInterrupt):
            self.run_scheduler([parent, pending], stages, capacity=1, control=control)
        self.assertTrue(command_drained.is_set())
        assert_reaped()
        self.assertEqual(self.closed, {parent})
        self.assertFalse(self.active)
        self.assert_unlocked(parent)
        self.assert_unlocked(pending)
        self.assertEqual(signal.getsignal(signal.SIGINT), old_handler)
        self.assertNotIn("PRIVATE-OUTPUT", self.output)
        self.assertNotIn("subprocess-child", self.output)
        self.assertNotIn("successful", self.output)


if __name__ == "__main__":
    unittest.main()

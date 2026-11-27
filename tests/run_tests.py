#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run all ULSBS source-tree test suites."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Start the TeX-heavy modules early so a long serial module doesn't hold up
# the end of an otherwise parallel run. Newly discovered modules still run.
LONG_TEST_MODULES = (
    "test_variants", "test_layout", "test_chords", "test_badge_metrics",
    "test_lilypond_scores_integration", "test_music",
)
# These two modules have independent test methods; each uses isolated fixtures
# and any class setup can safely run in more than one process.
MODULE_SHARDS = {"test_variants": 4, "test_layout": 2}


def _shard(suite: unittest.TestSuite, index: int, count: int) -> unittest.TestSuite:
    """Select a round-robin slice of the normally discovered tests, in order."""
    def cases(group):
        for test in group:
            if isinstance(test, unittest.TestSuite):
                yield from cases(test)
            else:
                yield test

    return unittest.TestSuite(test for offset, test in enumerate(cases(suite))
                              if offset % count == index)


def _run(command: list[str], *, capture: bool = False) -> int:
    print(f"+ {' '.join(command)}", flush=True)
    cache = ROOT / "build" / "texmf-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEXMFVAR"] = str(cache)
    env["TEXMFCACHE"] = str(cache)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT / "tests"), env.get("PYTHONPATH", "")]
    )
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=ROOT, env=env, check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
    )
    if capture:
        # Keep each worker's output together, including skipped-test summaries.
        print(f"\n{' '.join(command)} ({time.monotonic() - started:.1f}s)\n"
              f"{result.stdout}", flush=True)
    return result.returncode


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-l3build", action="store_true")
    parser.add_argument("--skip-integration", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--jobs", type=positive_int, default=4,
                        help="parallel Python test workers (default: 4; 1 for serial)")
    parser.add_argument("--shard", nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.shard:
        module, index, count = args.shard
        suite = unittest.defaultTestLoader.loadTestsFromName(module)
        if not unittest.defaultTestLoader.errors:
            suite = _shard(suite, int(index), int(count))
        return int(not unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
                   .run(suite).wasSuccessful())
    if args.skip_l3build and args.skip_integration:
        parser.error("all test suites were skipped")
    started = time.monotonic()

    if not args.skip_l3build:
        result = _run(["l3build", "check", "--halt-on-error", "--show-log-on-error"])
        if result:
            return result

    if not args.skip_integration:
        priority = {name: index for index, name in enumerate(LONG_TEST_MODULES)}
        modules = sorted((ROOT / "tests").glob("test_*.py"),
                         key=lambda path: (priority.get(path.stem, len(priority)), path.name))
        if not modules:
            parser.error("no Python test modules found")
        failed = []
        with ThreadPoolExecutor(max_workers=args.jobs) as workers:
            futures = {}
            for module in modules:
                count = min(args.jobs, MODULE_SHARDS.get(module.stem, 1))
                for index in range(count):
                    label = module.stem
                    if count == 1:
                        command = [sys.executable, "-m", "unittest", label]
                        verbose = "-v"
                    else:
                        command = [sys.executable, __file__, "--shard", label, str(index), str(count)]
                        verbose = "--verbose"
                        label += f"[{index + 1}/{count}]"
                    if args.verbose:
                        command.append(verbose)
                    futures[workers.submit(_run, command, capture=True)] = label
            for future in as_completed(futures):
                if future.result():
                    failed.append(futures[future])
        print(f"Python modules: {len(modules)}, jobs: {len(futures)}, "
              f"failed jobs: {len(failed)}", flush=True)
        if failed:
            print("Failed: " + ", ".join(sorted(failed)), file=sys.stderr)
            print(f"Suite wall time: {time.monotonic() - started:.1f}s", flush=True)
            return 1

    print(f"Suite wall time: {time.monotonic() - started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

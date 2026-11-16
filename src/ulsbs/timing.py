# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lightweight, worker-local wall-time aggregates for compiler diagnostics.

Stages are inclusive and may nest; their totals must not be added together.
Collection is explicitly scoped to a worker, never a process-global stopwatch.
Reports are temporary diagnostics, not publication artifacts or cache inputs.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path


_active: ContextVar[Timings | None] = ContextVar("ulsbs_timings", default=None)


@dataclass
class Timings:
    """Aggregate call counts, failures and inclusive seconds by stage name."""

    stages: dict[str, dict] = field(default_factory=dict)

    def add(self, name: str, seconds: float, *, failed: bool = False) -> None:
        """Record one completed or interrupted stage, using monotonic seconds."""
        stage = self.stages.setdefault(name, {"calls": 0, "elapsed_seconds": 0.0, "failures": 0})
        stage["calls"] += 1
        stage["elapsed_seconds"] += seconds
        stage["failures"] += int(failed)

    def seconds(self, *names: str) -> float:
        """Sum explicitly selected non-overlapping stages; absent stages are zero."""
        return sum(self.stages.get(name, {}).get("elapsed_seconds", 0.0) for name in names)

    def write(self, path: Path, *, elapsed_seconds: float, **metadata) -> None:
        """Write a compact report without allowing diagnostic I/O to fail a build."""
        data = {"schema_version": 1, "clock": "perf_counter", **metadata,
                "elapsed_seconds": round(elapsed_seconds, 6),
                "stages": {name: {**stage, "elapsed_seconds": round(stage["elapsed_seconds"], 6)}
                           for name, stage in sorted(self.stages.items())}}
        try:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError:
            logging.getLogger(__name__).debug("Cannot write timing report %s", path, exc_info=True)


@contextmanager
def collect(timings: Timings):
    """Bind aggregates to the current execution context, restoring any outer one."""
    token = _active.set(timings)
    try:
        yield timings
    finally:
        _active.reset(token)


@contextmanager
def measure(name: str):
    """Time a block or decorated function; do nothing outside a collection scope."""
    timings = _active.get()
    if timings is None:
        yield
        return
    started = time.perf_counter()
    failed = True
    try:
        yield
        failed = False
    finally:
        timings.add(name, time.perf_counter() - started, failed=failed)


def format_seconds(seconds: float) -> str:
    """Format job duration with two decimal places and a locale-independent comma."""
    return f"{seconds:.2f}".replace(".", ",") + " s"


def format_minutes(seconds: float) -> str:
    """Format run duration rounded to the nearest second, carrying whole minutes."""
    minutes, remainder = divmod(int(seconds + 0.5), 60)
    return f"{minutes} min {remainder} sec"

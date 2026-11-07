# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read index snapshots as data for semantic test assertions."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re


SIGNATURE = b"ULSBS index snapshot 3 fi-compatible-v1\n"
EVENT_SIGNATURE = b"ULSBS index records 1\n"
FIELDS = {"record": ("title", "label", "target", "chapter"),
          "directive": ("name", "value")}


def fields(data: bytes, start: int):
    while start < len(data):
        end = data.find(b":", start)
        if end < 0 or not data[start:end].isdigit():
            raise ValueError("Malformed index field length")
        count = int(data[start:end])
        start = end + 1
        if count > len(data) - start:
            raise ValueError("Truncated index field")
        yield data[start:start + count]
        start += count


def read_snapshot(path: Path) -> dict:
    try:
        digest, payload = path.read_bytes().split(b"\n", 1)
    except ValueError as error:
        raise ValueError("Missing index checksum") from error
    if hashlib.md5(payload).hexdigest().encode() != digest:
        raise ValueError("Index checksum mismatch")
    if not payload.startswith(SIGNATURE):
        raise ValueError("Unsupported index snapshot version")
    def take(items):
        try:
            return next(items)
        except StopIteration as error:
            raise ValueError("Incomplete index fields") from error

    items = iter(fields(payload, len(SIGNATURE)))
    job, state, source, sourcehash = (take(items).decode() for _ in range(4))
    if state != "complete":
        raise ValueError("Incomplete index pass")
    if re.fullmatch(r"[0-9a-f]{32}", sourcehash) is None:
        raise ValueError("Invalid index source hash")
    indices, filenames = {}, set()
    for identifier in items:
        kind, filename = (take(items).decode() for _ in range(2))
        events = take(items)
        if kind not in ("title", "tag", "author"):
            raise ValueError("Unknown index kind")
        if not events.startswith(EVENT_SIGNATURE):
            raise ValueError("Unsupported index event version")
        values = iter(fields(events, len(EVENT_SIGNATURE)))
        decoded = []
        for event_type in values:
            event_type = event_type.decode()
            if event_type not in FIELDS:
                raise ValueError("Unknown index event type")
            event = {"type": event_type,
                     **{name: take(values).decode() for name in FIELDS[event_type]}}
            if event_type == "directive":
                allowed = {"title": ("prefix",), "tag": (),
                           "author": ("sep", "after", "ignore")}
                if event["name"] not in allowed[kind]:
                    raise ValueError("Unknown index directive")
            decoded.append(event)
        identifier = identifier.decode()
        if identifier in indices:
            raise ValueError("Duplicate index declaration")
        if filename in filenames:
            raise ValueError("Duplicate index filename")
        filenames.add(filename)
        indices[identifier] = {"kind": kind, "filename": filename,
                               "events": decoded}
    return {"job": job, "source": source, "sourcehash": sourcehash, "indices": indices}


def index_events(work: Path, filename: str, job: str = "book") -> list[dict]:
    snapshot = read_snapshot(work / f"{job}.ulsbs-index-state")
    if snapshot["job"] != job:
        raise ValueError("Index snapshot belongs to another job")
    entry, = (item for item in snapshot["indices"].values() if item["filename"] == filename)
    return entry["events"]

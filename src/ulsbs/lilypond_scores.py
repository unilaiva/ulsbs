# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Original-footprint LilyPond alternatives for multikey and selection PDFs.

The first TeX pass supplies semantic song keys; generated lilypond-book
fragments supply score identities. Musical boundaries captured during original
engraving are replayed and verified before accepting multi-system alternatives.
Cached or newly engraved alternatives must fit the original score footprint;
failed alternatives fall back to the original notation through TeX dispatch.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import time
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import partial
from itertools import groupby
from pathlib import Path

import pikepdf

from . import lilypond_score_cache as cache
from .constants import LILYPOND_SCORE_MIN_SCALE
from .util import read_text, run_cmd, write_text
from .timing import measure


_NATURAL = (0, 2, 4, 5, 7, 9, 11)
_LETTERS = ("c", "d", "e", "f", "g", "a", "b")
_TAILS = {
    "ulsbs-include-tail" + suffix + clef + ".ly"
    for suffix in ("", "-notab", "-notab-nolyrics", "-lyricsbetween",
                   "-multivoice-notab", "-multivoice-twotabs")
    for clef in ("", "_bassclef")
}
_HEADS = {"ulsbs-include-head.ly", "ulsbs-include-head-spacious.ly"}
_INCLUDE = re.compile(r'\\include\s+"([^"\n]+)"')
_GRAPHIC = re.compile(r"\\includegraphics\{([^{}]+)\}")
_WRAPPED = re.compile(r"\\ulScoreSystem\{[a-f0-9]+\}\{\d+\}\{([^{}]+)\}")
_BAD_CONTENT = re.compile(r"No (?:open )?string for pitch|cannot find[^\n]*string|programming error|fatal error", re.I)
_BOUNDARY_INCLUDE = '\n\\include "ulsbs-score-boundaries.ily"\n'


@dataclass(frozen=True)
class Score:
    """Describe an original score, its system graphics, and transposition limits."""

    identity: str
    source: Path
    graphics: tuple[str, ...]
    tail_position: int | None
    unsupported: str | None
    boundaries: tuple[tuple[Fraction, Fraction, Fraction, Fraction], ...] = ()
    capture_boundaries: bool = False


def _minimum_scale_tex() -> str:
    """Carry the current Python fitting policy into the generated TeX bindings.

    Write this header even before alternatives exist, so the draft and final
    passes use one threshold. Compute it at call time rather than retaining a
    separate policy value in a template or another module.
    """
    return rf"\def\ulScoreMinimumScale{{{LILYPOND_SCORE_MIN_SCALE}}}" + "\n"


@measure("scores.prepare")
def prepare_scores(directory: Path, basename: str) -> dict[str, Score]:
    """Reset dispatch/status, write draft fitting policy, and wrap score inclusions.

    Preserve generated break tokens and original graphics. Only the fresh policy
    header remains in the bindings until generation supplies accepted variants.
    """
    for suffix in (".ulsbs-score-variants.tex", ".ulsbs-scores.json", ".ulsbs-score-results.json"):
        (directory / (basename + suffix)).unlink(missing_ok=True)
    write_text(directory / (basename + ".ulsbs-score-variants.tex"), _minimum_scale_tex())
    scores = {}
    inventory = directory / (basename + ".ulsbs-lilypond-systems.json")
    fragments = ([directory / name for name in json.loads(read_text(inventory))]
                 if inventory.is_file() else sorted(directory.rglob("*-systems.tex")))
    for fragment in fragments:
        if "ulsbs-score-variants" in fragment.relative_to(directory).parts:
            continue
        text = _WRAPPED.sub(lambda match: r"\includegraphics{" + match[1] + "}", read_text(fragment))
        # lilypond-book can repeat the same system inclusion. Preserve every
        # placement, but do not mistake repeated references for distinct music.
        graphics = tuple(dict.fromkeys(_GRAPHIC.findall(text)))
        if not graphics:
            continue
        source = fragment.with_name(fragment.name.removesuffix("-systems.tex") + ".ly")
        identity = hashlib.sha256(fragment.relative_to(directory).as_posix().encode()).hexdigest()[:20]
        reason, position = _support(source)
        boundaries = ()
        try:
            boundaries = _boundaries(source.with_suffix(".ulsbs-boundaries"))
        except (OSError, ValueError):
            pass
        if len(graphics) > 1 and len(boundaries) != len(graphics):
            reason = reason or "original musical boundaries are unavailable"
        if any(start_grace > 0 or end_grace > 0 for _, start_grace, _, end_grace in boundaries):
            reason = reason or "positive grace-time system boundaries are unsupported"
        if boundaries and boundaries[-1][3]:
            reason = reason or "final system boundary within grace music is unsupported"
        scores[identity] = Score(identity, source, graphics, position, reason, boundaries)
        indexes = {graphic: index for index, graphic in enumerate(graphics, 1)}

        def wrap(match, identity=identity, indexes=indexes):
            """Tag a graphic inclusion with its score identity and system index."""
            return rf"\ulScoreSystem{{{identity}}}{{{indexes[match[1]]}}}{{{match[1]}}}"

        write_text(fragment, _GRAPHIC.sub(wrap, text))
    return scores


def _support(source: Path) -> tuple[str | None, int | None]:
    """Return an unsupported reason or the insertion point before score assembly."""
    if not source.is_file():
        return "generated LilyPond source is unavailable", None
    text = read_text(source)
    # Mask comments but retain character positions for the include insertion.
    clean = re.sub(r"%\{[\s\S]*?%\}|%[^\n]*", lambda match: " " * len(match[0]), text)
    includes = list(_INCLUDE.finditer(clean))
    tails = [match for match in includes if match[1] in _TAILS]
    heads = [match for match in includes if match[1] in _HEADS]
    # Repeated identical headers before the definitions need no source repair.
    # Never permit a header reset interleaved with music or other settings.
    if (not heads or len({match[1] for match in heads}) != 1
            or any(clean[left.end():right.start()].strip()
                   for left, right in zip(heads, heads[1:], strict=False))):
        return "custom or unrecognized score structure", None
    blocks = list(re.finditer(r"\\score\b", clean))
    allowed = _HEADS | _TAILS | {"lilypond-book-preamble.ly"}
    if not blocks and len(tails) == 1:
        position = tails[0].start()
    elif len(blocks) == 1 and not tails and _named_score(clean[blocks[0].start():]):
        position = blocks[0].start()
        allowed |= {"ulsbs-internal-scorepart-tabstaff.ly", "ulsbs-internal-score-midi.ly"}
    else:
        return "custom or unrecognized score structure", None
    if heads[-1].end() > position:
        return "custom or unrecognized score structure", None
    if any(match[1] not in allowed for match in includes):
        return "additional LilyPond includes are not yet supported", None
    return None, position


def _named_score(text: str) -> bool:
    """Recognize two declarative assemblies, not arbitrary LilyPond or Scheme.

    Every pitched staff must consume the transformed named melody/chords. Fixed
    octave shifts and numeric engraving settings remain in their original place.
    """
    chords = r'\\new\s+ChordNames\s*\{\s*\\theChords\s*\}'
    staff = (r'\\new\s+Staff\s*\{\s*\\clef\s+"treble"\s*'
             r"(?:\\transpose\s+c'\s+c\s+)?"
             r'\\new\s+Voice\s*=\s*"theVoice"\s*\{\s*\\theMelody\s*\}\s*\}')
    tab = r'\\include\s+"ulsbs-internal-scorepart-tabstaff\.ly"'
    lyrics = (r'\\new\s+Lyrics\s+\\lyricsto\s+"theVoice"\s*'
              r'\{\s*\\theLyrics(?:One|Two|Three|Four|Five|Six)\s*\}')
    between = rf'{chords}\s*{staff}\s*(?:{lyrics}\s*)+{tab}\s*(?:{lyrics}\s*)*'
    grouped = (
        rf'{chords}\s*\\new\s+StaffGroup\s+\\with\s*\{{\s*'
        r'\\override\s+StaffGrouper\.staffgroup-staff-spacing\.padding\s*=\s*#\d+(?:\.\d+)?\s*\}'
        rf'\s*<<\s*{staff}\s*{tab}\s*'
        r'\\new\s+TabStaff\s*\{\s*\\tabFullNotation\s+\\stemDown\s*'
        r'\\clef\s+"moderntab"\s+\\set\s+minimumFret\s*=\s*#\d+\s*'
        r"\\transpose\s+c'\s+c\s+\\theMelody\s*\}\s*>>"
    )
    return re.fullmatch(
        rf'\\score\s*\{{\s*<<\s*(?:{between}|{grouped})\s*>>\s*'
        r'\\layout\s*\{\s*\}\s*\}\s*'
        r'\\include\s+"ulsbs-internal-score-midi\.ly"\s*', text) is not None


def _boundaries(path: Path) -> tuple[tuple[Fraction, Fraction, Fraction, Fraction], ...]:
    """Read and validate contiguous main/grace-time system boundary pairs."""
    try:
        rows = tuple(sorted(tuple(Fraction(value) for value in line.split())
                            for line in read_text(path).splitlines() if line.strip()))
    except ZeroDivisionError as error:
        raise ValueError("invalid musical system boundaries") from error
    if not rows or any(len(row) != 4 or row[:2] >= row[2:] for row in rows):
        raise ValueError("invalid musical system boundaries")
    if any(left[2:] != right[:2] for left, right in zip(rows, rows[1:], strict=False)):
        raise ValueError("noncontiguous musical system boundaries")
    return rows


def _replay(boundaries) -> str:
    """Build a parallel timing voice that forces the original system breaks."""
    # A parallel timing voice preserves repeats, pickups, lyrics, and polyphony.
    def skip(duration):
        """Construct a Scheme skip event for the given musical duration."""
        return f"(make-music 'SkipEvent 'duration (ly:make-duration 0 0 {duration}))"

    force = "(make-music 'LineBreakEvent 'break-permission 'force)"
    events, previous = [], Fraction(0)
    for main, group in groupby((row[2:] for row in boundaries[:-1]), key=lambda point: point[0]):
        points = [grace for _, grace in group]
        if main != previous:
            events.append(skip(main - previous))
        # One grace block per main moment: its total length starts the first
        # break at the exact negative grace time, then advances towards zero.
        negative = [grace for grace in points if grace < 0]
        if negative:
            grace_events = []
            for grace, following in zip(negative, [*negative[1:], Fraction(0)], strict=True):
                grace_events.extend((force, skip(following - grace)))
            events.append("(make-music 'GraceMusic 'element "
                          "(make-music 'SequentialMusic 'elements (list "
                          + " ".join(grace_events) + ")))")
        if 0 in points:
            events.append(force)
        previous = main
    return r'''
theMelody = #(make-music 'SimultaneousMusic 'elements
  (list theMelody #{ \autoLineBreaksOff #}
    (make-music 'SequentialMusic 'elements (list EVENTS))))
'''.replace("EVENTS", " ".join(events))


def interval(source: dict, target: dict, semitones: int) -> tuple[str, str]:
    """Spell a signed interval using TeX's authoritative tonic letters."""
    def note(key):
        """Return a tonic's LilyPond spelling and unwrapped semitone pitch."""
        accidental = (key["pitch"] - _NATURAL[key["letter"]] + 6) % 12 - 6
        if accidental not in (-1, 0, 1):
            raise ValueError("unsupported tonic accidental")
        return _LETTERS[key["letter"]] + {-1: "es", 0: "", 1: "is"}[accidental], (
            _NATURAL[key["letter"]] + accidental
        )

    original, original_pitch = note(source)
    destination, destination_pitch = note(target)
    octaves, remainder = divmod(semitones - destination_pitch + original_pitch, 12)
    if remainder:
        raise ValueError("target tonic disagrees with requested offset")
    destination += "'" * max(0, octaves) + "," * max(0, -octaves)
    return original, destination


@measure("scores.dimensions")
def _dimensions(path: Path) -> tuple[float, float]:
    """Return the validated crop-box or media-box size of a single-page PDF."""
    with pikepdf.open(path) as pdf:
        if len(pdf.pages) != 1:
            raise ValueError("system graphic must have exactly one page")
        box = pdf.pages[0].get("/CropBox", pdf.pages[0].MediaBox)
        try:
            coordinates = tuple(float(value) for value in box)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("invalid system graphic box") from error
        if len(coordinates) != 4 or not all(math.isfinite(value) for value in coordinates):
            raise ValueError("invalid system graphic box")
        width, height = coordinates[2] - coordinates[0], coordinates[3] - coordinates[1]
        if not all(math.isfinite(n) and n > 0 for n in (width, height)):
            raise ValueError("invalid system graphic dimensions")
        return width, height


def _valid_key(key: object, *, mode: bool = False) -> bool:
    """Check tonic metadata and, when requested, its major/minor mode flag."""
    return (isinstance(key, dict)
            and type(key.get("letter")) is int and 0 <= key["letter"] <= 6
            and type(key.get("pitch")) is int and 0 <= key["pitch"] <= 11
            and (not mode or type(key.get("minor")) is int and key["minor"] in (0, 1)))


@measure("scores.generate")
def generate_scores(ui, job, basename: str, scores: dict[str, Score],
                    env: dict[str, str], include_args: list[str], *, verbose: bool = False) -> None:
    """Run staged score generation synchronously, including its timing scope."""
    for tasks in generate_scores_staged(ui, job, basename, scores, env, include_args,
                                       verbose=verbose):
        for task in tasks:
            task()


def _engrave_chain(score, key, target, offset, dimensions, directory, env, include_args,
                    fingerprint, result) -> None:
    """Run sequential octave retries, mutating only this chain's private result."""
    signed = offset if offset <= 6 else offset - 12
    # Keep preferred choices first; the third, higher register covers instrument
    # pitch floors missed by both earlier choices.
    candidates = ((signed, signed - 12, signed + 12) if signed > 0
                  else (signed, signed + 12))
    for candidate in candidates:
        graphic, failure, log = _engrave(
            score, key, target, candidate, offset, dimensions, directory, env, include_args,
            fingerprint=fingerprint, statistics=result["statistics"],
        )
        result["rendered"].append((candidate, graphic, failure, log))
        if graphic:
            break


def generate_scores_staged(ui, job, basename: str, scores: dict[str, Score],
                           env: dict[str, str], include_args: list[str], *, verbose: bool = False):
    """Prepare independent score/offset chains, then assemble their ordered results.

    First advance yields zero-argument callables. The coordinator must execute each
    exactly once and wait for all to finish before advancing again. Chains own their
    result/statistics storage and emit no UI output; the coordinator supplies child
    timing scopes and propagates child exceptions. No timing scope spans the yield.

    The generated bindings carry ``LILYPOND_SCORE_MIN_SCALE`` alongside accepted graphics,
    keeping TeX's physical-box checks consistent with engraving and cache checks.
    Private result diagnostics include wall time for this between-pass phase,
    separate from the LuaLaTeX timings recorded by the pipeline.
    """
    started = time.perf_counter()
    directory = job.compile_dir
    request_file = directory / (basename + ".ulsbs-scores.json")
    result_file = directory / (basename + ".ulsbs-score-results.json")
    requests = []
    if request_file.is_file():
        try:
            envelope = json.loads(read_text(request_file))
            if envelope.get("schema_version") != 1 or not isinstance(envelope.get("requests"), list):
                raise ValueError("unsupported request schema")
            requests = envelope["requests"]
        except (ValueError, TypeError, AttributeError) as error:
            ui.warning_line(f"{ui.fmt_doc(job)} Multikey LilyPond: invalid requests ({error}); using originals",
                            source="Scores", category="requests", log_path=result_file)
    elif scores:
        ui.warning_line(f"{ui.fmt_doc(job)} Multikey LilyPond: no active score requests; using originals",
                        source="Scores", category="requests", log_path=result_file)

    dispatch, results = [], []
    warnings = {}
    chains, tasks, prepared = {}, [], []
    fingerprints = {}
    asset_directory = directory / "ulsbs-assets/ly"
    if requests and asset_directory.is_dir():
        try:
            for path, digest, trusted in cache.audit_assets([asset_directory]):
                if not trusted:
                    detail = (
                        f" (SHA-256 {digest}). Run python3 -m ulsbs.lilypond_score_cache "
                        f"{shlex.quote(str(asset_directory))} "
                        "and review changed files and dependencies before rewriting the trusted-asset "
                        "manifest with --rewrite."
                    ) if verbose else ""
                    ui.warning_line(
                        f"{ui.fmt_doc(job)} Multikey LilyPond cache asset {path.name} is not audited "
                        f"and may disable affected score caching, not engraving.{detail}",
                        source="Cache", category="assets")
        except (OSError, ValueError) as error:
            ui.warning_line(f"{ui.fmt_doc(job)} Cannot audit LilyPond cache assets: {error}; "
                            "normal cache eligibility checks still apply",
                            source="Cache", category="assets")
    toolchain = cache.toolchain_fingerprint(env=env, cwd=directory) if requests else None
    for request in requests:
        if not isinstance(request, dict):
            continue
        score = scores.get(request.get("snippet_id"))
        prefix = request.get("layer_prefix", "")
        if score is None or not isinstance(prefix, str) or not re.fullmatch(
                r"ulsbs:transpose:v1:id:[a-z0-9-]+(?::o\d+)?", prefix):
            prepared.append(None)
            continue
        key, targets = request.get("key"), request.get("targets")
        reason = score.unsupported
        if not _valid_key(key, mode=True) or not isinstance(targets, list) or len(targets) != 12:
            reason = reason or "effective key metadata is unavailable or unsupported (major/minor required)"
        elif any(not _valid_key(target) or (target["pitch"] - key["pitch"]) % 12 != offset
                 for offset, target in enumerate(targets)):
            reason = "invalid target key metadata"
        record = {"snippet_id": score.identity, "source": str(score.source.relative_to(directory)),
                  "systems": list(score.graphics), "layer_prefix": prefix,
                  "song_id": request.get("song_id"), "title": request.get("title"),
                  "key": key, "cache_eligible": False,
                  "boundaries": [[str(value) for value in row] for row in score.boundaries],
                  "offsets": []}
        # A broken original is not a recoverable additional-variant failure.
        dimensions = tuple(_dimensions(directory / (graphic + ".pdf")) for graphic in score.graphics)
        signature = f'{key["letter"]}-{key["pitch"]}-{key["minor"]}' if _valid_key(key, mode=True) else "unknown"
        prepared.append((request, score, prefix, key, targets, reason, record, signature))
        if reason:
            continue
        if score.identity not in fingerprints:
            fingerprints[score.identity] = cache.source_fingerprint(
                score.source, include_args, cwd=directory, env=env, toolchain=toolchain)
        record["cache_eligible"] = fingerprints[score.identity] is not None
        for offset in range(1, 12):
            # Each candidate's signed interval determines its offset modulo 12.
            # This groups precisely the old rendered keys, including spelling,
            # and retains the first request's operands for repeated requests.
            chain_key = (score.identity, signature, targets[offset]["letter"], offset)
            if chain_key not in chains:
                result = {"rendered": [], "statistics": {"engravings": 0, "cache_hits": 0}}
                chains[chain_key] = result
                tasks.append(partial(
                    _engrave_chain, score, key, targets[offset], offset, dimensions,
                    directory, env, include_args, fingerprints[score.identity], result,
                ))

    yield tasks

    statistics = {name: sum(result["statistics"][name] for result in chains.values())
                  for name in ("engravings", "cache_hits")}
    attempts = sum(len(result["rendered"]) for result in chains.values())
    successes = fallbacks = 0
    for entry in prepared:
        if entry is None:
            ui.warning_line(f"{ui.fmt_doc(job)} Multikey LilyPond: unmatched score request; using original",
                            source="Scores", category="requests", log_path=result_file)
            continue
        request, score, prefix, key, targets, reason, record, signature = entry
        for offset in range(1, 12):
            target = targets[offset] if isinstance(targets, list) and len(targets) == 12 else None
            target_label = "unknown"
            if _valid_key(target):
                try:
                    target_label = interval(target, target, 0)[0] + ("m" if _valid_key(key, mode=True) and key["minor"] else "")
                except ValueError:
                    target_label = str(target)
            outcome = {"offset": offset, "target": target, "attempts": [], "status": "fallback", "reason": reason}
            if not reason:
                chain_key = (score.identity, signature, targets[offset]["letter"], offset)
                for candidate, graphic, failure, log in chains[chain_key]["rendered"]:
                    outcome["attempts"].append({"interval": candidate, "log": log, "reason": failure})
                    if graphic:
                        outcome.update(status="transposed", reason=None, graphic=graphic)
                        dispatch.append(
                            rf"\expandafter\def\csname ULScoreVariant:{prefix}:{score.identity}:{signature}:t{offset:02d}"
                            rf"\endcsname{{{graphic}}}"
                        )
                        successes += 1
                        if verbose and len(outcome["attempts"]) > 1:
                            ui.debug_line(
                                f"{ui.fmt_doc(job)} Multikey LilyPond {prefix} score={score.identity} "
                                f"t{offset:02d} target={target_label}: octave-equivalent interval {candidate} accepted"
                            )
                        break
                    outcome["reason"] = failure
                    if verbose:
                        ui.debug_line(
                            f"{ui.fmt_doc(job)} Multikey LilyPond {prefix} score={score.identity} "
                            f"t{offset:02d} target={target_label} interval={candidate}: {failure}; log={log}"
                        )
            if outcome["status"] == "fallback":
                fallbacks += 1
                warning = warnings.setdefault((prefix, outcome["reason"]), {
                    "title": request.get("title"), "scores": {}, "offsets": {}, "alternatives": set(),
                })
                warning["scores"][score.identity] = None
                warning["offsets"][(offset, target_label)] = None
                warning["alternatives"].add((score.identity, signature, offset))
            record["offsets"].append(outcome)
        results.append(record)
    for (prefix, reason), warning in warnings.items():
        affected_count = len(warning["alternatives"])
        detail = ""
        if verbose:
            affected = ", ".join(f"t{offset:02d} ({label})" for offset, label in sorted(warning["offsets"]))
            detail = (f"; {prefix} score={','.join(warning['scores'])}; "
                      f"affected transpositions: {affected}")
        ui.warning_line(
            f"{ui.fmt_doc(job)} Multikey LilyPond title={warning['title']!r}: {reason}; "
            f"original notation substituted for {affected_count} affected score/transpositions{detail}",
            source="Scores", category="fallback", log_path=result_file, affected_count=affected_count,
        )
    write_text(directory / (basename + ".ulsbs-score-variants.tex"),
               _minimum_scale_tex() + "".join(line + "\n" for line in dispatch))
    write_text(result_file, json.dumps({
        "schema_version": 1, "scores": results, "attempts": attempts,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        **statistics,
        "successful_offsets": successes, "fallback_offsets": fallbacks,
    }, ensure_ascii=True, indent=2) + "\n")
    if verbose:
        ui.debug_line(f"{ui.fmt_doc(job)} Multikey LilyPond: {len(results)} scores, "
                      f"{statistics['engravings']} engravings, {statistics['cache_hits']} cache hits, "
                      f"{successes} successful offsets, {fallbacks} fallbacks")


def _selection_inventory(directory, basename):
    """Index only current generated graphics without rewriting their fragments."""
    names = json.loads(read_text(directory / (basename + ".ulsbs-lilypond-systems.json")))
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("invalid LilyPond systems inventory")
    by_graphic = {}
    for name in dict.fromkeys(names):
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not name.endswith("-systems.tex"):
            raise ValueError("invalid fragment path in LilyPond systems inventory")
        fragment = directory / path
        if not fragment.is_file():
            continue
        text = _WRAPPED.sub(lambda match: r"\includegraphics{" + match[1] + "}", read_text(fragment))
        graphics = tuple(dict.fromkeys(_GRAPHIC.findall(text)))
        identity = hashlib.sha256(path.as_posix().encode()).hexdigest()[:20]
        source = fragment.with_name(fragment.name.removesuffix("-systems.tex") + ".ly")
        score = Score(identity, source, graphics, None, None)
        for graphic in graphics:
            by_graphic.setdefault(graphic, {})[path] = score
    return by_graphic


def _selection_match(inventory, graphic, file):
    """Use the raw stem first, and the current TeX file to disambiguate it."""
    if not isinstance(graphic, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", graphic):
        raise ValueError("invalid generated score graphic stem")
    matches = inventory.get(graphic, {})
    if len(matches) == 1:
        return next(iter(matches.values()))
    if not matches:
        raise ValueError("graphic is not in the current LilyPond systems inventory")
    if isinstance(file, str) and file:
        path = Path(file)
        for candidates in ((score for name, score in matches.items()
                            if path == name or path.parts[-len(name.parts):] == name.parts),
                           (score for name, score in matches.items() if path.name == name.name)):
            found = list(candidates)
            if found:
                if len(found) == 1:
                    return found[0]
                break
    raise ValueError("graphic matches multiple current LilyPond fragments")


def _run_engraving(stem, directory, env, include_args):
    """Run the same EPS/PDF backend for diagnostic originals and candidates."""
    with measure("scores.engrave"):
        return run_cmd([
            "lilypond", *include_args, "-dno-point-and-click", "-dbackend=eps",
            "-dseparate-page-formats=pdf", "-dinclude-eps-fonts", "-dgs-load-fonts",
            "-o", str(stem), str(stem.with_suffix(".ly")),
        ], cwd=directory, env={**env, "LC_ALL": "C", "LANGUAGE": "C"},
            stdout_path=stem.with_suffix(".log"), check=False)


def _capture_selection_boundaries(score, stem, directory, env, include_args):
    """Re-engrave an untransposed copy with boundary capture enabled."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    for stale in stem.parent.glob(f"{stem.name}-*.pdf"):
        stale.unlink()
    boundary_file = stem.with_suffix(".ulsbs-boundaries")
    boundary_file.unlink(missing_ok=True)
    source = read_text(score.source)
    pos = score.tail_position
    write_text(stem.with_suffix(".ly"), source[:pos] + _BOUNDARY_INCLUDE + source[pos:])
    if _run_engraving(stem, directory, env, include_args).returncode:
        raise ValueError("original boundary capture engraving failed")
    if ({path.name for path in stem.parent.glob(f"{stem.name}-*.pdf")}
            != {f"{stem.name}-{i}.pdf" for i in range(1, len(score.graphics) + 1)}):
        raise ValueError("original boundary capture system count does not match original")
    try:
        boundaries = _boundaries(boundary_file)
    except OSError as error:
        raise ValueError("original musical boundaries are unavailable") from error
    if len(boundaries) != len(score.graphics):
        raise ValueError("original musical boundary count does not match original system count")
    if any(start_grace > 0 or end_grace > 0 for _, start_grace, _, end_grace in boundaries):
        raise ValueError("positive grace-time system boundaries are unsupported")
    if boundaries[-1][3]:
        raise ValueError("final system boundary within grace music is unsupported")
    return boundaries


def _selection_chains(score, chains, directory, env, include_args, toolchain):
    """Capture once per snippet, then run its independent target chains."""
    capture = len(score.graphics) > 1
    capture_log = None
    try:
        reason, position = _support(score.source)
        if reason:
            raise ValueError(reason)
        score = replace(score, tail_position=position)
        dimensions = tuple(_dimensions(directory / (graphic + ".pdf")) for graphic in score.graphics)
        fingerprint_source = score.source
        if capture:
            stem = directory / "ulsbs-score-variants" / ("selection-" + score.identity) / "original"
            capture_log = stem.with_suffix(".log").relative_to(directory).as_posix()
            score = replace(score, capture_boundaries=True, boundaries=_capture_selection_boundaries(
                score, stem, directory, env, include_args))
            # Include the recorder itself in the dependencies for cache eligibility.
            fingerprint_source = stem.with_suffix(".ly")
        fingerprint = cache.source_fingerprint(
            fingerprint_source, include_args, cwd=directory, env=env, toolchain=toolchain)
    except (OSError, ValueError, pikepdf.PdfError) as error:
        for _, _, _, result in chains.values():
            result.update(reason=str(error), capture_log=capture_log)
        return
    for key, target, offset, result in chains.values():
        result.update(capture_log=capture_log, cache_eligible=fingerprint is not None,
                      boundaries=[[str(value) for value in row] for row in score.boundaries])
        _engrave_chain(score, key, target, offset, dimensions, directory, env, include_args,
                       fingerprint, result)


def generate_selection_scores_staged(ui, job, basename, env, include_args):
    """Yield one batch of selection engraving tasks, then write direct bindings and results."""
    directory = job.compile_dir
    result_file = directory / (basename + ".ulsbs-selection-score-results.json")
    requests, results, groups, work, dispatch = [], [], {}, {}, {}
    try:
        envelope = json.loads(read_text(directory / (basename + ".ulsbs-selection-scores.json")))
        if (not isinstance(envelope, dict) or envelope.get("schema_version") != 1
                or not isinstance(envelope.get("requests"), list)):
            raise ValueError("unsupported request schema")
        requests = envelope["requests"]
    except (OSError, ValueError) as error:
        ui.warning_line(f"{ui.fmt_doc(job)} Selection LilyPond: invalid requests ({error}); using originals",
                        source="Scores", category="requests", log_path=result_file)

    inventory, inventory_error = {}, None
    if requests:
        try:
            inventory = _selection_inventory(directory, basename)
        except (OSError, ValueError) as error:
            inventory_error = f"current LilyPond systems inventory is unavailable ({error})"
    owners = {}
    for request in requests:
        request = request if isinstance(request, dict) else {}
        key, target = request.get("key"), request.get("target")
        title, song_id = request.get("title"), request.get("song_id")
        file, graphic = request.get("file"), request.get("graphic")
        score = signature = offset = reason = None
        target_label = repr(target)
        try:
            if _valid_key(target, mode=True):
                target_label = interval(target, target, 0)[0] + ("m" if target["minor"] else "")
            if not _valid_key(key, mode=True) or not _valid_key(target, mode=True):
                raise ValueError("invalid source or target key metadata")
            if key["minor"] != target["minor"]:
                raise ValueError("changing between major and minor is unsupported")
            offset = (target["pitch"] - key["pitch"]) % 12
            interval(key, target, offset)
            signature = (key["letter"], key["pitch"], key["minor"], target["letter"], target["pitch"])
            if inventory_error:
                raise ValueError(inventory_error)
            score = _selection_match(inventory, graphic, file)
        except ValueError as error:
            reason = str(error)
        group_key = (score, signature, repr(song_id), repr(title), reason, target_label)
        if group_key not in groups:
            groups[group_key] = ({"song_id": song_id, "title": title, "file": file, "key": key,
                                  "systems": [], "offsets": []}, offset, target)
        requested = groups[group_key][0]["systems"]
        if graphic not in requested:
            requested.append(graphic)
        if signature is not None and isinstance(graphic, str):
            owners.setdefault((signature, graphic), set()).add(score)

    prepared = []
    for (score, signature, _, _, reason, target_label), (record, offset, target) in groups.items():
        chain = None
        if not reason:
            if any(len(owners[signature, graphic]) != 1 for graphic in record["systems"]):
                reason = "binding would select graphics from multiple LilyPond fragments"
            else:
                record.update(snippet_id=score.identity, source=score.source.relative_to(directory).as_posix())
                chains = work.setdefault(score, {})
                if signature not in chains:
                    # The target mode is validated above, but transposition uses only its tonic.
                    key = {name: record["key"][name] for name in ("letter", "pitch", "minor")}
                    tonic = {name: target[name] for name in ("letter", "pitch")}
                    chains[signature] = (key, tonic, offset, {
                        "rendered": [], "statistics": {"engravings": 0, "cache_hits": 0},
                    })
                chain = chains[signature][3]
        prepared.append((score, signature, record, offset, target, target_label, reason, chain))

    toolchain = cache.toolchain_fingerprint(env=env, cwd=directory) if work else None
    yield [partial(_selection_chains, score, chains, directory, env, include_args, toolchain)
           for score, chains in work.items()]

    for score, signature, record, offset, target, target_label, reason, chain in prepared:
        outcome = {"offset": offset, "target": target, "attempts": [], "status": "fallback", "reason": reason}
        if chain is not None:
            record.update({name: chain[name] for name in ("capture_log", "cache_eligible", "boundaries")
                           if name in chain})
            outcome["reason"] = chain.get("reason")
            for candidate, alternative, failure, log in chain["rendered"]:
                outcome["attempts"].append({"interval": candidate, "log": log, "reason": failure})
                outcome["reason"] = failure
                if alternative:
                    outcome.update(status="transposed", graphic=alternative)
                    prefix = "-".join(map(str, signature))
                    for graphic in record["systems"]:
                        index = score.graphics.index(graphic) + 1
                        dispatch[f"ULSelectionScore:{prefix}:{graphic}"] = f"{alternative}-{index}"
        if outcome["status"] == "fallback":
            ui.warning_line(
                f"{ui.fmt_doc(job)} Selection LilyPond song={record['title'] or record['song_id']!r} "
                f"target={target_label}: {outcome['reason']}; using original notation",
                source="Scores", category="fallback", log_path=result_file)
        record["offsets"].append(outcome)
        results.append(record)

    write_text(directory / (basename + ".ulsbs-selection-score-variants.tex"), _minimum_scale_tex() + "".join(
        rf"\expandafter\def\csname {name}\endcsname{{{graphic}}}" + "\n" for name, graphic in dispatch.items()))
    write_text(result_file, json.dumps({"schema_version": 1, "scores": results}, ensure_ascii=True, indent=2) + "\n")


@measure("scores.candidate")
def _engrave(score: Score, key: dict, target: dict, signed: int, offset: int,
             original: tuple[tuple[float, float], ...], directory: Path, env: dict[str, str],
             include_args: list[str], *, fingerprint: str | None = None,
             statistics: dict | None = None) -> tuple[str | None, str | None, str]:
    """Return a restored/engraved graphic stem, failure reason, and log path."""
    name = f"{score.identity}:{key}:{target}:{signed}"
    if score.capture_boundaries:
        name += ":capture"
    identity = hashlib.sha256(name.encode()).hexdigest()[:20]
    destination = directory / "ulsbs-score-variants" / identity
    destination.mkdir(parents=True, exist_ok=True)
    stem = destination / f"t{offset:02d}"
    log = stem.with_suffix(".log")
    relative_log = log.relative_to(directory).as_posix()
    try:
        start, end = interval(key, target, signed)
        def pitch(key, octave):
            """Build a language-independent Scheme pitch operand for transposition."""
            accidental = (key["pitch"] - _NATURAL[key["letter"]] + 6) % 12 - 6
            return f'#(ly:make-pitch {octave} {key["letter"]} {accidental}/2)'
        # Scheme pitch operands must not be parsed in the source's language:
        # e.g. German `b` means B-flat, unlike the engine's Dutch spelling.
        source_pitch = pitch(key, 0)
        target_pitch = pitch(target, end.count("'") - end.count(","))
        source = read_text(score.source)
        additions = "\n".join(
            rf"{name} = \transpose {source_pitch} {target_pitch} \{name}"
            for name in ("theMelody", "theMelodyTwo", "theChords")
        ) + "\n"
        # Single-system originals must not acquire automatic breaks either.
        additions += _replay(score.boundaries)
        if score.capture_boundaries:
            additions += _BOUNDARY_INCLUDE
        source = source[:score.tail_position] + additions + source[score.tail_position:]
        write_text(stem.with_suffix(".ly"), source)
        cache_key = cache.candidate_key(
            fingerprint, signed=signed, spelled=(start, end), original_dimensions=original,
            original_boundaries=score.boundaries,
            extra={"key": key, "target": target, "source": source, "minimum_scale": LILYPOND_SCORE_MIN_SCALE},
            implementation_version="ulsbs-score-transpose-boundaries-6")
        if cache.restore(cache_key, stem, env=env) is not None:
            try:
                failure = _validate_variant(stem, score, original)
            except (OSError, ValueError, pikepdf.PdfError):
                failure = "invalid cached score"
            if not failure:
                if statistics is not None:
                    statistics["cache_hits"] += 1
                return stem.relative_to(directory).as_posix(), None, relative_log
        # Never accept leftover graphics after a failed retry or interrupted build.
        for stale in destination.glob(f"{stem.name}-*.pdf"):
            stale.unlink()
        stem.with_suffix(".ulsbs-boundaries").unlink(missing_ok=True)
        if statistics is not None:
            statistics["engravings"] += 1
        # Omitted-tab warnings are a validity check, including with exit zero.
        # Keep their language stable even on a localized host.
        result = _run_engraving(stem, directory, env, include_args)
        if result.returncode:
            return None, "LilyPond engraving failed", relative_log
        failure = _validate_variant(stem, score, original)
        if failure:
            return None, failure, relative_log
        cache.publish(cache_key, stem, success=True, original_dimensions=original,
                      minimum_scale=LILYPOND_SCORE_MIN_SCALE, env=env)
        return stem.relative_to(directory).as_posix(), None, relative_log
    except (OSError, ValueError, pikepdf.PdfError) as error:
        return None, str(error), relative_log


@measure("scores.validate")
def _validate_variant(stem: Path, score: Score, original) -> str | None:
    """Return a diagnostic for invalid notation, boundaries, or fit, else None."""
    diagnostic = _BAD_CONTENT.search(read_text(stem.with_suffix(".log")))
    if diagnostic:
        return diagnostic[0]
    graphics = set(stem.parent.glob(f"{stem.name}-*.pdf"))
    expected = [stem.with_name(f"{stem.name}-{index}.pdf") for index in range(1, len(original) + 1)]
    if graphics != set(expected):
        return "alternative system count does not match original"
    if score.boundaries and _boundaries(stem.with_suffix(".ulsbs-boundaries")) != score.boundaries:
        return "alternative musical system boundaries do not match original"
    for index, (graphic, dimensions) in enumerate(zip(expected, original, strict=True), 1):
        width, height = _dimensions(graphic)
        scale = min(1, dimensions[0] / width, dimensions[1] / height)
        if scale < LILYPOND_SCORE_MIN_SCALE:
            return f"system {index} required scale {scale:.3f} is below {LILYPOND_SCORE_MIN_SCALE:.2f}"
    return None

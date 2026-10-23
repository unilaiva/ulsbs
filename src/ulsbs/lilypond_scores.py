# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Experimental, original-footprint LilyPond alternatives for multikey PDFs.

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
from dataclasses import dataclass
from fractions import Fraction
from itertools import groupby
from pathlib import Path

import pikepdf

from . import lilypond_score_cache as cache
from .constants import LILYPOND_SCORE_MIN_SCALE
from .util import read_text, run_cmd, write_text


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


@dataclass(frozen=True)
class Score:
    """Describe an original score, its system graphics, and transposition limits."""

    identity: str
    source: Path
    graphics: tuple[str, ...]
    tail_position: int | None
    unsupported: str | None
    boundaries: tuple[tuple[Fraction, Fraction, Fraction, Fraction], ...] = ()


def _minimum_scale_tex() -> str:
    """Carry the current Python fitting policy into the generated TeX bindings.

    Write this header even before alternatives exist, so the draft and final
    passes use one threshold. Compute it at call time rather than retaining a
    separate policy value in a template or another module.
    """
    return rf"\def\ulScoreMinimumScale{{{LILYPOND_SCORE_MIN_SCALE}}}" + "\n"


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


def generate_scores(ui, job, basename: str, scores: dict[str, Score],
                    env: dict[str, str], include_args: list[str], *, verbose: bool = False) -> None:
    """Render requested alternatives and write final dispatch plus fitting policy.

    The generated bindings carry ``LILYPOND_SCORE_MIN_SCALE`` alongside accepted graphics,
    keeping TeX's physical-box checks consistent with engraving and cache checks.
    Private result diagnostics include wall time for this between-pass phase,
    separate from the LuaLaTeX timings recorded by the pipeline.
    """
    started = time.perf_counter()
    directory = job.compile_dir
    request_file = directory / (basename + ".ulsbs-scores.json")
    requests = []
    if request_file.is_file():
        try:
            envelope = json.loads(read_text(request_file))
            if envelope.get("schema_version") != 1 or not isinstance(envelope.get("requests"), list):
                raise ValueError("unsupported request schema")
            requests = envelope["requests"]
        except (ValueError, TypeError, AttributeError) as error:
            ui.warning_line(f"{ui.fmt_doc(job)} Multikey LilyPond: invalid requests ({error}); using originals")
    elif scores:
        ui.warning_line(f"{ui.fmt_doc(job)} Multikey LilyPond: no active score requests; using originals")

    dispatch, results = [], []
    warnings = {}
    rendered = {}
    fingerprints = {}
    asset_directory = directory / "ulsbs-assets/ly"
    if requests and asset_directory.is_dir():
        try:
            for path, digest, trusted in cache.audit_assets([asset_directory]):
                if not trusted:
                    ui.warning_line(
                        f"{ui.fmt_doc(job)} Multikey LilyPond cache asset {path.name} is not audited "
                        f"(SHA-256 {digest}); affected score caching may be disabled, not engraving. "
                        "Run python3 -m ulsbs.lilypond_score_cache "
                        f"{shlex.quote(str(asset_directory))} (installed alias: ulsbs-score-cache-assets) "
                        "and review changed files "
                        "and dependencies before rewriting the trusted-asset manifest with --rewrite.")
        except (OSError, ValueError) as error:
            ui.warning_line(f"{ui.fmt_doc(job)} Cannot audit LilyPond cache assets: {error}; "
                            "normal cache eligibility checks still apply")
    toolchain = cache.toolchain_fingerprint(env=env, cwd=directory) if requests else None
    statistics = {"engravings": 0, "cache_hits": 0}
    successes = fallbacks = attempts = 0
    for request in requests:
        if not isinstance(request, dict):
            continue
        score = scores.get(request.get("snippet_id"))
        prefix = request.get("layer_prefix", "")
        if score is None or not isinstance(prefix, str) or not re.fullmatch(
                r"ulsbs:transpose:v1:id:[a-z0-9-]+(?::o\d+)?", prefix):
            ui.warning_line(f"{ui.fmt_doc(job)} Multikey LilyPond: unmatched score request; using original")
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
                if score.identity not in fingerprints:
                    fingerprints[score.identity] = cache.source_fingerprint(
                        score.source, include_args, cwd=directory, env=env, toolchain=toolchain)
                record["cache_eligible"] = fingerprints[score.identity] is not None
                signed = offset if offset <= 6 else offset - 12
                # Keep existing choices first, then try the higher register that
                # positive intervals otherwise miss on instruments with a floor.
                candidates = ((signed, signed - 12, signed + 12) if signed > 0
                              else (signed, signed + 12))
                for candidate in candidates:
                    cache_key = (score.identity, signature, targets[offset]["letter"], candidate)
                    if cache_key not in rendered:
                        attempts += 1
                        rendered[cache_key] = _engrave(
                            score, key, targets[offset], candidate, offset, dimensions,
                            directory, env, include_args, fingerprint=fingerprints[score.identity],
                            statistics=statistics,
                        )
                    graphic, failure, log = rendered[cache_key]
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
                    "title": request.get("title"), "scores": {}, "offsets": {},
                })
                warning["scores"][score.identity] = None
                warning["offsets"][(offset, target_label)] = None
            record["offsets"].append(outcome)
        results.append(record)
    for (prefix, reason), warning in warnings.items():
        affected = ", ".join(f"t{offset:02d} ({label})" for offset, label in sorted(warning["offsets"]))
        ui.warning_line(
            f"{ui.fmt_doc(job)} Multikey LilyPond {prefix} score={','.join(warning['scores'])} "
            f"title={warning['title']!r}: {reason}; original notation substituted; "
            f"affected transpositions: {affected}"
        )
    write_text(directory / (basename + ".ulsbs-score-variants.tex"),
               _minimum_scale_tex() + "".join(line + "\n" for line in dispatch))
    write_text(directory / (basename + ".ulsbs-score-results.json"), json.dumps({
        "schema_version": 1, "scores": results, "attempts": attempts,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        **statistics,
        "successful_offsets": successes, "fallback_offsets": fallbacks,
    }, ensure_ascii=True, indent=2) + "\n")
    if verbose:
        ui.debug_line(f"{ui.fmt_doc(job)} Multikey LilyPond: {len(results)} scores, "
                      f"{statistics['engravings']} engravings, {statistics['cache_hits']} cache hits, "
                      f"{successes} successful offsets, {fallbacks} fallbacks")


def _engrave(score: Score, key: dict, target: dict, signed: int, offset: int,
             original: tuple[tuple[float, float], ...], directory: Path, env: dict[str, str],
             include_args: list[str], *, fingerprint: str | None = None,
             statistics: dict | None = None) -> tuple[str | None, str | None, str]:
    """Return a restored/engraved graphic stem, failure reason, and log path."""
    identity = hashlib.sha256(f"{score.identity}:{key}:{target}:{signed}".encode()).hexdigest()[:20]
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
        # Native pitch operands must not be parsed in the source's language:
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
        result = run_cmd([
            "lilypond", *include_args, "-dno-point-and-click", "-dbackend=eps",
            "-dseparate-page-formats=pdf", "-dinclude-eps-fonts", "-dgs-load-fonts",
            "-o", str(stem), str(stem.with_suffix(".ly")),
        ], cwd=directory, env={**env, "LC_ALL": "C", "LANGUAGE": "C"}, stdout_path=log, check=False)
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

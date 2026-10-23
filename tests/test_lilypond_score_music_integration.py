# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native score-assembly compatibility and independently spelled musical pitches."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pikepdf

from ulsbs import lilypond_scores
from ulsbs.util import run_cmd


# These are literal musical expectations, not results of the engine's interval
# or spelling functions. Columns are tonic, four chromatic notes, and C7/E.
MAJOR_TARGETS = (
    ("c", "c cis des fis", "c e g bes e"),
    ("des", "des d eeses g", "des f aes ces f"),
    ("d", "d dis ees gis", "d fis a c fis"),
    ("ees", "ees e fes a", "ees g bes des g"),
    ("e", "e eis f ais", "e gis b d gis"),
    ("f", "f fis ges b", "f a c ees a"),
    ("fis", "fis fisis g bis", "fis ais cis e ais"),
    ("g", "g gis aes cis", "g b d f b"),
    ("aes", "aes a beses d", "aes c ees ges c"),
    ("a", "a ais bes dis", "a cis e g cis"),
    ("bes", "bes b ces e", "bes d f aes d"),
    ("b", "b bis c eis", "b dis fis a dis"),
)
NATURALS = (0, 2, 4, 5, 7, 9, 11)


def spelling(name):
    letter = "cdefgab".index(name[0])
    accidental = {"": 0, "is": 1, "isis": 2, "es": -1, "eses": -2}[name[1:]]
    return letter, accidental


def key(name, minor=None):
    letter, accidental = spelling(name)
    result = {"letter": letter, "pitch": (NATURALS[letter] + accidental) % 12}
    if minor is not None:
        result["minor"] = minor
    return result


def expected_pitches(names, midi):
    result = []
    for name, number in zip(names.split(), midi, strict=True):
        letter, accidental = spelling(name)
        octave, remainder = divmod(number - 60 - NATURALS[letter] - accidental, 12)
        assert remainder == 0, (name, number)
        result.append((octave, letter, accidental * 2))
    return result


DUMP = r'''
#(define (ulsbs-test-pitch label role pitch)
   (when (ly:pitch? pitch)
     (ly:message "ULSBS-MUSIC ~a ~a ~a ~a ~a" label role
       (ly:pitch-octave pitch) (ly:pitch-notename pitch)
       (* 4 (ly:pitch-alteration pitch)))))
#(define (ulsbs-test-dump label music)
   (music-map (lambda (event)
     (ulsbs-test-pitch label
       (cond ((ly:music-property event 'bass #f) "bass")
             ((ly:music-property event 'inversion #f) "inversion")
             (else "note"))
       (ly:music-property event 'pitch))
     (ulsbs-test-pitch label "tonic" (ly:music-property event 'tonic))
     event) music))
#(ulsbs-test-dump "melody" theMelody)
#(ulsbs-test-dump "second" theMelodyTwo)
#(ulsbs-test-dump "chords" theChords)
#(for-each (lambda (pitch) (ulsbs-test-pitch "tuning" "string" pitch)) ul-chosen-tuning)
'''


class LilyPondScoreMusicIntegrationTests(unittest.TestCase):
    def setUp(self):
        for tool in ("lilypond", "gs"):
            if shutil.which(tool) is None:
                self.skipTest(f"{tool} is not installed")
        self.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-score-music-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        assets = Path(lilypond_scores.__file__).parent / "assets/ly"
        self.production_assets = {path.name: path.read_bytes() for path in assets.iterdir()}
        self.assets = self.root / "ly"
        shutil.copytree(assets, self.assets)
        # Match the multikey pipeline: PDF alternatives have no MIDI score.
        (self.assets / "ulsbs-internal-score-midi.ly").write_text(
            "% MIDI generation is disabled for this edition.\n"
        )
        version = subprocess.check_output(["lilypond", "--version"], text=True)
        if "2.24." not in version:
            if shutil.which("convert-ly") is None:
                self.skipTest("convert-ly is required for the host LilyPond fixture")
            # Host 2.26 removed set-global-fonts. Never convert production 2.24 assets.
            subprocess.run(
                ["convert-ly", "-e", "-f", "2.24.4",
                 str(self.assets / "ulsbs-internal-common-tail.ly")],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        self.addCleanup(lambda: self.assertEqual(
            self.production_assets, {path.name: path.read_bytes() for path in assets.iterdir()}
        ))
        self.env = dict(os.environ)
        self.includes = ["-I", str(self.assets)]

    def capture_boundaries(self):
        # Match job-local instrumentation: explicit assemblies consume the head
        # only; normal tails also preserve callbacks declared after the head.
        for name in ("ulsbs-internal-common-head.ly", "ulsbs-internal-common-tail.ly"):
            asset = self.assets / name
            asset.write_text(asset.read_text() + '\n\\include "ulsbs-score-boundaries.ily"\n')

    def logged_run(self, command, **kwargs):
        source = Path(command[-1])
        text = source.read_text()
        position = re.search(r'\\include "ulsbs-include-tail[^"\n]*\.ly"|\\score\b', text).start()
        # Inject only into the file actually passed to LilyPond, after _engrave
        # has inserted its transpose assignments. Restore the uninstrumented source.
        source.write_text(text[:position] + DUMP + text[position:])
        try:
            return run_cmd(command, **kwargs)
        finally:
            source.write_text(text)

    def original(self, name, music, tail="ulsbs-include-tail-notab.ly", settings="",
                 supported=True, headers=1):
        source = self.root / f"{name}.ly"
        source.write_text(
            '\\include "ulsbs-include-head.ly"\n' * headers
            + '\\paper { line-width = 140\\mm }\n' + settings + "\n" + music + "\n"
            + (f'\\include "{tail}"\n' if tail else "")
        )
        log = source.with_suffix(".log")
        result = self.logged_run(
            ["lilypond", *self.includes, "-dno-point-and-click", "-dbackend=eps",
             "-dseparate-page-formats=pdf", "-dinclude-eps-fonts", "-dgs-load-fonts",
             "-o", str(source.with_suffix("")), str(source)],
            cwd=self.root, env=self.env, stdout_path=log, check=False,
        )
        self.assertEqual(result.returncode, 0, log.read_text())
        self.assertTrue(source.with_name(name + "-1.pdf").is_file(), log.read_text())
        graphics = sorted(self.root.glob(f"{name}-[0-9]*.pdf"),
                          key=lambda path: int(path.stem.rsplit("-", 1)[1]))
        source.with_name(name + "-systems.tex").write_text("\n".join(
            rf"\includegraphics{{{graphic.stem}}}" for graphic in graphics) + "\n")
        scores = lilypond_scores.prepare_scores(self.root, "music")
        score = next(score for score in scores.values() if score.source == source)
        if supported:
            self.assertIsNone(score.unsupported)
        else:
            self.assertIsNotNone(score.unsupported)
        return score, log

    def pitches(self, log, label, role="note"):
        return [tuple(map(int, match)) for match in re.findall(
            rf"ULSBS-MUSIC {label} {role} (-?\d+) (-?\d+) (-?\d+)",
            log.read_text(),
        )]

    def assert_music(self, log, label, names, midi, role="note"):
        self.assertEqual(self.pitches(log, label, role), expected_pitches(names, midi),
                         log.read_text())

    def engrave(self, score, source_key, target, signed):
        dimensions = tuple(lilypond_scores._dimensions(self.root / (graphic + ".pdf"))
                           for graphic in score.graphics)
        with patch.object(lilypond_scores, "run_cmd", side_effect=self.logged_run):
            graphic, reason, log = lilypond_scores._engrave(
                score, source_key, target, signed, signed % 12, dimensions,
                self.root, self.env, self.includes,
            )
        return graphic, reason, self.root / log

    def test_nested_chromatic_major_and_slash_chords_all_twelve_layers(self):
        score, original_log = self.original("nested", r'''
theMelody = \transpose d c \transpose e d {
  \key e \major \time 4/4 e''4 eis'' f'' ais''
}
theChords = \transpose d c \transpose e d \chordmode { e'1:7/gis' }
''')
        self.assert_music(original_log, "melody", "c cis des fis", (72, 73, 73, 78))
        self.assert_music(original_log, "chords", "g bes c", (67, 70, 72))
        self.assert_music(original_log, "chords", "e", (64,), "inversion")
        (self.root / "custom.ily").write_text("% Custom include: original-only fallback.\n")
        fallback, _ = self.original("custom", r'''
\include "custom.ily"
theMelody = { \key c \major c''1 }
''', supported=False)
        request = {"schema_version": 1, "requests": [{
            "snippet_id": score.identity, "layer_prefix": "ulsbs:transpose:v1:id:music",
            "song_id": "music", "title": "Nested chromatic major",
            "key": key("c", 0), "targets": [key(row[0]) for row in MAJOR_TARGETS],
        }]}
        request["requests"].append({
            **request["requests"][0], "snippet_id": fallback.identity,
            "layer_prefix": "ulsbs:transpose:v1:id:custom", "song_id": "custom",
        })
        (self.root / "music.ulsbs-scores.json").write_text(json.dumps(request))
        with patch.object(lilypond_scores, "run_cmd", side_effect=self.logged_run):
            lilypond_scores.generate_scores(Mock(), SimpleNamespace(compile_dir=self.root),
                                            "music", {score.identity: score, fallback.identity: fallback},
                                            self.env, self.includes)
        report = json.loads((self.root / "music.ulsbs-score-results.json").read_text())
        self.assertEqual(report["successful_offsets"], 11, report)
        self.assertEqual(report["fallback_offsets"], 11, report)
        self.assertEqual(report["attempts"], 11, report)
        for outcome in report["scores"][1]["offsets"]:
            self.assertEqual(outcome["status"], "fallback", outcome)
            self.assertEqual(outcome["attempts"], [], outcome)
            self.assertIn("additional LilyPond includes", outcome["reason"])
        dispatch = (self.root / "music.ulsbs-score-variants.tex").read_text()
        self.assertNotIn("id:custom", dispatch)
        for outcome in report["scores"][0]["offsets"]:
            offset = outcome["offset"]
            with self.subTest(offset=offset):
                self.assertEqual(outcome["status"], "transposed", outcome)
                tonic, notes, chords = MAJOR_TARGETS[offset]
                self.assertEqual(len(outcome["attempts"]), 1, outcome)
                attempt = outcome["attempts"][0]
                signed = offset if offset <= 6 else offset - 12
                self.assertEqual(attempt["interval"], signed)
                log = self.root / attempt["log"]
                self.assert_music(log, "melody", notes,
                                  [number + signed for number in (72, 73, 73, 78)])
                chord_notes = chords.split()
                self.assert_music(log, "chords", " ".join(chord_notes[2:4] + chord_notes[:1]),
                                  [number + signed for number in (67, 70, 72)])
                self.assert_music(log, "chords", chords.split()[-1], (64 + signed,),
                                  "inversion")
                self.assertEqual([(letter, accidental) for _, letter, accidental
                                  in self.pitches(log, "melody", "tonic")],
                                 [(key(tonic)["letter"], spelling(tonic)[1] * 2)])
                self.assertTrue((self.root / (outcome["graphic"] + "-1.pdf")).is_file())
        self.assertEqual(list(self.root.rglob("*.midi")), [])

    def test_minor_guitar_octave_retry_after_unplayable_first_attempt(self):
        score, original_log = self.original("minor", r'''
theMelody = { \key a \minor \time 4/4 e'4 f' gis' a' }
theChords = \chordmode { a1:m/e }
''', tail="ulsbs-include-tail.ly")
        self.assert_music(original_log, "melody", "e f gis a", (64, 65, 68, 69))
        # Default tabs play two octaves below written melody: D#2 is below E2.
        self.env.update(LC_ALL="de_DE.UTF-8", LANGUAGE="de")
        graphic, reason, log = self.engrave(score, key("a", 1), key("gis"), -1)
        self.assertIsNone(graphic)
        self.assertIn("No string for pitch", reason)
        self.assert_music(log, "melody", "dis e fisis gis", (63, 64, 67, 68))
        graphic, reason, log = self.engrave(score, key("a", 1), key("gis"), 11)
        self.assertIsNotNone(graphic, (reason, log.read_text()))
        self.assert_music(log, "melody", "dis e fisis gis", (75, 76, 79, 80))
        self.assert_music(log, "chords", "gis b", (80, 83))
        self.assert_music(log, "chords", "dis", (75,), "inversion")
        self.assertEqual(list(self.root.rglob("*.midi")), [])

    def test_single_system_replay_prevents_rewrapping_and_preserves_staff_size(self):
        self.capture_boundaries()
        score, original_log = self.original("single-system", r'''
theMelody = { \autoLineBreaksOff \key c \major
  \repeat unfold 8 { c''4 d'' e'' f'' } }
theChords = \chordmode { \repeat unfold 8 { c1 } }
\setStaffSize #15
''', tail="ulsbs-include-tail.ly", settings=r'''
\include "lilypond-book-preamble.ly"
\paper { line-width = 60\mm }
''')
        self.assertEqual(len(score.graphics), 1)
        self.assertEqual(score.boundaries, ((Fraction(0), Fraction(0), Fraction(8), Fraction(0)),))
        # Remove the source's line lock: only candidate replay may now preserve it.
        score.source.write_text(score.source.read_text().replace(r"\autoLineBreaksOff", ""))
        score = replace(score, tail_position=lilypond_scores._support(score.source)[1])
        with patch.object(lilypond_scores, "_replay", return_value=""):
            graphic, reason, log = self.engrave(score, key("c", 0), key("des"), 1)
        self.assertIsNone(graphic)
        self.assertEqual(reason, "alternative system count does not match original", log.read_text())
        graphic, reason, log = self.engrave(score, key("c", 0), key("des"), 1)
        self.assertIsNotNone(graphic, (reason, log.read_text()))
        self.assert_music(log, "melody", "des ees f ges", (73, 75, 77, 78))
        self.assertEqual(lilypond_scores._boundaries(log.with_suffix(".ulsbs-boundaries")),
                         score.boundaries)
        self.assertIn(r"\setStaffSize #15", log.with_suffix(".ly").read_text())
        self.assert_music(original_log, "melody", "c d e f", (72, 74, 76, 77))

    def test_source_note_language_does_not_change_generated_intervals(self):
        score, original_log = self.original("german", r'''
\language "deutsch"
theMelody = { \key c \major c''4 h' b' c'' }
theChords = \chordmode { c1 }
''')
        self.assert_music(original_log, "melody", "c b bes c", (72, 71, 70, 72))
        graphic, reason, log = self.engrave(score, key("c", 0), key("b"), -1)
        self.assertIsNotNone(graphic, (reason, log.read_text()))
        self.assert_music(log, "melody", "b ais a b", (71, 70, 69, 71))

    def test_head_capture_supports_named_assemblies_and_duplicate_headers(self):
        self.capture_boundaries()
        melody = r'''
theMelody = { \autoLineBreaksOff \key c \major \time 4/4
  e''4 f'' g'' a'' | \break b''4 a'' g'' e'' | }
theLyricsOne = \lyricmode { one two three four five six seven eight }
theLyricsTwo = \lyricmode { red blue green gold white black brown gray }
theChords = \chordmode { c1 g1 }
'''
        between = r'''
\score {
  <<
    \new ChordNames { \theChords }
    \new Staff { \clef "treble" \new Voice = "theVoice" { \theMelody } }
    \new Lyrics \lyricsto "theVoice" { \theLyricsOne }
    \include "ulsbs-internal-scorepart-tabstaff.ly"
    \new Lyrics \lyricsto "theVoice" { \theLyricsTwo }
  >>
  \layout { }
}
\include "ulsbs-internal-score-midi.ly"
'''
        grouped = r'''
\score {
  <<
    \new ChordNames { \theChords }
    \new StaffGroup \with {
      \override StaffGrouper.staffgroup-staff-spacing.padding = #4
    } <<
      \new Staff { \clef "treble" \transpose c' c \new Voice = "theVoice" { \theMelody } }
      \include "ulsbs-internal-scorepart-tabstaff.ly"
      \new TabStaff {
        \tabFullNotation \stemDown
        \clef "moderntab" \set minimumFret = #7 \transpose c' c \theMelody
      }
    >>
  >>
  \layout { }
}
\include "ulsbs-internal-score-midi.ly"
'''
        expected = ((Fraction(0), Fraction(0), Fraction(1), Fraction(0)),
                    (Fraction(1), Fraction(0), Fraction(2), Fraction(0)))
        midi = (76, 77, 79, 81, 83, 81, 79, 76)
        cases = (("between", melody + between, None),
                 ("grouped", melody + grouped, None),
                 ("duplicate", melody,
                  "ulsbs-include-tail-lyricsbetween.ly"))
        for name, music, tail in cases:
            with self.subTest(assembly=name):
                score, original_log = self.original(name, music, tail=tail,
                                                   headers=2 if name == "duplicate" else 1, settings=r'''
\include "lilypond-book-preamble.ly"
\paper { line-width = 100\mm ragged-right = ##t ragged-last = ##t }
''')
                self.assertEqual(len(score.graphics), 2)
                self.assertEqual(score.boundaries, expected)
                self.assertEqual(len(score.source.with_suffix(".ulsbs-boundaries")
                                     .read_text().splitlines()), 2)
                self.assert_music(original_log, "melody", "e f g a b a g e", midi)
                originals = {path: path.read_bytes() for path in (
                    score.source, score.source.with_suffix(".ulsbs-boundaries"),
                    *(self.root / (graphic + ".pdf") for graphic in score.graphics))}
                request = {"schema_version": 1, "requests": [{
                    "snippet_id": score.identity,
                    "layer_prefix": f"ulsbs:transpose:v1:id:{name}",
                    "song_id": name, "title": "Generic two-system score",
                    "key": key("c", 0), "targets": [key(row[0]) for row in MAJOR_TARGETS],
                }]}
                (self.root / "music.ulsbs-scores.json").write_text(json.dumps(request))
                with patch.object(lilypond_scores, "run_cmd", side_effect=self.logged_run):
                    lilypond_scores.generate_scores(
                        Mock(), SimpleNamespace(compile_dir=self.root), "music",
                        {score.identity: score}, self.env, self.includes)
                report = json.loads((self.root / "music.ulsbs-score-results.json").read_text())
                self.assertEqual(report["successful_offsets"], 11, report)
                self.assertEqual(report["fallback_offsets"], 0, report)
                for outcome in report["scores"][0]["offsets"]:
                    with self.subTest(offset=outcome["offset"]):
                        self.assertEqual(outcome["status"], "transposed", outcome)
                        stem = self.root / outcome["graphic"]
                        self.assertEqual(lilypond_scores._boundaries(
                            stem.with_suffix(".ulsbs-boundaries")), expected)
                        self.assertEqual(len(list(stem.parent.glob(stem.name + "-[0-9]*.pdf"))), 2)
                        transformed = stem.with_suffix(".ly").read_text()
                        original = originals[score.source].decode()
                        self.assertTrue(transformed.startswith(original[:score.tail_position]))
                        self.assertTrue(transformed.endswith(original[score.tail_position:]))
                        pitches = self.pitches(stem.with_suffix(".log"), "melody")
                        signed = outcome["attempts"][-1]["interval"]
                        self.assertEqual([60 + 12 * octave + NATURALS[letter] + accidental // 2
                                          for octave, letter, accidental in pitches],
                                         [number + signed for number in midi])
                self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(list(self.root.rglob("*.midi")), [])

    def test_boundary_capture_preserves_existing_original_callback(self):
        settings = r'''
\layout { \context { \Score
  \override System.after-line-breaking = #(lambda (system)
    (ly:message "ULSBS-EXISTING-CALLBACK")
    (ly:grob-translate-axis! system 1 X))
} }
'''
        music = "theMelody = { c''4 d'' e'' f'' }"
        plain, plain_log = self.original("callback-plain", music, settings=settings)
        self.capture_boundaries()
        captured, captured_log = self.original("callback-captured", music, settings=settings)
        self.assertEqual(plain_log.read_text().count("ULSBS-EXISTING-CALLBACK"), 1)
        self.assertEqual(captured_log.read_text().count("ULSBS-EXISTING-CALLBACK"), 1)
        self.assertEqual(len(captured.boundaries), 1)
        with pikepdf.open(self.root / (plain.graphics[0] + ".pdf")) as before, \
                pikepdf.open(self.root / (captured.graphics[0] + ".pdf")) as after:
            self.assertEqual(list(before.pages[0].MediaBox), list(after.pages[0].MediaBox))
            self.assertEqual(before.pages[0].Contents.read_bytes(), after.pages[0].Contents.read_bytes())

    def test_initial_grace_with_pickup_volta_lyrics_and_tabs(self):
        self.capture_boundaries()
        # Firmeza-like timing: the only grace boundary is the very first moment.
        score, original_log = self.original("initial-grace", r'''
theMelody = \relative c'' {
  \key f \major \time 4/4 \partial 8
  \repeat volta 2 {
    \grace \parenthesize c8 c8 |
    f8. f16 f8. f16 c8.( c16)( c8.) c16 |
    f8. f16 f8. f16 c4( c8) f8 | \break
    f8. c16 c8. f16 f8. c16 c8. c16 |
    f8. f16 f8. f16 f4( f8)
  }
}
theLyricsOne = \lyricmode {
  Fir -- me -- za bem fir -- me -- za pe -- co em con -- cen -- tra -- cao
  Fir -- me -- za bem fir -- me -- za na cor -- ren -- te da ses -- sao
}
theChords = \chordmode { s8 | f2 c | f c | f4 c f c | f2.~ f8 }
''', tail="ulsbs-include-tail.ly", settings=r'''
\include "lilypond-book-preamble.ly"
\layout { \context { \Voice
  \consists #(lambda (context) (make-engraver
    (listeners ((note-event engraver event)
      (ulsbs-test-pitch "performed" "note" (ly:event-property event 'pitch))))))
} }
''')
        expected = ((Fraction(0), Fraction(-1, 8), Fraction(17, 8), Fraction(0)),
                    (Fraction(17, 8), Fraction(0), Fraction(4), Fraction(0)))
        self.assertEqual(score.boundaries, expected)
        self.assertEqual(len(score.graphics), 2)
        # Listen to actual notes: 2.26's parenthesize helper has a dummy pitch
        # in its structured expression that is never emitted to the engraver.
        original_pitches = self.pitches(original_log, "performed")
        melody_midi = (72, 72, 77, 77, 77, 77, 72, 72, 72, 72,
                       77, 77, 77, 77, 72, 72, 77, 77, 72, 72, 77, 77,
                       72, 72, 72, 77, 77, 77, 77, 77, 77)
        self.assertEqual([60 + 12 * octave + NATURALS[letter] + accidental // 2
                          for octave, letter, accidental in original_pitches], list(melody_midi))
        for offset, target in enumerate(("f", "fis", "g", "aes", "a", "bes",
                                         "b", "c", "des", "d", "ees", "e")):
            if not offset:
                continue
            signed = offset if offset <= 6 else offset - 12
            with self.subTest(offset=offset):
                graphic, reason, log = self.engrave(score, key("f", 0), key(target), signed)
                self.assertIsNotNone(graphic, (reason, log.read_text()))
                self.assertEqual(lilypond_scores._boundaries(
                    (self.root / graphic).with_suffix(".ulsbs-boundaries")), expected)
                pitches = self.pitches(log, "performed")
                self.assertEqual(len(pitches), len(original_pitches))
                self.assertEqual([60 + 12 * octave + NATURALS[letter] + accidental // 2
                                  for octave, letter, accidental in pitches],
                                 [number + signed for number in melody_midi])
                self.assertTrue((self.root / (graphic + "-2.pdf")).is_file())
        self.assertEqual(list(self.root.rglob("*.midi")), [])

    def test_internal_grace_replay_preserves_notes_lyrics_and_tablature_events(self):
        self.capture_boundaries()
        settings = r'''
\include "lilypond-book-preamble.ly"
\layout { \context { \Score
  \consists #(lambda (context) (make-engraver
    (listeners ((note-event engraver event)
      (let ((moment (ly:context-current-moment context)))
        (ly:message "ULSBS-NATIVE-NOTE ~a ~a ~a" (ly:moment-main moment)
          (ly:moment-grace moment) (+ 60 (ly:pitch-semitones (ly:event-property event 'pitch)))))))
    (acknowledgers
      ((lyric-syllable-interface engraver grob source)
        (ly:message "ULSBS-NATIVE-LYRIC ~a ~a"
          (ly:context-current-moment context) (ly:grob-property grob 'text)))
      ((tab-note-head-interface engraver grob source)
        (let ((moment (ly:context-current-moment context)))
          (ly:message "ULSBS-NATIVE-TAB ~a ~a ~a" (ly:moment-main moment)
            (ly:moment-grace moment) (ly:grob-property grob 'text)))))))
} }
'''
        cases = (
            ("shared", r"c''1*4 \grace { d''8 \break e''16 \break f''16 } \break g''1*4",
             "", ((4, "-1/8"), (4, "-1/16"), (4, 0))),
            ("initial-internal", r"\grace { c''8 \break d''8 } e''1*4", "", ((0, "-1/8"),)),
            ("after", r"\afterGrace c''1*4 { d''8 \break e''8 } f''1*4", "", ((3, "-1/8"),)),
            ("repeat", r"\partial 4 c''4 \repeat volta 2 { d''1 \grace { e''8 \break f''8 } g''1 } a''1",
             "", (("5/4", "-1/8"),)),
            ("alternatives", r"\repeat volta 2 { c''1 } \alternative { { \grace { d''8 \break e''8 } f''1 } { g''1 } } a''1",
             "", ((1, "-1/8"),)),
            ("tuplet", r"c''1*4 \grace { \tuplet 3/2 { d''8 e''8 \break f''8 } } g''1*4",
             "", ((4, "-1/12"),)),
            ("second-voice", "c''1*4 f''1*4",
             r"theMelodyTwo = { g'1*4 \grace { a'8 \break b'8 } c''1*4 }", ((4, "-1/8"),)),
        )
        for name, melody, second, endpoints in cases:
            with self.subTest(case=name):
                score, original_log = self.original(
                    name, r"theMelody = { \key c \major " + melody + " }\n" + second + r'''
theLyricsOne = \lyricmode { \set includeGraceNotes = ##t one two three four five six seven }
theChords = \chordmode { c1 f1 g1 c1 }
''', tail=("ulsbs-include-tail-multivoice-twotabs.ly" if second else "ulsbs-include-tail.ly"),
                    settings=settings)
                self.assertEqual(tuple(row[2:] for row in score.boundaries[:-1]),
                                 tuple((Fraction(main), Fraction(grace)) for main, grace in endpoints))
                # Remove original forced breaks from the copied fixture, so
                # only the production replay can reproduce the captured layout.
                score.source.write_text(score.source.read_text().replace(r"\break", ""))
                score = next(item for item in lilypond_scores.prepare_scores(self.root, "music").values()
                             if item.source == score.source)
                note_pattern = r"ULSBS-NATIVE-NOTE (\S+) (\S+) (-?\d+)"
                original_notes = re.findall(note_pattern, original_log.read_text())
                original_lyrics = re.findall(r"ULSBS-NATIVE-LYRIC (.+)", original_log.read_text())
                tab_pattern = r"ULSBS-NATIVE-TAB (\S+) (\S+) (.+)"
                original_tabs = re.findall(tab_pattern, original_log.read_text())
                self.assertTrue(original_notes)
                self.assertTrue(original_lyrics)
                self.assertTrue(original_tabs)
                for signed, target in ((0, "c"), (2, "d"), (-2, "bes")):
                    with self.subTest(interval=signed):
                        graphic, reason, log = self.engrave(score, key("c", 0), key(target), signed)
                        self.assertIsNotNone(graphic, (reason, log.read_text()))
                        self.assertEqual(lilypond_scores._boundaries(
                            (self.root / graphic).with_suffix(".ulsbs-boundaries")), score.boundaries)
                        notes = re.findall(note_pattern, log.read_text())
                        self.assertEqual(notes, [(main, grace, str(int(pitch) + signed))
                                                 for main, grace, pitch in original_notes])
                        self.assertEqual(re.findall(r"ULSBS-NATIVE-LYRIC (.+)", log.read_text()),
                                         original_lyrics)
                        tabs = re.findall(tab_pattern, log.read_text())
                        self.assertEqual([(main, grace) for main, grace, _ in tabs],
                                         [(main, grace) for main, grace, _ in original_tabs])
                        if signed == 0:
                            self.assertEqual(tabs, original_tabs)
        self.assertEqual(list(self.root.rglob("*.midi")), [])

    def test_charango_tunings_bassclef_and_both_multivoice_tails(self):
        music = r'''
theMelody = { \key c \major \time 4/4 \voiceOne c''4 cis'' des'' fis'' }
theMelodyTwo = { \key c \major \time 4/4 \voiceTwo g'4 aes' a' b' }
theChords = \chordmode { c1:7/+e }
'''
        cases = (
            ("charango", "ulsbs-include-tail.ly", "ul-charango-tuning", (52, 45, 40, 48, 43)),
            ("charango-skipmiddle", "ulsbs-include-tail.ly",
             "ul-charango-skipmiddle-tuning", (52, 45, 76, 48, 43)),
            ("bassclef", "ulsbs-include-tail_bassclef.ly", "ul-guitar-tuning",
             (64, 59, 55, 50, 45, 40)),
            ("multivoice", "ulsbs-include-tail-multivoice-notab.ly", "ul-guitar-tuning",
             (64, 59, 55, 50, 45, 40)),
            ("twotabs", "ulsbs-include-tail-multivoice-twotabs.ly", "ul-guitar-tuning",
             (64, 59, 55, 50, 45, 40)),
        )
        for name, tail, tuning, tuning_midi in cases:
            with self.subTest(tail=tail, tuning=tuning):
                score, original_log = self.original(
                    name, music, tail, "ul-chosen-tuning = #" + tuning
                )
                self.assert_music(original_log, "melody", "c cis des fis", (72, 73, 73, 78))
                self.assert_music(original_log, "second", "g aes a b", (67, 68, 69, 71))
                original_tuning = self.pitches(original_log, "tuning", "string")
                self.assertEqual([60 + octave * 12 + NATURALS[letter] + accidental // 2
                                  for octave, letter, accidental in original_tuning],
                                 list(tuning_midi))
                for signed, target, notes, second, chords in (
                    (2, "d", "d dis ees gis", "a bes b cis", "d fis a c fis"),
                    (-2, "bes", "bes b ces e", "f ges g a", "bes d f aes d"),
                ):
                    with self.subTest(interval=signed):
                        graphic, reason, log = self.engrave(score, key("c", 0), key(target), signed)
                        self.assertIsNotNone(graphic, (reason, log.read_text()))
                        self.assert_music(log, "melody", notes,
                                          [number + signed for number in (72, 73, 73, 78)])
                        self.assert_music(log, "second", second,
                                          [number + signed for number in (67, 68, 69, 71)])
                        self.assert_music(log, "chords", " ".join(chords.split()[:4]),
                                          [number + signed for number in (60, 64, 67, 70)])
                        self.assert_music(log, "chords", chords.split()[-1], (52 + signed,), "bass")
                        self.assertEqual(self.pitches(log, "tuning", "string"), original_tuning)
        self.assertEqual(list(self.root.rglob("*.midi")), [])

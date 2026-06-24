    % SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
    % SPDX-License-Identifier: GPL-3.0-or-later
    %
    % LilyPond tail include: chords, staff, TAB, lyrics.
    % This file is part of the 'ulsbs' package.

    %% ulsbs-include-tail-twomelodies-twotabs.ly
    %% =========================================
    %%
    %% This file should be included as the last thing within 'lilypond'
    %% environment, and creates a score with chord names, notes (two melodies
    %% within one staff), two guitar tablatures and lyrics, in that order, if
    %% they have been defined.
    %%
    %% Requires that 'ulsbs-include-head.ly' has been included before.
    %%
    %% See file 'ulsbs-include-head.ly' for documentation.
    %%
    \include "ulsbs-internal-common-tail.ly"
    \score {
      <<
        \new ChordNames {
          % Use chord name modifications defined in ulsbs-internal-common-head.ly
          \set chordNameExceptions = #chExceptions
          \theChords
        }
        \new Staff <<
          \clef "treble"
          \new Voice = "theVoice" { \theMelody }
          \\
          \new Voice = "theVoiceTwo" {
            %\override AmbitusLine.color = #color-melodytwo
            \override AmbitusNoteHead.color = #color-melodytwo
            \override AmbitusAccidental.color = #color-melodytwo
            \override NoteHead.color = #color-melodytwo
            \override Stem.color = #color-melodytwo
            \override Beam.color = #color-melodytwo
            \override Tie.color = #color-melodytwo
            \override Slur.color = #color-melodytwo
            \override Parentheses.color = #color-melodytwo
            \override Staff.LedgerLineSpanner.color = #color-melodytwo
            \theMelodyTwo
          }
        >>
        \include "ulsbs-internal-scorepart-tabstaff-melody2.ly"
        \include "ulsbs-internal-scorepart-tabstaff.ly"
        \include "ulsbs-internal-scorepart-lyrics.ly"
      >>
      \layout { }
    }
    \include "ulsbs-internal-score-midi.ly"

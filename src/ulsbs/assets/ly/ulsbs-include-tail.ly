    % SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
    % SPDX-License-Identifier: GPL-3.0-or-later
    %
    % LilyPond tail include: chords, staff, TAB, lyrics.
    % This file is part of the 'ulsbs' package.
    %
    % Covered by assets/lilypond-score-cache-assets.json.
    % After changing this file, run ulsbs-score-cache-assets --rewrite
    % or from the engine root:
    % PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite
    % See ARCHITECTURE.md#trusted-cache-assets for converted-tail variants.

    %% ulsbs-include-tail.ly
    %% =====================
    %%
    %% This file should be included as the last thing within 'lilypond'
    %% environment, and creates a score with chord names, notes, guitar
    %% tablature and lyrics, in that order, if they have been defined.
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
        \new Staff {
          \clef "treble"
          \new Voice = "theVoice" { \theMelody }
        }
        \include "ulsbs-internal-scorepart-tabstaff.ly"
        \include "ulsbs-internal-scorepart-lyrics.ly"
      >>
      \layout { }
    }
    \include "ulsbs-internal-score-midi.ly"

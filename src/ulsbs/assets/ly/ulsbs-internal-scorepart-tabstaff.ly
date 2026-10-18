        % SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
        % SPDX-License-Identifier: GPL-3.0-or-later
        %
        % LilyPond score part: TAB staff for melody.
        % This file is part of the 'ulsbs' package.
        %
        % Covered by assets/lilypond-score-cache-assets.json.
        % After changing this file, run ulsbs-score-cache-assets --rewrite
        % or from the engine root:
        % PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite
        % See ARCHITECTURE.md#trusted-cache-assets for converted-tail variants.

        % TAB staff to be inserted into a score
        % Transposed down two octaves to the common male singing range
        \new TabStaff {
          \clef "moderntab" \transpose c c,, \theMelody
        }

% SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
% SPDX-License-Identifier: GPL-3.0-or-later
% Record each laid-out system's exact start/end main and grace moments in a
% job-local .ulsbs-boundaries sidecar without changing the music or breaks.
%
% Covered by assets/lilypond-score-cache-assets.json.
% After changing this file, run ulsbs-score-cache-assets --rewrite
% or from the engine root:
% PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite
% See ARCHITECTURE.md#trusted-cache-assets for converted-tail variants.

#(define ulsbs-boundary-file
   (string-append (ly:parser-output-name) ".ulsbs-boundaries"))
% Truncate the sidecar before appending this job's system boundaries.
#(call-with-output-file ulsbs-boundary-file (lambda (port) #t))
% Append the first and last break-edge moments, preserving their grace parts.
#(define (ulsbs-capture-boundaries system)
   (let* ((columns (ly:grob-object system 'columns))
          (items (if (ly:grob-array? columns) (ly:grob-array->list columns) '()))
          (edges (filter (lambda (column) (not (= 0 (ly:item-break-dir column)))) items)))
     (when (pair? edges)
       (let ((start (ly:grob-property (car edges) 'when))
             (end (ly:grob-property (car (reverse edges)) 'when))
             (port (open-file ulsbs-boundary-file "a")))
         (format port "~a ~a ~a ~a\n"
           (ly:moment-main start) (ly:moment-grace start)
           (ly:moment-main end) (ly:moment-grace end))
         (close-port port)))))
\layout {
  \context {
    \Score
    % Capture boundaries while preserving the wrapped callback's original value.
    \override System.after-line-breaking =
      #(grob-transformer 'after-line-breaking
         (lambda (system original)
           (ulsbs-capture-boundaries system)
           original))
  }
}

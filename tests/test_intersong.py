# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Standalone intersong submission, geometry and exclusion contracts."""

import os
from pathlib import Path
import re
import unittest

import test_chords as chords
import test_song_lifecycle as helpers
from test_tex_integration import ROOT


ADJACENT = r"""
\begin{ulSongs}{}
\beginsong{Before}[id={before}]
\beginverse*
BeforeAnchor
\endverse
\endsong
\begin{intersong}
\begin{feeler}
QuotationAnchor: our soul is changed in the telling of our story.
\end{feeler}
\vfill
\end{intersong}
\beginsong{After}[id={after}]
\beginverse*
AfterAnchor
\endverse
\endsong
\end{ulSongs}
"""


class IntersongTests(unittest.TestCase):
    compile_source = helpers.SongLifecycleTests.compile_source
    pdf_text = helpers.SongLifecycleTests.pdf_text
    setUp = helpers.SongLifecycleTests.setUp
    compile_checked = chords.ChordTests.compile_checked

    @classmethod
    def setUpClass(cls):
        helpers.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_INTERSONG_DIAGNOSTICS", ROOT / "build/intersong"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def compile_intersong(self, body, preamble="", *, label=""):
        self.compile_checked(body, preamble, label=label)
        self.assertTrue((self.book / "book.ulsbs.psv").is_file())

    def test_adjacent_songs_feeler_and_bars(self):
        for height in ("0pt", ".4pt"):
            with self.subTest(height=height):
                self.compile_intersong(ADJACENT, r"\setlength{\ulSongBarHeight}{" + height + "}",
                                   label=height)
                text = self.pdf_text()
                self.assertEqual(text.count("QuotationAnchor"), 1)
                self.assertLess(text.index("BeforeAnchor"), text.index("QuotationAnchor"))
                self.assertLess(text.index("QuotationAnchor"), text.index("AfterAnchor"))

    def test_selection_excludes_standalone_block_and_keeps_requested_order(self):
        self.compile_intersong(ADJACENT, r"\ulIncludeOnlySongs{2,1}")
        text = self.pdf_text()
        self.assertNotIn("QuotationAnchor", text)
        self.assertLess(text.index("AfterAnchor"), text.index("BeforeAnchor"))
        psv = (self.book / "book.ulsbs.psv").read_text()
        self.assertLess(psv.index("|after|"), psv.index("|before|"))

    def test_song_end_resets_explanation_state_before_an_intersong_block(self):
        self.compile_intersong(r"""
\begin{ulSongs}{}
\beginsong{Before}[id={before}]
\beginverse*
\[C]BeforeAnchor
\endverse
\begin{explanation}[EN]
FirstExplanationAnchor.
\end{explanation}
\endsong
\begin{intersong}
\begin{feeler}
QuotationAnchor.
\end{feeler}
\begin{explanation}[EN]
\begin{description}
\item[Term:] InterExplanationAnchor describes the quotation.
\end{description}
\end{explanation}
\end{intersong}
\beginsong{After}[id={after}]
\beginverse*
\[G]AfterAnchor
\endverse
\endsong\end{ulSongs}
""")

    def test_omitted_and_selected_bodies_evaluate_once_without_shipping_writes(self):
        body = ADJACENT.replace("QuotationAnchor:",
            r"\Effect\write16{INTERSONG-SHIPPED} QuotationAnchor:")
        body += r"\typeout{INTERSONG-EFFECTS=\the\Effects}"
        for label, control in (("visible", ""), ("omitted", r"\ulScripture{false}"),
                               ("selected", r"\ulIncludeOnlySongs{2}")):
            with self.subTest(label=label):
                source = helpers.document(body, control + r"""
\newcount\Effects
\def\Effect{\global\advance\Effects1 }
""")
                output = self.compile_source(source, label=label)
                self.assertEqual(re.findall(r"INTERSONG-EFFECTS=(\d+)", output), ["1"])
                self.assertEqual(output.count("INTERSONG-SHIPPED"), int(label == "visible"))
                self.assertEqual(self.pdf_text().count("QuotationAnchor"), int(label == "visible"))
                if label == "selected":
                    self.assertNotIn("BeforeAnchor", self.pdf_text())
                    self.assertIn("AfterAnchor", self.pdf_text())

    def test_invalid_nested_lifecycle_is_rejected(self):
        for label, body, error in (
            ("song", r"\beginsong{Bad}\begin{intersong}", "intersong inside a song"),
            ("nested", r"\begin{intersong}\begin{intersong}", "nested intersong"),
            ("beginsong", r"\begin{intersong}\beginsong{Bad}", "beginsong inside intersong"),
        ):
            with self.subTest(label=label):
                output = self.compile_source(helpers.document(r"\begin{ulSongs}{}" + body),
                                             label=label, failure="Invalid song lifecycle:")
                self.assertIn(error, " ".join(output.replace("(ulsbs-song)", "").split()))

    def test_english_boundary_quote_and_following_song_psv(self):
        self.compile_intersong(r"""
\begin{ulSongs}{}
\beginsong{Primer}
\beginverse*
Primer.
\endverse
\endsong
\sclearpage
\setcounter{page}{253}\setcounter{ulSongNumber}{346}
\beginsong{I Release}[id={i-release}]
\beginverse
\[<A>]I re|\[<E>Em]lease and I let |go \rep{2}
I let the |\[D]spirit run my |\[Em]life \rep{2}
And my |\[Em]arms are open |wide \rep{2}
And I'm |\[D]only here for |\[Em]love \rep{2}
No more |\[Em]struggles no more |strife \rep{2}
With my |\[D]faith I see the |\[Em]light \rep{2}
\endverse
\beginverse
\beginrep
Yes I am |\[Em]free by the |spirit \rep{2}
And I'm |\[D]only here for |\[Em]love \rep{2}
\endrep
\endverse
\endsong
\begin{intersong}
\begin{feeler}
``True confession consists of telling our deed in such a way that our soul is changed in the telling it.'' --- \emph{Maude Petre} (1863--1942)
\end{feeler}
\vfill
\end{intersong}
\beginsong{Angels of Healing}[id={angels},by={Lisa Thiel}]
\transpose{-2}\meter{3}{4}
\beginverse\memorize
\beginrep
|\[<E>Em]Bles\[^<F#>]sing |\[<G>G]angels come |\[D]be with |\[Em]me
|\[Em]Heal my |\[D]spirit, |\[Em]mind and bo|dy
\endrep
\endverse
\notesoff
\beginverse
\beginrep
|^Blessing |^angels of |^green and |^gold
|^Heal my |^heart and |^heal my |soul
\endrep
\endverse
\beginverse
\beginrep
|^Blessing |^angels of |^violet and |^blue
|^Open my |^eyes to the |^vision of |truth
\endrep
\endverse
\endsong
\beginsong{I Am the Light of the Soul}[id={light}]
\meter{6}{8}
\beginverse
\beginrep
|\[<A>Am]I \[<E>]am the |\[C]light of the soul I am |\[G]bountiful
I am |\[F]beautiful I am |\[Dm]bliss I am I |\[E]am
\endrep
\endverse
\beginverse
\beginrep
|\[Am]I am the light of the |\[G]soul I am |\[Dm]bountiful
I am |\[F]beautiful I am |\[Dm]bliss I am I |\[E]am
\endrep
\endverse
\begin{feeler}
``\ldots he that beholds must be akin to that which he beholds, and must,
before he comes to this vision, be transformed into its likeness.
Never could the eye have looked upon the sun had it not become sun-like,
and never can the soul see Beauty unless she has become beautiful.''
--- \emph{Plotinus} (c. 240--270) in \emph{Enneads}
\end{feeler}
\endsong
\end{ulSongs}
""", r"\renewcommand\ulSongEndMark{END}")
        self.assertIn("Maude Petre", self.pdf_text())
        self.assertIn("END", self.pdf_text())
        psv = (self.book / "book.ulsbs.psv").read_text()
        for song_id, number in (("i-release", 346), ("angels", 347), ("light", 348)):
            self.assertRegex(psv, rf"ID-NR-PAGE-Y\|{song_id}\|{number}\|\d+\|\d+")


if __name__ == "__main__":
    unittest.main()

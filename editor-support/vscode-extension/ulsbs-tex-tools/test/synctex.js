// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

const assert = require("node:assert/strict");
const { gzipSync } = require("node:zlib");
const { readSyncTeX } = require("../core/synctex");

async function run() {
  // Reduced from LuaLaTeX 1.24.0 -synctex=1 output, with the input names
  // and source lines set as in a compiler-published sidecar. The same song
  // is included on both pages; the second tag is declared between pages.
  const bookPath = "/project/book.tex";
  const songPath = "../songs/a: \u00e4/song.tex ";
  const otherPath = "C:\\project\\other\\song.tex";
  const songKey = "file:///project/songs/a%3A%20%C3%A4/song.tex%20";
  const otherKey = "file:///C:/project/other/song.tex";
  const inputKeys = new Map([[bookPath, "file:///project/book.tex"], [songPath, songKey], [otherPath, otherKey]]);
  const names = [];
  const fixture = `SyncTeX Version:1
Input:1:${bookPath}
Input:5:${songPath}
Input:7:/untrusted/songs/a: \u00e4/song.tex${" "}
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
!361
{1
[1,40:4736286,4736286:26673152,41484288,0
(5,10:8799518,8865054:22609920,462029,7209
x5,10:10179706,8865054
g5,10:10397941,8865054
x5,10:11455692,8865054
)
(5,11:8799518,9651486:22609920,462029,14418
x5,11:9745858,9651486
)
(5,0:8799518,26200000:22609920,462029,0
x5,0:9745858,26200000
)
]
!995
}1
Input:6:${songPath}
!53
{2
x6,10:10179706,8865054
}
{3
x8,97:10179706,8865054
}
Input:8:${otherPath}
{4
x7,24:10179706,8865054
}
Postamble:
Count:23
Post scriptum:
`;
  const index = await readSyncTeX(gzipSync(fixture), (name) => {
    names.push(name);
    return inputKeys.get(name) ?? null;
  });
  assert.deepEqual(names, [bookPath, songPath, "/untrusted/songs/a: \u00e4/song.tex ", songPath, otherPath]);
  const closeTo = (actual, expected) => assert.ok(Math.abs(actual - expected) < 0.0001, `${actual} != ${expected}`);
  const hit = index.forward(songKey, 10);
  assert.equal(hit.page, 1);
  closeTo(hit.x, 154.749675);
  closeTo(hit.y, 134.764622);
  assert.equal(index.forward(songKey, 10, 2).page, 2);
  assert.equal(index.forward(songKey, 10, 7).page, 2);
  assert.equal(index.forward(otherKey, 97).page, 3);
  assert.equal(index.forward(songKey, 12), null);
  assert.equal(index.forward(songKey, 0), null);
  assert.equal(index.forward(songKey, "10"), null);
  assert.equal(index.forward("song.tex", 10), null);
  assert.equal(index.forward(songPath, 10), null);
  assert.equal(index.forward(otherKey, 10), null);
  assert.deepEqual(index.inverse(1, 136, 131), { source: songKey, line: 10 });
  assert.deepEqual(index.inverse(1, 136, 145), { source: songKey, line: 11 });
  assert.deepEqual(index.inverse(3, hit.x, hit.y), { source: otherKey, line: 97 });
  assert.equal(index.inverse(1, 140, 400), null); // Only a generated line and the page box here.
  assert.equal(index.inverse(4, hit.x, hit.y), null); // Exact coordinates, but untrusted input.
  assert.equal(index.inverse(5, hit.x, hit.y), null);
  assert.equal(index.inverse(1, NaN, hit.y), null);
  assert.equal(index.inverse(1, hit.x, Infinity), null);

  // Compact points borrow the raw vertical value from preceding records even
  // when those records cannot resolve to a project file. Units, magnification,
  // and offsets are independently applied, as in the native preamble scanner.
  const compact = `SyncTeX Version:1
Input:1:${bookPath}
Output:pdf
Magnification:2000
Unit:8192
X Offset:80
Y Offset:-40
Content:
{1
x5,10:160,320
x1,0:160,=
x1,13,7:240,=
c300,480
g1,14:320,=
}
{2
$1,88:500,=
}
Postamble:
`;
  const bytes = Uint8Array.from(gzipSync(compact.replaceAll("\n", "\r\n"))).buffer;
  const compactIndex = await readSyncTeX(bytes, (name) => inputKeys.get(name) ?? null);
  const key = inputKeys.get(bookPath);
  const compactHit = compactIndex.forward(key, 13);
  closeTo(compactHit.x, 69.738481);
  closeTo(compactHit.y, 74.719801);
  const glue = compactIndex.forward(key, 14);
  closeTo(glue.y, 114.570361);
  assert.deepEqual(compactIndex.inverse(1, glue.x, glue.y), { source: key, line: 14 });
  assert.equal(compactIndex.forward(key, 88).y, glue.y);

  // Reduced from an engraved ULSBS verse. A later line's repeat bar has a
  // running depth and nearly the same x coordinate as an earlier lyric word.
  const verse = `SyncTeX Version:1
Input:1:${songPath}
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
{1
[1,236:1678211,2862282:22935564,34617783,0
(1,47:5552043,12945875:2496135,431751,188744
x1,47:6373865,12945875
x1,236:6807975,12945875
x1,48:8048178,12945875
)
(1,69:2786163,24896678:1197736,431751,7864
x1,69:3983899,24896678
)
(1,88:3025238,34529940:32768,1305543,0
r1,88:3058006,34529940:32768,1305543,-1073741824
)
]
}1
Postamble:
`;
  const verseIndex = await readSyncTeX(gzipSync(verse), (name) => inputKeys.get(name) ?? null);
  assert.deepEqual(verseIndex.inverse(1, 46.69, 375.37), { source: songKey, line: 69 });
  assert.equal(verseIndex.inverse(1, 46.69, 300), null);
  // The text boundary tagged with its vertical ancestor uses its lyric box;
  // a genuinely different source line inside that box still stays distinct.
  assert.deepEqual(verseIndex.inverse(1, 103.37, 193.69), { source: songKey, line: 47 });
  assert.deepEqual(verseIndex.inverse(1, 115, 193.69), { source: songKey, line: 48 });
  closeTo(verseIndex.forward(songKey, 88).y, 524.916633);
  closeTo(verseIndex.forward(songKey, 236).x, 103.493350);

  // The same generated system can be used twice; its parent box, not its
  // generated filename, is the source location for each placement.
  const scores = `SyncTeX Version:1
Input:1:${songPath}
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
{1
(1,80:2983486,10624510:22935564,7762228,0
(2,1:2983486,10624510:22826215,7762228,0
)
)
(1,120:2983486,18254929:22935564,7564883,0
(2,1:2983486,18254929:22826215,7564883,0
)
)
(1,121:2950000,20000000:1197736,431751,7864
x1,121:4147736,20000000
)
}1
Input:2:/project/temp/work/lily-sample-systems.tex
Postamble:
`;
  const scoreIndex = await readSyncTeX(gzipSync(scores), (name) => inputKeys.get(name) ?? null);
  assert.deepEqual(scoreIndex.inverse(1, 80, 75), { source: songKey, line: 80, kind: "lilypond" });
  assert.deepEqual(scoreIndex.inverse(1, 80, 200), { source: songKey, line: 120, kind: "lilypond" });
  assert.deepEqual(scoreIndex.inverse(1, 50, 301), { source: songKey, line: 121 });
  assert.equal(scoreIndex.inverse(1, 20, 75), null);

  // Reduced from page 28 of the full book: LuaLaTeX tags the running head
  // with a shipout line, not the song whose title starts lower on the page.
  const runningHead = `SyncTeX Version:1
Input:1:${songPath}
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
{28
[1,661:1678211,1184072:22749096,36531925,0
[1,661:1678211,1184072:22749096,932339,0
(1,661:1678211,1880479:22749096,550500,235932
x1,661:2337635,1880479
)
]
(1,660:4491150,4100000:2970000,540000,0
x1,660:7461150,4100000
)
]
}28
Postamble:
`;
  const headIndex = await readSyncTeX(gzipSync(runningHead), (name) => inputKeys.get(name) ?? null);
  assert.deepEqual(headIndex.inverse(28, 30.52, 26.26), { kind: "header" });
  assert.deepEqual(headIndex.inverse(28, 90.70, 59.65), { source: songKey, line: 660 });

  await assert.rejects(readSyncTeX(gzipSync(fixture.replace("Version:1", "Version:2")), () => null), /version/);
  await assert.rejects(readSyncTeX(gzipSync(fixture.replace("Unit:1", "Unit:0")), () => null), /preamble/);
  await assert.rejects(readSyncTeX(new Uint8Array([1, 2, 3]), () => null));
  console.log("SyncTeX tests passed");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

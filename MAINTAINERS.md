# Maintainer Notes

This file documents the release workflow for the repository maintainer. It is
public intentionally and must not contain credentials, tokens, or other secrets.

## Engine Maintenance

Only LuaLaTeX is supported. `ulsbs.sty` loads required companion modules.
Preserve the documented public authoring API when changing internals.
[Architecture](ARCHITECTURE.md#song-engine) maps module owners,
extension hooks, index snapshots and PDF contracts; the
[writing guide](WRITING_SONGBOOKS.md) is the public syntax reference. The regression
suite tests current engine behavior and operational contracts.

Before distributing an engine change:

- Run `./ulsbs-test` in the supported compiler container, including normalized
  TeX and Python integration checks. A focused test run alone is not a release
  gate. Inspect wheel/sdist and installed-package assets as well as source-tree
   lookup; all required `.code.tex` and `.lua` companions must be included.
- Validate a standalone third-party lyrics/chords book with manual
  draft/full/full LuaLaTeX. Validate fresh and
  retained builds, separate output directories and convergence after index edits.
  A corrupt/aborted snapshot must diagnose rather than silently reuse stale data.
- For variant changes, verify omitted availability/default-only builds, declared
  subsets/all, default-first declaration ordering and quick-selector conflicts.
  Include a nested third-party custom class: presets must run after its complete
  setup but before author overrides, and policy must freeze before begin-document
  callbacks. Check grouped book-off/local-on denial and effective predicates,
  compact beat-only/empty geometry, replay and once-only source effects.
- Inspect the installed `ulsbs-variants.def.tex` registry and every referenced
  preset as well as Python resources. Use
  `python3 tests/test_modules.py --packaging-smoke` for source/wheel/sdist asset
  consistency and installed lookup. Exercise selector-free direct default and a
  separate non-default launcher; manual TeX does not install compiler score recipes.
  Test score-only bass-clef multikey separately from inline chords. Keep printed
  score visibility, score ChordNames/recipes, edition eligibility and media opt-ins
  independent, including global no-MIDI/no-audio switches.
- For migration delivery, preserve the versioned v2 entry point and
  v1-then-v2 upgrade sequence. Run focused `test_migrate_syntax_v1` /
  `test_migrate_syntax_v2` checks and the latter's `--installed-smoke` and
  `--installed-smoke-container` modes when validating tool delivery. Verify one
  original-source finalization, original coordinates, whole-file rejection,
  idempotence, mixed safe/rejected inputs, tag collisions and explicit config
  no-write behavior in every mode, including `--write`. Installed semantic smoke
  is not full installed raw-score/TeX or release acceptance. Unsupported TeX forms
  remain diagnostics, not invitations to widen conversion heuristics.
- Keep corpus migration separate: manually review each main source's availability
  and root/profile `variants` selection, known scripts and consumer catalog IDs.
  `--config-file` reviews selected configs but never writes or follows their book
  paths. Directory scans prune recognized nested engines; use explicit consumer
  scopes and inspect diffs, rather than treating the tool as a filesystem sandbox.
- Recipe changes must retain score-cache validation and audited asset inputs.
  Use the [score-cache maintenance workflow](ARCHITECTURE.md#opt-in-score-layers)
  for asset review; do not normalize away tuning/clef differences or rewrite a
  trust manifest merely to accept an unexplained cache result.
- For rendering changes, inspect representative affected books and variants,
  including long songs, selections, indices or multikey scores where relevant.
  Broaden coverage when the change warrants it, rather than requiring a complete
  consumer-corpus matrix for every edit. Default styling is allowed to evolve;
  there is no legacy pixel/PDF compatibility requirement. Test current behavior;
  do not add old-engine comparisons or guards for nonexistent legacy macros.
  Historical-input tests remain necessary for the migration tools.
- Check annotation alignment on physical lines, wrapped lyrics and independent
  raised/lowered groups. Verify shared `\ulMelodySize` slot/render sizing, retained
  ink clearance, scoped scalar verse spacing and font-based translation/prose
  leading. Read current styling values from the runtime and presets; use explicit
  fixture policies rather than pinning evolving defaults.
- Check content, pagination/navigation and ID/occurrence semantics separately
  from pixels. Inspect remaining visual differences explicitly rather than
  assuming historical byte identity. Check all twelve layer names/defaults and
  print policy, effective-original geometry, shipped-page metadata, normal PDF
  title/author/rights XMP, resource closure, font sharing and paired range hashes.
  ULSBS multikey JSON belongs in the external index, not PDF XMP. Use existing
  PDF.js/Poppler tests where applicable.
- Compare wall time and peak memory with matching toolchain, hardware,
  parallelism and cold/warm caches. Keep evidence of material regressions before
  optimizing. A concurrent wall-clock measurement is not isolated CPU cost.
  Use temporary [compiler timing diagnostics](ARCHITECTURE.md#compiler-timing-diagnostics)
  with `--keep-temp` to locate expensive stages; nested stage totals are inclusive.
- Preserve the finite collation policy: add reviewed weights and fixtures for a
  newly supported character rather than falling back to the host locale. All
  declared title/author/tag `.sbx` paths are generated job-local outputs. Keep
  authored fragments outside generated filenames before upgrading; the engine
  may replace or clear them, without a manual-author fallback.
- Preserve Kevin W. Hamlen's copyright and attribution for adapted material.
  The upstream songs v3.1 `README`, `songs.dtx` source and `songidx.lua` grant
  GPL version 2 or later. ULSBS uses the later-version option for its GPL
  3-or-later derivative implementation. Keep the README acknowledgement and
  packaged `LICENSE` and adapted-source notices.

Keep runtime changes and consumer-corpus changes separate in review. Release
validation must not modify the consumer's song sources to make a test pass. The runbook below
describes explicit maintainer actions; validation itself does not authorize a
commit, tag, push or release.

## Source release runbook

The ULSBS Python package and bundled VS Code extension normally use the same
version. GitHub is the only release target; the extension is not published to a
marketplace.

Run these commands from the ULSBS repository root on `main`.

1. Set release variables and start from an up-to-date, clean branch:

   ```sh
   VERSION=0.2.2
   TAG="v$VERSION"
   DATE="$(date +%F)"

   git switch main
   git pull --ff-only
   test -z "$(git status --short)"
   ```

   `v<version>` is the recommended tag format going forward. Existing
   date-based tags are historical.

2. Update the package and extension versions:

   ```sh
   "$EDITOR" pyproject.toml
   npm --prefix vscode-extension/ulsbs-tex-tools version "$VERSION" \
     --no-git-tag-version --allow-same-version
   ```

   Edit `[project].version` in `pyproject.toml`. The npm command updates both
   extension `package.json` and `package-lock.json`. Do not change
   `.vscode/launch.json`; its `version` is the VS Code launch-file schema.

3. Finalize both changelogs:

   ```sh
   "$EDITOR" CHANGELOG.md
   "$EDITOR" vscode-extension/ulsbs-tex-tools/CHANGELOG.md
   ```

   Keep Unreleased notes concise and consumer-oriented: summarize changes since
   the preceding release, including required source/configuration migration.
   Consolidate intermediate fixes into their final behavior rather than listing
   implementation phases or individual commits. Then move the release entries to
   `## [$VERSION] - $DATE`, then leave a new empty `## [Unreleased]` above it.

4. Verify versions and run release checks:

   ```sh
   python3 -c 'import sys,tomllib; assert tomllib.load(open("pyproject.toml", "rb"))["project"]["version"] == sys.argv[1]' "$VERSION"
   node -e 'const p=require("./vscode-extension/ulsbs-tex-tools/package.json"); const l=require("./vscode-extension/ulsbs-tex-tools/package-lock.json"); if (p.version !== process.argv[1] || l.version !== process.argv[1] || l.packages[""].version !== process.argv[1]) process.exit(1)' "$VERSION"
   ./ulsbs-test
   npm --prefix vscode-extension/ulsbs-tex-tools ci
   npm --prefix vscode-extension/ulsbs-tex-tools run compile-web
    npm --prefix vscode-extension/ulsbs-tex-tools run test:grammar
    npm --prefix vscode-extension/ulsbs-tex-tools run test:songbooks
    npm --prefix vscode-extension/ulsbs-tex-tools run test:verse
   npm --prefix vscode-extension/ulsbs-tex-tools run package
   git diff --check
   git status --short
   ```

   Packaging the VSIX is only a validation step. Do not upload it for a source-
   only release.

5. Review and commit the release preparation:

   ```sh
   git diff
   git add pyproject.toml CHANGELOG.md \
     vscode-extension/ulsbs-tex-tools/package.json \
     vscode-extension/ulsbs-tex-tools/package-lock.json \
     vscode-extension/ulsbs-tex-tools/CHANGELOG.md
   git commit -m "Prepare $TAG"
   ```

6. Create and verify an annotated tag, then push the commit and tag:

   ```sh
   git tag -a "$TAG" -m "ULSBS $VERSION"
   git show --stat "$TAG"
   git push origin main
   git push origin "$TAG"
   ```

7. In GitHub, open **Releases > Draft a new release**:

   - choose the existing `$TAG`;
   - use `ULSBS $VERSION` as the title;
   - generate release notes, then edit them to highlight breaking changes and
     required migrations from `CHANGELOG.md`;
   - leave **pre-release** unchecked and mark it as the latest release;
   - attach no VSIX or package artifacts for a source-only release;
   - publish the release.

8. Confirm the release page and source archives, then begin future work under
   the empty `Unreleased` sections.

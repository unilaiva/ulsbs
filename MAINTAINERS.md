# Maintainer Notes

This file documents the release workflow for the repository maintainer. It is
public intentionally and must not contain credentials, tokens, or other secrets.

## Source release runbook

The ULSBS Python package and bundled VS Code extension normally use the same
version. GitHub is the only release target; the extension is not published to a
marketplace.

Run these commands from the ULSBS repository root on `main`.

1. Set release variables and start from an up-to-date, clean branch:

   ```sh
   VERSION=0.2.0
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

   Move the release entries from `Unreleased` to
   `## [$VERSION] - $DATE`, then leave a new empty `## [Unreleased]` above it.

4. Verify versions and run release checks:

   ```sh
   python3 -c 'import sys,tomllib; assert tomllib.load(open("pyproject.toml", "rb"))["project"]["version"] == sys.argv[1]' "$VERSION"
   node -e 'const p=require("./vscode-extension/ulsbs-tex-tools/package.json"); const l=require("./vscode-extension/ulsbs-tex-tools/package-lock.json"); if (p.version !== process.argv[1] || l.version !== process.argv[1] || l.packages[""].version !== process.argv[1]) process.exit(1)' "$VERSION"
   ./ulsbs-test
   npm --prefix vscode-extension/ulsbs-tex-tools ci
   npm --prefix vscode-extension/ulsbs-tex-tools run compile-web
   npm --prefix vscode-extension/ulsbs-tex-tools run test:grammar
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

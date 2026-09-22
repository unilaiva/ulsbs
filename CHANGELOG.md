# Changelog

This changelog follows the spirit of [Keep a Changelog](https://keepachangelog.com/).
Changes accumulate under Unreleased and move to a dated version heading when
released.

## Unreleased

> [!IMPORTANT]
> This release completely replaces the melody-note and beat-mark authoring
> system. Existing song sources must be migrated; the removed `\mn*`, `\ma*`,
> `\bm*`, and `\ac<n>{Chord}` syntaxes are not backward compatible. Review
> changes in version control and run:
>
> ```sh
> ulsbs-migrate-melody-syntax --diff PATH
> ulsbs-migrate-melody-syntax --write PATH
> ```

### Added

- Melody-block syntax and renderer with sequences, two voices, beats, gaps,
  offsets, zero-advance blocks, scoped positioning/styles, replay, and
  visibility controls.
- `ulsbs-migrate-melody-syntax` for checked, file-atomic source migration.

### Removed

- Legacy `\mn*`, `\ma*`, `\bm*`, and `\usealtmnstyle...` authoring macros.
- Legacy `\ac<n>{Chord}` syntax, replaced by `\ac{n}{Chord}`.

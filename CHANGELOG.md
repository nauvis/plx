# Changelog

## [0.2.2] - 2026-03-29

### Changed
- Vendor-check dispatch now includes PR head SHA for cross-repo status reporting

## [0.2.1] - 2026-03-29

### Fixed
- Raise compile error for erroneous `int()` cast on enum literals in Beckhoff export (#1)

## [0.2.0] - 2026-03-29

### Added
- Semantic versioning with single source of truth (`VERSION` file)
- Changelog tracking (`CHANGELOG.md`)
- CI version bump check — PRs must increment the version before merging
- Release workflow — auto-creates git tags and GitHub Releases on merge

### Changed
- NumPy-style docstrings across entire public codebase

### Fixed
- 15 quality review issues: precedence bug, analysis gaps, dead code cleanup

## [0.1.0] - 2026-03-15

- Initial release

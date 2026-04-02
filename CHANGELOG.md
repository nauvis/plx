# Changelog

## [0.2.5] - 2026-04-01

### Added
- Ruff linting and formatting with 15 rule sets, enforced in CI
- `py.typed` marker for PEP 561 typed package compliance
- CI lint job (`ruff check` + `ruff format --check`) on all pushes and PRs

### Changed
- All source and test files formatted with ruff (consistent quotes, trailing commas, import ordering)
- 14 `str, Enum` classes migrated to `StrEnum` (Python 3.11+)
- 5 implicit `Optional` parameters made explicit (`str = None` → `str | None = None`)
- Unused imports and dead assignments removed across src/ and tests/
- `pytest.raises(match=...)` patterns use raw strings for regex clarity
- `pytest.raises(Exception)` narrowed to specific exception types

## [0.2.4] - 2026-04-01

### Fixed
- Simulator: dynamic bit access (`var.[idx]`) now evaluates Expression indices instead of crashing with TypeError
- Simulator: CASE statement now resolves `"EnumName#MEMBER"` string literals to integers for matching
- Simulator: user-defined FUNCTIONs now allocate `output_vars` and `constant_vars` (prevents KeyError)
- Simulator: dotted string `instance_name` paths (e.g. `"parent.child"`) now traverse nested state dicts
- Simulator: FOR loops now have an iteration guard matching WHILE/REPEAT (`MAX_LOOP_ITERATIONS`)
- ST export: abstract POUs no longer emit invalid `END_FUNCTION_BLOCK ABSTRACT` closing tag
- LD export: `NOT(function_call)` no longer silently drops the negation
- Python export: FOR loop variable now escaped with `_safe_name()` for Python keyword collisions
- Python export: `_try_format_fb_init` now bails on unrepresentable nested values instead of embedding `None`
- Framework: `_format_init_param` now raises `DeclarationError` on `None` instead of producing `"None"` string
- Framework: `_infer_type()` now resolves types for INPUT/OUTPUT/INOUT vars (not just STATIC)
- Framework: `PlxProject.compile()` is now idempotent — no longer mutates instance state on repeated calls
- IR model: `SFCBody` now rejects orphan transitions when `steps=[]`
- IR model: `FBInvocation._validate_instance_name` now rejects malformed paths (`.a`, `a.`, `a..b`, bare `^`)
- Analysis: `TempFBInstanceRule` no longer false-positives on structs/enums (only flags FB types)
- Analysis: `RecursiveCallRule` and `UnusedPOURule` now detect calls in methods, properties, and actions
- Analysis: `IgnoredFBOutputRule` now finds FB invocations in SFC actions and POU actions
- Analysis: `CrossTaskWriteRule` no longer false-positives on output vars (they are POU-local)

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

"""Global registry for compiled POU classes and data type classes.

Populated automatically at decoration time (import time) by @fb, @program,
@function, @sfc, @struct, and @enumeration.  Used by transitive dependency
resolution in _project.py to auto-include referenced POUs and types.

Zero framework dependencies (just dicts) — no circular import risk.
"""

from __future__ import annotations

import warnings


_pou_registry: dict[str, type] = {}
_type_registry: dict[str, type] = {}


def register_pou(cls: type) -> None:
    """Register a compiled POU class by its name."""
    existing = _pou_registry.get(cls.__name__)
    if existing is not None and existing is not cls:
        warnings.warn(
            f"POU registry: '{cls.__name__}' already registered "
            f"(replacing {existing.__qualname__} with {cls.__qualname__})",
            stacklevel=2,
        )
    _pou_registry[cls.__name__] = cls


def register_type(cls: type) -> None:
    """Register a compiled data type class by its name."""
    existing = _type_registry.get(cls.__name__)
    if existing is not None and existing is not cls:
        warnings.warn(
            f"Type registry: '{cls.__name__}' already registered "
            f"(replacing {existing.__qualname__} with {cls.__qualname__})",
            stacklevel=2,
        )
    _type_registry[cls.__name__] = cls


def lookup_pou(name: str) -> type | None:
    """Look up a POU class by name. Returns None if not found."""
    return _pou_registry.get(name)


def lookup_type(name: str) -> type | None:
    """Look up a data type class by name. Returns None if not found."""
    return _type_registry.get(name)


def _clear_registries() -> None:
    """Clear both registries. For tests only."""
    _pou_registry.clear()
    _type_registry.clear()


def _snapshot_registries() -> tuple[dict[str, type], dict[str, type]]:
    """Capture a copy of both registries. For tests only."""
    return dict(_pou_registry), dict(_type_registry)


def _restore_registries(snapshot: tuple[dict[str, type], dict[str, type]]) -> None:
    """Restore both registries from a snapshot. For tests only."""
    _pou_registry.clear()
    _pou_registry.update(snapshot[0])
    _type_registry.clear()
    _type_registry.update(snapshot[1])

"""Library type stubs for the plx framework.

Provides base classes for declaring interfaces of external library
types (FBs, structs, enums) — both IEC 61131-3 standard function
blocks and vendor-specific compiled libraries.

These stubs enable:

- **Type resolution**: ``axis: MC_Power`` → ``NamedTypeRef("MC_Power")``
- **Simulation**: auto-generated ``initial_state()`` + overridable ``execute()``
- **Library tracking**: raise passes can determine which libraries to reference

Usage::

    # IEC standard (no vendor)
    class TON(LibraryFB):
        IN: Input[BOOL]
        PT: Input[TIME]
        Q: Output[BOOL]
        ET: Output[TIME]

    # Vendor-specific
    class MC_Power(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
        Enable: Input[BOOL]
        Status: Output[BOOL]

Stub files must NOT use ``from __future__ import annotations`` —
annotations must be live objects for interface parsing.
"""

from __future__ import annotations

import dataclasses
from typing import ClassVar

from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
    TypeRef,
)


# ---------------------------------------------------------------------------
# FBParam — parameter metadata
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class FBParam:
    """A single parameter of a library FB stub."""

    name: str
    direction: str  # "input", "output", "inout", "static"
    type_ref: TypeRef


# ---------------------------------------------------------------------------
# Type default helper (framework-local, no simulator dependency)
# ---------------------------------------------------------------------------

_FLOAT_PRIMITIVES = frozenset({PrimitiveType.REAL, PrimitiveType.LREAL})


def _type_default_simple(type_ref: TypeRef) -> object:
    """Return a simple default value for a type."""
    if isinstance(type_ref, PrimitiveTypeRef):
        if type_ref.type == PrimitiveType.BOOL:
            return False
        if type_ref.type in _FLOAT_PRIMITIVES:
            return 0.0
        return 0
    if isinstance(type_ref, StringTypeRef):
        return ""
    if isinstance(type_ref, NamedTypeRef):
        return {}  # nested named type → empty dict (populated on demand)
    return 0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_LIBRARY_TYPE_REGISTRY: dict[str, type[LibraryType]] = {}


def get_library_type(name: str) -> type[LibraryType] | None:
    """Look up a registered library type by IEC name."""
    return _LIBRARY_TYPE_REGISTRY.get(name)


def get_library_fb(name: str) -> type[LibraryFB] | None:
    """Look up a registered library FB stub by name."""
    cls = _LIBRARY_TYPE_REGISTRY.get(name)
    if cls is not None and issubclass(cls, LibraryFB):
        return cls
    return None


def _clear_library_registry() -> None:
    """Remove all registered library types.  For tests."""
    _LIBRARY_TYPE_REGISTRY.clear()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class LibraryType:
    """Base class for all library type stubs.

    Subclass via ``LibraryFB``, ``LibraryStruct``, or ``LibraryEnum``
    — not directly.
    """

    _abstract: ClassVar[bool] = True  # set on intermediate bases only
    _vendor: ClassVar[str]
    _library: ClassVar[str]
    _type_name: ClassVar[str]

    def __init_subclass__(
        cls,
        vendor: str = "",
        library: str = "",
        **kw: object,
    ) -> None:
        super().__init_subclass__(**kw)
        # Skip intermediate base classes (LibraryFB, LibraryStruct, LibraryEnum)
        # — they set _abstract in their own __dict__
        if "_abstract" in cls.__dict__:
            return
        cls._vendor = vendor
        cls._library = library
        cls._type_name = getattr(cls, "_type_name", None) or cls.__name__
        _LIBRARY_TYPE_REGISTRY[cls._type_name] = cls
        cls._init_interface()

    @classmethod
    def _init_interface(cls) -> None:
        """Override in subclasses for kind-specific initialization."""


# ---------------------------------------------------------------------------
# LibraryFB
# ---------------------------------------------------------------------------

class LibraryFB(LibraryType):
    """Base class for library function block stubs.

    Declares the FB's input/output interface using the same
    ``Input[T]``/``Output[T]``/``InOut[T]`` annotation wrappers
    that ``@fb`` classes use.

    IEC standard FBs need no vendor::

        class TON(LibraryFB):
            IN: Input[BOOL]
            PT: Input[TIME]
            Q: Output[BOOL]
            ET: Output[TIME]

    Vendor-specific FBs declare vendor and library::

        class MC_Power(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
            Enable: Input[BOOL]
            Status: Output[BOOL]

    Override ``execute()`` to provide simulation logic.
    """

    _abstract: ClassVar[bool] = True  # marks LibraryFB itself as non-registrable
    _interface: ClassVar[dict[str, FBParam]]

    @classmethod
    def _init_interface(cls) -> None:
        cls._interface = _parse_fb_interface(cls)

    @classmethod
    def initial_state(cls) -> dict:
        """Auto-generate initial state dict from interface metadata."""
        state: dict[str, object] = {}
        for name, param in cls._interface.items():
            state[name] = _type_default_simple(param.type_ref)
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Override to provide stand-in simulation logic.

        Default: no-op (outputs retain values from previous scan).
        """


# ---------------------------------------------------------------------------
# LibraryStruct
# ---------------------------------------------------------------------------

class LibraryStruct(LibraryType):
    """Base class for library struct stubs.

    Declares fields with plain type annotations (no direction wrappers)::

        class AXIS_REF(LibraryStruct, vendor="beckhoff", library="Tc2_MC2"):
            Status: WORD

    An empty stub is also valid — the simulator creates an empty dict
    and fields are populated on first write.
    """

    _abstract: ClassVar[bool] = True
    _fields: ClassVar[dict[str, TypeRef]]

    @classmethod
    def _init_interface(cls) -> None:
        cls._fields = _parse_struct_fields(cls)

    @classmethod
    def initial_state(cls) -> dict:
        """Auto-generate initial state dict from field metadata."""
        state: dict[str, object] = {}
        for name, type_ref in cls._fields.items():
            state[name] = _type_default_simple(type_ref)
        return state


# ---------------------------------------------------------------------------
# LibraryEnum
# ---------------------------------------------------------------------------

class LibraryEnum(LibraryType):
    """Base class for library enum stubs.

    Declares enum values as integer class attributes::

        class MC_Direction(LibraryEnum, vendor="beckhoff", library="Tc2_MC2"):
            positive = 1
            negative = 2
            current = 3
    """

    _abstract: ClassVar[bool] = True
    _values: ClassVar[dict[str, int]]

    @classmethod
    def _init_interface(cls) -> None:
        cls._values = _parse_enum_values(cls)

    @classmethod
    def default_value(cls) -> int:
        """Return the default enum value (first member, or 0)."""
        if cls._values:
            return next(iter(cls._values.values()))
        return 0


# ---------------------------------------------------------------------------
# Interface parsers
# ---------------------------------------------------------------------------

def _parse_fb_interface(cls: type) -> dict[str, FBParam]:
    """Parse Input[T]/Output[T]/InOut[T] annotations into FBParam metadata."""
    from ._descriptors import _determine_direction, _unwrap_forward_ref
    from ._types import _resolve_type_ref

    result: dict[str, FBParam] = {}
    for name, hint in getattr(cls, "__annotations__", {}).items():
        if name.startswith("_"):
            continue
        direction, inner = _determine_direction(hint)
        inner = _unwrap_forward_ref(inner, cls)
        try:
            type_ref = _resolve_type_ref(inner)
        except TypeError:
            # Unresolvable type (e.g. complex vendor struct not yet imported)
            type_ref = NamedTypeRef(
                name=inner.__name__ if isinstance(inner, type) else str(inner),
            )
        result[name] = FBParam(
            name=name, direction=direction.value, type_ref=type_ref,
        )
    return result


def _parse_struct_fields(cls: type) -> dict[str, TypeRef]:
    """Parse plain type annotations into field type metadata."""
    from ._descriptors import _unwrap_forward_ref
    from ._types import _resolve_type_ref

    result: dict[str, TypeRef] = {}
    for name, hint in getattr(cls, "__annotations__", {}).items():
        if name.startswith("_"):
            continue
        hint = _unwrap_forward_ref(hint, cls)
        try:
            type_ref = _resolve_type_ref(hint)
        except TypeError:
            type_ref = NamedTypeRef(
                name=hint.__name__ if isinstance(hint, type) else str(hint),
            )
        result[name] = type_ref
    return result


def _parse_enum_values(cls: type) -> dict[str, int]:
    """Collect integer class attributes as enum values."""
    result: dict[str, int] = {}
    for name, value in cls.__dict__.items():
        if (
            not name.startswith("_")
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            result[name] = value
    return result

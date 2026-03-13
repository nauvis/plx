"""Type constants and literal helpers for the plx framework.

Provides:
- Primitive type constants (BOOL, INT, REAL, TIME, etc.) for use in
  variable annotations: ``sensor: Input[BOOL]``, ``speed: Output[REAL]``.
- ``timedelta_to_iec()`` / ``timedelta_to_ir()``: convert Python ``timedelta``
  to IEC 61131-3 duration literals (``T#5s``, ``LTIME#100ms``).
"""

from __future__ import annotations

from datetime import timedelta

from plx.model.expressions import LiteralExpr
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
    TypeRef,
)


# ---------------------------------------------------------------------------
# Primitive type constants
# ---------------------------------------------------------------------------
# Re-exported enum members so users write ``sensor: Input[BOOL]`` instead of
# ``sensor: Input[PrimitiveType.BOOL]``.

BOOL = PrimitiveType.BOOL

BYTE = PrimitiveType.BYTE
WORD = PrimitiveType.WORD
DWORD = PrimitiveType.DWORD
LWORD = PrimitiveType.LWORD

SINT = PrimitiveType.SINT
INT = PrimitiveType.INT
DINT = PrimitiveType.DINT
LINT = PrimitiveType.LINT

USINT = PrimitiveType.USINT
UINT = PrimitiveType.UINT
UDINT = PrimitiveType.UDINT
ULINT = PrimitiveType.ULINT

REAL = PrimitiveType.REAL
LREAL = PrimitiveType.LREAL

TIME = PrimitiveType.TIME
LTIME = PrimitiveType.LTIME

DATE = PrimitiveType.DATE
LDATE = PrimitiveType.LDATE
TOD = PrimitiveType.TOD
LTOD = PrimitiveType.LTOD
DT = PrimitiveType.DT
LDT = PrimitiveType.LDT

CHAR = PrimitiveType.CHAR
WCHAR = PrimitiveType.WCHAR


# ---------------------------------------------------------------------------
# timedelta → IEC 61131-3 conversion
# ---------------------------------------------------------------------------

def timedelta_to_iec(td: timedelta, *, ltime: bool = False) -> str:
    """Convert a ``timedelta`` to an IEC 61131-3 time literal string.

    Examples::

        timedelta_to_iec(timedelta(seconds=5))         # "T#5s"
        timedelta_to_iec(timedelta(milliseconds=500))   # "T#500ms"
        timedelta_to_iec(timedelta(hours=1, minutes=30)) # "T#1h30m"
        timedelta_to_iec(timedelta(milliseconds=100), ltime=True)  # "LTIME#100ms"
    """
    total_us = int(td.total_seconds() * 1_000_000)
    prefix = "LTIME#" if ltime else "T#"

    if total_us == 0:
        return f"{prefix}0s"

    negative = total_us < 0
    remaining = abs(total_us)
    parts: list[str] = []

    for divisor, suffix in (
        (3_600_000_000, "h"),
        (60_000_000, "m"),
        (1_000_000, "s"),
        (1_000, "ms"),
        (1, "us"),
    ):
        value, remaining = divmod(remaining, divisor)
        if value:
            parts.append(f"{value}{suffix}")

    sign = "-" if negative else ""
    return f"{prefix}{sign}{''.join(parts)}"


def timedelta_to_ir(td: timedelta, *, ltime: bool = False) -> LiteralExpr:
    """Convert a ``timedelta`` to an IR ``LiteralExpr`` node."""
    prim = PrimitiveType.LTIME if ltime else PrimitiveType.TIME
    return LiteralExpr(
        value=timedelta_to_iec(td, ltime=ltime),
        data_type=PrimitiveTypeRef(type=prim),
    )


def _resolve_type_ref(type_arg: PrimitiveType | TypeRef | type | str) -> TypeRef:
    """Normalize a user-provided type argument into a TypeRef.

    - PLC type classes (dint, real, sint, etc.) → PrimitiveTypeRef
    - Python builtins (bool, int, float, str) → default PLC types
    - PrimitiveType enum → PrimitiveTypeRef
    - Any TypeRef subclass → pass through
    - @struct / @enumeration decorated class → NamedTypeRef(name=cls.__name__)
    - @fb / @program decorated class → NamedTypeRef(name=cls.__name__)
    - str → NamedTypeRef(name=...)
    """
    # PLC type classes (dint, real, sint, etc.) — check before builtins
    from ._plc_types import _PlcInt, _PlcFloat
    if isinstance(type_arg, type) and issubclass(type_arg, (_PlcInt, _PlcFloat)):
        return PrimitiveTypeRef(type=PrimitiveType(type_arg._iec_name))
    # Python builtin type aliases (check bool before int — bool is subclass of int)
    if type_arg is bool:
        return PrimitiveTypeRef(type=PrimitiveType.BOOL)
    if type_arg is int:
        return PrimitiveTypeRef(type=PrimitiveType.DINT)
    if type_arg is float:
        return PrimitiveTypeRef(type=PrimitiveType.REAL)
    if type_arg is str:
        return StringTypeRef(wide=False, max_length=255)
    if isinstance(type_arg, PrimitiveType):
        return PrimitiveTypeRef(type=type_arg)
    if isinstance(type_arg, (
        PrimitiveTypeRef, StringTypeRef, NamedTypeRef,
        ArrayTypeRef, PointerTypeRef, ReferenceTypeRef,
    )):
        return type_arg
    # IntEnum subclasses → auto-compile and return NamedTypeRef
    # Late imports: _types.py and _data_types.py are mutually recursive.
    # _resolve_type_ref() may trigger _ensure_enum_compiled(), which in
    # turn calls _resolve_type_ref() for nested member types.  Late
    # imports here (rather than top-level) are the correct pattern to
    # break the import cycle while preserving the auto-compilation
    # convenience for IntEnum subclasses.
    from enum import IntEnum
    if isinstance(type_arg, type) and issubclass(type_arg, IntEnum) and type_arg is not IntEnum:
        from ._data_types import _ensure_enum_compiled
        _ensure_enum_compiled(type_arg)
        return NamedTypeRef(name=type_arg.__name__)
    # @struct / @enumeration decorated classes have _compiled_type
    from ._protocols import CompiledDataType, CompiledPOU
    if isinstance(type_arg, CompiledDataType):
        return NamedTypeRef(name=type_arg.__name__)
    # @fb / @program decorated classes have _compiled_pou
    if isinstance(type_arg, CompiledPOU):
        return NamedTypeRef(name=type_arg.__name__)
    if isinstance(type_arg, str):
        return NamedTypeRef(name=type_arg)
    raise TypeError(
        f"Expected a type (PrimitiveType, TypeRef, or str), got {type(type_arg).__name__}"
    )



# ---------------------------------------------------------------------------
# Type constructors
# ---------------------------------------------------------------------------

def ARRAY(
    element_type: PrimitiveType | TypeRef | type | str,
    *dims: int | tuple[int, int],
) -> ArrayTypeRef:
    """Create an ARRAY type reference.

    Each dimension argument can be:
    - ``int``: shorthand for ``0..n-1``
    - ``tuple[int, int]``: explicit ``(lower, upper)`` bounds

    Examples::

        ARRAY(INT, 10)              # ARRAY[0..9] OF INT
        ARRAY(REAL, (1, 10))        # ARRAY[1..10] OF REAL
        ARRAY(BOOL, 3, 4)           # ARRAY[0..2, 0..3] OF BOOL
    """
    if not dims:
        raise ValueError("ARRAY requires at least one dimension")
    dimensions: list[DimensionRange] = []
    for d in dims:
        if isinstance(d, int):
            if d < 1:
                raise ValueError(f"Array size must be >= 1, got {d}")
            dimensions.append(DimensionRange(lower=0, upper=d - 1))
        elif isinstance(d, tuple) and len(d) == 2:
            dimensions.append(DimensionRange(lower=d[0], upper=d[1]))
        else:
            raise TypeError(
                f"Dimension must be int or (lower, upper) tuple, got {type(d).__name__}"
            )
    return ArrayTypeRef(
        element_type=_resolve_type_ref(element_type),
        dimensions=dimensions,
    )


def STRING(max_length: int = 255) -> StringTypeRef:
    """Create a STRING type reference with optional max length.

    Example::

        STRING()       # STRING[255]
        STRING(80)     # STRING[80]
    """
    return StringTypeRef(wide=False, max_length=max_length)


def WSTRING(max_length: int = 255) -> StringTypeRef:
    """Create a WSTRING type reference with optional max length."""
    return StringTypeRef(wide=True, max_length=max_length)


def POINTER_TO(target: PrimitiveType | TypeRef | type | str) -> PointerTypeRef:
    """Create a POINTER TO type reference."""
    return PointerTypeRef(target_type=_resolve_type_ref(target))


def REFERENCE_TO(target: PrimitiveType | TypeRef | type | str) -> ReferenceTypeRef:
    """Create a REFERENCE TO type reference."""
    return ReferenceTypeRef(target_type=_resolve_type_ref(target))


# ---------------------------------------------------------------------------
# Lowercase aliases — Pythonic names for type constructors
# ---------------------------------------------------------------------------

array = ARRAY
string = STRING
wstring = WSTRING
pointer_to = POINTER_TO
reference_to = REFERENCE_TO


# ---------------------------------------------------------------------------
# System flag sentinels
# ---------------------------------------------------------------------------

def first_scan() -> bool:
    """TRUE on the first scan cycle after entering Run mode.

    Recognised by the AST compiler — do not call directly.
    """
    raise RuntimeError("first_scan() is a compile-time sentinel — do not call directly")

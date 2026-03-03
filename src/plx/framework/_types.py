"""Type constants and literal helpers for the plx framework.

Provides:
- Primitive type constants (BOOL, INT, REAL, TIME, etc.) for use in
  variable descriptors: ``input_var(BOOL)``, ``output_var(REAL)``.
- TIME/LTIME literal constructors: ``T(5)`` → ``T#5s``,
  ``LT(ms=100)`` → ``LTIME#100ms``.
"""

from __future__ import annotations

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
# Re-exported enum members so users write ``input_var(BOOL)`` instead of
# ``input_var(PrimitiveType.BOOL)``.

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
# Duration literals
# ---------------------------------------------------------------------------

class _DurationLiteral:
    """Base class for IEC 61131-3 duration literals.

    Subclasses override class variables to specialize for TIME vs LTIME.
    """

    __slots__ = ("_total_sub",)

    # -- Subclass overrides --------------------------------------------------
    _prefix: str  # "T#" or "LTIME#"
    _primitive: PrimitiveType  # TIME or LTIME
    _unit_table: tuple[tuple[int, str], ...]  # decomposition table
    _class_name: str  # for __hash__ and __eq__ identity

    def __init__(self, total_sub: int) -> None:
        self._total_sub = total_sub

    # -- Conversion ----------------------------------------------------------

    def to_iec(self) -> str:
        """IEC 61131-3 duration literal string."""
        if self._total_sub == 0:
            return f"{self._prefix}0s"

        negative = self._total_sub < 0
        remaining = abs(self._total_sub)
        parts: list[str] = []

        for divisor, suffix in self._unit_table:
            value, remaining = divmod(remaining, divisor)
            if value:
                parts.append(f"{value}{suffix}")

        sign = "-" if negative else ""
        return f"{self._prefix}{sign}{''.join(parts)}"

    def to_ir(self) -> LiteralExpr:
        """Convert to an IR ``LiteralExpr`` node."""
        return LiteralExpr(
            value=self.to_iec(),
            data_type=PrimitiveTypeRef(type=self._primitive),
        )

    # -- Dunder --------------------------------------------------------------

    def __repr__(self) -> str:
        return self.to_iec()

    def __str__(self) -> str:
        return self.to_iec()

    def __eq__(self, other: object) -> bool:
        if type(other) is type(self):
            return self._total_sub == other._total_sub
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._class_name, self._total_sub))


class TimeLiteral(_DurationLiteral):
    """IEC 61131-3 TIME literal value.

    Represents a duration that can be used as:
    - An initial value on variable descriptors (descriptor calls ``to_iec()``)
    - A value in ``logic()`` that the AST compiler recognises and emits
      as a ``LiteralExpr``

    Internal resolution: microseconds (TIME is typically millisecond-resolution
    on PLCs, but storing in microseconds avoids rounding during construction).
    """

    __slots__ = ()

    _prefix = "T#"
    _primitive = PrimitiveType.TIME
    _unit_table = (
        (3_600_000_000, "h"),
        (60_000_000, "m"),
        (1_000_000, "s"),
        (1_000, "ms"),
        (1, "us"),
    )
    _class_name = "TimeLiteral"

    def __init__(
        self,
        *,
        hours: int | float = 0,
        minutes: int | float = 0,
        seconds: int | float = 0,
        ms: int | float = 0,
        us: int | float = 0,
    ) -> None:
        total = round(
            hours * 3_600_000_000
            + minutes * 60_000_000
            + seconds * 1_000_000
            + ms * 1_000
            + us
        )
        super().__init__(total)

    @property
    def total_us(self) -> int:
        """Total duration in microseconds."""
        return self._total_sub

    @property
    def total_ms(self) -> float:
        """Total duration in milliseconds."""
        return self._total_sub / 1_000

    @property
    def total_seconds(self) -> float:
        """Total duration in seconds."""
        return self._total_sub / 1_000_000


class LTimeLiteral(_DurationLiteral):
    """IEC 61131-3 LTIME literal value (nanosecond resolution).

    Same interface as ``TimeLiteral`` but with ``LTIME#`` prefix and
    nanosecond support.
    """

    __slots__ = ()

    _prefix = "LTIME#"
    _primitive = PrimitiveType.LTIME
    _unit_table = (
        (3_600_000_000_000, "h"),
        (60_000_000_000, "m"),
        (1_000_000_000, "s"),
        (1_000_000, "ms"),
        (1_000, "us"),
        (1, "ns"),
    )
    _class_name = "LTimeLiteral"

    def __init__(
        self,
        *,
        hours: int | float = 0,
        minutes: int | float = 0,
        seconds: int | float = 0,
        ms: int | float = 0,
        us: int | float = 0,
        ns: int | float = 0,
    ) -> None:
        total = round(
            hours * 3_600_000_000_000
            + minutes * 60_000_000_000
            + seconds * 1_000_000_000
            + ms * 1_000_000
            + us * 1_000
            + ns
        )
        super().__init__(total)

    @property
    def total_ns(self) -> int:
        """Total duration in nanoseconds."""
        return self._total_sub

    @property
    def total_us(self) -> float:
        """Total duration in microseconds."""
        return self._total_sub / 1_000

    @property
    def total_ms(self) -> float:
        """Total duration in milliseconds."""
        return self._total_sub / 1_000_000

    @property
    def total_seconds(self) -> float:
        """Total duration in seconds."""
        return self._total_sub / 1_000_000_000


# ---------------------------------------------------------------------------
# Public constructors
# ---------------------------------------------------------------------------

def T(
    seconds: int | float = 0,
    *,
    hours: int | float = 0,
    minutes: int | float = 0,
    ms: int | float = 0,
    us: int | float = 0,
) -> TimeLiteral:
    """Create a TIME literal.

    The first positional argument is seconds (the most common unit).

    Examples::

        T(5)                        # T#5s
        T(ms=500)                   # T#500ms
        T(minutes=1, seconds=30)    # T#1m30s
        T(hours=2)                  # T#2h
        T(0.5)                      # T#500ms  (fractional seconds)
    """
    return TimeLiteral(
        hours=hours, minutes=minutes, seconds=seconds, ms=ms, us=us,
    )


def _resolve_type_ref(type_arg: PrimitiveType | TypeRef | type | str) -> TypeRef:
    """Normalize a user-provided type argument into a TypeRef.

    - Python builtins (bool, int, float, str) → default PLC types
    - PrimitiveType enum → PrimitiveTypeRef
    - Any TypeRef subclass → pass through
    - @struct / @enumeration decorated class → NamedTypeRef(name=cls.__name__)
    - @fb / @program decorated class → NamedTypeRef(name=cls.__name__)
    - str → NamedTypeRef(name=...)
    """
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
    from enum import IntEnum
    if isinstance(type_arg, type) and issubclass(type_arg, IntEnum) and type_arg is not IntEnum:
        from ._data_types import _ensure_enum_compiled
        _ensure_enum_compiled(type_arg)
        return NamedTypeRef(name=type_arg.__name__)
    # dataclass → auto-compile and return NamedTypeRef
    import dataclasses
    if isinstance(type_arg, type) and dataclasses.is_dataclass(type_arg):
        from ._data_types import _ensure_struct_compiled
        _ensure_struct_compiled(type_arg)
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


def LT(
    seconds: int | float = 0,
    *,
    hours: int | float = 0,
    minutes: int | float = 0,
    ms: int | float = 0,
    us: int | float = 0,
    ns: int | float = 0,
) -> LTimeLiteral:
    """Create an LTIME literal (nanosecond resolution).

    Examples::

        LT(5)                       # LTIME#5s
        LT(us=100, ns=500)          # LTIME#100us500ns
    """
    return LTimeLiteral(
        hours=hours, minutes=minutes, seconds=seconds, ms=ms, us=us, ns=ns,
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
# System flag sentinels
# ---------------------------------------------------------------------------

def first_scan() -> bool:
    """TRUE on the first scan cycle after entering Run mode.

    Recognised by the AST compiler — do not call directly.
    """
    raise RuntimeError("first_scan() is a compile-time sentinel — do not call directly")

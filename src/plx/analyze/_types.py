"""Type environment for static analysis expression type resolution."""

from __future__ import annotations

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    Expression,
    LiteralExpr,
    TypeConversionExpr,
    UnaryExpr,
    VariableRef,
)
from plx.model.pou import POUInterface
from plx.model.types import (
    ArrayTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    TypeRef,
)

_COMPARISON_OPS = frozenset(
    {
        BinaryOp.EQ,
        BinaryOp.NE,
        BinaryOp.GT,
        BinaryOp.GE,
        BinaryOp.LT,
        BinaryOp.LE,
    }
)

_LOGICAL_OPS = frozenset(
    {
        BinaryOp.AND,
        BinaryOp.OR,
        BinaryOp.AND_THEN,
        BinaryOp.OR_ELSE,
    }
)

_BOOL_TYPE = PrimitiveTypeRef(type=PrimitiveType.BOOL)


class TypeEnvironment:
    """Maps variable names to their TypeRef for type-aware analysis.

    Built from a POUInterface. Provides ``resolve_expr_type`` for simple
    expression type inference.  Returns None for ambiguous or unsupported cases.
    """

    def __init__(self, interface: POUInterface) -> None:
        self._var_types: dict[str, TypeRef] = {}
        for var_list in (
            interface.input_vars,
            interface.output_vars,
            interface.inout_vars,
            interface.static_vars,
            interface.temp_vars,
            interface.constant_vars,
            interface.external_vars,
        ):
            for var in var_list:
                self._var_types[var.name] = var.data_type

    def lookup(self, name: str) -> TypeRef | None:
        """Look up a variable's declared type by name."""
        return self._var_types.get(name)

    def resolve_expr_type(self, expr: Expression) -> TypeRef | None:
        """Infer the type of an expression. Returns None for ambiguous cases."""
        if isinstance(expr, VariableRef):
            return self.lookup(expr.name)

        if isinstance(expr, LiteralExpr):
            if expr.data_type is not None:
                return expr.data_type
            return _infer_literal_type(expr.value)

        if isinstance(expr, TypeConversionExpr):
            return expr.target_type

        if isinstance(expr, UnaryExpr):
            return self.resolve_expr_type(expr.operand)

        if isinstance(expr, BinaryExpr):
            if expr.op in _COMPARISON_OPS or expr.op in _LOGICAL_OPS:
                return _BOOL_TYPE
            left_type = self.resolve_expr_type(expr.left)
            right_type = self.resolve_expr_type(expr.right)
            if left_type is not None and left_type == right_type:
                return left_type
            return None

        if isinstance(expr, ArrayAccessExpr):
            array_type = self.resolve_expr_type(expr.array)
            if isinstance(array_type, ArrayTypeRef):
                return array_type.element_type
            return None

        # MemberAccessExpr, FunctionCallExpr, DerefExpr, BitAccessExpr,
        # SubstringExpr, SystemFlagExpr — would require struct/FB definitions
        return None


def _infer_literal_type(value: str) -> TypeRef | None:
    """Infer type from literal text representation.

    Prefix checks are ordered longest-first to avoid false matches
    (e.g. ``TOD#`` must not match ``T#``, ``LTIME#`` must not match ``TIME#``).
    """
    upper = value.upper()
    if upper in ("TRUE", "FALSE"):
        return _BOOL_TYPE
    # Time/date literals — long prefixes before short
    for prefix, ptype in (
        ("LTIME#", PrimitiveType.LTIME),
        ("TIME_OF_DAY#", PrimitiveType.TOD),
        ("TOD#", PrimitiveType.TOD),
        ("TIME#", PrimitiveType.TIME),
        ("T#", PrimitiveType.TIME),
        ("DATE_AND_TIME#", PrimitiveType.DT),
        ("LDT#", PrimitiveType.LDT),
        ("DT#", PrimitiveType.DT),
        ("LDATE#", PrimitiveType.LDATE),
        ("DATE#", PrimitiveType.DATE),
        ("D#", PrimitiveType.DATE),
        ("LTOD#", PrimitiveType.LTOD),
    ):
        if upper.startswith(prefix):
            return PrimitiveTypeRef(type=ptype)
    # Typed numeric literals
    for prefix, ptype in (
        ("LREAL#", PrimitiveType.LREAL),
        ("REAL#", PrimitiveType.REAL),
        ("LINT#", PrimitiveType.LINT),
        ("DINT#", PrimitiveType.DINT),
        ("SINT#", PrimitiveType.SINT),
        ("INT#", PrimitiveType.INT),
        ("ULINT#", PrimitiveType.ULINT),
        ("UDINT#", PrimitiveType.UDINT),
        ("USINT#", PrimitiveType.USINT),
        ("UINT#", PrimitiveType.UINT),
        ("BYTE#", PrimitiveType.BYTE),
        ("WORD#", PrimitiveType.WORD),
        ("DWORD#", PrimitiveType.DWORD),
        ("LWORD#", PrimitiveType.LWORD),
    ):
        if upper.startswith(prefix):
            return PrimitiveTypeRef(type=ptype)
    # Plain numeric — conservatively return None
    return None


# ---------------------------------------------------------------------------
# Type width / range utilities for narrowing & range checks
# ---------------------------------------------------------------------------

# Numeric type bit widths (used for narrowing detection)
_NUMERIC_WIDTH: dict[PrimitiveType, int] = {
    PrimitiveType.SINT: 8,
    PrimitiveType.INT: 16,
    PrimitiveType.DINT: 32,
    PrimitiveType.LINT: 64,
    PrimitiveType.USINT: 8,
    PrimitiveType.UINT: 16,
    PrimitiveType.UDINT: 32,
    PrimitiveType.ULINT: 64,
    PrimitiveType.BYTE: 8,
    PrimitiveType.WORD: 16,
    PrimitiveType.DWORD: 32,
    PrimitiveType.LWORD: 64,
    PrimitiveType.REAL: 32,
    PrimitiveType.LREAL: 64,
}

_SIGNED_INTEGERS = frozenset(
    {
        PrimitiveType.SINT,
        PrimitiveType.INT,
        PrimitiveType.DINT,
        PrimitiveType.LINT,
    }
)

_UNSIGNED_INTEGERS = frozenset(
    {
        PrimitiveType.USINT,
        PrimitiveType.UINT,
        PrimitiveType.UDINT,
        PrimitiveType.ULINT,
        PrimitiveType.BYTE,
        PrimitiveType.WORD,
        PrimitiveType.DWORD,
        PrimitiveType.LWORD,
    }
)

_FLOATS = frozenset({PrimitiveType.REAL, PrimitiveType.LREAL})

# Valid integer ranges for constant-out-of-range checks
_INTEGER_RANGE: dict[PrimitiveType, tuple[int, int]] = {
    PrimitiveType.SINT: (-128, 127),
    PrimitiveType.INT: (-32_768, 32_767),
    PrimitiveType.DINT: (-2_147_483_648, 2_147_483_647),
    PrimitiveType.LINT: (-9_223_372_036_854_775_808, 9_223_372_036_854_775_807),
    PrimitiveType.USINT: (0, 255),
    PrimitiveType.UINT: (0, 65_535),
    PrimitiveType.UDINT: (0, 4_294_967_295),
    PrimitiveType.ULINT: (0, 18_446_744_073_709_551_615),
    PrimitiveType.BYTE: (0, 255),
    PrimitiveType.WORD: (0, 65_535),
    PrimitiveType.DWORD: (0, 4_294_967_295),
    PrimitiveType.LWORD: (0, 18_446_744_073_709_551_615),
}


def is_narrowing(source: PrimitiveType, target: PrimitiveType) -> bool:
    """Return True if assigning *source* to *target* loses information."""
    s_width = _NUMERIC_WIDTH.get(source)
    t_width = _NUMERIC_WIDTH.get(target)
    if s_width is None or t_width is None:
        return False

    # Float → integer is always narrowing
    if source in _FLOATS and target not in _FLOATS:
        return True
    # Integer → float can lose precision for large integers
    if source not in _FLOATS and target in _FLOATS:
        if s_width > t_width:
            return True
    # Same family: wider → narrower
    if s_width > t_width:
        return True
    # Signed → unsigned of same width (loses negative range)
    return source in _SIGNED_INTEGERS and target in _UNSIGNED_INTEGERS and s_width == t_width


def parse_integer_literal(value: str) -> int | None:
    """Parse an IEC literal string to an integer, or None."""
    s = value.strip()
    # Strip type prefix: DINT#42 → 42
    if "#" in s:
        parts = s.split("#", 1)
        # Could be 16#FF (hex) or DINT#42 (typed)
        prefix = parts[0].upper()
        body = parts[1]
        if prefix in ("2", "8", "16"):
            base = int(prefix)
            body = body.replace("_", "")
            try:
                return int(body, base)
            except ValueError:
                return None
        # Typed prefix: DINT#-42
        s = body
    s = s.replace("_", "")
    try:
        return int(s)
    except ValueError:
        return None

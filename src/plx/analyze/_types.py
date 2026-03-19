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


_COMPARISON_OPS = frozenset({
    BinaryOp.EQ, BinaryOp.NE,
    BinaryOp.GT, BinaryOp.GE,
    BinaryOp.LT, BinaryOp.LE,
})

_LOGICAL_OPS = frozenset({
    BinaryOp.AND, BinaryOp.OR,
    BinaryOp.AND_THEN, BinaryOp.OR_ELSE,
})

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

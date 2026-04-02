"""Expression writer mixin for the ST exporter."""

from __future__ import annotations

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)

# ---------------------------------------------------------------------------
# Operator maps
# ---------------------------------------------------------------------------

_BINOP_SYMBOL: dict[BinaryOp, str] = {
    BinaryOp.ADD: "+",
    BinaryOp.SUB: "-",
    BinaryOp.MUL: "*",
    BinaryOp.DIV: "/",
    BinaryOp.MOD: "MOD",
    BinaryOp.AND: "AND",
    BinaryOp.OR: "OR",
    BinaryOp.XOR: "XOR",
    BinaryOp.BAND: "AND",
    BinaryOp.BOR: "OR",
    BinaryOp.EQ: "=",
    BinaryOp.NE: "<>",
    BinaryOp.GT: ">",
    BinaryOp.GE: ">=",
    BinaryOp.LT: "<",
    BinaryOp.LE: "<=",
    BinaryOp.EXPT: "**",
    BinaryOp.AND_THEN: "AND_THEN",
    BinaryOp.OR_ELSE: "OR_ELSE",
}

# IEC 61131-3 precedence (higher = binds tighter)
_BINOP_PRECEDENCE: dict[BinaryOp, int] = {
    BinaryOp.OR_ELSE: 1,
    BinaryOp.AND_THEN: 2,
    BinaryOp.OR: 3,
    BinaryOp.BOR: 3,
    BinaryOp.XOR: 4,
    BinaryOp.AND: 5,
    BinaryOp.BAND: 5,
    BinaryOp.EQ: 6,
    BinaryOp.NE: 6,
    BinaryOp.LT: 7,
    BinaryOp.GT: 7,
    BinaryOp.LE: 7,
    BinaryOp.GE: 7,
    BinaryOp.ADD: 8,
    BinaryOp.SUB: 8,
    BinaryOp.MUL: 9,
    BinaryOp.DIV: 9,
    BinaryOp.MOD: 9,
    BinaryOp.EXPT: 10,
    # Shifts emitted as function calls, not infix
    BinaryOp.SHL: 0,
    BinaryOp.SHR: 0,
    BinaryOp.ROL: 0,
    BinaryOp.ROR: 0,
}

# Shift/rotate ops are emitted as SHL(IN, N) function calls
_SHIFT_OPS = {BinaryOp.SHL, BinaryOp.SHR, BinaryOp.ROL, BinaryOp.ROR}


class _ExpressionWriterMixin:
    """Mixin providing expression-writing methods for STWriter."""

    def _expr(self, expr: Expression, parent_prec: int = 0) -> str:
        kind = expr.kind
        handler = _EXPR_WRITERS.get(kind)
        if handler is not None:
            return handler(self, expr, parent_prec)
        return f"/* unsupported: {kind} */"

    def _expr_literal(self, expr: LiteralExpr, _prec: int) -> str:
        return expr.value

    def _expr_variable_ref(self, expr: VariableRef, _prec: int) -> str:
        return expr.name

    def _expr_binary(self, expr: BinaryExpr, parent_prec: int) -> str:
        # Shift/rotate -> function call syntax
        if expr.op in _SHIFT_OPS:
            return f"{expr.op.value}({self._expr(expr.left)}, {self._expr(expr.right)})"

        my_prec = _BINOP_PRECEDENCE.get(expr.op, 0)
        symbol = _BINOP_SYMBOL.get(expr.op, expr.op.value)
        left = self._expr(expr.left, my_prec)
        right = self._expr(expr.right, my_prec + 1)
        result = f"{left} {symbol} {right}"
        if my_prec < parent_prec:
            return f"({result})"
        return result

    def _expr_unary(self, expr: UnaryExpr, _prec: int) -> str:
        operand = self._expr(expr.operand, 10)  # high precedence for unary
        if expr.op == UnaryOp.NEG:
            return f"-{operand}"
        if expr.op == UnaryOp.NOT:
            return f"NOT {operand}"
        if expr.op == UnaryOp.BNOT:
            return f"NOT {operand}"
        return f"{expr.op.value}({operand})"

    def _expr_function_call(self, expr: FunctionCallExpr, _prec: int) -> str:
        args = ", ".join(self._call_arg(a) for a in expr.args)
        return f"{expr.function_name}({args})"

    def _expr_array_access(self, expr: ArrayAccessExpr, _prec: int) -> str:
        indices = ", ".join(self._expr(i) for i in expr.indices)
        return f"{self._expr(expr.array, 10)}[{indices}]"

    def _expr_member_access(self, expr: MemberAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.struct, 10)}.{expr.member}"

    def _expr_deref(self, expr: DerefExpr, _prec: int) -> str:
        return f"{self._expr(expr.pointer, 10)}^"

    def _expr_bit_access(self, expr: BitAccessExpr, _prec: int) -> str:
        target = self._expr(expr.target, 10)
        if isinstance(expr.bit_index, int):
            return f"{target}.{expr.bit_index}"
        # Dynamic bit access: target.[expr]
        return f"{target}.[{self._expr(expr.bit_index)}]"

    def _expr_type_conversion(self, expr: TypeConversionExpr, _prec: int) -> str:
        target = self._type_ref(expr.target_type)
        if expr.source_type is not None:
            source = self._type_ref(expr.source_type)
            return f"{source}_TO_{target}({self._expr(expr.source)})"
        return f"{target}({self._expr(expr.source)})"

    def _expr_substring(self, expr: SubstringExpr, _prec: int) -> str:
        s = self._expr(expr.string, 10)
        if expr.single_char:
            # s[i] -> MID(s, 1, i + 1)
            pos = f"{self._expr(expr.start)} + 1"
            return f"MID({s}, 1, {pos})"
        if expr.start is not None and expr.end is not None:
            # s[i:j] -> MID(s, j - i, i + 1)
            start = self._expr(expr.start)
            end = self._expr(expr.end)
            return f"MID({s}, {end} - {start}, {start} + 1)"
        if expr.end is not None:
            # s[:n] -> LEFT(s, n)
            return f"LEFT({s}, {self._expr(expr.end)})"
        if expr.start is not None:
            # s[n:] -> RIGHT(s, LEN(s) - n)
            start = self._expr(expr.start)
            return f"RIGHT({s}, LEN({s}) - {start})"
        # s[:] -- identity (shouldn't reach here, compiler optimizes away)
        return s

    def _expr_system_flag(self, expr: SystemFlagExpr, _prec: int) -> str:
        if expr.flag == SystemFlag.FIRST_SCAN:
            return "FirstScan"
        return f"/* unknown flag: {expr.flag} */"

    def _call_arg(self, arg) -> str:
        if arg.name is not None:
            return f"{arg.name} := {self._expr(arg.value)}"
        return self._expr(arg.value)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_EXPR_WRITERS = {
    "literal": _ExpressionWriterMixin._expr_literal,
    "variable_ref": _ExpressionWriterMixin._expr_variable_ref,
    "binary": _ExpressionWriterMixin._expr_binary,
    "unary": _ExpressionWriterMixin._expr_unary,
    "function_call": _ExpressionWriterMixin._expr_function_call,
    "array_access": _ExpressionWriterMixin._expr_array_access,
    "member_access": _ExpressionWriterMixin._expr_member_access,
    "deref": _ExpressionWriterMixin._expr_deref,
    "bit_access": _ExpressionWriterMixin._expr_bit_access,
    "type_conversion": _ExpressionWriterMixin._expr_type_conversion,
    "substring": _ExpressionWriterMixin._expr_substring,
    "system_flag": _ExpressionWriterMixin._expr_system_flag,
}

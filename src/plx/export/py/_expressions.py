"""Expression writer mixin for the Python exporter."""

from __future__ import annotations

import re

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
from plx.model.types import StringTypeRef

from ._helpers import (
    _BINOP_PRECEDENCE,
    _BINOP_PYTHON,
    _FUNC_CALL_OPS,
    _FUNC_REMAP,
    _fix_embedded_iec,
    _iec_string_to_python,
    _parse_iec_time,
    _safe_name,
    _sanitize_identifier,
)


class _ExpressionWriterMixin:
    """Mixin providing expression-writing methods for PyWriter."""

    def _expr(self, expr: Expression, parent_prec: int = 0) -> str:
        handler = _EXPR_WRITERS.get(expr.kind)
        if handler is not None:
            return handler(self, expr, parent_prec)
        return f"# unsupported: {expr.kind}"

    def _expr_literal(self, expr: LiteralExpr, _prec: int) -> str:
        v = expr.value
        if v == "TRUE":
            return "True"
        if v == "FALSE":
            return "False"
        if v == "":
            return "''"  # empty string placeholder (e.g. GSV empty instance arg)

        # IEC time literal
        time_repr = _parse_iec_time(v)
        if time_repr is not None:
            return time_repr

        # IEC radix literals -> Python format
        # 16#FF -> 0xFF, 8#77 -> 0o77, 2#1010 -> 0b1010
        radix_match = re.match(r"^(\d+)#([0-9A-Fa-f_]+)$", v)
        if radix_match:
            base = int(radix_match.group(1))
            digits = radix_match.group(2)
            if base == 16:
                return f"0x{digits}"
            if base == 8:
                return f"0o{digits}"
            if base == 2:
                return f"0b{digits}"
            # Other bases (10#, etc.) -- convert to decimal
            try:
                return str(int(digits.replace("_", ""), base))
            except ValueError:
                pass

        # Date/time typed literal: DATE#2024-01-15 -> "DATE#2024-01-15"
        _DATE_TIME_PREFIXES = {
            "DATE", "LDATE", "TOD", "LTOD", "DT", "LDT",
            "TIME_OF_DAY", "LTIME_OF_DAY", "DATE_AND_TIME", "LDATE_AND_TIME",
            "D", "LD",
        }
        if "#" in v:
            prefix = v.split("#", 1)[0].upper()
            if prefix in _DATE_TIME_PREFIXES:
                return repr(v)

        # Typed numeric literal: BYTE#255 -> 255, REAL#3.14 -> 3.14
        _NUMERIC_TYPE_PREFIXES = {
            "BYTE", "WORD", "DWORD", "LWORD",
            "SINT", "INT", "DINT", "LINT",
            "USINT", "UINT", "UDINT", "ULINT",
            "REAL", "LREAL", "BOOL",
        }
        if "#" in v:
            prefix, _, suffix = v.partition("#")
            if prefix.upper() in _NUMERIC_TYPE_PREFIXES and suffix:
                if suffix.startswith("16#"):
                    return "0x" + suffix[3:]
                if suffix.startswith("8#"):
                    return "0o" + suffix[2:]
                if suffix.startswith("2#"):
                    return "0b" + suffix[2:]
                try:
                    int(suffix)
                    return suffix
                except ValueError:
                    pass
                try:
                    float(suffix)
                    return suffix
                except ValueError:
                    pass
                return repr(v)

        # Enum literal: Type#MEMBER -> Type.MEMBER (sanitize member name)
        if "#" in v:
            parts = v.split("#", 1)
            if parts[0] and parts[1] and parts[0][0].isalpha():
                return f"{parts[0]}.{_safe_name(parts[1])}"

        # Numeric
        try:
            int(v)
            return v
        except ValueError:
            pass
        try:
            float(v)
            return v
        except ValueError:
            pass

        # String literal -- convert IEC escapes to Python
        if v.startswith("'") or v.startswith('"'):
            return _iec_string_to_python(v)

        return v

    def _expr_variable_ref(self, expr: VariableRef, _prec: int) -> str:
        upper = expr.name.upper()
        if upper == "SUPER^":
            return "super()"
        if upper == "THIS^":
            return "self"
        name = expr.name
        # Sanitize names with invalid Python characters (e.g. I/O addresses: "FlexIO:3:I.Data")
        if not name.isidentifier() and ":" in name:
            name = _sanitize_identifier(name)
        # Escape Python keywords (IEC allows IN, AS, etc. as identifiers)
        name = _safe_name(name)
        if name in self._self_vars or expr.name in self._self_vars:
            return f"self.{name}"
        # For FBs with unresolved parents (library inheritance), assume
        # unknown names are inherited instance vars unless they're clearly
        # non-self (temp vars, type names, global functions, etc.)
        if self._has_unresolved_parent and expr.name not in self._non_self_names:
            return f"self.{name}"
        return name

    def _expr_binary(self, expr: BinaryExpr, parent_prec: int) -> str:
        # Pythonic reconstruction attempts
        result = self._try_reconstruct_membership(expr, parent_prec)
        if result is not None:
            return result

        # Function-call style ops
        if expr.op in _FUNC_CALL_OPS:
            return f"{expr.op.value}({self._expr(expr.left)}, {self._expr(expr.right)})"

        my_prec = _BINOP_PRECEDENCE.get(expr.op, 0)
        symbol = _BINOP_PYTHON.get(expr.op, expr.op.value)
        left = self._expr(expr.left, my_prec)
        right = self._expr(expr.right, my_prec + 1)
        result = f"{left} {symbol} {right}"
        if my_prec < parent_prec:
            return f"({result})"
        return result

    def _expr_unary(self, expr: UnaryExpr, parent_prec: int) -> str:
        operand = self._expr(expr.operand, 10)
        if expr.op == UnaryOp.NEG:
            return f"-{operand}"
        if expr.op == UnaryOp.NOT:
            # Python's 'not' has low precedence -- needs parens inside
            # bitwise ops (&, |, ^) to avoid SyntaxError
            result = f"not {operand}"
            if parent_prec > 6:  # 6 = Python precedence of 'not'
                return f"({result})"
            return result
        if expr.op == UnaryOp.BNOT:
            return f"~{operand}"
        return f"{expr.op.value}({operand})"

    def _expr_function_call(self, expr: FunctionCallExpr, _prec: int) -> str:
        # Pythonic reconstruction attempts
        for try_fn in (
            self._try_reconstruct_fstring,
            self._try_reconstruct_ternary,
            self._try_reconstruct_clamp,
            self._try_reconstruct_floor_div,
        ):
            result = try_fn(expr, _prec)
            if result is not None:
                return result

        name = expr.function_name
        upper = name.upper()
        # Beckhoff OOP: SUPER^.Method() -> super().Method() (case-insensitive)
        if upper.startswith("SUPER^."):
            name = f"super().{name[7:]}"
        elif upper.startswith("THIS^."):
            name = f"self.{name[6:]}"
        else:
            name = _FUNC_REMAP.get(name, name)
        # Convert remaining ptr^.member to ptr.deref.member (always, not just else)
        if "^." in name:
            name = name.replace("^.", ".deref.")
        if "^" in name:
            name = name.replace("^", ".deref")
        # Convert IEC operators in embedded chained calls
        name = _fix_embedded_iec(name)
        args = self._call_args_str(expr.args)
        return f"{name}({args})"

    # ------------------------------------------------------------------
    # Pythonic reconstruction methods
    #
    # Each method returns ``str | None``.  The calling site tries each
    # in turn and uses the first non-None result; otherwise falls
    # through to generic formatting.
    # ------------------------------------------------------------------

    def _try_reconstruct_fstring(self, expr: FunctionCallExpr, _prec: int) -> str | None:
        """``CONCAT(a, b, ...)`` -> ``f"...{expr}..."``."""
        if expr.function_name != "CONCAT":
            return None
        if any(a.name is not None for a in expr.args):
            return None  # named args -- not from f-string

        parts: list[str] = []
        all_literal = True
        for arg in expr.args:
            val = arg.value
            if isinstance(val, LiteralExpr) and val.value.startswith("'") and val.value.endswith("'"):
                text = val.value[1:-1]
                if '"' in text:
                    return None  # can't safely embed in f"..."
                parts.append(text.replace("{", "{{").replace("}", "}}"))
            elif isinstance(val, TypeConversionExpr) and isinstance(val.target_type, StringTypeRef):
                # Strip the *_TO_STRING conversion -- f-string handles it
                all_literal = False
                parts.append(f"{{{self._expr(val.source)}}}")
            else:
                # Already-string expression -- embed directly
                all_literal = False
                parts.append(f"{{{self._expr(val)}}}")

        if all_literal:
            # Pure string concatenation with no interpolations -- just join
            return f"'{''.join(parts)}'"

        return f'f"{"".join(parts)}"'

    def _try_reconstruct_ternary(self, expr: FunctionCallExpr, _prec: int) -> str | None:
        """``SEL(cond, false_val, true_val)`` -> ``true_val if cond else false_val``."""
        if expr.function_name != "SEL" or len(expr.args) != 3:
            return None
        if any(a.name is not None for a in expr.args):
            return None  # named args -- from vendor code, not from ternary
        cond = self._expr(expr.args[0].value)
        false_val = self._expr(expr.args[1].value)
        true_val = self._expr(expr.args[2].value)
        result = f"{true_val} if {cond} else {false_val}"
        # Ternary has very low precedence -- parenthesise if nested
        if _prec > 0:
            return f"({result})"
        return result

    def _try_reconstruct_clamp(self, expr: FunctionCallExpr, _prec: int) -> str | None:
        """``LIMIT(mn, val, mx)`` -> ``math.clamp(val, mn, mx)``."""
        if expr.function_name != "LIMIT" or len(expr.args) != 3:
            return None
        mn = self._expr(expr.args[0].value, 0)
        val = self._expr(expr.args[1].value, 0)
        mx = self._expr(expr.args[2].value, 0)
        return f"math.clamp({val}, {mn}, {mx})"

    def _try_reconstruct_floor_div(self, expr: FunctionCallExpr, _prec: int) -> str | None:
        """``TRUNC(a / b)`` -> ``a // b``."""
        if expr.function_name != "TRUNC" or len(expr.args) != 1:
            return None
        inner = expr.args[0].value
        if not isinstance(inner, BinaryExpr) or inner.op != BinaryOp.DIV:
            return None
        left = self._expr(inner.left, 5)
        right = self._expr(inner.right, 6)
        return f"{left} // {right}"

    def _try_reconstruct_membership(self, expr: BinaryExpr, parent_prec: int) -> str | None:
        """OR/EQ chain -> ``x in (a, b, c)``, AND/NE chain -> ``x not in (a, b, c)``.

        The compiler emits::

            OR(OR(EQ(x, a), EQ(x, b)), EQ(x, c))     # x in (a, b, c)
            AND(AND(NE(x, a), NE(x, b)), NE(x, c))    # x not in (a, b, c)

        Walks the left spine collecting EQ/NE leaves.  All leaves must
        compare the same ``left`` expression (structural equality via
        Pydantic ``__eq__``).  Requires at least two values.
        """
        # Determine which pair of ops to look for
        if expr.op == BinaryOp.OR:
            leaf_op = BinaryOp.EQ
            negate = False
        elif expr.op == BinaryOp.AND:
            leaf_op = BinaryOp.NE
            negate = True
        else:
            return None

        # Collect values by walking the left-folded spine
        values: list[Expression] = []
        target: Expression | None = None
        node: Expression = expr

        while isinstance(node, BinaryExpr) and node.op == expr.op:
            rhs = node.right
            if not isinstance(rhs, BinaryExpr) or rhs.op != leaf_op:
                return None
            if target is None:
                target = rhs.left
            elif rhs.left != target:
                return None
            values.append(rhs.right)
            node = node.left

        # The leftmost node is also a leaf
        if not isinstance(node, BinaryExpr) or node.op != leaf_op:
            return None
        if target is None:
            target = node.left
        elif node.left != target:
            return None
        values.append(node.right)

        if len(values) < 2:
            return None

        # Values were collected right-to-left; reverse to restore original order
        values.reverse()

        keyword = "not in" if negate else "in"
        target_str = self._expr(target)
        values_str = ", ".join(self._expr(v) for v in values)
        result = f"{target_str} {keyword} ({values_str})"
        # `in` has comparison-level precedence in Python
        if _BINOP_PRECEDENCE[BinaryOp.EQ] < parent_prec:
            return f"({result})"
        return result

    def _expr_array_access(self, expr: ArrayAccessExpr, _prec: int) -> str:
        indices = ", ".join(self._expr(i) for i in expr.indices)
        return f"{self._expr(expr.array, 10)}[{indices}]"

    def _expr_member_access(self, expr: MemberAccessExpr, _prec: int) -> str:
        # Beckhoff OOP: THIS^.member -> self.member, SUPER^.member -> super().member
        if isinstance(expr.struct, DerefExpr) and isinstance(expr.struct.pointer, VariableRef):
            name = expr.struct.pointer.name.upper()
            if name == "THIS":
                return f"self.{_safe_name(expr.member)}"
            if name == "SUPER":
                return f"super().{_safe_name(expr.member)}"
        return f"{self._expr(expr.struct, 10)}.{_safe_name(expr.member)}"

    def _expr_deref(self, expr: DerefExpr, _prec: int) -> str:
        # Beckhoff OOP: bare THIS^ -> self, SUPER^ -> super()
        if isinstance(expr.pointer, VariableRef):
            name = expr.pointer.name.upper()
            if name == "THIS":
                return "self"
            if name == "SUPER":
                return "super()"
        return f"{self._expr(expr.pointer, 10)}.deref"

    def _expr_bit_access(self, expr: BitAccessExpr, _prec: int) -> str:
        target = self._expr(expr.target, 10)
        if isinstance(expr.bit_index, int):
            return f"{target}.bit{expr.bit_index}"
        # Dynamic bit access (vendor-specific, e.g. AB target.[expr])
        return f"{target}.bit[{self._expr(expr.bit_index)}]"

    def _expr_type_conversion(self, expr: TypeConversionExpr, _prec: int) -> str:
        # Type conversions are implicit in the Python DSL -- variable declarations
        # carry the type info, and the raise pass inserts explicit conversions
        # when compiling to vendor ST.
        return self._expr(expr.source, _prec)

    def _expr_substring(self, expr: SubstringExpr, _prec: int) -> str:
        s = self._expr(expr.string, 10)
        if expr.single_char:
            return f"{s}[{self._expr(expr.start)}]"
        start = self._expr(expr.start) if expr.start is not None else ""
        end = self._expr(expr.end) if expr.end is not None else ""
        return f"{s}[{start}:{end}]"

    def _expr_system_flag(self, expr: SystemFlagExpr, _prec: int) -> str:
        if expr.flag == SystemFlag.FIRST_SCAN:
            return "first_scan()"
        return f"# unknown flag: {expr.flag}"

    def _call_args_str(self, args: list) -> str:
        """Render call args with positional args before named args.

        ST allows positional args after named args; Python does not.
        """
        positional = [a for a in args if a.name is None]
        named = [a for a in args if a.name is not None]
        parts = [self._expr(a.value) for a in positional]
        parts += [f"{_safe_name(a.name)}={self._expr(a.value)}" for a in named]
        return ", ".join(parts)


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

"""Expression compilation methods for the AST compiler.

Handles all expression AST nodes: constants, names, attributes, binary/unary
operators, comparisons, boolean operators, function calls, subscripts, and
ternary expressions.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.types import ArrayTypeRef, NamedTypeRef, PrimitiveType, PrimitiveTypeRef, StringTypeRef, TypeRef

from ._compiler_core import (
    CompileError,
    SENTINEL_REGISTRY,
    _BIT_ACCESS_RE,
    _BIT_ACCESSIBLE_WIDTHS,
    _BINOP_MAP,
    _BUILTIN_FUNCS,
    _CMPOP_MAP,
    _MATH_CONSTANTS,
    _MATH_FUNC_MAP,
    _PYTHON_BUILTIN_MAP,
    _PYTHON_TYPE_CONV_MAP,
    _REJECTED_BINOP_MESSAGES,
    _REJECTED_BUILTINS,
    _REJECTED_CMPOP_MESSAGES,
    _TYPE_CONV_RE,
    _infer_type,
)

if TYPE_CHECKING:
    from ._compiler import ASTCompiler


# ---------------------------------------------------------------------------
# Expression mixin
# ---------------------------------------------------------------------------

class _ExpressionMixin:
    """Mixin providing expression compilation methods for ASTCompiler."""

    def _compile_constant(self, node: ast.Constant) -> Expression:
        value = node.value
        # bool check before int (bool is subclass of int)
        if isinstance(value, bool):
            return LiteralExpr(value="TRUE" if value else "FALSE",
                               data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))
        if isinstance(value, int):
            return LiteralExpr(value=str(value))
        if isinstance(value, float):
            return LiteralExpr(value=str(value))
        if isinstance(value, str):
            return LiteralExpr(value=f"'{value}'")
        if value is None:
            raise CompileError(
                "None does not exist in PLC logic. Use 0, 0.0, FALSE, or '' depending on type.",
                node, self.ctx,
            )
        raise CompileError(f"Unsupported constant type: {type(value).__name__}", node, self.ctx)

    def _compile_name(self, node: ast.Name) -> Expression:
        name = node.id
        # Check for TRUE/FALSE constants
        if name in ("True", "TRUE"):
            return LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))
        if name in ("False", "FALSE"):
            return LiteralExpr(value="FALSE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))
        return VariableRef(name=name)

    def _compile_attribute(self, node: ast.Attribute) -> Expression:
        # self.x → VariableRef(name="x")
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            return VariableRef(name=node.attr)
        # Enum literal: MachineState.RUNNING → LiteralExpr
        if isinstance(node.value, ast.Name) and node.value.id in self.ctx.known_enums:
            enum_name = node.value.id
            member_name = node.attr
            members = self.ctx.known_enums[enum_name]
            if member_name not in members:
                raise CompileError(
                    f"'{member_name}' is not a member of enum '{enum_name}'",
                    node, self.ctx,
                )
            return LiteralExpr(
                value=f"{enum_name}#{member_name}",
                data_type=NamedTypeRef(name=enum_name),
            )
        # math module constants: math.pi, math.e, math.tau, math.inf
        if isinstance(node.value, ast.Name) and node.value.id == "math":
            if node.attr in _MATH_CONSTANTS:
                return LiteralExpr(value=_MATH_CONSTANTS[node.attr])
            raise CompileError(
                f"math.{node.attr} is not supported in PLC logic. "
                f"Supported: {', '.join(f'math.{k}' for k in sorted(_MATH_CONSTANTS))}",
                node, self.ctx,
            )
        # Pointer dereference: expr.deref → DerefExpr(pointer=expr)
        if node.attr == "deref":
            pointer = self.compile_expression(node.value)
            return DerefExpr(pointer=pointer)
        # Bit access: expr.bit5 → BitAccessExpr(target=expr, bit_index=5)
        m = _BIT_ACCESS_RE.match(node.attr)
        if m:
            bit_index = int(m.group(1))
            target = self.compile_expression(node.value)
            # Validate target type supports bit access when type is known
            target_type = _infer_type(node.value, self.ctx)
            if target_type is not None:
                if isinstance(target_type, PrimitiveTypeRef):
                    width = _BIT_ACCESSIBLE_WIDTHS.get(target_type.type)
                    if width is None:
                        raise CompileError(
                            f"Bit access is not supported on {target_type.type.value}. "
                            f"Bit access requires an integer or bit-string type "
                            f"(BYTE, WORD, DWORD, LWORD, SINT, INT, DINT, LINT, etc.).",
                            node, self.ctx,
                        )
                    if bit_index >= width:
                        raise CompileError(
                            f"bit{bit_index} is out of range for {target_type.type.value} "
                            f"(valid range: bit0..bit{width - 1}).",
                            node, self.ctx,
                        )
                elif isinstance(target_type, StringTypeRef):
                    kind = "WSTRING" if target_type.wide else "STRING"
                    raise CompileError(
                        f"Bit access is not supported on {kind}. "
                        f"Bit access requires an integer or bit-string type.",
                        node, self.ctx,
                    )
                elif isinstance(target_type, NamedTypeRef):
                    raise CompileError(
                        f"Bit access is not supported on '{target_type.name}'. "
                        f"Bit access requires an integer or bit-string type.",
                        node, self.ctx,
                    )
            return BitAccessExpr(target=target, bit_index=bit_index)
        # self.a.b → MemberAccessExpr
        struct = self.compile_expression(node.value)
        return MemberAccessExpr(struct=struct, member=node.attr)

    def _compile_binop(self, node: ast.BinOp) -> Expression:
        rejected_msg = _REJECTED_BINOP_MESSAGES.get(type(node.op))
        if rejected_msg is not None:
            raise CompileError(rejected_msg, node, self.ctx)
        # Reject string concatenation via + — use f-strings instead
        if isinstance(node.op, ast.Add):
            left_type = _infer_type(node.left, self.ctx)
            right_type = _infer_type(node.right, self.ctx)
            if isinstance(left_type, StringTypeRef) or isinstance(right_type, StringTypeRef):
                raise CompileError(
                    "String concatenation with + is not supported. "
                    'Use an f-string instead: f"text {self.var}"',
                    node, self.ctx,
                )
        # Floor division: a // b → TRUNC(a / b)
        if isinstance(node.op, ast.FloorDiv):
            left = self.compile_expression(node.left)
            right = self.compile_expression(node.right)
            return FunctionCallExpr(
                function_name="TRUNC",
                args=[CallArg(value=BinaryExpr(op=BinaryOp.DIV, left=left, right=right))],
            )
        op = _BINOP_MAP.get(type(node.op))
        if op is None:
            raise CompileError(
                f"Unsupported binary operator: {type(node.op).__name__}",
                node, self.ctx,
            )
        left = self.compile_expression(node.left)
        right = self.compile_expression(node.right)
        return BinaryExpr(op=op, left=left, right=right)

    def _compile_boolop(self, node: ast.BoolOp) -> Expression:
        op = BinaryOp.AND if isinstance(node.op, ast.And) else BinaryOp.OR
        # Left-fold: a and b and c → AND(AND(a, b), c)
        result = self.compile_expression(node.values[0])
        for val in node.values[1:]:
            right = self.compile_expression(val)
            result = BinaryExpr(op=op, left=result, right=right)
        return result

    def _compile_compare(self, node: ast.Compare) -> Expression:
        # a < b < c → (a < b) and (b < c)
        parts: list[Expression] = []
        left = self.compile_expression(node.left)

        for i, (cmp_op, comparator) in enumerate(zip(node.ops, node.comparators)):
            # in / not in → membership test expansion
            if isinstance(cmp_op, (ast.In, ast.NotIn)):
                if i != len(node.ops) - 1:
                    raise CompileError(
                        "'in' / 'not in' must be the last operator in a chained comparison",
                        node, self.ctx,
                    )
                negate = isinstance(cmp_op, ast.NotIn)
                parts.append(self._compile_membership_test(left, comparator, node, negate))
                break

            op = _CMPOP_MAP.get(type(cmp_op))
            if op is None:
                rejected = _REJECTED_CMPOP_MESSAGES.get(type(cmp_op))
                if rejected:
                    raise CompileError(rejected, node, self.ctx)
                raise CompileError(
                    f"Unsupported comparison operator: {type(cmp_op).__name__}",
                    node, self.ctx,
                )
            right = self.compile_expression(comparator)
            parts.append(BinaryExpr(op=op, left=left, right=right))
            left = right

        if len(parts) == 1:
            return parts[0]
        # Chain: AND all parts together
        result = parts[0]
        for p in parts[1:]:
            result = BinaryExpr(op=BinaryOp.AND, left=result, right=p)
        return result

    def _compile_membership_test(
        self,
        left: Expression,
        comparator: ast.expr,
        node: ast.Compare,
        negate: bool,
    ) -> Expression:
        """Compile ``x in (a, b, c)`` → OR chain of EQ, ``x not in (...)`` → AND chain of NE."""
        if not isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
            raise CompileError(
                "'in' / 'not in' requires a tuple, list, or set of values "
                "(e.g. x in (1, 2, 3)), not a variable or expression",
                node, self.ctx,
            )

        elements = comparator.elts

        # Empty collection → constant
        if not elements:
            value = "TRUE" if negate else "FALSE"
            return LiteralExpr(value=value, data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))

        eq_op = BinaryOp.NE if negate else BinaryOp.EQ
        chain_op = BinaryOp.AND if negate else BinaryOp.OR

        compiled_elts = [self.compile_expression(elt) for elt in elements]

        # Single element → simple comparison
        if len(compiled_elts) == 1:
            return BinaryExpr(op=eq_op, left=left, right=compiled_elts[0])

        # Multiple → left-folded chain
        result = BinaryExpr(op=eq_op, left=left, right=compiled_elts[0])
        for elt in compiled_elts[1:]:
            result = BinaryExpr(
                op=chain_op,
                left=result,
                right=BinaryExpr(op=eq_op, left=left, right=elt),
            )
        return result

    def _compile_unaryop(self, node: ast.UnaryOp) -> Expression:
        operand = self.compile_expression(node.operand)
        if isinstance(node.op, ast.Not):
            return UnaryExpr(op=UnaryOp.NOT, operand=operand)
        if isinstance(node.op, ast.USub):
            return UnaryExpr(op=UnaryOp.NEG, operand=operand)
        if isinstance(node.op, ast.Invert):
            return UnaryExpr(op=UnaryOp.BNOT, operand=operand)
        if isinstance(node.op, ast.UAdd):
            return operand  # +x → x
        raise CompileError(
            f"Unsupported unary operator: {type(node.op).__name__}",
            node, self.ctx,
        )

    # Sentinel category → compile method, built once at class level
    _SENTINEL_DISPATCH: dict[str, str] = {
        "timer": "_compile_timer_sentinel",
        "edge": "_compile_edge_sentinel",
        "counter": "_compile_counter_sentinel",
        "ctud": "_compile_ctud_sentinel",
        "bistable": "_compile_bistable_sentinel",
        "system_flag": "_compile_system_flag_sentinel",
    }

    def _compile_call(self, node: ast.Call) -> Expression:
        """Route call AST node to the appropriate handler."""
        func = node.func
        if isinstance(func, ast.Name):
            return self._compile_call_by_name(func.id, node)
        if isinstance(func, ast.Subscript):
            result = self._compile_call_subscript(func, node)
            if result is not None:
                return result
        if isinstance(func, ast.Attribute):
            return self._compile_call_attribute(func, node)
        raise CompileError(
            f"Unsupported call target: {type(func).__name__}",
            node, self.ctx,
        )

    # ------------------------------------------------------------------
    # Call by bare name: foo(...)
    # ------------------------------------------------------------------

    def _compile_call_by_name(self, name: str, node: ast.Call) -> Expression:
        """Compile a call where the target is a bare name (``foo(...)``).

        Tries each handler in order: sentinels, timedelta, Python builtins,
        type conversions, IEC built-ins, then falls through to a generic
        function call.
        """
        # Sentinel functions (timers, edges, counters, bistables, system flags)
        sentinel = SENTINEL_REGISTRY.get(name)
        if sentinel is not None:
            handler = getattr(self, self._SENTINEL_DISPATCH[sentinel.category])
            return handler(name, node)

        # timedelta(...) → LiteralExpr("T#...")
        if name == "timedelta":
            return self._compile_timedelta(node)

        # range() — error (only valid in for)
        if name == "range":
            raise CompileError(
                "range() can only be used in a for loop",
                node, self.ctx,
            )

        # Python type conversions: int(x), float(x), bool(x)
        if name in _PYTHON_TYPE_CONV_MAP:
            if len(node.args) != 1 or node.keywords:
                raise CompileError(f"{name}() takes exactly 1 argument", node, self.ctx)
            source = self.compile_expression(node.args[0])
            return TypeConversionExpr(target_type=_PYTHON_TYPE_CONV_MAP[name], source=source)

        # Rejected Python builtins
        if name in _REJECTED_BUILTINS:
            raise CompileError(_REJECTED_BUILTINS[name], node, self.ctx)

        # pow(x, y) → x ** y (BinaryExpr EXPT)
        if name == "pow":
            return self._compile_pow(node)

        # Python builtins → IEC functions
        if name in _PYTHON_BUILTIN_MAP:
            args = self._compile_call_args(node)
            return FunctionCallExpr(function_name=_PYTHON_BUILTIN_MAP[name], args=args)

        # Type conversion: INT_TO_REAL(x), DINT_TO_STRING(x)
        result = self._try_compile_type_conversion(name, node)
        if result is not None:
            return result

        # Direct IEC type name as conversion: INT(x), dint(x), LREAL(x)
        result = self._try_compile_primitive_cast(name, node)
        if result is not None:
            return result

        # IEC built-in functions (uppercase)
        if name.upper() in _BUILTIN_FUNCS and name == name.upper():
            args = self._compile_call_args(node)
            return FunctionCallExpr(function_name=name, args=args)

        # Default: generic function call
        args = self._compile_call_args(node)
        return FunctionCallExpr(function_name=name, args=args)

    def _compile_pow(self, node: ast.Call) -> Expression:
        """``pow(x, y)`` → ``BinaryExpr(EXPT, x, y)``."""
        if len(node.args) != 2 or node.keywords:
            raise CompileError(
                "pow() requires exactly 2 arguments in PLC logic (no modular exponentiation)",
                node, self.ctx,
            )
        left = self.compile_expression(node.args[0])
        right = self.compile_expression(node.args[1])
        return BinaryExpr(op=BinaryOp.EXPT, left=left, right=right)

    def _try_compile_type_conversion(self, name: str, node: ast.Call) -> Expression | None:
        """Try ``INT_TO_REAL(x)`` pattern. Returns None if name doesn't match."""
        m = _TYPE_CONV_RE.match(name)
        if not m:
            return None
        source_type_name = m.group(1)
        target_type_name = m.group(2)
        if len(node.args) != 1:
            raise CompileError(
                f"Type conversion {name}() takes exactly 1 argument",
                node, self.ctx,
            )
        source = self.compile_expression(node.args[0])
        try:
            target_type: TypeRef = PrimitiveTypeRef(type=PrimitiveType(target_type_name))
        except ValueError:
            target_type = NamedTypeRef(name=target_type_name)
        try:
            source_type: TypeRef = PrimitiveTypeRef(type=PrimitiveType(source_type_name))
        except ValueError:
            source_type = NamedTypeRef(name=source_type_name)
        return TypeConversionExpr(target_type=target_type, source=source, source_type=source_type)

    def _try_compile_primitive_cast(self, name: str, node: ast.Call) -> Expression | None:
        """Try ``INT(x)`` / ``LREAL(x)`` — direct IEC type name as cast. Returns None if not a primitive."""
        if len(node.args) != 1 or node.keywords:
            return None
        try:
            prim = PrimitiveType(name.upper())
        except ValueError:
            return None
        source = self.compile_expression(node.args[0])
        return TypeConversionExpr(target_type=PrimitiveTypeRef(type=prim), source=source)

    # ------------------------------------------------------------------
    # Call by subscript: self.fb_array[i](...)
    # ------------------------------------------------------------------

    def _compile_call_subscript(self, func: ast.Subscript, node: ast.Call) -> Expression | None:
        """``self.fb_array[i](...)`` → FBInvocation with array access. Returns None if not an FB array call."""
        attr = func.value
        if not (isinstance(attr, ast.Attribute) and isinstance(attr.value, ast.Name) and attr.value.id == "self"):
            return None
        array_name = attr.attr
        if isinstance(func.slice, ast.Tuple):
            index_exprs = [self.compile_expression(elt) for elt in func.slice.elts]
        else:
            index_exprs = [self.compile_expression(func.slice)]
        inv = self._build_fb_array_invocation(array_name, index_exprs, node)
        if inv is not None:
            self.ctx.pending_fb_invocations.append(inv)
            return ArrayAccessExpr(array=VariableRef(name=array_name), indices=index_exprs)
        return None

    # ------------------------------------------------------------------
    # Call by attribute: self.fb(...), self.method(...), math.sqrt(...)
    # ------------------------------------------------------------------

    def _compile_call_attribute(self, func: ast.Attribute, node: ast.Call) -> Expression:
        """Compile attribute-based calls: ``self.fb()``, ``math.sqrt()``, ``obj.method()``."""
        # self.fb_instance(...) or self.method_name(...)
        if isinstance(func.value, ast.Name) and func.value.id == "self":
            return self._compile_call_self_attr(func.attr, node)

        # Module-qualified calls: datetime.timedelta(...), math.sqrt(...)
        if isinstance(func.value, ast.Name):
            module = func.value.id
            if module == "datetime" and func.attr == "timedelta":
                return self._compile_timedelta(node)
            if module == "math":
                return self._compile_call_math(func.attr, node)

        # Other attribute calls: expr.method(...)
        struct = self.compile_expression(func.value)
        args = self._compile_call_args(node)
        return FunctionCallExpr(
            function_name=func.attr,
            args=[CallArg(value=struct)] + args,
        )

    def _compile_call_self_attr(self, attr_name: str, node: ast.Call) -> Expression:
        """``self.fb(...)`` → FBInvocation or ``self.method(...)`` → FunctionCallExpr."""
        inv = self._build_fb_invocation(attr_name, node)
        if inv is not None:
            self.ctx.pending_fb_invocations.append(inv)
            return VariableRef(name=attr_name)
        if attr_name in self.ctx.known_methods:
            args = self._compile_call_args(node)
            return FunctionCallExpr(function_name=attr_name, args=args)
        raise CompileError(
            f"'{attr_name}' is not a known FB instance or method on this POU",
            node, self.ctx,
        )

    def _compile_call_math(self, func_name: str, node: ast.Call) -> Expression:
        """``math.sqrt(x)`` → ``SQRT(x)``, ``math.clamp(v, mn, mx)`` → ``LIMIT(mn, v, mx)``."""
        if func_name == "clamp":
            if len(node.args) != 3 or node.keywords:
                raise CompileError(
                    "math.clamp() requires exactly 3 positional arguments: "
                    "math.clamp(value, min, max)",
                    node, self.ctx,
                )
            value = self.compile_expression(node.args[0])
            mn = self.compile_expression(node.args[1])
            mx = self.compile_expression(node.args[2])
            return FunctionCallExpr(
                function_name="LIMIT",
                args=[CallArg(value=mn), CallArg(value=value), CallArg(value=mx)],
            )
        iec_name = _MATH_FUNC_MAP.get(func_name)
        if iec_name is None:
            raise CompileError(
                f"math.{func_name}() is not supported in PLC logic. "
                f"Supported: {', '.join(f'math.{k}()' for k in sorted({**_MATH_FUNC_MAP, 'clamp': 'LIMIT'}))}",
                node, self.ctx,
            )
        args = self._compile_call_args(node)
        return FunctionCallExpr(function_name=iec_name, args=args)

    def _compile_subscript(self, node: ast.Subscript) -> Expression:
        # Slice operation (e.g. s[1:3], s[:n], s[n:])
        if isinstance(node.slice, ast.Slice):
            return self._compile_slice(node, node.slice)

        # Single index — check if this is string indexing
        from ._compiler_statements import _infer_type
        value_type = _infer_type(node.value, self.ctx)
        if isinstance(value_type, StringTypeRef):
            return self._compile_string_index(node)

        # Array access (existing logic)
        array = self.compile_expression(node.value)
        if isinstance(node.slice, ast.Tuple):
            indices = [self.compile_expression(elt) for elt in node.slice.elts]
        else:
            indices = [self.compile_expression(node.slice)]
        return ArrayAccessExpr(array=array, indices=indices)

    def _compile_slice(self, node: ast.Subscript, slc: ast.Slice) -> Expression:
        """Compile a slice operation. Only valid on STRING types."""
        from ._compiler_statements import _infer_type

        value_type = _infer_type(node.value, self.ctx)

        if not isinstance(value_type, StringTypeRef):
            if value_type is None:
                raise CompileError(
                    "Cannot determine the type of the sliced expression. "
                    "String slicing requires a declared STRING variable. "
                    "If this is an array, access elements individually "
                    "with a single index: arr[i].",
                    node, self.ctx,
                )
            raise CompileError(
                "Slice operations are not supported on this type. "
                "Only STRING variables support slicing. "
                "Access array elements individually with a single index: arr[i].",
                node, self.ctx,
            )

        # Reject step slicing: s[::2], s[1:3:2]
        if slc.step is not None:
            raise CompileError(
                "Step slicing (e.g. s[::2]) is not supported on strings.",
                node, self.ctx,
            )

        # Reject negative indices
        self._reject_negative_index(slc.lower, "start", node)
        self._reject_negative_index(slc.upper, "stop", node)

        string_expr = self.compile_expression(node.value)
        start = self.compile_expression(slc.lower) if slc.lower is not None else None
        end = self.compile_expression(slc.upper) if slc.upper is not None else None

        # s[:] → identity (return the string expression directly)
        if start is None and end is None:
            return string_expr

        return SubstringExpr(string=string_expr, start=start, end=end)

    def _compile_string_index(self, node: ast.Subscript) -> Expression:
        """Compile s[i] on a STRING → SubstringExpr(single_char=True)."""
        self._reject_negative_index(node.slice, "index", node)
        string_expr = self.compile_expression(node.value)
        index = self.compile_expression(node.slice)
        return SubstringExpr(string=string_expr, start=index, single_char=True)

    def _reject_negative_index(
        self, node: ast.expr | None, label: str, parent: ast.AST,
    ) -> None:
        """Raise CompileError if node is a negative literal."""
        if node is None:
            return
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
        ):
            raise CompileError(
                f"Negative {label} in string slicing is not supported. "
                f"Use LEN() to compute the position explicitly.",
                parent, self.ctx,
            )

    def _compile_ifexp(self, node: ast.IfExp) -> Expression:
        """Ternary: ``a if cond else b`` → ``SEL(cond, false_val, true_val)``."""
        cond = self.compile_expression(node.test)
        true_val = self.compile_expression(node.body)
        false_val = self.compile_expression(node.orelse)
        return FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=cond),
                CallArg(value=false_val),
                CallArg(value=true_val),
            ],
        )

    def _compile_timedelta(self, node: ast.Call) -> LiteralExpr:
        """Compile ``timedelta(...)`` to a TIME LiteralExpr at compile time."""
        from ._types import timedelta_to_ir
        if node.args:
            raise CompileError(
                "timedelta() in logic must use keyword arguments only "
                "(e.g. timedelta(seconds=5), timedelta(milliseconds=500))",
                node, self.ctx,
            )
        _VALID_KWARGS = {"weeks", "days", "hours", "minutes", "seconds", "milliseconds", "microseconds"}
        kwargs: dict[str, int | float] = {}
        for kw in node.keywords:
            if kw.arg is None:
                raise CompileError("**kwargs not supported in timedelta()", node, self.ctx)
            if kw.arg not in _VALID_KWARGS:
                raise CompileError(
                    f"timedelta() got unexpected keyword argument '{kw.arg}'. "
                    f"Supported: {', '.join(sorted(_VALID_KWARGS))}",
                    node, self.ctx,
                )
            if not isinstance(kw.value, ast.Constant) or not isinstance(kw.value.value, (int, float)):
                raise CompileError(
                    f"timedelta({kw.arg}=...) must be a numeric literal",
                    node, self.ctx,
                )
            kwargs[kw.arg] = kw.value.value
        if not kwargs:
            raise CompileError("timedelta() requires at least one argument", node, self.ctx)
        td = timedelta(**kwargs)
        return timedelta_to_ir(td)

    def _compile_call_args(self, node: ast.Call) -> list[CallArg]:
        """Compile positional and keyword arguments."""
        args: list[CallArg] = []
        for arg in node.args:
            args.append(CallArg(value=self.compile_expression(arg)))
        for kw in node.keywords:
            args.append(CallArg(name=kw.arg, value=self.compile_expression(kw.value)))
        return args

    def _compile_call_kwargs(self, node: ast.Call) -> dict[str, Expression]:
        """Compile keyword arguments into a dict (for FBInvocation inputs)."""
        inputs: dict[str, Expression] = {}
        for kw in node.keywords:
            if kw.arg is None:
                raise CompileError("**kwargs not supported in FB calls", node, self.ctx)
            inputs[kw.arg] = self.compile_expression(kw.value)
        # Positional args are not supported for FB invocations
        if node.args:
            raise CompileError(
                "FB invocations only accept keyword arguments (e.g. self.timer(IN=signal, PT=duration))",
                node, self.ctx,
            )
        return inputs

    def _compile_joinedstr(self, node: ast.JoinedStr) -> Expression:
        """Compile f-string to CONCAT() with automatic type conversions.

        ``f"Fault on axis {self.axis_id}: error {self.error_code}"``
        →  ``CONCAT('Fault on axis ', DINT_TO_STRING(axis_id), ': error ', DINT_TO_STRING(error_code))``
        """
        parts: list[Expression] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                # String literal segment — skip empty strings
                if value.value:
                    parts.append(LiteralExpr(value=f"'{value.value}'"))
            elif isinstance(value, ast.FormattedValue):
                parts.append(self._compile_formattedvalue(value))
            else:
                raise CompileError(
                    f"Unsupported f-string element: {type(value).__name__}",
                    node, self.ctx,
                )

        # Empty f-string → empty string literal
        if not parts:
            return LiteralExpr(value="''")

        # Single part → return directly (no CONCAT wrapper)
        if len(parts) == 1:
            return parts[0]

        # Multiple parts → CONCAT(part1, part2, ...)
        return FunctionCallExpr(
            function_name="CONCAT",
            args=[CallArg(value=p) for p in parts],
        )

    def _compile_formattedvalue(self, node: ast.FormattedValue) -> Expression:
        """Compile a single f-string interpolation ``{expr}``."""
        # Reject conversion flags (!r, !s, !a)
        if node.conversion and node.conversion != -1:
            flag = chr(node.conversion)
            raise CompileError(
                f"Conversion flag !{flag} is not supported in PLC f-strings. "
                f"Type conversion is applied automatically.",
                node, self.ctx,
            )

        # Reject format specs ({x:.2f}, {x:05d}, etc.)
        if node.format_spec is not None:
            raise CompileError(
                "Format specifiers (e.g. :.2f, :05d) are not supported in PLC f-strings. "
                "Use IEC string functions for custom formatting.",
                node, self.ctx,
            )

        expr = self.compile_expression(node.value)

        # If the expression is already a string literal, return as-is
        if isinstance(expr, LiteralExpr) and expr.value.startswith("'"):
            return expr

        # Infer the type to determine if conversion is needed
        inferred = _infer_type(node.value, self.ctx)

        # Already a string → no conversion
        if isinstance(inferred, StringTypeRef):
            return expr

        # Known primitive → wrap in TypeConversionExpr
        if isinstance(inferred, PrimitiveTypeRef):
            return TypeConversionExpr(
                target_type=StringTypeRef(),
                source=expr,
                source_type=inferred,
            )

        # Named type (struct, enum, FB) → can't auto-convert
        if isinstance(inferred, NamedTypeRef):
            raise CompileError(
                f"Cannot automatically convert '{inferred.name}' to STRING in f-string. "
                f"Convert the value to a string explicitly before interpolation.",
                node, self.ctx,
            )

        # Type unknown → error with guidance
        raise CompileError(
            "Cannot determine the type of this expression in the f-string. "
            "Use an explicit type conversion (e.g. DINT_TO_STRING(expr)) instead.",
            node, self.ctx,
        )

    # Expression handler dispatch table
    _EXPRESSION_HANDLERS: dict[type[ast.expr], Callable[[ASTCompiler, ast.expr], Expression]] = {
        ast.Constant: _compile_constant,
        ast.Name: _compile_name,
        ast.Attribute: _compile_attribute,
        ast.BinOp: _compile_binop,
        ast.BoolOp: _compile_boolop,
        ast.Compare: _compile_compare,
        ast.UnaryOp: _compile_unaryop,
        ast.Call: _compile_call,
        ast.Subscript: _compile_subscript,
        ast.IfExp: _compile_ifexp,
        ast.JoinedStr: _compile_joinedstr,
        ast.FormattedValue: _compile_formattedvalue,
    }

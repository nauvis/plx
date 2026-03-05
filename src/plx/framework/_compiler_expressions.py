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
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.types import ArrayTypeRef, NamedTypeRef, PrimitiveType, PrimitiveTypeRef, TypeRef

from ._compiler_core import (
    CompileError,
    SENTINEL_REGISTRY,
    _BIT_ACCESS_RE,
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
        # Bit access: expr.bit5 → BitAccessExpr(target=expr, bit_index=5)
        m = _BIT_ACCESS_RE.match(node.attr)
        if m:
            target = self.compile_expression(node.value)
            return BitAccessExpr(target=target, bit_index=int(m.group(1)))
        # self.a.b → MemberAccessExpr
        struct = self.compile_expression(node.value)
        return MemberAccessExpr(struct=struct, member=node.attr)

    def _compile_binop(self, node: ast.BinOp) -> Expression:
        rejected_msg = _REJECTED_BINOP_MESSAGES.get(type(node.op))
        if rejected_msg is not None:
            raise CompileError(rejected_msg, node, self.ctx)
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

        for cmp_op, comparator in zip(node.ops, node.comparators):
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

    def _compile_unaryop(self, node: ast.UnaryOp) -> Expression:
        operand = self.compile_expression(node.operand)
        if isinstance(node.op, ast.Not):
            return UnaryExpr(op=UnaryOp.NOT, operand=operand)
        if isinstance(node.op, ast.USub):
            return UnaryExpr(op=UnaryOp.NEG, operand=operand)
        if isinstance(node.op, ast.Invert):
            raise CompileError(
                "Bitwise ~ is not supported in logic(). Use 'not' for logical NOT.",
                node, self.ctx,
            )
        if isinstance(node.op, ast.UAdd):
            return operand  # +x → x
        raise CompileError(
            f"Unsupported unary operator: {type(node.op).__name__}",
            node, self.ctx,
        )

    def _compile_call(self, node: ast.Call) -> Expression:
        """Context-dependent call compilation."""
        func = node.func

        if isinstance(func, ast.Name):
            name = func.id

            # Sentinel functions (timers, edges, counters, bistables, system flags)
            sentinel = SENTINEL_REGISTRY.get(name)
            if sentinel is not None:
                _sentinel_dispatch = {
                    "timer": self._compile_timer_sentinel,
                    "edge": self._compile_edge_sentinel,
                    "counter": self._compile_counter_sentinel,
                    "bistable": self._compile_bistable_sentinel,
                    "system_flag": self._compile_system_flag_sentinel,
                }
                handler = _sentinel_dispatch[sentinel.category]
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

            # Python builtins → IEC functions
            if name in _PYTHON_BUILTIN_MAP:
                mapped = _PYTHON_BUILTIN_MAP[name]
                args = self._compile_call_args(node)
                return FunctionCallExpr(function_name=mapped, args=args)

            # Type conversion: INT_TO_REAL(x)
            m = _TYPE_CONV_RE.match(name)
            if m:
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

            # Direct IEC type name as conversion: INT(x), SINT(x), LREAL(x)
            if len(node.args) == 1 and not node.keywords:
                try:
                    prim = PrimitiveType(name)
                    source = self.compile_expression(node.args[0])
                    return TypeConversionExpr(
                        target_type=PrimitiveTypeRef(type=prim),
                        source=source,
                    )
                except ValueError:
                    pass

            # IEC built-in functions (uppercase)
            if name.upper() in _BUILTIN_FUNCS and name == name.upper():
                args = self._compile_call_args(node)
                return FunctionCallExpr(function_name=name, args=args)

            # Default: generic function call
            args = self._compile_call_args(node)
            return FunctionCallExpr(function_name=name, args=args)

        # self.fb_array[i](...) → FBInvocation with Expression instance_name
        if isinstance(func, ast.Subscript):
            attr = func.value
            if isinstance(attr, ast.Attribute) and isinstance(attr.value, ast.Name) and attr.value.id == "self":
                array_name = attr.attr
                if isinstance(func.slice, ast.Tuple):
                    index_exprs = [self.compile_expression(elt) for elt in func.slice.elts]
                else:
                    index_exprs = [self.compile_expression(func.slice)]
                inv = self._build_fb_array_invocation(array_name, index_exprs, node)
                if inv is not None:
                    self.ctx.pending_fb_invocations.append(inv)
                    return ArrayAccessExpr(array=VariableRef(name=array_name), indices=index_exprs)

        # self.fb_instance(...) → FBInvocation (as expression)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
            inv = self._build_fb_invocation(func.attr, node)
            if inv is not None:
                self.ctx.pending_fb_invocations.append(inv)
                return VariableRef(name=func.attr)
            # self.method_name(...) → FunctionCallExpr (method call, no self arg)
            if func.attr in self.ctx.known_methods:
                args = self._compile_call_args(node)
                return FunctionCallExpr(function_name=func.attr, args=args)

        # datetime.timedelta(...) → LiteralExpr("T#...")
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "datetime" and func.attr == "timedelta":
            return self._compile_timedelta(node)

        # math module functions: math.sqrt(x) → SQRT(x)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "math":
            iec_name = _MATH_FUNC_MAP.get(func.attr)
            if iec_name is None:
                raise CompileError(
                    f"math.{func.attr}() is not supported in PLC logic. "
                    f"Supported: {', '.join(f'math.{k}()' for k in sorted(_MATH_FUNC_MAP))}",
                    node, self.ctx,
                )
            args = self._compile_call_args(node)
            return FunctionCallExpr(function_name=iec_name, args=args)

        # Other attribute calls
        if isinstance(func, ast.Attribute):
            struct = self.compile_expression(func.value)
            args = self._compile_call_args(node)
            return FunctionCallExpr(
                function_name=func.attr,
                args=[CallArg(value=struct)] + args,
            )

        raise CompileError(
            f"Unsupported call target: {type(func).__name__}",
            node, self.ctx,
        )

    def _compile_subscript(self, node: ast.Subscript) -> Expression:
        array = self.compile_expression(node.value)
        # Multi-dimensional: a[i, j] → ast.Tuple in node.slice
        if isinstance(node.slice, ast.Tuple):
            indices = [self.compile_expression(elt) for elt in node.slice.elts]
        else:
            indices = [self.compile_expression(node.slice)]
        return ArrayAccessExpr(array=array, indices=indices)

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
    }

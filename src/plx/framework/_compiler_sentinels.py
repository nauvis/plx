"""Sentinel expansion methods for the AST compiler.

Handles timer sentinels (delayed/sustained/pulse/retentive → TON/TOF/TP/RTO),
edge sentinels (rising/falling → R_TRIG/F_TRIG),
counter sentinels (count_up/count_down → CTU/CTD, count_up_down → CTUD),
and system flag sentinels (first_scan).
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from plx.model.expressions import (
    Expression,
    LiteralExpr,
    MemberAccessExpr,
    SystemFlagExpr,
    VariableRef,
)
from plx.model.statements import FBInvocation
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable

from ._compiler_core import (
    CompileContext,
    CompileError,
    SENTINEL_REGISTRY,
)

if TYPE_CHECKING:
    from ._compiler import ASTCompiler


# ---------------------------------------------------------------------------
# Name kwarg helper
# ---------------------------------------------------------------------------

def _extract_name_kwarg(
    call_node: ast.Call,
    ctx: CompileContext,
) -> str | None:
    """Extract and validate optional ``name=`` kwarg from a sentinel call.

    Returns the name string if present, or None.
    """
    for kw in call_node.keywords:
        if kw.arg == "name":
            if not isinstance(kw.value, ast.Constant) or not isinstance(kw.value.value, str):
                raise CompileError("name= must be a string literal", call_node, ctx)
            name = kw.value.value
            if not name.isidentifier():
                raise CompileError(
                    f"name={name!r} is not a valid identifier", call_node, ctx,
                )
            if name in ctx.declared_vars:
                raise CompileError(
                    f"name={name!r} conflicts with a declared variable", call_node, ctx,
                )
            existing_names = {v.name for v in ctx.generated_static_vars}
            if name in existing_names:
                raise CompileError(
                    f"name={name!r} conflicts with an existing generated variable", call_node, ctx,
                )
            return name
    return None


# ---------------------------------------------------------------------------
# Duration helper
# ---------------------------------------------------------------------------

def _parse_duration_kwarg(
    call_node: ast.Call,
    ctx: CompileContext,
    compiler: ASTCompiler,
) -> Expression:
    """Parse duration from a sentinel call.

    Accepts either:
    - A positional second argument: ``delayed(signal, timedelta(seconds=5))``
    - A ``duration=`` kwarg: ``delayed(signal, duration=self.timeout)``

    Returns a LiteralExpr for literal values, or passes through variable
    expressions for HMI-configurable durations.
    """
    keywords = {kw.arg: kw.value for kw in call_node.keywords}

    if "duration" in keywords:
        return compiler.compile_expression(keywords["duration"])

    # Positional second arg (index 1, since index 0 is the signal)
    if len(call_node.args) >= 2:
        return compiler.compile_expression(call_node.args[1])

    raise CompileError(
        "Timer sentinel requires a duration argument: "
        "e.g. delayed(signal, timedelta(seconds=5)) or delayed(signal, duration=expr)",
        call_node, ctx,
    )


# ---------------------------------------------------------------------------
# Sentinel mixin
# ---------------------------------------------------------------------------

class _SentinelMixin:
    """Mixin providing sentinel expansion methods for ASTCompiler."""

    def _emit_fb_sentinel(
        self,
        fb_type: str,
        inputs: dict[str, Expression],
        output_member: str = "Q",
        name: str | None = None,
    ) -> Expression:
        """Create an FB instance variable, queue its invocation, return output.

        Shared by timer, edge, counter, and bistable sentinels.
        """
        instance_name = name if name is not None else self.ctx.next_auto_name(fb_type.lower())

        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs=inputs,
        ))

        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member=output_member,
        )

    def _compile_timer_sentinel(self, sentinel_name: str, node: ast.Call) -> Expression:
        """Compile delayed/sustained/pulse sentinel into TON/TOF/TP."""
        s = SENTINEL_REGISTRY[sentinel_name]

        if not node.args:
            raise CompileError(f"{sentinel_name}() requires a signal argument", node, self.ctx)

        user_name = _extract_name_kwarg(node, self.ctx)
        signal = self.compile_expression(node.args[0])
        duration = _parse_duration_kwarg(node, self.ctx, self)

        return self._emit_fb_sentinel(
            s.fb_type, {s.params["signal"]: signal, s.params["duration"]: duration}, name=user_name,
        )

    def _compile_edge_sentinel(self, sentinel_name: str, node: ast.Call) -> Expression:
        """Compile rising/falling sentinel into R_TRIG/F_TRIG."""
        s = SENTINEL_REGISTRY[sentinel_name]

        if not node.args:
            raise CompileError(f"{sentinel_name}() requires a signal argument", node, self.ctx)

        user_name = _extract_name_kwarg(node, self.ctx)
        signal = self.compile_expression(node.args[0])

        return self._emit_fb_sentinel(s.fb_type, {s.params["signal"]: signal}, name=user_name)

    def _compile_counter_sentinel(self, sentinel_name: str, node: ast.Call) -> Expression:
        """Compile count_up/count_down sentinel into CTU/CTD."""
        s = SENTINEL_REGISTRY[sentinel_name]

        if not node.args:
            raise CompileError(f"{sentinel_name}() requires a signal argument", node, self.ctx)

        user_name = _extract_name_kwarg(node, self.ctx)
        signal = self.compile_expression(node.args[0])

        # Parse keyword args
        keywords = {kw.arg: kw.value for kw in node.keywords}

        # preset is required
        if "preset" not in keywords:
            raise CompileError(
                f"{sentinel_name}() requires a preset= argument",
                node, self.ctx,
            )
        preset_node = keywords["preset"]
        if isinstance(preset_node, ast.Constant) and isinstance(preset_node.value, int):
            preset_expr = LiteralExpr(
                value=str(preset_node.value),
                data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            )
        else:
            preset_expr = self.compile_expression(preset_node)

        inputs = {s.params["signal"]: signal, s.params["preset"]: preset_expr}

        # Optional reset/load
        ctrl_kwarg = "reset" if sentinel_name == "count_up" else "load"
        if ctrl_kwarg in keywords:
            inputs[s.params["control"]] = self.compile_expression(keywords[ctrl_kwarg])

        return self._emit_fb_sentinel(s.fb_type, inputs, name=user_name)

    def _compile_ctud_sentinel(self, sentinel_name: str, node: ast.Call) -> Expression:
        """Compile count_up_down sentinel into CTUD."""
        if len(node.args) < 2:
            raise CompileError(
                "count_up_down() requires two arguments: up_signal and down_signal",
                node, self.ctx,
            )

        user_name = _extract_name_kwarg(node, self.ctx)
        up_signal = self.compile_expression(node.args[0])
        down_signal = self.compile_expression(node.args[1])

        keywords = {kw.arg: kw.value for kw in node.keywords}

        if "preset" not in keywords:
            raise CompileError(
                "count_up_down() requires a preset= argument",
                node, self.ctx,
            )
        preset_node = keywords["preset"]
        if isinstance(preset_node, ast.Constant) and isinstance(preset_node.value, int):
            preset_expr = LiteralExpr(
                value=str(preset_node.value),
                data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            )
        else:
            preset_expr = self.compile_expression(preset_node)

        inputs = {"CU": up_signal, "CD": down_signal, "PV": preset_expr}

        if "reset" in keywords:
            inputs["RESET"] = self.compile_expression(keywords["reset"])
        if "load" in keywords:
            inputs["LOAD"] = self.compile_expression(keywords["load"])

        return self._emit_fb_sentinel("CTUD", inputs, output_member="QU", name=user_name)

    def _compile_bistable_sentinel(self, sentinel_name: str, node: ast.Call) -> Expression:
        """Compile set_dominant/reset_dominant sentinel into SR/RS."""
        s = SENTINEL_REGISTRY[sentinel_name]

        if len(node.args) < 2:
            raise CompileError(
                f"{sentinel_name}() requires two arguments: set_signal and reset_signal",
                node, self.ctx,
            )

        user_name = _extract_name_kwarg(node, self.ctx)
        set_signal = self.compile_expression(node.args[0])
        reset_signal = self.compile_expression(node.args[1])

        return self._emit_fb_sentinel(
            s.fb_type,
            {s.params["set"]: set_signal, s.params["reset"]: reset_signal},
            output_member="Q1",
            name=user_name,
        )

    def _compile_system_flag_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile first_scan() and other system flag sentinels."""
        if node.args or node.keywords:
            raise CompileError(f"{name}() takes no arguments", node, self.ctx)
        return SystemFlagExpr(flag=SENTINEL_REGISTRY[name].system_flag)

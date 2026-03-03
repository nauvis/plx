"""Sentinel expansion methods for the AST compiler.

Handles timer sentinels (delayed/sustained/pulse/retentive → TON/TOF/TP/RTO),
edge sentinels (rising/falling → R_TRIG/F_TRIG),
counter sentinels (count_up/count_down → CTU/CTD),
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
    _BISTABLE_SENTINELS,
    _COUNTER_SENTINELS,
    _EDGE_SENTINELS,
    _SYSTEM_FLAG_SENTINELS,
    _TIMER_SENTINELS,
)

if TYPE_CHECKING:
    from ._compiler import ASTCompiler


# ---------------------------------------------------------------------------
# Duration helper
# ---------------------------------------------------------------------------

def _parse_duration_kwarg(
    call_node: ast.Call,
    ctx: CompileContext,
    compiler: ASTCompiler,
) -> Expression:
    """Parse duration kwargs (seconds=, ms=, duration=) from a sentinel call.

    Returns a LiteralExpr for literal values, or passes through variable
    expressions for HMI-configurable durations.
    """
    keywords = {kw.arg: kw.value for kw in call_node.keywords}

    if "duration" in keywords:
        return compiler.compile_expression(keywords["duration"])

    total_ms = 0.0
    has_duration = False

    if "seconds" in keywords:
        val = keywords["seconds"]
        if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
            total_ms += val.value * 1000
            has_duration = True
        else:
            raise CompileError("seconds= must be a numeric literal", call_node, ctx)

    if "ms" in keywords:
        val = keywords["ms"]
        if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
            total_ms += val.value
            has_duration = True
        else:
            raise CompileError("ms= must be a numeric literal", call_node, ctx)

    if not has_duration:
        raise CompileError(
            "Timer sentinel requires seconds=, ms=, or duration= argument",
            call_node, ctx,
        )

    # Format as IEC TIME literal
    total_ms_int = int(total_ms)
    if total_ms_int == total_ms:
        if total_ms_int >= 1000 and total_ms_int % 1000 == 0:
            iec_str = f"T#{total_ms_int // 1000}s"
        else:
            iec_str = f"T#{total_ms_int}ms"
    else:
        iec_str = f"T#{total_ms}ms"

    return LiteralExpr(
        value=iec_str,
        data_type=PrimitiveTypeRef(type=PrimitiveType.TIME),
    )


# ---------------------------------------------------------------------------
# Sentinel mixin
# ---------------------------------------------------------------------------

class _SentinelMixin:
    """Mixin providing sentinel expansion methods for ASTCompiler."""

    def _compile_timer_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile delayed/sustained/pulse sentinel into TON/TOF/TP."""
        fb_type, input_name, pt_name = _TIMER_SENTINELS[name]

        if not node.args:
            raise CompileError(f"{name}() requires a signal argument", node, self.ctx)

        signal = self.compile_expression(node.args[0])
        duration = _parse_duration_kwarg(node, self.ctx, self)

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        # Add to generated static vars
        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        # Add FBInvocation to pending
        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs={input_name: signal, pt_name: duration},
        ))

        # Return .Q member access
        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q",
        )

    def _compile_edge_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile rising/falling sentinel into R_TRIG/F_TRIG."""
        fb_type = _EDGE_SENTINELS[name]

        if not node.args:
            raise CompileError(f"{name}() requires a signal argument", node, self.ctx)

        signal = self.compile_expression(node.args[0])

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        # Add to generated static vars
        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        # Add FBInvocation to pending
        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs={"CLK": signal},
        ))

        # Return .Q member access
        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q",
        )

    def _compile_counter_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile count_up/count_down sentinel into CTU/CTD."""
        fb_type, count_input, pv_input, ctrl_input = _COUNTER_SENTINELS[name]

        if not node.args:
            raise CompileError(f"{name}() requires a signal argument", node, self.ctx)

        signal = self.compile_expression(node.args[0])

        # Parse keyword args
        keywords = {kw.arg: kw.value for kw in node.keywords}

        # preset is required
        if "preset" not in keywords:
            raise CompileError(
                f"{name}() requires a preset= argument",
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

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        inputs = {count_input: signal, pv_input: preset_expr}

        # Optional reset/load
        ctrl_kwarg = "reset" if name == "count_up" else "load"
        if ctrl_kwarg in keywords:
            inputs[ctrl_input] = self.compile_expression(keywords[ctrl_kwarg])

        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs=inputs,
        ))

        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q",
        )

    def _compile_bistable_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile set_dominant/reset_dominant sentinel into SR/RS."""
        fb_type, set_input, reset_input = _BISTABLE_SENTINELS[name]

        if len(node.args) < 2:
            raise CompileError(
                f"{name}() requires two arguments: set_signal and reset_signal",
                node, self.ctx,
            )

        set_signal = self.compile_expression(node.args[0])
        reset_signal = self.compile_expression(node.args[1])

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs={set_input: set_signal, reset_input: reset_signal},
        ))

        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q1",
        )

    def _compile_system_flag_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile first_scan() and other system flag sentinels."""
        if node.args or node.keywords:
            raise CompileError(f"{name}() takes no arguments", node, self.ctx)
        return SystemFlagExpr(flag=_SYSTEM_FLAG_SENTINELS[name])

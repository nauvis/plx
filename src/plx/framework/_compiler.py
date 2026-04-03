"""AST compiler: transforms Python AST from logic() into IR nodes.

This module is the core of the framework — it walks a Python AST and
emits Universal IR expression and statement nodes.  The source is parsed
(via ``ast.parse``), never executed.

Key concepts:

- **CompileContext**: carries variable metadata and accumulates generated
  variables (FB instances, temp vars) during compilation.
- **ASTCompiler**: dispatch-table compiler that maps Python AST node
  types to handler methods.
- **Sentinel functions**: ``delayed``, ``rising``, ``falling``,
  ``sustained``, ``pulse``, ``retentive``, ``count_up``, ``count_down``,
  ``count_up_down``
  — importable functions whose bodies raise ``RuntimeError``.  The AST compiler
  recognises them by name and expands them to FBInvocation + instance
  variables.
"""

from __future__ import annotations

import ast

from plx.model.expressions import (
    ArrayAccessExpr,
    Expression,
    VariableRef,
)
from plx.model.statements import (
    FBInvocation,
    Statement,
)
from plx.model.types import (
    ArrayTypeRef,
    NamedTypeRef,
)

from ._compiler_core import (  # noqa: F401
    _REJECTED_NODES,
    CompileContext,
    CompileError,
)
from ._compiler_expressions import _ExpressionMixin

# Import mixins at the top — no late imports needed now that shared
# constants live in _compiler_core.
from ._compiler_sentinels import _SentinelMixin
from ._compiler_statements import _StatementMixin

# ---------------------------------------------------------------------------
# Sentinel functions
# ---------------------------------------------------------------------------
# These exist for IDE autocompletion / linting.  The AST compiler
# recognises them by name and never calls them.


def delayed(signal: object, duration: object = None, *, name: str | None = None) -> bool:
    """On-delay timer (TON). Returns True when ``signal`` has been True
    for at least ``duration``.

    Recognised by the AST compiler and expanded to a ``TON``
    ``FBInvocation`` with an auto-generated instance variable. Never
    called at runtime.

    Parameters
    ----------
    signal : bool expression
        The enable signal. The timer starts when this becomes True.
    duration : timedelta or expression, optional
        Preset time. Pass a ``timedelta`` literal for a fixed duration,
        or a variable reference (e.g. ``self.cfg_timeout``) for a
        configurable duration.
    name : str, optional
        Explicit instance name for the generated timer variable. If
        omitted, an auto-generated name is used (``_plx_ton_0``, etc.).

    Returns
    -------
    bool
        True when the signal has been continuously True for ``duration``.

    Examples
    --------
    ::

        if delayed(self.sensor, timedelta(seconds=5)):
            self.output = True
        if delayed(self.enable, duration=self.cfg_timeout):
            self.timeout_active = True
    """
    raise RuntimeError("delayed() is a compile-time sentinel — do not call directly")


def sustained(signal: object, duration: object = None, *, name: str | None = None) -> bool:
    """Off-delay timer (TOF). Returns True while ``signal`` is True and
    remains True for ``duration`` after ``signal`` goes False.

    Recognised by the AST compiler and expanded to a ``TOF``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        The enable signal. Output stays True for ``duration`` after this
        goes False.
    duration : timedelta or expression, optional
        Off-delay time. Pass a ``timedelta`` literal or a variable
        reference.
    name : str, optional
        Explicit instance name for the generated timer variable.

    Returns
    -------
    bool
        True while the signal is True, and for ``duration`` after it
        goes False.

    Examples
    --------
    ::

        if sustained(self.pump_running, timedelta(seconds=5)):
            self.cooldown_active = True
    """
    raise RuntimeError("sustained() is a compile-time sentinel — do not call directly")


def pulse(signal: object, duration: object = None, *, name: str | None = None) -> bool:
    """Pulse timer (TP). Generates a fixed-duration pulse on the rising
    edge of ``signal``.

    Recognised by the AST compiler and expanded to a ``TP``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        Trigger signal. A rising edge starts the pulse.
    duration : timedelta or expression, optional
        Pulse width. Pass a ``timedelta`` literal or a variable
        reference.
    name : str, optional
        Explicit instance name for the generated timer variable.

    Returns
    -------
    bool
        True for exactly ``duration`` after each rising edge of
        ``signal``.

    Examples
    --------
    ::

        if pulse(self.trigger, timedelta(milliseconds=500)):
            self.solenoid = True
    """
    raise RuntimeError("pulse() is a compile-time sentinel — do not call directly")


def retentive(signal: object, duration: object = None, *, name: str | None = None) -> bool:
    """Retentive on-delay timer (RTO). Accumulates elapsed time while
    ``signal`` is True, retaining the accumulated value when ``signal``
    goes False. Returns True when the accumulated time reaches
    ``duration``.

    Recognised by the AST compiler and expanded to an ``RTO``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        The enable signal. Accumulated time increases while True,
        freezes while False.
    duration : timedelta or expression, optional
        Preset time threshold.
    name : str, optional
        Explicit instance name for the generated timer variable.

    Returns
    -------
    bool
        True when accumulated time reaches ``duration``.

    Examples
    --------
    ::

        if retentive(self.motor_running, timedelta(seconds=10)):
            self.maintenance_due = True
    """
    raise RuntimeError("retentive() is a compile-time sentinel — do not call directly")


def rising(signal: object, *, name: str | None = None) -> bool:
    """Rising edge detector (R_TRIG). Returns True for one scan cycle
    when ``signal`` transitions from False to True.

    Recognised by the AST compiler and expanded to an ``R_TRIG``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        The signal to monitor for rising edges.
    name : str, optional
        Explicit instance name for the generated trigger variable.

    Returns
    -------
    bool
        True for one scan when ``signal`` transitions False to True.

    Examples
    --------
    ::

        if rising(self.start_button):
            self.motor_on = True
    """
    raise RuntimeError("rising() is a compile-time sentinel — do not call directly")


def falling(signal: object, *, name: str | None = None) -> bool:
    """Falling edge detector (F_TRIG). Returns True for one scan cycle
    when ``signal`` transitions from True to False.

    Recognised by the AST compiler and expanded to an ``F_TRIG``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        The signal to monitor for falling edges.
    name : str, optional
        Explicit instance name for the generated trigger variable.

    Returns
    -------
    bool
        True for one scan when ``signal`` transitions True to False.

    Examples
    --------
    ::

        if falling(self.door_closed):
            self.alarm = True
    """
    raise RuntimeError("falling() is a compile-time sentinel — do not call directly")


def count_up(signal: object, *, preset: int = 0, reset: object = None, name: str | None = None) -> bool:
    """Count-up counter (CTU). Increments on each rising edge of
    ``signal``. Returns True when the count reaches ``preset``.

    Recognised by the AST compiler and expanded to a ``CTU``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        Count input. Each rising edge increments the counter.
    preset : int, optional
        Target count value. Output becomes True when the counter
        reaches this value. Defaults to 0.
    reset : bool expression, optional
        Reset input. When True, the counter resets to 0.
    name : str, optional
        Explicit instance name for the generated counter variable.

    Returns
    -------
    bool
        True when the accumulated count reaches ``preset``.

    Examples
    --------
    ::

        if count_up(self.part_sensor, preset=100, reset=self.reset_count):
            self.batch_complete = True
    """
    raise RuntimeError("count_up() is a compile-time sentinel — do not call directly")


def count_down(signal: object, *, preset: int = 0, load: object = None, name: str | None = None) -> bool:
    """Count-down counter (CTD). Decrements on each rising edge of
    ``signal``. Returns True when the count reaches zero.

    Recognised by the AST compiler and expanded to a ``CTD``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    signal : bool expression
        Count input. Each rising edge decrements the counter.
    preset : int, optional
        Starting count value loaded when ``load`` is True.
        Defaults to 0.
    load : bool expression, optional
        Load input. When True, the counter is loaded with ``preset``.
    name : str, optional
        Explicit instance name for the generated counter variable.

    Returns
    -------
    bool
        True when the count reaches zero.

    Examples
    --------
    ::

        if count_down(self.dispense, preset=10, load=self.reload):
            self.magazine_empty = True
    """
    raise RuntimeError("count_down() is a compile-time sentinel — do not call directly")


def count_up_down(
    up_signal: object,
    down_signal: object,
    *,
    preset: int = 0,
    reset: object = None,
    load: object = None,
    name: str | None = None,
) -> bool:
    """Bidirectional counter (CTUD). Increments on rising edges of
    ``up_signal``, decrements on rising edges of ``down_signal``.
    Returns True when the count reaches ``preset``.

    Recognised by the AST compiler and expanded to a ``CTUD``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    up_signal : bool expression
        Count-up input. Each rising edge increments the counter.
    down_signal : bool expression
        Count-down input. Each rising edge decrements the counter.
    preset : int, optional
        Target count value. Output becomes True when the counter
        reaches this value. Defaults to 0.
    reset : bool expression, optional
        Reset input. When True, the counter resets to 0.
    load : bool expression, optional
        Load input. When True, the counter is loaded with ``preset``.
    name : str, optional
        Explicit instance name for the generated counter variable.

    Returns
    -------
    bool
        True when the accumulated count reaches ``preset``.

    Examples
    --------
    ::

        if count_up_down(self.add_part, self.remove_part, preset=50):
            self.bin_full = True
    """
    raise RuntimeError("count_up_down() is a compile-time sentinel — do not call directly")


def set_dominant(set_signal: object, reset_signal: object, *, name: str | None = None) -> bool:
    """Set-dominant bistable (SR). When both ``set_signal`` and
    ``reset_signal`` are True simultaneously, the output is True
    (set dominates).

    Recognised by the AST compiler and expanded to an ``SR``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    set_signal : bool expression
        Set input. True sets the output.
    reset_signal : bool expression
        Reset input. True resets the output (unless set is also True).
    name : str, optional
        Explicit instance name for the generated bistable variable.

    Returns
    -------
    bool
        Latched output state.

    Examples
    --------
    ::

        self.motor_on = set_dominant(self.start, self.stop)
    """
    raise RuntimeError("set_dominant() is a compile-time sentinel — do not call directly")


def reset_dominant(set_signal: object, reset_signal: object, *, name: str | None = None) -> bool:
    """Reset-dominant bistable (RS). When both ``set_signal`` and
    ``reset_signal`` are True simultaneously, the output is False
    (reset dominates).

    Recognised by the AST compiler and expanded to an ``RS``
    ``FBInvocation``. Never called at runtime.

    Parameters
    ----------
    set_signal : bool expression
        Set input. True sets the output.
    reset_signal : bool expression
        Reset input. True resets the output (overrides set).
    name : str, optional
        Explicit instance name for the generated bistable variable.

    Returns
    -------
    bool
        Latched output state.

    Examples
    --------
    ::

        self.motor_on = reset_dominant(self.start, self.stop)
    """
    raise RuntimeError("reset_dominant() is a compile-time sentinel — do not call directly")


# ---------------------------------------------------------------------------
# ASTCompiler — composed from mixins
# ---------------------------------------------------------------------------


class ASTCompiler(_StatementMixin, _ExpressionMixin, _SentinelMixin):
    """Compiles Python AST nodes into Universal IR nodes."""

    def __init__(self, ctx: CompileContext) -> None:
        self.ctx = ctx

    # -----------------------------------------------------------------------
    # Public entry points
    # -----------------------------------------------------------------------

    def compile_statements(self, nodes: list[ast.stmt]) -> list[Statement]:
        """Compile a list of AST statement nodes into IR statements."""
        stmts: list[Statement] = []
        for node in nodes:
            stmts.extend(self._compile_statement(node))
        return stmts

    def compile_body(self, func_def: ast.FunctionDef) -> list[Statement]:
        """Compile a function body into a list of IR statements."""
        return self.compile_statements(func_def.body)

    # -----------------------------------------------------------------------
    # Statement dispatch
    # -----------------------------------------------------------------------

    def _compile_statement(self, node: ast.stmt) -> list[Statement]:
        """Compile a single AST statement node into IR statements."""
        # Check rejected nodes first
        if type(node) in _REJECTED_NODES:
            raise CompileError(_REJECTED_NODES[type(node)], node, self.ctx)

        handler = self._STATEMENT_HANDLERS.get(type(node))
        if handler is None:
            raise CompileError(
                f"Unsupported Python syntax: {type(node).__name__}. PLC logic supports a subset of Python.",
                node,
                self.ctx,
            )
        result = handler(self, node)
        assert not self.ctx.pending_fb_invocations, (
            f"Unflushed pending_fb_invocations after {type(node).__name__}. Handler must call _flush_pending()."
        )
        return result

    # -----------------------------------------------------------------------
    # Expression dispatch
    # -----------------------------------------------------------------------

    def compile_expression(self, node: ast.expr) -> Expression:
        """Compile a single AST expression node into an IR expression."""
        # Check rejected nodes
        if type(node) in _REJECTED_NODES:
            raise CompileError(_REJECTED_NODES[type(node)], node, self.ctx)

        handler = self._EXPRESSION_HANDLERS.get(type(node))
        if handler is None:
            raise CompileError(
                f"Unsupported Python syntax: {type(node).__name__}. PLC logic supports a subset of Python.",
                node,
                self.ctx,
            )
        return handler(self, node)

    # -----------------------------------------------------------------------
    # Shared utilities (used by multiple mixins)
    # -----------------------------------------------------------------------

    def _flush_pending(self) -> list[Statement]:
        """Flush pending FB invocations."""
        pending = list(self.ctx.pending_fb_invocations)
        self.ctx.pending_fb_invocations.clear()
        return pending

    def _compile_expr_and_flush(self, node: ast.expr) -> tuple[Expression, list[Statement]]:
        """Compile an expression and flush any pending FB invocations."""
        expr = self.compile_expression(node)
        pre = self._flush_pending()
        return expr, pre

    def _build_fb_invocation(self, instance_name: str, call_node: ast.Call) -> FBInvocation | None:
        """Build an FBInvocation if *instance_name* is a known static FB instance."""
        if instance_name not in self.ctx.static_var_types:
            return None
        # Only STATIC vars can be FB instances — skip input/output/etc.
        from plx.framework._compiler_core import VarDirection

        if self.ctx.declared_vars.get(instance_name) is not VarDirection.STATIC:
            return None
        type_ref = self.ctx.static_var_types[instance_name]
        fb_type = type_ref if isinstance(type_ref, NamedTypeRef) else None
        inputs = self._compile_call_kwargs(call_node)
        return FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs=inputs,
        )

    def _build_fb_array_invocation(
        self,
        array_name: str,
        index_exprs: list[Expression],
        call_node: ast.Call,
    ) -> FBInvocation | None:
        """Build an FBInvocation for an array-subscripted FB: ``self.timers[i](...)``."""
        if array_name not in self.ctx.static_var_types:
            return None
        # Only STATIC vars can be FB arrays
        from plx.framework._compiler_core import VarDirection

        if self.ctx.declared_vars.get(array_name) is not VarDirection.STATIC:
            return None
        type_ref = self.ctx.static_var_types[array_name]
        if not isinstance(type_ref, ArrayTypeRef):
            return None
        elem = type_ref.element_type
        if not isinstance(elem, NamedTypeRef):
            return None  # Only FB arrays, not primitive arrays
        inputs = self._compile_call_kwargs(call_node)
        return FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name=array_name),
                indices=index_exprs,
            ),
            fb_type=elem,
            inputs=inputs,
        )

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

# Re-export shared definitions so existing imports continue to work.
# Test files and __init__.py import from ._compiler — this keeps them valid.
from ._compiler_core import (  # noqa: F401
    CompileContext,
    CompileError,
    SENTINEL_REGISTRY,
    _BINOP_MAP,
    _BIT_ACCESS_RE,
    _BUILTIN_FUNCS,
    _CMPOP_MAP,
    _PYTHON_BUILTIN_MAP,
    _REJECTED_BINOP_MESSAGES,
    _REJECTED_NODES,
    _TYPE_CONV_RE,
    resolve_annotation,
)

# Import mixins at the top — no late imports needed now that shared
# constants live in _compiler_core.
from ._compiler_sentinels import _SentinelMixin
from ._compiler_expressions import _ExpressionMixin
from ._compiler_statements import _StatementMixin


# ---------------------------------------------------------------------------
# Sentinel functions
# ---------------------------------------------------------------------------
# These exist for IDE autocompletion / linting.  The AST compiler
# recognises them by name and never calls them.

def delayed(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None, name: str | None = None) -> bool:
    """TON (on-delay timer).  Recognised by the AST compiler."""
    raise RuntimeError("delayed() is a compile-time sentinel — do not call directly")


def sustained(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None, name: str | None = None) -> bool:
    """TOF (off-delay timer).  Recognised by the AST compiler."""
    raise RuntimeError("sustained() is a compile-time sentinel — do not call directly")


def pulse(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None, name: str | None = None) -> bool:
    """TP (pulse timer).  Recognised by the AST compiler."""
    raise RuntimeError("pulse() is a compile-time sentinel — do not call directly")


def retentive(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None, name: str | None = None) -> bool:
    """RTO (retentive timer on).  Recognised by the AST compiler."""
    raise RuntimeError("retentive() is a compile-time sentinel — do not call directly")


def rising(signal: object, *, name: str | None = None) -> bool:
    """R_TRIG (rising edge detect).  Recognised by the AST compiler."""
    raise RuntimeError("rising() is a compile-time sentinel — do not call directly")


def falling(signal: object, *, name: str | None = None) -> bool:
    """F_TRIG (falling edge detect).  Recognised by the AST compiler."""
    raise RuntimeError("falling() is a compile-time sentinel — do not call directly")


def count_up(signal: object, *, preset: int = 0, reset: object = None, name: str | None = None) -> bool:
    """CTU (count up).  Recognised by the AST compiler."""
    raise RuntimeError("count_up() is a compile-time sentinel — do not call directly")


def count_down(signal: object, *, preset: int = 0, load: object = None, name: str | None = None) -> bool:
    """CTD (count down).  Recognised by the AST compiler."""
    raise RuntimeError("count_down() is a compile-time sentinel — do not call directly")


def count_up_down(up_signal: object, down_signal: object, *, preset: int = 0, reset: object = None, load: object = None, name: str | None = None) -> bool:
    """CTUD (count up/down).  Recognised by the AST compiler."""
    raise RuntimeError("count_up_down() is a compile-time sentinel — do not call directly")


def set_dominant(set_signal: object, reset_signal: object, *, name: str | None = None) -> bool:
    """SR (set-dominant bistable).  Recognised by the AST compiler."""
    raise RuntimeError("set_dominant() is a compile-time sentinel — do not call directly")


def reset_dominant(set_signal: object, reset_signal: object, *, name: str | None = None) -> bool:
    """RS (reset-dominant bistable).  Recognised by the AST compiler."""
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
                f"Unsupported Python syntax: {type(node).__name__}. "
                f"PLC logic supports a subset of Python.",
                node, self.ctx,
            )
        result = handler(self, node)
        assert not self.ctx.pending_fb_invocations, (
            f"Unflushed pending_fb_invocations after {type(node).__name__}. "
            f"Handler must call _flush_pending()."
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
                f"Unsupported Python syntax: {type(node).__name__}. "
                f"PLC logic supports a subset of Python.",
                node, self.ctx,
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
        type_ref = self.ctx.static_var_types[instance_name]
        fb_type = type_ref.name if isinstance(type_ref, NamedTypeRef) else None
        inputs = self._compile_call_kwargs(call_node)
        return FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs=inputs,
        )

    def _build_fb_array_invocation(
        self, array_name: str, index_exprs: list[Expression], call_node: ast.Call,
    ) -> FBInvocation | None:
        """Build an FBInvocation for an array-subscripted FB: ``self.timers[i](...)``."""
        if array_name not in self.ctx.static_var_types:
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
            fb_type=elem.name,
            inputs=inputs,
        )

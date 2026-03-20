"""Shared IR tree walkers for statements and expressions.

Provides structural traversal of IR trees with callback hooks.
Handles all recursion into compound statement bodies and expression
children — callers only supply what to DO at each node.

Usage::

    from plx.model.walk import walk_project, walk_pou, walk_statements, walk_expressions

    # Collect all FB invocation types in a project
    fb_types: set[str] = set()
    def on_stmt(stmt):
        if isinstance(stmt, FBInvocation) and isinstance(stmt.fb_type, NamedTypeRef):
            fb_types.add(stmt.fb_type.name)
    walk_project(project, on_stmt=on_stmt)

    # Collect all function calls in an expression tree
    calls: list[str] = []
    walk_expressions(expr, on_expr=lambda e: calls.append(e.function_name)
                     if isinstance(e, FunctionCallExpr) else None)
"""

from __future__ import annotations

from typing import Callable

from .expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BitAccessExpr,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    MemberAccessExpr,
    SubstringExpr,
    TypeConversionExpr,
    UnaryExpr,
)
from .statements import (
    Assignment,
    CaseStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    TryCatchStatement,
    WhileStatement,
)

# Type aliases for callbacks
ExprCallback = Callable[[Expression], None]
StmtCallback = Callable[[Statement], None]


# ---------------------------------------------------------------------------
# Expression walking
# ---------------------------------------------------------------------------

def walk_expressions(expr: Expression, on_expr: ExprCallback) -> None:
    """Walk an expression tree depth-first (pre-order), calling *on_expr* for every node.

    Handles all 12 Expression union members.  Leaf nodes (LiteralExpr,
    VariableRef, SystemFlagExpr) are visited but have no children to recurse into.
    """
    on_expr(expr)
    for child in _expr_children(expr):
        walk_expressions(child, on_expr)


def _expr_children(expr: Expression) -> list[Expression]:
    """Return the immediate child expressions of *expr*."""
    if isinstance(expr, BinaryExpr):
        return [expr.left, expr.right]
    if isinstance(expr, UnaryExpr):
        return [expr.operand]
    if isinstance(expr, FunctionCallExpr):
        return [a.value for a in expr.args]
    if isinstance(expr, ArrayAccessExpr):
        return [expr.array, *expr.indices]
    if isinstance(expr, MemberAccessExpr):
        return [expr.struct]
    if isinstance(expr, BitAccessExpr):
        children = [expr.target]
        if not isinstance(expr.bit_index, int):
            children.append(expr.bit_index)
        return children
    if isinstance(expr, TypeConversionExpr):
        return [expr.source]
    if isinstance(expr, DerefExpr):
        return [expr.pointer]
    if isinstance(expr, SubstringExpr):
        children = [expr.string]
        if expr.start is not None:
            children.append(expr.start)
        if expr.end is not None:
            children.append(expr.end)
        return children
    # Leaf nodes: LiteralExpr, VariableRef, SystemFlagExpr
    return []


# ---------------------------------------------------------------------------
# Statement walking
# ---------------------------------------------------------------------------

def walk_statements(
    stmts: list[Statement],
    on_stmt: StmtCallback | None = None,
    on_expr: ExprCallback | None = None,
) -> None:
    """Walk a statement list, recursing into compound bodies.

    Calls *on_stmt(stmt)* for each statement (if provided).
    If *on_expr* is provided, also walks all expressions embedded in each
    statement via :func:`walk_expressions`.
    """
    for stmt in stmts:
        if on_stmt is not None:
            on_stmt(stmt)
        if on_expr is not None:
            for expr in _stmt_expressions(stmt):
                walk_expressions(expr, on_expr)
        for body in _stmt_bodies(stmt):
            walk_statements(body, on_stmt, on_expr)


def _stmt_bodies(stmt: Statement) -> list[list[Statement]]:
    """Return all child statement body lists of *stmt*.

    This is the single source of truth for which statement types
    contain child statement lists.  Adding a new compound statement
    type requires only updating this function.
    """
    if isinstance(stmt, IfStatement):
        bodies = [stmt.if_branch.body]
        for branch in stmt.elsif_branches:
            bodies.append(branch.body)
        if stmt.else_body:
            bodies.append(stmt.else_body)
        return bodies
    if isinstance(stmt, CaseStatement):
        bodies = [b.body for b in stmt.branches]
        if stmt.else_body:
            bodies.append(stmt.else_body)
        return bodies
    if isinstance(stmt, ForStatement):
        return [stmt.body]
    if isinstance(stmt, WhileStatement):
        return [stmt.body]
    if isinstance(stmt, RepeatStatement):
        return [stmt.body]
    if isinstance(stmt, TryCatchStatement):
        bodies = [stmt.try_body]
        if stmt.catch_body:
            bodies.append(stmt.catch_body)
        if stmt.finally_body:
            bodies.append(stmt.finally_body)
        return bodies
    # All other statements are leaf nodes (no child bodies)
    return []


def _stmt_expressions(stmt: Statement) -> list[Expression]:
    """Return all expression fields embedded in *stmt*.

    This is the single source of truth for which statement fields
    contain expressions.  Adding a new statement type with expression
    fields requires only updating this function.

    Note: expressions inside child statement bodies are NOT included —
    those are reached via ``_stmt_bodies`` recursion.
    """
    if isinstance(stmt, Assignment):
        return [stmt.target, stmt.value]
    if isinstance(stmt, IfStatement):
        exprs = [stmt.if_branch.condition]
        for branch in stmt.elsif_branches:
            exprs.append(branch.condition)
        return exprs
    if isinstance(stmt, CaseStatement):
        return [stmt.selector]
    if isinstance(stmt, ForStatement):
        exprs = [stmt.from_expr, stmt.to_expr]
        if stmt.by_expr is not None:
            exprs.append(stmt.by_expr)
        return exprs
    if isinstance(stmt, WhileStatement):
        return [stmt.condition]
    if isinstance(stmt, RepeatStatement):
        return [stmt.until]
    if isinstance(stmt, ReturnStatement):
        if stmt.value is not None:
            return [stmt.value]
        return []
    if isinstance(stmt, FunctionCallStatement):
        return [a.value for a in stmt.args]
    if isinstance(stmt, FBInvocation):
        exprs: list[Expression] = []
        # instance_name can be an expression (ArrayAccessExpr, MemberAccessExpr, BitAccessExpr)
        if not isinstance(stmt.instance_name, str):
            exprs.append(stmt.instance_name)
        exprs.extend(stmt.inputs.values())
        exprs.extend(stmt.outputs.values())
        return exprs
    # Leaf statements: Exit, Continue, Empty, Pragma, Jump, Label
    return []


# ---------------------------------------------------------------------------
# POU and Project walking
# ---------------------------------------------------------------------------

def walk_pou(
    pou: "POU",
    on_stmt: StmtCallback | None = None,
    on_expr: ExprCallback | None = None,
) -> None:
    """Walk all code in a POU: networks, SFC body, methods, actions, properties.

    This is a convenience that ensures no code location in a POU is missed.
    """
    from .pou import POU  # noqa: F811 — deferred to avoid circular import

    # Networks (main body)
    for net in pou.networks:
        walk_statements(net.statements, on_stmt, on_expr)

    # SFC body
    _walk_sfc_body(pou.sfc_body, on_stmt, on_expr)

    # Methods
    for method in pou.methods:
        for net in method.networks:
            walk_statements(net.statements, on_stmt, on_expr)
        _walk_sfc_body(method.sfc_body, on_stmt, on_expr)

    # POU actions
    for action in pou.actions:
        for net in action.body:
            walk_statements(net.statements, on_stmt, on_expr)

    # Properties (getter/setter bodies)
    for prop in pou.properties:
        if prop.getter is not None:
            for net in prop.getter.networks:
                walk_statements(net.statements, on_stmt, on_expr)
        if prop.setter is not None:
            for net in prop.setter.networks:
                walk_statements(net.statements, on_stmt, on_expr)


def walk_project(
    project: "Project",
    on_stmt: StmtCallback | None = None,
    on_expr: ExprCallback | None = None,
) -> None:
    """Walk all POUs in a project."""
    for pou in project.pous:
        walk_pou(pou, on_stmt, on_expr)


def _walk_sfc_body(
    sfc_body: "SFCBody | None",
    on_stmt: StmtCallback | None,
    on_expr: ExprCallback | None,
) -> None:
    """Walk the statements and expressions in an SFC body."""
    if sfc_body is None:
        return
    for step in sfc_body.steps:
        for action_list in (step.actions, step.entry_actions, step.exit_actions):
            for action in action_list:
                walk_statements(action.body, on_stmt, on_expr)
    if on_expr is not None:
        for transition in sfc_body.transitions:
            walk_expressions(transition.condition, on_expr)

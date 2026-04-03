"""Shared detection for the ``def init(self)`` compilation pattern.

The framework compiles ``def init(self)`` into a flattened IR form:

- A ``_plx_initialized`` static var (BOOL, initial FALSE)
- An ``IfStatement`` guard as the first statement of the first network:
  ``IF NOT _plx_initialized THEN <init_body>; _plx_initialized := TRUE; END_IF``

Both the Python exporter (to reconstruct ``def init(self):``) and the
Beckhoff raise pass (to extract into a ``_plx_init`` method) use this
helper to detect and extract the pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

from .expressions import LiteralExpr, UnaryExpr, UnaryOp, VariableRef
from .pou import Network
from .statements import Assignment, IfStatement, Statement
from .types import PrimitiveType, PrimitiveTypeRef
from .variables import Variable

INIT_FLAG_NAME = "_plx_initialized"


@dataclass
class InitPattern:
    """Result of successfully detecting the init pattern."""

    init_body: list[Statement]
    """The init statements (excluding the ``_plx_initialized := TRUE`` assignment)."""

    flag_var: Variable
    """The ``_plx_initialized`` variable to remove from static vars."""

    if_statement: IfStatement
    """The outer IF guard statement (for removal from networks)."""

    network_index: int
    """Index of the network containing the IF guard."""

    stmt_index: int
    """Index of the IF statement within that network."""


def detect_init_pattern(
    static_vars: list[Variable],
    networks: list[Network],
) -> InitPattern | None:
    """Detect the ``def init(self)`` flattened IR pattern.

    Returns an ``InitPattern`` if all parts match, otherwise ``None``.
    """
    # 1. Find _plx_initialized in static vars
    flag_var: Variable | None = None
    for v in static_vars:
        if v.name == INIT_FLAG_NAME:
            if isinstance(v.data_type, PrimitiveTypeRef) and v.data_type.type == PrimitiveType.BOOL:
                flag_var = v
                break

    if flag_var is None:
        return None

    # 2. Find the IF guard as first statement in first non-empty network
    for net_idx, net in enumerate(networks):  # noqa: B007
        if not net.statements:
            continue
        first_stmt = net.statements[0]
        if not isinstance(first_stmt, IfStatement):
            return None  # Must be first statement in first network
        break
    else:
        return None  # No non-empty networks

    if_stmt = first_stmt

    # 3. Validate the IF condition: NOT _plx_initialized
    cond = if_stmt.if_branch.condition
    if not isinstance(cond, UnaryExpr):
        return None
    if cond.op != UnaryOp.NOT:
        return None
    if not isinstance(cond.operand, VariableRef):
        return None
    if cond.operand.name != INIT_FLAG_NAME:
        return None

    # 4. No elsif/else branches
    if if_stmt.elsif_branches or if_stmt.else_body:
        return None

    # 5. Last statement in IF body must be: _plx_initialized := TRUE
    if_body = if_stmt.if_branch.body
    if not if_body:
        return None
    last_stmt = if_body[-1]
    if not isinstance(last_stmt, Assignment):
        return None
    if not isinstance(last_stmt.target, VariableRef):
        return None
    if last_stmt.target.name != INIT_FLAG_NAME:
        return None
    if not isinstance(last_stmt.value, LiteralExpr):
        return None
    if last_stmt.value.value != "TRUE":
        return None

    # Extract init body (everything except the final assignment)
    init_body = if_body[:-1]

    return InitPattern(
        init_body=init_body,
        flag_var=flag_var,
        if_statement=if_stmt,
        network_index=net_idx,
        stmt_index=0,
    )

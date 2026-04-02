"""Structured Text pretty-printer for Universal IR.

Walks Pydantic IR models and emits IEC 61131-3 Structured Text.
"""

from __future__ import annotations

from typing import Union, overload

from plx.model.expressions import Expression
from plx.model.pou import POU
from plx.model.project import Project
from plx.model.statements import Statement

from ._source_map import _build_source_map, _collect_variable_names
from ._writer import STWriter

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@overload
def to_structured_text(target: Union[Project, POU], *, source_map: bool = False) -> str: ...
@overload
def to_structured_text(target: Union[Project, POU], *, source_map: bool = True) -> tuple[str, list[dict]]: ...


def to_structured_text(target: Union[Project, POU], *, source_map: bool = False) -> str | tuple[str, list[dict]]:
    """Emit IEC 61131-3 Structured Text for a Project or single POU.

    When *source_map* is True, returns ``(st_text, var_source_map)`` where
    ``var_source_map`` is a list of ``{"name", "line", "column"}`` dicts
    mapping each variable reference to its 1-indexed position in the ST output.

    Parameters
    ----------
    target : Project or POU
        The compiled IR to render as Structured Text.
    source_map : bool, optional
        If ``True``, return a ``(text, source_map)`` tuple instead of just
        the text string. Default is ``False``.

    Returns
    -------
    str or tuple[str, list[dict]]
        The ST text, or ``(text, var_source_map)`` when *source_map* is True.
    """
    w = STWriter()
    if isinstance(target, Project):
        w.write_project(target)
    elif isinstance(target, POU):
        w.write_pou(target)
    else:
        raise TypeError(f"to_structured_text() expects Project or POU, got {type(target).__name__}")
    st_text = w.getvalue()

    if not source_map:
        return st_text

    var_names = _collect_variable_names(target)
    smap = _build_source_map(st_text, var_names)
    return st_text, smap


def format_statement(stmt: Statement) -> str:
    """Format a single IR statement as Structured Text.

    Parameters
    ----------
    stmt : Statement
        The IR statement node to format.

    Returns
    -------
    str
        The statement rendered as ST, without a trailing newline.
    """
    w = STWriter()
    w._write_stmt(stmt)
    return w.getvalue().rstrip("\n")


def format_expression(expr: Expression) -> str:
    """Format a single IR expression as Structured Text.

    Parameters
    ----------
    expr : Expression
        The IR expression node to format.

    Returns
    -------
    str
        The expression rendered as ST.
    """
    w = STWriter()
    return w._expr(expr)

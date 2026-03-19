"""Mutable traversal state tracked by the visitor for a single POU."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from plx.model.expressions import Expression
from plx.model.pou import POU

from ._results import Finding

if TYPE_CHECKING:
    from ._types import TypeEnvironment


@dataclass
class WriteInfo:
    """Snapshot of context at the point a variable was written."""

    guarded: bool
    nesting_depth: int
    guard_conditions: list[Expression]
    value_is_true: bool | None  # TRUE, FALSE, or unknown
    location: str


@dataclass
class ReadInfo:
    """Snapshot of context at the point a variable was read."""

    location: str
    guarded: bool


@dataclass
class AnalysisContext:
    """Per-POU mutable analysis state."""

    pou: POU
    pou_name: str
    nesting_depth: int = 0
    guard_conditions: list[Expression] = field(default_factory=list)
    writes: dict[str, list[WriteInfo]] = field(default_factory=dict)
    reads: dict[str, list[ReadInfo]] = field(default_factory=dict)
    output_names: set[str] = field(default_factory=set)
    input_names: set[str] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)
    current_network_idx: int = 0
    current_stmt_path: list[str] = field(default_factory=list)
    type_env: TypeEnvironment | None = None
    extra: dict[str, Any] = field(default_factory=dict)

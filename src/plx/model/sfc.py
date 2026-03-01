"""Sequential Function Chart constructs for the Universal IR."""

from __future__ import annotations

from enum import Enum

from pydantic import model_validator

from ._base import IRModel

from .expressions import Expression
from .statements import Statement


class ActionQualifier(str, Enum):
    """IEC 61131-3 action qualifiers."""

    N = "N"       # Non-stored (active while step is active)
    R = "R"       # Reset
    S = "S"       # Set (stored)
    P = "P"       # Pulse (single execution on step entry)
    L = "L"       # Time-limited
    D = "D"       # Time-delayed
    P0 = "P0"     # Pulse on deactivation
    P1 = "P1"     # Pulse on activation
    SD = "SD"     # Stored and time-delayed
    DS = "DS"     # Delayed and stored
    SL = "SL"     # Stored and time-limited


class Action(IRModel):
    name: str
    qualifier: ActionQualifier = ActionQualifier.N
    duration: str | None = None
    body: list[Statement] = []
    action_name: str | None = None  # Reference to a named POUAction

    @model_validator(mode="after")
    def _body_exclusivity(self):
        has_body = bool(self.body)
        has_ref = self.action_name is not None
        if has_body and has_ref:
            raise ValueError(
                "Action must have either inline 'body' or 'action_name' reference, not both"
            )
        return self


class Step(IRModel):
    name: str
    is_initial: bool = False
    actions: list[Action] = []
    entry_actions: list[Action] = []
    exit_actions: list[Action] = []


class Transition(IRModel):
    """An SFC transition.

    Divergence/convergence is encoded by the graph structure:
    - len(target_steps) > 1 → simultaneous divergence
    - len(source_steps) > 1 → simultaneous convergence
    - Multiple transitions sharing a source → selection divergence
    """

    source_steps: list[str]
    target_steps: list[str]
    condition: Expression

    @model_validator(mode="after")
    def _validate_steps(self):
        if not self.source_steps:
            raise ValueError("source_steps must not be empty")
        if not self.target_steps:
            raise ValueError("target_steps must not be empty")
        if len(self.source_steps) != len(set(self.source_steps)):
            raise ValueError("source_steps contains duplicates")
        if len(self.target_steps) != len(set(self.target_steps)):
            raise ValueError("target_steps contains duplicates")
        return self


class SFCBody(IRModel):
    steps: list[Step] = []
    transitions: list[Transition] = []

    @model_validator(mode="after")
    def _validate_initial_step(self):
        if self.steps:
            initial_count = sum(1 for s in self.steps if s.is_initial)
            if initial_count != 1:
                raise ValueError(
                    f"SFCBody must have exactly one initial step when steps exist, "
                    f"found {initial_count}"
                )
        return self

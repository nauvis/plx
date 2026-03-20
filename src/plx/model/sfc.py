"""Sequential Function Chart constructs for the Universal IR."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from ._base import IRModel, validate_iec_identifier

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
    """An action association on an SFC step (inline body or reference to a POUAction).

    Either *body* (inline statements) or *action_name* (reference to a
    named ``POUAction``) may be set, but not both.

    Attributes
    ----------
    qualifier : ActionQualifier
        IEC 61131-3 action qualifier (N, S, R, P, L, D, etc.).
    duration : str or None
        Time duration for timed qualifiers (L, D, SD, DS, SL).
        Format: IEC time literal (e.g. ``"T#5s"``).
    body : list of Statement
        Inline action body (mutually exclusive with *action_name*).
    action_name : str or None
        Name of a ``POUAction`` to reference (mutually exclusive with *body*).
    """

    name: str = Field(min_length=1)
    qualifier: ActionQualifier = ActionQualifier.N
    duration: str | None = None
    body: list[Statement] = []
    action_name: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)

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
    """An SFC step with optional entry, exit, and body actions.

    Attributes
    ----------
    is_initial : bool
        True if this is the initial step (exactly one per SFCBody).
    actions : list of Action
        Actions active while this step is active (N qualifier typical).
    entry_actions : list of Action
        Actions executed once on step activation.
    exit_actions : list of Action
        Actions executed once on step deactivation.
    """

    name: str = Field(min_length=1)
    is_initial: bool = False
    actions: list[Action] = []
    entry_actions: list[Action] = []
    exit_actions: list[Action] = []

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)


class Transition(IRModel):
    """An SFC transition connecting source step(s) to target step(s).

    Divergence/convergence is encoded by the graph structure:

    - ``len(target_steps) > 1`` -- simultaneous divergence
    - ``len(source_steps) > 1`` -- simultaneous convergence
    - Multiple transitions sharing a source -- selection divergence

    Attributes
    ----------
    source_steps : list of str
        Step names this transition originates from.
    target_steps : list of str
        Step names this transition leads to.
    condition : Expression
        Boolean expression that must be True for the transition to fire.
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
    """Sequential Function Chart body — a graph of steps connected by transitions."""

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

    @model_validator(mode="after")
    def _no_duplicate_step_names(self):
        seen: set[str] = set()
        for s in self.steps:
            if s.name in seen:
                raise ValueError(f"Duplicate step name '{s.name}'")
            seen.add(s.name)
        return self

    @model_validator(mode="after")
    def _transition_refs_valid(self):
        if not self.steps or not self.transitions:
            return self
        step_names = {s.name for s in self.steps}
        for t in self.transitions:
            for name in t.source_steps:
                if name not in step_names:
                    raise ValueError(
                        f"Transition references unknown source step '{name}'"
                    )
            for name in t.target_steps:
                if name not in step_names:
                    raise ValueError(
                        f"Transition references unknown target step '{name}'"
                    )
        return self

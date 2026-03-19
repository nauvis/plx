"""Statement AST nodes for the Universal IR."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, model_validator

from ._base import IRModel, _IEC_IDENT_RE

from .expressions import ArrayAccessExpr, BitAccessExpr, CallArg, Expression, MemberAccessExpr
from .types import NamedTypeRef, TypeRef


class Assignment(IRModel):
    """Assign a value to a target: target := value."""

    kind: Literal["assignment"] = "assignment"
    target: Expression
    value: Expression
    ref_assign: bool = False  # True for REF= (reference binding)
    latch: Literal["", "S", "R"] = ""  # "S" for S= (set/latch), "R" for R= (reset/unlatch)
    instruction_hint: str = ""  # Original instruction mnemonic for round-trip fidelity (e.g. "CPT")
    comment: str = ""  # Leading comment lines (preserved from source)


class IfBranch(IRModel):
    """A single IF or ELSIF branch (condition + body)."""

    condition: Expression
    body: list[Statement]


class IfStatement(IRModel):
    """IF / ELSIF / ELSE conditional."""

    kind: Literal["if"] = "if"
    if_branch: IfBranch
    elsif_branches: list[IfBranch] = []
    else_body: list[Statement] = []
    comment: str = ""


class CaseRange(IRModel):
    """An inclusive integer range for a CASE branch (e.g. 20..29)."""

    start: int
    end: int

    @model_validator(mode="after")
    def _bounds_check(self):
        if self.start > self.end:
            raise ValueError(
                f"start ({self.start}) must be <= end ({self.end})"
            )
        return self


class CaseBranch(IRModel):
    """One branch of a CASE statement.

    Matches if the selector equals any value in *values*
    or falls within any range in *ranges*.
    """

    values: list[int | str] = []
    ranges: list[CaseRange] = []
    body: list[Statement] = []

    @model_validator(mode="after")
    def _check_non_empty(self):
        if not self.values and not self.ranges:
            raise ValueError(
                "CaseBranch must have at least one value or range"
            )
        return self


class CaseStatement(IRModel):
    """CASE selector OF ... END_CASE multi-way branch."""

    kind: Literal["case"] = "case"
    selector: Expression
    branches: list[CaseBranch]
    else_body: list[Statement] = []
    comment: str = ""

    @model_validator(mode="after")
    def _non_empty_branches(self):
        if not self.branches and not self.else_body:
            raise ValueError(
                "CaseStatement must have at least one branch or an else body"
            )
        return self


class ForStatement(IRModel):
    """FOR loop_var := from TO to [BY step] DO ... END_FOR."""

    kind: Literal["for"] = "for"
    loop_var: str = Field(min_length=1)
    from_expr: Expression
    to_expr: Expression
    by_expr: Expression | None = None
    body: list[Statement]
    comment: str = ""


class WhileStatement(IRModel):
    """WHILE condition DO ... END_WHILE loop."""

    kind: Literal["while"] = "while"
    condition: Expression
    body: list[Statement]
    comment: str = ""


class RepeatStatement(IRModel):
    """REPEAT ... UNTIL condition END_REPEAT loop."""

    kind: Literal["repeat"] = "repeat"
    body: list[Statement]
    until: Expression
    comment: str = ""


class ExitStatement(IRModel):
    """EXIT — break out of the innermost loop."""

    kind: Literal["exit"] = "exit"
    comment: str = ""


class ContinueStatement(IRModel):
    """CONTINUE — skip to next loop iteration (Beckhoff ExST extension)."""

    kind: Literal["continue"] = "continue"
    comment: str = ""


class ReturnStatement(IRModel):
    """RETURN — early exit from POU/method, optionally with a value (functions)."""

    kind: Literal["return"] = "return"
    value: Expression | None = None
    comment: str = ""


class FunctionCallStatement(IRModel):
    """Call a function as a statement (discarding return value)."""

    kind: Literal["function_call_stmt"] = "function_call_stmt"
    function_name: str = Field(min_length=1)
    args: list[CallArg] = []
    comment: str = ""


class FBInvocation(IRModel):
    """Invoke a function block instance.

    *inputs*: parameter_name → value expression  (the := assignments)
    *outputs*: parameter_name → target expression (the => assignments)
    """

    kind: Literal["fb_invocation"] = "fb_invocation"
    instance_name: str | ArrayAccessExpr | MemberAccessExpr | BitAccessExpr
    fb_type: TypeRef | None = None
    inputs: dict[str, Expression] = {}
    outputs: dict[str, Expression] = {}
    comment: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_fb_type(cls, data: Any) -> Any:
        """Auto-coerce bare string fb_type to NamedTypeRef for backward compat."""
        if isinstance(data, dict):
            val = data.get("fb_type")
            if isinstance(val, str):
                data = dict(data)
                data["fb_type"] = {"kind": "named", "name": val}
        return data

    @model_validator(mode="after")
    def _validate_instance_name(self) -> "FBInvocation":
        if isinstance(self.instance_name, str):
            if not self.instance_name:
                raise ValueError("FBInvocation.instance_name must not be empty")
            # Allow dotted paths (e.g. "parent.child.Method") and caret
            # deref (e.g. "SUPER^") — each segment must be a valid identifier
            clean = self.instance_name.replace("^", "")
            for segment in clean.split("."):
                if segment and not _IEC_IDENT_RE.match(segment):
                    raise ValueError(
                        f"FBInvocation.instance_name '{self.instance_name}' "
                        f"contains invalid segment '{segment}'"
                    )
        return self


class EmptyStatement(IRModel):
    """Placeholder statement (`;`) — preserves empty branches and comment-only lines."""

    kind: Literal["empty"] = "empty"
    comment: str = ""


class PragmaStatement(IRModel):
    """A pragma directive preserved as opaque text (e.g. conditional compilation)."""

    kind: Literal["pragma"] = "pragma"
    text: str
    comment: str = ""


class TryCatchStatement(IRModel):
    """Beckhoff TwinCAT exception handling: __TRY / __CATCH / __FINALLY / __ENDTRY."""

    kind: Literal["try_catch"] = "try_catch"
    try_body: list["Statement"]
    catch_var: str | None = None  # Exception variable in __CATCH(exc)
    catch_body: list["Statement"] = []
    finally_body: list["Statement"] = []
    comment: str = ""


class JumpStatement(IRModel):
    """Unconditional jump to a label: JMP label;"""

    kind: Literal["jump"] = "jump"
    label: str = Field(min_length=1)
    comment: str = ""


class LabelStatement(IRModel):
    """A label target: label:"""

    kind: Literal["label"] = "label"
    name: str = Field(min_length=1)
    comment: str = ""


Statement = Annotated[
    Union[
        Assignment,
        IfStatement,
        CaseStatement,
        ForStatement,
        WhileStatement,
        RepeatStatement,
        ExitStatement,
        ContinueStatement,
        ReturnStatement,
        FunctionCallStatement,
        FBInvocation,
        EmptyStatement,
        PragmaStatement,
        TryCatchStatement,
        JumpStatement,
        LabelStatement,
    ],
    Field(discriminator="kind"),
]

# Rebuild models with recursive Statement references.
IfBranch.model_rebuild()
IfStatement.model_rebuild()
CaseBranch.model_rebuild()
CaseStatement.model_rebuild()
ForStatement.model_rebuild()
WhileStatement.model_rebuild()
RepeatStatement.model_rebuild()
ReturnStatement.model_rebuild()
FunctionCallStatement.model_rebuild()
FBInvocation.model_rebuild()
PragmaStatement.model_rebuild()
TryCatchStatement.model_rebuild()
JumpStatement.model_rebuild()
LabelStatement.model_rebuild()

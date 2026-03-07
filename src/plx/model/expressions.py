"""Expression AST nodes for the Universal IR."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import Field

from ._base import IRModel

from .types import TypeRef


class SystemFlag(str, Enum):
    FIRST_SCAN = "first_scan"


class SystemFlagExpr(IRModel):
    """Reference to a system-level PLC flag (e.g. first scan)."""

    kind: Literal["system_flag"] = "system_flag"
    flag: SystemFlag


class BinaryOp(str, Enum):
    ADD = "ADD"
    SUB = "SUB"
    MUL = "MUL"
    DIV = "DIV"
    MOD = "MOD"
    AND = "AND"
    OR = "OR"
    XOR = "XOR"
    BAND = "BAND"  # Bitwise AND (from Python &)
    BOR = "BOR"    # Bitwise OR (from Python |)
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"
    SHL = "SHL"
    SHR = "SHR"
    ROL = "ROL"
    ROR = "ROR"
    EXPT = "EXPT"
    AND_THEN = "AND_THEN"  # Short-circuit AND (Beckhoff ExST extension)
    OR_ELSE = "OR_ELSE"    # Short-circuit OR (Beckhoff ExST extension)


class UnaryOp(str, Enum):
    NEG = "NEG"
    NOT = "NOT"
    BNOT = "BNOT"  # Bitwise NOT / complement (from Python ~)


class LiteralExpr(IRModel):
    """A typed constant value (e.g. TRUE, 42, 3.14, T#5s)."""

    kind: Literal["literal"] = "literal"
    value: str
    data_type: TypeRef | None = None


class VariableRef(IRModel):
    """Reference to a variable by name."""

    kind: Literal["variable_ref"] = "variable_ref"
    name: str = Field(min_length=1)


class BinaryExpr(IRModel):
    kind: Literal["binary"] = "binary"
    op: BinaryOp
    left: Expression
    right: Expression


class UnaryExpr(IRModel):
    kind: Literal["unary"] = "unary"
    op: UnaryOp
    operand: Expression


class CallArg(IRModel):
    """A single argument in a function/FB call.

    Positional if *name* is None, named otherwise.
    """

    name: str | None = None
    value: Expression


class FunctionCallExpr(IRModel):
    """Inline function call that returns a value."""

    kind: Literal["function_call"] = "function_call"
    function_name: str = Field(min_length=1)
    args: list[CallArg] = []


class ArrayAccessExpr(IRModel):
    """Array subscript: arr[i] or arr[i, j]."""

    kind: Literal["array_access"] = "array_access"
    array: Expression
    indices: list[Expression]


class MemberAccessExpr(IRModel):
    """Struct/FB member access: expr.member."""

    kind: Literal["member_access"] = "member_access"
    struct: Expression
    member: str = Field(min_length=1)


class BitAccessExpr(IRModel):
    """Bit-level access on an integer/word variable: var.bit5."""

    kind: Literal["bit_access"] = "bit_access"
    target: Expression
    bit_index: int = Field(ge=0)


class TypeConversionExpr(IRModel):
    """Explicit type conversion: INT_TO_REAL(x)."""

    kind: Literal["type_conversion"] = "type_conversion"
    target_type: TypeRef
    source: Expression
    source_type: TypeRef | None = None


Expression = Annotated[
    Union[
        LiteralExpr,
        VariableRef,
        BinaryExpr,
        UnaryExpr,
        FunctionCallExpr,
        ArrayAccessExpr,
        MemberAccessExpr,
        BitAccessExpr,
        TypeConversionExpr,
        SystemFlagExpr,
    ],
    Field(discriminator="kind"),
]

# Rebuild models with recursive Expression references.
BinaryExpr.model_rebuild()
UnaryExpr.model_rebuild()
CallArg.model_rebuild()
FunctionCallExpr.model_rebuild()
ArrayAccessExpr.model_rebuild()
MemberAccessExpr.model_rebuild()
BitAccessExpr.model_rebuild()
TypeConversionExpr.model_rebuild()
SystemFlagExpr.model_rebuild()

"""Expression AST nodes for the Universal IR."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Self, Union

from pydantic import Field, model_validator

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
    """Bit-level access on an integer/word variable.

    Static: ``var.5`` (bit_index is int).
    Dynamic: ``var.[idx]`` (bit_index is Expression — AB syntax).
    """

    kind: Literal["bit_access"] = "bit_access"
    target: Expression
    bit_index: int | Expression

    @model_validator(mode="after")
    def _validate_bit_index(self) -> Self:
        if isinstance(self.bit_index, int) and self.bit_index < 0:
            raise ValueError("bit_index must be >= 0 for static bit access")
        return self


class TypeConversionExpr(IRModel):
    """Explicit type conversion: INT_TO_REAL(x)."""

    kind: Literal["type_conversion"] = "type_conversion"
    target_type: TypeRef
    source: Expression
    source_type: TypeRef | None = None


class DerefExpr(IRModel):
    """Pointer dereference: ptr^ in ST."""

    kind: Literal["deref"] = "deref"
    pointer: Expression


class SubstringExpr(IRModel):
    """String substring extraction (0-based, half-open interval).

    Models Python-style string slicing: ``s[start:end]``.
    Exporters emit the appropriate vendor function (LEFT, RIGHT, MID).

    - ``start`` only  → ``s[n:]``  (RIGHT)
    - ``end`` only    → ``s[:n]``  (LEFT)
    - both            → ``s[i:j]`` (MID)
    - neither         → ``s[:]``   (identity — should be optimized away)

    When ``single_char`` is True, represents ``s[i]`` (single character
    access) rather than ``s[i:i+1]``.  ``start`` holds the index and
    ``end`` is unused.
    """

    kind: Literal["substring"] = "substring"
    string: Expression
    start: Expression | None = None
    end: Expression | None = None
    single_char: bool = False


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
        DerefExpr,
        SubstringExpr,
        SystemFlagExpr,
    ],
    Field(discriminator="kind"),
]

# ---------------------------------------------------------------------------
# Rebuild all models that use recursive Expression or TypeRef references.
#
# DimensionRange (in types.py) uses ``int | Expression`` for bounds, so
# types.py cannot call model_rebuild() at module level — Expression isn't
# defined yet.  We rebuild everything here where both TypeRef and
# Expression are available.
# ---------------------------------------------------------------------------

# Expression models (recursive Expression references)
BinaryExpr.model_rebuild()
UnaryExpr.model_rebuild()
CallArg.model_rebuild()
FunctionCallExpr.model_rebuild()
ArrayAccessExpr.model_rebuild()
MemberAccessExpr.model_rebuild()
BitAccessExpr.model_rebuild()
TypeConversionExpr.model_rebuild()
DerefExpr.model_rebuild()
SubstringExpr.model_rebuild()
SystemFlagExpr.model_rebuild()

# Type models (recursive TypeRef + Expression in DimensionRange)
from .types import (
    AliasType,
    ArrayTypeRef,
    DimensionRange,
    PointerTypeRef,
    ReferenceTypeRef,
    StructMember,
)

DimensionRange.model_rebuild()
ArrayTypeRef.model_rebuild()
PointerTypeRef.model_rebuild()
ReferenceTypeRef.model_rebuild()
StructMember.model_rebuild()
AliasType.model_rebuild()

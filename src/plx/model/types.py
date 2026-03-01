"""Type system for the Universal IR.

Two distinct concepts:
- TypeRef: used wherever a type is *referenced* (variable declarations,
  expression annotations, array element types, function return types).
- TypeDefinition: a named type *definition* that lives in the project's
  type registry (project.data_types).

These are separate discriminated unions. TypeRef never contains a
TypeDefinition — named types are referenced by name via NamedTypeRef.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from ._base import IRModel


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class PrimitiveType(str, Enum):
    """IEC 61131-3 elementary types."""

    # Boolean
    BOOL = "BOOL"

    # Bit-string
    BYTE = "BYTE"
    WORD = "WORD"
    DWORD = "DWORD"
    LWORD = "LWORD"

    # Signed integer
    SINT = "SINT"
    INT = "INT"
    DINT = "DINT"
    LINT = "LINT"

    # Unsigned integer
    USINT = "USINT"
    UINT = "UINT"
    UDINT = "UDINT"
    ULINT = "ULINT"

    # Floating point
    REAL = "REAL"
    LREAL = "LREAL"

    # Duration
    TIME = "TIME"
    LTIME = "LTIME"

    # Date and time
    DATE = "DATE"
    LDATE = "LDATE"
    TOD = "TOD"
    LTOD = "LTOD"
    DT = "DT"
    LDT = "LDT"

    # Character
    CHAR = "CHAR"
    WCHAR = "WCHAR"


# ---------------------------------------------------------------------------
# Type References (used in variable decls, expressions, return types, etc.)
# ---------------------------------------------------------------------------

class PrimitiveTypeRef(IRModel):
    """Reference to a primitive type (BOOL, INT, REAL, etc.)."""

    kind: Literal["primitive"] = "primitive"
    type: PrimitiveType


class StringTypeRef(IRModel):
    """STRING or WSTRING with optional max length."""

    kind: Literal["string"] = "string"
    wide: bool = False
    max_length: int | None = None


class NamedTypeRef(IRModel):
    """Reference to a named type (UDT, FB type, system type, etc.)."""

    kind: Literal["named"] = "named"
    name: str


class DimensionRange(IRModel):
    """Array dimension bounds (inclusive)."""

    lower: int = 0
    upper: int

    @model_validator(mode="after")
    def _bounds_check(self):
        if self.lower > self.upper:
            raise ValueError(
                f"lower ({self.lower}) must be <= upper ({self.upper})"
            )
        return self


class ArrayTypeRef(IRModel):
    """Inline array type: ARRAY[lo..hi, lo..hi] OF element_type."""

    kind: Literal["array"] = "array"
    element_type: TypeRef
    dimensions: list[DimensionRange]


class PointerTypeRef(IRModel):
    """POINTER TO target_type."""

    kind: Literal["pointer"] = "pointer"
    target_type: TypeRef


class ReferenceTypeRef(IRModel):
    """REFERENCE TO target_type."""

    kind: Literal["reference"] = "reference"
    target_type: TypeRef


TypeRef = Annotated[
    Union[
        PrimitiveTypeRef,
        StringTypeRef,
        NamedTypeRef,
        ArrayTypeRef,
        PointerTypeRef,
        ReferenceTypeRef,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Type Definitions (live in project.data_types)
# ---------------------------------------------------------------------------

class StructMember(IRModel):
    """Member of a struct or union."""

    name: str
    data_type: TypeRef
    initial_value: str | None = None
    description: str = ""


class StructType(IRModel):
    """Named struct type definition.

    ``folder`` is a forward-slash-delimited organizational path
    (e.g. ``"Utilities/Motors"``).  Empty string means root / no folder.
    Maps to Beckhoff folder tree, Siemens project navigator folders,
    AB program containers.  Vendor raise passes map to their native model.
    """

    kind: Literal["struct"] = "struct"
    name: str
    folder: str = ""
    extends: str | None = None
    members: list[StructMember]


class EnumMember(IRModel):
    """Member of an enum type."""

    name: str
    value: int | None = None


class EnumType(IRModel):
    """Named enum type definition.

    ``folder``: see ``StructType`` for convention.
    """

    kind: Literal["enum"] = "enum"
    name: str
    folder: str = ""
    members: list[EnumMember]
    base_type: PrimitiveType | None = None


class UnionType(IRModel):
    """Named union type definition.

    ``folder``: see ``StructType`` for convention.
    """

    kind: Literal["union"] = "union"
    name: str
    folder: str = ""
    members: list[StructMember]


class AliasType(IRModel):
    """Type alias (typedef): TYPE MyAlias : base_type; END_TYPE.

    ``folder``: see ``StructType`` for convention.
    """

    kind: Literal["alias"] = "alias"
    name: str
    folder: str = ""
    base_type: TypeRef


class SubrangeType(IRModel):
    """Constrained numeric subrange: TYPE Pct : INT(0..100); END_TYPE.

    ``folder``: see ``StructType`` for convention.
    """

    kind: Literal["subrange"] = "subrange"
    name: str
    folder: str = ""
    base_type: PrimitiveType
    lower_bound: int
    upper_bound: int

    @model_validator(mode="after")
    def _bounds_check(self):
        if self.lower_bound > self.upper_bound:
            raise ValueError(
                f"lower_bound ({self.lower_bound}) must be "
                f"<= upper_bound ({self.upper_bound})"
            )
        return self


TypeDefinition = Annotated[
    Union[StructType, EnumType, UnionType, AliasType, SubrangeType],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Rebuild models with recursive TypeRef references
# ---------------------------------------------------------------------------

ArrayTypeRef.model_rebuild()
PointerTypeRef.model_rebuild()
ReferenceTypeRef.model_rebuild()
StructMember.model_rebuild()
AliasType.model_rebuild()

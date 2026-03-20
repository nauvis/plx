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

from pydantic import Field, field_validator, model_validator

from ._base import IRModel, validate_iec_identifier


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
    """STRING or WSTRING with optional max length.

    Attributes
    ----------
    wide : bool
        True for ``WSTRING`` (UTF-16), False for ``STRING`` (single-byte).
    max_length : int or None
        Maximum character count (e.g. ``STRING(80)``).  None uses the
        vendor default (typically 80 for Beckhoff, 82 for AB).
    """

    kind: Literal["string"] = "string"
    wide: bool = False
    max_length: int | None = None

    @model_validator(mode="after")
    def _positive_max_length(self):
        if self.max_length is not None and self.max_length < 0:
            raise ValueError(
                f"max_length must be >= 0, got {self.max_length}"
            )
        return self


class NamedTypeRef(IRModel):
    """Reference to a named type (UDT, FB type, system type, etc.)."""

    kind: Literal["named"] = "named"
    name: str = Field(min_length=1)


class DimensionRange(IRModel):
    """Array dimension bounds (inclusive).

    Bounds can be integer literals or Expression nodes (for symbolic
    bounds like ``GVL_Params.MAX_SIZE``).  When bounds are expressions,
    numeric validation is skipped.

    Attributes
    ----------
    lower : int or Expression
        Lower bound (inclusive).  Defaults to 0.
    upper : int or Expression
        Upper bound (inclusive).  A value of ``-1`` is a sentinel for
        variable-length arrays (``ARRAY[*] OF T``).
    """

    lower: int | Expression = 0
    upper: int | Expression

    @model_validator(mode="after")
    def _bounds_check(self):
        # Only validate when both bounds are integers
        if isinstance(self.lower, int) and isinstance(self.upper, int):
            # upper == -1 is a sentinel for variable-length arrays (ARRAY[*] OF T)
            if self.upper != -1 and self.lower > self.upper:
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
    """``POINTER TO target_type`` -- Beckhoff-only raw pointer.

    Dereference via ``DerefExpr`` (``ptr^`` in ST).  Dynamic allocation
    uses ``__NEW`` / ``__DELETE``.
    """

    kind: Literal["pointer"] = "pointer"
    target_type: TypeRef


class ReferenceTypeRef(IRModel):
    """``REFERENCE TO target_type`` -- safe reference (no arithmetic).

    Bound via ``REF=`` assignment (``Assignment(ref_assign=True)``).
    Semantically similar to a pointer but cannot be incremented or
    compared as an integer.
    """

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

    name: str = Field(min_length=1)
    data_type: TypeRef
    initial_value: str | None = None
    description: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)


class StructType(IRModel):
    """Named struct type definition.

    ``folder`` is a forward-slash-delimited organizational path
    (e.g. ``"Utilities/Motors"``).  Empty string means root / no folder.
    Maps to Beckhoff folder tree, Siemens project navigator folders,
    AB program containers.  Vendor raise passes map to their native model.

    Attributes
    ----------
    folder : str
        Organizational path (forward-slash-delimited).
    extends : str or None
        Parent struct name for inheritance (Beckhoff ``EXTENDS``).
    members : list of StructMember
        Ordered member definitions (unique names validated).
    """

    kind: Literal["struct"] = "struct"
    name: str = Field(min_length=1)
    folder: str = ""
    extends: str | None = None
    members: list[StructMember]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)

    @model_validator(mode="after")
    def _no_duplicate_member_names(self):
        seen: set[str] = set()
        for m in self.members:
            if m.name in seen:
                raise ValueError(
                    f"Duplicate member name '{m.name}' in struct '{self.name}'"
                )
            seen.add(m.name)
        return self


class EnumMember(IRModel):
    """Member of an enum type.

    Attributes
    ----------
    value : int or str or None
        Explicit integer value, string expression, or None for auto-assigned.
    """

    name: str = Field(min_length=1)
    value: int | str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)


class EnumType(IRModel):
    """Named enum type definition.

    ``folder``: see ``StructType`` for convention.

    Attributes
    ----------
    members : list of EnumMember
        Enum members with optional explicit integer values.
    base_type : PrimitiveType or None
        Underlying integer type (e.g. ``DINT``).  None uses vendor default.
    """

    kind: Literal["enum"] = "enum"
    name: str = Field(min_length=1)
    folder: str = ""
    members: list[EnumMember]
    base_type: PrimitiveType | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)

    @model_validator(mode="after")
    def _no_duplicate_member_names(self):
        seen: set[str] = set()
        for m in self.members:
            if m.name in seen:
                raise ValueError(
                    f"Duplicate member name '{m.name}' in enum '{self.name}'"
                )
            seen.add(m.name)
        return self


class UnionType(IRModel):
    """Named union type definition (all members share the same memory).

    Rarely used in practice.  Exists in the IR for round-trip fidelity
    with Beckhoff projects.  ``folder``: see ``StructType`` for convention.

    Attributes
    ----------
    members : list of StructMember
        Overlapping members (all occupy the same address).
    """

    kind: Literal["union"] = "union"
    name: str = Field(min_length=1)
    folder: str = ""
    members: list[StructMember]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)

    @model_validator(mode="after")
    def _no_duplicate_member_names(self):
        seen: set[str] = set()
        for m in self.members:
            if m.name in seen:
                raise ValueError(
                    f"Duplicate member name '{m.name}' in union '{self.name}'"
                )
            seen.add(m.name)
        return self


class AliasType(IRModel):
    """Type alias (typedef): ``TYPE MyAlias : base_type; END_TYPE``.

    Rarely used in practice.  Exists in the IR for round-trip fidelity.
    ``folder``: see ``StructType`` for convention.

    Attributes
    ----------
    base_type : TypeRef
        The type that this alias refers to.
    """

    kind: Literal["alias"] = "alias"
    name: str = Field(min_length=1)
    folder: str = ""
    base_type: TypeRef

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)


class SubrangeType(IRModel):
    """Constrained numeric subrange: ``TYPE Pct : INT(0..100); END_TYPE``.

    Rarely used in practice.  Exists in the IR for round-trip fidelity.
    ``folder``: see ``StructType`` for convention.

    Attributes
    ----------
    base_type : PrimitiveType
        The underlying integer type being constrained.
    lower_bound : int
        Minimum allowed value (inclusive).
    upper_bound : int
        Maximum allowed value (inclusive).
    """

    kind: Literal["subrange"] = "subrange"
    name: str = Field(min_length=1)
    folder: str = ""
    base_type: PrimitiveType
    lower_bound: int
    upper_bound: int

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)

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
# DimensionRange uses ``int | Expression`` for bounds. Expression is defined
# in expressions.py, which imports from this module.  All model_rebuild()
# calls are therefore deferred to the bottom of expressions.py where both
# TypeRef and Expression are available.
# ---------------------------------------------------------------------------

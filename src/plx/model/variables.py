"""Variable definitions for the Universal IR.

Variables carry no scope or direction information — that is encoded
structurally by which list a Variable appears in (e.g.
POUInterface.input_vars vs .static_vars, or GlobalVariableList.variables).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from ._base import IRModel, validate_iec_identifier

from .types import TypeRef


class Variable(IRModel):
    """A named, typed data element."""

    name: str = Field(min_length=1)
    data_type: TypeRef
    initial_value: str | None = None
    description: str = ""
    constant: bool = False
    retain: bool = False
    persistent: bool = False
    edge: Literal["", "rising", "falling"] = ""
    metadata: dict[str, Any] = {}

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_iec_identifier(v)

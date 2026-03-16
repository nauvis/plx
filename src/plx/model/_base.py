"""Base model for all Universal IR Pydantic models."""

import re

from pydantic import BaseModel, ConfigDict

_IEC_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_iec_identifier(name: str) -> str:
    if not _IEC_IDENT_RE.match(name):
        raise ValueError(
            f"'{name}' is not a valid IEC 61131-3 identifier "
            f"(must match [A-Za-z_][A-Za-z0-9_]*)"
        )
    return name


class IRModel(BaseModel):
    """Base class for all IR models. Forbids extra fields at construction."""

    model_config = ConfigDict(extra="forbid")

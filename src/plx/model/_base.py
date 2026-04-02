"""Base model for all Universal IR Pydantic models."""

import re

from pydantic import BaseModel, ConfigDict

_IEC_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_iec_identifier(name: str) -> str:
    """Validate that *name* is a legal IEC 61131-3 identifier.

    Must start with a letter or underscore and contain only letters,
    digits, and underscores (``[A-Za-z_][A-Za-z0-9_]*``).

    Parameters
    ----------
    name : str
        The identifier string to validate.

    Returns
    -------
    str
        The validated *name*, unchanged.

    Raises
    ------
    ValueError
        If *name* does not match the IEC 61131-3 identifier pattern.
    """
    if not _IEC_IDENT_RE.match(name):
        raise ValueError(f"'{name}' is not a valid IEC 61131-3 identifier (must match [A-Za-z_][A-Za-z0-9_]*)")
    return name


class IRModel(BaseModel):
    """Base class for all IR models. Forbids extra fields at construction."""

    model_config = ConfigDict(extra="forbid")

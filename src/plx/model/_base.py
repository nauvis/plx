"""Base model for all Universal IR Pydantic models."""

from pydantic import BaseModel, ConfigDict


class IRModel(BaseModel):
    """Base class for all IR models. Forbids extra fields at construction."""

    model_config = ConfigDict(extra="forbid")

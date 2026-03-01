"""Ladder Diagram element models (display only).

Pydantic models representing LD visual elements — contacts, coils, boxes,
and structural combinators (series/parallel).  These form the output of
the IR → LD transformation and serve as the input to SVG rendering in the
web IDE.

These models are intentionally simpler than vendor-native LD formats (which
include layout coordinates, connection UIDs, execution order, etc.).  They
should not be reused for vendor code generation.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ContactType(str, Enum):
    """Contact variants in ladder logic."""
    NO = "NO"          # Normally Open
    NC = "NC"          # Normally Closed
    P = "P"            # Positive-edge detect
    N = "N"            # Negative-edge detect


class CoilType(str, Enum):
    """Coil variants in ladder logic."""
    NORMAL = "NORMAL"
    NEGATED = "NEGATED"
    SET = "SET"        # Latch
    RESET = "RESET"    # Unlatch


# ---------------------------------------------------------------------------
# Pin model (for Box inputs/outputs)
# ---------------------------------------------------------------------------

class Pin(BaseModel):
    """A labeled input or output pin on a box element."""
    name: str
    expression: str  # ST text for the connected expression


# ---------------------------------------------------------------------------
# Leaf elements
# ---------------------------------------------------------------------------

class Contact(BaseModel):
    """Reads a boolean variable (NO, NC, P, or N contact)."""
    kind: Literal["contact"] = "contact"
    variable: str
    contact_type: ContactType = ContactType.NO


class Coil(BaseModel):
    """Writes a boolean variable."""
    kind: Literal["coil"] = "coil"
    variable: str
    coil_type: CoilType = CoilType.NORMAL


class Box(BaseModel):
    """Function block instance or function call box."""
    kind: Literal["box"] = "box"
    name: str
    type_name: str
    input_pins: list[Pin] = []
    output_pins: list[Pin] = []
    en_input: LDElement | None = None


class STBox(BaseModel):
    """Inline Structured Text for constructs that don't map to LD."""
    kind: Literal["st_box"] = "st_box"
    st_text: str


# ---------------------------------------------------------------------------
# Structural combinators
# ---------------------------------------------------------------------------

class Series(BaseModel):
    """AND — elements in sequence (left power rail → right)."""
    kind: Literal["series"] = "series"
    elements: list[LDElement]


class Parallel(BaseModel):
    """OR — elements in parallel branches."""
    kind: Literal["parallel"] = "parallel"
    branches: list[LDElement]


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

LDElement = Annotated[
    Union[Contact, Coil, Box, STBox, Series, Parallel],
    Field(discriminator="kind"),
]

# Rebuild models with recursive LDElement references.
Box.model_rebuild()
Series.model_rebuild()
Parallel.model_rebuild()


# ---------------------------------------------------------------------------
# Top-level containers
# ---------------------------------------------------------------------------

class Rung(BaseModel):
    """A single ladder rung: optional input circuit driving output elements."""
    input_circuit: LDElement | None = None
    outputs: list[LDElement] = []


class LDNetwork(BaseModel):
    """A complete ladder diagram — an ordered collection of rungs."""
    rungs: list[Rung] = []

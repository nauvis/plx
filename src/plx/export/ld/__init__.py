"""Ladder Diagram export — IR → LD element tree for **display purposes only**.

This module produces a simplified LD representation suitable for visual
rendering in the web IDE.  It is NOT the same as vendor-native LD and must
not be used as the basis for generating vendor project files.

Key differences from vendor LD:

- **No layout metadata** — vendor formats (Beckhoff TcPOU, Siemens SimaticML)
  store X/Y coordinates, connection UIDs, wire routing, and execution-order
  IDs.  This model has none of that.
- **STBox fallback** — constructs that don't map cleanly to LD elements are
  rendered as inline ST text boxes.  Vendor LD has no such escape hatch.
- **Heuristic mapping** — uses ``_is_boolean_expr()`` to decide contacts vs
  boxes.  Vendor raise passes must make exact, type-aware decisions.

Vendor-native LD should be built in each vendor's ``raise_/`` module,
producing vendor IR models directly from the Universal IR.

Public API::

    from plx.export.ld import ir_to_ld, LDNetwork, Rung, Contact, Coil, ...
"""

from ._model import (
    Box,
    Coil,
    CoilType,
    Contact,
    ContactType,
    LDElement,
    LDNetwork,
    Parallel,
    Pin,
    Rung,
    Series,
    STBox,
)
from ._transform import ir_to_ld

__all__ = [
    "ir_to_ld",
    "Box",
    "Coil",
    "CoilType",
    "Contact",
    "ContactType",
    "LDElement",
    "LDNetwork",
    "Parallel",
    "Pin",
    "Rung",
    "STBox",
    "Series",
]

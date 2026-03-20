"""Hardware configuration base models.

Defines the universal envelope and IO channel model that all
vendor-specific hardware configs inherit from.  The base class
handles YAML serialization and IO point extraction; vendor
subclasses define topology structure and mapping mechanisms.
"""

from __future__ import annotations

from abc import abstractmethod
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChannelDirection(str, Enum):
    """Whether an IO channel is a physical input or output."""

    INPUT = "input"
    OUTPUT = "output"


class IOChannel(BaseModel):
    """Universal IO point at the leaf of any vendor's topology.

    Every vendor's config bottoms out at channels -- the individual
    signals that PLC logic reads/writes.  This model captures the
    minimal info needed for IO address validation.

    Attributes
    ----------
    type : str
        Data type name (``"BOOL"``, ``"INT"``, ``"REAL"``, etc.).
    direction : ChannelDirection
        Whether this channel is a physical INPUT or OUTPUT.
    address : str
        IEC address (``"%IX0.0"``) or AB tag path (``"Local:1:I.Data.0"``).
        Empty when address is assigned dynamically.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    direction: ChannelDirection
    address: str = ""
    description: str = ""


class ControllerConfig(BaseModel):
    """Controller identity -- universal across vendors.

    Attributes
    ----------
    model : str
        Catalog or order number (e.g. ``"1756-L83E"``, ``"CX5130"``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    model: str = ""
    description: str = ""


class HardwareConfig(BaseModel):
    """Base class for vendor-specific hardware configurations.

    Shared envelope:

    - ``plx_version`` -- config schema version
    - ``vendor`` -- which vendor this config targets
    - ``controller`` -- PLC identity

    Subclasses add vendor-specific ``io`` and ``mappings`` sections
    and implement ``extract_io_channels()`` to flatten their topology
    into a list of ``IOChannel`` for address validation.

    Attributes
    ----------
    plx_version : str
        Config schema version (for forward compatibility).
    vendor : {"beckhoff", "ab", "siemens"}
        Target vendor identifier.
    controller : ControllerConfig
        PLC identity (name, catalog number).
    """

    model_config = ConfigDict(extra="forbid")

    plx_version: str = "1.0"
    vendor: Literal["beckhoff", "ab", "siemens"]
    controller: ControllerConfig

    @abstractmethod
    def extract_io_channels(self) -> list[IOChannel]:
        """Flatten vendor-specific topology into universal IO channels.

        Used by the framework to validate that IO addresses referenced
        in logic (``AT %IX0.0``, ``Local:1:I.Data.0``, etc.) actually
        exist in the hardware configuration.
        """
        ...

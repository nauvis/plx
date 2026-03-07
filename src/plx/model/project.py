"""Top-level Project container for the Universal IR."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ._base import IRModel

from .hardware import Controller
from .pou import POU
from .task import Task
from .types import TypeDefinition
from .variables import Variable


class GlobalVariableList(IRModel):
    """A named group of global variables.

    Maps to Beckhoff GVLs, Siemens tag tables, AB controller/program
    scoped tag collections.

    ``folder`` is a forward-slash-delimited organizational path
    (e.g. ``"Utilities/Motors"``).  Empty string means root / no folder.
    Maps to Beckhoff folder tree, Siemens project navigator folders,
    AB program containers.  Vendor raise passes map to their native model.
    """

    name: str = Field(min_length=1)
    folder: str = ""
    scope: Literal["", "controller", "program"] = ""
    description: str = ""
    qualified_only: bool = False
    variables: list[Variable] = []
    metadata: dict[str, Any] = {}


class LibraryReference(IRModel):
    """A reference to an external library dependency."""

    name: str = Field(min_length=1)
    version: str | None = None
    vendor: str | None = None


class Project(IRModel):
    name: str = Field(min_length=1)
    description: str = ""
    controller: Controller | None = None
    data_types: list[TypeDefinition] = []
    global_variable_lists: list[GlobalVariableList] = []
    pous: list[POU] = []
    tasks: list[Task] = []
    libraries: list[LibraryReference] = []
    metadata: dict[str, Any] = {}

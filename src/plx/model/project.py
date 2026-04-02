"""Top-level Project container for the Universal IR."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from ._base import IRModel
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

    Attributes
    ----------
    folder : str
        Organizational path (forward-slash-delimited).
    scope : {"", "controller", "program"}
        Tag scope for AB (controller-scoped vs program-scoped tags).
        Empty string for vendors where scope is implicit.
    qualified_only : bool
        True if variables must be accessed with the GVL name prefix
        (Beckhoff ``{attribute 'qualified_only'}``).
    variables : list of Variable
        The global variables in this list (unique names validated).
    metadata : dict
        Vendor-specific key-value pairs for round-trip fidelity.
    """

    name: str = Field(min_length=1)
    folder: str = ""
    scope: Literal["", "controller", "program"] = ""
    description: str = ""
    qualified_only: bool = False
    variables: list[Variable] = []
    metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def _no_duplicate_var_names(self) -> Self:
        seen: set[str] = set()
        for v in self.variables:
            if v.name in seen:
                raise ValueError(f"Duplicate variable name '{v.name}' in global variable list '{self.name}'")
            seen.add(v.name)
        return self


class Project(IRModel):
    """Top-level container: a complete PLC project with POUs, types, GVLs, and tasks.

    All child collections enforce unique names at construction time
    (no duplicate POU names, type names, GVL names, or task names).

    Attributes
    ----------
    vendor : str
        Vendor identifier set during lower pass (e.g. ``"beckhoff"``).
        Empty when vendor-agnostic.
    vendor_version : str
        Vendor toolchain version (e.g. ``"3.1.4024.12"``).
    data_types : list of TypeDefinition
        User-defined types (structs, enums, unions, aliases, subranges).
    global_variable_lists : list of GlobalVariableList
        Global variable lists (Beckhoff GVLs, Siemens tag tables, AB tags).
    pous : list of POU
        All program organization units in the project.
    tasks : list of Task
        Task/scheduling configuration (periodic, continuous, event, startup).
    metadata : dict
        Vendor-specific key-value pairs for round-trip fidelity.
    """

    name: str = Field(min_length=1)
    vendor: str = ""
    vendor_version: str = ""
    data_types: list[TypeDefinition] = []
    global_variable_lists: list[GlobalVariableList] = []
    pous: list[POU] = []
    tasks: list[Task] = []
    metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def _no_duplicate_pou_names(self) -> Self:
        seen: set[str] = set()
        for pou in self.pous:
            if pou.name in seen:
                raise ValueError(f"Duplicate POU name '{pou.name}'")
            seen.add(pou.name)
        return self

    @model_validator(mode="after")
    def _no_duplicate_type_names(self) -> Self:
        seen: set[str] = set()
        for dt in self.data_types:
            if dt.name in seen:
                raise ValueError(f"Duplicate data type name '{dt.name}'")
            seen.add(dt.name)
        return self

    @model_validator(mode="after")
    def _no_duplicate_gvl_names(self) -> Self:
        seen: set[str] = set()
        for gvl in self.global_variable_lists:
            if gvl.name in seen:
                raise ValueError(f"Duplicate global variable list name '{gvl.name}'")
            seen.add(gvl.name)
        return self

    @model_validator(mode="after")
    def _no_duplicate_task_names(self) -> Self:
        seen: set[str] = set()
        for task in self.tasks:
            if task.name in seen:
                raise ValueError(f"Duplicate task name '{task.name}'")
            seen.add(task.name)
        return self

"""plx Python Framework — public API.

Users import everything from this single flat namespace::

    from plx.framework import fb, Input, BOOL, REAL, TIME, T, Field, delayed
"""

from ._types import (
    # Primitive type constants
    BOOL,
    BYTE,
    CHAR,
    DATE,
    DINT,
    DWORD,
    DT,
    INT,
    LDATE,
    LINT,
    LREAL,
    LTIME,
    LTOD,
    LWORD,
    LDT,
    REAL,
    SINT,
    TIME,
    TOD,
    UDINT,
    UINT,
    ULINT,
    USINT,
    WCHAR,
    WORD,
    # Duration literal constructors
    T,
    LT,
    # Duration literal types (for isinstance checks / type annotations)
    TimeLiteral,
    LTimeLiteral,
    # Type constructors
    ARRAY,
    STRING,
    WSTRING,
    POINTER_TO,
    REFERENCE_TO,
    # System flag sentinels
    first_scan,
)

from ._descriptors import (
    Input,
    Output,
    InOut,
    Static,
    Temp,
    Constant,
    External,
    Field,
    # IEC 61131-3 standard function block types
    TON,
    TOF,
    TP,
    RTO,
    R_TRIG,
    F_TRIG,
    CTU,
    CTD,
    CTUD,
    SR,
    RS,
)

from ._decorators import (
    fb,
    program,
    function,
    method,
    interface,
)

from ._properties import (
    fb_property,
)

from ._sfc import (
    sfc,
    step,
    transition,
)

from ._data_types import (
    struct,
    enumeration,
)

from ._global_vars import (
    global_vars,
)

from ._protocols import (
    CompiledPOU,
    CompiledDataType,
    CompiledGlobalVarList,
)

from ._errors import (
    PlxError,
    DeclarationError,
    DefinitionError,
    ProjectAssemblyError,
)

from ._compiler import (
    delayed,
    rising,
    falling,
    sustained,
    pulse,
    retentive,
    count_up,
    count_down,
    set_dominant,
    reset_dominant,
    CompileError,
)

from ._discover import (
    discover,
    DiscoveryResult,
)

from plx.export.py import (
    generate,
    generate_files,
)

from ._project import (
    project,
    task,
)

from ._vendor import (
    CompileResult,
    PortabilityWarning,
    Vendor,
    VendorValidationError,
)

# Standard library re-exports for convenience
from dataclasses import dataclass
from enum import IntEnum
from typing import Annotated

__all__ = [
    # Primitive type constants
    "BOOL",
    "BYTE",
    "CHAR",
    "DATE",
    "DINT",
    "DWORD",
    "DT",
    "INT",
    "LDATE",
    "LINT",
    "LREAL",
    "LTIME",
    "LTOD",
    "LWORD",
    "LDT",
    "REAL",
    "SINT",
    "TIME",
    "TOD",
    "UDINT",
    "UINT",
    "ULINT",
    "USINT",
    "WCHAR",
    "WORD",
    # Duration literals
    "T",
    "LT",
    "TimeLiteral",
    "LTimeLiteral",
    # Type constructors
    "ARRAY",
    "STRING",
    "WSTRING",
    "POINTER_TO",
    "REFERENCE_TO",
    # Variable annotation wrappers
    "Input",
    "Output",
    "InOut",
    "Static",
    "Temp",
    "Constant",
    "External",
    "Field",
    # IEC 61131-3 standard function block types
    "TON",
    "TOF",
    "TP",
    "RTO",
    "R_TRIG",
    "F_TRIG",
    "CTU",
    "CTD",
    "CTUD",
    "SR",
    "RS",
    # POU decorators
    "fb",
    "program",
    "function",
    "method",
    "interface",
    "fb_property",
    # SFC
    "sfc",
    "step",
    "transition",
    # Data type decorators
    "struct",
    "enumeration",
    # Global variable lists
    "global_vars",
    # Sentinel functions
    "first_scan",
    "delayed",
    "rising",
    "falling",
    "sustained",
    "pulse",
    "retentive",
    "count_up",
    "count_down",
    "set_dominant",
    "reset_dominant",
    # Protocols
    "CompiledPOU",
    "CompiledDataType",
    "CompiledGlobalVarList",
    # Errors
    "PlxError",
    "CompileError",
    "DeclarationError",
    "DefinitionError",
    "ProjectAssemblyError",
    # Discovery
    "discover",
    "DiscoveryResult",
    # Code generation
    "generate",
    "generate_files",
    # Project & tasks
    "project",
    "task",
    # Vendor targeting
    "CompileResult",
    "PortabilityWarning",
    "Vendor",
    "VendorValidationError",
    # Standard library re-exports
    "dataclass",
    "IntEnum",
    "Annotated",
]

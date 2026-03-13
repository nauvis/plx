"""plx Python Framework — public API.

Users import everything from this single flat namespace::

    from plx.framework import fb, Input, BOOL, REAL, TIME, Field, delayed, timedelta
"""

from ._types import (
    # Primitive type constants (ALL_CAPS — backwards compat)
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
    # timedelta → IEC conversion helpers
    timedelta_to_iec,
    timedelta_to_ir,
    # Type constructors (uppercase — backwards compat)
    ARRAY,
    STRING,
    WSTRING,
    POINTER_TO,
    REFERENCE_TO,
    # Type constructors (lowercase aliases)
    array,
    string,
    wstring,
    pointer_to,
    reference_to,
    # System flag sentinels
    first_scan,
)

from ._plc_types import (  # noqa: F811 — int shadows builtin intentionally
    # PLC data type classes (lowercase, with overflow semantics)
    sint,
    int,
    dint,
    lint,
    usint,
    uint,
    udint,
    ulint,
    real,
    lreal,
    byte,
    word,
    dword,
    lword,
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
    # IEC 61131-3 standard function block types (uppercase — backwards compat)
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
    # Standard FB types (lowercase aliases)
    ton,
    tof,
    tp,
    rto,
    r_trig,
    f_trig,
    ctu,
    ctd,
    ctud,
    sr,
    rs,
)

from ._decorators import (
    fb,
    program,
    function,
    method,
    interface,
)

from ..model.pou import AccessSpecifier

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
    count_up_down,
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

from ._project import project
from ._task import task

from ._vendor import (
    CompileResult,
    PortabilityWarning,
    Vendor,
    VendorValidationError,
)

# Standard library re-exports for convenience
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum
from typing import Annotated
import math

__all__ = [
    # PLC data type classes (lowercase, with overflow semantics)
    "sint",
    "int",
    "dint",
    "lint",
    "usint",
    "uint",
    "udint",
    "ulint",
    "real",
    "lreal",
    "byte",
    "word",
    "dword",
    "lword",
    # Primitive type constants (ALL_CAPS — backwards compat)
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
    # timedelta (re-exported from datetime)
    "timedelta",
    # timedelta → IEC conversion helpers
    "timedelta_to_iec",
    "timedelta_to_ir",
    # Type constructors (uppercase — backwards compat)
    "ARRAY",
    "STRING",
    "WSTRING",
    "POINTER_TO",
    "REFERENCE_TO",
    # Type constructors (lowercase aliases)
    "array",
    "string",
    "wstring",
    "pointer_to",
    "reference_to",
    # Variable annotation wrappers
    "Input",
    "Output",
    "InOut",
    "Static",
    "Temp",
    "Constant",
    "External",
    "Field",
    # IEC 61131-3 standard function block types (uppercase — backwards compat)
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
    # Standard FB types (lowercase aliases)
    "ton",
    "tof",
    "tp",
    "rto",
    "r_trig",
    "f_trig",
    "ctu",
    "ctd",
    "ctud",
    "sr",
    "rs",
    # POU decorators
    "fb",
    "program",
    "function",
    "method",
    "interface",
    "fb_property",
    "AccessSpecifier",
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
    "count_up_down",
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
    "math",
]

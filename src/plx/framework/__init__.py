"""plx Python Framework — public API.

Users import everything from this single flat namespace::

    from plx.framework import fb, Input, BOOL, REAL, TIME, Field, delayed, timedelta
"""

import math

# Standard library re-exports for convenience
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum
from typing import Annotated

from plx.export.py import (
    generate,
    generate_files,
)

from ..model.pou import AccessSpecifier

# Import IEC standard builtins to register them in the library registry.
# This must happen after _library and _descriptors are loaded.
from . import _iec_builtins
from ._compiler import (
    CompileError,
    count_down,
    count_up,
    count_up_down,
    delayed,
    falling,
    pulse,
    reset_dominant,
    retentive,
    rising,
    set_dominant,
    sustained,
)
from ._data_types import (
    enumeration,
    struct,
)
from ._decorators import (
    fb,
    fb_method,
    function,
    interface,
    method,  # backward-compat alias — will be removed
    program,
)
from ._descriptors import (
    CTD,
    CTU,
    CTUD,
    F_TRIG,
    R_TRIG,
    RS,
    RTO,
    SR,
    TOF,
    # IEC 61131-3 standard function block types (uppercase — backwards compat)
    TON,
    TP,
    External,
    Field,
    InOut,
    Input,
    Output,
    Static,
    Temp,
    ctd,
    ctu,
    ctud,
    f_trig,
    r_trig,
    rs,
    rto,
    sr,
    tof,
    # Standard FB types (lowercase aliases)
    ton,
    tp,
)
from ._discover import (
    DiscoveryResult,
    discover,
)
from ._errors import (
    DeclarationError,
    DefinitionError,
    PlxError,
    ProjectAssemblyError,
)
from ._global_vars import (
    global_vars,
)
from ._library import (
    FBParam,
    LibraryEnum,
    LibraryFB,
    LibraryStruct,
    get_library_fb,
    get_library_type,
)
from ._plc_types import (
    byte,
    dint,
    dword,
    int,
    lint,
    lreal,
    lword,
    real,
    # PLC data type classes (lowercase, with overflow semantics)
    sint,
    udint,
    uint,
    ulint,
    usint,
    word,
)
from ._project import project
from ._properties import (
    fb_property,
)
from ._protocols import (
    CompiledDataType,
    CompiledGlobalVarList,
    CompiledPOU,
)
from ._sfc import (
    sfc,
    step,
    transition,
)
from ._task import task
from ._types import (
    # Type constructors (uppercase — backwards compat)
    ARRAY,
    # Primitive type constants (ALL_CAPS — backwards compat)
    BOOL,
    BYTE,
    CHAR,
    DATE,
    DINT,
    DT,
    DWORD,
    INT,
    LDATE,
    LDT,
    LINT,
    LREAL,
    LTIME,
    LTOD,
    LWORD,
    POINTER_TO,
    REAL,
    REFERENCE_TO,
    SINT,
    STRING,
    TIME,
    TOD,
    UDINT,
    UINT,
    ULINT,
    USINT,
    WCHAR,
    WORD,
    WSTRING,
    # Type constructors (lowercase aliases)
    array,
    char,
    date,
    dt,
    # System flag sentinels
    first_scan,
    ldate,
    ldt,
    ltime,
    ltod,
    pointer_to,
    reference_to,
    string,
    # Lowercase type constants (date/time/character)
    time,
    # timedelta → IEC conversion helpers
    timedelta_to_iec,
    timedelta_to_ir,
    tod,
    wchar,
    wstring,
)
from ._vendor import (
    CompileResult,
    PortabilityWarning,
    Vendor,
    VendorValidationError,
)

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
    # Lowercase type constants (date/time/character)
    "time",
    "ltime",
    "date",
    "ldate",
    "tod",
    "ltod",
    "dt",
    "ldt",
    "char",
    "wchar",
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
    "fb_method",
    "method",  # backward-compat alias — will be removed
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
    # Library type stubs
    "LibraryFB",
    "LibraryStruct",
    "LibraryEnum",
    "FBParam",
    "get_library_type",
    "get_library_fb",
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

"""Constants, formatting utilities, and standalone helpers for the Python exporter."""

from __future__ import annotations

import re

from plx.model.expressions import BinaryOp
from plx.model.pou import POU, POUInterface, POUType
from plx.model.project import Project
from plx.model.statements import CaseBranch
from plx.model.types import (
    AliasType,
    ArrayTypeRef,
    EnumType,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    ReferenceTypeRef,
    StructType,
    SubrangeType,
    TypeRef,
    UnionType,
)


def _standard_fb_types() -> frozenset[str]:
    """Lazy import to avoid circular dependency with plx.framework.__init__."""
    from plx.framework._constants import STANDARD_FB_TYPES

    return STANDARD_FB_TYPES


# ---------------------------------------------------------------------------
# Primitive type -> Python name mapping
# ---------------------------------------------------------------------------

_PRIMITIVE_PY_NAME: dict[PrimitiveType, str] = {
    # Boolean -> Python builtin
    PrimitiveType.BOOL: "bool",
    # Signed integers -> PLC type classes
    PrimitiveType.SINT: "sint",
    PrimitiveType.INT: "int",
    PrimitiveType.DINT: "dint",
    PrimitiveType.LINT: "lint",
    # Unsigned integers -> PLC type classes
    PrimitiveType.USINT: "usint",
    PrimitiveType.UINT: "uint",
    PrimitiveType.UDINT: "udint",
    PrimitiveType.ULINT: "ulint",
    # Floating point -> PLC type classes
    PrimitiveType.REAL: "real",
    PrimitiveType.LREAL: "lreal",
    # Bit-strings -> PLC type classes
    PrimitiveType.BYTE: "byte",
    PrimitiveType.WORD: "word",
    PrimitiveType.DWORD: "dword",
    PrimitiveType.LWORD: "lword",
    # Duration (no PLC class yet -- lowercase IEC name)
    PrimitiveType.TIME: "time",
    PrimitiveType.LTIME: "ltime",
    # Date/time (no PLC class yet -- lowercase IEC name)
    PrimitiveType.DATE: "date",
    PrimitiveType.LDATE: "ldate",
    PrimitiveType.TOD: "tod",
    PrimitiveType.LTOD: "ltod",
    PrimitiveType.DT: "dt",
    PrimitiveType.LDT: "ldt",
    # Character (no PLC class yet -- lowercase IEC name)
    PrimitiveType.CHAR: "char",
    PrimitiveType.WCHAR: "wchar",
}

# Standard FB types -> lowercase Python names
_NAMED_TYPE_PY_NAME: dict[str, str] = {
    "TON": "ton",
    "TOF": "tof",
    "TP": "tp",
    "RTO": "rto",
    "R_TRIG": "r_trig",
    "F_TRIG": "f_trig",
    "CTU": "ctu",
    "CTD": "ctd",
    "CTUD": "ctud",
    "SR": "sr",
    "RS": "rs",
    # AB-specific type aliases (lowered from L5X)
    "BIT": "bool",
    "TIMER": "TON",
    "COUNTER": "CTU",
    "PID": "PID",
    "MESSAGE": "MESSAGE",
}


# ---------------------------------------------------------------------------
# Operator maps
# ---------------------------------------------------------------------------

_BINOP_PYTHON: dict[BinaryOp, str] = {
    BinaryOp.ADD: "+",
    BinaryOp.SUB: "-",
    BinaryOp.MUL: "*",
    BinaryOp.DIV: "/",
    BinaryOp.MOD: "%",
    BinaryOp.AND: "and",
    BinaryOp.OR: "or",
    BinaryOp.XOR: "^",
    BinaryOp.BAND: "&",
    BinaryOp.BOR: "|",
    BinaryOp.EQ: "==",
    BinaryOp.NE: "!=",
    BinaryOp.GT: ">",
    BinaryOp.GE: ">=",
    BinaryOp.LT: "<",
    BinaryOp.LE: "<=",
    BinaryOp.EXPT: "**",
    BinaryOp.AND_THEN: "and",  # Python and/or are already short-circuit
    BinaryOp.OR_ELSE: "or",
}

# Python precedence (higher = binds tighter)
# https://docs.python.org/3/reference/expressions.html#operator-precedence
_BINOP_PRECEDENCE: dict[BinaryOp, int] = {
    BinaryOp.OR: 1,
    BinaryOp.OR_ELSE: 1,
    BinaryOp.AND: 2,
    BinaryOp.AND_THEN: 2,
    BinaryOp.EQ: 3,
    BinaryOp.NE: 3,
    BinaryOp.LT: 3,
    BinaryOp.GT: 3,
    BinaryOp.LE: 3,
    BinaryOp.GE: 3,
    BinaryOp.BOR: 4,
    BinaryOp.XOR: 5,
    BinaryOp.BAND: 6,
    BinaryOp.ADD: 7,
    BinaryOp.SUB: 7,
    BinaryOp.MUL: 8,
    BinaryOp.DIV: 8,
    BinaryOp.MOD: 8,
    BinaryOp.EXPT: 9,
    # Function-call style
    BinaryOp.SHL: 0,
    BinaryOp.SHR: 0,
    BinaryOp.ROL: 0,
    BinaryOp.ROR: 0,
}

_FUNC_CALL_OPS = {BinaryOp.SHL, BinaryOp.SHR, BinaryOp.ROL, BinaryOp.ROR}

# IEC functions -> Python builtins / math module
_FUNC_REMAP: dict[str, str] = {
    "ABS": "abs",
    "MIN": "min",
    "MAX": "max",
    "ROUND": "round",
    "SQRT": "math.sqrt",
    "LN": "math.log",
    "LOG": "math.log10",
    "EXP": "math.exp",
    "SIN": "math.sin",
    "COS": "math.cos",
    "TAN": "math.tan",
    "ASIN": "math.asin",
    "ACOS": "math.acos",
    "ATAN": "math.atan",
    "TRUNC": "math.trunc",
    "CEIL": "math.ceil",
    "FLOOR": "math.floor",
}

_POU_DECORATOR = {
    POUType.FUNCTION_BLOCK: "fb",
    POUType.PROGRAM: "program",
    POUType.FUNCTION: "function",
}


# ---------------------------------------------------------------------------
# String quoting
# ---------------------------------------------------------------------------


def _quote_string(s: str) -> str:
    """Quote a string for use in generated Python code.

    Uses simple ``"..."`` when the string is single-line, or ``repr()``
    when it contains newlines, backslashes, or quotes that would break
    a bare double-quoted string.
    """
    if "\n" in s or "\r" in s or '"' in s or "\\" in s:
        return repr(s)
    return f'"{s}"'


def _iec_string_to_python(value: str) -> str:
    """Convert an IEC 61131-3 quoted string literal to a Python string literal.

    Strips outer IEC quotes, un-escapes ``$`` sequences, and re-quotes for
    Python using ``repr()`` which handles backslashes and special characters.

    IEC escape sequences:
      ``$'`` → ``'``, ``$"`` → ``"``, ``$$`` → ``$``,
      ``$N``/``$L`` → newline, ``$R`` → carriage return,
      ``$T`` → tab, ``$P`` → form feed
    """
    # Determine and strip outer quotes
    if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
        inner = value[1:-1]
    else:
        return value  # not a quoted string — return as-is

    # Un-escape IEC $ sequences
    chars: list[str] = []
    i = 0
    while i < len(inner):
        if inner[i] == "$" and i + 1 < len(inner):
            nc = inner[i + 1]
            if nc == "'":
                chars.append("'")
            elif nc == '"':
                chars.append('"')
            elif nc == "$":
                chars.append("$")
            elif nc in ("N", "n", "L", "l"):
                chars.append("\n")
            elif nc in ("R", "r"):
                chars.append("\r")
            elif nc in ("T", "t"):
                chars.append("\t")
            elif nc in ("P", "p"):
                chars.append("\f")
            else:
                # Unknown $ escape — preserve both chars
                chars.append("$")
                chars.append(nc)
            i += 2
        else:
            chars.append(inner[i])
            i += 1

    # Re-quote for Python (repr handles backslashes, quotes, control chars)
    return repr("".join(chars))


# IEC boolean/arithmetic operator pattern — matches standalone keywords only
_IEC_OP_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_])   # not preceded by identifier char
    (AND_THEN|OR_ELSE|AND|OR|NOT|XOR|MOD)
    (?![A-Za-z0-9_])    # not followed by identifier char
    """,
    re.VERBOSE,
)

_IEC_OP_MAP = {
    "AND": "and",
    "OR": "or",
    "NOT": "not",
    "XOR": "^",
    "MOD": "%",
    "AND_THEN": "and",
    "OR_ELSE": "or",
}


def _fix_embedded_iec(name: str) -> str:
    """Convert IEC operators and string escapes inside an embedded function_name.

    When the Beckhoff parser flattens chained method calls into a single
    ``function_name`` string (e.g. ``Messenger.OnCondition(x AND NOT y).Error('msg')``),
    the embedded IEC operators and string literals need conversion to Python syntax.
    """
    if "(" not in name:
        return name  # simple dotted name — no embedded call syntax

    # Convert IEC boolean/arithmetic operators to Python
    def _replace_op(m: re.Match) -> str:
        return _IEC_OP_MAP[m.group(1)]

    result = _IEC_OP_RE.sub(_replace_op, name)

    # Convert THIS^/This^/this^ → self (case-insensitive) within embedded args
    result = re.sub(r"\bTHIS\^\.", "self.", result, flags=re.IGNORECASE)
    result = re.sub(r"\bTHIS\^", "self", result, flags=re.IGNORECASE)

    # Convert remaining ptr^.member → ptr.deref.member
    result = result.replace("^.", ".deref.")
    result = result.replace("^", ".deref")

    # Convert IEC <> (not-equal) to !=
    result = result.replace("<>", "!=")

    # Convert IEC = (comparison) to == where it appears as comparison
    # (not := assignment, not == already, not at start of expression)
    result = re.sub(r"(?<![:<>=!])=(?!=)", "==", result)

    # Convert IEC string escapes within embedded single-quoted strings
    def _fix_iec_string(m: re.Match) -> str:
        return _iec_string_to_python(m.group(0))

    result = re.sub(r"'[^']*(?:\$.[^']*)*'", _fix_iec_string, result)

    return result


# ---------------------------------------------------------------------------
# IEC time parsing
# ---------------------------------------------------------------------------

# IEC time literal regex: T#1h2m3s4ms5us or subsets
_IEC_TIME_RE = re.compile(
    r"^(?:L?TIME#|[LT]#)"
    r"(?:(\d+)h)?"
    r"(?:(\d+)m(?!s))?"
    r"(?:(\d+(?:\.\d+)?)s(?!$|[a-zA-Z]))?"
    r"(?:(\d+(?:\.\d+)?)s)?"
    r"(?:(\d+)ms)?"
    r"(?:(\d+)us)?$",
    re.IGNORECASE,
)

# Simpler per-unit patterns for IEC time
_IEC_TIME_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ms|us|h|d|m(?!s)|s)",
    re.IGNORECASE,
)


def _parse_iec_time(value: str) -> str | None:
    """Parse an IEC time literal like T#100ms into timedelta(milliseconds=100).

    Returns None if not a time literal.
    """
    if not re.match(r"^(?:L?TIME#|[LT]#)", value, re.IGNORECASE):
        return None

    # Map IEC unit abbreviations to timedelta kwarg names
    _UNIT_TO_KWARG = {
        "d": "days",
        "h": "hours",
        "m": "minutes",
        "s": "seconds",
        "ms": "milliseconds",
        "us": "microseconds",
    }

    # Extract units
    parts: dict[str, str] = {}
    for match in _IEC_TIME_UNIT_RE.finditer(value):
        amount = match.group(1)
        unit = match.group(2).lower()
        kwarg_name = _UNIT_TO_KWARG.get(unit)
        if kwarg_name:
            parts[kwarg_name] = amount

    if not parts:
        return None

    # Simplify: remove .0 from float amounts, use int if possible
    kwargs = []
    for k, v in parts.items():
        if "." in v:
            fv = float(v)
            if fv == int(fv):
                v = str(int(fv))
        kwargs.append(f"{k}={v}")

    return f"timedelta({', '.join(kwargs)})"


# ---------------------------------------------------------------------------
# Initial value formatting
# ---------------------------------------------------------------------------


def _format_initial_value(value: str) -> str | None:
    """Convert an IEC initial value string to a Python literal.

    Returns ``None`` for values that have no valid Python representation
    (function calls, complex expressions).  Callers should fall back to
    ``Field(initial=...)`` when this returns ``None``.
    """
    if value == "TRUE":
        return "True"
    if value == "FALSE":
        return "False"

    # IEC time literal
    time_repr = _parse_iec_time(value)
    if time_repr is not None:
        return time_repr

    # Date/time typed literals: DATE#2024-01-15 -> "DATE#2024-01-15" (string)
    _DATE_TIME_PREFIXES = {
        "DATE",
        "LDATE",
        "TOD",
        "LTOD",
        "DT",
        "LDT",
        "TIME_OF_DAY",
        "LTIME_OF_DAY",
        "DATE_AND_TIME",
        "LDATE_AND_TIME",
        "D",
        "LD",  # short forms
    }
    if "#" in value:
        prefix = value.split("#", 1)[0].upper()
        if prefix in _DATE_TIME_PREFIXES:
            return repr(value)

    # Typed numeric literal: BYTE#255 -> 255, REAL#3.14 -> 3.14
    # The prefix is an IEC type name; the suffix is a numeric value.
    _NUMERIC_TYPE_PREFIXES = {
        "BYTE",
        "WORD",
        "DWORD",
        "LWORD",
        "SINT",
        "INT",
        "DINT",
        "LINT",
        "USINT",
        "UINT",
        "UDINT",
        "ULINT",
        "REAL",
        "LREAL",
        "BOOL",
    }
    if "#" in value and not value.startswith("16#") and not value.startswith("8#"):
        prefix, _, suffix = value.partition("#")
        if prefix.upper() in _NUMERIC_TYPE_PREFIXES and suffix:
            # Strip nested base prefixes (e.g. BYTE#16#FF -> 0xFF)
            if suffix.startswith("16#"):
                return "0x" + suffix[3:]
            if suffix.startswith("8#"):
                return "0o" + suffix[2:]
            if suffix.startswith("2#"):
                return "0b" + suffix[2:]
            # Plain numeric — try to parse, return as-is if valid
            try:
                int(suffix)
                return suffix
            except ValueError:
                pass
            try:
                float(suffix)
                return suffix
            except ValueError:
                pass
            # Not a simple number — quote the whole thing
            return repr(value)

    # Enum literal: EnumType#MEMBER -> EnumType.MEMBER (sanitize member name)
    if "#" in value and not value.startswith("16#") and not value.startswith("8#"):
        parts = value.split("#", 1)
        if parts[0] and parts[1] and parts[0][0].isalpha():
            return f"{parts[0]}.{_safe_name(parts[1])}"

    # Numeric -- try int then float
    try:
        int(value)
        return value
    except ValueError:
        pass
    try:
        float(value)
        return value
    except ValueError:
        pass

    # String literal -- convert IEC escapes to Python
    if value.startswith(("'", '"')):
        return _iec_string_to_python(value)

    # IEC FB/struct initialization: (Param := Value, ...) -> dict(Param=Value, ...)
    fb_init = _try_format_fb_init(value)
    if fb_init is not None:
        return fb_init

    # Empty array/struct initializer
    if value in ("[]", "{}"):
        return value

    # Not representable as a Python literal (function calls, complex
    # expressions, etc.) -- return None so callers use Field(initial=...).
    return None


def _try_format_fb_init(value: str) -> str | None:
    """Convert IEC FB init ``(A := 1, B := TRUE)`` to Python dict literal.

    Returns a string like ``{"Name": "Axis", "Flag": True}`` which callers
    wrap in ``Field(initial=...)``.  Returns None if the value doesn't match.
    """
    stripped = value.strip()
    if not (stripped.startswith("(") and stripped.endswith(")")):
        return None
    inner = stripped[1:-1].strip()
    if ":=" not in inner:
        return None

    # Split on commas that aren't inside nested parens or strings
    parts = _split_init_params(inner)
    if not parts:
        return None

    py_params: list[str] = []
    for part in parts:
        part = part.strip()
        if ":=" not in part:
            return None  # Not a named param -- bail
        name, _, val = part.partition(":=")
        name = name.strip()
        val = val.strip()
        if not name or not val:
            return None
        # Recursively format the value
        py_val = _format_initial_value(val)
        if py_val is None:
            return None  # Unrepresentable nested value -- bail
        py_params.append(f'"{name}": {py_val}')

    return "{" + ", ".join(py_params) + "}"


def _is_dict_literal(formatted: str) -> bool:
    """Check if a formatted initial value is a dict literal (FB/struct init)."""
    return formatted.startswith("{")


def _split_init_params(text: str) -> list[str]:
    """Split comma-separated IEC init params, respecting nested parens and strings."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    in_string = False
    for ch in text:
        if ch == "'" and not in_string:
            in_string = True
            current.append(ch)
        elif ch == "'" and in_string:
            in_string = False
            current.append(ch)
        elif in_string:
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


# ---------------------------------------------------------------------------
# Self-var / inheritance helpers
# ---------------------------------------------------------------------------


def _build_self_vars(iface: POUInterface) -> set[str]:
    """Build the set of variable names that need self. prefix.

    All vars except temp_vars get self. prefix.
    """
    names: set[str] = set()
    for v in iface.input_vars:
        names.add(v.name)
    for v in iface.output_vars:
        names.add(v.name)
    for v in iface.inout_vars:
        names.add(v.name)
    for v in iface.static_vars:
        names.add(v.name)
    for v in iface.constant_vars:
        names.add(v.name)
    for v in iface.external_vars:
        names.add(v.name)
    return names


def _build_inherited_self_context(
    parent_name: str,
    all_pous: list[POU],
) -> tuple[set[str], set[str], bool]:
    """Walk the inheritance chain and collect parent vars + method names.

    Returns (inherited_vars, inherited_methods, fully_resolved).
    ``fully_resolved`` is False if the chain hits a POU not in the project
    (e.g. a library FB).
    """
    inherited_vars: set[str] = set()
    inherited_methods: set[str] = set()
    pou_map = {p.name: p for p in all_pous}
    current = parent_name
    while current:
        parent = pou_map.get(current)
        if parent is None:
            return inherited_vars, inherited_methods, False
        inherited_vars |= _build_self_vars(parent.interface)
        inherited_methods |= {m.name for m in parent.methods}
        current = parent.extends
    return inherited_vars, inherited_methods, True


# Well-known IEC 61131-3 / Beckhoff built-in functions that should never get
# a self. prefix. This is intentionally non-exhaustive -- when the parent is
# fully resolved, the heuristic is not needed.
_KNOWN_GLOBAL_FUNCTIONS: frozenset[str] = frozenset(
    {
        # IEC standard functions
        "ABS",
        "SQRT",
        "LN",
        "LOG",
        "EXP",
        "SIN",
        "COS",
        "TAN",
        "ASIN",
        "ACOS",
        "ATAN",
        "ATAN2",
        "CEIL",
        "FLOOR",
        "TRUNC",
        "ROUND",
        "MIN",
        "MAX",
        "LIMIT",
        "SEL",
        "MUX",
        "SHL",
        "SHR",
        "ROL",
        "ROR",
        "LEN",
        "LEFT",
        "RIGHT",
        "MID",
        "FIND",
        "REPLACE",
        "INSERT",
        "DELETE",
        "CONCAT",
        "SIZEOF",
        "ADR",
        "ADRINST",
        "MEMSET",
        "MEMCPY",
        "MEMMOVE",
        "AND",
        "OR",
        "XOR",
        "NOT",
        # Python builtins used in plx
        "abs",
        "min",
        "max",
        "len",
        "round",
        "range",
        "print",
        # Common Beckhoff system functions
        "F_GetActualDcTime64",
        "F_CreateAllEventsInClass",
        "F_GetMaxSeverityRaised",
        "F_RaiseAlarmWithStringParameters",
        "F_UnitModeToString",
    }
)


def _build_non_self_names(pou: POU, project: Project | None) -> set[str]:
    """Build the set of names that should NOT get a self. prefix.

    Used as a negative filter when the POU has an unresolved parent.
    Includes: temp vars, known global functions, type/POU/GVL names
    from the project, IEC primitive type names, and enum type names.
    """
    names: set[str] = set(_KNOWN_GLOBAL_FUNCTIONS)

    # Temp vars from the POU's own interface
    for v in pou.interface.temp_vars:
        names.add(v.name)

    # IEC primitive type names
    for pt in PrimitiveType:
        names.add(pt.value)

    # Standard FB type names
    names |= set(_standard_fb_types())

    if project is not None:
        # POU names, data type names, GVL names
        for p in project.pous:
            names.add(p.name)
        for td in project.data_types:
            if isinstance(td, (StructType, EnumType)):
                names.add(td.name)
                # Enum members are accessed via EnumType.MEMBER so the type
                # name itself is non-self, but members don't appear as
                # standalone VariableRefs.
        for gvl in project.global_variable_lists:
            names.add(gvl.name)

    return names


# ---------------------------------------------------------------------------
# Topological sort / SFC / CASE helpers
# ---------------------------------------------------------------------------


def _topo_sort_fbs(fbs: list[POU]) -> list[POU]:
    """Sort function blocks so bases come before derived classes."""
    by_name = {fb.name: fb for fb in fbs}
    visited: set[str] = set()
    result: list[POU] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        fb = by_name.get(name)
        if fb is None:
            return
        if fb.extends and fb.extends in by_name:
            visit(fb.extends)
        result.append(fb)

    for fb in fbs:
        visit(fb.name)
    return result


def _topo_sort_data_types(data_types: list) -> list:
    """Sort data types so dependencies come before dependents."""
    by_name: dict[str, object] = {dt.name: dt for dt in data_types}
    visited: set[str] = set()
    result: list = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        dt = by_name.get(name)
        if dt is None:
            return
        if isinstance(dt, StructType):
            for m in dt.members:
                for dep in _collect_named_refs(m.data_type):
                    if dep in by_name:
                        visit(dep)
        result.append(dt)

    for dt in data_types:
        visit(dt.name)
    return result


def _step_group_expr(steps: list[str]) -> str:
    """Format step list for SFC transition path."""
    if len(steps) == 1:
        return steps[0]
    return f"({' & '.join(steps)})"


def _case_branch_condition(sel: str, branch: CaseBranch) -> str:
    """Build a Python condition for a CASE branch with ranges."""
    parts: list[str] = []
    for v in branch.values:
        if isinstance(v, str):
            # Sanitize member part of dotted enum names (e.g. Enum.None → Enum.None_)
            if "." in v:
                prefix, member = v.rsplit(".", 1)
                v = f"{prefix}.{_safe_name(member)}"
            parts.append(f"{sel} == {v}")
        else:
            parts.append(f"{sel} == {v}")
    for r in branch.ranges:
        parts.append(f"{r.start} <= {sel} <= {r.end}")
    return " or ".join(parts) if parts else "True"


# ---------------------------------------------------------------------------
# Identifier / folder sanitization
# ---------------------------------------------------------------------------

_PYTHON_KEYWORDS = frozenset(
    {
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    }
)


def _sanitize_identifier(name: str) -> str:
    """Convert a task/POU name to a valid Python identifier."""
    result = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if result and result[0].isdigit():
        result = "_" + result
    # Escape Python reserved words
    if result in _PYTHON_KEYWORDS:
        result = result + "_"
    return result


def _safe_name(name: str) -> str:
    """Escape Python keywords used as IEC variable/parameter/member names.

    IEC 61131-3 allows ``IN``, ``AS``, etc. as identifiers.  Python does not.
    Appends ``_`` when the name (case-insensitively lowered, since the framework
    uses lowercase PLC types) collides with a Python keyword or builtin constant.
    """
    if name in _PYTHON_KEYWORDS or name == "None":
        return name + "_"
    return name


def _sanitize_folder(folder: str) -> str:
    """Sanitize a folder path so each segment is a valid Python identifier.

    Beckhoff FolderPath can contain spaces (e.g. ``"Machine/HMI Connections"``),
    which are invalid in Python module paths.  Replaces non-identifier characters
    with underscores in each path segment.
    """
    if not folder:
        return folder
    return "/".join(_sanitize_identifier(seg) for seg in folder.split("/"))


# ---------------------------------------------------------------------------
# Dependency collection
# ---------------------------------------------------------------------------


def _collect_named_refs(tr: TypeRef) -> set[str]:
    """Collect all NamedTypeRef names from a TypeRef tree."""
    names: set[str] = set()
    if isinstance(tr, NamedTypeRef):
        names.add(tr.name)
    elif isinstance(tr, ArrayTypeRef):
        names |= _collect_named_refs(tr.element_type)
    elif isinstance(tr, PointerTypeRef):
        names |= _collect_named_refs(tr.target_type)
    elif isinstance(tr, ReferenceTypeRef):
        names |= _collect_named_refs(tr.target_type)
    return names


def _collect_fb_type_names_from_statements(stmts: list) -> set[str]:
    """Collect NamedTypeRef names from FBInvocations in statement bodies."""
    names: set[str] = set()
    for stmt in stmts:
        # FBInvocation — extract fb_type name
        fb_type = getattr(stmt, "fb_type", None)
        if fb_type is not None and isinstance(fb_type, NamedTypeRef):
            names.add(fb_type.name)
        # Recurse into compound statement bodies
        # IfStatement: if_branch.body, elsif_branches[].body, else_body
        if_branch = getattr(stmt, "if_branch", None)
        if if_branch is not None:
            names |= _collect_fb_type_names_from_statements(if_branch.body)
            for elsif in getattr(stmt, "elsif_branches", []):
                names |= _collect_fb_type_names_from_statements(elsif.body)
        # else_body (IfStatement, CaseStatement)
        else_body = getattr(stmt, "else_body", None)
        if isinstance(else_body, list):
            names |= _collect_fb_type_names_from_statements(else_body)
        # body (ForStatement, WhileStatement, RepeatStatement)
        body = getattr(stmt, "body", None)
        if isinstance(body, list):
            names |= _collect_fb_type_names_from_statements(body)
        # CaseStatement branches
        branches = getattr(stmt, "branches", None)
        if isinstance(branches, list):
            for branch in branches:
                branch_body = getattr(branch, "body", None)
                if isinstance(branch_body, list):
                    names |= _collect_fb_type_names_from_statements(branch_body)
        # TryCatchStatement
        try_body = getattr(stmt, "try_body", None)
        if isinstance(try_body, list):
            names |= _collect_fb_type_names_from_statements(try_body)
        catch_body = getattr(stmt, "catch_body", None)
        if isinstance(catch_body, list):
            names |= _collect_fb_type_names_from_statements(catch_body)
        finally_body = getattr(stmt, "finally_body", None)
        if isinstance(finally_body, list):
            names |= _collect_fb_type_names_from_statements(finally_body)
    return names


def _collect_library_imports(pou: POU, project: Project) -> list[str]:
    """Collect vendor-qualified import lines for library types used by a POU.

    Returns lines like ``'from plx.framework.vendor.beckhoff import MC_Power, AXIS_REF'``.
    """
    # Lazy import to avoid circular dependency (export -> framework)
    from plx.framework._library import get_library_type

    # Collect all NamedTypeRef names from the POU's interface
    referenced: set[str] = set()

    def _collect_from_interface(iface: POUInterface) -> None:
        for var_list in (
            iface.input_vars,
            iface.output_vars,
            iface.inout_vars,
            iface.static_vars,
            iface.temp_vars,
            iface.constant_vars,
            iface.external_vars,
        ):
            for v in var_list:
                referenced.update(_collect_named_refs(v.data_type))

    _collect_from_interface(pou.interface)

    # Method and property interfaces
    for method in pou.methods:
        if method.interface:
            _collect_from_interface(method.interface)
        if method.return_type:
            referenced.update(_collect_named_refs(method.return_type))
    for prop in pou.properties:
        if prop.data_type:
            referenced.update(_collect_named_refs(prop.data_type))
        if prop.getter and prop.getter.local_vars:
            for v in prop.getter.local_vars:
                referenced.update(_collect_named_refs(v.data_type))
        if prop.setter and prop.setter.local_vars:
            for v in prop.setter.local_vars:
                referenced.update(_collect_named_refs(v.data_type))

    # extends / implements
    if pou.extends:
        referenced.add(pou.extends)
    for iface_name in pou.implements:
        referenced.add(iface_name)

    # Scan FBInvocation type names in the body
    for net in pou.networks:
        referenced |= _collect_fb_type_names_from_statements(net.statements)
    if pou.sfc_body:
        for step in pou.sfc_body.steps:
            for action in step.actions:
                referenced |= _collect_fb_type_names_from_statements(action.body)
            for action in step.entry_actions:
                referenced |= _collect_fb_type_names_from_statements(action.body)
            for action in step.exit_actions:
                referenced |= _collect_fb_type_names_from_statements(action.body)

    # Filter out project-local names
    project_names = set()
    for td in project.data_types:
        if hasattr(td, "name"):
            project_names.add(td.name)
    for p in project.pous:
        project_names.add(p.name)

    # Filter out standard FB types
    std_fbs = _standard_fb_types()

    # Look up remaining names in the library registry
    # Group by (vendor, package) -> type names
    groups: dict[str, list[str]] = {}  # vendor -> [type_names]
    for name in referenced:
        if name in project_names or name in std_fbs:
            continue
        lib_type = get_library_type(name)
        if lib_type is not None:
            vendor = lib_type._vendor
            if vendor:
                groups.setdefault(vendor, []).append(name)

    # Build import lines
    lines: list[str] = []
    for vendor in sorted(groups):
        type_names = sorted(groups[vendor])
        lines.append(f"from plx.framework.vendor.{vendor} import {', '.join(type_names)}")
    return lines


def _collect_pou_deps(pou: POU, project: Project) -> dict[str, list[str]]:
    """Collect cross-file dependencies for a POU.

    Returns {module_name: [imported_names]} for sibling file imports.
    Only includes names that correspond to project-level definitions
    (data types, GVLs, other POUs).
    """

    # Build lookup of what's defined where
    def _mod(folder: str, name: str) -> str:
        folder = _sanitize_folder(folder)
        if folder:
            return folder.replace("/", ".") + "." + name
        return name

    project_names: dict[str, str] = {}  # name -> module_path (dotted)
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType, UnionType, AliasType, SubrangeType)):
            project_names[td.name] = _mod(td.folder, td.name)
    for gvl in project.global_variable_lists:
        project_names[gvl.name] = _mod(gvl.folder, gvl.name)
    for p in project.pous:
        if p.name != pou.name:
            project_names[p.name] = _mod(p.folder, p.name)

    # Collect all NamedTypeRef references from this POU's interface
    referenced: set[str] = set()

    def _collect_from_interface(iface: POUInterface) -> None:
        for var_list in (
            iface.input_vars,
            iface.output_vars,
            iface.inout_vars,
            iface.static_vars,
            iface.temp_vars,
            iface.constant_vars,
            iface.external_vars,
        ):
            for v in var_list:
                referenced.update(_collect_named_refs(v.data_type))

    _collect_from_interface(pou.interface)

    # Method and property interfaces
    for method in pou.methods:
        if method.interface:
            _collect_from_interface(method.interface)
        if method.return_type:
            referenced.update(_collect_named_refs(method.return_type))
    for prop in pou.properties:
        if prop.data_type:
            referenced.update(_collect_named_refs(prop.data_type))
        if prop.getter and prop.getter.local_vars:
            for v in prop.getter.local_vars:
                referenced.update(_collect_named_refs(v.data_type))
        if prop.setter and prop.setter.local_vars:
            for v in prop.setter.local_vars:
                referenced.update(_collect_named_refs(v.data_type))

    # extends reference
    if pou.extends:
        referenced.add(pou.extends)

    # implements references
    for iface_name in pou.implements:
        referenced.add(iface_name)

    # Filter to project-level names only
    deps: dict[str, list[str]] = {}
    for name in referenced:
        if name in project_names and name not in _standard_fb_types():
            module = project_names[name]
            deps.setdefault(module, []).append(name)

    return deps

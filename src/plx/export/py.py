"""Python framework code generator (IR → plx Python).

Walks Universal IR ``Project`` models and emits valid plx Python framework code.
Follows the ``STWriter`` pattern — buffer-based writer with indent management.
"""

from __future__ import annotations

import re
from io import StringIO

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.pou import (
    POU,
    AccessSpecifier,
    Method,
    Network,
    POUAction,
    POUInterface,
    POUType,
    Property,
)
from plx.model.project import GlobalVariableList, Project
from plx.model.sfc import Action, ActionQualifier, SFCBody, Step, Transition
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    ContinueStatement,
    EmptyStatement,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfStatement,
    JumpStatement,
    LabelStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    TryCatchStatement,
    WhileStatement,
)
from plx.model.task import (
    ContinuousTask,
    EventTask,
    PeriodicTask,
    StartupTask,
    Task,
)
from plx.model.types import (
    AliasType,
    ArrayTypeRef,
    DimensionRange,
    EnumType,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
    StructType,
    SubrangeType,
    TypeDefinition,
    TypeRef,
    UnionType,
)
from plx.model.variables import Variable
from plx.framework._constants import STANDARD_FB_TYPES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(project: Project) -> str:
    """Generate Python framework code from a Universal IR Project as a single string."""
    w = PyWriter(project)
    w.write_project(project)
    return w.getvalue()


def generate_files(project: Project) -> dict[str, str]:
    """Generate Python framework code as multiple files preserving project structure.

    Returns a dict of ``{filename: code}`` with one file per POU, data type,
    and global variable list, plus a ``project.py`` that imports everything
    and assembles the project.  File names mirror the original project structure
    to support round-trip export.
    """
    files: dict[str, str] = {}
    w = PyWriter(project)

    def _prefixed(folder: str, name: str) -> str:
        return f"{folder}/{name}" if folder else name

    # Data types — one file per type
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType, UnionType, AliasType, SubrangeType)):
            fw = PyWriter(project)
            fw._line("from plx.framework import *")
            fw._line()
            fw._write_type_definition(td)
            files[_prefixed(td.folder, f"{td.name}.py")] = fw.getvalue()

    # Global variable lists — one file per GVL
    for gvl in project.global_variable_lists:
        fw = PyWriter(project)
        fw._line("from plx.framework import *")
        fw._line()
        fw._write_global_variable_list(gvl)
        files[_prefixed(gvl.folder, f"{gvl.name}.py")] = fw.getvalue()

    # POUs — one file per POU (methods/actions/properties inline)
    for pou in project.pous:
        fw = PyWriter(project)
        fw._line("from plx.framework import *")

        # Import any types/GVLs/FBs this POU might reference
        deps = _collect_pou_deps(pou, project)
        if deps:
            fw._line()
            for dep_file, dep_names in sorted(deps.items()):
                fw._line(f"from .{dep_file} import {', '.join(sorted(dep_names))}")

        fw._line()
        if pou.pou_type == POUType.INTERFACE:
            fw._write_interface(pou)
        else:
            fw._write_pou(pou)
        files[_prefixed(pou.folder, f"{pou.name}.py")] = fw.getvalue()

    # project.py — imports + task definitions + project() call
    pw = PyWriter()
    pw._line("from plx.framework import *")

    # Import all definitions from sibling files
    def _module_path(folder: str, name: str) -> str:
        if folder:
            return "." + folder.replace("/", ".") + "." + name
        return "." + name

    all_names: list[str] = []
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType)):
            pw._line(f"from {_module_path(td.folder, td.name)} import {td.name}")
            all_names.append(td.name)
    for gvl in project.global_variable_lists:
        pw._line(f"from {_module_path(gvl.folder, gvl.name)} import {gvl.name}")
        all_names.append(gvl.name)
    for pou in project.pous:
        pw._line(f"from {_module_path(pou.folder, pou.name)} import {pou.name}")
        all_names.append(pou.name)

    pw._line()
    pw._write_project_assembly(project)
    files["project.py"] = pw.getvalue()

    return files


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
    BinaryOp.AND_THEN: "and",   # Python and/or are already short-circuit
    BinaryOp.OR_ELSE: "or",
}

# IEC primitive → Python type name.  Use uppercase IEC names for lossless
# round-trip (DINT and INT are distinct types; both mapped to "int" is lossy).

# Python precedence (higher = binds tighter)
_BINOP_PRECEDENCE: dict[BinaryOp, int] = {
    BinaryOp.BOR: 7,
    BinaryOp.OR: 1,
    BinaryOp.OR_ELSE: 1,
    BinaryOp.XOR: 8,
    BinaryOp.BAND: 9,
    BinaryOp.AND: 3,
    BinaryOp.AND_THEN: 3,
    BinaryOp.EQ: 4,
    BinaryOp.NE: 4,
    BinaryOp.LT: 5,
    BinaryOp.GT: 5,
    BinaryOp.LE: 5,
    BinaryOp.GE: 5,
    BinaryOp.ADD: 6,
    BinaryOp.SUB: 6,
    BinaryOp.MUL: 7,
    BinaryOp.DIV: 7,
    BinaryOp.MOD: 7,
    BinaryOp.EXPT: 8,
    # Function-call style
    BinaryOp.SHL: 0,
    BinaryOp.SHR: 0,
    BinaryOp.ROL: 0,
    BinaryOp.ROR: 0,
}

_FUNC_CALL_OPS = {BinaryOp.SHL, BinaryOp.SHR, BinaryOp.ROL, BinaryOp.ROR}

# IEC functions → Python builtins / math module
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
    r"(\d+(?:\.\d+)?)\s*(ms|us|h|m(?!s)|s)",
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

    # Enum literal: EnumType#MEMBER → EnumType.MEMBER
    if "#" in value and not value.startswith("16#") and not value.startswith("8#"):
        parts = value.split("#", 1)
        if parts[0] and parts[1] and parts[0][0].isalpha():
            return f"{parts[0]}.{parts[1]}"

    # Numeric — try int then float
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

    # String literal — pass through
    if value.startswith("'") or value.startswith('"'):
        return value

    # IEC FB/struct initialization: (Param := Value, ...) → dict(Param=Value, ...)
    fb_init = _try_format_fb_init(value)
    if fb_init is not None:
        return fb_init

    # Empty array/struct initializer
    if value in ("[]", "{}"):
        return value

    # Not representable as a Python literal (function calls, complex
    # expressions, etc.) — return None so callers use Field(initial=...).
    return None


def _try_format_fb_init(value: str) -> str | None:
    """Convert IEC FB init ``(A := 1, B := TRUE)`` to ``dict(A=1, B=True)``.

    Returns None if the value doesn't match the pattern.
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
            return None  # Not a named param — bail
        name, _, val = part.partition(":=")
        name = name.strip()
        val = val.strip()
        if not name or not val:
            return None
        # Recursively format the value
        py_val = _format_initial_value(val)
        py_params.append(f"{name}={py_val}")

    return f"dict({', '.join(py_params)})"


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
# PyWriter
# ---------------------------------------------------------------------------

class PyWriter:
    """Walks IR models and emits Python framework code into an internal buffer."""

    def __init__(self, project: Project | None = None) -> None:
        self._buf = StringIO()
        self._indent = 0
        self._indent_str = "    "
        self._self_vars: set[str] = set()
        self._self_methods: set[str] = set()
        self._non_self_names: set[str] = set()
        self._has_unresolved_parent: bool = False
        self._return_var: str | None = None  # property/function name → return rewrite
        self._project = project

    def getvalue(self) -> str:
        return self._buf.getvalue().rstrip("\n") + "\n"

    # -- Low-level output helpers -------------------------------------------

    def _write(self, text: str) -> None:
        self._buf.write(text)

    def _line(self, text: str = "") -> None:
        if text:
            self._buf.write(self._indent_str * self._indent + text + "\n")
        else:
            self._buf.write("\n")

    def _indent_inc(self) -> None:
        self._indent += 1

    def _indent_dec(self) -> None:
        self._indent = max(0, self._indent - 1)

    # ======================================================================
    # Project
    # ======================================================================

    def write_project(self, proj: Project) -> None:
        self._line("from plx.framework import *")
        self._line()

        # Collect POU names for identifier reference
        pou_names = {p.name for p in proj.pous}

        # Data types
        for td in proj.data_types:
            self._write_type_definition(td)
            self._line()

        # Global variable lists
        for gvl in proj.global_variable_lists:
            self._write_global_variable_list(gvl)
            self._line()

        # POUs sorted: FUNCTIONs first, then FUNCTION_BLOCKs (respecting extends),
        # then PROGRAMs. INTERFACEs as comments.
        functions = [p for p in proj.pous if p.pou_type == POUType.FUNCTION]
        fbs = [p for p in proj.pous if p.pou_type == POUType.FUNCTION_BLOCK]
        programs = [p for p in proj.pous if p.pou_type == POUType.PROGRAM]
        interfaces = [p for p in proj.pous if p.pou_type == POUType.INTERFACE]

        # Sort FBs by extends dependency
        fbs = _topo_sort_fbs(fbs)

        for iface in interfaces:
            self._write_interface(iface)
            self._line()

        for pou in functions:
            self._write_pou(pou)
            self._line()

        for pou in fbs:
            self._write_pou(pou)
            self._line()

        for pou in programs:
            self._write_pou(pou)
            self._line()

        # Tasks and project assembly
        self._write_project_assembly(proj)

    # ======================================================================
    # Type definitions
    # ======================================================================

    def _write_type_definition(self, td: TypeDefinition) -> None:
        if isinstance(td, StructType):
            self._write_struct(td)
        elif isinstance(td, EnumType):
            self._write_enum(td)
        elif isinstance(td, UnionType):
            self._line(f"# UnionType '{td.name}' — not supported in framework")
            for m in td.members:
                self._line(f"#   {m.name}: {self._type_ref(m.data_type)}")
        elif isinstance(td, AliasType):
            self._line(
                f"# AliasType '{td.name}' = {self._type_ref(td.base_type)}"
                f" — not supported in framework"
            )
        elif isinstance(td, SubrangeType):
            self._line(
                f"# SubrangeType '{td.name}': {td.base_type.value}"
                f"({td.lower_bound}..{td.upper_bound})"
                f" — not supported in framework"
            )

    def _write_struct(self, td: StructType) -> None:
        self._line("@struct")
        self._line(f"class {td.name}:")
        self._indent_inc()
        if not td.members:
            self._line("pass")
        for m in td.members:
            type_str = self._type_ref(m.data_type)
            if m.initial_value is not None:
                self._line(f"{m.name}: {type_str} = {_format_initial_value(m.initial_value)}")
            else:
                self._line(f"{m.name}: {type_str}")
        self._indent_dec()

    def _write_enum(self, td: EnumType) -> None:
        if td.base_type is not None:
            self._line(f"@enumeration(base_type={td.base_type.value})")
        else:
            self._line("@enumeration")
        self._line(f"class {td.name}:")
        self._indent_inc()
        if not td.members:
            self._line("pass")
        next_val = 0
        for m in td.members:
            if m.value is not None:
                self._line(f"{m.name} = {m.value}")
                next_val = m.value + 1
            else:
                self._line(f"{m.name} = {next_val}")
                next_val += 1
        self._indent_dec()

    # ======================================================================
    # Global variable lists
    # ======================================================================

    def _write_global_variable_list(self, gvl: GlobalVariableList) -> None:
        # Header comment from metadata
        self._write_header_comment(gvl.metadata)

        # Decorator
        decorator_args: list[str] = []
        if gvl.description:
            decorator_args.append(f'description="{gvl.description}"')
        if gvl.folder:
            decorator_args.append(f'folder="{gvl.folder}"')
        if gvl.scope:
            decorator_args.append(f'scope="{gvl.scope}"')

        if decorator_args:
            self._line(f"@global_vars({', '.join(decorator_args)})")
        else:
            self._line("@global_vars")

        self._line(f"class {gvl.name}:")
        self._indent_inc()

        if not gvl.variables:
            self._line("pass")
            self._indent_dec()
            return

        for v in gvl.variables:
            self._write_global_var(v)

        self._indent_dec()

    def _write_global_var(self, v: Variable) -> None:
        """Emit a single global variable declaration."""
        type_str = self._type_ref(v.data_type)

        if self._has_metadata(v):
            field_args = self._build_field_kwargs(v)
            self._line(f"{v.name}: {type_str} = Field({field_args})")
        elif v.initial_value is not None:
            self._line(f"{v.name}: {type_str} = {_format_initial_value(v.initial_value)}")
        else:
            self._line(f"{v.name}: {type_str}")

    # ======================================================================
    # POUs
    # ======================================================================

    def _write_header_comment(self, metadata: dict) -> None:
        """Emit header_comment from metadata as Python # comments."""
        header = metadata.get("header_comment")
        if header:
            for line in header.splitlines():
                self._line(f"# {line}" if line else "#")

    def _write_pou(self, pou: POU) -> None:
        # Build self_vars set from own interface + inherited vars
        self._self_vars = _build_self_vars(pou.interface)
        self._self_methods = {m.name for m in pou.methods}
        self._has_unresolved_parent = False

        if pou.extends and self._project is not None:
            inherited_vars, inherited_methods, resolved = _build_inherited_self_context(
                pou.extends, self._project.pous,
            )
            self._self_vars |= inherited_vars
            self._self_methods |= inherited_methods
            if not resolved:
                self._has_unresolved_parent = True
        elif pou.extends:
            # No project context — assume unresolved
            self._has_unresolved_parent = True

        # Build non-self names for unresolved parent heuristic
        self._non_self_names = _build_non_self_names(pou, self._project)

        if pou.sfc_body is not None:
            self._write_sfc_pou(pou)
            return

        # Header comment from metadata
        self._write_header_comment(pou.metadata)

        # Decorator
        decorator = _POU_DECORATOR[pou.pou_type]
        self._line(f"@{decorator}")

        # Class header
        if pou.extends:
            self._line(f"class {pou.name}({pou.extends}):")
        else:
            self._line(f"class {pou.name}:")

        self._indent_inc()

        # Variable declarations
        has_vars = self._write_var_descriptors(pou.interface)

        # Methods
        for m in pou.methods:
            if has_vars:
                self._line()
            self._write_method(m)
            has_vars = True

        # Properties
        for prop in pou.properties:
            if has_vars:
                self._line()
            self._write_property(prop)
            has_vars = True

        # Actions — commented
        for action in pou.actions:
            if has_vars:
                self._line()
            self._write_action_comment(action)
            has_vars = True

        # logic() method
        if has_vars:
            self._line()

        if pou.pou_type == POUType.FUNCTION and pou.return_type is not None:
            self._line(f"def logic(self) -> {self._type_ref(pou.return_type)}:")
        else:
            self._line("def logic(self):")

        self._indent_inc()
        stmts = []
        for net in pou.networks:
            if net.comment:
                stmts.append(("comment", net.comment))
            for s in net.statements:
                stmts.append(("stmt", s))

        if not stmts:
            self._line("pass")
        else:
            for i, (kind, item) in enumerate(stmts):
                if kind == "comment":
                    if i > 0:
                        self._line()
                    for comment_line in item.split("\n"):
                        self._line(f"# {comment_line}")
                else:
                    self._write_stmt(item)

        self._indent_dec()
        self._indent_dec()

    def _write_interface(self, pou: POU) -> None:
        """Emit an INTERFACE POU as valid @interface code."""
        self._line("@interface")
        if pou.extends:
            self._line(f"class {pou.name}({pou.extends}):")
        else:
            self._line(f"class {pou.name}:")
        self._indent_inc()

        has_content = False

        # Method stubs
        for m in pou.methods:
            if has_content:
                self._line()
            if m.access != AccessSpecifier.PUBLIC:
                self._line(f"@method(access=AccessSpecifier.{m.access.value})")
            else:
                self._line("@method")
            params: list[str] = ["self"]
            for v in m.interface.input_vars:
                params.append(f"{v.name}: {self._type_ref(v.data_type)}")
            ret = f" -> {self._type_ref(m.return_type)}" if m.return_type else ""
            self._line(f"def {m.name}({', '.join(params)}){ret}: ...")
            has_content = True

        # Property stubs
        for prop in pou.properties:
            if has_content:
                self._line()
            kwargs: list[str] = []
            if prop.access != AccessSpecifier.PUBLIC:
                kwargs.append(f"access=AccessSpecifier.{prop.access.value}")
            if prop.abstract:
                kwargs.append("abstract=True")
            if prop.final:
                kwargs.append("final=True")
            type_str = self._type_ref(prop.data_type)
            if kwargs:
                self._line(f"@fb_property({type_str}, {', '.join(kwargs)})")
            else:
                self._line(f"@fb_property({type_str})")
            self._line(f"def {prop.name}(self): ...")
            has_content = True

        if not has_content:
            self._line("pass")

        self._indent_dec()

    # ======================================================================
    # Variable descriptors
    # ======================================================================

    def _write_var_descriptors(self, iface: POUInterface) -> bool:
        """Emit variable declarations. Returns True if any were emitted."""
        any_emitted = False
        for v in iface.input_vars:
            self._write_annotation_var(v, "Input")
            any_emitted = True
        for v in iface.output_vars:
            self._write_annotation_var(v, "Output")
            any_emitted = True
        for v in iface.inout_vars:
            self._write_annotation_var(v, "InOut")
            any_emitted = True
        for v in iface.static_vars:
            self._write_static_var(v)
            any_emitted = True
        for v in iface.temp_vars:
            self._write_annotation_var(v, "Temp")
            any_emitted = True
        for v in iface.constant_vars:
            self._write_annotation_var(v, "Constant")
            any_emitted = True
        for v in iface.external_vars:
            self._write_annotation_var(v, "External")
            any_emitted = True
        return any_emitted

    def _has_metadata(self, v: Variable, *, skip_constant: bool = False) -> bool:
        """Check if a variable has metadata beyond initial value."""
        constant_flag = v.constant and not skip_constant
        return bool(v.description or v.retain or v.persistent or constant_flag)

    def _build_field_kwargs(self, v: Variable, *, skip_constant: bool = False) -> str:
        """Build Field() argument string from variable metadata."""
        kwargs: list[str] = []
        if v.initial_value is not None:
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None:
                kwargs.append(f"initial={formatted}")
            else:
                kwargs.append(f"initial={repr(v.initial_value)}")
        if v.description:
            kwargs.append(f'description="{v.description}"')
        if v.retain:
            kwargs.append("retain=True")
        if v.persistent:
            kwargs.append("persistent=True")
        if v.constant and not skip_constant:
            kwargs.append("constant=True")
        return ", ".join(kwargs)

    def _write_annotation_var(self, v: Variable, wrapper: str) -> None:
        """Emit annotation syntax, using Field() when metadata is present."""
        type_str = self._type_ref(v.data_type)
        # Constant[T] already implies constant=True — don't repeat it in Field()
        skip_constant = wrapper == "Constant"
        if self._has_metadata(v, skip_constant=skip_constant):
            field_args = self._build_field_kwargs(v, skip_constant=skip_constant)
            self._line(f"{v.name}: {wrapper}[{type_str}] = Field({field_args})")
        elif v.initial_value is not None:
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None:
                self._line(f"{v.name}: {wrapper}[{type_str}] = {formatted}")
            else:
                self._line(f"{v.name}: {wrapper}[{type_str}] = Field(initial={repr(v.initial_value)})")
        else:
            self._line(f"{v.name}: {wrapper}[{type_str}]")

    def _write_static_var(self, v: Variable) -> None:
        """Emit a static variable, using shorthand for standard FB types."""
        if isinstance(v.data_type, NamedTypeRef) and v.data_type.name in STANDARD_FB_TYPES:
            # Standard FB instance: timer: TON
            if not self._has_metadata(v) and v.initial_value is None:
                self._line(f"{v.name}: {v.data_type.name}")
                return
        # With metadata → use Field()
        if self._has_metadata(v):
            type_str = self._type_ref(v.data_type)
            field_args = self._build_field_kwargs(v)
            self._line(f"{v.name}: {type_str} = Field({field_args})")
            return
        # Simple annotation
        type_str = self._type_ref(v.data_type)
        if v.initial_value is not None:
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None:
                self._line(f"{v.name}: {type_str} = {formatted}")
            else:
                self._line(f"{v.name}: {type_str} = Field(initial={repr(v.initial_value)})")
        else:
            self._line(f"{v.name}: {type_str}")

    # ======================================================================
    # Methods
    # ======================================================================

    def _write_method(self, m: Method) -> None:
        # Build self_vars for this method's scope
        method_self_vars = _build_self_vars(m.interface)
        # Method scope includes parent self_vars + own vars
        saved_self_vars = self._self_vars
        self._self_vars = saved_self_vars | method_self_vars

        # Add method input/inout params and temp vars to non-self names
        saved_non_self = self._non_self_names
        method_non_self = {v.name for v in m.interface.input_vars}
        method_non_self |= {v.name for v in m.interface.inout_vars}
        method_non_self |= {v.name for v in m.interface.temp_vars}
        self._non_self_names = saved_non_self | method_non_self

        # Decorator
        if m.access != AccessSpecifier.PUBLIC:
            self._line(f"@method(access=AccessSpecifier.{m.access.value})")
        else:
            self._line("@method")

        # Signature — input and inout params go in the method signature
        params: list[str] = ["self"]
        for v in m.interface.input_vars:
            params.append(f"{v.name}: {self._type_ref(v.data_type)}")
        for v in m.interface.inout_vars:
            params.append(f"{v.name}: {self._type_ref(v.data_type)}")

        ret = f" -> {self._type_ref(m.return_type)}" if m.return_type else ""
        self._line(f"def {m.name}({', '.join(params)}){ret}:")

        self._indent_inc()

        # Non-input/inout vars as local declarations
        for v in m.interface.output_vars:
            self._write_annotation_var(v, "Output")
        for v in m.interface.static_vars:
            self._write_annotation_var(v, "Static")
        for v in m.interface.temp_vars:
            self._write_annotation_var(v, "Temp")

        stmts = []
        for net in m.networks:
            if net.comment:
                stmts.append(("comment", net.comment))
            for s in net.statements:
                stmts.append(("stmt", s))

        if not stmts and not m.interface.output_vars and not m.interface.static_vars and not m.interface.temp_vars:
            self._line("pass")
        elif stmts:
            for i, (kind, item) in enumerate(stmts):
                if kind == "comment":
                    if i > 0:
                        self._line()
                    for comment_line in item.split("\n"):
                        self._line(f"# {comment_line}")
                else:
                    self._write_stmt(item)

        self._indent_dec()
        self._self_vars = saved_self_vars
        self._non_self_names = saved_non_self

    def _write_property(self, prop: Property) -> None:
        """Emit a property as valid @fb_property code."""
        # Build decorator kwargs
        kwargs: list[str] = []
        if prop.access != AccessSpecifier.PUBLIC:
            kwargs.append(f"access=AccessSpecifier.{prop.access.value}")
        if prop.abstract:
            kwargs.append("abstract=True")
        if prop.final:
            kwargs.append("final=True")

        type_str = self._type_ref(prop.data_type)
        if kwargs:
            self._line(f"@fb_property({type_str}, {', '.join(kwargs)})")
        else:
            self._line(f"@fb_property({type_str})")

        # Save/restore self_vars for property scope
        saved_self_vars = self._self_vars

        # Getter — assignments to property name become return statements
        self._line(f"def {prop.name}(self):")
        self._indent_inc()
        saved_return_var = self._return_var
        self._return_var = prop.name
        if prop.getter is not None:
            # Include local_vars if present
            for v in prop.getter.local_vars:
                self._write_annotation_var(v, "Temp")
            stmts = []
            for net in prop.getter.networks:
                if net.comment:
                    stmts.append(("comment", net.comment))
                for s in net.statements:
                    stmts.append(("stmt", s))
            if not stmts:
                self._line("pass")
            else:
                for i, (kind, item) in enumerate(stmts):
                    if kind == "comment":
                        if i > 0:
                            self._line()
                        for comment_line in item.split("\n"):
                            self._line(f"# {comment_line}")
                    else:
                        self._write_stmt(item)
        else:
            self._line("pass")
        self._return_var = saved_return_var
        self._indent_dec()

        # Setter
        if prop.setter is not None:
            self._line()
            self._line(f"@{prop.name}.setter")
            self._line(f"def {prop.name}(self, {prop.name}: {type_str}):")
            self._indent_inc()
            for v in prop.setter.local_vars:
                self._write_annotation_var(v, "Temp")
            stmts = []
            for net in prop.setter.networks:
                if net.comment:
                    stmts.append(("comment", net.comment))
                for s in net.statements:
                    stmts.append(("stmt", s))
            if not stmts:
                self._line("pass")
            else:
                for i, (kind, item) in enumerate(stmts):
                    if kind == "comment":
                        if i > 0:
                            self._line()
                        for comment_line in item.split("\n"):
                            self._line(f"# {comment_line}")
                    else:
                        self._write_stmt(item)
            self._indent_dec()

        self._self_vars = saved_self_vars

    def _write_action_comment(self, action: POUAction) -> None:
        """Emit a POU action as a commented stub."""
        self._line(f"# ACTION {action.name}")

    # ======================================================================
    # SFC POUs
    # ======================================================================

    def _write_sfc_pou(self, pou: POU) -> None:
        sfc = pou.sfc_body
        assert sfc is not None

        # Header comment from metadata
        self._write_header_comment(pou.metadata)

        self._line("@sfc")
        if pou.extends:
            self._line(f"class {pou.name}({pou.extends}):")
        else:
            self._line(f"class {pou.name}:")
        self._indent_inc()

        # Variable declarations (non-SFC vars)
        self._write_var_descriptors(pou.interface)

        # Steps
        if pou.interface.input_vars or pou.interface.output_vars or pou.interface.static_vars:
            self._line()
        for s in sfc.steps:
            if s.is_initial:
                self._line(f"{s.name} = step(initial=True)")
            else:
                self._line(f"{s.name} = step()")

        # Step actions
        for s in sfc.steps:
            # Entry actions
            for action in s.entry_actions:
                self._line()
                self._write_sfc_action(s.name, action, "entry")

            # Main (N-qualified) actions
            for action in s.actions:
                self._line()
                self._write_sfc_action(s.name, action, "action")

            # Exit actions
            for action in s.exit_actions:
                self._line()
                self._write_sfc_action(s.name, action, "exit")

        # Transitions
        for trans in sfc.transitions:
            self._line()
            self._write_sfc_transition(trans)

        self._indent_dec()

    def _write_sfc_action(self, step_name: str, action: Action, slot: str) -> None:
        """Emit a step action method."""
        if slot == "entry":
            self._line(f"@{step_name}.entry")
        elif slot == "exit":
            self._line(f"@{step_name}.exit")
        else:
            # Regular action — check qualifier
            if action.qualifier != ActionQualifier.N:
                q_args = f'qualifier="{action.qualifier.value}"'
                if action.duration:
                    dur = _parse_iec_time(action.duration)
                    q_args += f", duration={dur or repr(action.duration)}"
                self._line(f"@{step_name}.action({q_args})")
            else:
                self._line(f"@{step_name}.action")

        method_name = action.name
        self._line(f"def {method_name}(self):")
        self._indent_inc()
        if action.body:
            for stmt in action.body:
                self._write_stmt(stmt)
        else:
            self._line("pass")
        self._indent_dec()

    def _write_sfc_transition(self, trans: Transition) -> None:
        """Emit an SFC transition."""
        # Build path expression
        src = _step_group_expr(trans.source_steps)
        tgt = _step_group_expr(trans.target_steps)
        path = f"{src} >> {tgt}"

        self._line(f"@transition({path})")
        # Use a name derived from source/target
        name = f"{'_'.join(trans.source_steps)}_to_{'_'.join(trans.target_steps)}"
        self._line(f"def {name}(self):")
        self._indent_inc()
        self._line(f"return {self._expr(trans.condition)}")
        self._indent_dec()

    # ======================================================================
    # Type references
    # ======================================================================

    def _type_ref(self, tr: TypeRef) -> str:
        if isinstance(tr, PrimitiveTypeRef):
            return tr.type.value
        if isinstance(tr, StringTypeRef):
            base = "WSTRING" if tr.wide else "STRING"
            if tr.max_length is not None:
                return f"{base}({tr.max_length})"
            return base
        if isinstance(tr, NamedTypeRef):
            return tr.name
        if isinstance(tr, ArrayTypeRef):
            return self._array_type_ref(tr)
        if isinstance(tr, PointerTypeRef):
            return f"POINTER_TO({self._type_ref(tr.target_type)})"
        if isinstance(tr, ReferenceTypeRef):
            return f"REFERENCE_TO({self._type_ref(tr.target_type)})"
        return "???"

    def _array_type_ref(self, tr: ArrayTypeRef) -> str:
        elem = self._type_ref(tr.element_type)
        dims: list[str] = []
        for d in tr.dimensions:
            lower_is_int = isinstance(d.lower, int)
            upper_is_int = isinstance(d.upper, int)
            if lower_is_int and upper_is_int:
                if d.lower == 0 and d.upper == -1:
                    # Variable-length array (ARRAY[*] OF T)
                    continue
                elif d.lower == 0:
                    # Simple size: ARRAY(INT, 10) for 0..9
                    dims.append(str(d.upper + 1))
                else:
                    # Explicit bounds: ARRAY(INT, (1, 10))
                    dims.append(f"({d.lower}, {d.upper})")
            else:
                # Expression-based bounds — emit without self. prefix since
                # array dimensions reference GVL constants, not instance vars
                saved = self._self_vars
                self._self_vars = set()
                lower_str = str(d.lower) if lower_is_int else self._expr(d.lower)
                upper_str = str(d.upper) if upper_is_int else self._expr(d.upper)
                self._self_vars = saved
                dims.append(f"({lower_str}, {upper_str})")
        if not dims:
            return f"ARRAY({elem})"
        return f"ARRAY({elem}, {', '.join(dims)})"

    # ======================================================================
    # Statements
    # ======================================================================

    def _write_stmt(self, stmt: Statement) -> None:
        if stmt.comment:
            for cline in stmt.comment.split("\n"):
                self._line(f"# {cline}" if cline else "#")
        handler = _STMT_WRITERS.get(stmt.kind)
        if handler is not None:
            handler(self, stmt)
        else:
            self._line(f"# Unsupported statement: {stmt.kind}")

    # BinaryOp → Python augmented-assignment operator for ``x = x + y`` → ``x += y``
    _AUGOP: dict[BinaryOp, str] = {
        BinaryOp.ADD: "+=",
        BinaryOp.SUB: "-=",
        BinaryOp.MUL: "*=",
        BinaryOp.DIV: "/=",
        BinaryOp.MOD: "%=",
        BinaryOp.XOR: "^=",
        BinaryOp.BAND: "&=",
        BinaryOp.BOR: "|=",
        BinaryOp.SHL: "<<=",
        BinaryOp.SHR: ">>=",
        BinaryOp.EXPT: "**=",
    }

    def _write_assignment(self, stmt: Assignment) -> None:
        # Property/function return: ``PropName = expr`` → ``return expr``
        if (self._return_var is not None
                and isinstance(stmt.target, VariableRef)
                and stmt.target.name == self._return_var):
            self._line(f"return {self._expr(stmt.value)}")
            return
        # S=/R= latch assignments have no Python framework equivalent
        if stmt.latch:
            self._line(f"# {self._expr(stmt.target)} {stmt.latch}= {self._expr(stmt.value)}")
            return
        # Recover augmented assignment: ``x = x + y`` → ``x += y``
        if isinstance(stmt.value, BinaryExpr):
            aug = self._AUGOP.get(stmt.value.op)
            if aug is not None and stmt.value.left == stmt.target:
                self._line(f"{self._expr(stmt.target)} {aug} {self._expr(stmt.value.right)}")
                return
        self._line(f"{self._expr(stmt.target)} = {self._expr(stmt.value)}")

    def _write_if(self, stmt: IfStatement) -> None:
        self._line(f"if {self._expr(stmt.if_branch.condition)}:")
        self._indent_inc()
        self._write_body(stmt.if_branch.body)
        self._indent_dec()

        for branch in stmt.elsif_branches:
            self._line(f"elif {self._expr(branch.condition)}:")
            self._indent_inc()
            self._write_body(branch.body)
            self._indent_dec()

        if stmt.else_body:
            self._line("else:")
            self._indent_inc()
            self._write_body(stmt.else_body)
            self._indent_dec()

    def _write_case(self, stmt: CaseStatement) -> None:
        # Check if any branch has ranges — if so, use if/elif
        has_ranges = any(b.ranges for b in stmt.branches)

        if has_ranges:
            self._write_case_as_if(stmt)
        else:
            self._write_case_as_match(stmt)

    def _write_case_as_match(self, stmt: CaseStatement) -> None:
        self._line(f"match {self._expr(stmt.selector)}:")
        self._indent_inc()
        for branch in stmt.branches:
            labels: list[str] = []
            for v in branch.values:
                if isinstance(v, str):
                    # Enum reference: E_State.Idle → use as-is (Python dotted name)
                    labels.append(v)
                else:
                    labels.append(str(v))
            pattern = " | ".join(labels) if labels else "_"
            self._line(f"case {pattern}:")
            self._indent_inc()
            self._write_body(branch.body)
            self._indent_dec()

        if stmt.else_body:
            self._line("case _:")
            self._indent_inc()
            self._write_body(stmt.else_body)
            self._indent_dec()

        self._indent_dec()

    def _write_case_as_if(self, stmt: CaseStatement) -> None:
        sel = self._expr(stmt.selector)
        first = True
        for branch in stmt.branches:
            cond = _case_branch_condition(sel, branch)
            keyword = "if" if first else "elif"
            self._line(f"{keyword} {cond}:")
            self._indent_inc()
            self._write_body(branch.body)
            self._indent_dec()
            first = False

        if stmt.else_body:
            self._line("else:")
            self._indent_inc()
            self._write_body(stmt.else_body)
            self._indent_dec()

    def _write_for(self, stmt: ForStatement) -> None:
        from_str = self._expr(stmt.from_expr)

        # IEC FOR is inclusive; Python range() is exclusive. Pre-compute
        # the +1 when the upper bound is an integer literal so we emit
        # clean ``range(1, 6)`` instead of ``range(1, 5 + 1)``.
        if (isinstance(stmt.to_expr, LiteralExpr)
                and stmt.to_expr.data_type is None):
            try:
                to_val = int(stmt.to_expr.value)
                to_str = str(to_val + 1)
            except ValueError:
                to_str = f"{self._expr(stmt.to_expr)} + 1"
        else:
            to_str = f"{self._expr(stmt.to_expr)} + 1"

        if stmt.by_expr is not None:
            by_str = self._expr(stmt.by_expr)
            self._line(f"for {stmt.loop_var} in range({from_str}, {to_str}, {by_str}):")
        else:
            self._line(f"for {stmt.loop_var} in range({from_str}, {to_str}):")

        self._indent_inc()
        self._write_body(stmt.body)
        self._indent_dec()

    def _write_while(self, stmt: WhileStatement) -> None:
        self._line(f"while {self._expr(stmt.condition)}:")
        self._indent_inc()
        self._write_body(stmt.body)
        self._indent_dec()

    def _write_repeat(self, stmt: RepeatStatement) -> None:
        self._line("while True:")
        self._indent_inc()
        for s in stmt.body:
            self._write_stmt(s)
        self._line(f"if {self._expr(stmt.until)}:")
        self._indent_inc()
        self._line("break")
        self._indent_dec()
        self._indent_dec()

    def _write_exit(self, _stmt: ExitStatement) -> None:
        self._line("break")

    def _write_continue(self, _stmt: ContinueStatement) -> None:
        self._line("continue")

    def _write_return(self, stmt: ReturnStatement) -> None:
        if stmt.value is not None:
            self._line(f"return {self._expr(stmt.value)}")
        else:
            self._line("return")

    def _write_function_call_stmt(self, stmt: FunctionCallStatement) -> None:
        name = stmt.function_name
        # Beckhoff OOP: SUPER^.Method() → super().Method()
        if name.startswith("SUPER^."):
            name = f"super().{name[7:]}"
        elif name.startswith("THIS^."):
            name = f"self.{name[6:]}"
        else:
            name = _FUNC_REMAP.get(name, name)
            name = self._qualify_function_name(name)
        args = self._call_args_str(stmt.args)
        self._line(f"{name}({args})")

    def _qualify_function_name(self, name: str) -> str:
        """Add self. prefix to function/method names that need it."""
        # Dotted name: Instance.Method() — qualify the first part
        if "." in name:
            first, rest = name.split(".", 1)
            if first in self._self_vars:
                return f"self.{name}"
            if self._has_unresolved_parent and first not in self._non_self_names:
                return f"self.{name}"
            return name
        # Simple name: own/inherited method
        if name in self._self_methods:
            return f"self.{name}"
        if self._has_unresolved_parent and name not in self._non_self_names:
            return f"self.{name}"
        return name

    def _write_fb_invocation(self, stmt: FBInvocation) -> None:
        # Emit: self.instance(IN=val, PT=val)
        if isinstance(stmt.instance_name, str):
            instance = f"self.{stmt.instance_name}" if stmt.instance_name in self._self_vars else stmt.instance_name
        else:
            instance = self._expr(stmt.instance_name)
        parts: list[str] = []
        for name, expr in stmt.inputs.items():
            parts.append(f"{name}={self._expr(expr)}")
        args = ", ".join(parts)
        self._line(f"{instance}({args})")

        # Output assignments on separate lines
        for name, expr in stmt.outputs.items():
            self._line(f"{self._expr(expr)} = {instance}.{name}")

    def _write_empty(self, stmt: EmptyStatement) -> None:
        if not stmt.comment:
            self._line("pass")

    def _write_try_catch(self, stmt: TryCatchStatement) -> None:
        # No Python framework equivalent — emit as ST-style comment block
        self._line("# __TRY")
        self._indent_inc()
        for s in stmt.try_body:
            self._write_stmt(s)
        self._indent_dec()
        if stmt.catch_body or stmt.catch_var is not None:
            catch_header = "# __CATCH"
            if stmt.catch_var is not None:
                catch_header += f"({stmt.catch_var})"
            self._line(catch_header)
            self._indent_inc()
            for s in stmt.catch_body:
                self._write_stmt(s)
            self._indent_dec()
        if stmt.finally_body:
            self._line("# __FINALLY")
            self._indent_inc()
            for s in stmt.finally_body:
                self._write_stmt(s)
            self._indent_dec()
        self._line("# __ENDTRY")

    def _write_jump(self, stmt: JumpStatement) -> None:
        self._line(f"# JMP {stmt.label}")

    def _write_label(self, stmt: LabelStatement) -> None:
        self._line(f"# {stmt.name}:")

    def _write_body(self, body: list[Statement]) -> None:
        """Write a statement list, emitting 'pass' if empty."""
        if not body:
            self._line("pass")
        else:
            for s in body:
                self._write_stmt(s)

    # ======================================================================
    # Expressions
    # ======================================================================

    def _expr(self, expr: Expression, parent_prec: int = 0) -> str:
        handler = _EXPR_WRITERS.get(expr.kind)
        if handler is not None:
            return handler(self, expr, parent_prec)
        return f"# unsupported: {expr.kind}"

    def _expr_literal(self, expr: LiteralExpr, _prec: int) -> str:
        v = expr.value
        if v == "TRUE":
            return "True"
        if v == "FALSE":
            return "False"

        # IEC time literal
        time_repr = _parse_iec_time(v)
        if time_repr is not None:
            return time_repr

        # Enum literal: Type#MEMBER → Type.MEMBER
        if "#" in v and not v.startswith("16#") and not v.startswith("8#"):
            parts = v.split("#", 1)
            if parts[0] and parts[1] and parts[0][0].isalpha():
                return f"{parts[0]}.{parts[1]}"

        # Numeric
        try:
            int(v)
            return v
        except ValueError:
            pass
        try:
            float(v)
            return v
        except ValueError:
            pass

        return v

    def _expr_variable_ref(self, expr: VariableRef, _prec: int) -> str:
        if expr.name == "SUPER^":
            return "super()"
        if expr.name == "THIS^":
            return "self"
        if expr.name in self._self_vars:
            return f"self.{expr.name}"
        # For FBs with unresolved parents (library inheritance), assume
        # unknown names are inherited instance vars unless they're clearly
        # non-self (temp vars, type names, global functions, etc.)
        if self._has_unresolved_parent and expr.name not in self._non_self_names:
            return f"self.{expr.name}"
        return expr.name

    def _expr_binary(self, expr: BinaryExpr, parent_prec: int) -> str:
        # Function-call style ops
        if expr.op in _FUNC_CALL_OPS:
            return f"{expr.op.value}({self._expr(expr.left)}, {self._expr(expr.right)})"

        my_prec = _BINOP_PRECEDENCE.get(expr.op, 0)
        symbol = _BINOP_PYTHON.get(expr.op, expr.op.value)
        left = self._expr(expr.left, my_prec)
        right = self._expr(expr.right, my_prec + 1)
        result = f"{left} {symbol} {right}"
        if my_prec < parent_prec:
            return f"({result})"
        return result

    def _expr_unary(self, expr: UnaryExpr, _prec: int) -> str:
        operand = self._expr(expr.operand, 10)
        if expr.op == UnaryOp.NEG:
            return f"-{operand}"
        if expr.op == UnaryOp.NOT:
            return f"not {operand}"
        if expr.op == UnaryOp.BNOT:
            return f"~{operand}"
        return f"{expr.op.value}({operand})"

    def _expr_function_call(self, expr: FunctionCallExpr, _prec: int) -> str:
        if expr.function_name == "CONCAT":
            fstr = self._try_reconstruct_fstring(expr)
            if fstr is not None:
                return fstr
        # LIMIT(mn, val, mx) → math.clamp(val, mn, mx)
        if expr.function_name == "LIMIT" and len(expr.args) == 3:
            mn = self._expr(expr.args[0].value, 0)
            val = self._expr(expr.args[1].value, 0)
            mx = self._expr(expr.args[2].value, 0)
            return f"math.clamp({val}, {mn}, {mx})"
        # TRUNC(a / b) → a // b
        if expr.function_name == "TRUNC" and len(expr.args) == 1:
            inner = expr.args[0].value
            if isinstance(inner, BinaryExpr) and inner.op == BinaryOp.DIV:
                left = self._expr(inner.left, 5)
                right = self._expr(inner.right, 6)
                return f"{left} // {right}"
        name = expr.function_name
        # Beckhoff OOP: SUPER^.Method() → super().Method()
        if name.startswith("SUPER^."):
            name = f"super().{name[7:]}"
        elif name.startswith("THIS^."):
            name = f"self.{name[6:]}"
        else:
            name = _FUNC_REMAP.get(name, name)
        args = self._call_args_str(expr.args)
        return f"{name}({args})"

    def _try_reconstruct_fstring(self, expr: FunctionCallExpr) -> str | None:
        """Try to reconstruct an f-string from a CONCAT(...) call.

        Returns ``f"..."`` string if all args are positional and representable,
        ``None`` otherwise (caller falls back to raw CONCAT).
        """
        if any(a.name is not None for a in expr.args):
            return None  # named args — not from f-string

        parts: list[str] = []
        all_literal = True
        for arg in expr.args:
            val = arg.value
            if isinstance(val, LiteralExpr) and val.value.startswith("'") and val.value.endswith("'"):
                text = val.value[1:-1]
                if '"' in text:
                    return None  # can't safely embed in f"..."
                parts.append(text.replace("{", "{{").replace("}", "}}"))
            elif isinstance(val, TypeConversionExpr) and isinstance(val.target_type, StringTypeRef):
                # Strip the *_TO_STRING conversion — f-string handles it
                all_literal = False
                parts.append(f"{{{self._expr(val.source)}}}")
            else:
                # Already-string expression — embed directly
                all_literal = False
                parts.append(f"{{{self._expr(val)}}}")

        if all_literal:
            # Pure string concatenation with no interpolations — just join
            return f"'{''.join(parts)}'"

        return f'f"{"".join(parts)}"'

    def _expr_array_access(self, expr: ArrayAccessExpr, _prec: int) -> str:
        indices = ", ".join(self._expr(i) for i in expr.indices)
        return f"{self._expr(expr.array, 10)}[{indices}]"

    def _expr_member_access(self, expr: MemberAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.struct, 10)}.{expr.member}"

    def _expr_bit_access(self, expr: BitAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.target, 10)}.bit{expr.bit_index}"

    def _expr_type_conversion(self, expr: TypeConversionExpr, _prec: int) -> str:
        # Type conversions are implicit in the Python DSL — variable declarations
        # carry the type info, and the raise pass inserts explicit conversions
        # when compiling to vendor ST.
        return self._expr(expr.source, _prec)

    def _expr_substring(self, expr: SubstringExpr, _prec: int) -> str:
        s = self._expr(expr.string)
        start = self._expr(expr.start) if expr.start is not None else ""
        end = self._expr(expr.end) if expr.end is not None else ""
        return f"{s}[{start}:{end}]"

    def _expr_system_flag(self, expr: SystemFlagExpr, _prec: int) -> str:
        if expr.flag == SystemFlag.FIRST_SCAN:
            return "first_scan()"
        return f"# unknown flag: {expr.flag}"

    def _call_args_str(self, args: list) -> str:
        """Render call args with positional args before named args.

        ST allows positional args after named args; Python does not.
        """
        positional = [a for a in args if a.name is None]
        named = [a for a in args if a.name is not None]
        parts = [self._expr(a.value) for a in positional]
        parts += [f"{a.name}={self._expr(a.value)}" for a in named]
        return ", ".join(parts)

    # ======================================================================
    # Project assembly
    # ======================================================================

    def _write_project_assembly(self, proj: Project) -> None:
        # Task definitions
        task_var_names: list[str] = []
        for t in proj.tasks:
            var_name = _sanitize_identifier(t.name)
            task_var_names.append(var_name)
            self._write_task(t, var_name)

        # project() call
        kwargs: list[str] = []

        pou_names = [p.name for p in proj.pous if p.pou_type != POUType.INTERFACE]
        if pou_names:
            kwargs.append(f"pous=[{', '.join(pou_names)}]")

        dt_names = [td.name for td in proj.data_types
                    if isinstance(td, (StructType, EnumType))]
        if dt_names:
            kwargs.append(f"data_types=[{', '.join(dt_names)}]")

        gvl_names = [gvl.name for gvl in proj.global_variable_lists]
        if gvl_names:
            kwargs.append(f"global_var_lists=[{', '.join(gvl_names)}]")

        if task_var_names:
            kwargs.append(f"tasks=[{', '.join(task_var_names)}]")

        if kwargs:
            args_str = ",\n    ".join(kwargs)
            self._line(f'proj = project("{proj.name}",')
            self._line(f"    {args_str},")
            self._line(")")
        else:
            self._line(f'proj = project("{proj.name}")')

    def _write_task(self, t: Task, var_name: str) -> None:
        kwargs: list[str] = []

        if isinstance(t, PeriodicTask):
            interval = _parse_iec_time(t.interval)
            if interval:
                kwargs.append(f"periodic={interval}")
            else:
                kwargs.append(f'periodic="{t.interval}"')
        elif isinstance(t, ContinuousTask):
            kwargs.append("continuous=True")
        elif isinstance(t, EventTask):
            kwargs.append(f'event="{t.trigger_variable}"')
        elif isinstance(t, StartupTask):
            kwargs.append("startup=True")

        if t.assigned_pous:
            kwargs.append(f"pous=[{', '.join(t.assigned_pous)}]")

        if t.priority != 0:
            kwargs.append(f"priority={t.priority}")

        args = ", ".join(kwargs)
        self._line(f'{var_name} = task("{t.name}", {args})')
        self._line()


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

_STMT_WRITERS = {
    "assignment": PyWriter._write_assignment,
    "if": PyWriter._write_if,
    "case": PyWriter._write_case,
    "for": PyWriter._write_for,
    "while": PyWriter._write_while,
    "repeat": PyWriter._write_repeat,
    "exit": PyWriter._write_exit,
    "continue": PyWriter._write_continue,
    "return": PyWriter._write_return,
    "function_call_stmt": PyWriter._write_function_call_stmt,
    "fb_invocation": PyWriter._write_fb_invocation,
    "empty": PyWriter._write_empty,
    "try_catch": PyWriter._write_try_catch,
    "jump": PyWriter._write_jump,
    "label": PyWriter._write_label,
}

_EXPR_WRITERS = {
    "literal": PyWriter._expr_literal,
    "variable_ref": PyWriter._expr_variable_ref,
    "binary": PyWriter._expr_binary,
    "unary": PyWriter._expr_unary,
    "function_call": PyWriter._expr_function_call,
    "array_access": PyWriter._expr_array_access,
    "member_access": PyWriter._expr_member_access,
    "bit_access": PyWriter._expr_bit_access,
    "type_conversion": PyWriter._expr_type_conversion,
    "substring": PyWriter._expr_substring,
    "system_flag": PyWriter._expr_system_flag,
}

_POU_DECORATOR = {
    POUType.FUNCTION_BLOCK: "fb",
    POUType.PROGRAM: "program",
    POUType.FUNCTION: "function",
}


# ---------------------------------------------------------------------------
# Helpers
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
    parent_name: str, all_pous: list[POU],
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
# a self. prefix. This is intentionally non-exhaustive — when the parent is
# fully resolved, the heuristic is not needed.
_KNOWN_GLOBAL_FUNCTIONS: frozenset[str] = frozenset({
    # IEC standard functions
    "ABS", "SQRT", "LN", "LOG", "EXP", "SIN", "COS", "TAN",
    "ASIN", "ACOS", "ATAN", "ATAN2",
    "CEIL", "FLOOR", "TRUNC", "ROUND",
    "MIN", "MAX", "LIMIT", "SEL", "MUX",
    "SHL", "SHR", "ROL", "ROR",
    "LEN", "LEFT", "RIGHT", "MID", "FIND", "REPLACE", "INSERT", "DELETE",
    "CONCAT", "SIZEOF", "ADR", "ADRINST",
    "MEMSET", "MEMCPY", "MEMMOVE",
    "AND", "OR", "XOR", "NOT",
    # Python builtins used in plx
    "abs", "min", "max", "len", "round", "range", "print",
    # Common Beckhoff system functions
    "F_GetActualDcTime64", "F_CreateAllEventsInClass", "F_GetMaxSeverityRaised",
    "F_RaiseAlarmWithStringParameters", "F_UnitModeToString",
})


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
    names |= set(STANDARD_FB_TYPES)

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
            parts.append(f"{sel} == {v}")
        else:
            parts.append(f"{sel} == {v}")
    for r in branch.ranges:
        parts.append(f"{r.start} <= {sel} <= {r.end}")
    return " or ".join(parts) if parts else "True"


def _sanitize_identifier(name: str) -> str:
    """Convert a task/POU name to a valid Python identifier."""
    result = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if result and result[0].isdigit():
        result = "_" + result
    return result


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


def _collect_pou_deps(pou: POU, project: Project) -> dict[str, list[str]]:
    """Collect cross-file dependencies for a POU.

    Returns {module_name: [imported_names]} for sibling file imports.
    Only includes names that correspond to project-level definitions
    (data types, GVLs, other POUs).
    """
    # Build lookup of what's defined where
    def _mod(folder: str, name: str) -> str:
        if folder:
            return folder.replace("/", ".") + "." + name
        return name

    project_names: dict[str, str] = {}  # name → module_path (dotted)
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
    for var_list in (
        pou.interface.input_vars, pou.interface.output_vars,
        pou.interface.inout_vars, pou.interface.static_vars,
        pou.interface.temp_vars, pou.interface.constant_vars,
        pou.interface.external_vars,
    ):
        for v in var_list:
            referenced |= _collect_named_refs(v.data_type)

    # extends reference
    if pou.extends:
        referenced.add(pou.extends)

    # implements references
    for iface_name in pou.implements:
        referenced.add(iface_name)

    # Filter to project-level names only
    deps: dict[str, list[str]] = {}
    for name in referenced:
        if name in project_names and name not in STANDARD_FB_TYPES:
            module = project_names[name]
            deps.setdefault(module, []).append(name)

    return deps

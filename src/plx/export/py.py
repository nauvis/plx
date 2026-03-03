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
    RepeatStatement,
    ReturnStatement,
    Statement,
    WhileStatement,
)
from plx.model.task import Task, TaskType
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
    w = PyWriter()
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
    w = PyWriter()

    # Data types — one file per type
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType, UnionType, AliasType, SubrangeType)):
            fw = PyWriter()
            fw._line("from plx.framework import *")
            fw._line()
            fw._write_type_definition(td)
            files[f"{td.name}.py"] = fw.getvalue()

    # Global variable lists — one file per GVL
    for gvl in project.global_variable_lists:
        fw = PyWriter()
        fw._line("from plx.framework import *")
        fw._line()
        fw._write_global_variable_list(gvl)
        files[f"{gvl.name}.py"] = fw.getvalue()

    # POUs — one file per POU (methods/actions/properties inline)
    for pou in project.pous:
        fw = PyWriter()
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
        files[f"{pou.name}.py"] = fw.getvalue()

    # project.py — imports + task definitions + project() call
    pw = PyWriter()
    pw._line("from plx.framework import *")

    # Import all definitions from sibling files
    all_names: list[str] = []
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType)):
            pw._line(f"from .{td.name} import {td.name}")
            all_names.append(td.name)
    for gvl in project.global_variable_lists:
        pw._line(f"from .{gvl.name} import {gvl.name}")
        all_names.append(gvl.name)
    for pou in project.pous:
        pw._line(f"from .{pou.name} import {pou.name}")
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
    BinaryOp.EQ: "==",
    BinaryOp.NE: "!=",
    BinaryOp.GT: ">",
    BinaryOp.GE: ">=",
    BinaryOp.LT: "<",
    BinaryOp.LE: "<=",
    BinaryOp.EXPT: "**",
}

# Python precedence (higher = binds tighter)
_BINOP_PRECEDENCE: dict[BinaryOp, int] = {
    BinaryOp.OR: 1,
    BinaryOp.XOR: 2,
    BinaryOp.AND: 3,
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

# IEC functions → Python builtins
_FUNC_REMAP: dict[str, str] = {
    "ABS": "abs",
    "MIN": "min",
    "MAX": "max",
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
    """Parse an IEC time literal like T#100ms into T(ms=100).

    Returns None if not a time literal.
    """
    if not re.match(r"^(?:L?TIME#|[LT]#)", value, re.IGNORECASE):
        return None

    is_ltime = value.upper().startswith("LTIME#") or value.upper().startswith("LT#")
    prefix = "LT" if is_ltime else "T"

    # Extract units
    parts: dict[str, str] = {}
    for match in _IEC_TIME_UNIT_RE.finditer(value):
        amount = match.group(1)
        unit = match.group(2).lower()
        if unit == "h":
            parts["hours"] = amount
        elif unit == "m":
            parts["minutes"] = amount
        elif unit == "s":
            parts["seconds"] = amount
        elif unit == "ms":
            parts["ms"] = amount
        elif unit == "us":
            parts["us"] = amount

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

    return f"{prefix}({', '.join(kwargs)})"


def _format_initial_value(value: str) -> str:
    """Convert an IEC initial value string to Python literal."""
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

    return repr(value)


# ---------------------------------------------------------------------------
# PyWriter
# ---------------------------------------------------------------------------

class PyWriter:
    """Walks IR models and emits Python framework code into an internal buffer."""

    def __init__(self) -> None:
        self._buf = StringIO()
        self._indent = 0
        self._indent_str = "    "
        self._self_vars: set[str] = set()

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
        for m in td.members:
            if m.value is not None:
                self._line(f"{m.name} = {m.value}")
            else:
                self._line(f"{m.name} = auto()")
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
        # Build self_vars set
        self._self_vars = _build_self_vars(pou.interface)

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
            for kind, item in stmts:
                if kind == "comment":
                    self._line(f"# {item}")
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

    def _has_metadata(self, v: Variable) -> bool:
        """Check if a variable has metadata beyond initial value."""
        return bool(v.description or v.retain or v.persistent or v.address is not None or v.constant)

    def _build_field_kwargs(self, v: Variable) -> str:
        """Build Field() argument string from variable metadata."""
        kwargs: list[str] = []
        if v.initial_value is not None:
            kwargs.append(f"initial={_format_initial_value(v.initial_value)}")
        if v.description:
            kwargs.append(f'description="{v.description}"')
        if v.retain:
            kwargs.append("retain=True")
        if v.persistent:
            kwargs.append("persistent=True")
        if v.address is not None:
            kwargs.append(f'address="{v.address}"')
        if v.constant:
            kwargs.append("constant=True")
        return ", ".join(kwargs)

    def _write_annotation_var(self, v: Variable, wrapper: str) -> None:
        """Emit annotation syntax, using Field() when metadata is present."""
        type_str = self._type_ref(v.data_type)
        if self._has_metadata(v):
            field_args = self._build_field_kwargs(v)
            self._line(f"{v.name}: {wrapper}[{type_str}] = Field({field_args})")
        elif v.initial_value is not None:
            self._line(f"{v.name}: {wrapper}[{type_str}] = {_format_initial_value(v.initial_value)}")
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
            self._line(f"{v.name}: {type_str} = {_format_initial_value(v.initial_value)}")
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

        # Decorator
        if m.access != AccessSpecifier.PUBLIC:
            self._line(f"@method(access=AccessSpecifier.{m.access.value})")
        else:
            self._line("@method")

        # Signature
        params: list[str] = ["self"]
        for v in m.interface.input_vars:
            params.append(f"{v.name}: {self._type_ref(v.data_type)}")

        ret = f" -> {self._type_ref(m.return_type)}" if m.return_type else ""
        self._line(f"def {m.name}({', '.join(params)}){ret}:")

        self._indent_inc()

        # Non-input vars as local declarations
        for v in m.interface.output_vars:
            self._write_annotation_var(v, "Output")
        for v in m.interface.inout_vars:
            self._write_annotation_var(v, "InOut")
        for v in m.interface.static_vars:
            self._write_static_var(v)
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
            for kind, item in stmts:
                if kind == "comment":
                    self._line(f"# {item}")
                else:
                    self._write_stmt(item)

        self._indent_dec()
        self._self_vars = saved_self_vars

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

        # Getter
        self._line(f"def {prop.name}(self):")
        self._indent_inc()
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
                for kind, item in stmts:
                    if kind == "comment":
                        self._line(f"# {item}")
                    else:
                        self._write_stmt(item)
        else:
            self._line("pass")
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
                for kind, item in stmts:
                    if kind == "comment":
                        self._line(f"# {item}")
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

    # Python builtin names for default PLC types
    _PYTHON_TYPE_NAMES = {
        PrimitiveType.BOOL: "bool",
        PrimitiveType.DINT: "int",
        PrimitiveType.REAL: "float",
    }

    def _type_ref(self, tr: TypeRef) -> str:
        if isinstance(tr, PrimitiveTypeRef):
            return self._PYTHON_TYPE_NAMES.get(tr.type, tr.type.value)
        if isinstance(tr, StringTypeRef):
            # STRING[255] → str (default max-length string)
            if not tr.wide and tr.max_length == 255:
                return "str"
            base = "WSTRING" if tr.wide else "STRING"
            if tr.max_length is not None:
                return f"{base}({tr.max_length})"
            return f"{base}()"
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
            if d.lower == 0:
                # Simple size: ARRAY(INT, 10) for 0..9
                dims.append(str(d.upper + 1))
            else:
                # Explicit bounds: ARRAY(INT, (1, 10))
                dims.append(f"({d.lower}, {d.upper})")
        return f"ARRAY({elem}, {', '.join(dims)})"

    # ======================================================================
    # Statements
    # ======================================================================

    def _write_stmt(self, stmt: Statement) -> None:
        handler = _STMT_WRITERS.get(stmt.kind)
        if handler is not None:
            handler(self, stmt)
        else:
            self._line(f"# Unsupported statement: {stmt.kind}")

    def _write_assignment(self, stmt: Assignment) -> None:
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
            values = [str(v) for v in branch.values]
            pattern = " | ".join(values) if values else "_"
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
        to_str = self._expr(stmt.to_expr)

        # Reverse the compiler's to - 1 transform: IR stores exclusive upper bound
        # Actually, IEC FOR is inclusive, and the framework compiler emits
        # to_expr as the user's inclusive bound. We need range(from, to + 1).
        if stmt.by_expr is not None:
            by_str = self._expr(stmt.by_expr)
            self._line(f"for {stmt.loop_var} in range({from_str}, {to_str} + 1, {by_str}):")
        else:
            self._line(f"for {stmt.loop_var} in range({from_str}, {to_str} + 1):")

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
        name = _FUNC_REMAP.get(stmt.function_name, stmt.function_name)
        args = ", ".join(self._call_arg(a) for a in stmt.args)
        self._line(f"{name}({args})")

    def _write_fb_invocation(self, stmt: FBInvocation) -> None:
        # Emit: self.instance(IN=val, PT=val)
        instance = f"self.{stmt.instance_name}" if stmt.instance_name in self._self_vars else stmt.instance_name
        parts: list[str] = []
        for name, expr in stmt.inputs.items():
            parts.append(f"{name}={self._expr(expr)}")
        args = ", ".join(parts)
        self._line(f"{instance}({args})")

        # Output assignments on separate lines
        for name, expr in stmt.outputs.items():
            self._line(f"{self._expr(expr)} = {instance}.{name}")

    def _write_empty(self, _stmt: EmptyStatement) -> None:
        self._line("pass")

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
        if expr.name in self._self_vars:
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
        return f"{expr.op.value}({operand})"

    def _expr_function_call(self, expr: FunctionCallExpr, _prec: int) -> str:
        name = _FUNC_REMAP.get(expr.function_name, expr.function_name)
        args = ", ".join(self._call_arg(a) for a in expr.args)
        return f"{name}({args})"

    def _expr_array_access(self, expr: ArrayAccessExpr, _prec: int) -> str:
        indices = ", ".join(self._expr(i) for i in expr.indices)
        return f"{self._expr(expr.array, 10)}[{indices}]"

    def _expr_member_access(self, expr: MemberAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.struct, 10)}.{expr.member}"

    def _expr_bit_access(self, expr: BitAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.target, 10)}.bit{expr.bit_index}"

    def _expr_type_conversion(self, expr: TypeConversionExpr, _prec: int) -> str:
        target = self._type_ref(expr.target_type)
        source_type = ""
        # For type conversions, emit SRCTYPE_TO_TARGETTYPE(expr)
        # We don't always know the source type, so just emit target(expr)
        return f"{target}({self._expr(expr.source)})"

    def _expr_system_flag(self, expr: SystemFlagExpr, _prec: int) -> str:
        if expr.flag == SystemFlag.FIRST_SCAN:
            return "first_scan()"
        return f"# unknown flag: {expr.flag}"

    def _call_arg(self, arg) -> str:
        if arg.name is not None:
            return f"{arg.name}={self._expr(arg.value)}"
        return self._expr(arg.value)

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

        if t.task_type == TaskType.PERIODIC and t.interval:
            interval = _parse_iec_time(t.interval)
            if interval:
                kwargs.append(f"periodic={interval}")
            else:
                kwargs.append(f'periodic="{t.interval}"')
        elif t.task_type == TaskType.CONTINUOUS:
            kwargs.append("continuous=True")
        elif t.task_type == TaskType.EVENT and t.trigger_variable:
            kwargs.append(f'event="{t.trigger_variable}"')
        elif t.task_type == TaskType.STARTUP:
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
    project_names: dict[str, str] = {}  # name → module_name (file stem)
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType, UnionType, AliasType, SubrangeType)):
            project_names[td.name] = td.name
    for gvl in project.global_variable_lists:
        project_names[gvl.name] = gvl.name
    for p in project.pous:
        if p.name != pou.name:
            project_names[p.name] = p.name

    # Collect all NamedTypeRef references from this POU's interface
    referenced: set[str] = set()
    for var_list in (
        pou.interface.input_vars, pou.interface.output_vars,
        pou.interface.inout_vars, pou.interface.static_vars,
        pou.interface.temp_vars, pou.interface.constant_vars,
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

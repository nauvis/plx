"""STWriter class -- composed from expression and statement mixins."""

from __future__ import annotations

from io import StringIO

from plx.model.expressions import Expression
from plx.model.pou import (
    POU,
    AccessSpecifier,
    Method,
    POUAction,
    POUInterface,
    POUType,
    Property,
)
from plx.model.project import GlobalVariableList, Project
from plx.model.sfc import Action, ActionQualifier, SFCBody, Step
from plx.model.types import (
    AliasType,
    ArrayTypeRef,
    DimensionRange,
    EnumType,
    NamedTypeRef,
    PointerTypeRef,
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

from ._expressions import _ExpressionWriterMixin
from ._statements import _StatementWriterMixin


class STWriter(_ExpressionWriterMixin, _StatementWriterMixin):
    """Walks IR models and emits Structured Text into an internal buffer."""

    def __init__(self) -> None:
        self._buf = StringIO()
        self._indent = 0
        self._indent_str = "    "

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
        """Write a complete project: type definitions, GVLs, then POUs."""
        first = True

        # Type definitions
        for td in proj.data_types:
            if not first:
                self._line()
            self.write_type_definition(td)
            first = False

        # Global variable lists
        for gvl in proj.global_variable_lists:
            if not first:
                self._line()
            self.write_global_variable_list(gvl)
            first = False

        # POUs
        for pou in proj.pous:
            if not first:
                self._line()
            self.write_pou(pou)
            first = False

    # ======================================================================
    # Type definitions
    # ======================================================================

    def write_type_definition(self, td: TypeDefinition) -> None:
        """Write a TYPE ... END_TYPE block (struct, enum, union, alias, or subrange)."""
        if isinstance(td, StructType):
            self._write_struct_type(td)
        elif isinstance(td, EnumType):
            self._write_enum_type(td)
        elif isinstance(td, UnionType):
            self._write_union_type(td)
        elif isinstance(td, AliasType):
            self._write_alias_type(td)
        elif isinstance(td, SubrangeType):
            self._write_subrange_type(td)

    def _write_struct_type(self, td: StructType) -> None:
        if td.extends:
            self._line(f"TYPE {td.name} EXTENDS {td.extends} :")
        else:
            self._line(f"TYPE {td.name} :")
        self._line("STRUCT")
        self._indent_inc()
        for m in td.members:
            decl = f"{m.name} : {self._type_ref(m.data_type)}"
            if m.initial_value is not None:
                decl += f" := {m.initial_value}"
            decl += ";"
            self._line(decl)
        self._indent_dec()
        self._line("END_STRUCT")
        self._line("END_TYPE")

    def _write_enum_type(self, td: EnumType) -> None:
        members = []
        for m in td.members:
            if m.value is not None:
                members.append(f"{m.name} := {m.value}")
            else:
                members.append(m.name)
        member_str = ", ".join(members)
        if td.base_type is not None:
            self._line(f"TYPE {td.name} : {td.base_type.value} (")
        else:
            self._line(f"TYPE {td.name} : (")
        self._indent_inc()
        self._line(f"{member_str}")
        self._indent_dec()
        self._line(");")
        self._line("END_TYPE")

    def _write_union_type(self, td: UnionType) -> None:
        self._line(f"TYPE {td.name} :")
        self._line("UNION")
        self._indent_inc()
        for m in td.members:
            decl = f"{m.name} : {self._type_ref(m.data_type)}"
            if m.initial_value is not None:
                decl += f" := {m.initial_value}"
            decl += ";"
            self._line(decl)
        self._indent_dec()
        self._line("END_UNION")
        self._line("END_TYPE")

    def _write_alias_type(self, td: AliasType) -> None:
        self._line(f"TYPE {td.name} : {self._type_ref(td.base_type)};")
        self._line("END_TYPE")

    def _write_subrange_type(self, td: SubrangeType) -> None:
        self._line(f"TYPE {td.name} : {td.base_type.value}({td.lower_bound}..{td.upper_bound});")
        self._line("END_TYPE")

    # ======================================================================
    # Global variable lists
    # ======================================================================

    def write_global_variable_list(self, gvl: GlobalVariableList) -> None:
        if gvl.description:
            self._line(f"// {gvl.description}")
        if gvl.qualified_only:
            self._line("{attribute 'qualified_only'}")
        self._line("VAR_GLOBAL")
        self._indent_inc()
        for v in gvl.variables:
            self._write_var_decl(v)
        self._indent_dec()
        self._line("END_VAR")

    # ======================================================================
    # POU
    # ======================================================================

    def write_pou(self, pou: POU) -> None:
        """Write a POU with header, var blocks, body, actions, methods, and properties."""
        if pou.pou_type == POUType.INTERFACE:
            self._write_interface_pou(pou)
            return

        # Header
        base_keyword = pou.pou_type.value
        keyword = f"{base_keyword} ABSTRACT" if pou.abstract else base_keyword
        header = f"{keyword} {pou.name}"
        if pou.extends:
            header += f" EXTENDS {pou.extends}"
        if pou.implements:
            header += f" IMPLEMENTS {', '.join(pou.implements)}"
        if pou.return_type is not None:
            header += f" : {self._type_ref(pou.return_type)}"
        self._line(header)

        # Variable blocks
        self._write_var_blocks(pou.interface)

        # Body
        if pou.sfc_body is not None:
            self._write_sfc_body(pou.sfc_body)
        else:
            self._write_networks(pou.networks)

        # End
        self._line(f"END_{base_keyword}")

        # Actions (after POU body, before methods)
        for action in pou.actions:
            self._line()
            self._write_pou_action(pou.name, action)

        # Methods
        for method in pou.methods:
            self._line()
            self._write_method(method)

        # Properties
        for prop in pou.properties:
            self._line()
            self._write_property(prop)

    def _write_interface_pou(self, pou: POU) -> None:
        self._line(f"INTERFACE {pou.name}")
        if pou.extends:
            self._line(f"EXTENDS {pou.extends}")
        for method in pou.methods:
            self._line()
            self._write_method(method, interface_only=True)
        for prop in pou.properties:
            self._line()
            self._write_property(prop, interface_only=True)
        self._line("END_INTERFACE")

    # ======================================================================
    # Variable declarations
    # ======================================================================

    def _write_var_blocks(self, iface: POUInterface) -> None:
        self._write_var_block("VAR_INPUT", iface.input_vars)
        self._write_var_block("VAR_OUTPUT", iface.output_vars)
        self._write_var_block("VAR_IN_OUT", iface.inout_vars)
        self._write_var_block("VAR", iface.static_vars)
        self._write_var_block("VAR_TEMP", iface.temp_vars)
        self._write_var_block("VAR CONSTANT", iface.constant_vars)
        self._write_var_block("VAR_EXTERNAL", iface.external_vars)

    def _write_var_block(self, keyword: str, variables: list[Variable]) -> None:
        if not variables:
            return
        self._line(keyword)
        self._indent_inc()
        for v in variables:
            self._write_var_decl(v)
        self._indent_dec()
        self._line("END_VAR")

    def _write_var_decl(self, v: Variable) -> None:
        parts = []
        if v.retain:
            parts.append("RETAIN")
        if v.persistent:
            parts.append("PERSISTENT")

        decl = f"{v.name} : {self._type_ref(v.data_type)}"
        if v.initial_value is not None:
            decl += f" := {v.initial_value}"
        decl += ";"
        if v.description:
            decl += f" // {v.description}"

        if parts:
            self._line(f"{' '.join(parts)} {decl}")
        else:
            self._line(decl)

    # ======================================================================
    # Type references
    # ======================================================================

    def _type_ref(self, tr: TypeRef) -> str:
        """Format a TypeRef as an IEC 61131-3 type string."""
        if isinstance(tr, PrimitiveTypeRef):
            return tr.type.value
        if isinstance(tr, StringTypeRef):
            base = "WSTRING" if tr.wide else "STRING"
            if tr.max_length is not None:
                return f"{base}[{tr.max_length}]"
            return base
        if isinstance(tr, NamedTypeRef):
            return tr.name
        if isinstance(tr, ArrayTypeRef):
            dims = ", ".join(self._dim_range(d) for d in tr.dimensions)
            return f"ARRAY[{dims}] OF {self._type_ref(tr.element_type)}"
        if isinstance(tr, PointerTypeRef):
            return f"POINTER TO {self._type_ref(tr.target_type)}"
        if isinstance(tr, ReferenceTypeRef):
            return f"REFERENCE TO {self._type_ref(tr.target_type)}"
        raise TypeError(f"Unhandled TypeRef kind: {type(tr).__name__}")

    def _dim_range(self, d: DimensionRange) -> str:
        def _bound(b: int | Expression) -> str:
            if isinstance(b, int):
                return str(b)
            return self._expr(b)
        return f"{_bound(d.lower)}..{_bound(d.upper)}"

    # ======================================================================
    # SFC body
    # ======================================================================

    def _write_sfc_body(self, sfc: SFCBody) -> None:
        for step_obj in sfc.steps:
            self._write_sfc_step(step_obj)
            self._line()

        for trans in sfc.transitions:
            src = ", ".join(trans.source_steps)
            tgt = ", ".join(trans.target_steps)
            self._line(f"TRANSITION FROM {src} TO {tgt}")
            self._indent_inc()
            self._line(f":= {self._expr(trans.condition)};")
            self._indent_dec()
            self._line("END_TRANSITION")
            self._line()

    def _write_sfc_step(self, step_obj: Step) -> None:
        keyword = "INITIAL_STEP" if step_obj.is_initial else "STEP"
        self._line(f"{keyword} {step_obj.name}:")

        self._indent_inc()
        # Entry actions
        for action in step_obj.entry_actions:
            self._write_sfc_action_association(action, "entry")
        # Main actions
        for action in step_obj.actions:
            self._write_sfc_action_association(action)
        # Exit actions
        for action in step_obj.exit_actions:
            self._write_sfc_action_association(action, "exit")
        self._indent_dec()

        self._line("END_STEP")

    def _write_sfc_action_association(self, action: Action, phase: str | None = None) -> None:
        qualifier = action.qualifier.value
        if action.duration:
            qualifier += f", {action.duration}"
        name = action.action_name or action.name
        if phase:
            self._line(f"{name}({qualifier}); // {phase}")
        else:
            self._line(f"{name}({qualifier});")

    # ======================================================================
    # POU actions
    # ======================================================================

    def _write_pou_action(self, pou_name: str, action: POUAction) -> None:
        self._line(f"ACTION {pou_name}.{action.name}:")
        self._indent_inc()
        self._write_networks(action.body)
        self._indent_dec()
        self._line("END_ACTION")

    # ======================================================================
    # Methods and properties
    # ======================================================================

    def _write_method(self, method: Method, interface_only: bool = False) -> None:
        header = f"METHOD"
        if method.access != AccessSpecifier.PUBLIC:
            header += f" {method.access.value}"
        if method.abstract:
            header += " ABSTRACT"
        if method.final:
            header += " FINAL"
        header += f" {method.name}"
        if method.return_type is not None:
            header += f" : {self._type_ref(method.return_type)}"
        self._line(header)

        if interface_only:
            self._write_var_blocks(method.interface)
            self._line("END_METHOD")
            return

        self._write_var_blocks(method.interface)

        if method.sfc_body is not None:
            self._write_sfc_body(method.sfc_body)
        else:
            self._write_networks(method.networks)

        self._line("END_METHOD")

    def _write_property(self, prop: Property, interface_only: bool = False) -> None:
        header = f"PROPERTY"
        if prop.access != AccessSpecifier.PUBLIC:
            header += f" {prop.access.value}"
        if prop.abstract:
            header += " ABSTRACT"
        if prop.final:
            header += " FINAL"
        header += f" {prop.name} : {self._type_ref(prop.data_type)}"
        self._line(header)

        if interface_only:
            self._line("END_PROPERTY")
            return

        if prop.getter is not None:
            self._line("GET")
            self._indent_inc()
            self._write_networks(prop.getter.networks)
            self._indent_dec()
            self._line("END_GET")

        if prop.setter is not None:
            self._line("SET")
            self._indent_inc()
            self._write_networks(prop.setter.networks)
            self._indent_dec()
            self._line("END_SET")

        self._line("END_PROPERTY")

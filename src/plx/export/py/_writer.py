"""PyWriter class — composed from expression and statement mixins."""

from __future__ import annotations

import warnings
from io import StringIO

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
from plx.model.statements import Statement
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
from ._helpers import (
    _NAMED_TYPE_PY_NAME,
    _POU_DECORATOR,
    _PRIMITIVE_PY_NAME,
    _build_inherited_self_context,
    _build_non_self_names,
    _build_self_vars,
    _format_initial_value,
    _is_dict_literal,
    _parse_iec_time,
    _quote_string,
    _sanitize_identifier,
    _standard_fb_types,
    _step_group_expr,
    _topo_sort_fbs,
)


class PyWriter(_ExpressionWriterMixin, _StatementWriterMixin):
    """Walks IR models and emits Python framework code into an internal buffer."""

    def __init__(self, project: Project | None = None) -> None:
        self._buf = StringIO()
        self._indent = 0
        self._indent_str = "    "
        self._self_vars: set[str] = set()
        self._self_methods: set[str] = set()
        self._non_self_names: set[str] = set()
        self._has_unresolved_parent: bool = False
        self._return_var: str | None = None  # property/function name -> return rewrite
        self._project = project
        # Collect known type names so we can quote unknown references
        self._known_types: set[str] = set()
        if project:
            for td in project.data_types:
                self._known_types.add(td.name)
            for pou in project.pous:
                self._known_types.add(pou.name)

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
            self._line(f"# UnionType '{td.name}' — no Python framework equivalent")
            for m in td.members:
                self._line(f"#   {m.name}: {self._type_ref(m.data_type)}")
            warnings.warn(
                f"plx export: UnionType '{td.name}' has no Python equivalent — emitted as comment",
                stacklevel=2,
            )
        elif isinstance(td, AliasType):
            self._line(
                f"# AliasType '{td.name}' = {self._type_ref(td.base_type)}"
                f" — no Python framework equivalent"
            )
            warnings.warn(
                f"plx export: AliasType '{td.name}' has no Python equivalent — emitted as comment",
                stacklevel=2,
            )
        elif isinstance(td, SubrangeType):
            self._line(
                f"# SubrangeType '{td.name}': {td.base_type.value}"
                f"({td.lower_bound}..{td.upper_bound})"
                f" — no Python framework equivalent"
            )
            warnings.warn(
                f"plx export: SubrangeType '{td.name}' has no Python equivalent — emitted as comment",
                stacklevel=2,
            )

    def _write_struct(self, td: StructType) -> None:
        self._line("@struct")
        self._line(f"class {td.name}:")
        self._indent_inc()
        if not td.members:
            self._line("pass")
        for m in td.members:
            type_str = self._type_ref(m.data_type)
            mname = _sanitize_identifier(m.name)
            if m.initial_value is not None:
                self._line(f"{mname}: {type_str} = {_format_initial_value(m.initial_value)}")
            else:
                self._line(f"{mname}: {type_str}")
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
            decorator_args.append(f'description={_quote_string(gvl.description)}')
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
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None and _is_dict_literal(formatted):
                self._line(f"{v.name}: {type_str} = Field(initial={formatted})")
            elif formatted is not None:
                self._line(f"{v.name}: {type_str} = {formatted}")
            else:
                self._line(f"{v.name}: {type_str} = Field(initial={repr(v.initial_value)})")
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
            # No project context -- assume unresolved
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

        # Actions -- commented
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
                self._line(f"@fb_method(access=AccessSpecifier.{m.access.value})")
            else:
                self._line("@fb_method")
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
            self._write_static_var(v)
            any_emitted = True
        for v in iface.external_vars:
            self._write_annotation_var(v, "External")
            any_emitted = True
        return any_emitted

    def _has_metadata(self, v: Variable) -> bool:
        """Check if a variable has metadata beyond initial value."""
        return bool(
            v.description or v.retain or v.persistent or v.constant
            or v.metadata.get("hardware") or v.metadata.get("external")
        )

    def _build_field_kwargs(self, v: Variable) -> str:
        """Build Field() argument string from variable metadata."""
        kwargs: list[str] = []
        if v.initial_value is not None:
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None:
                kwargs.append(f"initial={formatted}")
            else:
                kwargs.append(f"initial={repr(v.initial_value)}")
        if v.description:
            kwargs.append(f'description={_quote_string(v.description)}')
        if v.retain:
            kwargs.append("retain=True")
        if v.persistent:
            kwargs.append("persistent=True")
        if v.constant:
            kwargs.append("constant=True")
        hw = v.metadata.get("hardware")
        if hw:
            kwargs.append(f'hardware="{hw}"')
        ext = v.metadata.get("external")
        if ext:
            # "readwrite" -> True (cleaner API), "read" -> "read"
            if ext == "readwrite":
                kwargs.append("external=True")
            else:
                kwargs.append(f'external="{ext}"')
        return ", ".join(kwargs)

    def _write_annotation_var(self, v: Variable, wrapper: str) -> None:
        """Emit annotation syntax, using Field() when metadata is present."""
        type_str = self._type_ref(v.data_type)
        if self._has_metadata(v):
            field_args = self._build_field_kwargs(v)
            self._line(f"{v.name}: {wrapper}[{type_str}] = Field({field_args})")
        elif v.initial_value is not None:
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None and _is_dict_literal(formatted):
                # Structured FB/struct init -> must use Field()
                self._line(f"{v.name}: {wrapper}[{type_str}] = Field(initial={formatted})")
            elif formatted is not None:
                self._line(f"{v.name}: {wrapper}[{type_str}] = {formatted}")
            else:
                self._line(f"{v.name}: {wrapper}[{type_str}] = Field(initial={repr(v.initial_value)})")
        else:
            self._line(f"{v.name}: {wrapper}[{type_str}]")

    def _write_static_var(self, v: Variable) -> None:
        """Emit a static variable, using shorthand for standard FB types."""
        if isinstance(v.data_type, NamedTypeRef) and v.data_type.name in _standard_fb_types():
            # Standard FB instance: timer: ton
            if not self._has_metadata(v) and v.initial_value is None:
                self._line(f"{v.name}: {_NAMED_TYPE_PY_NAME[v.data_type.name]}")
                return
        # With metadata -> use Field()
        if self._has_metadata(v):
            type_str = self._type_ref(v.data_type)
            field_args = self._build_field_kwargs(v)
            self._line(f"{v.name}: {type_str} = Field({field_args})")
            return
        # Simple annotation
        type_str = self._type_ref(v.data_type)
        if v.initial_value is not None:
            formatted = _format_initial_value(v.initial_value)
            if formatted is not None and _is_dict_literal(formatted):
                # Structured FB/struct init -> must use Field()
                self._line(f"{v.name}: {type_str} = Field(initial={formatted})")
            elif formatted is not None:
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
            self._line(f"@fb_method(access=AccessSpecifier.{m.access.value})")
        else:
            self._line("@fb_method")

        # Signature -- input and inout params go in the method signature
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

        # Getter -- assignments to property name become return statements
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
        if action.body:
            warnings.warn(
                f"plx export: POUAction '{action.name}' body cannot be represented in Python "
                f"— emitted as comment",
                stacklevel=2,
            )
            self._line(f"# (body omitted — {len(action.body)} network(s))")

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
            # Regular action -- check qualifier
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
        elif action.action_name and not action.body:
            self._line(f"pass  # references POUAction: {action.action_name}")
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
            return _PRIMITIVE_PY_NAME[tr.type]
        if isinstance(tr, StringTypeRef):
            base = "wstring" if tr.wide else "string"
            if tr.max_length is not None:
                return f"{base}({tr.max_length})"
            return base
        if isinstance(tr, NamedTypeRef):
            mapped = _NAMED_TYPE_PY_NAME.get(tr.name)
            if mapped:
                return mapped
            # If we have project context, quote types not defined in this project
            # to avoid NameError for vendor FBs and cross-file UDT references
            if self._known_types and tr.name not in self._known_types:
                return repr(tr.name)
            return tr.name
        if isinstance(tr, ArrayTypeRef):
            return self._array_type_ref(tr)
        if isinstance(tr, PointerTypeRef):
            return f"pointer_to({self._type_ref(tr.target_type)})"
        if isinstance(tr, ReferenceTypeRef):
            return f"reference_to({self._type_ref(tr.target_type)})"
        raise TypeError(f"Unhandled TypeRef kind: {type(tr).__name__}")

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
                # Expression-based bounds -- emit without self. prefix since
                # array dimensions reference GVL constants, not instance vars
                saved_vars = self._self_vars
                saved_unresolved = self._has_unresolved_parent
                self._self_vars = set()
                self._has_unresolved_parent = False
                lower_str = str(d.lower) if lower_is_int else self._expr(d.lower)
                upper_str = str(d.upper) if upper_is_int else self._expr(d.upper)
                self._self_vars = saved_vars
                self._has_unresolved_parent = saved_unresolved
                dims.append(f"({lower_str}, {upper_str})")
        if not dims:
            return f"array({elem})"
        return f"array({elem}, {', '.join(dims)})"

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

        # project() call -- use explicit pous list for portability
        pou_names = [p.name for p in proj.pous]
        kwargs: list[str] = [f"pous=[{', '.join(pou_names)}]"]

        if task_var_names:
            kwargs.append(f"tasks=[{', '.join(task_var_names)}]")

        args_str = ",\n    ".join(kwargs)
        self._line(f'proj = project("{proj.name}",')
        self._line(f"    {args_str},")
        self._line(")")

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

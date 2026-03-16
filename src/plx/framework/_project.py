"""Project assembly for the plx framework.

Collects compiled POU classes and task definitions, assembles them into
a ``Project`` IR node.
"""

from __future__ import annotations

import warnings
from typing import overload

from plx.model.pou import POU, POUType
from plx.model.project import Project
from plx.model.types import ArrayTypeRef, NamedTypeRef, PointerTypeRef, ReferenceTypeRef
from plx.model.variables import Variable

from ._errors import ProjectAssemblyError
from ._protocols import CompiledDataType, CompiledGlobalVarList, CompiledPOU
from ._registry import lookup_pou, lookup_type
from ._task import PlxTask, _format_interval, task
from ._vendor import CompileResult, Vendor, validate_target


# ---------------------------------------------------------------------------
# Transitive dependency resolution
# ---------------------------------------------------------------------------

_MAX_DEP_ITERATIONS = 10_000


def _collect_named_refs(variables: list[Variable]) -> set[str]:
    """Extract all NamedTypeRef names from a list of variables."""
    names: set[str] = set()
    for var in variables:
        _collect_type_ref_names(var.data_type, names)
    return names


def _collect_type_ref_names(type_ref: object, names: set[str]) -> None:
    """Recursively extract NamedTypeRef names from a TypeRef."""
    if isinstance(type_ref, NamedTypeRef):
        names.add(type_ref.name)
    elif isinstance(type_ref, ArrayTypeRef):
        _collect_type_ref_names(type_ref.element_type, names)
    elif isinstance(type_ref, (PointerTypeRef, ReferenceTypeRef)):
        _collect_type_ref_names(type_ref.target_type, names)


def _resolve_transitive_deps(
    pou_classes: list[type],
    data_type_classes: list[type],
) -> None:
    """Walk compiled POUs to find referenced POUs/types and add them.

    Modifies *pou_classes* and *data_type_classes* in place.  Looks up
    names via the global registry; unresolved names (IEC standard types
    like TON, TOF, etc.) are silently skipped.
    """
    pou_names: set[str] = {c._compiled_pou.name for c in pou_classes if hasattr(c, "_compiled_pou")}
    type_names: set[str] = {c._compiled_type.name for c in data_type_classes if hasattr(c, "_compiled_type")}

    # Queue: POU classes whose dependencies haven't been examined yet
    queue = list(pou_classes)
    iterations = 0
    while queue:
        iterations += 1
        if iterations > _MAX_DEP_ITERATIONS:
            raise ProjectAssemblyError(
                f"Transitive dependency resolution exceeded {_MAX_DEP_ITERATIONS} "
                f"iterations — possible circular dependency or corrupt registry"
            )
        cls = queue.pop()
        if not hasattr(cls, "compile"):
            raise ProjectAssemblyError(f"{cls.__name__} is not a compiled POU")
        pou: POU = cls.compile()

        # Collect all NamedTypeRef names from this POU
        names: set[str] = set()

        # Interface vars (all sections)
        iface = pou.interface
        for var_list in (
            iface.input_vars, iface.output_vars, iface.inout_vars,
            iface.static_vars, iface.temp_vars, iface.constant_vars,
            iface.external_vars,
        ):
            names |= _collect_named_refs(var_list)

        # Methods — their interfaces too
        for m in pou.methods:
            mi = m.interface
            for var_list in (
                mi.input_vars, mi.output_vars, mi.inout_vars,
                mi.static_vars, mi.temp_vars, mi.constant_vars,
                mi.external_vars,
            ):
                names |= _collect_named_refs(var_list)

        # FB inheritance
        if pou.extends:
            names.add(pou.extends)

        # Implements
        for iface_name in pou.implements:
            names.add(iface_name)

        # Resolve each name
        for name in names:
            dep_pou = lookup_pou(name)
            if dep_pou is not None:
                dep_pou_name = dep_pou._compiled_pou.name
                if dep_pou_name in pou_names:
                    warnings.warn(
                        f"plx: duplicate POU name '{dep_pou_name}' — "
                        f"second definition ignored",
                        stacklevel=3,
                    )
                else:
                    pou_classes.append(dep_pou)
                    pou_names.add(dep_pou_name)
                    queue.append(dep_pou)

            dep_type = lookup_type(name)
            if dep_type is not None and dep_type._compiled_type.name not in type_names:
                data_type_classes.append(dep_type)
                type_names.add(dep_type._compiled_type.name)


# ---------------------------------------------------------------------------
# Duplicate name checks
# ---------------------------------------------------------------------------

def _check_duplicates(
    items: list[object], attr: str, label: str, project_name: str
) -> None:
    """Raise ``ProjectAssemblyError`` if any two items share the same name."""
    seen: set[str] = set()
    for item in items:
        name = getattr(item, attr)
        if name in seen:
            raise ProjectAssemblyError(
                f"Duplicate {label} name '{name}' in project '{project_name}'"
            )
        seen.add(name)


# ---------------------------------------------------------------------------
# Project builder
# ---------------------------------------------------------------------------

class PlxProject:
    """Builder for assembling a Project IR from compiled POU classes."""

    def __init__(
        self,
        name: str,
        *,
        pous: list[type] | None = None,
        tasks: list[PlxTask] | None = None,
        data_types: list[type] | None = None,
        global_var_lists: list[type] | None = None,
        packages: list[str] | None = None,
    ) -> None:
        self.name = name
        self._pou_classes: list[type] = list(pous) if pous else []
        self._tasks: list[PlxTask] = list(tasks) if tasks else []
        self._data_type_classes: list[type] = list(data_types) if data_types else []
        self._gvl_classes: list[type] = list(global_var_lists) if global_var_lists else []
        self._packages: list[str] = list(packages) if packages else []

    @overload
    def compile(self, *, target: None = None) -> Project: ...
    @overload
    def compile(self, *, target: Vendor) -> CompileResult: ...

    def compile(self, *, target: Vendor | None = None) -> Project | CompileResult:
        """Compile all registered POUs and data types, return a Project IR node.

        Parameters
        ----------
        target
            Optional vendor target.  When set, a validation pass checks
            that the compiled IR only uses features supported by the
            target vendor (e.g. ``Vendor.AB``).  Raises
            ``VendorValidationError`` if unsupported features are found.
            Returns a ``CompileResult`` wrapping the project and any
            portability warnings.
        """
        # Merge discovered items from packages (if any)
        if self._packages:
            from ._discover import discover
            discovered = discover(*self._packages)
            # Dedup by compiled name — explicit entries take priority
            explicit_pou_names = {c._compiled_pou.name for c in self._pou_classes if hasattr(c, "_compiled_pou")}
            explicit_type_names = {c._compiled_type.name for c in self._data_type_classes if hasattr(c, "_compiled_type")}
            explicit_gvl_names = {c._compiled_gvl.name for c in self._gvl_classes if hasattr(c, "_compiled_gvl")}
            explicit_task_ids = {id(t) for t in self._tasks}
            for cls in discovered.pous:
                if cls._compiled_pou.name not in explicit_pou_names:
                    self._pou_classes.append(cls)
                    explicit_pou_names.add(cls._compiled_pou.name)
            for cls in discovered.data_types:
                if cls._compiled_type.name not in explicit_type_names:
                    self._data_type_classes.append(cls)
                    explicit_type_names.add(cls._compiled_type.name)
            for cls in discovered.global_var_lists:
                if cls._compiled_gvl.name not in explicit_gvl_names:
                    self._gvl_classes.append(cls)
                    explicit_gvl_names.add(cls._compiled_gvl.name)
            for t in discovered.tasks:
                if id(t) not in explicit_task_ids:
                    self._tasks.append(t)
                    explicit_task_ids.add(id(t))

        # Resolve transitive dependencies — auto-include POUs and types
        # referenced via NamedTypeRef in static vars, extends, implements, etc.
        _resolve_transitive_deps(self._pou_classes, self._data_type_classes)

        # Compile data types
        compiled_data_types = []
        for cls in self._data_type_classes:
            # Auto-compile IntEnum types
            from enum import IntEnum
            if isinstance(cls, type) and issubclass(cls, IntEnum) and cls is not IntEnum:
                from ._data_types import _ensure_enum_compiled
                _ensure_enum_compiled(cls)
            if not isinstance(cls, CompiledDataType):
                raise ProjectAssemblyError(
                    f"{cls.__name__} is not a data type "
                    f"(missing @struct or @enumeration decorator)"
                )
            compiled_data_types.append(cls.compile())
        _check_duplicates(compiled_data_types, "name", "data type", self.name)

        # Compile global variable lists
        compiled_gvls = []
        for cls in self._gvl_classes:
            if not isinstance(cls, CompiledGlobalVarList):
                raise ProjectAssemblyError(
                    f"{cls.__name__} is not a global variable list "
                    f"(missing @global_vars decorator)"
                )
            compiled_gvls.append(cls.compile())
        _check_duplicates(compiled_gvls, "name", "global variable list", self.name)

        # Compile POUs
        compiled_pous: list[POU] = []
        for cls in self._pou_classes:
            if not isinstance(cls, CompiledPOU):
                raise ProjectAssemblyError(
                    f"{cls.__name__} is not a compiled POU class "
                    f"(missing @fb, @program, or @function decorator)"
                )
            compiled_pous.append(cls.compile())

        # Also collect POUs referenced in tasks but not in the explicit pous list
        pou_names = {p.name for p in compiled_pous}
        for t in self._tasks:
            for cls in t._pou_classes:
                if isinstance(cls, CompiledPOU):
                    pou = cls.compile()
                    if pou.name not in pou_names:
                        compiled_pous.append(pou)
                        pou_names.add(pou.name)

        _check_duplicates(compiled_pous, "name", "POU", self.name)

        compiled_tasks = [t.compile() for t in self._tasks]
        _check_duplicates(compiled_tasks, "name", "task", self.name)

        result = Project(
            name=self.name,
            vendor=target.value if target else "",
            data_types=compiled_data_types,
            global_variable_lists=compiled_gvls,
            pous=compiled_pous,
            tasks=compiled_tasks,
        )

        if target is not None:
            warnings = validate_target(result, target)
            return CompileResult(result, warnings)

        return result


def project(
    name: str,
    *,
    pous: list[type] | None = None,
    tasks: list[PlxTask] | None = None,
    data_types: list[type] | None = None,
    global_var_lists: list[type] | None = None,
    packages: list[str] | None = None,
) -> PlxProject:
    """Create a project builder.

    Example::

        proj = project("MyProject",
            pous=[Controller],
            data_types=[MotorData, MachineState],
            global_var_lists=[SystemIO, Constants],
            tasks=[
                task("MainTask", periodic=T(ms=10), pous=[FastLoop], priority=1),
                task("SlowTask", periodic=T(ms=100), pous=[SlowLoop]),
            ]
        )
        ir = proj.compile()

        # Auto-discover from packages:
        proj = project("MyProject", packages=["my_machine"]).compile()
    """
    return PlxProject(
        name,
        pous=pous,
        tasks=tasks,
        data_types=data_types,
        global_var_lists=global_var_lists,
        packages=packages,
    )

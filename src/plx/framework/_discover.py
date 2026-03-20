"""Auto-discovery of decorated classes from Python packages.

Walks package trees, finds classes decorated with ``@fb``, ``@program``,
``@function``, ``@sfc``, ``@struct``, ``@enumeration``, ``@global_vars``, and
``task()`` instances.  Infers ``folder`` paths from module structure when
the decorator didn't set one explicitly.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import warnings
from enum import IntEnum
from types import ModuleType
from typing import Any

from ._task import PlxTask
from ._protocols import CompiledDataType, CompiledGlobalVarList, CompiledPOU


class DiscoveryResult:
    """Container for auto-discovered framework objects.

    Attributes
    ----------
    pous : list of type
        POU classes (``@fb``, ``@program``, ``@function``, ``@sfc``)
        found in the scanned packages.
    data_types : list of type
        Data type classes (``@struct``, ``@enumeration``, ``IntEnum``
        subclasses) found in the scanned packages.
    global_var_lists : list of type
        Global variable list classes (``@global_vars``) found in the
        scanned packages.
    tasks : list of PlxTask
        Task instances created with ``task()`` found as module-level
        attributes in the scanned packages.
    """

    __slots__ = ("pous", "data_types", "global_var_lists", "tasks")

    def __init__(self) -> None:
        self.pous: list[type] = []
        self.data_types: list[type] = []
        self.global_var_lists: list[type] = []
        self.tasks: list[PlxTask] = []


def _infer_folder(cls_or_obj: Any, root_package: str) -> str:
    """Infer a folder path from the object's module relative to root_package.

    - Regular module (``my_machine.conveyors.belt``): drops the last segment
      (the filename) → ``"conveyors"``
    - Package init (``my_machine.conveyors``, module has ``__path__``): keeps
      all segments → ``"conveyors"``
    - Root-level module (``my_machine.types``): → ``""``
    - Root package itself (``my_machine``): → ``""``
    """
    module_name: str = getattr(cls_or_obj, "__module__", "")
    if not module_name or not module_name.startswith(root_package):
        return ""

    # Strip root package prefix
    relative = module_name[len(root_package):]
    if relative.startswith("."):
        relative = relative[1:]

    if not relative:
        # Defined in root package __init__.py
        return ""

    parts = relative.split(".")

    # Check if the module is a package (__init__.py) vs a regular .py file
    mod = sys.modules.get(module_name)
    is_package = mod is not None and hasattr(mod, "__path__")

    if is_package:
        # Package __init__.py → keep all parts
        return "/".join(parts)
    else:
        # Regular module → drop last segment (the filename)
        if len(parts) <= 1:
            return ""
        return "/".join(parts[:-1])


def _walk_package(package_name: str) -> list[ModuleType]:
    """Import a package and all its submodules, return as a flat list."""
    root = importlib.import_module(package_name)
    modules = [root]

    if not hasattr(root, "__path__"):
        # Not a package, just a single module
        return modules

    for _importer, modname, _ispkg in pkgutil.walk_packages(
        root.__path__, prefix=package_name + "."
    ):
        try:
            mod = importlib.import_module(modname)
            modules.append(mod)
        except Exception as exc:
            import logging as _logging
            _logger = _logging.getLogger("plx.discover")
            _logger.error(
                "Failed to import %s — any POUs defined in this module "
                "will be missing from the project: %s",
                modname, exc, exc_info=True,
            )
            continue

    return modules


def discover(*package_names: str) -> DiscoveryResult:
    """Auto-discover decorated classes and tasks from Python packages.

    Walks each package and its submodules, finding classes that match
    framework protocols (``CompiledPOU``, ``CompiledDataType``,
    ``CompiledGlobalVarList``) and ``PlxTask`` instances.

    Only includes objects *defined* in the scanned packages (filters
    by ``__module__``). Deduplicates by ``id(obj)``. Sets ``folder``
    on the IR object when not explicitly set by the decorator, using
    the module's relative path within the package.

    Parameters
    ----------
    *package_names : str
        One or more Python package names to scan (e.g.
        ``"my_machine"``, ``"my_machine.conveyors"``).

    Returns
    -------
    DiscoveryResult
        Container with ``pous``, ``data_types``, ``global_var_lists``,
        and ``tasks`` lists populated from the scanned packages.

    Examples
    --------
    ::

        result = discover("my_machine")
        proj = project("MyProject",
            pous=result.pous,
            data_types=result.data_types,
            global_var_lists=result.global_var_lists,
            tasks=result.tasks,
        ).compile()

        # Or pass packages directly to project():
        proj = project("MyProject", packages=["my_machine"]).compile()
    """
    result = DiscoveryResult()
    seen_ids: set[int] = set()

    for pkg_name in package_names:
        modules = _walk_package(pkg_name)

        for mod in modules:
            mod_name = mod.__name__
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                obj_id = id(obj)

                if obj_id in seen_ids:
                    continue

                # Filter: only include objects defined in scanned packages.
                # For types, use __module__; for instances (PlxTask),
                # use the module we found them in.
                obj_module = getattr(obj, "__module__", None)
                if isinstance(obj, type):
                    if obj_module is None:
                        continue
                    if not _in_packages(obj_module, package_names):
                        continue
                else:
                    # Non-type objects (e.g. PlxTask instances) — use
                    # the module they were found in
                    if not _in_packages(mod_name, package_names):
                        continue

                if isinstance(obj, type) and isinstance(obj, CompiledPOU):
                    seen_ids.add(obj_id)
                    _set_inferred_folder(obj._compiled_pou, obj, pkg_name)
                    result.pous.append(obj)
                elif isinstance(obj, type) and isinstance(obj, CompiledDataType):
                    seen_ids.add(obj_id)
                    _set_inferred_folder(obj._compiled_type, obj, pkg_name)
                    result.data_types.append(obj)
                elif isinstance(obj, type) and issubclass(obj, IntEnum) and obj is not IntEnum:
                    from ._data_types import _ensure_enum_compiled
                    _ensure_enum_compiled(obj)
                    seen_ids.add(obj_id)
                    _set_inferred_folder(obj._compiled_type, obj, pkg_name)
                    result.data_types.append(obj)
                elif isinstance(obj, type) and isinstance(obj, CompiledGlobalVarList):
                    seen_ids.add(obj_id)
                    _set_inferred_folder(obj._compiled_gvl, obj, pkg_name)
                    result.global_var_lists.append(obj)
                elif isinstance(obj, PlxTask):
                    seen_ids.add(obj_id)
                    result.tasks.append(obj)

    return result


def _in_packages(module_name: str, package_names: tuple[str, ...]) -> bool:
    """Check if a module name belongs to any of the given packages."""
    return any(
        module_name == p or module_name.startswith(p + ".")
        for p in package_names
    )


def _set_inferred_folder(ir_obj: Any, cls: type, root_package: str) -> None:
    """Set folder on an IR object if not explicitly set by the decorator."""
    if ir_obj.folder == "":
        inferred = _infer_folder(cls, root_package)
        if inferred:
            ir_obj.folder = inferred

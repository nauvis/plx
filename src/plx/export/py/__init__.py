"""Python framework code generator (IR -> plx Python).

Walks Universal IR ``Project`` models and emits valid plx Python framework code.
Follows the ``STWriter`` pattern -- buffer-based writer with indent management.
"""

from __future__ import annotations

from plx.model.pou import POUType
from plx.model.project import Project
from plx.model.types import (
    AliasType,
    EnumType,
    StructType,
    SubrangeType,
    UnionType,
)

from ._writer import PyWriter
from ._helpers import (
    _collect_pou_deps,
    _format_initial_value,
    _parse_iec_time,
    _sanitize_folder,
    _topo_sort_data_types,
    _topo_sort_fbs,
)


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
        folder = _sanitize_folder(folder)
        return f"{folder}/{name}" if folder else name

    # Data types -- one file per type
    for td in project.data_types:
        if isinstance(td, (StructType, EnumType, UnionType, AliasType, SubrangeType)):
            fw = PyWriter(project)
            fw._line("from plx.framework import *")
            fw._line()
            fw._write_type_definition(td)
            files[_prefixed(td.folder, f"{td.name}.py")] = fw.getvalue()

    # Global variable lists -- one file per GVL
    for gvl in project.global_variable_lists:
        fw = PyWriter(project)
        fw._line("from plx.framework import *")
        fw._line()
        fw._write_global_variable_list(gvl)
        files[_prefixed(gvl.folder, f"{gvl.name}.py")] = fw.getvalue()

    # POUs -- one file per POU (methods/actions/properties inline)
    for pou in project.pous:
        fw = PyWriter(project)
        fw._line("from plx.framework import *")

        # Import any types/GVLs/FBs this POU might reference
        deps = _collect_pou_deps(pou, project)
        if deps:
            fw._line()
            for dep_file, dep_names in sorted(deps.items()):
                fw._line(f"from {dep_file} import {', '.join(sorted(dep_names))}")

        fw._line()
        if pou.pou_type == POUType.INTERFACE:
            fw._write_interface(pou)
        else:
            fw._write_pou(pou)
        files[_prefixed(pou.folder, f"{pou.name}.py")] = fw.getvalue()

    # project.py -- task definitions + project() with packages discovery
    pw = PyWriter()
    pw._line("from plx.framework import *")

    # Import all POUs, data types, and GVLs referenced by the project
    def _module_path(folder: str, name: str) -> str:
        folder = _sanitize_folder(folder)
        if folder:
            return folder.replace("/", ".") + "." + name
        return name

    for dt in _topo_sort_data_types(project.data_types):
        pw._line(f"from {_module_path(dt.folder, dt.name)} import {dt.name}")
    for gvl in project.global_variable_lists:
        pw._line(f"from {_module_path(gvl.folder, gvl.name)} import {gvl.name}")
    for pou in _topo_sort_fbs(project.pous):
        pw._line(f"from {_module_path(pou.folder, pou.name)} import {pou.name}")

    pw._line()
    pw._write_project_assembly(project)
    files["project.py"] = pw.getvalue()

    return files

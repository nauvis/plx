"""Project loading for the plx runtime.

Three loading modes:
- Directory: discover() + project().compile()
- Python file: import module, find Project or PlxProject
- JSON file: Project.model_validate_json()
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from plx.model.project import Project


def load_project(path: str) -> tuple[Project, Path]:
    """Load a plx project from a directory, .py file, or .plx.json file.

    Parameters
    ----------
    path : str
        Path to a project directory (package with decorated POUs), a ``.py``
        file containing a ``Project`` or ``PlxProject``, or a ``.plx.json``
        file with serialized IR.

    Returns
    -------
    tuple[Project, Path]
        The compiled Project IR and the resolved source path (used for
        file watching / hot reload).

    Raises
    ------
    RuntimeError
        If the path format is unrecognized, the file cannot be imported,
        or no POUs / Project objects are found.
    FileNotFoundError
        If the path does not exist (raised by Path operations).
    """
    p = Path(path).resolve()

    if p.is_dir():
        return _load_directory(p), p
    elif p.suffix == ".json" or p.name.endswith(".plx.json"):
        return _load_json(p), p
    elif p.suffix == ".py":
        return _load_python_file(p), p
    else:
        raise RuntimeError(f"Cannot load project from '{path}': expected a directory, .py file, or .plx.json file")


def _load_directory(directory: Path) -> Project:
    """Load a package directory via discover() + project().compile()."""
    from plx.framework._discover import discover
    from plx.framework._project import project

    package_name = directory.name

    # Add parent to sys.path so the package can be imported
    parent = str(directory.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    result = discover(package_name)

    if not result.pous:
        raise RuntimeError(
            f"No POUs found in package '{package_name}'. "
            f"Ensure the directory contains @fb/@program/@function decorated classes."
        )

    proj = project(
        package_name,
        pous=result.pous,
        data_types=result.data_types,
        global_var_lists=result.global_var_lists,
        tasks=result.tasks,
    )
    return proj.compile()


def _load_python_file(filepath: Path) -> Project:
    """Load a .py file, find a Project IR or PlxProject builder."""
    from plx.framework._project import PlxProject

    # Add the file's directory to sys.path
    parent = str(filepath.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    module_name = filepath.stem
    # Remove stale module if reloading
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import '{filepath}'")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Search module globals for a Project or PlxProject
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, Project):
            return obj
        if isinstance(obj, PlxProject):
            return obj.compile()

    raise RuntimeError(
        f"No Project or PlxProject found in '{filepath}'. "
        f"The file must define a 'proj = project(...)' or compiled Project IR."
    )


def _load_json(filepath: Path) -> Project:
    """Load a Project from a .plx.json file."""
    text = filepath.read_text(encoding="utf-8")
    return Project.model_validate_json(text)


def reload_project(path: str) -> Project:
    """Reload a project, clearing cached modules for the package.

    Used by the hot-reload watcher. For directory sources, all cached
    modules for the package are purged before re-importing.

    Parameters
    ----------
    path : str
        Original source path (directory, ``.py`` file, or ``.plx.json``).

    Returns
    -------
    Project
        The freshly compiled Project IR.
    """
    p = Path(path).resolve()

    if p.is_dir():
        package_name = p.name
        # Clear all cached modules for this package
        to_remove = [key for key in sys.modules if key == package_name or key.startswith(package_name + ".")]
        for key in to_remove:
            del sys.modules[key]
        return _load_directory(p)
    elif p.suffix == ".py":
        return _load_python_file(p)
    else:
        return _load_json(p)

"""Shared compilation helpers used by _decorators.py and _sfc.py.

Centralises source-parsing and CompileContext construction that was
previously duplicated across multiple call sites.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

from plx.model.types import TypeRef

from enum import IntEnum

from ._compiler_core import CompileContext, CompileError
from ._descriptors import VarDirection, _collect_descriptors
from ._protocols import CompiledEnum, CompiledPOU


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------

def _parse_function_source(
    func: Any,
    context_name: str,
    *,
    validate_self_only: bool = True,
    validate_single_return: bool = False,
) -> tuple[ast.FunctionDef, str, int]:
    """Parse a method's source into an AST ``FunctionDef``.

    Parameters
    ----------
    func:
        The function/method object to parse.
    context_name:
        Human-readable name for error messages (e.g. ``"MyFB.logic()"``).
    validate_self_only:
        If *True*, verify the signature is ``(self)`` with no extra
        parameters, ``*args``, or ``**kwargs``.
    validate_single_return:
        If *True*, verify the body is a single ``return <expr>`` statement.

    Returns
    -------
    tuple of (func_def, source, start_lineno)
    """
    source_lines, start_lineno = inspect.getsourcelines(func)
    source = textwrap.dedent("".join(source_lines))

    try:
        _src_file = inspect.getfile(func)
    except (TypeError, OSError):
        _src_file = None

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise CompileError(
            f"Syntax error in {context_name}: {e}",
            source_file=_src_file,
        ) from e

    if not tree.body or not isinstance(tree.body[0], ast.FunctionDef):
        raise CompileError(
            f"Expected a function definition in {context_name}",
            source_file=_src_file,
        )

    func_def = tree.body[0]

    if validate_self_only:
        params = func_def.args
        if len(params.args) != 1 or params.args[0].arg != "self":
            raise CompileError(
                f"{context_name} must take exactly one parameter (self)",
                node=func_def,
                source_file=_src_file,
            )
        if params.vararg or params.kwarg or params.kwonlyargs or params.posonlyargs:
            raise CompileError(
                f"{context_name} must take only 'self'",
                node=func_def,
                source_file=_src_file,
            )

    if validate_single_return:
        body = func_def.body
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            raise CompileError(
                f"{context_name} must have exactly one statement: "
                f"'return <condition>'",
                source_file=_src_file,
            )
        if body[0].value is None:
            raise CompileError(
                f"{context_name} must return an expression (the condition)",
                source_file=_src_file,
            )

    return func_def, source, start_lineno


# ---------------------------------------------------------------------------
# CompileContext construction
# ---------------------------------------------------------------------------

def _build_compile_context(
    enum_source: Any,
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    start_lineno: int,
    source_file: str,
) -> CompileContext:
    """Build a ``CompileContext`` with automatic enum discovery.

    Parameters
    ----------
    enum_source:
        The function/class whose globals and closure are scanned for
        ``@enumeration``-decorated types.
    cls:
        The POU class being compiled (set as ``pou_class``).
    declared_vars:
        Pre-built variable direction map.  Caller is responsible for
        copying if mutation isolation is needed.
    static_var_types:
        Pre-built static variable type map.
    start_lineno:
        Source line number of the function (1-based).
    source_file:
        Path to the source file.
    """
    known_enums, plx_enum_names = _discover_enums(enum_source)
    known_constants = _discover_constants(enum_source)
    return CompileContext(
        declared_vars=declared_vars,
        static_var_types=static_var_types,
        pou_class=cls,
        source_line_offset=start_lineno - 1,
        source_file=source_file,
        known_enums=known_enums,
        plx_enum_names=plx_enum_names,
        known_constants=known_constants,
    )


# ---------------------------------------------------------------------------
# Enum discovery
# ---------------------------------------------------------------------------

def _discover_enums(func: Any) -> tuple[dict[str, dict[str, int]], set[str]]:
    """Discover @enumeration types visible to *func* (globals + closure).

    Returns ``(known_enums, plx_enum_names)`` where *plx_enum_names*
    contains the names of ``@enumeration``-decorated types (which compile
    to IEC 61131-3 enum types) as opposed to plain Python ``IntEnum``
    subclasses (which are just integer constants).
    """
    known: dict[str, dict[str, int]] = {}
    plx_names: set[str] = set()
    # Module-level globals (guard for objects without __globals__, e.g. builtins)
    if not hasattr(func, '__globals__'):
        return known, plx_names
    for name, obj in func.__globals__.items():
        if isinstance(obj, CompiledEnum):
            known[name] = obj._enum_values
            plx_names.add(name)
        elif isinstance(obj, type) and issubclass(obj, IntEnum) and obj is not IntEnum:
            known[name] = {m.name: m.value for m in obj}
    # Closure variables (locally-scoped enums)
    code = getattr(func, '__code__', None)
    closure = getattr(func, '__closure__', None)
    if code and closure:
        for name, cell in zip(code.co_freevars, closure):
            try:
                obj = cell.cell_contents
            except ValueError:
                # Uninitialized closure cell — the variable was declared in
                # an enclosing scope but hasn't been assigned yet (e.g. a
                # class being defined in a closure).  Safe to skip.
                continue
            if isinstance(obj, CompiledEnum):
                known[name] = obj._enum_values
                plx_names.add(name)
            elif isinstance(obj, type) and issubclass(obj, IntEnum) and obj is not IntEnum:
                known[name] = {m.name: m.value for m in obj}
    return known, plx_names


# ---------------------------------------------------------------------------
# Constant discovery
# ---------------------------------------------------------------------------

# Names to exclude — Python builtins, dunder names, and common non-constant
# module-level objects that happen to be int/str/bool.
_CONSTANT_EXCLUDES = frozenset({
    "True", "False", "None",
    # Common module-level names that aren't user constants
    "__name__", "__doc__", "__file__", "__spec__", "__loader__",
    "__package__", "__builtins__", "__cached__",
})


def _discover_constants(func: Any) -> dict[str, int | float | bool | str]:
    """Discover module-level literal constants visible to *func*.

    Only picks up ``int``, ``float``, ``bool``, and ``str`` values whose
    names look like constants (UPPER_CASE or Title_Case — specifically,
    names that don't start with ``_``).  Enum classes and their members
    are excluded so they don't shadow the enum-resolution path.
    """
    known: dict[str, int | float | bool | str] = {}
    if not hasattr(func, "__globals__"):
        return known
    for name, val in func.__globals__.items():
        if name.startswith("_"):
            continue
        if name in _CONSTANT_EXCLUDES:
            continue
        # Skip classes, functions, modules — only want bare literals
        if isinstance(val, type) or callable(val):
            continue
        # Skip enum members (IntEnum subclass instances)
        if isinstance(val, IntEnum):
            continue
        if isinstance(val, (int, float, str)):
            # bool is a subclass of int — include it
            known[name] = val
    return known


# ---------------------------------------------------------------------------
# POU helpers (shared by _decorators.py and _sfc.py)
# ---------------------------------------------------------------------------

def _detect_parent_pou(cls: type) -> str | None:
    """Walk MRO to find the first parent with a compiled POU (inheritance)."""
    for base in cls.__mro__[1:]:
        if base is object:
            continue
        if isinstance(base, CompiledPOU):
            return base._compiled_pou.name
    return None


def _build_var_context(
    cls: type,
) -> tuple[dict[str, list], dict[str, VarDirection], dict[str, TypeRef]]:
    """Collect descriptors and build declared_vars + static_var_types maps.

    ``static_var_types`` records types for ALL declared variables (input,
    output, inout, static, etc.) so that ``_infer_type()`` can resolve
    ``self.x`` regardless of direction — needed for string-concat
    rejection, bit-access validation, and other type-aware compile checks.

    The FB-invocation detection path (``_build_fb_invocation`` in
    ``_compiler.py``) further filters by ``declared_vars`` direction to
    ensure only STATIC vars are treated as FB instances.
    """
    var_groups = _collect_descriptors(cls)
    declared_vars: dict[str, VarDirection] = {}
    static_var_types: dict[str, TypeRef] = {}

    for direction_str, var_list in var_groups.items():
        direction = VarDirection(direction_str)
        for v in var_list:
            declared_vars[v.name] = direction
            static_var_types[v.name] = v.data_type

    return var_groups, declared_vars, static_var_types

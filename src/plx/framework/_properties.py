"""Property decorators for function blocks.

Provides ``@fb_property`` for defining getter/setter properties on FBs
that compile to IEC 61131-3 PROPERTY constructs.

Usage::

    @fb
    class Motor:
        _speed = static_var(REAL)

        @fb_property(REAL)
        def speed(self):
            return self._speed

        @speed.setter
        def speed(self, value: REAL):
            self._speed = value

        def logic(self): ...
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from typing import Any

from plx.model._base import IRModel
from plx.model.expressions import VariableRef
from plx.model.pou import (
    AccessSpecifier,
    Network,
    Property,
    PropertyAccessor,
)
from plx.model.types import TypeRef
from plx.model.variables import Variable

from ._compiler import ASTCompiler
from ._compiler_core import CompileError, resolve_annotation
from ._compilation_helpers import (
    _build_compile_context,
    _parse_function_source,
)
from ._descriptors import VarDirection


# ---------------------------------------------------------------------------
# Property descriptor (class-level marker)
# ---------------------------------------------------------------------------

@dataclass
class _PropertyMarker:
    """Stored on getter functions decorated with @fb_property."""
    data_type: TypeRef
    access: AccessSpecifier
    abstract: bool
    final: bool
    getter_func: Any
    setter_func: Any | None = None


class PropDescriptor:
    """Returned by ``@fb_property``.  Supports ``.setter`` chaining.

    The descriptor is stored as a class attribute; ``_collect_properties``
    walks MRO to discover them.
    """

    __slots__ = ("_marker",)

    def __init__(self, marker: _PropertyMarker) -> None:
        self._marker = marker

    def setter(self, func: Any) -> PropDescriptor:
        """Register a setter for this property."""
        self._marker.setter_func = func
        return self


# ---------------------------------------------------------------------------
# @fb_property decorator
# ---------------------------------------------------------------------------

def fb_property(
    data_type_arg: Any = None,
    *,
    access: AccessSpecifier = AccessSpecifier.PUBLIC,
    abstract: bool = False,
    final: bool = False,
) -> Any:
    """Declare a property on a function block.

    Can be used as ``@fb_property(REAL)`` or ``@fb_property(REAL, access=PRIVATE)``.

    The decorated function becomes the getter.  Use ``.setter`` to add a setter::

        @fb_property(REAL)
        def speed(self):
            return self._speed

        @speed.setter
        def speed(self, value: REAL):
            self._speed = value
    """
    from ._types import _resolve_type_ref

    def decorator(func: Any) -> PropDescriptor:
        type_ref = _resolve_type_ref(data_type_arg)
        marker = _PropertyMarker(
            data_type=type_ref,
            access=access,
            abstract=abstract,
            final=final,
            getter_func=func,
        )
        return PropDescriptor(marker)

    # Support @fb_property(REAL) — data_type_arg is the type
    if data_type_arg is not None and not callable(data_type_arg):
        return decorator

    raise CompileError(
        "@fb_property requires a type argument: @fb_property(REAL)"
    )


# ---------------------------------------------------------------------------
# Collection + compilation
# ---------------------------------------------------------------------------

def _collect_properties(cls: type) -> list[tuple[str, _PropertyMarker]]:
    """Collect PropDescriptor instances from *cls* MRO."""
    seen: set[str] = set()
    collected: list[tuple[str, _PropertyMarker]] = []

    for base in reversed(cls.__mro__):
        if base is object:
            continue
        for attr_name, value in base.__dict__.items():
            if not isinstance(value, PropDescriptor):
                continue
            if attr_name in seen:
                collected = [(n, m) for n, m in collected if n != attr_name]
            seen.add(attr_name)
            collected.append((attr_name, value._marker))

    return collected


def _compile_property(
    prop_name: str,
    marker: _PropertyMarker,
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
) -> Property:
    """Compile a PropDescriptor into a Property IR node."""

    getter_accessor: PropertyAccessor | None = None
    setter_accessor: PropertyAccessor | None = None

    if marker.getter_func is not None and not marker.abstract:
        getter_accessor = _compile_accessor(
            marker.getter_func, "getter", prop_name, cls,
            declared_vars, static_var_types, source_file,
        )

    if marker.setter_func is not None and not marker.abstract:
        setter_accessor = _compile_accessor(
            marker.setter_func, "setter", prop_name, cls,
            declared_vars, static_var_types, source_file,
        )

    return Property(
        name=prop_name,
        data_type=marker.data_type,
        access=marker.access,
        abstract=marker.abstract,
        final=marker.final,
        getter=getter_accessor,
        setter=setter_accessor,
    )


def _compile_accessor(
    func: Any,
    role: str,
    prop_name: str,
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
) -> PropertyAccessor:
    """Compile a getter or setter function body."""
    context_name = f"{cls.__name__}.{prop_name} ({role})"

    if role == "getter":
        func_def, _, start_lineno = _parse_function_source(
            func, context_name, validate_self_only=True,
        )
    else:
        # setter has (self, value)
        func_def, _, start_lineno = _parse_function_source(
            func, context_name, validate_self_only=False,
        )

    ctx = _build_compile_context(
        func, cls,
        dict(declared_vars), dict(static_var_types),
        start_lineno, source_file,
    )

    compiler = ASTCompiler(ctx)
    stmts = compiler.compile_body(func_def)

    # IEC 61131-3 property setters use the property name as the input
    # parameter (not the Python parameter name).  Rename VariableRefs.
    if role == "setter" and len(func_def.args.args) >= 2:
        py_param = func_def.args.args[1].arg
        if py_param != prop_name:
            stmts = [_rename_var(s, py_param, prop_name) for s in stmts]

    return PropertyAccessor(
        networks=[Network(statements=stmts)],
    )


# ---------------------------------------------------------------------------
# Variable rename helper (setter parameter → property name)
# ---------------------------------------------------------------------------

def _rename_in_node(node: IRModel, old: str, new: str) -> IRModel:
    """Return a copy of *node* with VariableRef *old* renamed to *new*.

    Recursively walks all IRModel fields (expressions and statements).
    """
    if isinstance(node, VariableRef) and node.name == old:
        return node.model_copy(update={"name": new})

    updates: dict[str, object] = {}
    for field_name in type(node).model_fields:
        val = getattr(node, field_name)
        if isinstance(val, IRModel):
            renamed = _rename_in_node(val, old, new)
            if renamed is not val:
                updates[field_name] = renamed
        elif isinstance(val, list) and val and isinstance(val[0], IRModel):
            new_list = [_rename_in_node(v, old, new) for v in val]
            if any(a is not b for a, b in zip(new_list, val)):
                updates[field_name] = new_list
    return node.model_copy(update=updates) if updates else node


def _rename_var(stmt: IRModel, old: str, new: str) -> IRModel:
    """Rename VariableRef *old* → *new* throughout a statement tree."""
    return _rename_in_node(stmt, old, new)

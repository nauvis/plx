"""plx simulator — scan-cycle execution of Universal IR.

Entry point::

    from plx.simulate import simulate

    ctx = simulate(MyFB)
    ctx.cmd = True
    ctx.scan()
    assert ctx.running
    ctx.tick(seconds=5)
"""

from __future__ import annotations

import inspect
import sys
from enum import IntEnum
from typing import Any

from plx.model.pou import POU
from plx.model.types import EnumType, StructType

from plx.framework._protocols import CompiledDataType, CompiledPOU

from ._context import SimulationContext
from ._values import SimulationError


def simulate(
    target: Any,
    *,
    pous: list[Any] | None = None,
    data_types: list[Any] | None = None,
    scan_period_ms: int = 10,
    global_state: dict[str, dict[str, object]] | None = None,
) -> SimulationContext:
    """Create a simulation context for a POU.

    Parameters
    ----------
    target
        A ``@fb``/``@program``-decorated class (has ``_compiled_pou``)
        or a ``POU`` IR node directly.
    pous
        Additional POU classes or POU IR nodes for nested FB resolution.
    data_types
        ``@struct``/``@enumeration``-decorated classes or TypeDefinition IR
        for type resolution.
    scan_period_ms
        Simulated time advance per scan cycle (default 10ms).
    global_state
        Shared global variable state for external vars: GVL name ->
        {var_name: value}. Pass the same dict to multiple ``simulate()``
        calls to share state between POUs.

    Returns
    -------
    SimulationContext
        The simulation context with attribute-style variable access.

    Notes
    -----
    Enum, struct, and FB types defined in the same module as *target* are
    auto-discovered, so ``data_types=`` and ``pous=`` are only needed for
    types defined elsewhere.
    """
    # Resolve target POU
    pou = _resolve_pou(target)

    # Auto-discover POUs and data types from the target's module
    auto_pous, auto_data_types = _auto_discover(target)

    # Build POU registry (auto-discovered first, explicit overrides)
    pou_registry: dict[str, POU] = {}
    for p in auto_pous:
        resolved = _resolve_pou(p)
        pou_registry[resolved.name] = resolved
    if pous:
        for p in pous:
            resolved = _resolve_pou(p)
            pou_registry[resolved.name] = resolved
    # Auto-register the target itself
    pou_registry[pou.name] = pou

    # Build data type and enum registries (auto-discovered + explicit)
    data_type_registry: dict[str, StructType | EnumType] = {}
    enum_registry: dict[str, type[IntEnum]] = {}

    for dt in auto_data_types:
        _register_typedef(dt, data_type_registry, enum_registry)
    if data_types:
        for dt in data_types:
            _register_typedef(dt, data_type_registry, enum_registry)

    return SimulationContext(
        pou=pou,
        pou_registry=pou_registry,
        data_type_registry=data_type_registry,
        enum_registry=enum_registry,
        scan_period_ms=scan_period_ms,
        global_state=global_state,
    )


def _resolve_pou(target: Any) -> POU:
    """Resolve a target to a POU IR node."""
    if isinstance(target, POU):
        return target
    if isinstance(target, CompiledPOU):
        return target._compiled_pou
    raise TypeError(
        f"simulate() expects a @fb/@program/@sfc class or POU IR, "
        f"got {type(target).__name__}"
    )


def _resolve_typedef(dt: Any) -> StructType | EnumType:
    """Resolve a data type to a TypeDefinition IR node."""
    if isinstance(dt, (StructType, EnumType)):
        return dt
    if isinstance(dt, CompiledDataType):
        return dt._compiled_type
    # Auto-compile bare IntEnum/dataclass that hasn't been compiled yet
    if isinstance(dt, type):
        from plx.framework._data_types import _ensure_enum_compiled, _ensure_struct_compiled
        _ensure_enum_compiled(dt)
        _ensure_struct_compiled(dt)
        if isinstance(dt, CompiledDataType):
            return dt._compiled_type
    raise TypeError(
        f"data_types entries must be @struct/@enumeration classes or TypeDefinition IR, "
        f"got {type(dt).__name__}"
    )


def _register_typedef(
    dt: Any,
    data_type_registry: dict[str, StructType | EnumType],
    enum_registry: dict[str, type[IntEnum]],
) -> None:
    """Resolve a data type and add it to both registries."""
    typedef = _resolve_typedef(dt)
    data_type_registry[typedef.name] = typedef
    if isinstance(typedef, EnumType):
        members = {m.name: m.value for m in typedef.members if m.value is not None}
        if members:
            enum_registry[typedef.name] = IntEnum(typedef.name, members)


def _auto_discover(target: Any) -> tuple[list[Any], list[Any]]:
    """Auto-discover POUs and data types from the target's scope.

    Checks:
    1. The target's defining module (normal imports)
    2. Caller frames' globals/locals (exec'd code, e.g. web test runner)

    Returns (pou_classes, data_type_classes).
    """
    seen_ids: set[int] = {id(target)}
    pou_classes: list[Any] = []
    data_type_classes: list[Any] = []

    def _scan_namespace(ns: dict) -> None:
        for obj in ns.values():
            if id(obj) in seen_ids:
                continue
            seen_ids.add(id(obj))
            if isinstance(obj, type) and isinstance(obj, CompiledPOU):
                pou_classes.append(obj)
            elif isinstance(obj, type) and isinstance(obj, CompiledDataType):
                data_type_classes.append(obj)

    # Strategy 1: target's module (works for normal .py files)
    module_name = getattr(target, "__module__", None)
    if module_name is not None:
        module = sys.modules.get(module_name)
        if module is not None:
            _scan_namespace(vars(module))

    # Strategy 2: walk caller frames (works for exec'd code)
    # The web test runner exec's code into a namespace dict. Classes defined
    # there won't have a real module in sys.modules, but they'll be visible
    # in the globals of some frame on the call stack.
    try:
        frame = inspect.currentframe()
        if frame is not None:
            frame = frame.f_back  # skip simulate() itself
        while frame is not None:
            _scan_namespace(frame.f_globals)
            _scan_namespace(frame.f_locals)
            frame = frame.f_back
    finally:
        del frame  # avoid reference cycle

    return pou_classes, data_type_classes


__all__ = ["simulate", "SimulationContext", "SimulationError"]

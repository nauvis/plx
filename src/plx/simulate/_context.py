"""Simulation context: the user-facing object for running POU scans.

Manages instance allocation, scan execution, simulated time, and
provides attribute-style access to POU variables.
"""

from __future__ import annotations

import math
from enum import IntEnum

from plx.model.pou import POU
from plx.model.types import (
    ArrayTypeRef,
    EnumType,
    NamedTypeRef,
    PrimitiveTypeRef,
    StructType,
    TypeRef,
)
from plx.model.variables import Variable

from ._builtins import BUILTIN_FBS
from ._executor import ExecutionEngine
from ._values import SimulationError, parse_literal, type_default


class SimulationContext:
    """User-facing simulation object for a single POU.

    Provides ``scan()``, ``tick()``, and attribute-style variable access.

    Parameters
    ----------
    pou : POU
        The POU to simulate.
    pou_registry : dict[str, POU]
        Registry of user-defined POUs for nested FB resolution.
    data_type_registry : dict[str, StructType | EnumType]
        Registry of type definitions.
    enum_registry : dict[str, type[IntEnum]]
        Enum name -> IntEnum class for literal resolution.
    scan_period_ms : int
        Simulated time advance per scan (default 10ms).
    global_state : dict[str, dict[str, object]]
        Shared global variable state: GVL name -> {var_name: value}.
        External vars in POUs resolve against this dict.
    """

    def __init__(
        self,
        pou: POU,
        pou_registry: dict[str, POU] | None = None,
        data_type_registry: dict | None = None,
        enum_registry: dict[str, type[IntEnum]] | None = None,
        scan_period_ms: int = 10,
        global_state: dict[str, dict[str, object]] | None = None,
    ) -> None:
        object.__setattr__(self, "_pou", pou)
        object.__setattr__(self, "_pou_registry", pou_registry or {})
        object.__setattr__(self, "_data_type_registry", data_type_registry or {})
        object.__setattr__(self, "_enum_registry", enum_registry or {})
        object.__setattr__(self, "_scan_period_ms", scan_period_ms)
        object.__setattr__(self, "_clock_ms", 0)
        object.__setattr__(self, "_global_state", global_state if global_state is not None else {})

        # Allocate state
        state = self._allocate_state(pou)
        object.__setattr__(self, "_state", state)

        # First-scan flag: TRUE on the first scan, FALSE thereafter
        state["__system_first_scan"] = True

        # Initialize SFC state if this is an SFC POU
        if pou.sfc_body is not None:
            state["__sfc_active_steps"] = set()
            state["__sfc_step_entry_time"] = {}
            state["__sfc_just_activated"] = set()
            state["__sfc_just_deactivated"] = set()
            state["__sfc_action_start_time"] = {}
            state["__sfc_stored_actions"] = set()
            state["__sfc_initialized"] = False

        # Build set of known variable names for __setattr__
        known = set(state.keys())
        # Exclude internal keys from known vars (not user-accessible)
        known -= {
            "__sfc_active_steps", "__sfc_step_entry_time",
            "__sfc_just_activated", "__sfc_just_deactivated",
            "__sfc_action_start_time", "__sfc_stored_actions",
            "__sfc_initialized",
            "__system_first_scan",
        }
        object.__setattr__(self, "_known_vars", known)

        # Track temp var definitions for fresh allocation each scan
        object.__setattr__(self, "_temp_vars", list(pou.interface.temp_vars))

    # -----------------------------------------------------------------------
    # State allocation
    # -----------------------------------------------------------------------

    def _allocate_state(self, pou: POU) -> dict[str, object]:
        """Allocate the full state dict for a POU."""
        state: dict[str, object] = {}

        all_vars = (
            list(pou.interface.input_vars)
            + list(pou.interface.output_vars)
            + list(pou.interface.inout_vars)
            + list(pou.interface.static_vars)
            + list(pou.interface.temp_vars)
            + list(pou.interface.constant_vars)
        )

        for var in all_vars:
            state[var.name] = self._allocate_var(var)

        # External vars: allocate defaults in global_state if not present,
        # then snapshot into local state. Sync back after each scan.
        for var in pou.interface.external_vars:
            gvl_name = var.description or "__default__"
            if gvl_name not in self._global_state:
                self._global_state[gvl_name] = {}
            gvl = self._global_state[gvl_name]
            if var.name not in gvl:
                gvl[var.name] = self._allocate_var(var)
            state[var.name] = gvl[var.name]

        return state

    def _sync_externals_in(self) -> None:
        """Copy global state → local state for external vars (pre-scan)."""
        for var in self._pou.interface.external_vars:
            gvl_name = var.description or "__default__"
            gvl = self._global_state.get(gvl_name, {})
            if var.name in gvl:
                self._state[var.name] = gvl[var.name]

    def _sync_externals_out(self) -> None:
        """Copy local state → global state for external vars (post-scan)."""
        for var in self._pou.interface.external_vars:
            gvl_name = var.description or "__default__"
            if gvl_name not in self._global_state:
                self._global_state[gvl_name] = {}
            self._global_state[gvl_name][var.name] = self._state[var.name]

    def _allocate_var(self, var: Variable) -> object:
        """Allocate initial value for a single variable."""
        if var.initial_value is not None:
            return parse_literal(var.initial_value, var.data_type, self._enum_registry)

        dt = var.data_type

        # Array allocation
        if isinstance(dt, ArrayTypeRef):
            return self._allocate_array(dt)

        # Named type — check registries
        if isinstance(dt, NamedTypeRef):
            return self._allocate_named(dt.name)

        # Primitive default
        default = type_default(dt)
        if default is not None:
            return default

        return 0

    def _allocate_array(self, dt: ArrayTypeRef) -> list:
        """Build nested list from ArrayTypeRef dimensions."""
        def _build(dims, idx):
            dim = dims[idx]
            size = dim.upper - dim.lower + 1
            if idx == len(dims) - 1:
                # Innermost dimension — allocate element defaults
                elem_default = type_default(dt.element_type)
                if elem_default is None:
                    if isinstance(dt.element_type, NamedTypeRef):
                        return [self._allocate_named(dt.element_type.name) for _ in range(size)]
                    return [0 for _ in range(size)]
                return [elem_default for _ in range(size)]
            return [_build(dims, idx + 1) for _ in range(size)]

        return _build(dt.dimensions, 0)

    def _allocate_named(self, name: str) -> object:
        """Allocate a named type (builtin FB, user FB, struct, enum)."""
        # Builtin FB
        if name in BUILTIN_FBS:
            return BUILTIN_FBS[name].initial_state()

        # User-defined FB
        if name in self._pou_registry:
            pou = self._pou_registry[name]
            return self._allocate_state(pou)

        # Struct
        if name in self._data_type_registry:
            typedef = self._data_type_registry[name]
            if isinstance(typedef, StructType):
                return self._allocate_struct(typedef)
            if isinstance(typedef, EnumType):
                # Enum default = first member as IntEnum member if available
                if typedef.members and typedef.members[0].value is not None:
                    if name in self._enum_registry:
                        enum_cls = self._enum_registry[name]
                        return enum_cls(typedef.members[0].value)
                    return typedef.members[0].value
                return 0

        # Unknown named type — return empty dict
        return {}

    def _allocate_struct(self, typedef: StructType) -> dict:
        """Allocate a struct as a dict of member defaults."""
        result: dict[str, object] = {}
        for member in typedef.members:
            if member.initial_value is not None:
                result[member.name] = parse_literal(
                    member.initial_value, member.data_type, self._enum_registry,
                )
            else:
                default = type_default(member.data_type)
                if default is not None:
                    result[member.name] = default
                elif isinstance(member.data_type, NamedTypeRef):
                    result[member.name] = self._allocate_named(member.data_type.name)
                elif isinstance(member.data_type, ArrayTypeRef):
                    result[member.name] = self._allocate_array(member.data_type)
                else:
                    result[member.name] = 0
        return result

    # -----------------------------------------------------------------------
    # Scan / tick
    # -----------------------------------------------------------------------

    def scan(self, n: int = 1) -> None:
        """Execute *n* scan cycles.

        Each scan:
        1. Allocate fresh temp vars
        2. Execute POU logic
        3. Advance clock by scan_period_ms
        """
        for _ in range(n):
            # Sync external vars from global state
            self._sync_externals_in()

            # Fresh temp vars
            for var in self._temp_vars:
                self._state[var.name] = self._allocate_var(var)

            # Execute
            engine = ExecutionEngine(
                pou=self._pou,
                state=self._state,
                clock_ms=self._clock_ms,
                pou_registry=self._pou_registry,
                data_type_registry=self._data_type_registry,
                enum_registry=self._enum_registry,
            )
            engine.execute()

            # Sync external vars back to global state
            self._sync_externals_out()

            # Clear first-scan flag after the first scan
            if self._state.get("__system_first_scan", False):
                self._state["__system_first_scan"] = False

            # Advance clock
            self._clock_ms += self._scan_period_ms

    def tick(self, seconds: float = 0, ms: float = 0) -> None:
        """Advance simulated time by running enough scans.

        Computes ``ceil(total_ms / scan_period_ms)`` and calls ``scan(n=...)``.
        """
        total_ms = seconds * 1000 + ms
        if total_ms <= 0:
            return
        n = math.ceil(total_ms / self._scan_period_ms)
        self.scan(n=n)

    @property
    def clock_ms(self) -> int:
        """Current simulated time in milliseconds."""
        return self._clock_ms

    @property
    def global_state(self) -> dict[str, dict[str, object]]:
        """Shared global variable state: GVL name -> {var_name: value}."""
        return self._global_state

    @property
    def active_steps(self) -> set[str]:
        """Currently active SFC steps (empty for non-SFC POUs)."""
        return set(self._state.get("__sfc_active_steps", set()))

    # -----------------------------------------------------------------------
    # Context manager
    # -----------------------------------------------------------------------

    def __enter__(self) -> SimulationContext:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    def set(self, **kwargs: object) -> None:
        """Set multiple variables at once via keyword arguments.

        Example::

            ctx.set(enable=True, speed=50.0)
            # equivalent to:
            # ctx.enable = True
            # ctx.speed = 50.0
        """
        known = object.__getattribute__(self, "_known_vars")
        for name, value in kwargs.items():
            if name not in known:
                raise AttributeError(
                    f"'{type(self).__name__}' has no variable '{name}'. "
                    f"Available: {sorted(known)}"
                )
            self._state[name] = value

    # -----------------------------------------------------------------------
    # Attribute access
    # -----------------------------------------------------------------------

    def __getattr__(self, name: str) -> object:
        # Only intercept known variable names
        state = object.__getattribute__(self, "_state")
        if name in state:
            return state[name]
        known = object.__getattribute__(self, "_known_vars")
        raise AttributeError(
            f"'{type(self).__name__}' has no variable '{name}'. "
            f"Available: {sorted(known)}"
        )

    def __setattr__(self, name: str, value: object) -> None:
        try:
            known = object.__getattribute__(self, "_known_vars")
        except AttributeError:
            # During __init__
            object.__setattr__(self, name, value)
            return

        if name in known:
            self._state[name] = value
        else:
            object.__setattr__(self, name, value)

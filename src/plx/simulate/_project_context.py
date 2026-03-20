"""Project-level simulation context: multi-program, multi-task orchestration.

Provides ``ProjectSimulationContext`` — the user-facing object for simulating
an entire ``Project`` IR with task scheduling, GVL sharing, and multi-program
coordination.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from plx.model.pou import POU, POUType
from plx.model.project import GlobalVariableList, Project
from plx.model.task import ContinuousTask, EventTask, PeriodicTask, StartupTask
from plx.model.types import (
    ArrayTypeRef,
    EnumType,
    NamedTypeRef,
    StructType,
)
from plx.model.variables import Variable

from ._context import SimulationContext
from ._proxy import StructProxy
from ._trace import ScanSnapshot, ScanTrace
from ._triggers import ScanTrigger
from ._values import SimulationError, parse_literal, type_default


# ---------------------------------------------------------------------------
# Scheduled task wrapper
# ---------------------------------------------------------------------------

@dataclass
class _ScheduledTask:
    """Runtime scheduling state for a single task."""

    task: PeriodicTask | ContinuousTask | EventTask | StartupTask
    program_names: list[str]
    period_ms: int | None = None
    next_fire_ms: int = 0
    fired: bool = False
    last_trigger_value: object = False


# ---------------------------------------------------------------------------
# Base period computation
# ---------------------------------------------------------------------------

def _compute_base_period(
    tasks: list[_ScheduledTask],
    default_ms: int,
) -> int:
    """GCD of all periodic task intervals. Falls back to *default_ms*."""
    periods = [st.period_ms for st in tasks if st.period_ms is not None]
    if not periods:
        return default_ms
    result = periods[0]
    for p in periods[1:]:
        result = math.gcd(result, p)
    return result


# ---------------------------------------------------------------------------
# GVL initialization (standalone — no SimulationContext dependency)
# ---------------------------------------------------------------------------

def _init_gvl_var(
    var: Variable,
    data_type_registry: dict[str, StructType | EnumType],
    enum_registry: dict[str, type[IntEnum]],
) -> object:
    """Allocate initial value for a single GVL variable."""
    if var.initial_value is not None:
        return parse_literal(var.initial_value, var.data_type, enum_registry)

    dt = var.data_type

    if isinstance(dt, ArrayTypeRef):
        return _init_array(dt, data_type_registry, enum_registry)

    if isinstance(dt, NamedTypeRef):
        return _init_named(dt.name, data_type_registry, enum_registry)

    default = type_default(dt)
    return default if default is not None else 0


def _init_array(
    dt: ArrayTypeRef,
    data_type_registry: dict[str, StructType | EnumType],
    enum_registry: dict[str, type[IntEnum]],
) -> list:
    """Build nested list from ArrayTypeRef dimensions."""
    def _build(dims, idx):
        dim = dims[idx]
        if not isinstance(dim.lower, int) or not isinstance(dim.upper, int):
            raise SimulationError(
                "Cannot simulate array with expression-based bounds"
            )
        size = dim.upper - dim.lower + 1
        if idx == len(dims) - 1:
            elem_default = type_default(dt.element_type)
            if elem_default is None:
                if isinstance(dt.element_type, NamedTypeRef):
                    return [
                        _init_named(
                            dt.element_type.name,
                            data_type_registry,
                            enum_registry,
                        )
                        for _ in range(size)
                    ]
                return [0] * size
            return [elem_default] * size
        return [_build(dims, idx + 1) for _ in range(size)]

    return _build(dt.dimensions, 0)


def _init_named(
    name: str,
    data_type_registry: dict[str, StructType | EnumType],
    enum_registry: dict[str, type[IntEnum]],
) -> object:
    """Allocate a named type from registries."""
    from plx.framework._library import (
        LibraryEnum,
        LibraryFB,
        LibraryStruct,
        get_library_type,
    )

    lib_type = get_library_type(name)
    if lib_type is not None:
        if issubclass(lib_type, LibraryFB):
            return lib_type.initial_state()
        if issubclass(lib_type, LibraryStruct):
            return lib_type.initial_state()
        if issubclass(lib_type, LibraryEnum):
            return lib_type.default_value()

    if name in data_type_registry:
        typedef = data_type_registry[name]
        if isinstance(typedef, StructType):
            return _init_struct(typedef, data_type_registry, enum_registry)
        if isinstance(typedef, EnumType):
            if typedef.members and typedef.members[0].value is not None:
                if name in enum_registry:
                    return enum_registry[name](typedef.members[0].value)
                return typedef.members[0].value
            return 0

    return {}


def _init_struct(
    typedef: StructType,
    data_type_registry: dict[str, StructType | EnumType],
    enum_registry: dict[str, type[IntEnum]],
) -> dict:
    """Allocate a struct as a dict of member defaults."""
    result: dict[str, object] = {}
    for member in typedef.members:
        if member.initial_value is not None:
            result[member.name] = parse_literal(
                member.initial_value, member.data_type, enum_registry,
            )
        else:
            d = type_default(member.data_type)
            if d is not None:
                result[member.name] = d
            elif isinstance(member.data_type, NamedTypeRef):
                result[member.name] = _init_named(
                    member.data_type.name, data_type_registry, enum_registry,
                )
            elif isinstance(member.data_type, ArrayTypeRef):
                result[member.name] = _init_array(
                    member.data_type, data_type_registry, enum_registry,
                )
            else:
                result[member.name] = 0
    return result


def _init_global_state(
    gvls: list[GlobalVariableList],
    data_type_registry: dict[str, StructType | EnumType],
    enum_registry: dict[str, type[IntEnum]],
) -> dict[str, dict[str, object]]:
    """Initialize global state from project GVLs."""
    state: dict[str, dict[str, object]] = {}
    for gvl in gvls:
        gvl_dict: dict[str, object] = {}
        for var in gvl.variables:
            gvl_dict[var.name] = _init_gvl_var(
                var, data_type_registry, enum_registry,
            )
        state[gvl.name] = gvl_dict
    return state


# ---------------------------------------------------------------------------
# ProjectSimulationContext
# ---------------------------------------------------------------------------

class ProjectSimulationContext:
    """Multi-program simulation context with task scheduling.

    Orchestrates multiple ``SimulationContext`` instances (one per PROGRAM
    POU), shared GVL state, and task-based scan scheduling.

    Parameters
    ----------
    project_ir : Project
        Compiled project IR.
    scan_period_ms : int
        Fallback base period when no periodic tasks are defined.
    """

    def __init__(
        self,
        project_ir: Project,
        *,
        scan_period_ms: int = 10,
    ) -> None:
        self._project = project_ir

        # Build registries from project
        pou_registry: dict[str, POU] = {p.name: p for p in project_ir.pous}

        data_type_registry: dict[str, StructType | EnumType] = {}
        enum_registry: dict[str, type[IntEnum]] = {}
        for dt in project_ir.data_types:
            if isinstance(dt, (StructType, EnumType)):
                data_type_registry[dt.name] = dt
            if isinstance(dt, EnumType):
                members = {
                    m.name: m.value
                    for m in dt.members
                    if m.value is not None
                }
                if members:
                    enum_registry[dt.name] = IntEnum(dt.name, members)

        # Initialize GVL state before creating program contexts
        self._global_state = _init_global_state(
            project_ir.global_variable_lists,
            data_type_registry,
            enum_registry,
        )

        # Build task schedule
        from ._values import _parse_time_literal

        scheduled: list[_ScheduledTask] = []
        for task_ir in project_ir.tasks:
            st = _ScheduledTask(
                task=task_ir,
                program_names=list(task_ir.assigned_pous),
            )
            if isinstance(task_ir, PeriodicTask):
                st.period_ms = _parse_time_literal(task_ir.interval)
            scheduled.append(st)

        self._tasks = scheduled
        self._base_period_ms = _compute_base_period(scheduled, scan_period_ms)

        # Create per-program SimulationContexts
        program_pous = [
            p for p in project_ir.pous if p.pou_type == POUType.PROGRAM
        ]
        if not program_pous:
            raise SimulationError("Project has no PROGRAM POUs to simulate")

        self._programs: dict[str, SimulationContext] = {}
        for pou in program_pous:
            self._programs[pou.name] = SimulationContext(
                pou=pou,
                pou_registry=pou_registry,
                data_type_registry=data_type_registry,
                enum_registry=enum_registry,
                scan_period_ms=self._base_period_ms,
                global_state=self._global_state,
            )

        # Master clock
        self._clock_ms = 0
        self._no_tasks = len(scheduled) == 0

        # ScanTrigger duck-typing: expose _state and _known_vars
        # so ScanTrigger/ScanTrace can read them without crashing.
        # Per-program .sample()/.changed() use ctx.MainProgram.scans().
        self._state: dict = {}
        self._known_vars: set = set()

    # -----------------------------------------------------------------------
    # Scan / tick
    # -----------------------------------------------------------------------

    def scan(self, n: int = 1) -> None:
        """Execute *n* base-period scan cycles with task scheduling.

        Parameters
        ----------
        n : int, optional
            Number of base-period scans to execute. Default is 1.
        """
        for _ in range(n):
            self._execute_one_scan()

    def _execute_one_scan(self) -> None:
        """Execute a single base-period scan cycle."""
        if self._no_tasks:
            # No tasks: all programs run every scan
            for ctx in self._programs.values():
                self._run_program(ctx)
        else:
            # Collect due tasks
            due: list[_ScheduledTask] = []
            for st in self._tasks:
                if isinstance(st.task, PeriodicTask):
                    if self._clock_ms >= st.next_fire_ms:
                        due.append(st)
                elif isinstance(st.task, ContinuousTask):
                    due.append(st)
                elif isinstance(st.task, StartupTask):
                    if not st.fired:
                        due.append(st)
                elif isinstance(st.task, EventTask):
                    val = self._resolve_trigger(st.task.trigger_variable)
                    if val != st.last_trigger_value:
                        due.append(st)
                        st.last_trigger_value = val

            # Sort by priority (lower number = higher priority)
            due.sort(key=lambda s: s.task.priority)

            # Execute programs for due tasks
            executed: set[str] = set()
            for st in due:
                for pname in st.program_names:
                    if pname in self._programs and pname not in executed:
                        self._run_program(self._programs[pname])
                        executed.add(pname)

                # Update scheduling state
                if isinstance(st.task, PeriodicTask):
                    st.next_fire_ms += st.period_ms
                elif isinstance(st.task, StartupTask):
                    st.fired = True

        # Advance master clock
        self._clock_ms += self._base_period_ms

        # Sync all program clocks to master
        for ctx in self._programs.values():
            object.__setattr__(ctx, "_clock_ms", self._clock_ms)

    def _run_program(self, ctx: SimulationContext) -> None:
        """Execute one scan of a program (driven by project scheduler)."""
        ctx._sync_externals_in()

        # Reset temp vars
        for var in ctx._temp_vars:
            ctx._state[var.name] = ctx._allocate_var(var)

        # Execute with master clock
        ctx._engine.clock_ms = self._clock_ms
        ctx._engine.execute()

        ctx._sync_externals_out()

        # Clear first-scan flag
        if ctx._state.get("__system_first_scan", False):
            ctx._state["__system_first_scan"] = False

    def _resolve_trigger(self, trigger_variable: str) -> object:
        """Resolve event trigger variable from global state.

        Supports ``"GVL.var"`` dotted notation or ``"var"`` (searches
        all GVLs).
        """
        if "." in trigger_variable:
            gvl_name, _, var_name = trigger_variable.partition(".")
            return self._global_state.get(gvl_name, {}).get(var_name, False)
        # Search all GVLs
        for gvl_dict in self._global_state.values():
            if trigger_variable in gvl_dict:
                return gvl_dict[trigger_variable]
        return False

    def tick(
        self,
        seconds: float = 0,
        ms: float = 0,
        *,
        trace: bool = False,
    ) -> ScanTrace | None:
        """Advance simulated time by running enough scans.

        Parameters
        ----------
        seconds, ms : float
            Simulated time to advance.
        trace : bool
            If ``True``, capture a :class:`ScanTrace` with a snapshot
            after each scan cycle.

        Returns
        -------
        ScanTrace or None
        """
        total_ms = seconds * 1000 + ms
        if total_ms <= 0:
            return ScanTrace() if trace else None
        n = math.ceil(total_ms / self._base_period_ms)
        if not trace:
            self.scan(n=n)
            return None
        # Trace mode: capture composite snapshot per scan
        result = ScanTrace()
        for _ in range(n):
            self.scan(n=1)
            values: dict[str, object] = {}
            for pname, ctx in self._programs.items():
                for k in ctx._known_vars:
                    if k in ctx._state:
                        values[f"{pname}.{k}"] = ctx._state[k]
            result._snapshots.append(
                ScanSnapshot(clock_ms=self._clock_ms, values=values)
            )
        return result

    def scan_until(
        self,
        condition: Callable[[ProjectSimulationContext], object],
        *,
        timeout_seconds: float = 60,
    ) -> None:
        """Scan until *condition(ctx)* is truthy, with a timeout.

        Parameters
        ----------
        condition : Callable[[ProjectSimulationContext], object]
            A function that receives this context and returns a truthy
            value when the wait is over.
        timeout_seconds : float, optional
            Maximum simulated time to wait in seconds. Default is 60.

        Raises
        ------
        SimulationTimeout
            If condition is not met within *timeout_seconds*.
        """
        self.scans().until(condition).timeout(seconds=timeout_seconds).run()

    def scans(self) -> ScanTrigger:
        """Return a :class:`ScanTrigger` builder for this project context."""
        return ScanTrigger(self)

    # -----------------------------------------------------------------------
    # Access
    # -----------------------------------------------------------------------

    @property
    def clock_ms(self) -> int:
        """Current simulated time in milliseconds."""
        return self._clock_ms

    @property
    def globals(self) -> StructProxy:
        """GVL access via dot notation: ``ctx.globals.IO.sensor``."""
        return StructProxy(self._global_state)

    @property
    def programs(self) -> dict[str, SimulationContext]:
        """Read-only dict of program names to SimulationContexts."""
        return dict(self._programs)

    def __getattr__(self, name: str) -> SimulationContext:
        """Provide attribute-style access to program simulation contexts.

        Allows ``ctx.Main`` instead of ``ctx.programs["Main"]``.

        Parameters
        ----------
        name : str
            Program name to look up.

        Returns
        -------
        SimulationContext
            The simulation context for the named program.

        Raises
        ------
        AttributeError
            If *name* does not match any program in the project.
        """
        try:
            programs = object.__getattribute__(self, "_programs")
        except AttributeError:
            raise AttributeError(name)
        if name in programs:
            return programs[name]
        raise AttributeError(
            f"'{type(self).__name__}' has no program '{name}'. "
            f"Available: {sorted(programs.keys())}"
        )

    def __getitem__(self, name: str) -> SimulationContext:
        return self._programs[name]

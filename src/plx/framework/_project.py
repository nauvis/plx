"""Project assembly for the plx framework.

Collects compiled POU classes and task definitions, assembles them into
a ``Project`` IR node.
"""

from __future__ import annotations

from typing import Any

from plx.model.pou import POU, POUType
from plx.model.project import Project
from plx.model.task import Task, TaskType

from ._protocols import CompiledDataType, CompiledGlobalVarList, CompiledPOU
from ._types import TimeLiteral, LTimeLiteral
from ._vendor import Vendor, validate_target


# ---------------------------------------------------------------------------
# Task builder
# ---------------------------------------------------------------------------

class PlxTask:
    """Builder for a PLC task / scheduling entry."""

    def __init__(
        self,
        name: str,
        *,
        task_type: TaskType,
        interval: str | None = None,
        priority: int = 0,
        trigger_variable: str | None = None,
        watchdog: str | None = None,
        pous: list[type] | None = None,
    ) -> None:
        self.name = name
        self.task_type = task_type
        self.interval = interval
        self.priority = priority
        self.trigger_variable = trigger_variable
        self.watchdog = watchdog
        self._pou_classes: list[type] = list(pous) if pous else []

    def compile(self) -> Task:
        """Compile to a Task IR node."""
        assigned: list[str] = []
        for cls in self._pou_classes:
            if not isinstance(cls, CompiledPOU):
                raise TypeError(
                    f"{cls.__name__} is not a compiled POU class "
                    f"(missing @fb, @program, or @function decorator)"
                )
            pou = cls.compile()
            if pou.pou_type != POUType.PROGRAM:
                raise TypeError(
                    f"Only programs can be assigned to tasks, "
                    f"but {cls.__name__} is a {pou.pou_type.value}. "
                    f"Function blocks and functions are called from "
                    f"within programs, not scheduled directly."
                )
            assigned.append(pou.name)
        return Task(
            name=self.name,
            task_type=self.task_type,
            interval=self.interval,
            priority=self.priority,
            trigger_variable=self.trigger_variable,
            watchdog=self.watchdog,
            assigned_pous=assigned,
        )


def _format_interval(value: Any) -> str:
    """Convert a duration value to an IEC time literal string."""
    if isinstance(value, (TimeLiteral, LTimeLiteral)):
        return value.to_iec()
    if isinstance(value, str):
        return value
    raise TypeError(
        f"Expected a duration (T(...), LT(...), or str), got {type(value).__name__}"
    )


def task(
    name: str,
    *,
    periodic: Any = None,
    continuous: bool = False,
    event: str | None = None,
    startup: bool = False,
    priority: int = 0,
    watchdog: Any = None,
    pous: list[type] | None = None,
) -> PlxTask:
    """Create a task definition.

    Exactly one scheduling mode must be specified: ``periodic``,
    ``continuous``, ``event``, or ``startup``.

    Examples::

        task("MainTask", periodic=T(ms=10), pous=[FastLoop], priority=1)
        task("SlowTask", periodic=T(ms=100), pous=[SlowLoop], priority=5)
        task("Background", continuous=True, pous=[Monitoring])
        task("Init", startup=True, pous=[StartupProgram])
        task("OnAlarm", event="AlarmTrigger", pous=[AlarmHandler])
    """
    modes = sum([periodic is not None, continuous, event is not None, startup])
    if modes == 0:
        raise ValueError(
            "task() requires exactly one scheduling mode: "
            "periodic=, continuous=, event=, or startup="
        )
    if modes > 1:
        raise ValueError(
            "task() accepts only one scheduling mode, "
            "got multiple of: periodic, continuous, event, startup"
        )

    watchdog_str = _format_interval(watchdog) if watchdog is not None else None

    if periodic is not None:
        return PlxTask(
            name,
            task_type=TaskType.PERIODIC,
            interval=_format_interval(periodic),
            priority=priority,
            watchdog=watchdog_str,
            pous=pous,
        )
    if continuous:
        return PlxTask(
            name,
            task_type=TaskType.CONTINUOUS,
            priority=priority,
            watchdog=watchdog_str,
            pous=pous,
        )
    if event is not None:
        return PlxTask(
            name,
            task_type=TaskType.EVENT,
            trigger_variable=event,
            priority=priority,
            watchdog=watchdog_str,
            pous=pous,
        )
    # startup
    return PlxTask(
        name,
        task_type=TaskType.STARTUP,
        priority=priority,
        watchdog=watchdog_str,
        pous=pous,
    )


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

    def compile(self, *, target: Vendor | None = None) -> Project:
        """Compile all registered POUs and data types, return a Project IR node.

        Parameters
        ----------
        target
            Optional vendor target.  When set, a validation pass checks
            that the compiled IR only uses features supported by the
            target vendor (e.g. ``Vendor.AB``).  Raises
            ``VendorValidationError`` if unsupported features are found.
        """
        # Merge discovered items from packages (if any)
        if self._packages:
            from ._discover import discover
            discovered = discover(*self._packages)
            # Dedup by id — explicit entries take priority
            explicit_ids = (
                {id(c) for c in self._pou_classes}
                | {id(c) for c in self._data_type_classes}
                | {id(c) for c in self._gvl_classes}
                | {id(t) for t in self._tasks}
            )
            for cls in discovered.pous:
                if id(cls) not in explicit_ids:
                    self._pou_classes.append(cls)
                    explicit_ids.add(id(cls))
            for cls in discovered.data_types:
                if id(cls) not in explicit_ids:
                    self._data_type_classes.append(cls)
                    explicit_ids.add(id(cls))
            for cls in discovered.global_var_lists:
                if id(cls) not in explicit_ids:
                    self._gvl_classes.append(cls)
                    explicit_ids.add(id(cls))
            for t in discovered.tasks:
                if id(t) not in explicit_ids:
                    self._tasks.append(t)
                    explicit_ids.add(id(t))

        # Compile data types
        compiled_data_types = []
        for cls in self._data_type_classes:
            if not isinstance(cls, CompiledDataType):
                raise TypeError(
                    f"{cls.__name__} is not a data type "
                    f"(missing @struct or @enumeration decorator)"
                )
            compiled_data_types.append(cls.compile())

        # Compile global variable lists
        compiled_gvls = []
        for cls in self._gvl_classes:
            if not isinstance(cls, CompiledGlobalVarList):
                raise TypeError(
                    f"{cls.__name__} is not a global variable list "
                    f"(missing @global_vars decorator)"
                )
            compiled_gvls.append(cls.compile())

        # Compile POUs
        compiled_pous: list[POU] = []
        for cls in self._pou_classes:
            if not isinstance(cls, CompiledPOU):
                raise TypeError(
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

        compiled_tasks = [t.compile() for t in self._tasks]

        result = Project(
            name=self.name,
            data_types=compiled_data_types,
            global_variable_lists=compiled_gvls,
            pous=compiled_pous,
            tasks=compiled_tasks,
        )

        if target is not None:
            validate_target(result, target)

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

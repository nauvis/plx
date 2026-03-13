"""Task builder for the plx framework.

Extracted from ``_project.py`` to break the circular import between
``_project.py`` and ``_discover.py`` — both need ``PlxTask`` but
``_project.py`` also imports ``discover()`` lazily.
"""

from __future__ import annotations

from typing import Any

from plx.model.pou import POUType
from plx.model.task import (
    ContinuousTask,
    EventTask,
    PeriodicTask,
    StartupTask,
    TaskType,
)

from datetime import timedelta

from ._errors import ProjectAssemblyError
from ._protocols import CompiledPOU
from ._types import timedelta_to_iec


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
        pous: list[type] | None = None,
    ) -> None:
        self.name = name
        self.task_type = task_type
        self.interval = interval
        self.priority = priority
        self.trigger_variable = trigger_variable
        self._pou_classes: list[type] = list(pous) if pous else []

    def compile(self) -> PeriodicTask | ContinuousTask | EventTask | StartupTask:
        """Compile to a Task IR node."""
        assigned: list[str] = []
        for cls in self._pou_classes:
            if not isinstance(cls, CompiledPOU):
                raise ProjectAssemblyError(
                    f"{cls.__name__} is not a compiled POU class "
                    f"(missing @fb, @program, or @function decorator)"
                )
            pou = cls.compile()
            if pou.pou_type != POUType.PROGRAM:
                raise ProjectAssemblyError(
                    f"Only programs can be assigned to tasks, "
                    f"but {cls.__name__} is a {pou.pou_type.value}. "
                    f"Function blocks and functions are called from "
                    f"within programs, not scheduled directly."
                )
            assigned.append(pou.name)

        common = dict(
            name=self.name,
            priority=self.priority,
            assigned_pous=assigned,
        )
        if self.task_type == TaskType.PERIODIC:
            return PeriodicTask(interval=self.interval, **common)
        if self.task_type == TaskType.EVENT:
            return EventTask(trigger_variable=self.trigger_variable, **common)
        if self.task_type == TaskType.CONTINUOUS:
            return ContinuousTask(**common)
        return StartupTask(**common)


def _format_interval(value: Any) -> str:
    """Convert a duration value to an IEC time literal string."""
    if isinstance(value, timedelta):
        return timedelta_to_iec(value)
    if isinstance(value, str):
        return value
    raise ProjectAssemblyError(
        f"Expected a duration (timedelta or str), got {type(value).__name__}"
    )


def task(
    name: str,
    *,
    periodic: Any = None,
    continuous: bool = False,
    event: str | None = None,
    startup: bool = False,
    priority: int = 0,
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
        raise ProjectAssemblyError(
            "task() requires exactly one scheduling mode: "
            "periodic=, continuous=, event=, or startup="
        )
    if modes > 1:
        raise ProjectAssemblyError(
            "task() accepts only one scheduling mode, "
            "got multiple of: periodic, continuous, event, startup"
        )

    if periodic is not None:
        return PlxTask(
            name,
            task_type=TaskType.PERIODIC,
            interval=_format_interval(periodic),
            priority=priority,
            pous=pous,
        )
    if continuous:
        return PlxTask(
            name,
            task_type=TaskType.CONTINUOUS,
            priority=priority,
            pous=pous,
        )
    if event is not None:
        return PlxTask(
            name,
            task_type=TaskType.EVENT,
            trigger_variable=event,
            priority=priority,
            pous=pous,
        )
    # startup
    return PlxTask(
        name,
        task_type=TaskType.STARTUP,
        priority=priority,
        pous=pous,
    )

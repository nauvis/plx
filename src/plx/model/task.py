"""Task / scheduling configuration for the Universal IR."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from ._base import IRModel


class PeriodicTask(IRModel):
    """Task that runs at a fixed interval (e.g. every 10ms).

    Attributes
    ----------
    priority : int
        Execution priority (lower number = higher priority).
    interval : str
        Cycle time as an IEC time literal (e.g. ``"T#10ms"``).
    assigned_pous : list of str
        Names of POUs executed by this task, in order.
    """

    kind: Literal["periodic"] = "periodic"
    name: str = Field(min_length=1)
    priority: int = 0
    interval: str
    assigned_pous: list[str] = []


class ContinuousTask(IRModel):
    """Task that runs continuously (every scan cycle).

    Attributes
    ----------
    priority : int
        Execution priority (lower number = higher priority).
    assigned_pous : list of str
        Names of POUs executed by this task, in order.
    """

    kind: Literal["continuous"] = "continuous"
    name: str = Field(min_length=1)
    priority: int = 0
    assigned_pous: list[str] = []


class EventTask(IRModel):
    """Task triggered by a rising edge on a variable.

    Attributes
    ----------
    priority : int
        Execution priority (lower number = higher priority).
    trigger_variable : str
        Name of the BOOL variable whose rising edge triggers execution.
    assigned_pous : list of str
        Names of POUs executed by this task, in order.
    """

    kind: Literal["event"] = "event"
    name: str = Field(min_length=1)
    priority: int = 0
    trigger_variable: str
    assigned_pous: list[str] = []


class StartupTask(IRModel):
    """Task that runs once at controller startup.

    Attributes
    ----------
    priority : int
        Execution priority (lower number = higher priority).
    assigned_pous : list of str
        Names of POUs executed by this task, in order.
    """

    kind: Literal["startup"] = "startup"
    name: str = Field(min_length=1)
    priority: int = 0
    assigned_pous: list[str] = []

Task = Annotated[
    Union[PeriodicTask, ContinuousTask, EventTask, StartupTask],
    Field(discriminator="kind"),
]

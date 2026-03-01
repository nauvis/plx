"""Task / scheduling configuration for the Universal IR."""

from __future__ import annotations

from enum import Enum

from pydantic import model_validator

from ._base import IRModel


class TaskType(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    PERIODIC = "PERIODIC"
    EVENT = "EVENT"
    STARTUP = "STARTUP"


class Task(IRModel):
    name: str
    task_type: TaskType
    priority: int = 0
    interval: str | None = None
    trigger_variable: str | None = None
    watchdog: str | None = None
    assigned_pous: list[str] = []

    @model_validator(mode="after")
    def _validate_task_config(self):
        if self.task_type == TaskType.PERIODIC and self.interval is None:
            raise ValueError("PERIODIC task requires 'interval'")
        if self.task_type == TaskType.EVENT and self.trigger_variable is None:
            raise ValueError("EVENT task requires 'trigger_variable'")
        if self.task_type in (TaskType.CONTINUOUS, TaskType.STARTUP):
            if self.interval is not None:
                raise ValueError(f"{self.task_type.value} task must not have 'interval'")
            if self.trigger_variable is not None:
                raise ValueError(f"{self.task_type.value} task must not have 'trigger_variable'")
        return self

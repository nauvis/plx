"""Task / scheduling configuration for the Universal IR."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field

from ._base import IRModel


class PeriodicTask(IRModel):
    kind: Literal["periodic"] = "periodic"
    name: str = Field(min_length=1)
    priority: int = 0
    interval: str
    watchdog: str | None = None
    assigned_pous: list[str] = []


class ContinuousTask(IRModel):
    kind: Literal["continuous"] = "continuous"
    name: str = Field(min_length=1)
    priority: int = 0
    watchdog: str | None = None
    assigned_pous: list[str] = []


class EventTask(IRModel):
    kind: Literal["event"] = "event"
    name: str = Field(min_length=1)
    priority: int = 0
    trigger_variable: str
    watchdog: str | None = None
    assigned_pous: list[str] = []


class StartupTask(IRModel):
    kind: Literal["startup"] = "startup"
    name: str = Field(min_length=1)
    priority: int = 0
    watchdog: str | None = None
    assigned_pous: list[str] = []


# ---------------------------------------------------------------------------
# Backward-compatible discriminated union
# ---------------------------------------------------------------------------

# Mapping from old TaskType enum values to new kind values
_TASK_TYPE_TO_KIND = {
    "PERIODIC": "periodic",
    "CONTINUOUS": "continuous",
    "EVENT": "event",
    "STARTUP": "startup",
}


def _coerce_old_task_format(data: Any) -> Any:
    """Pre-process old-style Task dicts with task_type field."""
    if not isinstance(data, dict) or "kind" in data:
        return data
    task_type = data.get("task_type")
    if task_type is None:
        return data
    # Extract the string value from TaskType enum or raw string
    tt_str = task_type.value if hasattr(task_type, "value") else str(task_type)
    kind = _TASK_TYPE_TO_KIND.get(tt_str)
    if kind is None:
        return data
    data = dict(data)
    data["kind"] = kind
    del data["task_type"]
    # Remove None fields that the new models don't accept as None
    # (e.g. PeriodicTask.interval is required, not optional)
    if kind == "periodic":
        # interval is required — leave it; remove trigger_variable if present
        data.pop("trigger_variable", None)
    elif kind == "event":
        # trigger_variable is required — leave it; remove interval if present
        data.pop("interval", None)
    elif kind in ("continuous", "startup"):
        data.pop("interval", None)
        data.pop("trigger_variable", None)
    return data


Task = Annotated[
    Union[PeriodicTask, ContinuousTask, EventTask, StartupTask],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Deprecated TaskType — kept for backward compatibility
# ---------------------------------------------------------------------------

from enum import Enum  # noqa: E402


class TaskType(str, Enum):
    """Deprecated: use PeriodicTask/ContinuousTask/EventTask/StartupTask."""

    CONTINUOUS = "CONTINUOUS"
    PERIODIC = "PERIODIC"
    EVENT = "EVENT"
    STARTUP = "STARTUP"

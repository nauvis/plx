"""Tests for task scheduling configuration."""

import pytest

from datetime import timedelta

from plx.framework import (
    BOOL,
    REAL,
    fb,
    program,
    Input,
    Output,
    ProjectAssemblyError,
    project,
    task,
    Field,
)
from plx.framework._task import PlxTask
from plx.model.task import (
    ContinuousTask,
    EventTask,
    PeriodicTask,
    StartupTask,
)
from plx.model.project import Project


# -- Fixtures ---------------------------------------------------------------

@program
class _FastLoop:
    sensor: Input[BOOL]
    out: Output[BOOL]

    def logic(self):
        self.out = self.sensor


@program
class _SlowLoop:
    value: Input[REAL]

    def logic(self):
        pass


@program
class _StartupProg:
    def logic(self):
        pass


# ---------------------------------------------------------------------------
# task() constructor
# ---------------------------------------------------------------------------

class TestTaskConstructor:
    def test_periodic_with_time_literal(self):
        t = task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop])
        assert isinstance(t, PlxTask)
        assert t.kind == "periodic"
        assert t.interval == "T#10ms"

    def test_periodic_with_string(self):
        t = task("Main", periodic="T#50ms")
        assert t.interval == "T#50ms"

    def test_continuous(self):
        t = task("Background", continuous=True)
        assert t.kind == "continuous"
        assert t.interval is None

    def test_event(self):
        t = task("OnAlarm", event="AlarmTrigger")
        assert t.kind == "event"
        assert t.trigger_variable == "AlarmTrigger"

    def test_startup(self):
        t = task("Init", startup=True)
        assert t.kind == "startup"

    def test_priority(self):
        t = task("Main", periodic=timedelta(milliseconds=10), priority=3)
        assert t.priority == 3

    def test_default_priority(self):
        t = task("Main", periodic=timedelta(milliseconds=10))
        assert t.priority == 0

    def test_no_mode_raises(self):
        with pytest.raises(ProjectAssemblyError, match="requires exactly one"):
            task("Bad")

    def test_multiple_modes_raises(self):
        with pytest.raises(ProjectAssemblyError, match="only one scheduling mode"):
            task("Bad", periodic=timedelta(milliseconds=10), continuous=True)

    def test_periodic_and_startup_raises(self):
        with pytest.raises(ProjectAssemblyError, match="only one scheduling mode"):
            task("Bad", periodic=timedelta(milliseconds=10), startup=True)

    def test_invalid_interval_type_raises(self):
        with pytest.raises(ProjectAssemblyError, match="Expected a duration"):
            task("Bad", periodic=42)


# ---------------------------------------------------------------------------
# task.compile()
# ---------------------------------------------------------------------------

class TestTaskCompile:
    def test_compiles_to_ir(self):
        t = task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop])
        ir = t.compile()
        assert isinstance(ir, PeriodicTask)
        assert ir.name == "Main"
        assert ir.kind == "periodic"
        assert ir.interval == "T#10ms"

    def test_assigned_pous(self):
        t = task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop, _SlowLoop])
        ir = t.compile()
        assert ir.assigned_pous == ["_FastLoop", "_SlowLoop"]

    def test_no_pous(self):
        t = task("Empty", continuous=True)
        ir = t.compile()
        assert ir.assigned_pous == []

    def test_non_pou_raises(self):
        class NotAPOU:
            pass

        t = task("Bad", periodic=timedelta(milliseconds=10), pous=[NotAPOU])
        with pytest.raises(ProjectAssemblyError, match="not a compiled POU"):
            t.compile()

    def test_fb_assigned_to_task_raises(self):
        @fb
        class SomeFB:
            x: Input[BOOL]
            def logic(self):
                pass

        t = task("Bad", periodic=timedelta(milliseconds=10), pous=[SomeFB])
        with pytest.raises(ProjectAssemblyError, match="Only programs can be assigned"):
            t.compile()

    def test_function_assigned_to_task_raises(self):
        from plx.framework import function

        @function
        class SomeFunc:
            x: Input[REAL]
            def logic(self) -> REAL:
                return self.x + 1.0

        t = task("Bad", periodic=timedelta(milliseconds=10), pous=[SomeFunc])
        with pytest.raises(ProjectAssemblyError, match="Only programs can be assigned"):
            t.compile()

    def test_event_trigger(self):
        t = task("OnAlarm", event="AlarmFlag", pous=[_FastLoop])
        ir = t.compile()
        assert isinstance(ir, EventTask)
        assert ir.trigger_variable == "AlarmFlag"

    def test_startup_compile(self):
        t = task("Init", startup=True, pous=[_StartupProg])
        ir = t.compile()
        assert isinstance(ir, StartupTask)
        assert ir.assigned_pous == ["_StartupProg"]


# ---------------------------------------------------------------------------
# project() with tasks
# ---------------------------------------------------------------------------

class TestProjectWithTasks:
    def test_project_with_tasks(self):
        proj = project("MyProject",
            tasks=[
                task("MainTask", periodic=timedelta(milliseconds=10), pous=[_FastLoop], priority=1),
                task("SlowTask", periodic=timedelta(milliseconds=100), pous=[_SlowLoop], priority=5),
            ]
        )
        ir = proj.compile()
        assert isinstance(ir, Project)
        assert len(ir.tasks) == 2
        assert ir.tasks[0].name == "MainTask"
        assert ir.tasks[0].interval == "T#10ms"
        assert ir.tasks[0].priority == 1
        assert ir.tasks[1].name == "SlowTask"
        assert ir.tasks[1].interval == "T#100ms"

    def test_task_pous_included_in_project(self):
        """POUs referenced in tasks are auto-included in project.pous."""
        proj = project("AutoInclude",
            tasks=[
                task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop]),
            ]
        )
        ir = proj.compile()
        pou_names = [p.name for p in ir.pous]
        assert "_FastLoop" in pou_names

    def test_no_duplicate_pous(self):
        """POUs in both pous= and tasks= aren't duplicated."""
        proj = project("NoDup",
            pous=[_FastLoop],
            tasks=[
                task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop]),
            ]
        )
        ir = proj.compile()
        pou_names = [p.name for p in ir.pous]
        assert pou_names.count("_FastLoop") == 1

    def test_mixed_pous_and_tasks(self):
        """Project with explicit pous and tasks collects all POUs."""
        proj = project("Mixed",
            pous=[_StartupProg],
            tasks=[
                task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop]),
                task("Slow", periodic=timedelta(milliseconds=100), pous=[_SlowLoop]),
            ]
        )
        ir = proj.compile()
        pou_names = {p.name for p in ir.pous}
        assert pou_names == {"_StartupProg", "_FastLoop", "_SlowLoop"}

    def test_empty_tasks(self):
        proj = project("NoTasks", pous=[_FastLoop])
        ir = proj.compile()
        assert len(ir.tasks) == 0

    def test_serializes_with_tasks(self):
        proj = project("SerProject",
            tasks=[
                task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop], priority=1),
            ]
        )
        ir = proj.compile()
        data = ir.model_dump()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["name"] == "Main"
        assert data["tasks"][0]["kind"] == "periodic"
        assert data["tasks"][0]["interval"] == "T#10ms"
        assert data["tasks"][0]["priority"] == 1
        assert data["tasks"][0]["assigned_pous"] == ["_FastLoop"]

    def test_roundtrips_with_tasks(self):
        proj = project("RoundTrip",
            tasks=[
                task("Main", periodic=timedelta(milliseconds=10), pous=[_FastLoop]),
                task("Init", startup=True, pous=[_StartupProg]),
            ]
        )
        ir = proj.compile()
        json_str = ir.model_dump_json()
        restored = Project.model_validate_json(json_str)
        assert len(restored.tasks) == 2
        assert restored.tasks[0].name == "Main"
        assert isinstance(restored.tasks[0], PeriodicTask)
        assert restored.tasks[1].name == "Init"
        assert isinstance(restored.tasks[1], StartupTask)

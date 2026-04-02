"""Tests for project-level simulation (simulate_project)."""

from __future__ import annotations

import pytest

from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    LiteralExpr,
    VariableRef,
)
from plx.model.pou import POU, Network, POUInterface, POUType
from plx.model.project import GlobalVariableList, Project
from plx.model.statements import Assignment, IfBranch, IfStatement
from plx.model.task import (
    ContinuousTask,
    EventTask,
    PeriodicTask,
    StartupTask,
)
from plx.model.types import PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable
from plx.simulate import (
    ProjectSimulationContext,
    SimulationContext,
    simulate_project,
)
from plx.simulate._triggers import SimulationTimeout
from plx.simulate._values import SimulationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOOL_REF = PrimitiveTypeRef(type=PrimitiveType.BOOL)
DINT_REF = PrimitiveTypeRef(type=PrimitiveType.DINT)
REAL_REF = PrimitiveTypeRef(type=PrimitiveType.REAL)


def _var(name, dt=DINT_REF, initial=None, description=None):
    kwargs: dict = {"name": name, "data_type": dt}
    if initial is not None:
        kwargs["initial_value"] = str(initial)
    if description is not None:
        kwargs["description"] = description
    return Variable(**kwargs)


def _bool_var(name, initial=None, description=None):
    iv = None
    if initial is not None:
        iv = "TRUE" if initial else "FALSE"
    return _var(name, BOOL_REF, iv, description)


def _program_pou(name, *, inputs=None, outputs=None, statics=None, externals=None, stmts=None):
    return POU(
        name=name,
        pou_type=POUType.PROGRAM,
        interface=POUInterface(
            input_vars=inputs or [],
            output_vars=outputs or [],
            static_vars=statics or [],
            external_vars=externals or [],
        ),
        networks=[Network(statements=stmts or [])],
    )


def _increment(var_name):
    """Statement: var_name := var_name + 1"""
    return Assignment(
        target=VariableRef(name=var_name),
        value=BinaryExpr(
            op=BinaryOp.ADD,
            left=VariableRef(name=var_name),
            right=LiteralExpr(value="1"),
        ),
    )


def _assign(target, source):
    """Statement: target := source (both variable refs)."""
    return Assignment(
        target=VariableRef(name=target),
        value=VariableRef(name=source),
    )


def _assign_literal(target, value):
    """Statement: target := literal."""
    return Assignment(
        target=VariableRef(name=target),
        value=LiteralExpr(value=str(value)),
    )


# ---------------------------------------------------------------------------
# TestProjectBasic
# ---------------------------------------------------------------------------


class TestProjectBasic:
    def test_single_program_no_tasks(self):
        """All programs run every scan when no tasks are defined."""
        prog = _program_pou(
            "Counter",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        ctx.scan(n=5)
        assert ctx.Counter.count == 5

    def test_multiple_programs_no_tasks(self):
        """All programs run each scan when no tasks are defined."""
        prog_a = _program_pou(
            "ProgA",
            statics=[_var("count_a", initial="0")],
            stmts=[_increment("count_a")],
        )
        prog_b = _program_pou(
            "ProgB",
            statics=[_var("count_b", initial="0")],
            stmts=[_increment("count_b")],
        )
        proj = Project(name="Test", pous=[prog_a, prog_b])
        ctx = simulate_project(proj)
        ctx.scan(n=3)
        assert ctx.ProgA.count_a == 3
        assert ctx.ProgB.count_b == 3

    def test_gvl_initialization(self):
        """GVL variables are initialized with their declared values."""
        gvl = GlobalVariableList(
            name="Globals",
            variables=[
                _var("speed", REAL_REF, initial="42.0"),
                _bool_var("enabled", initial=True),
                _var("count", DINT_REF),  # no initial → default 0
            ],
        )
        prog = _program_pou("Main", stmts=[])
        proj = Project(
            name="Test",
            pous=[prog],
            global_variable_lists=[gvl],
        )
        ctx = simulate_project(proj)
        assert ctx.globals.Globals.speed == 42.0
        assert ctx.globals.Globals.enabled is True
        assert ctx.globals.Globals.count == 0

    def test_clock_advances(self):
        """Clock advances by base period per scan."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        assert ctx.clock_ms == 0
        ctx.scan()
        assert ctx.clock_ms == 10  # default scan_period_ms
        ctx.tick(seconds=1)
        # 100 scans of 10ms = 1000ms additional
        assert ctx.clock_ms == 1010

    def test_program_clock_synced(self):
        """Program contexts have clocks synced to the master clock."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        ctx.scan(n=5)
        assert ctx.Main.clock_ms == ctx.clock_ms

    def test_custom_scan_period(self):
        """scan_period_ms parameter controls the base period."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj, scan_period_ms=50)
        ctx.scan()
        assert ctx.clock_ms == 50

    def test_returns_project_simulation_context(self):
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        assert isinstance(ctx, ProjectSimulationContext)


# ---------------------------------------------------------------------------
# TestTaskScheduling
# ---------------------------------------------------------------------------


class TestTaskScheduling:
    def test_periodic_different_rates(self):
        """Periodic tasks fire at their configured rates."""
        fast = _program_pou(
            "Fast",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        slow = _program_pou(
            "Slow",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[fast, slow],
            tasks=[
                PeriodicTask(
                    name="FastTask",
                    interval="T#10ms",
                    assigned_pous=["Fast"],
                    priority=1,
                ),
                PeriodicTask(
                    name="SlowTask",
                    interval="T#20ms",
                    assigned_pous=["Slow"],
                    priority=2,
                ),
            ],
        )
        ctx = simulate_project(proj)
        # Base period = GCD(10, 20) = 10ms
        # Fast fires at 0, 10, 20, 30 → 4 times in 40ms
        # Slow fires at 0, 20 → 2 times in 40ms
        ctx.tick(ms=40)
        assert ctx.Fast.count == 4
        assert ctx.Slow.count == 2

    def test_base_period_is_gcd(self):
        """Base period is GCD of periodic task intervals."""
        prog_a = _program_pou("A", stmts=[])
        prog_b = _program_pou("B", stmts=[])
        proj = Project(
            name="Test",
            pous=[prog_a, prog_b],
            tasks=[
                PeriodicTask(name="T1", interval="T#10ms", assigned_pous=["A"]),
                PeriodicTask(name="T2", interval="T#30ms", assigned_pous=["B"]),
            ],
        )
        ctx = simulate_project(proj)
        assert ctx._base_period_ms == 10

    def test_priority_ordering(self):
        """Higher priority (lower number) tasks execute first within a scan."""
        gvl = GlobalVariableList(
            name="IO",
            variables=[_var("shared_value", DINT_REF, initial="0")],
        )
        # Writer sets shared_value = 42
        writer = _program_pou(
            "Writer",
            externals=[_var("shared_value", DINT_REF, description="IO")],
            stmts=[_assign_literal("shared_value", 42)],
        )
        # Reader captures shared_value into a static
        reader = _program_pou(
            "Reader",
            externals=[_var("shared_value", DINT_REF, description="IO")],
            statics=[_var("captured", initial="0")],
            stmts=[_assign("captured", "shared_value")],
        )
        proj = Project(
            name="Test",
            pous=[writer, reader],
            global_variable_lists=[gvl],
            tasks=[
                PeriodicTask(
                    name="WriterTask",
                    interval="T#10ms",
                    assigned_pous=["Writer"],
                    priority=1,
                ),
                PeriodicTask(
                    name="ReaderTask",
                    interval="T#10ms",
                    assigned_pous=["Reader"],
                    priority=5,
                ),
            ],
        )
        ctx = simulate_project(proj)
        ctx.scan()
        # Writer (priority 1) runs before Reader (priority 5),
        # so Reader sees Writer's output (42)
        assert ctx.Reader.captured == 42

    def test_continuous_fires_every_scan(self):
        """Continuous task fires on every scan."""
        prog = _program_pou(
            "Monitor",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[prog],
            tasks=[
                ContinuousTask(name="ContTask", assigned_pous=["Monitor"]),
            ],
        )
        ctx = simulate_project(proj)
        ctx.scan(n=5)
        assert ctx.Monitor.count == 5

    def test_unassigned_programs_excluded(self):
        """Programs not assigned to any task don't run when tasks exist."""
        assigned = _program_pou(
            "Assigned",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        unassigned = _program_pou(
            "Unassigned",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[assigned, unassigned],
            tasks=[
                PeriodicTask(
                    name="Task1",
                    interval="T#10ms",
                    assigned_pous=["Assigned"],
                ),
            ],
        )
        ctx = simulate_project(proj)
        ctx.scan(n=3)
        assert ctx.Assigned.count == 3
        assert ctx.Unassigned.count == 0


# ---------------------------------------------------------------------------
# TestStartupTask
# ---------------------------------------------------------------------------


class TestStartupTask:
    def test_fires_once(self):
        """Startup task fires exactly once on the first scan."""
        prog = _program_pou(
            "Init",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[prog],
            tasks=[StartupTask(name="InitTask", assigned_pous=["Init"])],
        )
        ctx = simulate_project(proj)
        ctx.scan(n=5)
        assert ctx.Init.count == 1

    def test_startup_with_periodic(self):
        """Startup task fires once alongside periodic tasks."""
        init = _program_pou(
            "Init",
            statics=[_var("init_count", initial="0")],
            stmts=[_increment("init_count")],
        )
        main = _program_pou(
            "Main",
            statics=[_var("main_count", initial="0")],
            stmts=[_increment("main_count")],
        )
        proj = Project(
            name="Test",
            pous=[init, main],
            tasks=[
                StartupTask(name="InitTask", assigned_pous=["Init"]),
                PeriodicTask(
                    name="MainTask",
                    interval="T#10ms",
                    assigned_pous=["Main"],
                ),
            ],
        )
        ctx = simulate_project(proj)
        ctx.scan(n=5)
        assert ctx.Init.init_count == 1  # once
        assert ctx.Main.main_count == 5  # every scan


# ---------------------------------------------------------------------------
# TestEventTask
# ---------------------------------------------------------------------------


class TestEventTask:
    def test_fires_on_trigger_change(self):
        """Event task fires when trigger variable value changes."""
        gvl = GlobalVariableList(
            name="IO",
            variables=[_bool_var("trigger", initial=False)],
        )
        handler = _program_pou(
            "Handler",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[handler],
            global_variable_lists=[gvl],
            tasks=[
                EventTask(
                    name="OnTrigger",
                    trigger_variable="IO.trigger",
                    assigned_pous=["Handler"],
                ),
            ],
        )
        ctx = simulate_project(proj)

        # No change — trigger stays False
        ctx.scan(n=3)
        assert ctx.Handler.count == 0

        # Change trigger → True
        ctx.globals.IO.trigger = True
        ctx.scan()
        assert ctx.Handler.count == 1

        # Trigger stays True — no more fires
        ctx.scan(n=3)
        assert ctx.Handler.count == 1

        # Change trigger back → False
        ctx.globals.IO.trigger = False
        ctx.scan()
        assert ctx.Handler.count == 2

    def test_event_without_gvl_prefix(self):
        """Trigger variable without GVL prefix searches all GVLs."""
        gvl = GlobalVariableList(
            name="Signals",
            variables=[_bool_var("alarm", initial=False)],
        )
        handler = _program_pou(
            "AlarmHandler",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[handler],
            global_variable_lists=[gvl],
            tasks=[
                EventTask(
                    name="OnAlarm",
                    trigger_variable="alarm",
                    assigned_pous=["AlarmHandler"],
                ),
            ],
        )
        ctx = simulate_project(proj)
        ctx.scan(n=2)
        assert ctx.AlarmHandler.count == 0

        ctx.globals.Signals.alarm = True
        ctx.scan()
        assert ctx.AlarmHandler.count == 1


# ---------------------------------------------------------------------------
# TestGVLSharing
# ---------------------------------------------------------------------------


class TestGVLSharing:
    def test_two_programs_share_gvl(self):
        """Two programs communicate through shared GVL state."""
        gvl = GlobalVariableList(
            name="Shared",
            variables=[_bool_var("handshake", initial=False)],
        )
        # Writer sets handshake = True
        writer = _program_pou(
            "Writer",
            externals=[_bool_var("handshake", description="Shared")],
            stmts=[_assign_literal("handshake", "TRUE")],
        )
        # Reader copies handshake to its output
        reader = _program_pou(
            "Reader",
            externals=[_bool_var("handshake", description="Shared")],
            outputs=[_bool_var("got_signal")],
            stmts=[_assign("got_signal", "handshake")],
        )
        proj = Project(
            name="Test",
            pous=[writer, reader],
            global_variable_lists=[gvl],
        )
        ctx = simulate_project(proj)
        ctx.scan()
        assert ctx.Reader.got_signal is True
        assert ctx.globals.Shared.handshake is True

    def test_gvl_write_from_outside(self):
        """Setting globals directly is visible to programs on next scan."""
        gvl = GlobalVariableList(
            name="IO",
            variables=[_var("setpoint", REAL_REF, initial="0.0")],
        )
        prog = _program_pou(
            "Controller",
            externals=[_var("setpoint", REAL_REF, description="IO")],
            outputs=[_var("output", REAL_REF)],
            stmts=[_assign("output", "setpoint")],
        )
        proj = Project(
            name="Test",
            pous=[prog],
            global_variable_lists=[gvl],
        )
        ctx = simulate_project(proj)
        ctx.scan()
        assert ctx.Controller.output == 0.0

        ctx.globals.IO.setpoint = 75.5
        ctx.scan()
        assert ctx.Controller.output == 75.5


# ---------------------------------------------------------------------------
# TestProgramAccess
# ---------------------------------------------------------------------------


class TestProgramAccess:
    def test_attribute_access(self):
        """Programs are accessible as attributes."""
        prog = _program_pou(
            "MainProg",
            statics=[_var("speed", REAL_REF, initial="50.0")],
            stmts=[],
        )
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        assert ctx.MainProg.speed == 50.0

    def test_dict_access(self):
        """Programs are accessible via dict-style indexing."""
        prog = _program_pou(
            "MainProg",
            statics=[_var("speed", REAL_REF, initial="50.0")],
            stmts=[],
        )
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        ctx["MainProg"].speed = 75.0
        assert ctx["MainProg"].speed == 75.0

    def test_globals_dot_access(self):
        """GVL variables are accessible via globals.GVL.var dot notation."""
        gvl = GlobalVariableList(
            name="IO",
            variables=[_bool_var("sensor", initial=True)],
        )
        prog = _program_pou("Main", stmts=[])
        proj = Project(
            name="Test",
            pous=[prog],
            global_variable_lists=[gvl],
        )
        ctx = simulate_project(proj)
        assert ctx.globals.IO.sensor is True
        ctx.globals.IO.sensor = False
        assert ctx.globals.IO.sensor is False

    def test_programs_property(self):
        """programs property returns a dict of program contexts."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        assert "Main" in ctx.programs
        assert isinstance(ctx.programs["Main"], SimulationContext)

    def test_unknown_program_raises(self):
        """Accessing a non-existent program raises AttributeError."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        with pytest.raises(AttributeError, match="NoSuchProgram"):
            _ = ctx.NoSuchProgram


# ---------------------------------------------------------------------------
# TestScanUntil
# ---------------------------------------------------------------------------


class TestScanUntil:
    def test_scan_until_condition(self):
        """scan_until waits for a condition across programs."""
        prog = _program_pou(
            "Counter",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        ctx.scan_until(
            lambda c: c.Counter.count >= 10,
            timeout_seconds=1,
        )
        assert ctx.Counter.count >= 10

    def test_scan_until_timeout(self):
        """scan_until raises SimulationTimeout when condition not met."""
        prog = _program_pou("Stuck", stmts=[])  # does nothing
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        with pytest.raises(SimulationTimeout):
            ctx.scan_until(
                lambda c: False,  # never true
                timeout_seconds=0.1,
            )

    def test_scans_trigger_builder(self):
        """scans() returns a ScanTrigger that works with project context."""
        prog = _program_pou(
            "Counter",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        ctx.scans().until(lambda c: c.Counter.count >= 5).timeout(seconds=1).run()
        assert ctx.Counter.count >= 5


# ---------------------------------------------------------------------------
# TestTickTrace
# ---------------------------------------------------------------------------


class TestTickTrace:
    def test_tick_with_trace(self):
        """tick(trace=True) captures composite snapshots."""
        prog = _program_pou(
            "Counter",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        trace = ctx.tick(ms=30, trace=True)
        assert trace is not None
        assert len(trace) == 3  # 30ms / 10ms = 3 scans
        # Composite keys: "ProgramName.var_name"
        vals = trace.values_of("Counter.count")
        assert vals == [1, 2, 3]

    def test_tick_without_trace(self):
        """tick without trace returns None."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        result = ctx.tick(ms=50)
        assert result is None

    def test_tick_zero_returns_empty(self):
        """tick with zero time returns empty trace or None."""
        prog = _program_pou("Main", stmts=[])
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)
        assert ctx.tick(ms=0, trace=True) is not None
        assert len(ctx.tick(ms=0, trace=True)) == 0
        assert ctx.tick(ms=0) is None

    def test_tick_multiple_programs(self):
        """Trace captures state from all programs."""
        prog_a = _program_pou(
            "ProgA",
            statics=[_var("val_a", initial="0")],
            stmts=[_increment("val_a")],
        )
        prog_b = _program_pou(
            "ProgB",
            statics=[_var("val_b", initial="0")],
            stmts=[_increment("val_b")],
        )
        proj = Project(name="Test", pous=[prog_a, prog_b])
        ctx = simulate_project(proj)
        trace = ctx.tick(ms=20, trace=True)
        assert trace.values_of("ProgA.val_a") == [1, 2]
        assert trace.values_of("ProgB.val_b") == [1, 2]


# ---------------------------------------------------------------------------
# TestAcceptPlxProject
# ---------------------------------------------------------------------------


class TestAcceptPlxProject:
    def test_accept_plx_project_builder(self):
        """simulate_project accepts an uncompiled PlxProject builder."""
        from plx.framework import (
            BOOL,
            Output,
        )
        from plx.framework import (
            program as program_deco,
        )
        from plx.framework import (
            project as project_builder,
        )

        @program_deco
        class AcceptTestProgram:
            flag: Output[BOOL]

            def logic(self):
                self.flag = True

        proj_builder = project_builder(
            "AcceptTest",
            pous=[AcceptTestProgram],
        )
        ctx = simulate_project(proj_builder)
        ctx.scan()
        assert ctx.AcceptTestProgram.flag is True

    def test_rejects_invalid_target(self):
        """simulate_project raises TypeError for unsupported input."""
        with pytest.raises(TypeError, match="simulate_project"):
            simulate_project("not a project")


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_programs_raises_error(self):
        """Project with no PROGRAM POUs raises SimulationError."""
        fb = POU(
            name="MyFB",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(),
            networks=[],
        )
        proj = Project(name="Test", pous=[fb])
        with pytest.raises(SimulationError, match="no PROGRAM"):
            simulate_project(proj)

    def test_empty_project_raises_error(self):
        """Project with no POUs at all raises SimulationError."""
        proj = Project(name="Test")
        with pytest.raises(SimulationError, match="no PROGRAM"):
            simulate_project(proj)

    def test_task_references_missing_pou(self):
        """Task referencing a non-existent POU is silently skipped."""
        prog = _program_pou(
            "Existing",
            statics=[_var("count", initial="0")],
            stmts=[_increment("count")],
        )
        proj = Project(
            name="Test",
            pous=[prog],
            tasks=[
                PeriodicTask(
                    name="Task1",
                    interval="T#10ms",
                    assigned_pous=["Existing"],
                ),
                PeriodicTask(
                    name="Task2",
                    interval="T#10ms",
                    assigned_pous=["NonExistent"],
                ),
            ],
        )
        ctx = simulate_project(proj)
        ctx.scan(n=3)
        assert ctx.Existing.count == 3

    def test_fb_pous_excluded_from_programs(self):
        """Function blocks in the project don't get SimulationContexts."""
        prog = _program_pou("Main", stmts=[])
        fb = POU(
            name="HelperFB",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(),
            networks=[],
        )
        proj = Project(name="Test", pous=[prog, fb])
        ctx = simulate_project(proj)
        assert "Main" in ctx.programs
        assert "HelperFB" not in ctx.programs

    def test_first_scan_flag(self):
        """First-scan flag is True on first scan, False after."""
        prog = _program_pou(
            "Main",
            statics=[_bool_var("was_first")],
            stmts=[
                IfStatement(
                    if_branch=IfBranch(
                        condition=VariableRef(name="__system_first_scan"),
                        body=[_assign_literal("was_first", "TRUE")],
                    ),
                ),
            ],
        )
        # Manually add system_first_scan support: the engine reads
        # __system_first_scan from state, which is set by SimulationContext.
        proj = Project(name="Test", pous=[prog])
        ctx = simulate_project(proj)

        # First scan: __system_first_scan is True
        ctx.scan()
        assert ctx.Main.was_first is True

        # Reset the flag to verify it doesn't fire again
        ctx.Main.was_first = False
        ctx.scan()
        assert ctx.Main.was_first is False

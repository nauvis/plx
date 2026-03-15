"""Stress tests: push the AI agent workflow to its limits.

Each test simulates a realistic multi-file project that the AI agent would
generate, runs it through the sandboxed test runner, and verifies correctness.
These exercise edge cases, complex patterns, and interactions that are most
likely to break.
"""

from __future__ import annotations

import pytest

from web.backend.test_runner import run_tests


def _assert_pass(result, *, expected_count=None):
    """Assert all tests passed, with detailed failure info."""
    failures = [r for r in result.results if not r.passed]
    if failures or result.error:
        lines = []
        if result.error:
            lines.append(f"Runner error: {result.error}")
        for r in failures:
            lines.append(f"FAIL {r.file}::{r.name}: {r.error}")
            if r.traceback:
                for tb_line in r.traceback.split("\n")[:10]:
                    lines.append(f"  {tb_line}")
        pytest.fail("\n".join(lines))
    if expected_count is not None:
        assert len(result.results) == expected_count, (
            f"Expected {expected_count} tests, got {len(result.results)}: "
            f"{[r.name for r in result.results]}"
        )


class TestNestedFBHierarchy:
    """Deeply nested FB composition across multiple files."""

    def test_three_level_fb_nesting(self):
        """Program → MotorCtrl → PIDController → all across files."""
        files = {
            "pid.py": """\
from plx.framework import *

@fb
class PIDCtrl:
    setpoint: Input[REAL]
    process_var: Input[REAL]
    output: Output[REAL]
    kp: Input[REAL]
    error: Static[REAL]

    def logic(self):
        self.error = self.setpoint - self.process_var
        self.output = self.kp * self.error
""",
            "motor.py": """\
from plx.framework import *
from pid import PIDCtrl

@fb
class MotorCtrl:
    cmd_speed: Input[REAL]
    feedback_speed: Input[REAL]
    drive_output: Output[REAL]
    running: Output[BOOL]
    pid: PIDCtrl

    def logic(self):
        self.running = self.cmd_speed > 0.0
        if self.running:
            self.pid(setpoint=self.cmd_speed, process_var=self.feedback_speed, kp=1.5)
            self.drive_output = self.pid.output
        else:
            self.drive_output = 0.0
""",
            "main.py": """\
from plx.framework import *
from motor import MotorCtrl

@global_vars
class IO:
    speed_cmd: REAL = 0.0
    speed_feedback: REAL = 0.0
    drive_output: REAL = 0.0

@program
class SpeedLoop:
    speed_cmd: External[REAL] = Field(description="IO")
    speed_feedback: External[REAL] = Field(description="IO")
    drive_output: External[REAL] = Field(description="IO")
    motor: MotorCtrl

    def logic(self):
        self.motor(cmd_speed=self.speed_cmd, feedback_speed=self.speed_feedback)
        self.drive_output = self.motor.drive_output
""",
            "test_nested.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_nested_fb_through_project():
    proj_ir = project("NestedTest",
        pous=[SpeedLoop],
        global_var_lists=[IO],
        tasks=[task("Fast", periodic=timedelta(milliseconds=10), pous=[SpeedLoop])],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Set speed command, no feedback
    ctx.globals.IO.speed_cmd = 100.0
    ctx.globals.IO.speed_feedback = 0.0
    ctx.scan()

    # PID output = kp * (setpoint - pv) = 1.5 * (100 - 0) = 150.0
    assert ctx.globals.IO.drive_output == 150.0
    assert ctx.SpeedLoop.motor.running == True

    # With feedback matching setpoint
    ctx.globals.IO.speed_feedback = 100.0
    ctx.scan()
    # PID output = 1.5 * (100 - 100) = 0.0
    assert ctx.globals.IO.drive_output == 0.0

def test_nested_fb_unit():
    ctx = simulate(MotorCtrl, pous=[PIDCtrl])
    ctx.cmd_speed = 50.0
    ctx.feedback_speed = 20.0
    ctx.scan()
    # PID: kp * (50 - 20) = 1.5 * 30 = 45.0
    assert ctx.drive_output == 45.0
    assert ctx.running == True

def test_pid_unit():
    ctx = simulate(PIDCtrl)
    ctx.setpoint = 100.0
    ctx.process_var = 60.0
    ctx.kp = 2.0
    ctx.scan()
    assert ctx.output == 80.0  # 2.0 * (100 - 60)
""",
        }
        _assert_pass(run_tests(files), expected_count=3)


class TestStructsAndEnumsInGVLs:
    """Custom data types used in GVLs and shared between programs."""

    def test_enum_state_machine_across_programs(self):
        """Enum-based state machine with programs reading/writing state."""
        files = {
            "machine_types.py": """\
from plx.framework import *

class MachineState(IntEnum):
    IDLE = 0
    RUNNING = 1
    PAUSED = 2
    FAULTED = 3
""",
            "globals.py": """\
from plx.framework import *

@global_vars
class Status:
    state: DINT = 0
    fault_code: DINT = 0
    cycle_count: DINT = 0
""",
            "controller.py": """\
from plx.framework import *

@program
class Controller:
    state: External[DINT] = Field(description="Status")
    cycle_count: External[DINT] = Field(description="Status")
    cmd_start: Input[BOOL]
    cmd_stop: Input[BOOL]

    def logic(self):
        if self.state == 0:  # IDLE
            if self.cmd_start:
                self.state = 1  # RUNNING
        elif self.state == 1:  # RUNNING
            self.cycle_count = self.cycle_count + 1
            if self.cmd_stop:
                self.state = 0  # IDLE
""",
            "monitor.py": """\
from plx.framework import *

@program
class Monitor:
    state: External[DINT] = Field(description="Status")
    cycle_count: External[DINT] = Field(description="Status")
    is_running: Output[BOOL]
    total_cycles: Output[DINT]

    def logic(self):
        self.is_running = self.state == 1
        self.total_cycles = self.cycle_count
""",
            "test_state_machine.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_state_transitions():
    proj_ir = project("SMTest",
        pous=[Controller, Monitor],
        data_types=[MachineState],
        global_var_lists=[Status],
        tasks=[
            task("Control", periodic=timedelta(milliseconds=10),
                 pous=[Controller], priority=1),
            task("Mon", periodic=timedelta(milliseconds=10),
                 pous=[Monitor], priority=5),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Initially idle
    ctx.scan()
    assert ctx.Monitor.is_running == False
    assert ctx.globals.Status.state == 0

    # Start — state transitions to RUNNING on this scan,
    # but cycle_count doesn't increment yet (elif branch)
    ctx.Controller.cmd_start = True
    ctx.scan()
    assert ctx.globals.Status.state == 1
    assert ctx.Monitor.is_running == True

    # Run for 5 more scans — cycle_count increments each
    ctx.Controller.cmd_start = False
    ctx.scan(n=5)
    assert ctx.globals.Status.cycle_count == 5

    # Stop
    ctx.Controller.cmd_stop = True
    ctx.scan()
    assert ctx.globals.Status.state == 0
    assert ctx.Monitor.is_running == False
""",
        }
        _assert_pass(run_tests(files), expected_count=1)

    def test_struct_in_gvl(self):
        """Struct type used in GVL variables shared between programs."""
        files = {
            "recipe_types.py": """\
from plx.framework import *

@struct
class RecipeData:
    temperature: REAL = 25.0
    pressure: REAL = 1.0
    duration_ms: DINT = 5000
""",
            "globals.py": """\
from plx.framework import *
from recipe_types import RecipeData

@global_vars
class Recipe:
    active: RecipeData
""",
            "programs.py": """\
from plx.framework import *
from recipe_types import RecipeData

@program
class RecipeWriter:
    active: External[RecipeData] = Field(description="Recipe")
    cmd_load: Input[BOOL]

    def logic(self):
        if self.cmd_load:
            self.active.temperature = 85.0
            self.active.pressure = 2.5
            self.active.duration_ms = 10000

@program
class RecipeReader:
    active: External[RecipeData] = Field(description="Recipe")
    current_temp: Output[REAL]
    current_pressure: Output[REAL]

    def logic(self):
        self.current_temp = self.active.temperature
        self.current_pressure = self.active.pressure
""",
            "test_struct_gvl.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_struct_shared_via_gvl():
    proj_ir = project("StructTest",
        pous=[RecipeWriter, RecipeReader],
        data_types=[RecipeData],
        global_var_lists=[Recipe],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Initial defaults from @struct
    ctx.scan()
    assert ctx.RecipeReader.current_temp == 25.0
    assert ctx.RecipeReader.current_pressure == 1.0

    # Load new recipe
    ctx.RecipeWriter.cmd_load = True
    ctx.scan()
    assert ctx.RecipeReader.current_temp == 85.0
    assert ctx.RecipeReader.current_pressure == 2.5

def test_struct_access_via_globals():
    proj_ir = project("StructTest2",
        pous=[RecipeWriter, RecipeReader],
        data_types=[RecipeData],
        global_var_lists=[Recipe],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan()

    # Access struct fields through globals proxy
    assert ctx.globals.Recipe.active.temperature == 25.0
    assert ctx.globals.Recipe.active.pressure == 1.0

    # Set struct fields through globals proxy
    ctx.globals.Recipe.active.temperature = 99.0
    ctx.scan()
    assert ctx.RecipeReader.current_temp == 99.0
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


class TestTimerLogicInProject:
    """Timer sentinels (TON/TOF) executing within project simulation."""

    def test_ton_timer_in_program(self):
        """TON timer inside a program tested via project tick()."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class DelayedStart:
    cmd: Input[BOOL]
    output: Output[BOOL]

    def logic(self):
        self.output = delayed(self.cmd, timedelta(seconds=2))
""",
            "test_timer.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_ton_delay():
    proj_ir = project("TimerTest", pous=[DelayedStart]).compile()
    ctx = simulate_project(proj_ir)

    ctx.DelayedStart.cmd = True
    ctx.tick(seconds=1)
    assert ctx.DelayedStart.output == False  # not enough time

    ctx.tick(seconds=1.5)
    assert ctx.DelayedStart.output == True  # 2.5s > 2s delay

def test_ton_resets_on_false():
    proj_ir = project("TimerTest2", pous=[DelayedStart]).compile()
    ctx = simulate_project(proj_ir)

    ctx.DelayedStart.cmd = True
    ctx.tick(seconds=1.5)
    assert ctx.DelayedStart.output == False

    # Remove input before timer expires
    ctx.DelayedStart.cmd = False
    ctx.scan()
    ctx.DelayedStart.cmd = True
    ctx.tick(seconds=1.5)
    # Timer reset — not enough time from restart
    assert ctx.DelayedStart.output == False

    ctx.tick(seconds=1)
    assert ctx.DelayedStart.output == True
""",
        }
        _assert_pass(run_tests(files), expected_count=2)

    def test_edge_detection_in_program(self):
        """Rising/falling edge detection in project simulation."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class EdgeCounter:
    trigger: Input[BOOL]
    rise_count: Static[DINT]
    fall_count: Static[DINT]

    def logic(self):
        if rising(self.trigger):
            self.rise_count = self.rise_count + 1
        if falling(self.trigger):
            self.fall_count = self.fall_count + 1
""",
            "test_edges.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_rising_falling_edges():
    proj_ir = project("EdgeTest", pous=[EdgeCounter]).compile()
    ctx = simulate_project(proj_ir)

    # Initial scan — no edges
    ctx.scan()
    assert ctx.EdgeCounter.rise_count == 0
    assert ctx.EdgeCounter.fall_count == 0

    # Rising edge
    ctx.EdgeCounter.trigger = True
    ctx.scan()
    assert ctx.EdgeCounter.rise_count == 1
    assert ctx.EdgeCounter.fall_count == 0

    # Stay high — no edge
    ctx.scan(n=3)
    assert ctx.EdgeCounter.rise_count == 1

    # Falling edge
    ctx.EdgeCounter.trigger = False
    ctx.scan()
    assert ctx.EdgeCounter.rise_count == 1
    assert ctx.EdgeCounter.fall_count == 1

    # Rapid toggle
    ctx.EdgeCounter.trigger = True
    ctx.scan()
    ctx.EdgeCounter.trigger = False
    ctx.scan()
    ctx.EdgeCounter.trigger = True
    ctx.scan()
    assert ctx.EdgeCounter.rise_count == 3
    assert ctx.EdgeCounter.fall_count == 2
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


class TestSFCInProject:
    """SFC programs running as tasks in project simulation."""

    def test_sfc_sequence_in_project(self):
        """SFC program executing as a periodic task."""
        files = {
            "sequence.py": """\
from plx.framework import *

@sfc
class FillSequence:
    cmd_start: Input[BOOL]
    tank_full: Input[BOOL]
    valve_open: Output[BOOL]
    done: Output[BOOL]

    s_idle = step(initial=True)
    s_filling = step()
    s_done = step()

    @transition(s_idle >> s_filling)
    def t_start(self):
        return self.cmd_start

    @s_filling.action
    def filling_action(self):
        self.valve_open = True

    @transition(s_filling >> s_done)
    def t_full(self):
        return self.tank_full

    @s_done.entry
    def done_entry(self):
        self.valve_open = False
        self.done = True
""",
            "test_sfc.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_sfc_in_project():
    proj_ir = project("SFCTest",
        pous=[FillSequence],
        tasks=[task("SeqTask", periodic=timedelta(milliseconds=10), pous=[FillSequence])],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Initially in idle
    ctx.scan()
    assert ctx.FillSequence.valve_open == False
    assert ctx.FillSequence.done == False

    # Start command
    ctx.FillSequence.cmd_start = True
    ctx.scan()
    # Should transition to s_filling
    ctx.scan()
    assert ctx.FillSequence.valve_open == True

    # Tank fills up
    ctx.FillSequence.tank_full = True
    ctx.scan()
    ctx.scan()
    assert ctx.FillSequence.done == True
    assert ctx.FillSequence.valve_open == False

def test_sfc_unit():
    \"\"\"Same SFC tested with single-POU simulate for comparison.\"\"\"
    ctx = simulate(FillSequence)
    ctx.cmd_start = True
    ctx.scan()
    ctx.scan()
    assert ctx.valve_open == True
    ctx.tank_full = True
    ctx.scan()
    ctx.scan()
    assert ctx.done == True
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


class TestConcurrentGVLAccess:
    """Multiple programs writing to the same GVL — last writer wins."""

    def test_two_writers_same_variable(self):
        """Two programs write to the same GVL var — priority determines order."""
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class Shared:
    value: DINT = 0

@program
class WriterA:
    value: External[DINT] = Field(description="Shared")

    def logic(self):
        self.value = 100

@program
class WriterB:
    value: External[DINT] = Field(description="Shared")

    def logic(self):
        self.value = 200
""",
            "test_concurrent.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_last_writer_wins_by_priority():
    # WriterA priority=1 (runs first), WriterB priority=5 (runs second)
    proj_ir = project("ConcurrentTest",
        pous=[WriterA, WriterB],
        global_var_lists=[Shared],
        tasks=[
            task("TaskA", periodic=timedelta(milliseconds=10),
                 pous=[WriterA], priority=1),
            task("TaskB", periodic=timedelta(milliseconds=10),
                 pous=[WriterB], priority=5),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan()
    # WriterB runs last, so its value persists
    assert ctx.globals.Shared.value == 200

def test_reversed_priority():
    # WriterB priority=1 (runs first), WriterA priority=5 (runs second)
    proj_ir = project("ConcurrentTest2",
        pous=[WriterA, WriterB],
        global_var_lists=[Shared],
        tasks=[
            task("TaskA", periodic=timedelta(milliseconds=10),
                 pous=[WriterA], priority=5),
            task("TaskB", periodic=timedelta(milliseconds=10),
                 pous=[WriterB], priority=1),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan()
    # WriterA runs last now, so its value persists
    assert ctx.globals.Shared.value == 100
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


class TestLargeProject:
    """Simulate a realistically large project with many POUs and GVLs."""

    def test_five_programs_three_gvls(self):
        """5 programs, 3 GVLs, mixed task types."""
        files = {
            "types.py": """\
from plx.framework import *

@struct
class AlarmInfo:
    active: BOOL = False
    code: DINT = 0
""",
            "gvls.py": """\
from plx.framework import *

@global_vars
class Inputs:
    sensor_1: REAL = 0.0
    sensor_2: REAL = 0.0
    emergency_stop: BOOL = False

@global_vars
class Outputs:
    motor_1_speed: REAL = 0.0
    motor_2_speed: REAL = 0.0
    alarm_light: BOOL = False

@global_vars
class Internal:
    system_ready: BOOL = False
    alarm_count: DINT = 0
""",
            "init_prog.py": """\
from plx.framework import *

@program
class InitProgram:
    system_ready: External[BOOL] = Field(description="Internal")

    def logic(self):
        self.system_ready = True
""",
            "fast_ctrl.py": """\
from plx.framework import *

@program
class FastControl:
    sensor_1: External[REAL] = Field(description="Inputs")
    motor_1_speed: External[REAL] = Field(description="Outputs")
    system_ready: External[BOOL] = Field(description="Internal")

    def logic(self):
        if self.system_ready:
            self.motor_1_speed = self.sensor_1 * 10.0
""",
            "slow_ctrl.py": """\
from plx.framework import *

@program
class SlowControl:
    sensor_2: External[REAL] = Field(description="Inputs")
    motor_2_speed: External[REAL] = Field(description="Outputs")
    system_ready: External[BOOL] = Field(description="Internal")

    def logic(self):
        if self.system_ready:
            self.motor_2_speed = self.sensor_2 * 5.0
""",
            "alarm_prog.py": """\
from plx.framework import *

@program
class AlarmMonitor:
    emergency_stop: External[BOOL] = Field(description="Inputs")
    alarm_light: External[BOOL] = Field(description="Outputs")
    alarm_count: External[DINT] = Field(description="Internal")
    prev_alarm: Static[BOOL]

    def logic(self):
        self.alarm_light = self.emergency_stop
        if self.emergency_stop and not self.prev_alarm:
            self.alarm_count = self.alarm_count + 1
        self.prev_alarm = self.emergency_stop
""",
            "diagnostics.py": """\
from plx.framework import *

@program
class Diagnostics:
    system_ready: External[BOOL] = Field(description="Internal")
    alarm_count: External[DINT] = Field(description="Internal")
    ok: Output[BOOL]

    def logic(self):
        self.ok = self.system_ready and self.alarm_count == 0
""",
            "test_large.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def _build_project():
    return project("LargeProject",
        pous=[InitProgram, FastControl, SlowControl, AlarmMonitor, Diagnostics],
        data_types=[AlarmInfo],
        global_var_lists=[Inputs, Outputs, Internal],
        tasks=[
            task("Init", startup=True, pous=[InitProgram], priority=0),
            task("FastTask", periodic=timedelta(milliseconds=10),
                 pous=[FastControl, AlarmMonitor], priority=1),
            task("SlowTask", periodic=timedelta(milliseconds=50),
                 pous=[SlowControl], priority=5),
            task("DiagTask", periodic=timedelta(milliseconds=100),
                 pous=[Diagnostics], priority=10),
        ],
    ).compile()

def test_startup_initializes():
    ctx = simulate_project(_build_project())
    ctx.scan()
    assert ctx.globals.Internal.system_ready == True

def test_fast_control_responds():
    ctx = simulate_project(_build_project())
    ctx.globals.Inputs.sensor_1 = 5.0
    ctx.scan()  # startup + first periodic
    assert ctx.globals.Outputs.motor_1_speed == 50.0  # 5.0 * 10.0

def test_slow_control_rate():
    ctx = simulate_project(_build_project())
    ctx.globals.Inputs.sensor_2 = 4.0
    # Base period = GCD(10, 50, 100) = 10ms
    # SlowControl fires at 0, 50, 100, ...
    ctx.tick(ms=100)
    assert ctx.globals.Outputs.motor_2_speed == 20.0  # 4.0 * 5.0

def test_alarm_monitoring():
    ctx = simulate_project(_build_project())
    ctx.scan()  # init
    assert ctx.Diagnostics.ok == True

    # Trigger emergency
    ctx.globals.Inputs.emergency_stop = True
    ctx.scan()
    assert ctx.globals.Outputs.alarm_light == True
    assert ctx.globals.Internal.alarm_count == 1

    # Diagnostics runs at 100ms — need to tick to its period
    ctx.tick(ms=100)
    assert ctx.Diagnostics.ok == False

def test_alarm_count_increments_on_edges():
    ctx = simulate_project(_build_project())
    ctx.scan()

    # First alarm
    ctx.globals.Inputs.emergency_stop = True
    ctx.scan()
    assert ctx.globals.Internal.alarm_count == 1

    # Stays high — no new count
    ctx.scan(n=5)
    assert ctx.globals.Internal.alarm_count == 1

    # Clear and re-trigger
    ctx.globals.Inputs.emergency_stop = False
    ctx.scan()
    ctx.globals.Inputs.emergency_stop = True
    ctx.scan()
    assert ctx.globals.Internal.alarm_count == 2

def test_full_integration():
    ctx = simulate_project(_build_project())

    # System initializes
    ctx.scan()
    assert ctx.globals.Internal.system_ready == True

    # Normal operation
    ctx.globals.Inputs.sensor_1 = 3.0
    ctx.globals.Inputs.sensor_2 = 2.0
    ctx.tick(seconds=1)

    assert ctx.globals.Outputs.motor_1_speed == 30.0
    assert ctx.globals.Outputs.motor_2_speed == 10.0
    assert ctx.globals.Outputs.alarm_light == False
    assert ctx.Diagnostics.ok == True

    # Emergency stop
    ctx.globals.Inputs.emergency_stop = True
    ctx.tick(seconds=1)
    assert ctx.globals.Outputs.alarm_light == True
""",
        }
        _assert_pass(run_tests(files), expected_count=6)


class TestMatchCaseStateMachine:
    """Match/case with enum-style state machine in project context."""

    def test_batch_process_state_machine(self):
        """Multi-state batch process controlled via GVL commands."""
        files = {
            "batch.py": """\
from plx.framework import *

class BatchState(IntEnum):
    IDLE = 0
    FILLING = 1
    MIXING = 2
    DRAINING = 3
    DONE = 4

@global_vars
class BatchIO:
    cmd_start: BOOL = False
    fill_level: REAL = 0.0
    mix_complete: BOOL = False
    drain_complete: BOOL = False
    fill_valve: BOOL = False
    mixer_on: BOOL = False
    drain_valve: BOOL = False

@program
class BatchController:
    cmd_start: External[BOOL] = Field(description="BatchIO")
    fill_level: External[REAL] = Field(description="BatchIO")
    mix_complete: External[BOOL] = Field(description="BatchIO")
    drain_complete: External[BOOL] = Field(description="BatchIO")
    fill_valve: External[BOOL] = Field(description="BatchIO")
    mixer_on: External[BOOL] = Field(description="BatchIO")
    drain_valve: External[BOOL] = Field(description="BatchIO")
    state: Static[DINT]

    def logic(self):
        if self.state == 0:  # IDLE
            self.fill_valve = False
            self.mixer_on = False
            self.drain_valve = False
            if self.cmd_start:
                self.state = 1
        elif self.state == 1:  # FILLING
            self.fill_valve = True
            if self.fill_level >= 90.0:
                self.fill_valve = False
                self.state = 2
        elif self.state == 2:  # MIXING
            self.mixer_on = True
            if self.mix_complete:
                self.mixer_on = False
                self.state = 3
        elif self.state == 3:  # DRAINING
            self.drain_valve = True
            if self.drain_complete:
                self.drain_valve = False
                self.state = 4
        elif self.state == 4:  # DONE
            self.state = 0
""",
            "test_batch.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_full_batch_cycle():
    proj_ir = project("BatchTest",
        pous=[BatchController],
        data_types=[BatchState],
        global_var_lists=[BatchIO],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Start batch — state transitions to FILLING (but elif doesn't act yet)
    ctx.globals.BatchIO.cmd_start = True
    ctx.scan()
    assert ctx.BatchController.state == 1  # FILLING

    # Next scan: now in FILLING branch, fill_valve opens
    ctx.globals.BatchIO.cmd_start = False
    ctx.scan()
    assert ctx.globals.BatchIO.fill_valve == True

    # Simulate tank filling — state transitions to MIXING
    ctx.globals.BatchIO.fill_level = 95.0
    ctx.scan()
    assert ctx.BatchController.state == 2  # MIXING
    assert ctx.globals.BatchIO.fill_valve == False

    # Next scan: now in MIXING branch, mixer starts
    ctx.scan()
    assert ctx.globals.BatchIO.mixer_on == True

    # Mix complete — transitions to DRAINING
    ctx.globals.BatchIO.mix_complete = True
    ctx.scan()
    assert ctx.BatchController.state == 3  # DRAINING
    assert ctx.globals.BatchIO.mixer_on == False

    # Next scan: drain valve opens
    ctx.scan()
    assert ctx.globals.BatchIO.drain_valve == True

    # Drain complete — transitions to DONE
    ctx.globals.BatchIO.drain_complete = True
    ctx.scan()
    assert ctx.BatchController.state == 4  # DONE

    # Back to idle
    ctx.scan()
    assert ctx.BatchController.state == 0  # IDLE
    assert ctx.globals.BatchIO.drain_valve == False

def test_idle_stays_idle():
    proj_ir = project("BatchTest2",
        pous=[BatchController],
        data_types=[BatchState],
        global_var_lists=[BatchIO],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan(n=10)
    assert ctx.BatchController.state == 0
    assert ctx.globals.BatchIO.fill_valve == False
    assert ctx.globals.BatchIO.mixer_on == False
    assert ctx.globals.BatchIO.drain_valve == False
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


class TestArraysInProject:
    """Array variables in GVLs and programs."""

    def test_array_in_program(self):
        """Program with array static var working in project simulation."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class ArrayProcessor:
    values: Static[ARRAY(DINT, 5)]
    sum_output: Output[DINT]
    write_idx: Input[DINT]
    write_val: Input[DINT]
    cmd_write: Input[BOOL]

    def logic(self):
        if self.cmd_write:
            self.values[self.write_idx] = self.write_val

        total = 0
        for i in range(5):
            total = total + self.values[i]
        self.sum_output = total
""",
            "test_arrays.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_array_write_and_sum():
    proj_ir = project("ArrayTest", pous=[ArrayProcessor]).compile()
    ctx = simulate_project(proj_ir)

    # Write values
    for i in range(5):
        ctx.ArrayProcessor.write_idx = i
        ctx.ArrayProcessor.write_val = (i + 1) * 10
        ctx.ArrayProcessor.cmd_write = True
        ctx.scan()

    # Sum should be 10+20+30+40+50 = 150
    assert ctx.ArrayProcessor.sum_output == 150
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


class TestContinuousAndPeriodicMixed:
    """Continuous task running alongside periodic tasks."""

    def test_continuous_with_periodic(self):
        """Continuous task fires every scan, periodic only at interval."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Background:
    count: Static[DINT]

    def logic(self):
        self.count = self.count + 1

@program
class Periodic50ms:
    count: Static[DINT]

    def logic(self):
        self.count = self.count + 1
""",
            "test_mixed_tasks.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_continuous_always_fires():
    proj_ir = project("MixedTest",
        pous=[Background, Periodic50ms],
        tasks=[
            task("Bg", continuous=True, pous=[Background]),
            task("Periodic", periodic=timedelta(milliseconds=50),
                 pous=[Periodic50ms]),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Base period = 50ms (only one periodic)
    # 200ms = 4 scans of 50ms each
    ctx.tick(ms=200)

    # Continuous fires every scan = 4
    assert ctx.Background.count == 4
    # Periodic fires every 50ms = 4
    assert ctx.Periodic50ms.count == 4
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


class TestEmptyAndMinimalPrograms:
    """Edge cases: empty logic, programs with only external vars, etc."""

    def test_empty_program_doesnt_crash(self):
        """Program with no logic should run without errors."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class EmptyProgram:
    def logic(self):
        pass
""",
            "test_empty.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_empty_runs():
    proj_ir = project("EmptyTest", pous=[EmptyProgram]).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan(n=10)
    assert ctx.clock_ms == 100
""",
        }
        _assert_pass(run_tests(files), expected_count=1)

    def test_external_only_program(self):
        """Program that only reads/writes external vars."""
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class IO:
    input_val: DINT = 0
    output_val: DINT = 0

@program
class Passthrough:
    input_val: External[DINT] = Field(description="IO")
    output_val: External[DINT] = Field(description="IO")

    def logic(self):
        self.output_val = self.input_val * 2
""",
            "test_external_only.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_passthrough():
    proj_ir = project("PassTest",
        pous=[Passthrough],
        global_var_lists=[IO],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.globals.IO.input_val = 21
    ctx.scan()
    assert ctx.globals.IO.output_val == 42
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


class TestFBInheritanceInProject:
    """FB inheritance used within a project simulation."""

    def test_derived_fb_in_program(self):
        """Program using a derived FB class."""
        files = {
            "base.py": """\
from plx.framework import *

@fb
class BaseMotor:
    cmd_run: Input[BOOL]
    speed: Output[REAL]
    base_speed: Input[REAL]

    def logic(self):
        if self.cmd_run:
            self.speed = self.base_speed
        else:
            self.speed = 0.0
""",
            "derived.py": """\
from plx.framework import *
from base import BaseMotor

@fb
class VFDMotor(BaseMotor):
    accel_rate: Input[REAL]
    current_speed: Static[REAL]

    def logic(self):
        super().logic()
        # Simple acceleration ramp
        if self.cmd_run:
            if self.current_speed < self.speed:
                self.current_speed = self.current_speed + self.accel_rate
                if self.current_speed > self.speed:
                    self.current_speed = self.speed
        else:
            self.current_speed = 0.0
""",
            "main.py": """\
from plx.framework import *
from derived import VFDMotor

@program
class MotorProgram:
    motor: VFDMotor
    cmd: Input[BOOL]
    actual_speed: Output[REAL]

    def logic(self):
        self.motor(cmd_run=self.cmd, base_speed=1800.0, accel_rate=100.0)
        self.actual_speed = self.motor.current_speed
""",
            "test_inheritance.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_vfd_ramp_up():
    proj_ir = project("InheritTest",
        pous=[MotorProgram],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.MotorProgram.cmd = True
    ctx.scan()
    assert ctx.MotorProgram.actual_speed == 100.0  # first ramp step
    ctx.scan()
    assert ctx.MotorProgram.actual_speed == 200.0  # second step

    # After enough scans, should reach target
    ctx.scan(n=20)
    assert ctx.MotorProgram.actual_speed == 1800.0  # capped at base_speed

def test_vfd_stops():
    proj_ir = project("InheritTest2",
        pous=[MotorProgram],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.MotorProgram.cmd = True
    ctx.scan(n=5)
    assert ctx.MotorProgram.actual_speed == 500.0

    ctx.MotorProgram.cmd = False
    ctx.scan()
    assert ctx.MotorProgram.actual_speed == 0.0

def test_base_fb_unit():
    ctx = simulate(BaseMotor)
    ctx.cmd_run = True
    ctx.base_speed = 3600.0
    ctx.scan()
    assert ctx.speed == 3600.0

def test_derived_fb_unit():
    ctx = simulate(VFDMotor, pous=[BaseMotor])
    ctx.cmd_run = True
    ctx.base_speed = 1000.0
    ctx.accel_rate = 250.0
    ctx.scan()
    assert ctx.current_speed == 250.0
    ctx.scan()
    assert ctx.current_speed == 500.0
""",
        }
        _assert_pass(run_tests(files), expected_count=4)


class TestMultipleTestFiles:
    """Project with multiple test files — all should run."""

    def test_two_test_files(self):
        """Two separate test files both execute and pass."""
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class Counters:
    a: DINT = 0
    b: DINT = 0

@program
class ProgA:
    a: External[DINT] = Field(description="Counters")
    def logic(self):
        self.a = self.a + 1

@program
class ProgB:
    b: External[DINT] = Field(description="Counters")
    def logic(self):
        self.b = self.b + 10
""",
            "test_prog_a.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_prog_a_increments():
    proj_ir = project("TestA",
        pous=[ProgA, ProgB],
        global_var_lists=[Counters],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan(n=5)
    assert ctx.globals.Counters.a == 5
""",
            "test_prog_b.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_prog_b_increments_by_ten():
    proj_ir = project("TestB",
        pous=[ProgA, ProgB],
        global_var_lists=[Counters],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan(n=3)
    assert ctx.globals.Counters.b == 30
""",
        }
        result = run_tests(files)
        _assert_pass(result, expected_count=2)
        # Verify both test files were found
        test_files = {r.file for r in result.results}
        assert "test_prog_a.py" in test_files
        assert "test_prog_b.py" in test_files


class TestMethodsInProject:
    """FB methods invoked within project simulation."""

    def test_fb_with_method_unit(self):
        """FB methods work in single-POU simulation (unit test pattern)."""
        files = {
            "accumulator.py": """\
from plx.framework import *

@fb
class Accumulator:
    amount: Input[REAL]
    value: Static[REAL]
    total: Output[REAL]

    @fb_method
    def add(self, delta: REAL):
        self.value = self.value + delta

    def logic(self):
        self.add(delta=self.amount)
        self.total = self.value
""",
            "main.py": """\
from plx.framework import *
from accumulator import Accumulator

@program
class AccumProgram:
    acc: Accumulator
    input_val: Input[REAL]

    def logic(self):
        self.acc(amount=self.input_val)
""",
            "test_methods.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_accumulator_via_project():
    proj_ir = project("MethodTest", pous=[AccumProgram]).compile()
    ctx = simulate_project(proj_ir)

    ctx.AccumProgram.input_val = 10.0
    ctx.scan()
    assert ctx.AccumProgram.acc.total == 10.0

    ctx.scan()
    assert ctx.AccumProgram.acc.total == 20.0

    ctx.AccumProgram.input_val = 5.0
    ctx.scan()
    assert ctx.AccumProgram.acc.total == 25.0

def test_accumulator_unit():
    ctx = simulate(Accumulator)
    ctx.amount = 7.5
    ctx.scan()
    assert ctx.total == 7.5
    ctx.scan()
    assert ctx.total == 15.0
""",
        }
        _assert_pass(run_tests(files), expected_count=2)

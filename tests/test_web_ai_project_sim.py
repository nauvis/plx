"""Integration tests: simulate what the web IDE AI agent would generate.

These tests replicate the AI workflow:
1. AI writes code files (POUs, GVLs, tasks)
2. AI writes test_*.py files using simulate_project()
3. Test runner executes them in sandboxed environment

Each test function builds a files dict (code + test files) and runs them
through the test runner, verifying that the AI-generated tests pass.
"""

from __future__ import annotations

import pytest

from web.backend.test_runner import run_tests


class TestAIGeneratesProjectTests:
    """Test that AI-style project-level test files work through the test runner."""

    def test_motor_control_with_tasks(self):
        """AI writes a motor control project with fast/slow tasks and tests."""
        files = {
            "motor.py": """\
from plx.framework import *

@fb
class MotorCtrl:
    cmd_start: Input[BOOL]
    cmd_stop: Input[BOOL]
    running: Output[BOOL]
    speed: Output[REAL]
    cfg_speed: Input[REAL]

    def logic(self):
        if self.cmd_start and not self.cmd_stop:
            self.running = True
            self.speed = self.cfg_speed
        if self.cmd_stop:
            self.running = False
            self.speed = 0.0
""",
            "io.py": """\
from plx.framework import *

@global_vars
class IO:
    start_button: BOOL = False
    stop_button: BOOL = False
    speed_setpoint: REAL = 0.0
    motor_running: BOOL = False
    motor_speed: REAL = 0.0
""",
            "main.py": """\
from plx.framework import *
from motor import MotorCtrl

@program
class FastLoop:
    motor: MotorCtrl
    start_button: External[BOOL] = Field(description="IO")
    stop_button: External[BOOL] = Field(description="IO")
    speed_setpoint: External[REAL] = Field(description="IO")
    motor_running: External[BOOL] = Field(description="IO")
    motor_speed: External[REAL] = Field(description="IO")

    def logic(self):
        self.motor(
            cmd_start=self.start_button,
            cmd_stop=self.stop_button,
            cfg_speed=self.speed_setpoint,
        )
        self.motor_running = self.motor.running
        self.motor_speed = self.motor.speed
""",
            "test_motor.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_motor_starts():
    proj_ir = project("MotorTest",
        pous=[FastLoop],
        global_var_lists=[IO],
        tasks=[
            task("FastTask", periodic=timedelta(milliseconds=10), pous=[FastLoop]),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.globals.IO.start_button = True
    ctx.globals.IO.speed_setpoint = 1750.0
    ctx.scan()
    assert ctx.globals.IO.motor_running == True
    assert ctx.globals.IO.motor_speed == 1750.0

def test_motor_stops():
    proj_ir = project("MotorTest",
        pous=[FastLoop],
        global_var_lists=[IO],
        tasks=[
            task("FastTask", periodic=timedelta(milliseconds=10), pous=[FastLoop]),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Start motor
    ctx.globals.IO.start_button = True
    ctx.globals.IO.speed_setpoint = 1750.0
    ctx.scan()
    assert ctx.globals.IO.motor_running == True

    # Stop motor
    ctx.globals.IO.stop_button = True
    ctx.scan()
    assert ctx.globals.IO.motor_running == False
    assert ctx.globals.IO.motor_speed == 0.0

def test_motor_single_pou():
    \"\"\"Also verify single-POU simulate still works alongside project tests.\"\"\"
    ctx = simulate(MotorCtrl)
    ctx.cmd_start = True
    ctx.cfg_speed = 1800.0
    ctx.scan()
    assert ctx.running == True
    assert ctx.speed == 1800.0
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)
        assert len(result.results) == 3
        assert all(r.passed for r in result.results)

    def test_multi_rate_tasks(self):
        """AI writes a project with fast and slow periodic tasks."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class FastLoop:
    count: Static[DINT]

    def logic(self):
        self.count = self.count + 1

@program
class SlowLoop:
    count: Static[DINT]

    def logic(self):
        self.count = self.count + 1
""",
            "test_rates.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_fast_runs_more_often():
    proj_ir = project("RateTest",
        pous=[FastLoop, SlowLoop],
        tasks=[
            task("Fast", periodic=timedelta(milliseconds=10), pous=[FastLoop], priority=1),
            task("Slow", periodic=timedelta(milliseconds=50), pous=[SlowLoop], priority=2),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.tick(ms=100)
    # Fast fires at 0, 10, 20, ..., 90 = 10 times
    assert ctx.FastLoop.count == 10
    # Slow fires at 0, 50 = 2 times
    assert ctx.SlowLoop.count == 2
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_startup_and_periodic(self):
        """AI writes a project with startup task and periodic task."""
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class SystemState:
    initialized: BOOL = False
    run_count: DINT = 0

@program
class InitProgram:
    initialized: External[BOOL] = Field(description="SystemState")

    def logic(self):
        self.initialized = True

@program
class MainProgram:
    initialized: External[BOOL] = Field(description="SystemState")
    run_count: External[DINT] = Field(description="SystemState")

    def logic(self):
        if self.initialized:
            self.run_count = self.run_count + 1
""",
            "test_startup.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_init_runs_once_then_main_uses_flag():
    proj_ir = project("StartupTest",
        pous=[InitProgram, MainProgram],
        global_var_lists=[SystemState],
        tasks=[
            task("Init", startup=True, pous=[InitProgram], priority=0),
            task("Main", periodic=timedelta(milliseconds=10), pous=[MainProgram], priority=1),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    # First scan: startup fires (init sets flag), periodic fires (main checks flag)
    ctx.scan()
    assert ctx.globals.SystemState.initialized == True
    assert ctx.globals.SystemState.run_count == 1

    # Subsequent scans: only periodic fires (startup already fired)
    ctx.scan(n=4)
    assert ctx.globals.SystemState.run_count == 5
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_gvl_communication_between_programs(self):
        """AI writes programs that communicate through shared GVL."""
        files = {
            "shared.py": """\
from plx.framework import *

@global_vars
class Handshake:
    request: BOOL = False
    acknowledge: BOOL = False
    data_value: DINT = 0
""",
            "sender.py": """\
from plx.framework import *

@program
class Sender:
    request: External[BOOL] = Field(description="Handshake")
    data_value: External[DINT] = Field(description="Handshake")
    cmd_send: Input[BOOL]
    payload: Input[DINT]

    def logic(self):
        if self.cmd_send:
            self.request = True
            self.data_value = self.payload
""",
            "receiver.py": """\
from plx.framework import *

@program
class Receiver:
    request: External[BOOL] = Field(description="Handshake")
    acknowledge: External[BOOL] = Field(description="Handshake")
    data_value: External[DINT] = Field(description="Handshake")
    received_data: Output[DINT]

    def logic(self):
        if self.request:
            self.received_data = self.data_value
            self.acknowledge = True
""",
            "test_handshake.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_sender_receiver_handshake():
    proj_ir = project("HandshakeTest",
        pous=[Sender, Receiver],
        global_var_lists=[Handshake],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Initially nothing happening
    ctx.scan()
    assert ctx.globals.Handshake.request == False
    assert ctx.Receiver.received_data == 0

    # Sender sends data
    ctx.Sender.cmd_send = True
    ctx.Sender.payload = 42
    ctx.scan()

    # After scan: Sender set request+data, Receiver picks it up
    assert ctx.globals.Handshake.request == True
    assert ctx.globals.Handshake.data_value == 42
    assert ctx.Receiver.received_data == 42
    assert ctx.globals.Handshake.acknowledge == True
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_event_task(self):
        """AI writes a project with event-triggered task."""
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class Signals:
    alarm_trigger: BOOL = False

@program
class AlarmHandler:
    alarm_count: Static[DINT]

    def logic(self):
        self.alarm_count = self.alarm_count + 1
""",
            "test_events.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_event_fires_on_change():
    proj_ir = project("EventTest",
        pous=[AlarmHandler],
        global_var_lists=[Signals],
        tasks=[
            task("OnAlarm", event="Signals.alarm_trigger", pous=[AlarmHandler]),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    # No trigger change, handler doesn't run
    ctx.scan(n=3)
    assert ctx.AlarmHandler.alarm_count == 0

    # Trigger alarm
    ctx.globals.Signals.alarm_trigger = True
    ctx.scan()
    assert ctx.AlarmHandler.alarm_count == 1

    # No further changes, no more fires
    ctx.scan(n=3)
    assert ctx.AlarmHandler.alarm_count == 1

    # Clear and re-trigger
    ctx.globals.Signals.alarm_trigger = False
    ctx.scan()
    assert ctx.AlarmHandler.alarm_count == 2
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_tick_with_trace_capture(self):
        """AI writes a test capturing waveform data from project simulation."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Ramp:
    output: Output[DINT]
    counter: Static[DINT]

    def logic(self):
        self.counter = self.counter + 1
        self.output = self.counter
""",
            "test_trace.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_ramp_waveform():
    proj_ir = project("TraceTest", pous=[Ramp]).compile()
    ctx = simulate_project(proj_ir)
    trace = ctx.tick(ms=50, trace=True)

    # 50ms / 10ms = 5 scans
    assert len(trace) == 5
    ramp_values = trace.values_of("Ramp.output")
    assert ramp_values == [1, 2, 3, 4, 5]
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_scan_until_across_programs(self):
        """AI writes a test using scan_until on project context."""
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Counter:
    count: Static[DINT]

    def logic(self):
        self.count = self.count + 1
""",
            "test_until.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_wait_for_counter():
    proj_ir = project("UntilTest", pous=[Counter]).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan_until(lambda c: c.Counter.count >= 10, timeout_seconds=1)
    assert ctx.Counter.count >= 10
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_priority_ordering(self):
        """AI writes a test verifying task priority affects execution order."""
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class State:
    value: DINT = 0

@program
class Writer:
    value: External[DINT] = Field(description="State")

    def logic(self):
        self.value = 42

@program
class Reader:
    value: External[DINT] = Field(description="State")
    captured: Output[DINT]

    def logic(self):
        self.captured = self.value
""",
            "test_priority.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_writer_before_reader():
    proj_ir = project("PriorityTest",
        pous=[Writer, Reader],
        global_var_lists=[State],
        tasks=[
            task("WriterTask", periodic=timedelta(milliseconds=10),
                 pous=[Writer], priority=1),
            task("ReaderTask", periodic=timedelta(milliseconds=10),
                 pous=[Reader], priority=5),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)
    ctx.scan()
    # Writer (priority 1) runs before Reader (priority 5)
    # So Reader sees Writer's value on the same scan
    assert ctx.Reader.captured == 42
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)

    def test_mixed_unit_and_integration(self):
        """AI writes both unit tests (simulate) and integration tests (simulate_project)."""
        files = {
            "valve.py": """\
from plx.framework import *

@fb
class ValveCtrl:
    cmd_open: Input[BOOL]
    cmd_close: Input[BOOL]
    is_open: Output[BOOL]

    def logic(self):
        if self.cmd_open:
            self.is_open = True
        if self.cmd_close:
            self.is_open = False
""",
            "main.py": """\
from plx.framework import *
from valve import ValveCtrl

@global_vars
class IO:
    open_cmd: BOOL = False
    valve_status: BOOL = False

@program
class Controller:
    open_cmd: External[BOOL] = Field(description="IO")
    valve_status: External[BOOL] = Field(description="IO")
    valve: ValveCtrl

    def logic(self):
        self.valve(cmd_open=self.open_cmd, cmd_close=not self.open_cmd)
        self.valve_status = self.valve.is_open
""",
            "test_valve.py": """\
from plx.framework import *
from plx.simulate import simulate_project

# Unit test: test the FB in isolation
def test_valve_opens():
    ctx = simulate(ValveCtrl)
    ctx.cmd_open = True
    ctx.scan()
    assert ctx.is_open == True

def test_valve_closes():
    ctx = simulate(ValveCtrl)
    ctx.cmd_open = True
    ctx.scan()
    ctx.cmd_open = False
    ctx.cmd_close = True
    ctx.scan()
    assert ctx.is_open == False

# Integration test: test the whole project
def test_project_valve_control():
    proj_ir = project("ValveTest",
        pous=[Controller],
        global_var_lists=[IO],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Open valve via GVL
    ctx.globals.IO.open_cmd = True
    ctx.scan()
    assert ctx.globals.IO.valve_status == True

    # Close valve
    ctx.globals.IO.open_cmd = False
    ctx.scan()
    assert ctx.globals.IO.valve_status == False
""",
        }
        result = run_tests(files)
        assert result.success, _format_failures(result)
        # Should have 3 tests: 2 unit + 1 integration
        assert len(result.results) == 3


def _format_failures(result) -> str:
    """Format test runner failures for assertion messages."""
    lines = []
    for r in result.results:
        if not r.passed:
            lines.append(f"FAIL {r.file}::{r.name}: {r.error}")
            if r.traceback:
                lines.append(f"  {r.traceback}")
    if result.error:
        lines.append(f"Runner error: {result.error}")
    return "\n".join(lines)

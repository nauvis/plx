"""High-coverage AI agent tests: sentinel functions, @function POUs,
first_scan, FB properties, counters, latches, complex predicates.

Every pattern here has been verified working in single-POU simulation
but was NOT previously tested through the web IDE test runner pipeline.
"""

from __future__ import annotations

import pytest

from web.backend.test_runner import run_tests


def _assert_pass(result, *, expected_count=None):
    failures = [r for r in result.results if not r.passed]
    if failures or result.error:
        lines = []
        if result.error:
            lines.append(f"Runner error: {result.error}")
        for r in failures:
            lines.append(f"FAIL {r.file}::{r.name}: {r.error}")
            if r.traceback:
                for ln in r.traceback.split("\n")[:12]:
                    lines.append(f"  {ln}")
        pytest.fail("\n".join(lines))
    if expected_count is not None:
        assert len(result.results) == expected_count, (
            f"Expected {expected_count} tests, got {len(result.results)}: "
            f"{[r.name for r in result.results]}"
        )


# -----------------------------------------------------------------------
# Sentinel: pulse (TP)
# -----------------------------------------------------------------------

class TestPulseSentinel:

    def test_pulse_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class PulseDetector:
    trigger: Input[BOOL]
    pulse_out: Output[BOOL]

    def logic(self):
        self.pulse_out = pulse(self.trigger, timedelta(milliseconds=100))
""",
            "test_pulse.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_pulse_one_shot():
    proj_ir = project("PulseTest", pous=[PulseDetector]).compile()
    ctx = simulate_project(proj_ir)

    ctx.PulseDetector.trigger = True
    ctx.scan()
    assert ctx.PulseDetector.pulse_out == True

    # Pulse stays high for duration
    ctx.tick(ms=50)
    assert ctx.PulseDetector.pulse_out == True

    # Pulse ends after duration
    ctx.tick(ms=60)
    assert ctx.PulseDetector.pulse_out == False

def test_pulse_no_retrigger_during_active():
    proj_ir = project("PulseTest2", pous=[PulseDetector]).compile()
    ctx = simulate_project(proj_ir)

    ctx.PulseDetector.trigger = True
    ctx.scan()
    assert ctx.PulseDetector.pulse_out == True

    # Toggle trigger while pulse active — doesn't restart
    ctx.PulseDetector.trigger = False
    ctx.tick(ms=50)
    ctx.PulseDetector.trigger = True
    ctx.tick(ms=60)
    # Pulse should be done (original 100ms passed)
    assert ctx.PulseDetector.pulse_out == False
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


# -----------------------------------------------------------------------
# Sentinel: sustained (TOF)
# -----------------------------------------------------------------------

class TestSustainedSentinel:

    def test_sustained_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class FailSafeValve:
    cmd_open: Input[BOOL]
    valve_open: Output[BOOL]

    def logic(self):
        self.valve_open = sustained(self.cmd_open, timedelta(milliseconds=500))
""",
            "test_sustained.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_sustained_delays_off():
    proj_ir = project("SustTest", pous=[FailSafeValve]).compile()
    ctx = simulate_project(proj_ir)

    ctx.FailSafeValve.cmd_open = True
    ctx.scan()
    assert ctx.FailSafeValve.valve_open == True

    # Remove input — output stays high for 500ms
    ctx.FailSafeValve.cmd_open = False
    ctx.tick(ms=300)
    assert ctx.FailSafeValve.valve_open == True  # still within sustain

    ctx.tick(ms=300)  # 600ms total > 500ms
    assert ctx.FailSafeValve.valve_open == False
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# Sentinel: retentive (RTO)
# -----------------------------------------------------------------------

class TestRetentiveSentinel:

    def test_retentive_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class AccumTimer:
    run: Input[BOOL]
    done: Output[BOOL]

    def logic(self):
        self.done = retentive(self.run, timedelta(seconds=1))
""",
            "test_retentive.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_retentive_accumulates():
    proj_ir = project("RtoTest", pous=[AccumTimer]).compile()
    ctx = simulate_project(proj_ir)

    # Run for 600ms
    ctx.AccumTimer.run = True
    ctx.tick(ms=600)
    assert ctx.AccumTimer.done == False

    # Stop — accumulated time preserved
    ctx.AccumTimer.run = False
    ctx.scan()
    assert ctx.AccumTimer.done == False

    # Resume — continues from 600ms
    ctx.AccumTimer.run = True
    ctx.tick(ms=500)  # 600 + 500 = 1100ms > 1000ms
    assert ctx.AccumTimer.done == True
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# Sentinel: count_up / count_down / count_up_down (CTU/CTD/CTUD)
# -----------------------------------------------------------------------

class TestCounterSentinels:
    """Counter sentinels return BOOL (Q output: done flag), not the count value."""

    def test_count_up_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class PartCounter:
    part_detect: Input[BOOL]
    batch_done: Output[BOOL]

    def logic(self):
        # count_up returns Q: True when count reaches preset
        self.batch_done = count_up(self.part_detect, preset=3)
""",
            "test_ctu.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_count_up_reaches_preset():
    proj_ir = project("CtuTest", pous=[PartCounter]).compile()
    ctx = simulate_project(proj_ir)

    # Pulse 2 times — not at preset yet
    for _ in range(2):
        ctx.PartCounter.part_detect = True
        ctx.scan()
        ctx.PartCounter.part_detect = False
        ctx.scan()

    assert ctx.PartCounter.batch_done == False

    # Third pulse reaches preset=3
    ctx.PartCounter.part_detect = True
    ctx.scan()
    ctx.PartCounter.part_detect = False
    ctx.scan()
    assert ctx.PartCounter.batch_done == True
""",
        }
        _assert_pass(run_tests(files), expected_count=1)

    def test_count_down_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Countdown:
    tick_pulse: Input[BOOL]
    done: Output[BOOL]

    def logic(self):
        # count_down returns Q: True when CV <= 0
        self.done = count_down(self.tick_pulse, preset=2)
""",
            "test_ctd.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_count_down_reaches_zero():
    proj_ir = project("CtdTest", pous=[Countdown]).compile()
    ctx = simulate_project(proj_ir)

    # First pulse: CV goes to -1, Q = True (CV <= 0)
    ctx.Countdown.tick_pulse = True
    ctx.scan()
    assert ctx.Countdown.done == True
""",
        }
        _assert_pass(run_tests(files), expected_count=1)

    def test_count_up_down_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class BiCounter:
    up_pulse: Input[BOOL]
    down_pulse: Input[BOOL]
    at_max: Output[BOOL]

    def logic(self):
        # count_up_down returns Q (QU): True when CV >= preset
        self.at_max = count_up_down(self.up_pulse, self.down_pulse, preset=3)
""",
            "test_ctud.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_count_up_down_reaches_preset():
    proj_ir = project("CtudTest", pous=[BiCounter]).compile()
    ctx = simulate_project(proj_ir)

    # Count up 3 times to reach preset
    for _ in range(3):
        ctx.BiCounter.up_pulse = True
        ctx.scan()
        ctx.BiCounter.up_pulse = False
        ctx.scan()

    assert ctx.BiCounter.at_max == True

    # Count down once — below preset
    ctx.BiCounter.down_pulse = True
    ctx.scan()
    ctx.BiCounter.down_pulse = False
    ctx.scan()
    assert ctx.BiCounter.at_max == False
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# Sentinel: set_dominant / reset_dominant (SR/RS)
# -----------------------------------------------------------------------

class TestLatchSentinels:

    def test_set_dominant_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class SRLatch:
    set_cmd: Input[BOOL]
    reset_cmd: Input[BOOL]
    latched: Output[BOOL]

    def logic(self):
        self.latched = set_dominant(self.set_cmd, self.reset_cmd)
""",
            "test_sr.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_sr_basic():
    proj_ir = project("SRTest", pous=[SRLatch]).compile()
    ctx = simulate_project(proj_ir)

    # Set
    ctx.SRLatch.set_cmd = True
    ctx.scan()
    assert ctx.SRLatch.latched == True

    # Release set — stays latched
    ctx.SRLatch.set_cmd = False
    ctx.scan()
    assert ctx.SRLatch.latched == True

    # Reset
    ctx.SRLatch.reset_cmd = True
    ctx.scan()
    assert ctx.SRLatch.latched == False

def test_sr_set_wins_when_both():
    proj_ir = project("SRTest2", pous=[SRLatch]).compile()
    ctx = simulate_project(proj_ir)

    # Both high: set dominates
    ctx.SRLatch.set_cmd = True
    ctx.SRLatch.reset_cmd = True
    ctx.scan()
    assert ctx.SRLatch.latched == True
""",
        }
        _assert_pass(run_tests(files), expected_count=2)

    def test_reset_dominant_in_project(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class RSLatch:
    set_cmd: Input[BOOL]
    reset_cmd: Input[BOOL]
    latched: Output[BOOL]

    def logic(self):
        self.latched = reset_dominant(self.set_cmd, self.reset_cmd)
""",
            "test_rs.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_rs_reset_wins_when_both():
    proj_ir = project("RSTest", pous=[RSLatch]).compile()
    ctx = simulate_project(proj_ir)

    # Both high: reset dominates
    ctx.RSLatch.set_cmd = True
    ctx.RSLatch.reset_cmd = True
    ctx.scan()
    assert ctx.RSLatch.latched == False

def test_rs_normal_operation():
    proj_ir = project("RSTest2", pous=[RSLatch]).compile()
    ctx = simulate_project(proj_ir)

    ctx.RSLatch.set_cmd = True
    ctx.scan()
    assert ctx.RSLatch.latched == True

    ctx.RSLatch.set_cmd = False
    ctx.scan()
    assert ctx.RSLatch.latched == True  # retained

    ctx.RSLatch.reset_cmd = True
    ctx.scan()
    assert ctx.RSLatch.latched == False
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


# -----------------------------------------------------------------------
# first_scan() across programs in project
# -----------------------------------------------------------------------

class TestFirstScanInProject:

    def test_first_scan_per_program(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Initializer:
    init_done: Output[BOOL]
    init_count: Static[DINT]

    def logic(self):
        if first_scan():
            self.init_count = self.init_count + 1
            self.init_done = True

@program
class Worker:
    work_done: Output[BOOL]
    scan_count: Static[DINT]

    def logic(self):
        self.scan_count = self.scan_count + 1
        if first_scan():
            self.work_done = False
        elif self.scan_count > 3:
            self.work_done = True
""",
            "test_first_scan.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_first_scan_fires_once():
    proj_ir = project("FSTest",
        pous=[Initializer, Worker],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.scan()
    assert ctx.Initializer.init_done == True
    assert ctx.Initializer.init_count == 1

    ctx.scan(n=10)
    assert ctx.Initializer.init_count == 1  # still 1

def test_first_scan_in_worker():
    proj_ir = project("FSTest2",
        pous=[Initializer, Worker],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.scan()
    assert ctx.Worker.work_done == False  # first scan sets to False

    ctx.scan(n=3)
    assert ctx.Worker.work_done == True  # scan_count > 3

def test_first_scan_with_tasks():
    proj_ir = project("FSTest3",
        pous=[Initializer],
        tasks=[
            task("InitTask", periodic=timedelta(milliseconds=10),
                 pous=[Initializer]),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.scan(n=5)
    assert ctx.Initializer.init_count == 1
    assert ctx.Initializer.init_done == True
""",
        }
        _assert_pass(run_tests(files), expected_count=3)


# -----------------------------------------------------------------------
# @function POUs in project simulation
# -----------------------------------------------------------------------

class TestFunctionPOUsInProject:
    """@function is a CLASS decorator (like @fb), not a def decorator."""

    def test_function_called_from_program(self):
        files = {
            "main.py": """\
from plx.framework import *

@function
class ScaleValue:
    raw: Input[REAL]
    in_min: Input[REAL]
    in_max: Input[REAL]
    out_min: Input[REAL]
    out_max: Input[REAL]

    def logic(self) -> REAL:
        if self.in_max == self.in_min:
            return self.out_min
        ratio: REAL = (self.raw - self.in_min) / (self.in_max - self.in_min)
        return self.out_min + ratio * (self.out_max - self.out_min)

@function
class ClampValue:
    val: Input[REAL]
    lo: Input[REAL]
    hi: Input[REAL]

    def logic(self) -> REAL:
        if self.val < self.lo:
            return self.lo
        if self.val > self.hi:
            return self.hi
        return self.val

@program
class Scaler:
    raw_input: Input[REAL]
    scaled_output: Output[REAL]

    def logic(self):
        scaled: REAL = ScaleValue(self.raw_input, 0.0, 100.0, 4.0, 20.0)
        self.scaled_output = ClampValue(scaled, 4.0, 20.0)
""",
            "test_functions.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_scale_and_clamp():
    proj_ir = project("FuncTest", pous=[Scaler, ScaleValue, ClampValue]).compile()
    ctx = simulate_project(proj_ir)

    # Midpoint: 50 -> 12.0
    ctx.Scaler.raw_input = 50.0
    ctx.scan()
    assert ctx.Scaler.scaled_output == 12.0

    # Over range: 120 -> scaled 23.2 -> clamped 20.0
    ctx.Scaler.raw_input = 120.0
    ctx.scan()
    assert ctx.Scaler.scaled_output == 20.0

    # Under range: -10 -> scaled 2.4 -> clamped 4.0
    ctx.Scaler.raw_input = -10.0
    ctx.scan()
    assert ctx.Scaler.scaled_output == 4.0

    # Zero: 0 -> 4.0
    ctx.Scaler.raw_input = 0.0
    ctx.scan()
    assert ctx.Scaler.scaled_output == 4.0

    # Full: 100 -> 20.0
    ctx.Scaler.raw_input = 100.0
    ctx.scan()
    assert ctx.Scaler.scaled_output == 20.0
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# FB properties (getter/setter) in project
# -----------------------------------------------------------------------

class TestFBPropertiesInProject:

    def test_property_getter_setter(self):
        files = {
            "controlled_motor.py": """\
from plx.framework import *

@fb
class ControlledMotor:
    _speed: Static[REAL]
    _enabled: Static[BOOL]

    @fb_property(REAL)
    def speed(self):
        return self._speed

    @speed.setter
    def speed(self, value: REAL):
        if self._enabled:
            self._speed = value

    @fb_property(BOOL)
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value: BOOL):
        self._enabled = value
        if not value:
            self._speed = 0.0

    def logic(self):
        pass
""",
            "main.py": """\
from plx.framework import *
from controlled_motor import ControlledMotor

@program
class MotorProg:
    motor: ControlledMotor
    cmd_enable: Input[BOOL]
    cmd_speed: Input[REAL]
    actual_speed: Output[REAL]

    def logic(self):
        self.motor.enabled = self.cmd_enable
        self.motor.speed = self.cmd_speed
        self.motor()
        self.actual_speed = self.motor.speed
""",
            "test_properties.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_property_in_project():
    proj_ir = project("PropTest", pous=[MotorProg]).compile()
    ctx = simulate_project(proj_ir)

    # Enable and set speed
    ctx.MotorProg.cmd_enable = True
    ctx.MotorProg.cmd_speed = 1500.0
    ctx.scan()
    assert ctx.MotorProg.actual_speed == 1500.0

    # Disable — speed zeroed by setter
    ctx.MotorProg.cmd_enable = False
    ctx.scan()
    assert ctx.MotorProg.actual_speed == 0.0

def test_property_unit():
    ctx = simulate(ControlledMotor)
    ctx.enabled = True
    ctx.scan()
    ctx.speed = 3000.0
    ctx.scan()
    assert ctx.speed == 3000.0
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


# -----------------------------------------------------------------------
# Complex multi-program with all sentinels combined
# -----------------------------------------------------------------------

class TestAllSentinelsCombined:

    def test_realistic_machine_control(self):
        """Motor + counter + latch all in one project."""
        files = {
            "machine.py": """\
from plx.framework import *

@global_vars
class MachineIO:
    start_button: BOOL = False
    stop_button: BOOL = False
    part_sensor: BOOL = False
    motor_running: BOOL = False
    batch_done: BOOL = False

@program
class MotorControl:
    start_button: External[BOOL] = Field(description="MachineIO")
    stop_button: External[BOOL] = Field(description="MachineIO")
    motor_running: External[BOOL] = Field(description="MachineIO")

    def logic(self):
        self.motor_running = set_dominant(self.start_button, self.stop_button)

@program
class PartCounting:
    part_sensor: External[BOOL] = Field(description="MachineIO")
    motor_running: External[BOOL] = Field(description="MachineIO")
    batch_done: External[BOOL] = Field(description="MachineIO")

    def logic(self):
        if self.motor_running:
            # count_up returns Q: True when 5 parts counted
            self.batch_done = count_up(self.part_sensor, preset=5)
""",
            "test_machine.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_full_machine_cycle():
    proj_ir = project("MachineTest",
        pous=[MotorControl, PartCounting],
        global_var_lists=[MachineIO],
        tasks=[
            task("Control", periodic=timedelta(milliseconds=10),
                 pous=[MotorControl], priority=1),
            task("Count", periodic=timedelta(milliseconds=10),
                 pous=[PartCounting], priority=2),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Start motor
    ctx.globals.MachineIO.start_button = True
    ctx.scan()
    ctx.globals.MachineIO.start_button = False
    assert ctx.globals.MachineIO.motor_running == True

    # Count 4 parts — not done yet
    for _ in range(4):
        ctx.globals.MachineIO.part_sensor = True
        ctx.scan()
        ctx.globals.MachineIO.part_sensor = False
        ctx.scan()

    assert ctx.globals.MachineIO.batch_done == False

    # 5th part — batch done
    ctx.globals.MachineIO.part_sensor = True
    ctx.scan()
    ctx.globals.MachineIO.part_sensor = False
    ctx.scan()
    assert ctx.globals.MachineIO.batch_done == True

    # Stop motor
    ctx.globals.MachineIO.stop_button = True
    ctx.scan()
    ctx.globals.MachineIO.stop_button = False
    assert ctx.globals.MachineIO.motor_running == False
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# Complex scan_until predicates
# -----------------------------------------------------------------------

class TestComplexPredicates:

    def test_multi_condition_scan_until(self):
        files = {
            "programs.py": """\
from plx.framework import *

@global_vars
class State:
    ready: BOOL = False
    count: DINT = 0

@program
class Setup:
    ready: External[BOOL] = Field(description="State")

    def logic(self):
        self.ready = True

@program
class Worker:
    count: External[DINT] = Field(description="State")
    ready: External[BOOL] = Field(description="State")

    def logic(self):
        if self.ready:
            self.count = self.count + 1
""",
            "test_predicate.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_compound_predicate():
    proj_ir = project("PredTest",
        pous=[Setup, Worker],
        global_var_lists=[State],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.scan_until(
        lambda c: c.globals.State.ready and c.globals.State.count >= 10,
        timeout_seconds=1,
    )
    assert ctx.globals.State.ready == True
    assert ctx.globals.State.count >= 10

def test_scans_trigger_with_repeat():
    proj_ir = project("RepeatTest",
        pous=[Setup, Worker],
        global_var_lists=[State],
    ).compile()
    ctx = simulate_project(proj_ir)

    trace = ctx.scans().repeat(20).run()
    assert ctx.globals.State.count >= 19  # ready on scan 1, count from scan 2
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


# -----------------------------------------------------------------------
# Trace capture across multiple POUs with verification
# -----------------------------------------------------------------------

class TestDetailedTrace:

    def test_trace_captures_all_programs(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Ramp:
    value: Output[DINT]
    counter: Static[DINT]

    def logic(self):
        self.counter = self.counter + 1
        self.value = self.counter * 10

@program
class Doubler:
    input_val: Input[DINT]
    output_val: Output[DINT]

    def logic(self):
        self.output_val = self.input_val * 2
""",
            "test_trace.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_trace_multi_program():
    proj_ir = project("TraceTest",
        pous=[Ramp, Doubler],
        tasks=[
            task("T1", periodic=timedelta(milliseconds=10),
                 pous=[Ramp], priority=1),
            task("T2", periodic=timedelta(milliseconds=10),
                 pous=[Doubler], priority=2),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)
    trace = ctx.tick(ms=50, trace=True)

    assert len(trace) == 5
    ramp_vals = trace.values_of("Ramp.value")
    assert ramp_vals == [10, 20, 30, 40, 50]

def test_trace_to_dict():
    proj_ir = project("DictTest", pous=[Ramp]).compile()
    ctx = simulate_project(proj_ir)
    trace = ctx.tick(ms=30, trace=True)

    data = trace.to_dict()
    assert "__clock_ms" in data
    assert len(data["__clock_ms"]) == 3
    assert "Ramp.value" in data
    assert data["Ramp.value"] == [10, 20, 30]
""",
        }
        _assert_pass(run_tests(files), expected_count=2)


# -----------------------------------------------------------------------
# Multiple GVLs with programs reading from different ones
# -----------------------------------------------------------------------

class TestMultipleGVLs:

    def test_three_gvls_three_programs(self):
        files = {
            "gvls.py": """\
from plx.framework import *

@global_vars
class Sensors:
    temp: REAL = 20.0
    pressure: REAL = 1.0

@global_vars
class Setpoints:
    temp_sp: REAL = 50.0
    pressure_sp: REAL = 2.5

@global_vars
class Outputs:
    heat_on: BOOL = False
    pump_on: BOOL = False
""",
            "programs.py": """\
from plx.framework import *

@program
class TempControl:
    temp: External[REAL] = Field(description="Sensors")
    temp_sp: External[REAL] = Field(description="Setpoints")
    heat_on: External[BOOL] = Field(description="Outputs")

    def logic(self):
        self.heat_on = self.temp < self.temp_sp

@program
class PressureControl:
    pressure: External[REAL] = Field(description="Sensors")
    pressure_sp: External[REAL] = Field(description="Setpoints")
    pump_on: External[BOOL] = Field(description="Outputs")

    def logic(self):
        self.pump_on = self.pressure < self.pressure_sp
""",
            "test_multi_gvl.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_cross_gvl_logic():
    proj_ir = project("MultiGVL",
        pous=[TempControl, PressureControl],
        global_var_lists=[Sensors, Setpoints, Outputs],
    ).compile()
    ctx = simulate_project(proj_ir)

    # Initial: temp 20 < sp 50 → heat on, pressure 1.0 < sp 2.5 → pump on
    ctx.scan()
    assert ctx.globals.Outputs.heat_on == True
    assert ctx.globals.Outputs.pump_on == True

    # Raise temp above setpoint
    ctx.globals.Sensors.temp = 60.0
    ctx.scan()
    assert ctx.globals.Outputs.heat_on == False
    assert ctx.globals.Outputs.pump_on == True  # pressure still low

    # Change setpoints
    ctx.globals.Setpoints.temp_sp = 80.0
    ctx.globals.Setpoints.pressure_sp = 0.5
    ctx.scan()
    assert ctx.globals.Outputs.heat_on == True   # 60 < 80
    assert ctx.globals.Outputs.pump_on == False  # 1.0 > 0.5
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# While/for loops in project simulation
# -----------------------------------------------------------------------

class TestLoopsInProject:

    def test_for_loop_in_program(self):
        files = {
            "programs.py": """\
from plx.framework import *

@program
class Averager:
    values: Static[ARRAY(REAL, 4)]
    average: Output[REAL]
    idx: Input[DINT]
    new_val: Input[REAL]
    cmd_write: Input[BOOL]

    def logic(self):
        if self.cmd_write:
            self.values[self.idx] = self.new_val

        total = 0.0
        for i in range(4):
            total = total + self.values[i]
        self.average = total / 4.0
""",
            "test_loops.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_array_average():
    proj_ir = project("LoopTest", pous=[Averager]).compile()
    ctx = simulate_project(proj_ir)

    # Write values: [10, 20, 30, 40]
    for i, v in enumerate([10.0, 20.0, 30.0, 40.0]):
        ctx.Averager.idx = i
        ctx.Averager.new_val = v
        ctx.Averager.cmd_write = True
        ctx.scan()

    # Average = (10+20+30+40)/4 = 25.0
    assert ctx.Averager.average == 25.0
""",
        }
        _assert_pass(run_tests(files), expected_count=1)


# -----------------------------------------------------------------------
# Timer + GVL interaction: delayed start via shared state
# -----------------------------------------------------------------------

class TestTimerWithGVL:

    def test_delayed_start_via_gvl(self):
        """Timer in one program, status read by another."""
        files = {
            "gvls.py": """\
from plx.framework import *

@global_vars
class Control:
    start_cmd: BOOL = False
    system_ready: BOOL = False
""",
            "programs.py": """\
from plx.framework import *

@program
class Sequencer:
    start_cmd: External[BOOL] = Field(description="Control")
    system_ready: External[BOOL] = Field(description="Control")

    def logic(self):
        self.system_ready = delayed(self.start_cmd, timedelta(seconds=2))

@program
class Executor:
    system_ready: External[BOOL] = Field(description="Control")
    work_count: Static[DINT]

    def logic(self):
        if self.system_ready:
            self.work_count = self.work_count + 1
""",
            "test_timer_gvl.py": """\
from plx.framework import *
from plx.simulate import simulate_project

def test_delayed_ready_signal():
    proj_ir = project("TimerGVL",
        pous=[Sequencer, Executor],
        global_var_lists=[Control],
        tasks=[
            task("Seq", periodic=timedelta(milliseconds=10),
                 pous=[Sequencer], priority=1),
            task("Exec", periodic=timedelta(milliseconds=10),
                 pous=[Executor], priority=2),
        ],
    ).compile()
    ctx = simulate_project(proj_ir)

    ctx.globals.Control.start_cmd = True

    # Before delay expires — executor shouldn't work
    ctx.tick(seconds=1)
    assert ctx.Executor.work_count == 0

    # After delay expires — executor starts working
    ctx.tick(seconds=1.5)  # total 2.5s > 2s delay
    assert ctx.globals.Control.system_ready == True
    assert ctx.Executor.work_count > 0
""",
        }
        _assert_pass(run_tests(files), expected_count=1)

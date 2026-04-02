"""Automated Bottling Line — exercises @fb_method on FBs, pulse() sentinel,
falling() edge detection, match/case state machines, and multiple @struct types.

~50 I/O: 18 DI, 12 DO, 6 AI, 4 AO across filler, capper, reject, conveyors.
"""

from datetime import timedelta

import pytest

from plx.framework import (
    BOOL,
    DINT,
    INT,
    REAL,
    Input,
    Output,
    delayed,
    falling,
    fb,
    fb_method,
    program,
    project,
    pulse,
    rising,
    struct,
    task,
)
from plx.simulate import simulate

# ==========================================================================
# Data Types (3 structs)
# ==========================================================================


@struct
class StationStatus:
    running: BOOL = False
    faulted: BOOL = False
    jam: BOOL = False
    product_count: DINT = 0


@struct
class ProductionCounters:
    total: DINT = 0
    rejected: DINT = 0
    good: DINT = 0
    fill_rejects: DINT = 0
    cap_rejects: DINT = 0


@struct
class FillerConfig:
    target_fill: REAL = 95.0
    fill_tolerance: REAL = 2.0
    target_weight: REAL = 500.0
    weight_tolerance: REAL = 10.0


# ==========================================================================
# Function Blocks
# ==========================================================================


@fb
class ConveyorStation:
    """Generic conveyor with jam detection, product counting, and motor control.

    Demonstrates @fb_method for reset_count.
    """

    run_cmd: Input[BOOL]
    product_sensor: Input[BOOL]
    e_stop: Input[BOOL] = True
    reset_cmd: Input[BOOL]

    motor: Output[BOOL]
    jam_alarm: Output[BOOL]
    product_count: Output[DINT]

    def logic(self):
        # Jam detection: product stuck for 5 seconds
        self.jam_alarm = delayed(self.product_sensor, timedelta(seconds=5))

        # Motor control
        self.motor = self.run_cmd and self.e_stop and not self.jam_alarm

        # Count products on rising edge
        if rising(self.product_sensor):
            self.product_count = self.product_count + 1

        # Reset count on command
        if self.reset_cmd:
            self.product_count = 0

    @fb_method
    def reset_count(self):
        self.product_count = 0


@fb
class FillerStation:
    """Bottle filler with match/case state machine.

    States: 0=IDLE, 1=FILLING, 2=CHECKING, 3=COMPLETE, 4=REJECT.
    Verifies fill level and weight against tolerances.

    Demonstrates @fb_method for get_reject_reason.
    """

    start: Input[BOOL]
    fill_level: Input[REAL]
    weight: Input[REAL]
    target_fill: Input[REAL] = 95.0
    fill_tolerance: Input[REAL] = 2.0
    target_weight: Input[REAL] = 500.0
    weight_tolerance: Input[REAL] = 10.0

    fill_valve: Output[BOOL]
    complete: Output[BOOL]
    reject: Output[BOOL]
    reject_reason: Output[INT]  # 0=none, 1=underfill, 2=overfill, 3=weight
    state: Output[INT]

    fill_timer: DINT
    check_timer: DINT

    def logic(self):
        match self.state:
            case 0:
                # IDLE
                self.fill_valve = False
                self.complete = False
                self.reject = False
                self.reject_reason = 0
                self.fill_timer = 0
                self.check_timer = 0

                if self.start:
                    self.state = 1

            case 1:
                # FILLING
                self.fill_valve = True
                self.fill_timer = self.fill_timer + 1

                # Fill complete when level reaches target
                if self.fill_level >= self.target_fill:
                    self.fill_valve = False
                    self.state = 2

                # Timeout after 10 seconds (1000 scans) — reject
                if self.fill_timer >= 1000:
                    self.fill_valve = False
                    self.reject_reason = 1  # Underfill
                    self.state = 4

            case 2:
                # CHECKING — verify fill level and weight
                self.check_timer = self.check_timer + 1

                # Wait 1 scan for measurements to settle, then check
                if self.check_timer >= 1:
                    # Check fill level tolerance
                    fill_error: REAL = self.fill_level - self.target_fill
                    if fill_error < -self.fill_tolerance:
                        self.reject_reason = 1  # Underfill
                        self.state = 4
                    elif fill_error > self.fill_tolerance:
                        self.reject_reason = 2  # Overfill
                        self.state = 4
                    else:
                        # Check weight tolerance
                        weight_error: REAL = self.weight - self.target_weight
                        if weight_error > self.weight_tolerance:
                            self.reject_reason = 3  # Overweight
                            self.state = 4
                        elif weight_error < -self.weight_tolerance:
                            self.reject_reason = 3  # Underweight
                            self.state = 4
                        else:
                            self.state = 3  # All good

            case 3:
                # COMPLETE — bottle accepted
                self.complete = True

                # Return to idle when start drops
                if not self.start:
                    self.state = 0

            case 4:
                # REJECT
                self.reject = True

                # Return to idle when start drops
                if not self.start:
                    self.state = 0

    @fb_method
    def get_reject_reason(self) -> INT:
        return self.reject_reason


@fb
class CapperStation:
    """Bottle capper with match/case state machine.

    States: 0=IDLE, 1=CAPPING, 2=VERIFYING, 3=COMPLETE, 4=REJECT.
    Checks torque and cap presence.
    """

    start: Input[BOOL]
    cap_present: Input[BOOL]
    torque: Input[REAL]
    min_torque: Input[REAL] = 5.0
    max_torque: Input[REAL] = 15.0

    cap_actuator: Output[BOOL]
    complete: Output[BOOL]
    reject: Output[BOOL]
    reject_reason: Output[INT]  # 0=none, 1=no_cap, 2=torque
    state: Output[INT]

    cap_timer: DINT

    def logic(self):
        match self.state:
            case 0:
                # IDLE
                self.cap_actuator = False
                self.complete = False
                self.reject = False
                self.reject_reason = 0
                self.cap_timer = 0

                if self.start:
                    # Check cap presence before starting
                    if not self.cap_present:
                        self.reject_reason = 1  # No cap
                        self.state = 4
                    else:
                        self.state = 1

            case 1:
                # CAPPING
                self.cap_actuator = True
                self.cap_timer = self.cap_timer + 1

                # Capping takes 2 seconds (200 scans)
                if self.cap_timer >= 200:
                    self.cap_actuator = False
                    self.state = 2

            case 2:
                # VERIFYING torque
                if self.torque < self.min_torque:
                    self.reject_reason = 2  # Under-torque
                    self.state = 4
                elif self.torque > self.max_torque:
                    self.reject_reason = 2  # Over-torque
                    self.state = 4
                else:
                    self.state = 3

            case 3:
                # COMPLETE
                self.complete = True
                if not self.start:
                    self.state = 0

            case 4:
                # REJECT
                self.reject = True
                if not self.start:
                    self.state = 0


@fb
class RejectStation:
    """Reject diverter with pulse() activation and bin-full alarm."""

    trigger: Input[BOOL]  # Rising edge fires diverter
    bin_level: Input[REAL]
    bin_full_sp: Input[REAL] = 90.0

    diverter: Output[BOOL]
    reject_count: Output[DINT]
    bin_full: Output[BOOL]

    def logic(self):
        # Pulse diverter for 500ms on trigger
        self.diverter = pulse(self.trigger, timedelta(milliseconds=500))

        # Count rejects on falling edge of diverter (after pulse completes)
        if falling(self.diverter):
            self.reject_count = self.reject_count + 1

        # Bin full alarm
        self.bin_full = self.bin_level >= self.bin_full_sp


@fb
class StackLight:
    """Stack light controller: green/yellow/red from system states."""

    running: Input[BOOL]
    warning: Input[BOOL]
    faulted: Input[BOOL]

    green: Output[BOOL]
    yellow: Output[BOOL]
    red: Output[BOOL]

    def logic(self):
        # Priority: faulted > warning > running
        if self.faulted:
            self.green = False
            self.yellow = False
            self.red = True
        elif self.warning:
            self.green = False
            self.yellow = True
            self.red = False
        elif self.running:
            self.green = True
            self.yellow = False
            self.red = False
        else:
            self.green = False
            self.yellow = False
            self.red = False


# ==========================================================================
# Top-level program with match/case state machine
# ==========================================================================


@program
class BottlingLine:
    """Automated bottling line with top-level state machine.

    States: 0=STOPPED, 1=STARTING, 2=RUNNING, 3=STOPPING, 4=FAULTED, 5=ESTOPPED.
    """

    # Inputs (DI)
    start_cmd: Input[BOOL]
    stop_cmd: Input[BOOL]
    e_stop: Input[BOOL] = True  # NC: True=safe
    reset_cmd: Input[BOOL]
    filler_product_sensor: Input[BOOL]
    capper_product_sensor: Input[BOOL]
    outfeed_product_sensor: Input[BOOL]
    cap_present: Input[BOOL] = True

    # Inputs (AI)
    fill_level: Input[REAL]
    weight: Input[REAL]
    torque: Input[REAL] = 10.0
    reject_bin_level: Input[REAL]

    # Outputs (DO)
    infeed_motor: Output[BOOL]
    filler_motor: Output[BOOL]
    capper_motor: Output[BOOL]
    outfeed_motor: Output[BOOL]
    fill_valve: Output[BOOL]
    cap_actuator: Output[BOOL]
    reject_diverter: Output[BOOL]
    green_light: Output[BOOL]
    yellow_light: Output[BOOL]
    red_light: Output[BOOL]

    # Outputs (status)
    line_state: Output[INT]
    total_count: Output[DINT]
    good_count: Output[DINT]
    reject_count: Output[DINT]

    # Internal FBs
    infeed: ConveyorStation
    filler_conv: ConveyorStation
    capper_conv: ConveyorStation
    outfeed: ConveyorStation
    filler: FillerStation
    capper: CapperStation
    rejector: RejectStation
    stack: StackLight

    # Internals
    state: INT  # 0=STOPPED
    startup_timer: DINT
    any_fault: BOOL
    line_running: BOOL

    def logic(self):
        # E-stop override — highest priority
        if not self.e_stop:
            self.state = 5

        match self.state:
            case 0:
                # STOPPED
                self.line_running = False
                self.startup_timer = 0

                if self.start_cmd and self.e_stop:
                    self.state = 1

            case 1:
                # STARTING — ramp up conveyors
                self.line_running = False
                self.startup_timer = self.startup_timer + 1

                # Start conveyors in sequence (100 scans = 1 second each)
                if self.startup_timer >= 300:
                    self.line_running = True
                    self.state = 2

            case 2:
                # RUNNING
                self.line_running = True

                if self.stop_cmd:
                    self.state = 3

                # Fault detection
                if self.any_fault:
                    self.state = 4

            case 3:
                # STOPPING
                self.line_running = False
                self.state = 0

            case 4:
                # FAULTED
                self.line_running = False

                if self.reset_cmd:
                    self.any_fault = False
                    self.state = 0

            case 5:
                # E-STOPPED
                self.line_running = False

                # Recover when e-stop clears and reset pressed
                if self.e_stop and self.reset_cmd:
                    self.state = 0

        self.line_state = self.state

        # --- Conveyors ---
        self.infeed(
            run_cmd=self.line_running,
            product_sensor=self.filler_product_sensor,
            e_stop=self.e_stop,
        )
        self.infeed_motor = self.infeed.motor

        self.filler_conv(
            run_cmd=self.line_running,
            product_sensor=self.filler_product_sensor,
            e_stop=self.e_stop,
        )
        self.filler_motor = self.filler_conv.motor

        self.capper_conv(
            run_cmd=self.line_running,
            product_sensor=self.capper_product_sensor,
            e_stop=self.e_stop,
        )
        self.capper_motor = self.capper_conv.motor

        self.outfeed(
            run_cmd=self.line_running,
            product_sensor=self.outfeed_product_sensor,
            e_stop=self.e_stop,
        )
        self.outfeed_motor = self.outfeed.motor

        # --- Filler ---
        self.filler(
            start=self.line_running and self.filler_product_sensor,
            fill_level=self.fill_level,
            weight=self.weight,
        )
        self.fill_valve = self.filler.fill_valve

        # --- Capper ---
        self.capper(
            start=self.line_running and self.capper_product_sensor,
            cap_present=self.cap_present,
            torque=self.torque,
        )
        self.cap_actuator = self.capper.cap_actuator

        # --- Reject station ---
        reject_trigger: BOOL = self.filler.reject or self.capper.reject
        self.rejector(
            trigger=reject_trigger,
            bin_level=self.reject_bin_level,
        )
        self.reject_diverter = self.rejector.diverter

        # --- Production counters ---
        self.total_count = self.infeed.product_count
        if self.filler.complete and self.capper.complete:
            self.good_count = self.outfeed.product_count
        self.reject_count = self.rejector.reject_count

        # --- Fault aggregation ---
        self.any_fault = (
            self.infeed.jam_alarm
            or self.filler_conv.jam_alarm
            or self.capper_conv.jam_alarm
            or self.outfeed.jam_alarm
            or self.rejector.bin_full
        )

        # --- Stack light ---
        warning: BOOL = self.rejector.bin_full
        faulted: BOOL = self.state == 4 or self.state == 5
        self.stack(
            running=self.line_running,
            warning=warning,
            faulted=faulted,
        )
        self.green_light = self.stack.green
        self.yellow_light = self.stack.yellow
        self.red_light = self.stack.red


# ==========================================================================
# Tests
# ==========================================================================


class TestConveyorStation:
    @pytest.fixture
    def conv(self):
        ctx = simulate(ConveyorStation)
        ctx.e_stop = True
        return ctx

    def test_motor_runs_when_commanded(self, conv):
        conv.run_cmd = True
        conv.scan()
        assert conv.motor is True

    def test_e_stop_kills_motor(self, conv):
        conv.run_cmd = True
        conv.scan()
        assert conv.motor is True

        conv.e_stop = False
        conv.scan()
        assert conv.motor is False

    def test_jam_detection(self, conv):
        conv.run_cmd = True
        conv.product_sensor = True
        conv.tick(seconds=4)
        assert conv.jam_alarm is False
        assert conv.motor is True

        conv.tick(seconds=2)
        assert conv.jam_alarm is True
        assert conv.motor is False  # Jam kills motor

    def test_product_counting(self, conv):
        conv.run_cmd = True
        for _ in range(5):
            conv.product_sensor = True
            conv.scan()
            conv.product_sensor = False
            conv.scan()
        assert conv.product_count == 5

    def test_reset_count_via_input(self, conv):
        conv.run_cmd = True
        for _ in range(3):
            conv.product_sensor = True
            conv.scan()
            conv.product_sensor = False
            conv.scan()
        assert conv.product_count == 3

        conv.reset_cmd = True
        conv.scan()
        assert conv.product_count == 0


class TestFillerStation:
    @pytest.fixture
    def filler(self):
        return simulate(FillerStation)

    def test_stays_idle_without_start(self, filler):
        filler.scan()
        assert filler.state == 0
        assert filler.fill_valve is False

    def test_normal_fill_cycle(self, filler):
        filler.start = True
        filler.scan()  # IDLE → FILLING (state=1)
        filler.scan()  # FILLING runs
        assert filler.state == 1
        assert filler.fill_valve is True

        # Simulate fill reaching target
        filler.fill_level = 95.0
        filler.weight = 500.0
        filler.scan()  # Fill complete → CHECKING (state=2)
        filler.scan()  # CHECKING: check_timer increments
        filler.scan()  # CHECKING: check_timer>=1, all good → COMPLETE
        assert filler.state == 3
        assert filler.complete is True
        assert filler.fill_valve is False

    def test_underfill_reject(self, filler):
        filler.start = True
        filler.scan()  # → FILLING

        # Timeout: 1000 scans filling without reaching target
        filler.scan(n=1000)
        filler.scan()  # REJECT state runs
        assert filler.state == 4
        assert filler.reject is True
        assert filler.reject_reason == 1  # Underfill

    def test_overfill_reject(self, filler):
        filler.start = True
        filler.scan()  # → FILLING
        filler.scan()  # FILLING

        # Fill level way above target
        filler.fill_level = 100.0
        filler.weight = 500.0
        filler.scan()  # Fill complete → CHECKING
        filler.scan()  # check_timer=1
        filler.scan()  # Check: overfill (100 - 95 = 5 > tolerance 2) → REJECT
        assert filler.state == 4
        assert filler.reject_reason == 2  # Overfill

    def test_weight_reject(self, filler):
        filler.start = True
        filler.scan()  # → FILLING

        # Fill level within tolerance but weight out of range
        filler.fill_level = 95.0
        filler.weight = 520.0  # 20 over target, tolerance=10
        filler.scan()  # → CHECKING
        filler.scan()  # check_timer=1
        filler.scan()  # Check: weight error → REJECT
        assert filler.state == 4
        assert filler.reject_reason == 3  # Weight

    def test_returns_to_idle_on_start_drop(self, filler):
        filler.start = True
        filler.fill_level = 95.0
        filler.weight = 500.0
        filler.scan()  # → FILLING
        filler.scan()  # FILLING
        filler.scan()  # → CHECKING
        filler.scan()  # check_timer=1
        filler.scan()  # → COMPLETE
        assert filler.state == 3

        filler.start = False
        filler.scan()  # → IDLE
        assert filler.state == 0


class TestCapperStation:
    @pytest.fixture
    def capper(self):
        return simulate(CapperStation)

    def test_normal_cap_cycle(self, capper):
        capper.start = True
        capper.cap_present = True
        capper.torque = 10.0
        capper.scan()  # IDLE → CAPPING (state=1)
        capper.scan()  # CAPPING runs

        assert capper.state == 1
        assert capper.cap_actuator is True

        # Wait for capping to complete (200 scans)
        capper.scan(n=199)  # cap_timer reaches 200
        capper.scan()  # → VERIFYING
        capper.scan()  # Torque OK → COMPLETE
        assert capper.state == 3
        assert capper.complete is True

    def test_no_cap_reject(self, capper):
        capper.start = True
        capper.cap_present = False
        capper.scan()  # IDLE: no cap → REJECT
        capper.scan()  # REJECT runs
        assert capper.state == 4
        assert capper.reject is True
        assert capper.reject_reason == 1  # No cap

    def test_under_torque_reject(self, capper):
        capper.start = True
        capper.cap_present = True
        capper.torque = 3.0  # Below min_torque=5
        capper.scan()  # → CAPPING
        capper.scan(n=200)  # cap_timer=200 → VERIFYING
        capper.scan()  # VERIFYING: under-torque → state=4
        capper.scan()  # REJECT: reject=True
        assert capper.state == 4
        assert capper.reject is True
        assert capper.reject_reason == 2

    def test_over_torque_reject(self, capper):
        capper.start = True
        capper.cap_present = True
        capper.torque = 20.0  # Above max_torque=15
        capper.scan()  # → CAPPING
        capper.scan(n=200)  # → VERIFYING
        capper.scan()  # Over-torque → REJECT
        assert capper.state == 4
        assert capper.reject_reason == 2


class TestRejectStation:
    @pytest.fixture
    def rej(self):
        return simulate(RejectStation)

    def test_pulse_activation(self, rej):
        rej.trigger = True
        rej.scan()
        assert rej.diverter is True

        # Pulse lasts 500ms (50 scans at 10ms)
        rej.trigger = False
        rej.scan(n=48)
        assert rej.diverter is True

        rej.scan(n=5)
        assert rej.diverter is False

    def test_reject_counting_on_falling_edge(self, rej):
        # Trigger a reject
        rej.trigger = True
        rej.scan()
        rej.trigger = False

        # Wait for pulse to complete
        rej.scan(n=60)
        assert rej.diverter is False
        assert rej.reject_count == 1

    def test_bin_full_alarm(self, rej):
        rej.bin_level = 95.0
        rej.scan()
        assert rej.bin_full is True

        rej.bin_level = 80.0
        rej.scan()
        assert rej.bin_full is False


class TestStackLight:
    @pytest.fixture
    def light(self):
        return simulate(StackLight)

    def test_all_off_when_stopped(self, light):
        light.scan()
        assert light.green is False
        assert light.yellow is False
        assert light.red is False

    def test_green_when_running(self, light):
        light.running = True
        light.scan()
        assert light.green is True
        assert light.yellow is False
        assert light.red is False

    def test_yellow_overrides_green(self, light):
        light.running = True
        light.warning = True
        light.scan()
        assert light.green is False
        assert light.yellow is True

    def test_red_overrides_all(self, light):
        light.running = True
        light.warning = True
        light.faulted = True
        light.scan()
        assert light.green is False
        assert light.yellow is False
        assert light.red is True


class TestBottlingLine:
    @pytest.fixture
    def line(self):
        ctx = simulate(
            BottlingLine,
            pous=[
                ConveyorStation,
                FillerStation,
                CapperStation,
                RejectStation,
                StackLight,
            ],
            data_types=[StationStatus, ProductionCounters, FillerConfig],
        )
        return ctx

    def _start_line(self, ctx):
        """Helper: bring line from STOPPED to RUNNING."""
        ctx.start_cmd = True
        ctx.scan()  # STOPPED → STARTING
        ctx.scan(n=300)  # Startup timer reaches 300 → RUNNING
        ctx.scan()  # RUNNING state runs
        assert ctx.line_state == 2

    def test_starts_stopped(self, line):
        line.scan()
        assert line.line_state == 0
        assert line.infeed_motor is False
        assert line.green_light is False

    def test_start_sequence(self, line):
        line.start_cmd = True
        line.scan()  # → STARTING
        assert line.line_state == 1

        line.scan(n=300)  # Startup complete → RUNNING
        line.scan()
        assert line.line_state == 2
        assert line.infeed_motor is True
        assert line.green_light is True

    def test_stop_sequence(self, line):
        self._start_line(line)

        line.stop_cmd = True
        line.scan()  # RUNNING → STOPPING
        line.scan()  # STOPPING → STOPPED
        assert line.line_state == 0
        assert line.infeed_motor is False

    def test_e_stop(self, line):
        self._start_line(line)

        line.e_stop = False
        line.scan()  # → ESTOPPED (state=5)
        line.scan()  # ESTOPPED runs
        assert line.line_state == 5
        assert line.infeed_motor is False
        assert line.red_light is True

    def test_e_stop_recovery(self, line):
        self._start_line(line)

        # E-stop
        line.e_stop = False
        line.scan()
        line.scan()
        assert line.line_state == 5

        # Clear start_cmd before recovery to stay in STOPPED
        line.start_cmd = False

        # Recovery: clear e-stop + reset
        line.e_stop = True
        line.reset_cmd = True
        line.scan()  # → STOPPED
        line.scan()
        assert line.line_state == 0

    def test_conveyors_run_while_running(self, line):
        self._start_line(line)
        assert line.infeed_motor is True
        assert line.filler_motor is True
        assert line.capper_motor is True
        assert line.outfeed_motor is True

    def test_product_counting(self, line):
        self._start_line(line)

        # Simulate products passing infeed
        for _ in range(5):
            line.filler_product_sensor = True
            line.scan()
            line.filler_product_sensor = False
            line.scan()

        assert line.total_count == 5

    def test_reject_triggers_diverter(self, line):
        self._start_line(line)

        # Trigger filler with product present, then cause reject
        line.filler_product_sensor = True
        line.scan()
        # Filler starts (start = line_running and product_sensor)

        # Let filler timeout (underfill)
        line.scan(n=1005)
        # Filler reject → rejector trigger
        assert line.reject_diverter is True

    def test_stack_light_states(self, line):
        # Stopped — all off
        line.scan()
        assert line.green_light is False
        assert line.red_light is False

        # Running — green
        self._start_line(line)
        assert line.green_light is True

        # Faulted — red
        line.e_stop = False
        line.scan()
        line.scan()
        assert line.red_light is True


class TestBottlingProjectCompilation:
    def test_project_compiles_with_methods_and_structs(self):
        @program
        class CounterProgram:
            def logic(self):
                pass

        prj = project(
            "BottlingProject",
            pous=[
                ConveyorStation,
                FillerStation,
                CapperStation,
                RejectStation,
                StackLight,
                BottlingLine,
                CounterProgram,
            ],
            data_types=[StationStatus, ProductionCounters, FillerConfig],
            tasks=[
                task(
                    "MotorControl",
                    periodic=timedelta(milliseconds=10),
                    pous=[BottlingLine],
                    priority=1,
                ),
                task(
                    "Counters",
                    periodic=timedelta(milliseconds=100),
                    pous=[CounterProgram],
                    priority=5,
                ),
            ],
        ).compile()

        assert len(prj.pous) >= 6
        assert len(prj.tasks) == 2
        assert len(prj.data_types) == 3

        # Verify @fb_method on ConveyorStation
        pou_map = {p.name: p for p in prj.pous}
        conv_methods = pou_map["ConveyorStation"].methods
        assert any(m.name == "reset_count" for m in conv_methods)

        # Verify @fb_method on FillerStation
        filler_methods = pou_map["FillerStation"].methods
        assert any(m.name == "get_reject_reason" for m in filler_methods)

        # Verify match/case compiles to CaseStatement
        filler_networks = pou_map["FillerStation"].networks
        all_stmts = [s for n in filler_networks for s in n.statements]
        case_stmts = [s for s in all_stmts if s.kind == "case"]
        assert len(case_stmts) >= 1

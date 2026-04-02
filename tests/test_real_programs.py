"""Real-world PLC programs demonstrating the plx framework.

These are fully functional programs — not unit tests of individual features,
but complete control systems that exercise the framework end-to-end.
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
    fb,
    program,
    project,
    pulse,
    rising,
    sfc,
    step,
    struct,
    task,
    transition,
)
from plx.simulate import simulate

# ==========================================================================
# Program 1: Conveyor Sorting System
#
# Three conveyors feed a single merge conveyor. Each has a photo-eye at the
# infeed that detects product. A diverter gate routes product left/right
# based on barcode scanner data. The system has an E-stop, jam detection
# (photo-eye blocked too long), and motor overload interlocks.
# ==========================================================================


@struct
class ConveyorStatus:
    running: BOOL = False
    jammed: BOOL = False
    motor_overload: BOOL = False
    product_count: DINT = 0


@fb
class ConveyorDrive:
    """Single conveyor with jam detection and motor protection."""

    # Inputs
    run_cmd: Input[BOOL]
    photo_eye: Input[BOOL]  # True = product present
    motor_overload_fb: Input[BOOL]  # True = overload trip
    e_stop: Input[BOOL]  # True = safe (NC contact)

    # Outputs
    motor_run: Output[BOOL]
    jam_alarm: Output[BOOL]
    fault: Output[BOOL]
    product_count: Output[DINT]

    # Internals
    jam_detected: BOOL
    overload_latched: BOOL
    reset_cmd: Input[BOOL]

    def logic(self):
        # Latch motor overload — requires reset
        if self.motor_overload_fb:
            self.overload_latched = True
        if self.reset_cmd and not self.motor_overload_fb:
            self.overload_latched = False

        # Jam detection: photo-eye blocked > 10 seconds
        self.jam_detected = delayed(self.photo_eye, timedelta(seconds=10))
        self.jam_alarm = self.jam_detected

        # Fault = overload OR jam
        self.fault = self.overload_latched or self.jam_detected

        # Motor runs only when: commanded AND e-stop clear AND no faults
        self.motor_run = self.run_cmd and self.e_stop and not self.fault

        # Count products on rising edge of photo-eye
        if rising(self.photo_eye):
            self.product_count = self.product_count + 1


@fb
class DiverterGate:
    """Routes product left or right based on sort signal."""

    trigger: Input[BOOL]  # Rising edge = fire diverter
    sort_left: Input[BOOL]

    gate_left: Output[BOOL]
    gate_right: Output[BOOL]

    def logic(self):
        # On trigger, fire appropriate gate for 2 seconds
        if self.sort_left:
            self.gate_left = pulse(self.trigger, timedelta(seconds=2))
            self.gate_right = False
        else:
            self.gate_left = False
            self.gate_right = pulse(self.trigger, timedelta(seconds=2))


@fb
class SortingSystem:
    """Top-level sorting system with 3 infeed conveyors and a diverter."""

    # System inputs
    e_stop: Input[BOOL] = True
    system_run: Input[BOOL]
    sort_left: Input[BOOL]
    reset: Input[BOOL]

    # Sensor inputs
    infeed_1_eye: Input[BOOL]
    infeed_2_eye: Input[BOOL]
    infeed_3_eye: Input[BOOL]
    merge_eye: Input[BOOL]

    # Motor overloads
    infeed_1_ol: Input[BOOL]
    infeed_2_ol: Input[BOOL]
    infeed_3_ol: Input[BOOL]

    # Outputs
    infeed_1_motor: Output[BOOL]
    infeed_2_motor: Output[BOOL]
    infeed_3_motor: Output[BOOL]
    gate_left: Output[BOOL]
    gate_right: Output[BOOL]
    system_fault: Output[BOOL]
    total_product_count: Output[DINT]

    # Internal FBs
    conv1: ConveyorDrive
    conv2: ConveyorDrive
    conv3: ConveyorDrive
    diverter: DiverterGate

    def logic(self):
        # --- Infeed conveyor 1 ---
        self.conv1(
            run_cmd=self.system_run,
            photo_eye=self.infeed_1_eye,
            motor_overload_fb=self.infeed_1_ol,
            e_stop=self.e_stop,
            reset_cmd=self.reset,
        )
        self.infeed_1_motor = self.conv1.motor_run

        # --- Infeed conveyor 2 ---
        self.conv2(
            run_cmd=self.system_run,
            photo_eye=self.infeed_2_eye,
            motor_overload_fb=self.infeed_2_ol,
            e_stop=self.e_stop,
            reset_cmd=self.reset,
        )
        self.infeed_2_motor = self.conv2.motor_run

        # --- Infeed conveyor 3 ---
        self.conv3(
            run_cmd=self.system_run,
            photo_eye=self.infeed_3_eye,
            motor_overload_fb=self.infeed_3_ol,
            e_stop=self.e_stop,
            reset_cmd=self.reset,
        )
        self.infeed_3_motor = self.conv3.motor_run

        # --- Diverter gate ---
        self.diverter(
            trigger=rising(self.merge_eye),
            sort_left=self.sort_left,
        )
        self.gate_left = self.diverter.gate_left
        self.gate_right = self.diverter.gate_right

        # --- System-level fault ---
        self.system_fault = self.conv1.fault or self.conv2.fault or self.conv3.fault

        # --- Total product count ---
        self.total_product_count = self.conv1.product_count + self.conv2.product_count + self.conv3.product_count


class TestSortingSystem:
    @pytest.fixture
    def sys(self):
        ctx = simulate(
            SortingSystem,
            pous=[ConveyorDrive, DiverterGate],
            data_types=[ConveyorStatus],
        )
        ctx.e_stop = True  # NC contact — True = safe
        return ctx

    def test_system_starts_and_runs_motors(self, sys):
        sys.system_run = True
        sys.scan()
        assert sys.infeed_1_motor is True
        assert sys.infeed_2_motor is True
        assert sys.infeed_3_motor is True

    def test_e_stop_kills_all_motors(self, sys):
        sys.system_run = True
        sys.scan()
        assert sys.infeed_1_motor is True

        # Hit e-stop
        sys.e_stop = False
        sys.scan()
        assert sys.infeed_1_motor is False
        assert sys.infeed_2_motor is False
        assert sys.infeed_3_motor is False

    def test_motor_overload_latches_fault(self, sys):
        sys.system_run = True
        sys.scan()
        assert sys.infeed_1_motor is True

        # Trip overload on conveyor 1
        sys.infeed_1_ol = True
        sys.scan()
        assert sys.infeed_1_motor is False
        assert sys.system_fault is True

        # Overload clears, but fault stays latched
        sys.infeed_1_ol = False
        sys.scan()
        assert sys.infeed_1_motor is False
        assert sys.system_fault is True

        # Reset clears the latched fault
        sys.reset = True
        sys.scan()
        assert sys.infeed_1_motor is True
        assert sys.system_fault is False

    def test_jam_detection(self, sys):
        sys.system_run = True
        sys.scan()
        assert sys.infeed_2_motor is True

        # Photo-eye blocked — product stuck
        sys.infeed_2_eye = True
        sys.tick(seconds=9)
        assert sys.infeed_2_motor is True  # Not jammed yet

        sys.tick(seconds=2)
        assert sys.infeed_2_motor is False  # Jam detected
        assert sys.system_fault is True

    def test_product_counting(self, sys):
        sys.system_run = True
        sys.scan()

        # Simulate 3 products on conveyor 1
        for _ in range(3):
            sys.infeed_1_eye = True
            sys.scan()
            sys.infeed_1_eye = False
            sys.scan()

        # 2 products on conveyor 3
        for _ in range(2):
            sys.infeed_3_eye = True
            sys.scan()
            sys.infeed_3_eye = False
            sys.scan()

        assert sys.total_product_count == 5

    def test_diverter_sorts_left(self, sys):
        sys.system_run = True
        sys.sort_left = True
        sys.scan()

        # Product arrives at merge point
        sys.merge_eye = True
        sys.scan()
        assert sys.gate_left is True
        assert sys.gate_right is False

    def test_diverter_sorts_right(self, sys):
        sys.system_run = True
        sys.sort_left = False
        sys.scan()

        sys.merge_eye = True
        sys.scan()
        assert sys.gate_left is False
        assert sys.gate_right is True


# ==========================================================================
# Program 2: Tank Level PID Control (simplified)
#
# Controls liquid level in a tank with inlet and drain valves.
# Fill mode ramps up, drain mode ramps down. Includes high/low alarms,
# overflow protection, and a deadband to prevent valve hunting.
# ==========================================================================


@fb
class TankLevelControl:
    """Simplified tank level control with proportional output and alarms."""

    # Inputs
    level_pv: Input[REAL]  # Current level (0-100%)
    setpoint: Input[REAL] = 50.0
    enable: Input[BOOL]

    # Tuning
    kp: Input[REAL] = 2.0  # Proportional gain
    deadband: Input[REAL] = 1.0  # +/- deadband around SP

    # Alarm setpoints
    hi_alarm_sp: Input[REAL] = 90.0
    hihi_alarm_sp: Input[REAL] = 95.0
    lo_alarm_sp: Input[REAL] = 10.0
    lolo_alarm_sp: Input[REAL] = 5.0

    # Outputs
    inlet_valve: Output[REAL]  # 0-100% open
    drain_valve: Output[REAL]  # 0-100% open
    hi_alarm: Output[BOOL]
    hihi_alarm: Output[BOOL]
    lo_alarm: Output[BOOL]
    lolo_alarm: Output[BOOL]
    at_setpoint: Output[BOOL]

    # Internals
    error: REAL

    def logic(self):
        # --- Alarms ---
        self.hi_alarm = self.level_pv >= self.hi_alarm_sp
        self.hihi_alarm = self.level_pv >= self.hihi_alarm_sp
        self.lo_alarm = self.level_pv <= self.lo_alarm_sp
        self.lolo_alarm = self.level_pv <= self.lolo_alarm_sp

        # --- Error calculation ---
        self.error = self.setpoint - self.level_pv

        # --- Deadband check ---
        if self.error > -self.deadband and self.error < self.deadband:
            self.at_setpoint = True
        else:
            self.at_setpoint = False

        if not self.enable:
            # Disabled — close everything
            self.inlet_valve = 0.0
            self.drain_valve = 0.0
        elif self.hihi_alarm:
            # Emergency: force drain, close inlet
            self.inlet_valve = 0.0
            self.drain_valve = 100.0
        elif self.lolo_alarm:
            # Emergency: force fill, close drain
            self.inlet_valve = 100.0
            self.drain_valve = 0.0
        elif self.at_setpoint:
            # Within deadband — hold
            self.inlet_valve = 0.0
            self.drain_valve = 0.0
        else:
            # Proportional control
            output: REAL = self.error * self.kp

            # Clamp to 0-100
            if output > 100.0:
                output = 100.0
            if output < -100.0:
                output = -100.0

            if output > 0.0:
                self.inlet_valve = output
                self.drain_valve = 0.0
            else:
                self.inlet_valve = 0.0
                self.drain_valve = -output


class TestTankLevelControl:
    @pytest.fixture
    def tank(self):
        ctx = simulate(TankLevelControl)
        ctx.enable = True
        return ctx

    def test_below_setpoint_opens_inlet(self, tank):
        tank.setpoint = 50.0
        tank.level_pv = 30.0
        tank.scan()
        assert tank.inlet_valve > 0.0
        assert tank.drain_valve == pytest.approx(0.0)

    def test_above_setpoint_opens_drain(self, tank):
        tank.setpoint = 50.0
        tank.level_pv = 70.0
        tank.scan()
        assert tank.inlet_valve == pytest.approx(0.0)
        assert tank.drain_valve > 0.0

    def test_at_setpoint_closes_both(self, tank):
        tank.setpoint = 50.0
        tank.level_pv = 50.0  # Exactly at SP, within deadband
        tank.scan()
        assert tank.inlet_valve == pytest.approx(0.0)
        assert tank.drain_valve == pytest.approx(0.0)
        assert tank.at_setpoint is True

    def test_deadband_prevents_hunting(self, tank):
        tank.setpoint = 50.0
        tank.deadband = 2.0

        # Just inside deadband — should be at setpoint
        tank.level_pv = 49.5
        tank.scan()
        assert tank.at_setpoint is True
        assert tank.inlet_valve == pytest.approx(0.0)

        # Just outside deadband — should control
        tank.level_pv = 47.0
        tank.scan()
        assert tank.at_setpoint is False
        assert tank.inlet_valve > 0.0

    def test_proportional_response(self, tank):
        tank.setpoint = 50.0
        tank.kp = 2.0

        # 10% below SP → error=10 → output=20%
        tank.level_pv = 40.0
        tank.scan()
        assert tank.inlet_valve == pytest.approx(20.0)

        # 20% below → error=20 → output=40%
        tank.level_pv = 30.0
        tank.scan()
        assert tank.inlet_valve == pytest.approx(40.0)

    def test_output_clamped_to_100(self, tank):
        tank.setpoint = 50.0
        tank.kp = 10.0  # High gain

        tank.level_pv = 0.0  # error=50, output=500 → clamp to 100
        tank.scan()
        assert tank.inlet_valve == pytest.approx(100.0)

    def test_hihi_alarm_forces_drain(self, tank):
        tank.setpoint = 50.0
        tank.level_pv = 96.0
        tank.scan()
        assert tank.hihi_alarm is True
        assert tank.inlet_valve == pytest.approx(0.0)
        assert tank.drain_valve == pytest.approx(100.0)

    def test_lolo_alarm_forces_fill(self, tank):
        tank.setpoint = 50.0
        tank.level_pv = 4.0
        tank.scan()
        assert tank.lolo_alarm is True
        assert tank.inlet_valve == pytest.approx(100.0)
        assert tank.drain_valve == pytest.approx(0.0)

    def test_disabled_closes_valves(self, tank):
        tank.enable = False
        tank.level_pv = 30.0
        tank.scan()
        assert tank.inlet_valve == pytest.approx(0.0)
        assert tank.drain_valve == pytest.approx(0.0)

    def test_all_alarms(self, tank):
        # HI alarm
        tank.level_pv = 91.0
        tank.scan()
        assert tank.hi_alarm is True
        assert tank.hihi_alarm is False

        # LO alarm
        tank.level_pv = 9.0
        tank.scan()
        assert tank.lo_alarm is True
        assert tank.lolo_alarm is False


# ==========================================================================
# Program 3: Traffic Light Controller (SFC)
#
# A proper traffic light intersection controller with:
# - Green → Yellow → Red cycle
# - Pedestrian walk request button
# - Minimum green time (15s), yellow time (3s)
# - Pedestrian crossing extends the red phase
# ==========================================================================


@sfc
class TrafficLightController:
    """Four-phase traffic light with pedestrian crossing."""

    # Inputs
    ped_request: Input[BOOL]

    # Outputs
    green_light: Output[BOOL]
    yellow_light: Output[BOOL]
    red_light: Output[BOOL]
    walk_light: Output[BOOL]
    dont_walk_light: Output[BOOL]

    # Internal timers
    phase_timer: DINT = 0
    ped_pending: BOOL

    # Steps
    GREEN = step(initial=True)
    YELLOW = step()
    RED = step()
    PED_WALK = step()

    # -- Transitions --

    @transition(GREEN >> YELLOW)
    def green_to_yellow(self):
        # Green for at least 15 seconds (1500 scans at 10ms)
        return self.phase_timer >= 1500

    @transition(YELLOW >> RED)
    def yellow_to_red(self):
        # Yellow for 3 seconds (300 scans)
        return self.phase_timer >= 300

    @transition(RED >> PED_WALK)
    def red_to_ped(self):
        # If pedestrian requested, go to walk phase after 2s all-red
        return self.ped_pending and self.phase_timer >= 200

    @transition(RED >> GREEN)
    def red_to_green(self):
        # No pedestrian: 2 second all-red clearance
        return not self.ped_pending and self.phase_timer >= 200

    @transition(PED_WALK >> GREEN)
    def ped_to_green(self):
        # Walk phase lasts 10 seconds
        return self.phase_timer >= 1000

    # -- Actions --

    @GREEN.entry
    def enter_green(self):
        self.phase_timer = 0
        self.green_light = True
        self.yellow_light = False
        self.red_light = False
        self.walk_light = False
        self.dont_walk_light = True

    @GREEN.action
    def green_action(self):
        self.phase_timer = self.phase_timer + 1
        # Latch pedestrian request
        if self.ped_request:
            self.ped_pending = True

    @YELLOW.entry
    def enter_yellow(self):
        self.phase_timer = 0
        self.green_light = False
        self.yellow_light = True

    @YELLOW.action
    def yellow_action(self):
        self.phase_timer = self.phase_timer + 1

    @RED.entry
    def enter_red(self):
        self.phase_timer = 0
        self.yellow_light = False
        self.red_light = True

    @RED.action
    def red_action(self):
        self.phase_timer = self.phase_timer + 1

    @PED_WALK.entry
    def enter_ped_walk(self):
        self.phase_timer = 0
        self.walk_light = True
        self.dont_walk_light = False
        self.ped_pending = False  # Clear the request

    @PED_WALK.action
    def ped_walk_action(self):
        self.phase_timer = self.phase_timer + 1


class TestTrafficLightController:
    @pytest.fixture
    def tl(self):
        return simulate(TrafficLightController)

    def test_starts_green(self, tl):
        tl.scan()
        assert tl.green_light is True
        assert tl.yellow_light is False
        assert tl.red_light is False

    def test_green_to_yellow_after_15s(self, tl):
        tl.scan()
        assert "GREEN" in tl.active_steps

        # Run for 15 seconds (1500 scans at 10ms each)
        tl.scan(n=1500)
        assert "YELLOW" in tl.active_steps
        assert tl.green_light is False
        assert tl.yellow_light is True

    def test_full_cycle_without_ped(self, tl):
        tl.scan()
        assert "GREEN" in tl.active_steps

        # Green → Yellow (15s)
        tl.scan(n=1500)
        assert "YELLOW" in tl.active_steps

        # Yellow → Red (3s)
        tl.scan(n=300)
        assert "RED" in tl.active_steps
        assert tl.red_light is True

        # Red → Green (2s, no ped request)
        tl.scan(n=200)
        assert "GREEN" in tl.active_steps
        assert tl.green_light is True

    def test_pedestrian_cycle(self, tl):
        tl.scan()

        # Press walk button during green
        tl.ped_request = True
        tl.scan()
        tl.ped_request = False
        assert tl.ped_pending is True

        # Green → Yellow
        tl.scan(n=1500)
        assert "YELLOW" in tl.active_steps

        # Yellow → Red
        tl.scan(n=300)
        assert "RED" in tl.active_steps

        # Red → Ped Walk (ped_pending is True)
        tl.scan(n=200)
        assert "PED_WALK" in tl.active_steps
        assert tl.walk_light is True
        assert tl.dont_walk_light is False
        assert tl.ped_pending is False  # Cleared on entry

        # Ped Walk → Green (10s)
        tl.scan(n=1000)
        assert "GREEN" in tl.active_steps


# ==========================================================================
# Program 4: Batch Mixing Process
#
# Three ingredient tanks dose into a mixing vessel. The process:
# 1. Fill ingredient A to target weight
# 2. Fill ingredient B to target weight
# 3. Agitate for configured time
# 4. Drain the mix
# 5. Return to idle
#
# With interlock: agitator can't run while filling or draining.
# ==========================================================================


@sfc
class BatchMixer:
    """Three-step batch: fill A, fill B, mix, drain."""

    # Inputs
    start_cmd: Input[BOOL]
    weight_pv: Input[REAL]
    mix_complete: Input[BOOL]  # Simulated: agitation done
    vessel_empty: Input[BOOL]
    abort_cmd: Input[BOOL]

    # Recipe parameters
    target_a: Input[REAL] = 100.0
    target_b: Input[REAL] = 50.0

    # Outputs
    valve_a: Output[BOOL]
    valve_b: Output[BOOL]
    agitator: Output[BOOL]
    drain_valve: Output[BOOL]
    batch_complete: Output[BOOL]
    batch_running: Output[BOOL]
    current_step_id: Output[INT]

    # Internals
    weight_at_start_b: REAL
    mix_timer: DINT = 0

    # Steps
    IDLE = step(initial=True)
    FILL_A = step()
    FILL_B = step()
    MIXING = step()
    DRAINING = step()
    COMPLETE = step()

    # -- Transitions --

    @transition(IDLE >> FILL_A)
    def start(self):
        return self.start_cmd

    @transition(FILL_A >> FILL_B)
    def a_done(self):
        return self.weight_pv >= self.target_a

    @transition(FILL_B >> MIXING)
    def b_done(self):
        return self.weight_pv >= self.weight_at_start_b + self.target_b

    @transition(MIXING >> DRAINING)
    def mix_done(self):
        # Mix for 500 scans (5 seconds at 10ms)
        return self.mix_timer >= 500

    @transition(DRAINING >> COMPLETE)
    def drain_done(self):
        return self.vessel_empty

    @transition(COMPLETE >> IDLE)
    def ack(self):
        return not self.start_cmd  # Operator releases start button

    # -- Actions --

    @IDLE.entry
    def idle_entry(self):
        self.valve_a = False
        self.valve_b = False
        self.agitator = False
        self.drain_valve = False
        self.batch_complete = False
        self.batch_running = False
        self.current_step_id = 0

    @FILL_A.entry
    def fill_a_entry(self):
        self.valve_a = True
        self.batch_running = True
        self.current_step_id = 1

    @FILL_A.exit
    def fill_a_exit(self):
        self.valve_a = False

    @FILL_B.entry
    def fill_b_entry(self):
        self.weight_at_start_b = self.weight_pv
        self.valve_b = True
        self.current_step_id = 2

    @FILL_B.exit
    def fill_b_exit(self):
        self.valve_b = False

    @MIXING.entry
    def mix_entry(self):
        self.agitator = True
        self.mix_timer = 0
        self.current_step_id = 3

    @MIXING.action
    def mix_action(self):
        self.mix_timer = self.mix_timer + 1

    @MIXING.exit
    def mix_exit(self):
        self.agitator = False

    @DRAINING.entry
    def drain_entry(self):
        self.drain_valve = True
        self.current_step_id = 4

    @DRAINING.exit
    def drain_exit(self):
        self.drain_valve = False

    @COMPLETE.entry
    def complete_entry(self):
        self.batch_complete = True
        self.batch_running = False
        self.current_step_id = 5


class TestBatchMixer:
    @pytest.fixture
    def batch(self):
        return simulate(BatchMixer)

    def test_stays_idle_without_start(self, batch):
        batch.scan()
        assert "IDLE" in batch.active_steps
        assert batch.batch_running is False

    def test_full_batch_sequence(self, batch):
        batch.scan()  # Initialize
        assert "IDLE" in batch.active_steps

        # Start batch — transition fires, entry runs next scan
        batch.start_cmd = True
        batch.scan()  # Transition IDLE→FILL_A fires
        batch.scan()  # FILL_A entry runs
        assert "FILL_A" in batch.active_steps
        assert batch.valve_a is True
        assert batch.batch_running is True

        # Simulate weight reaching target A
        batch.weight_pv = 100.0
        batch.scan()  # Transition FILL_A→FILL_B fires
        batch.scan()  # FILL_B entry runs
        assert "FILL_B" in batch.active_steps
        assert batch.valve_a is False
        assert batch.valve_b is True

        # Simulate weight reaching target A + B (100 + 50)
        batch.weight_pv = 150.0
        batch.scan()  # Transition FILL_B→MIXING fires
        batch.scan()  # MIXING entry runs
        assert "MIXING" in batch.active_steps
        assert batch.valve_b is False
        assert batch.agitator is True

        # Mix for 5 seconds (500 scans of N-action incrementing mix_timer)
        batch.scan(n=500)  # Transition MIXING→DRAINING fires on scan 500
        batch.scan()  # DRAINING entry runs
        assert "DRAINING" in batch.active_steps
        assert batch.agitator is False
        assert batch.drain_valve is True

        # Vessel empties
        batch.vessel_empty = True
        batch.scan()  # Transition fires
        batch.scan()  # COMPLETE entry runs
        assert "COMPLETE" in batch.active_steps
        assert batch.drain_valve is False
        assert batch.batch_complete is True

        # Release start button to return to idle
        batch.start_cmd = False
        batch.scan()  # Transition fires
        batch.scan()  # IDLE entry runs
        assert "IDLE" in batch.active_steps

    def test_weight_at_start_b_records_correctly(self, batch):
        """Fill B target is relative — verifies weight_at_start_b is captured."""
        batch.scan()

        batch.start_cmd = True
        batch.scan()  # Transition fires
        batch.scan()  # FILL_A entry runs

        # Ingredient A fills to 120 (overshoot)
        batch.weight_pv = 120.0
        batch.scan()  # Transition fires
        batch.scan()  # FILL_B entry runs (weight_at_start_b = 120.0)
        assert "FILL_B" in batch.active_steps

        # Need 50 more kg on top of 120
        batch.weight_pv = 160.0
        batch.scan()
        assert "FILL_B" in batch.active_steps  # Not done (120 + 50 = 170)

        batch.weight_pv = 170.0
        batch.scan()  # Transition fires
        batch.scan()  # MIXING entry runs
        assert "MIXING" in batch.active_steps

    def test_step_id_progression(self, batch):
        batch.scan()
        assert batch.current_step_id == 0  # IDLE

        batch.start_cmd = True
        batch.scan()  # Transition fires
        batch.scan()  # FILL_A entry runs
        assert batch.current_step_id == 1  # FILL_A

        batch.weight_pv = 100.0
        batch.scan()  # Transition fires
        batch.scan()  # FILL_B entry runs
        assert batch.current_step_id == 2  # FILL_B

        batch.weight_pv = 150.0
        batch.scan()  # Transition fires
        batch.scan()  # MIXING entry runs
        assert batch.current_step_id == 3  # MIXING


# ==========================================================================
# Program 5: Star-Delta Motor Starter
#
# Classic motor starting sequence:
# 1. Close star contactor (low-torque start)
# 2. After 5 seconds, open star and close delta (full power)
# 3. Motor overload trips fault (latched)
# 4. Requires reset to clear fault
# ==========================================================================


@fb
class StarDeltaStarter:
    """Star-delta motor starter with timing and fault logic."""

    # Inputs
    start_cmd: Input[BOOL]
    stop_cmd: Input[BOOL]
    overload_trip: Input[BOOL]
    reset_cmd: Input[BOOL]

    # Outputs
    main_contactor: Output[BOOL]
    star_contactor: Output[BOOL]
    delta_contactor: Output[BOOL]
    running: Output[BOOL]
    fault: Output[BOOL]
    starting: Output[BOOL]

    # Internals
    state: INT = 0
    # 0=stopped, 1=starting(star), 2=running(delta), 3=fault
    star_timer: DINT = 0
    switch_delay: DINT = 0

    def logic(self):
        # State machine
        match self.state:
            case 0:
                # STOPPED
                self.main_contactor = False
                self.star_contactor = False
                self.delta_contactor = False
                self.running = False
                self.starting = False
                self.star_timer = 0
                self.switch_delay = 0

                if self.start_cmd and not self.overload_trip:
                    self.state = 1

            case 1:
                # STARTING (Star configuration)
                self.main_contactor = True
                self.star_contactor = True
                self.delta_contactor = False
                self.starting = True
                self.running = False

                self.star_timer = self.star_timer + 1

                # After 5 seconds (500 scans), switch to delta
                if self.star_timer >= 500:
                    # Brief dead-time: open star before closing delta
                    self.star_contactor = False
                    self.switch_delay = self.switch_delay + 1

                    # 50ms dead-time (5 scans)
                    if self.switch_delay >= 5:
                        self.state = 2

                if self.stop_cmd:
                    self.state = 0

            case 2:
                # RUNNING (Delta configuration)
                self.main_contactor = True
                self.star_contactor = False
                self.delta_contactor = True
                self.running = True
                self.starting = False

                if self.stop_cmd:
                    self.state = 0

            case 3:
                # FAULT
                self.main_contactor = False
                self.star_contactor = False
                self.delta_contactor = False
                self.running = False
                self.starting = False
                self.fault = True

                if self.reset_cmd and not self.overload_trip:
                    self.fault = False
                    self.state = 0

        # Overload trips from any state
        if self.overload_trip and self.state != 3:
            self.state = 3


class TestStarDeltaStarter:
    @pytest.fixture
    def motor(self):
        return simulate(StarDeltaStarter)

    def test_starts_in_stopped(self, motor):
        motor.scan()
        assert motor.running is False
        assert motor.starting is False
        assert motor.main_contactor is False

    def test_start_engages_star(self, motor):
        motor.scan()  # State=0, outputs cleared
        motor.start_cmd = True
        motor.scan()  # State 0→1 (state changes, but case 0 ran)
        motor.scan()  # Now case 1 runs: star engaged
        assert motor.starting is True
        assert motor.main_contactor is True
        assert motor.star_contactor is True
        assert motor.delta_contactor is False

    def test_star_to_delta_transition(self, motor):
        motor.scan()
        motor.start_cmd = True
        motor.scan()  # State 0→1
        motor.scan()  # Case 1 runs, star_timer=1

        # Run star — need 500 timer ticks, already at 1
        motor.scan(n=498)
        assert motor.star_contactor is True
        assert motor.delta_contactor is False

        # Star timer hits 500, dead-time begins (5 scans)
        motor.scan(n=5)
        assert motor.star_contactor is False

        # State transitions 1→2, next scan runs case 2
        motor.scan()  # State becomes 2
        motor.scan()  # Case 2 runs
        assert motor.running is True
        assert motor.delta_contactor is True
        assert motor.star_contactor is False

    def test_stop_from_running(self, motor):
        motor.scan()
        motor.start_cmd = True
        motor.scan()  # 0→1
        motor.scan()  # Case 1 starts, timer=1
        motor.scan(n=498)  # timer=499
        motor.scan(n=5)  # timer=500+, dead-time
        motor.scan()  # 1→2
        motor.scan()  # Case 2 runs
        assert motor.running is True

        motor.stop_cmd = True
        motor.scan()  # 2→0
        motor.scan()  # Case 0 runs
        assert motor.running is False
        assert motor.main_contactor is False

    def test_overload_faults(self, motor):
        motor.scan()
        motor.start_cmd = True
        motor.scan()  # 0→1
        motor.scan()  # Case 1 runs
        motor.scan(n=498)
        motor.scan(n=5)
        motor.scan()  # 1→2
        motor.scan()  # Case 2 runs
        assert motor.running is True

        # Overload trips — the overload check runs AFTER match/case
        motor.overload_trip = True
        motor.scan()  # Case 2 runs (sets running=True), then overload sets state=3
        motor.scan()  # Case 3 runs: everything off, fault=True
        assert motor.running is False
        assert motor.fault is True
        assert motor.main_contactor is False

    def test_fault_requires_reset_and_clear_overload(self, motor):
        motor.scan()
        motor.start_cmd = True
        motor.scan()  # 0→1

        # Overload during starting
        motor.overload_trip = True
        motor.scan()  # Case 1 runs, then overload sets state=3
        motor.scan()  # Case 3 runs, fault=True
        assert motor.fault is True

        # Reset with overload still active — stays faulted
        motor.reset_cmd = True
        motor.scan()
        assert motor.fault is True

        # Clear overload, then reset
        motor.overload_trip = False
        motor.scan()  # Reset clears fault, state=0
        assert motor.fault is False
        assert motor.state == 0  # Back to stopped


# ==========================================================================
# Program 6: Elevator Door Controller
#
# Controls elevator door open/close with:
# - Open/close commands
# - Safety edge (obstruction detection) — reopens if blocked
# - Timeout auto-close (doors open too long)
# - Position feedback (fully open / fully closed sensors)
# - Nudge mode after repeated obstructions
# ==========================================================================


@fb
class ElevatorDoor:
    """Elevator door controller with safety and timeout logic."""

    # Inputs
    open_cmd: Input[BOOL]
    close_cmd: Input[BOOL]
    safety_edge: Input[BOOL]  # True = obstruction detected
    fully_open: Input[BOOL]
    fully_closed: Input[BOOL]

    # Outputs
    motor_open: Output[BOOL]
    motor_close: Output[BOOL]
    buzzer: Output[BOOL]
    nudge_mode: Output[BOOL]

    # Internals
    state: INT = 0
    # 0=closed, 1=opening, 2=open, 3=closing, 4=nudge_closing
    open_timer: DINT = 0
    obstruction_count: INT = 0

    def logic(self):
        match self.state:
            case 0:
                # CLOSED
                self.motor_open = False
                self.motor_close = False
                self.buzzer = False
                self.nudge_mode = False
                self.open_timer = 0
                self.obstruction_count = 0

                if self.open_cmd:
                    self.state = 1

            case 1:
                # OPENING
                self.motor_open = True
                self.motor_close = False

                if self.fully_open:
                    self.state = 2

            case 2:
                # OPEN (waiting to close)
                self.motor_open = False
                self.motor_close = False
                self.open_timer = self.open_timer + 1

                # Auto-close after 5 seconds (500 scans)
                if self.close_cmd or self.open_timer >= 500:
                    if self.obstruction_count >= 3:
                        self.state = 4  # Nudge mode
                    else:
                        self.state = 3

            case 3:
                # CLOSING
                self.motor_open = False
                self.motor_close = True
                self.buzzer = False

                # Safety edge — reopen
                if self.safety_edge:
                    self.obstruction_count = self.obstruction_count + 1
                    self.state = 1  # Reopen

                if self.fully_closed:
                    self.state = 0

                # Open button overrides
                if self.open_cmd:
                    self.state = 1

            case 4:
                # NUDGE MODE — close slowly with buzzer, ignore safety edge
                self.motor_close = True
                self.motor_open = False
                self.buzzer = True
                self.nudge_mode = True

                if self.fully_closed:
                    self.state = 0


class TestElevatorDoor:
    @pytest.fixture
    def door(self):
        ctx = simulate(ElevatorDoor)
        ctx.fully_closed = True  # Start fully closed
        ctx.scan()
        return ctx

    def test_starts_closed(self, door):
        assert door.motor_open is False
        assert door.motor_close is False

    def test_open_command(self, door):
        door.open_cmd = True
        door.fully_closed = False
        door.scan()  # State 0→1
        door.scan()  # Case 1 runs: motor_open=True
        assert door.motor_open is True

    def test_stops_when_fully_open(self, door):
        door.open_cmd = True
        door.fully_closed = False
        door.scan()  # 0→1
        door.scan()  # Case 1: motor_open=True
        assert door.motor_open is True

        door.open_cmd = False
        door.fully_open = True
        door.scan()  # Case 1: fully_open → 1→2
        door.scan()  # Case 2: motor_open=False
        assert door.motor_open is False
        assert door.state == 2  # OPEN

    def test_auto_close_after_timeout(self, door):
        # Open the door
        door.open_cmd = True
        door.fully_closed = False
        door.scan()  # 0→1
        door.scan()  # Case 1: opening
        door.open_cmd = False
        door.fully_open = True
        door.scan()  # 1→2
        door.scan()  # Case 2: open, timer starts
        assert door.state == 2

        # Wait 5 seconds (500 scans, timer increments each scan)
        # Timer is already at 1 from the scan above
        door.scan(n=499)
        assert door.state == 3  # Case 2 transitions to 3
        door.scan()  # Case 3 runs: motor_close=True
        assert door.motor_close is True

    def test_safety_edge_reopens(self, door):
        # Open → fully open → close
        door.open_cmd = True
        door.fully_closed = False
        door.scan()  # 0→1
        door.scan()  # Case 1: opening
        door.open_cmd = False
        door.fully_open = True
        door.scan()  # 1→2
        door.scan()  # Case 2: open
        door.fully_open = False
        door.close_cmd = True
        door.scan()  # 2→3
        door.scan()  # Case 3: closing
        assert door.state == 3

        # Obstruction!
        door.close_cmd = False
        door.safety_edge = True
        door.scan()  # 3→1
        assert door.state == 1
        assert door.obstruction_count == 1

    def test_nudge_mode_after_three_obstructions(self, door):
        # Open the door
        door.open_cmd = True
        door.fully_closed = False
        door.scan()  # 0→1
        door.scan()  # Case 1: opening
        door.open_cmd = False
        door.fully_open = True
        door.scan()  # 1→2
        door.scan()  # Case 2: open
        door.fully_open = False

        # Simulate 3 obstructions
        for _ in range(3):
            door.close_cmd = True
            door.scan()  # 2→3
            door.scan()  # Case 3: closing
            door.close_cmd = False
            door.safety_edge = True
            door.scan()  # 3→1 (obstruction)
            door.scan()  # Case 1: opening
            door.safety_edge = False
            door.fully_open = True
            door.scan()  # 1→2
            door.scan()  # Case 2: open
            door.fully_open = False

        assert door.obstruction_count == 3

        # Next close should enter nudge mode
        door.close_cmd = True
        door.scan()  # 2→4 (nudge)
        door.scan()  # Case 4: nudge
        assert door.state == 4
        assert door.buzzer is True
        assert door.nudge_mode is True

    def test_nudge_mode_ignores_safety_edge(self, door):
        """In nudge mode, safety edge is ignored — door closes regardless."""
        door.open_cmd = True
        door.fully_closed = False
        door.scan()  # 0→1
        door.scan()  # Case 1
        door.open_cmd = False
        door.fully_open = True
        door.scan()  # 1→2
        door.scan()  # Case 2
        door.fully_open = False

        for _ in range(3):
            door.close_cmd = True
            door.scan()  # →3
            door.scan()  # Case 3
            door.close_cmd = False
            door.safety_edge = True
            door.scan()  # →1
            door.scan()  # Case 1
            door.safety_edge = False
            door.fully_open = True
            door.scan()  # →2
            door.scan()  # Case 2
            door.fully_open = False

        door.close_cmd = True
        door.scan()  # →4
        door.scan()  # Case 4: nudge
        assert door.state == 4

        # Safety edge in nudge mode — door keeps closing
        door.close_cmd = False
        door.safety_edge = True
        door.scan()
        assert door.state == 4  # Still nudging
        assert door.motor_close is True

        # Eventually closes
        door.fully_closed = True
        door.scan()  # 4→0
        door.scan()  # Case 0
        assert door.state == 0  # CLOSED


# ==========================================================================
# Program 7: Pump Alternation System
#
# Two duty/standby pumps for a sump. Features:
# - Level-based start/stop (hi starts pump, lo stops)
# - Lead/lag alternation (swap lead pump each cycle)
# - Auto-failover if lead pump faults
# - Run-hour equalization
# ==========================================================================


@fb
class PumpAlternation:
    """Dual pump system with lead/lag alternation and failover."""

    # Inputs
    level_hi: Input[BOOL]  # Start pumping
    level_lo: Input[BOOL]  # Stop pumping
    level_hihi: Input[BOOL]  # Both pumps needed
    pump1_fault: Input[BOOL]
    pump2_fault: Input[BOOL]

    # Outputs
    pump1_run: Output[BOOL]
    pump2_run: Output[BOOL]
    alarm: Output[BOOL]
    lead_pump: Output[INT] = 1  # 1 or 2

    # Internals
    pumping: BOOL
    was_pumping: BOOL
    pump1_hours: DINT = 0
    pump2_hours: DINT = 0

    def logic(self):
        # Level control — start on hi, stop on lo
        if self.level_hi:
            self.pumping = True
        if self.level_lo:
            self.pumping = False

        # Select lead pump only at START of pumping cycle (rising edge)
        # This prevents oscillation during a cycle
        if self.pumping and not self.was_pumping:
            if self.pump1_hours <= self.pump2_hours:
                self.lead_pump = 1
            else:
                self.lead_pump = 2
        self.was_pumping = self.pumping

        # Assign pumps
        if self.pumping:
            if self.lead_pump == 1:
                if not self.pump1_fault:
                    self.pump1_run = True
                    self.pump2_run = False
                else:
                    # Failover to pump 2
                    self.pump1_run = False
                    self.pump2_run = not self.pump2_fault
            else:
                if not self.pump2_fault:
                    self.pump2_run = True
                    self.pump1_run = False
                else:
                    # Failover to pump 1
                    self.pump2_run = False
                    self.pump1_run = not self.pump1_fault

            # Hi-hi: run both pumps
            if self.level_hihi:
                if not self.pump1_fault:
                    self.pump1_run = True
                if not self.pump2_fault:
                    self.pump2_run = True
        else:
            self.pump1_run = False
            self.pump2_run = False

        # Track run hours (increment each scan while running)
        if self.pump1_run:
            self.pump1_hours = self.pump1_hours + 1
        if self.pump2_run:
            self.pump2_hours = self.pump2_hours + 1

        # Alarm: both pumps faulted
        self.alarm = self.pump1_fault and self.pump2_fault


class TestPumpAlternation:
    @pytest.fixture
    def pumps(self):
        return simulate(PumpAlternation)

    def test_pumps_off_below_level(self, pumps):
        pumps.scan()
        assert pumps.pump1_run is False
        assert pumps.pump2_run is False

    def test_lead_pump_starts_on_hi_level(self, pumps):
        pumps.scan()
        pumps.level_hi = True
        pumps.scan()
        assert pumps.pump1_run is True  # Pump 1 is default lead
        assert pumps.pump2_run is False

    def test_stops_on_lo_level(self, pumps):
        pumps.level_hi = True
        pumps.scan()
        assert pumps.pump1_run is True

        pumps.level_hi = False
        pumps.level_lo = True
        pumps.scan()
        assert pumps.pump1_run is False

    def test_alternation_equalizes_hours(self, pumps):
        # Run pump 1 for a while
        pumps.level_hi = True
        pumps.scan(n=100)
        assert pumps.pump1_run is True
        assert pumps.pump1_hours == 100

        # Stop
        pumps.level_hi = False
        pumps.level_lo = True
        pumps.scan()

        # Next cycle — pump 2 should be lead (fewer hours)
        pumps.level_lo = False
        pumps.level_hi = True
        pumps.scan()
        assert pumps.pump2_run is True
        assert pumps.pump1_run is False
        assert pumps.lead_pump == 2

    def test_failover_on_fault(self, pumps):
        pumps.level_hi = True
        pumps.scan()
        assert pumps.pump1_run is True

        # Pump 1 faults
        pumps.pump1_fault = True
        pumps.scan()
        assert pumps.pump1_run is False
        assert pumps.pump2_run is True  # Failover

    def test_hihi_runs_both(self, pumps):
        pumps.level_hi = True
        pumps.level_hihi = True
        pumps.scan()
        assert pumps.pump1_run is True
        assert pumps.pump2_run is True

    def test_both_faulted_alarm(self, pumps):
        pumps.pump1_fault = True
        pumps.pump2_fault = True
        pumps.scan()
        assert pumps.alarm is True

    def test_single_fault_no_alarm(self, pumps):
        pumps.pump1_fault = True
        pumps.scan()
        assert pumps.alarm is False


# ==========================================================================
# Program 8: Packaging Line Counter with Reject Station
#
# Counts good and bad products on a packaging line.
# Every Nth product (configurable) triggers an inspection.
# If inspection fails, the reject gate fires.
# Tracks production stats: total, good, rejected, reject rate.
# ==========================================================================


@struct
class ProductionStats:
    total: DINT = 0
    good: DINT = 0
    rejected: DINT = 0
    reject_rate: REAL = 0.0


@fb
class PackagingLine:
    """Packaging line with sampling inspection and reject station."""

    # Inputs
    product_sensor: Input[BOOL]  # Rising edge = product detected
    inspection_pass: Input[BOOL]
    inspection_done: Input[BOOL]  # Rising edge = result ready
    enable: Input[BOOL]
    reset_stats: Input[BOOL]

    # Configuration
    sample_interval: Input[INT] = 10  # Inspect every Nth product

    # Outputs
    reject_gate: Output[BOOL]  # Pulse to reject
    inspect_trigger: Output[BOOL]  # Tell inspection station to check
    total_count: Output[DINT]
    good_count: Output[DINT]
    rejected_count: Output[DINT]

    # Internals
    since_last_inspect: INT = 0
    awaiting_result: BOOL
    reject_pulse_timer: DINT = 0

    def logic(self):
        # Reset statistics
        if self.reset_stats:
            self.total_count = 0
            self.good_count = 0
            self.rejected_count = 0
            self.since_last_inspect = 0

        if not self.enable:
            self.reject_gate = False
            self.inspect_trigger = False
            return

        # Product detected
        if rising(self.product_sensor):
            self.total_count = self.total_count + 1
            self.since_last_inspect = self.since_last_inspect + 1

            # Time to inspect?
            if self.since_last_inspect >= self.sample_interval:
                self.inspect_trigger = True
                self.awaiting_result = True
                self.since_last_inspect = 0
            else:
                self.good_count = self.good_count + 1

        # Inspection result
        if rising(self.inspection_done):
            self.inspect_trigger = False
            self.awaiting_result = False

            if self.inspection_pass:
                self.good_count = self.good_count + 1
            else:
                self.rejected_count = self.rejected_count + 1
                self.reject_pulse_timer = 30  # Fire gate for 30 scans

        # Reject gate pulse
        if self.reject_pulse_timer > 0:
            self.reject_gate = True
            self.reject_pulse_timer = self.reject_pulse_timer - 1
        else:
            self.reject_gate = False


class TestPackagingLine:
    @pytest.fixture
    def line(self):
        ctx = simulate(PackagingLine, data_types=[ProductionStats])
        ctx.enable = True
        ctx.scan()
        return ctx

    def _pulse_product(self, ctx):
        """Simulate a product passing the sensor."""
        ctx.product_sensor = True
        ctx.scan()
        ctx.product_sensor = False
        ctx.scan()

    def test_counts_products(self, line):
        for _ in range(5):
            self._pulse_product(line)
        assert line.total_count == 5

    def test_first_nine_are_good(self, line):
        """With sample_interval=10, first 9 products go straight through."""
        line.sample_interval = 10
        for _ in range(9):
            self._pulse_product(line)
        assert line.total_count == 9
        assert line.good_count == 9

    def test_tenth_triggers_inspection(self, line):
        line.sample_interval = 10
        for _ in range(10):
            self._pulse_product(line)
        assert line.total_count == 10
        assert line.inspect_trigger is True
        assert line.awaiting_result is True

    def test_inspection_pass(self, line):
        line.sample_interval = 5
        for _ in range(5):
            self._pulse_product(line)
        assert line.inspect_trigger is True

        # Inspection passes
        line.inspection_pass = True
        line.inspection_done = True
        line.scan()
        assert line.good_count == 5  # 4 auto-good + 1 inspected good

    def test_inspection_fail_fires_reject(self, line):
        line.sample_interval = 5
        for _ in range(5):
            self._pulse_product(line)

        # Inspection fails
        line.inspection_pass = False
        line.inspection_done = True
        line.scan()
        assert line.rejected_count == 1
        assert line.reject_gate is True

        # Gate stays open: timer set to 30, each scan checks timer>0 THEN decrements.
        # So gate is True for 30 scans, then False on scan 31.
        line.inspection_done = False
        line.scan(n=29)
        assert line.reject_gate is True  # 30 total scans, timer now 0
        line.scan()
        assert line.reject_gate is False  # Timer was 0, gate off

    def test_reset_clears_stats(self, line):
        for _ in range(5):
            self._pulse_product(line)
        assert line.total_count == 5

        line.reset_stats = True
        line.scan()
        assert line.total_count == 0
        assert line.good_count == 0
        assert line.rejected_count == 0


# ==========================================================================
# Program 9: HVAC Zone Controller
#
# Controls heating and cooling for a building zone.
# - Heating and cooling are mutually exclusive
# - Deadband prevents rapid switching
# - Fan runs whenever heating or cooling, plus a coast-down period
# - Occupied/unoccupied setpoints
# ==========================================================================


@fb
class HVACZone:
    """Single-zone HVAC with heating, cooling, and occupancy modes."""

    # Inputs
    zone_temp: Input[REAL]
    occupied: Input[BOOL]
    enable: Input[BOOL]

    # Setpoints
    heat_sp_occ: Input[REAL] = 70.0  # Occupied heating setpoint (F)
    cool_sp_occ: Input[REAL] = 75.0  # Occupied cooling setpoint
    heat_sp_unocc: Input[REAL] = 60.0  # Unoccupied heating setpoint
    cool_sp_unocc: Input[REAL] = 85.0  # Unoccupied cooling setpoint
    deadband: Input[REAL] = 2.0

    # Outputs
    heating: Output[BOOL]
    cooling: Output[BOOL]
    fan: Output[BOOL]
    active_heat_sp: Output[REAL]
    active_cool_sp: Output[REAL]
    mode: Output[INT]  # 0=off, 1=heating, 2=cooling

    # Internals
    fan_coast_timer: DINT = 0

    def logic(self):
        # Select setpoints based on occupancy
        if self.occupied:
            self.active_heat_sp = self.heat_sp_occ
            self.active_cool_sp = self.cool_sp_occ
        else:
            self.active_heat_sp = self.heat_sp_unocc
            self.active_cool_sp = self.cool_sp_unocc

        if not self.enable:
            self.heating = False
            self.cooling = False
            self.fan = False
            self.mode = 0
            return

        # Heating logic: start when below (setpoint - deadband), stop at setpoint
        if self.zone_temp < self.active_heat_sp - self.deadband:
            self.heating = True
            self.cooling = False
            self.mode = 1
        elif self.zone_temp >= self.active_heat_sp:
            if self.heating:
                self.heating = False
                if self.zone_temp < self.active_cool_sp - self.deadband:
                    self.mode = 0

        # Cooling logic: start when above (setpoint + deadband), stop at setpoint
        if self.zone_temp > self.active_cool_sp + self.deadband:
            self.cooling = True
            self.heating = False
            self.mode = 2
        elif self.zone_temp <= self.active_cool_sp:
            if self.cooling:
                self.cooling = False
                if self.zone_temp > self.active_heat_sp:
                    self.mode = 0

        # Fan: on during heating/cooling, coast 30s (3000 scans) after
        if self.heating or self.cooling:
            self.fan = True
            self.fan_coast_timer = 3000
        elif self.fan_coast_timer > 0:
            self.fan = True
            self.fan_coast_timer = self.fan_coast_timer - 1
        else:
            self.fan = False


class TestHVACZone:
    @pytest.fixture
    def hvac(self):
        ctx = simulate(HVACZone)
        ctx.enable = True
        ctx.occupied = True
        return ctx

    def test_comfortable_no_action(self, hvac):
        hvac.zone_temp = 72.0  # Between 70 and 75
        hvac.scan()
        assert hvac.heating is False
        assert hvac.cooling is False

    def test_cold_zone_heats(self, hvac):
        hvac.zone_temp = 65.0  # Below 70 - 2 = 68
        hvac.scan()
        assert hvac.heating is True
        assert hvac.cooling is False
        assert hvac.mode == 1

    def test_hot_zone_cools(self, hvac):
        hvac.zone_temp = 80.0  # Above 75 + 2 = 77
        hvac.scan()
        assert hvac.cooling is True
        assert hvac.heating is False
        assert hvac.mode == 2

    def test_heating_stops_at_setpoint(self, hvac):
        hvac.zone_temp = 65.0
        hvac.scan()
        assert hvac.heating is True

        hvac.zone_temp = 70.0  # Reached setpoint
        hvac.scan()
        assert hvac.heating is False

    def test_deadband_prevents_hunting(self, hvac):
        hvac.deadband = 2.0

        # Just above heating deadband — no heating
        hvac.zone_temp = 69.0  # Below SP (70) but above (70-2)=68
        hvac.scan()
        assert hvac.heating is False

        # Below deadband — heating starts
        hvac.zone_temp = 67.0
        hvac.scan()
        assert hvac.heating is True

    def test_unoccupied_wider_band(self, hvac):
        hvac.occupied = False
        hvac.scan()

        # Unoccupied: heat=60, cool=85
        hvac.zone_temp = 62.0  # Above 60-2=58 — no heating needed
        hvac.scan()
        assert hvac.heating is False

        hvac.zone_temp = 55.0  # Below 58 — heat
        hvac.scan()
        assert hvac.heating is True

    def test_fan_coast_down(self, hvac):
        # Heat up
        hvac.zone_temp = 65.0
        hvac.scan()
        assert hvac.fan is True

        # Temperature reaches setpoint, heating stops
        hvac.zone_temp = 70.0
        hvac.scan()
        assert hvac.heating is False
        assert hvac.fan is True  # Still coasting

        # After 30 seconds of coast
        hvac.scan(n=3000)
        assert hvac.fan is False

    def test_mutual_exclusion(self, hvac):
        """Heating and cooling can never be on simultaneously."""
        hvac.zone_temp = 65.0
        hvac.scan()
        assert hvac.heating is True
        assert hvac.cooling is False

        hvac.zone_temp = 80.0
        hvac.scan()
        assert hvac.cooling is True
        assert hvac.heating is False

    def test_disabled_turns_everything_off(self, hvac):
        hvac.zone_temp = 65.0
        hvac.scan()
        assert hvac.heating is True

        hvac.enable = False
        hvac.scan()
        assert hvac.heating is False
        assert hvac.cooling is False
        assert hvac.fan is False


# ==========================================================================
# Program 10: Garage Door Opener
#
# Single-button toggle (press to open, press to stop, press to close).
# Photo-eye safety reversal during close.
# Auto-close after 5 minutes open.
# Light turns on for 4.5 minutes after any operation.
# ==========================================================================


@fb
class GarageDoor:
    """Residential garage door opener with safety features."""

    # Inputs
    button: Input[BOOL]
    photo_eye: Input[BOOL]  # True = beam broken (obstruction)
    limit_open: Input[BOOL]
    limit_closed: Input[BOOL]

    # Outputs
    motor_up: Output[BOOL]
    motor_down: Output[BOOL]
    light: Output[BOOL]

    # Internals
    state: INT = 0
    # 0=closed, 1=opening, 2=open, 3=closing, 4=stopped_opening, 5=stopped_closing
    open_timer: DINT = 0
    light_timer: DINT = 0
    prev_button: BOOL

    def logic(self):
        # Edge detect on button (manual rising edge)
        button_press: BOOL = self.button and not self.prev_button
        self.prev_button = self.button

        # Light timer — on for 4.5 minutes (27000 scans at 10ms)
        if button_press:
            self.light_timer = 27000

        if self.light_timer > 0:
            self.light = True
            self.light_timer = self.light_timer - 1
        else:
            self.light = False

        match self.state:
            case 0:
                # CLOSED
                self.motor_up = False
                self.motor_down = False
                self.open_timer = 0

                if button_press:
                    self.state = 1

            case 1:
                # OPENING
                self.motor_up = True
                self.motor_down = False

                if self.limit_open:
                    self.state = 2

                if button_press:
                    self.state = 4  # Stop

            case 2:
                # OPEN
                self.motor_up = False
                self.motor_down = False
                self.open_timer = self.open_timer + 1

                # Auto-close after 5 minutes (30000 scans)
                if self.open_timer >= 30000:
                    self.state = 3
                    self.light_timer = 27000  # Turn light on

                if button_press:
                    self.state = 3

            case 3:
                # CLOSING
                self.motor_up = False
                self.motor_down = True

                # Safety reversal
                if self.photo_eye:
                    self.state = 1  # Reverse to opening

                if self.limit_closed:
                    self.state = 0

                if button_press:
                    self.state = 5  # Stop

            case 4:
                # STOPPED while opening
                self.motor_up = False
                self.motor_down = False

                if button_press:
                    self.state = 3  # Close

            case 5:
                # STOPPED while closing
                self.motor_up = False
                self.motor_down = False

                if button_press:
                    self.state = 1  # Open


class TestGarageDoor:
    @pytest.fixture
    def door(self):
        ctx = simulate(GarageDoor)
        ctx.limit_closed = True
        ctx.scan()
        return ctx

    def test_starts_closed(self, door):
        assert door.motor_up is False
        assert door.motor_down is False

    def test_button_opens(self, door):
        door.button = True
        door.limit_closed = False
        door.scan()  # 0→1 (button_press detected, state changes)
        door.scan()  # Case 1 runs: motor_up=True
        assert door.motor_up is True

        door.button = False
        door.scan()
        assert door.motor_up is True  # Still opening

    def test_stops_at_limit(self, door):
        door.button = True
        door.limit_closed = False
        door.scan()  # 0→1
        door.button = False
        door.scan()  # Case 1: opening
        door.limit_open = True
        door.scan()  # 1→2
        door.scan()  # Case 2
        assert door.motor_up is False
        assert door.state == 2  # OPEN

    def test_button_closes_when_open(self, door):
        # Open the door
        door.button = True
        door.limit_closed = False
        door.scan()  # 0→1
        door.button = False
        door.limit_open = True
        door.scan()  # Case 1: opening
        door.scan()  # 1→2
        door.scan()  # Case 2: open

        # Press button to close
        door.button = True
        door.limit_open = False
        door.scan()  # 2→3
        door.button = False
        door.scan()  # Case 3: closing
        assert door.motor_down is True

    def test_photo_eye_reversal(self, door):
        # Open the door
        door.button = True
        door.limit_closed = False
        door.scan()  # 0→1
        door.button = False
        door.limit_open = True
        door.scan()  # Case 1
        door.scan()  # 1→2
        door.scan()  # Case 2

        # Start closing
        door.button = True
        door.limit_open = False
        door.scan()  # 2→3
        door.button = False
        door.scan()  # Case 3: closing
        assert door.motor_down is True

        # Photo-eye triggers reversal
        door.photo_eye = True
        door.scan()  # 3→1
        door.scan()  # Case 1: opening
        assert door.motor_down is False
        assert door.motor_up is True

    def test_button_stops_during_open(self, door):
        door.button = True
        door.limit_closed = False
        door.scan()  # 0→1
        door.button = False
        door.scan()  # Case 1: opening
        assert door.motor_up is True

        # Press again to stop
        door.button = True
        door.scan()  # 1→4 (button_press in case 1)
        door.button = False
        door.scan()  # Case 4: stopped
        assert door.motor_up is False
        assert door.state == 4

    def test_auto_close_after_5_minutes(self, door):
        # Open the door
        door.button = True
        door.limit_closed = False
        door.scan()  # 0→1
        door.button = False
        door.limit_open = True
        door.scan()  # Case 1: opening
        door.scan()  # 1→2
        door.limit_open = False
        door.scan()  # Case 2: open, timer starts

        # Wait 5 minutes (30000 ticks, timer already at 1)
        door.scan(n=29999)
        assert door.state == 3  # Auto-closing
        door.scan()  # Case 3
        assert door.motor_down is True

    def test_light_on_for_4_5_minutes(self, door):
        door.button = True
        door.limit_closed = False
        door.scan()  # button_press sets light_timer=27000
        assert door.light is True

        door.button = False
        # Light timer: set to 27000, then check>0 (True, light on), decrement.
        # After scan 1: timer=26999, light=True.
        # Light stays on for 27000 scans total, then off on scan 27001.
        door.scan(n=26999)
        assert door.light is True  # 27000 total, timer now 0
        door.scan()
        assert door.light is False  # Timer 0, light off


# ==========================================================================
# Verify they all compile into a valid project
# ==========================================================================


class TestProjectAssembly:
    def test_all_programs_compile(self):
        """Every POU defined here compiles into a valid project IR."""

        # Tasks require @program POUs — wrap top-level FBs as programs
        @program
        class SortingMain:
            sys: SortingSystem

            def logic(self):
                self.sys()

        @program
        class ProcessMain:
            tank: TankLevelControl
            hvac: HVACZone

            def logic(self):
                self.tank()
                self.hvac()

        prj = project(
            "RealWorldPrograms",
            pous=[
                ConveyorDrive,
                DiverterGate,
                SortingSystem,
                TankLevelControl,
                StarDeltaStarter,
                ElevatorDoor,
                PumpAlternation,
                PackagingLine,
                HVACZone,
                GarageDoor,
                TrafficLightController,
                BatchMixer,
                SortingMain,
                ProcessMain,
            ],
            data_types=[ConveyorStatus, ProductionStats],
            tasks=[
                task(
                    "FastScan",
                    periodic=timedelta(milliseconds=10),
                    pous=[SortingMain],
                    priority=1,
                ),
                task(
                    "SlowScan",
                    periodic=timedelta(milliseconds=100),
                    pous=[ProcessMain],
                    priority=5,
                ),
            ],
        ).compile()

        # Basic sanity checks on the compiled project
        assert len(prj.pous) >= 10
        assert len(prj.tasks) == 2
        assert len(prj.data_types) == 2

        # Verify POU names exist
        pou_names = {p.name for p in prj.pous}
        assert "SortingSystem" in pou_names
        assert "TankLevelControl" in pou_names
        assert "StarDeltaStarter" in pou_names
        assert "ElevatorDoor" in pou_names
        assert "GarageDoor" in pou_names
        assert "TrafficLightController" in pou_names
        assert "BatchMixer" in pou_names

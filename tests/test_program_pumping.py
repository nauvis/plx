"""Water/Wastewater Pumping Station — exercises @function with -> REAL,
@global_vars with address mapping, rising() for pump cycle detection,
delayed() for fail-to-start, and 4-level alarm with hysteresis.

~35 I/O: 12 DI, 3 DO, 5 AI, 3 AO across 3 VFD pumps + level control.
"""

import pytest

from datetime import timedelta

from plx.framework import (
    BOOL,
    DINT,
    INT,
    REAL,
    delayed,
    fb,
    function,
    global_vars,
    Input,
    Output,
    program,
    project,
    rising,
    struct,
    task,
)
from plx.simulate import simulate


# ==========================================================================
# Data Types
# ==========================================================================


@struct
class PumpStatus:
    running: BOOL = False
    faulted: BOOL = False
    speed_ref: REAL = 0.0
    run_hours: DINT = 0
    current: REAL = 0.0


@struct
class AlarmThresholds:
    hihi: REAL = 95.0
    hi: REAL = 85.0
    lo: REAL = 15.0
    lolo: REAL = 5.0


# ==========================================================================
# Utility function
# ==========================================================================


@function
class Clamp:
    """Clamp a value between lo and hi bounds."""

    value: Input[REAL]
    lo: Input[REAL] = 0.0
    hi: Input[REAL] = 100.0

    def logic(self) -> REAL:
        if self.value > self.hi:
            return self.hi
        if self.value < self.lo:
            return self.lo
        return self.value


# ==========================================================================
# Global Variables (I/O address mapping)
# ==========================================================================


@global_vars(description="Pump Station I/O")
class PumpStationIO:
    wet_well_level: REAL
    pump1_speed_ref: REAL
    pump2_speed_ref: REAL
    pump3_speed_ref: REAL
    pump1_run_fb: BOOL
    pump2_run_fb: BOOL
    pump3_run_fb: BOOL
    pump1_run_cmd: BOOL
    pump2_run_cmd: BOOL
    pump3_run_cmd: BOOL
    pump1_fault: BOOL
    pump2_fault: BOOL
    pump3_fault: BOOL
    e_stop: BOOL
    alarm_horn: BOOL
    alarm_beacon: BOOL


# ==========================================================================
# Function Blocks
# ==========================================================================


@fb
class AlarmBlock:
    """4-level alarm (HH/H/L/LL) with hysteresis and priority output."""

    pv: Input[REAL]
    hihi_sp: Input[REAL] = 95.0
    hi_sp: Input[REAL] = 85.0
    lo_sp: Input[REAL] = 15.0
    lolo_sp: Input[REAL] = 5.0
    hysteresis: Input[REAL] = 2.0

    hihi: Output[BOOL]
    hi: Output[BOOL]
    lo: Output[BOOL]
    lolo: Output[BOOL]
    priority: Output[INT]  # 0=normal, 1=lo, 2=hi, 3=lolo, 4=hihi

    def logic(self):
        # HiHi — trips on rising, resets with hysteresis
        if self.pv >= self.hihi_sp:
            self.hihi = True
        elif self.pv < self.hihi_sp - self.hysteresis:
            self.hihi = False

        # Hi
        if self.pv >= self.hi_sp:
            self.hi = True
        elif self.pv < self.hi_sp - self.hysteresis:
            self.hi = False

        # Lo
        if self.pv <= self.lo_sp:
            self.lo = True
        elif self.pv > self.lo_sp + self.hysteresis:
            self.lo = False

        # LoLo
        if self.pv <= self.lolo_sp:
            self.lolo = True
        elif self.pv > self.lolo_sp + self.hysteresis:
            self.lolo = False

        # Priority (highest severity wins)
        if self.hihi:
            self.priority = 4
        elif self.lolo:
            self.priority = 3
        elif self.hi:
            self.priority = 2
        elif self.lo:
            self.priority = 1
        else:
            self.priority = 0


@fb
class PumpController:
    """Single pump: VFD speed control, fault latch, fail-to-start, e-stop."""

    run_cmd: Input[BOOL]
    speed_cmd: Input[REAL]
    run_feedback: Input[BOOL]
    fault_input: Input[BOOL]
    e_stop: Input[BOOL] = True  # NC contact
    reset_cmd: Input[BOOL]

    run_output: Output[BOOL]
    speed_output: Output[REAL]
    running: Output[BOOL]
    faulted: Output[BOOL]
    run_hours: Output[DINT]

    fault_latched: BOOL

    def logic(self):
        # E-stop interlock
        if not self.e_stop:
            self.run_output = False
            self.speed_output = 0.0
            self.running = False
            self.faulted = self.fault_latched
            return

        # Fault latch
        if self.fault_input:
            self.fault_latched = True
        if self.reset_cmd and not self.fault_input:
            self.fault_latched = False

        self.faulted = self.fault_latched

        # Run command (blocked by fault)
        if self.run_cmd and not self.faulted:
            self.run_output = True
            self.speed_output = self.speed_cmd
        else:
            self.run_output = False
            self.speed_output = 0.0

        self.running = self.run_output and self.run_feedback

        # Fail-to-start: commanded on but no feedback within 5 seconds
        waiting: BOOL = self.run_output and not self.run_feedback
        fail_detected: BOOL = delayed(waiting, timedelta(seconds=5))
        if fail_detected:
            self.fault_latched = True

        # Run hours (each scan while running = 10ms)
        if self.running:
            self.run_hours = self.run_hours + 1


@fb
class LevelController:
    """Level-to-speed proportional control with pump staging."""

    level: Input[REAL]  # 0-100%

    # Staging setpoints
    stage1_sp: Input[REAL] = 40.0
    stage2_sp: Input[REAL] = 60.0
    stage3_sp: Input[REAL] = 80.0
    stop_sp: Input[REAL] = 20.0

    # Outputs
    num_pumps: Output[INT]  # 0-3
    speed_cmd: Output[REAL]  # 0-100%

    gain: REAL = 3.0

    def logic(self):
        # Determine number of pumps needed
        if self.level >= self.stage3_sp:
            self.num_pumps = 3
        elif self.level >= self.stage2_sp:
            self.num_pumps = 2
        elif self.level >= self.stage1_sp:
            self.num_pumps = 1
        elif self.level <= self.stop_sp:
            self.num_pumps = 0

        # Speed proportional to level above stop point
        if self.num_pumps > 0:
            error: REAL = self.level - self.stop_sp
            self.speed_cmd = error * self.gain
            if self.speed_cmd > 100.0:
                self.speed_cmd = 100.0
            if self.speed_cmd < 20.0:
                self.speed_cmd = 20.0  # VFD minimum speed
        else:
            self.speed_cmd = 0.0


@fb
class LeadLagSelector:
    """Pump rotation by run hours — selects lead/lag/standby on new cycle."""

    recalc: Input[BOOL]  # Rising edge triggers recalculation
    pump1_hours: Input[DINT]
    pump2_hours: Input[DINT]
    pump3_hours: Input[DINT]
    pump1_available: Input[BOOL] = True
    pump2_available: Input[BOOL] = True
    pump3_available: Input[BOOL] = True

    lead: Output[INT] = 1  # Pump number: 1, 2, or 3
    lag1: Output[INT] = 2
    lag2: Output[INT] = 3

    def logic(self):
        if rising(self.recalc):
            # Select lead: available pump with fewest run hours
            best: INT = 0
            best_hours: DINT = 999999999

            if self.pump1_available:
                if self.pump1_hours < best_hours:
                    best = 1
                    best_hours = self.pump1_hours

            if self.pump2_available:
                if self.pump2_hours < best_hours:
                    best = 2
                    best_hours = self.pump2_hours

            if self.pump3_available:
                if self.pump3_hours < best_hours:
                    best = 3

            if best > 0:
                self.lead = best

            # Assign lag positions (round-robin after lead)
            if self.lead == 1:
                self.lag1 = 2
                self.lag2 = 3
            elif self.lead == 2:
                self.lag1 = 1
                self.lag2 = 3
            else:
                self.lag1 = 1
                self.lag2 = 2


# ==========================================================================
# Top-level program
# ==========================================================================


@program
class PumpStation:
    """3-pump wet well pumping station with level control and alarms."""

    # Inputs
    wet_well_level: Input[REAL]
    pump1_run_fb: Input[BOOL]
    pump2_run_fb: Input[BOOL]
    pump3_run_fb: Input[BOOL]
    pump1_fault: Input[BOOL]
    pump2_fault: Input[BOOL]
    pump3_fault: Input[BOOL]
    e_stop: Input[BOOL] = True
    reset: Input[BOOL]
    alarm_ack: Input[BOOL]

    # Outputs
    pump1_run_cmd: Output[BOOL]
    pump2_run_cmd: Output[BOOL]
    pump3_run_cmd: Output[BOOL]
    pump1_speed: Output[REAL]
    pump2_speed: Output[REAL]
    pump3_speed: Output[REAL]
    alarm_horn: Output[BOOL]
    alarm_beacon: Output[BOOL]
    hihi_alarm: Output[BOOL]

    # Internal FBs
    pump1: PumpController
    pump2: PumpController
    pump3: PumpController
    level_ctrl: LevelController
    selector: LeadLagSelector
    level_alarm: AlarmBlock

    # Internal state
    cycle_start: BOOL
    prev_num_pumps: INT

    def logic(self):
        # Level controller — determine pump staging and speed
        self.level_ctrl(level=self.wet_well_level)

        # Detect new pump cycle start (0 → >0 pumps)
        self.cycle_start = self.level_ctrl.num_pumps > 0 and self.prev_num_pumps == 0
        self.prev_num_pumps = self.level_ctrl.num_pumps

        # Lead/lag selection (recalculates on cycle start rising edge)
        self.selector(
            recalc=self.cycle_start,
            pump1_hours=self.pump1.run_hours,
            pump2_hours=self.pump2.run_hours,
            pump3_hours=self.pump3.run_hours,
            pump1_available=not self.pump1.faulted,
            pump2_available=not self.pump2.faulted,
            pump3_available=not self.pump3.faulted,
        )

        # Map selector → pump commands based on staging
        lead_run: BOOL = self.level_ctrl.num_pumps >= 1
        lag1_run: BOOL = self.level_ctrl.num_pumps >= 2
        lag2_run: BOOL = self.level_ctrl.num_pumps >= 3

        p1_cmd: BOOL = False
        p2_cmd: BOOL = False
        p3_cmd: BOOL = False

        # Lead pump
        if self.selector.lead == 1:
            p1_cmd = lead_run
        elif self.selector.lead == 2:
            p2_cmd = lead_run
        else:
            p3_cmd = lead_run

        # Lag 1
        if lag1_run:
            if self.selector.lag1 == 1:
                p1_cmd = True
            elif self.selector.lag1 == 2:
                p2_cmd = True
            else:
                p3_cmd = True

        # Lag 2
        if lag2_run:
            if self.selector.lag2 == 1:
                p1_cmd = True
            elif self.selector.lag2 == 2:
                p2_cmd = True
            else:
                p3_cmd = True

        # Pump controllers
        self.pump1(
            run_cmd=p1_cmd,
            speed_cmd=self.level_ctrl.speed_cmd,
            run_feedback=self.pump1_run_fb,
            fault_input=self.pump1_fault,
            e_stop=self.e_stop,
            reset_cmd=self.reset,
        )
        self.pump1_run_cmd = self.pump1.run_output
        self.pump1_speed = self.pump1.speed_output

        self.pump2(
            run_cmd=p2_cmd,
            speed_cmd=self.level_ctrl.speed_cmd,
            run_feedback=self.pump2_run_fb,
            fault_input=self.pump2_fault,
            e_stop=self.e_stop,
            reset_cmd=self.reset,
        )
        self.pump2_run_cmd = self.pump2.run_output
        self.pump2_speed = self.pump2.speed_output

        self.pump3(
            run_cmd=p3_cmd,
            speed_cmd=self.level_ctrl.speed_cmd,
            run_feedback=self.pump3_run_fb,
            fault_input=self.pump3_fault,
            e_stop=self.e_stop,
            reset_cmd=self.reset,
        )
        self.pump3_run_cmd = self.pump3.run_output
        self.pump3_speed = self.pump3.speed_output

        # Level alarms
        self.level_alarm(pv=self.wet_well_level)
        self.hihi_alarm = self.level_alarm.hihi

        # Alarm horn and beacon
        any_alarm: BOOL = (
            self.level_alarm.hihi
            or self.level_alarm.hi
            or self.level_alarm.lo
            or self.level_alarm.lolo
        )
        self.alarm_horn = any_alarm and not self.alarm_ack
        self.alarm_beacon = any_alarm


# ==========================================================================
# Tests
# ==========================================================================


class TestAlarmBlock:
    @pytest.fixture
    def alarm(self):
        return simulate(AlarmBlock)

    def test_normal_no_alarms(self, alarm):
        alarm.pv = 50.0
        alarm.scan()
        assert alarm.hihi is False
        assert alarm.hi is False
        assert alarm.lo is False
        assert alarm.lolo is False
        assert alarm.priority == 0

    def test_hihi_trips_and_resets_with_hysteresis(self, alarm):
        alarm.pv = 96.0  # Above hihi_sp=95
        alarm.scan()
        assert alarm.hihi is True
        assert alarm.priority == 4

        # Drop to 94 — within hysteresis (95 - 2 = 93), stays tripped
        alarm.pv = 94.0
        alarm.scan()
        assert alarm.hihi is True

        # Drop to 92 — below hysteresis band, resets
        alarm.pv = 92.0
        alarm.scan()
        assert alarm.hihi is False

    def test_hi_alarm(self, alarm):
        alarm.pv = 86.0  # Above hi_sp=85
        alarm.scan()
        assert alarm.hi is True
        assert alarm.priority == 2

    def test_lo_alarm(self, alarm):
        alarm.pv = 14.0  # Below lo_sp=15
        alarm.scan()
        assert alarm.lo is True
        assert alarm.priority == 1

    def test_lolo_alarm(self, alarm):
        alarm.pv = 4.0  # Below lolo_sp=5
        alarm.scan()
        assert alarm.lolo is True
        assert alarm.priority == 3  # lolo is higher priority than lo

    def test_lo_hysteresis(self, alarm):
        alarm.pv = 14.0
        alarm.scan()
        assert alarm.lo is True

        # Rise to 16 — within hysteresis (15 + 2 = 17), stays tripped
        alarm.pv = 16.0
        alarm.scan()
        assert alarm.lo is True

        # Rise to 18 — above hysteresis band, resets
        alarm.pv = 18.0
        alarm.scan()
        assert alarm.lo is False


class TestPumpController:
    @pytest.fixture
    def pump(self):
        ctx = simulate(PumpController)
        ctx.e_stop = True
        return ctx

    def test_normal_start(self, pump):
        pump.run_cmd = True
        pump.speed_cmd = 75.0
        pump.run_feedback = True
        pump.scan()
        assert pump.run_output is True
        assert pump.speed_output == pytest.approx(75.0)
        assert pump.running is True

    def test_e_stop_kills_output(self, pump):
        pump.run_cmd = True
        pump.speed_cmd = 75.0
        pump.run_feedback = True
        pump.scan()
        assert pump.run_output is True

        pump.e_stop = False
        pump.scan()
        assert pump.run_output is False
        assert pump.speed_output == pytest.approx(0.0)
        assert pump.running is False

    def test_fault_latch_and_reset(self, pump):
        pump.run_cmd = True
        pump.run_feedback = True
        pump.speed_cmd = 50.0
        pump.scan()
        assert pump.running is True

        # Fault trips
        pump.fault_input = True
        pump.scan()
        assert pump.faulted is True
        assert pump.run_output is False

        # Fault clears but stays latched
        pump.fault_input = False
        pump.scan()
        assert pump.faulted is True

        # Reset clears latch
        pump.reset_cmd = True
        pump.scan()
        assert pump.faulted is False
        assert pump.run_output is True  # run_cmd still True

    def test_fail_to_start(self, pump):
        pump.run_cmd = True
        pump.speed_cmd = 50.0
        pump.run_feedback = False  # No feedback
        pump.scan()
        assert pump.run_output is True

        # Wait 5 seconds — fail-to-start triggers
        pump.tick(seconds=6)
        assert pump.faulted is True
        assert pump.run_output is False

    def test_run_hours_increment(self, pump):
        pump.run_cmd = True
        pump.speed_cmd = 50.0
        pump.run_feedback = True
        pump.scan(n=100)
        assert pump.run_hours == 100

    def test_speed_tracks_command(self, pump):
        pump.run_cmd = True
        pump.run_feedback = True
        pump.speed_cmd = 30.0
        pump.scan()
        assert pump.speed_output == pytest.approx(30.0)

        pump.speed_cmd = 80.0
        pump.scan()
        assert pump.speed_output == pytest.approx(80.0)


class TestLevelController:
    @pytest.fixture
    def lc(self):
        return simulate(LevelController)

    def test_no_pumps_below_stop(self, lc):
        lc.level = 15.0  # Below stop_sp=20
        lc.scan()
        assert lc.num_pumps == 0
        assert lc.speed_cmd == pytest.approx(0.0)

    def test_one_pump_at_stage1(self, lc):
        lc.level = 45.0  # Above stage1_sp=40
        lc.scan()
        assert lc.num_pumps == 1
        # speed = (45-20)*3 = 75
        assert lc.speed_cmd == pytest.approx(75.0)

    def test_two_pumps_at_stage2(self, lc):
        lc.level = 65.0  # Above stage2_sp=60
        lc.scan()
        assert lc.num_pumps == 2

    def test_three_pumps_at_stage3(self, lc):
        lc.level = 85.0  # Above stage3_sp=80
        lc.scan()
        assert lc.num_pumps == 3
        # speed = (85-20)*3 = 195 → clamped to 100
        assert lc.speed_cmd == pytest.approx(100.0)

    def test_minimum_speed(self, lc):
        # First start pumps above stage1
        lc.level = 45.0
        lc.scan()
        assert lc.num_pumps == 1

        # Drop level into hysteresis band — pumps hold, but speed drops
        lc.level = 25.0
        lc.scan()
        # speed = (25-20)*3 = 15 → clamped to minimum 20
        assert lc.num_pumps == 1  # Held from previous
        assert lc.speed_cmd == pytest.approx(20.0)

    def test_hysteresis_between_stop_and_stage1(self, lc):
        # Start with pumps running at stage1
        lc.level = 45.0
        lc.scan()
        assert lc.num_pumps == 1

        # Level drops between stop_sp and stage1_sp — num_pumps holds
        lc.level = 25.0
        lc.scan()
        assert lc.num_pumps == 1  # Held: above stop_sp but below stage1_sp

        # Level drops below stop_sp — pumps off
        lc.level = 19.0
        lc.scan()
        assert lc.num_pumps == 0


class TestLeadLagSelector:
    @pytest.fixture
    def sel(self):
        return simulate(LeadLagSelector)

    def test_default_lead_is_pump1(self, sel):
        sel.scan()
        assert sel.lead == 1
        assert sel.lag1 == 2
        assert sel.lag2 == 3

    def test_rotation_by_hours(self, sel):
        # Pump 1 has most hours → pump 2 should be lead
        sel.pump1_hours = 1000
        sel.pump2_hours = 500
        sel.pump3_hours = 800

        # Trigger recalculation
        sel.recalc = True
        sel.scan()
        sel.recalc = False
        sel.scan()

        assert sel.lead == 2
        assert sel.lag1 == 1
        assert sel.lag2 == 3

    def test_unavailable_pump_skipped(self, sel):
        sel.pump1_hours = 100
        sel.pump2_hours = 200
        sel.pump3_hours = 300
        sel.pump1_available = False  # Pump 1 faulted

        sel.recalc = True
        sel.scan()
        sel.recalc = False
        sel.scan()

        assert sel.lead == 2  # Pump 2 has next fewest hours


class TestPumpStation:
    @pytest.fixture
    def station(self):
        ctx = simulate(
            PumpStation,
            pous=[PumpController, LevelController, LeadLagSelector, AlarmBlock],
            data_types=[PumpStatus, AlarmThresholds],
        )
        ctx.e_stop = True
        return ctx

    def test_pumps_off_at_low_level(self, station):
        station.wet_well_level = 15.0
        station.scan()
        assert station.pump1_run_cmd is False
        assert station.pump2_run_cmd is False
        assert station.pump3_run_cmd is False

    def test_auto_start_on_level_rise(self, station):
        # Level below start threshold
        station.wet_well_level = 15.0
        station.pump1_run_fb = True
        station.pump2_run_fb = True
        station.pump3_run_fb = True
        station.scan()
        assert station.pump1_run_cmd is False

        # Level rises to stage 1
        station.wet_well_level = 45.0
        station.scan()
        # First scan: level_ctrl sets num_pumps=1, cycle_start fires,
        # selector recalc triggers on next scan
        station.scan()
        # Lead pump (pump 1 by default) should be running
        assert station.pump1_run_cmd is True
        assert station.pump2_run_cmd is False

    def test_two_pump_staging(self, station):
        station.pump1_run_fb = True
        station.pump2_run_fb = True
        station.pump3_run_fb = True

        # Start with 1 pump
        station.wet_well_level = 45.0
        station.scan(n=3)
        assert station.pump1_run_cmd is True

        # Level rises to stage 2
        station.wet_well_level = 65.0
        station.scan()
        # Lead + lag1 should run
        assert station.pump1_run_cmd is True
        assert station.pump2_run_cmd is True

    def test_alarm_horn_and_beacon(self, station):
        station.wet_well_level = 96.0  # HiHi alarm
        station.scan()
        assert station.hihi_alarm is True
        assert station.alarm_horn is True
        assert station.alarm_beacon is True

        # ACK silences horn but beacon stays
        station.alarm_ack = True
        station.scan()
        assert station.alarm_horn is False
        assert station.alarm_beacon is True

    def test_e_stop_stops_all_pumps(self, station):
        station.wet_well_level = 45.0
        station.pump1_run_fb = True
        station.scan(n=3)

        station.e_stop = False
        station.scan()
        assert station.pump1_run_cmd is False
        assert station.pump2_run_cmd is False
        assert station.pump3_run_cmd is False


class TestPumpingProjectCompilation:
    def test_project_compiles_with_global_vars_and_function(self):
        @program
        class AlarmProgram:
            def logic(self):
                pass

        prj = project(
            "PumpStationProject",
            pous=[
                Clamp,
                AlarmBlock,
                PumpController,
                LevelController,
                LeadLagSelector,
                PumpStation,
                AlarmProgram,
            ],
            data_types=[PumpStatus, AlarmThresholds],
            global_var_lists=[PumpStationIO],
            tasks=[
                task(
                    "FastControl",
                    periodic=timedelta(milliseconds=10),
                    pous=[PumpStation],
                    priority=1,
                ),
                task(
                    "AlarmScan",
                    periodic=timedelta(milliseconds=500),
                    pous=[AlarmProgram],
                    priority=5,
                ),
            ],
        ).compile()

        assert len(prj.pous) >= 6
        assert len(prj.tasks) == 2
        assert len(prj.data_types) == 2
        assert len(prj.global_variable_lists) == 1

        # Verify Clamp is a FUNCTION with return type
        pou_map = {p.name: p for p in prj.pous}
        clamp_pou = pou_map["Clamp"]
        assert clamp_pou.pou_type.value == "FUNCTION"
        assert clamp_pou.return_type is not None

        # Verify global vars compiled
        gvl = prj.global_variable_lists[0]
        assert len(gvl.variables) >= 10

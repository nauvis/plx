"""Multi-Zone HVAC System — exercises 3-level FB inheritance, @fb_method(access=PROTECTED),
sustained() for fan coast-down, and first_scan() for initialization.

~45 I/O: 9 DI, 3 DO, 18 AI, 9 AO across 3 zones + central plant.
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
    first_scan,
    Input,
    fb_method,
    Output,
    program,
    project,
    struct,
    sustained,
    task,
    Field,
)
from plx.model.pou import AccessSpecifier
from plx.simulate import simulate


# ==========================================================================
# Data Types
# ==========================================================================


@struct
class ZoneConfig:
    heat_sp_occ: REAL = 72.0
    cool_sp_occ: REAL = 76.0
    heat_sp_unocc: REAL = 62.0
    cool_sp_unocc: REAL = 82.0
    deadband: REAL = 1.0
    warmup_sp: REAL = 68.0


@struct
class ZoneStatus:
    heating: BOOL = False
    cooling: BOOL = False
    heat_valve: REAL = 0.0
    cool_valve: REAL = 0.0
    damper_pos: REAL = 0.0
    mode: INT = 0


# ==========================================================================
# FB Hierarchy — 3-level inheritance chain
# ==========================================================================


@fb
class BaseZoneController:
    """Proportional heat/cool demand from temperature vs. setpoint + deadband.

    Level 1 of the 3-level inheritance chain.
    """

    # Inputs
    zone_temp: Input[REAL]
    heat_sp: Input[REAL] = 72.0
    cool_sp: Input[REAL] = 76.0
    deadband: Input[REAL] = 1.0
    enable: Input[BOOL] = True

    # Outputs
    heat_demand: Output[REAL]  # 0-100%
    cool_demand: Output[REAL]  # 0-100%

    # Internals
    gain: REAL = 5.0

    @fb_method(access=AccessSpecifier.PROTECTED)
    def compute_demand(self, error: REAL) -> REAL:
        """Proportional demand: error * gain, clamped 0-100."""
        result: REAL = error * self.gain
        if result > 100.0:
            result = 100.0
        if result < 0.0:
            result = 0.0
        return result

    def logic(self):
        if not self.enable:
            self.heat_demand = 0.0
            self.cool_demand = 0.0
            return

        # Heating demand: proportional when temp below (heat_sp - deadband)
        heat_error: REAL = self.heat_sp - self.zone_temp
        if heat_error > self.deadband:
            self.heat_demand = heat_error * self.gain
            if self.heat_demand > 100.0:
                self.heat_demand = 100.0
        else:
            self.heat_demand = 0.0

        # Cooling demand: proportional when temp above (cool_sp + deadband)
        cool_error: REAL = self.zone_temp - self.cool_sp
        if cool_error > self.deadband:
            self.cool_demand = cool_error * self.gain
            if self.cool_demand > 100.0:
                self.cool_demand = 100.0
        else:
            self.cool_demand = 0.0


@fb
class OccupancyZoneController(BaseZoneController):
    """Adds occupied/unoccupied setpoint selection.

    Level 2 of the 3-level inheritance chain. Selects the appropriate
    setpoints based on occupancy, then delegates to BaseZoneController.
    """

    occupied: Input[BOOL] = True
    heat_sp_occ: Input[REAL] = 72.0
    cool_sp_occ: Input[REAL] = 76.0
    heat_sp_unocc: Input[REAL] = 62.0
    cool_sp_unocc: Input[REAL] = 82.0

    def logic(self):
        # Select setpoints based on occupancy
        if self.occupied:
            self.heat_sp = self.heat_sp_occ
            self.cool_sp = self.cool_sp_occ
        else:
            self.heat_sp = self.heat_sp_unocc
            self.cool_sp = self.cool_sp_unocc

        super().logic()


@fb
class FullZoneController(OccupancyZoneController):
    """Adds window interlock, morning warmup, damper control, fan coast-down.

    Level 3 of the 3-level inheritance chain. Post-processes the demands
    computed by the parent chain.
    """

    window_open: Input[BOOL]
    morning_warmup: Input[BOOL]
    warmup_sp: Input[REAL] = 68.0

    damper_pos: Output[REAL]
    fan_running: Output[BOOL]

    def logic(self):
        # Run parent chain first (occupancy selection + proportional control)
        super().logic()

        # Window interlock — kill all demand when window is open
        if self.window_open:
            self.heat_demand = 0.0
            self.cool_demand = 0.0

        # Morning warmup override — force max heating below warmup setpoint
        if self.morning_warmup:
            if self.zone_temp < self.warmup_sp:
                self.heat_demand = 100.0
                self.cool_demand = 0.0

        # Damper position — proportional to the larger demand
        if self.heat_demand > self.cool_demand:
            self.damper_pos = self.heat_demand
        else:
            self.damper_pos = self.cool_demand

        # Fan coast-down: fan runs while demand exists, plus 30s after
        any_demand: BOOL = self.heat_demand > 0.0 or self.cool_demand > 0.0
        self.fan_running = sustained(any_demand, timedelta(seconds=30))


# ==========================================================================
# Standalone FBs
# ==========================================================================


@fb
class EconomizerController:
    """Outdoor air economizer — free cooling when outdoor temp < return air."""

    outdoor_temp: Input[REAL]
    return_air_temp: Input[REAL]
    mixed_air_sp: Input[REAL] = 55.0
    mixed_air_temp: Input[REAL]
    enable: Input[BOOL] = True
    min_damper: Input[REAL] = 10.0

    damper_cmd: Output[REAL]  # 0-100%
    free_cooling: Output[BOOL]

    gain: REAL = 5.0

    def logic(self):
        if not self.enable:
            self.damper_cmd = self.min_damper
            self.free_cooling = False
            return

        # Free cooling available when outdoor air is cooler than return air
        self.free_cooling = self.outdoor_temp < self.return_air_temp

        if self.free_cooling:
            # Modulate damper to maintain mixed air setpoint
            error: REAL = self.mixed_air_sp - self.mixed_air_temp
            self.damper_cmd = 50.0 + error * self.gain
            if self.damper_cmd > 100.0:
                self.damper_cmd = 100.0
            if self.damper_cmd < self.min_damper:
                self.damper_cmd = self.min_damper
        else:
            self.damper_cmd = self.min_damper


@fb
class FilterAlarm:
    """Filter differential pressure alarm with delayed() debounce and latch."""

    filter_dp: Input[REAL]
    alarm_sp: Input[REAL] = 2.5
    alarm_ack: Input[BOOL]

    alarm: Output[BOOL]
    alarm_latched: Output[BOOL]

    dp_high: BOOL

    def logic(self):
        self.dp_high = self.filter_dp > self.alarm_sp

        # Debounce: DP must be high for 30 continuous seconds
        self.alarm = delayed(self.dp_high, timedelta(seconds=30))

        # Latch alarm until acknowledged (and DP drops)
        if self.alarm:
            self.alarm_latched = True
        if self.alarm_ack and not self.dp_high:
            self.alarm_latched = False


@fb
class CentralPlant:
    """Central plant: chiller, boiler, supply/return fans with outdoor lockouts."""

    max_heat_demand: Input[REAL]
    max_cool_demand: Input[REAL]
    outdoor_temp: Input[REAL]
    system_enable: Input[BOOL]

    # Lockout temperatures
    chiller_lockout: Input[REAL] = 40.0
    boiler_lockout: Input[REAL] = 75.0

    # Outputs
    supply_fan: Output[BOOL]
    return_fan: Output[BOOL]
    chiller_enable: Output[BOOL]
    boiler_enable: Output[BOOL]

    def logic(self):
        if not self.system_enable:
            self.supply_fan = False
            self.return_fan = False
            self.chiller_enable = False
            self.boiler_enable = False
            return

        # Fans run when any demand exists
        any_demand: BOOL = self.max_heat_demand > 0.0 or self.max_cool_demand > 0.0
        self.supply_fan = any_demand
        self.return_fan = any_demand

        # Chiller: cool demand + outdoor above lockout
        self.chiller_enable = self.max_cool_demand > 0.0 and self.outdoor_temp > self.chiller_lockout

        # Boiler: heat demand + outdoor below lockout
        self.boiler_enable = self.max_heat_demand > 0.0 and self.outdoor_temp < self.boiler_lockout


# ==========================================================================
# Top-level program (wires 3 zones + economizer + filter + central plant)
# ==========================================================================


@program
class HVACSystem:
    """Multi-zone HVAC with 3 FullZoneControllers + economizer + filter alarm + central plant."""

    # System-level DI
    system_enable: Input[BOOL] = True
    morning_warmup_cmd: Input[BOOL]
    filter_dp_alarm_ack: Input[BOOL]

    # Zone 1 I/O  (temp AI, humidity AI, sp AI, co2 AI, occupied DI, window DI)
    zone1_temp: Input[REAL]
    zone1_humidity: Input[REAL]
    zone1_sp: Input[REAL]
    zone1_co2: Input[REAL]
    zone1_occupied: Input[BOOL] = True
    zone1_window: Input[BOOL]

    # Zone 2 I/O
    zone2_temp: Input[REAL]
    zone2_humidity: Input[REAL]
    zone2_sp: Input[REAL]
    zone2_co2: Input[REAL]
    zone2_occupied: Input[BOOL] = True
    zone2_window: Input[BOOL]

    # Zone 3 I/O
    zone3_temp: Input[REAL]
    zone3_humidity: Input[REAL]
    zone3_sp: Input[REAL]
    zone3_co2: Input[REAL]
    zone3_occupied: Input[BOOL] = True
    zone3_window: Input[BOOL]

    # Central AI
    outdoor_temp: Input[REAL]
    mixed_air_temp: Input[REAL]
    supply_air_temp: Input[REAL]
    return_air_temp: Input[REAL]
    chilled_water_temp: Input[REAL]
    filter_dp: Input[REAL]

    # Zone AO outputs
    zone1_heat_valve: Output[REAL]
    zone1_cool_valve: Output[REAL]
    zone1_damper: Output[REAL]
    zone2_heat_valve: Output[REAL]
    zone2_cool_valve: Output[REAL]
    zone2_damper: Output[REAL]
    zone3_heat_valve: Output[REAL]
    zone3_cool_valve: Output[REAL]
    zone3_damper: Output[REAL]

    # Central DO outputs
    supply_fan: Output[BOOL]
    return_fan: Output[BOOL]
    chiller_enable: Output[BOOL]

    # Status outputs
    filter_alarm: Output[BOOL]
    economizer_active: Output[BOOL]

    # Internal FBs
    zone1_ctrl: FullZoneController
    zone2_ctrl: FullZoneController
    zone3_ctrl: FullZoneController
    econ: EconomizerController
    filt: FilterAlarm
    plant: CentralPlant

    # Internals
    max_heat: REAL
    max_cool: REAL
    initialized: BOOL

    def logic(self):
        # First scan initialization
        if first_scan():
            self.initialized = True

        # Zone 1
        self.zone1_ctrl(
            zone_temp=self.zone1_temp,
            occupied=self.zone1_occupied,
            window_open=self.zone1_window,
            morning_warmup=self.morning_warmup_cmd,
            enable=self.system_enable,
        )
        self.zone1_heat_valve = self.zone1_ctrl.heat_demand
        self.zone1_cool_valve = self.zone1_ctrl.cool_demand
        self.zone1_damper = self.zone1_ctrl.damper_pos

        # Zone 2
        self.zone2_ctrl(
            zone_temp=self.zone2_temp,
            occupied=self.zone2_occupied,
            window_open=self.zone2_window,
            morning_warmup=self.morning_warmup_cmd,
            enable=self.system_enable,
        )
        self.zone2_heat_valve = self.zone2_ctrl.heat_demand
        self.zone2_cool_valve = self.zone2_ctrl.cool_demand
        self.zone2_damper = self.zone2_ctrl.damper_pos

        # Zone 3
        self.zone3_ctrl(
            zone_temp=self.zone3_temp,
            occupied=self.zone3_occupied,
            window_open=self.zone3_window,
            morning_warmup=self.morning_warmup_cmd,
            enable=self.system_enable,
        )
        self.zone3_heat_valve = self.zone3_ctrl.heat_demand
        self.zone3_cool_valve = self.zone3_ctrl.cool_demand
        self.zone3_damper = self.zone3_ctrl.damper_pos

        # Max demands across zones
        self.max_heat = self.zone1_ctrl.heat_demand
        if self.zone2_ctrl.heat_demand > self.max_heat:
            self.max_heat = self.zone2_ctrl.heat_demand
        if self.zone3_ctrl.heat_demand > self.max_heat:
            self.max_heat = self.zone3_ctrl.heat_demand

        self.max_cool = self.zone1_ctrl.cool_demand
        if self.zone2_ctrl.cool_demand > self.max_cool:
            self.max_cool = self.zone2_ctrl.cool_demand
        if self.zone3_ctrl.cool_demand > self.max_cool:
            self.max_cool = self.zone3_ctrl.cool_demand

        # Economizer
        self.econ(
            outdoor_temp=self.outdoor_temp,
            return_air_temp=self.return_air_temp,
            mixed_air_temp=self.mixed_air_temp,
            enable=self.system_enable,
        )
        self.economizer_active = self.econ.free_cooling

        # Filter alarm
        self.filt(
            filter_dp=self.filter_dp,
            alarm_ack=self.filter_dp_alarm_ack,
        )
        self.filter_alarm = self.filt.alarm_latched

        # Central plant
        self.plant(
            max_heat_demand=self.max_heat,
            max_cool_demand=self.max_cool,
            outdoor_temp=self.outdoor_temp,
            system_enable=self.system_enable,
        )
        self.supply_fan = self.plant.supply_fan
        self.return_fan = self.plant.return_fan
        self.chiller_enable = self.plant.chiller_enable


# ==========================================================================
# Tests
# ==========================================================================


class TestBaseZoneController:
    @pytest.fixture
    def zone(self):
        ctx = simulate(BaseZoneController)
        ctx.enable = True
        return ctx

    def test_heating_demand_when_cold(self, zone):
        zone.zone_temp = 65.0  # Below 72 - 1 = 71
        zone.scan()
        # heat_error = 72 - 65 = 7, demand = 7 * 5 = 35
        assert zone.heat_demand == pytest.approx(35.0)
        assert zone.cool_demand == pytest.approx(0.0)

    def test_no_heating_in_deadband(self, zone):
        zone.zone_temp = 71.5  # error=0.5, below deadband=1
        zone.scan()
        assert zone.heat_demand == pytest.approx(0.0)

    def test_cooling_demand_when_hot(self, zone):
        zone.zone_temp = 82.0  # Above 76 + 1 = 77
        zone.scan()
        # cool_error = 82 - 76 = 6, demand = 6 * 5 = 30
        assert zone.heat_demand == pytest.approx(0.0)
        assert zone.cool_demand == pytest.approx(30.0)

    def test_no_cooling_in_deadband(self, zone):
        zone.zone_temp = 76.5  # error=0.5, below deadband=1
        zone.scan()
        assert zone.cool_demand == pytest.approx(0.0)

    def test_disabled_no_demand(self, zone):
        zone.enable = False
        zone.zone_temp = 65.0
        zone.scan()
        assert zone.heat_demand == pytest.approx(0.0)
        assert zone.cool_demand == pytest.approx(0.0)

    def test_demand_clamped_at_100(self, zone):
        # heat_error = 72 - 40 = 32, demand = 32 * 5 = 160 → clamped to 100
        zone.zone_temp = 40.0
        zone.scan()
        assert zone.heat_demand == pytest.approx(100.0)


class TestOccupancyZoneController:
    @pytest.fixture
    def zone(self):
        ctx = simulate(OccupancyZoneController)
        ctx.enable = True
        return ctx

    def test_occupied_uses_tight_setpoints(self, zone):
        zone.occupied = True
        zone.zone_temp = 65.0
        zone.scan()
        # heat_sp_occ=72, error=7, demand=35
        assert zone.heat_demand == pytest.approx(35.0)

    def test_unoccupied_uses_wide_setpoints(self, zone):
        zone.occupied = False
        zone.zone_temp = 65.0
        zone.scan()
        # heat_sp_unocc=62, error=62-65=-3, below deadband → 0
        assert zone.heat_demand == pytest.approx(0.0)

    def test_unoccupied_heats_when_very_cold(self, zone):
        zone.occupied = False
        zone.zone_temp = 55.0
        zone.scan()
        # heat_sp_unocc=62, error=62-55=7, demand=35
        assert zone.heat_demand == pytest.approx(35.0)

    def test_unoccupied_cools_at_higher_temp(self, zone):
        zone.occupied = False
        zone.zone_temp = 88.0
        zone.scan()
        # cool_sp_unocc=82, cool_error=88-82=6, demand=30
        assert zone.cool_demand == pytest.approx(30.0)


class TestFullZoneController:
    @pytest.fixture
    def zone(self):
        ctx = simulate(FullZoneController)
        ctx.enable = True
        ctx.occupied = True
        return ctx

    def test_inherits_proportional_control(self, zone):
        zone.zone_temp = 65.0
        zone.scan()
        assert zone.heat_demand == pytest.approx(35.0)

    def test_window_kills_demand(self, zone):
        zone.zone_temp = 65.0
        zone.scan()
        assert zone.heat_demand > 0.0

        zone.window_open = True
        zone.scan()
        assert zone.heat_demand == pytest.approx(0.0)
        assert zone.cool_demand == pytest.approx(0.0)

    def test_warmup_override(self, zone):
        zone.morning_warmup = True
        zone.zone_temp = 60.0  # Below warmup_sp=68
        zone.scan()
        assert zone.heat_demand == pytest.approx(100.0)
        assert zone.cool_demand == pytest.approx(0.0)

    def test_warmup_not_active_above_setpoint(self, zone):
        zone.morning_warmup = True
        zone.zone_temp = 74.0  # Above warmup_sp=68, comfortable
        zone.scan()
        # Normal proportional control (no heating needed at 74)
        assert zone.heat_demand == pytest.approx(0.0)

    def test_damper_tracks_max_demand(self, zone):
        zone.zone_temp = 65.0
        zone.scan()
        # heat_demand=35, cool_demand=0 → damper=35
        assert zone.damper_pos == pytest.approx(35.0)

    def test_fan_runs_with_demand(self, zone):
        zone.zone_temp = 65.0
        zone.scan()
        assert zone.fan_running is True

    def test_fan_coast_down(self, zone):
        # Start with demand
        zone.zone_temp = 65.0
        zone.scan()
        assert zone.fan_running is True

        # Move to comfort zone — no demand
        zone.zone_temp = 74.0
        zone.scan()
        assert zone.heat_demand == pytest.approx(0.0)
        assert zone.cool_demand == pytest.approx(0.0)
        # Fan still running (sustained for 30s)
        assert zone.fan_running is True

        zone.tick(seconds=29)
        assert zone.fan_running is True  # Still coasting

        zone.tick(seconds=2)
        assert zone.fan_running is False  # Coast complete


class TestEconomizerController:
    @pytest.fixture
    def econ(self):
        ctx = simulate(EconomizerController)
        ctx.enable = True
        return ctx

    def test_free_cooling_when_outdoor_cool(self, econ):
        econ.outdoor_temp = 60.0
        econ.return_air_temp = 75.0
        econ.mixed_air_temp = 55.0
        econ.scan()
        assert econ.free_cooling is True
        assert econ.damper_cmd > 10.0

    def test_no_free_cooling_when_outdoor_hot(self, econ):
        econ.outdoor_temp = 80.0
        econ.return_air_temp = 75.0
        econ.scan()
        assert econ.free_cooling is False
        assert econ.damper_cmd == pytest.approx(10.0)

    def test_proportional_damper(self, econ):
        econ.outdoor_temp = 60.0
        econ.return_air_temp = 75.0
        econ.mixed_air_temp = 58.0  # 3 above SP of 55
        econ.scan()
        # error = 55 - 58 = -3, damper = 50 + (-3)*5 = 35
        assert econ.damper_cmd == pytest.approx(35.0)

    def test_disabled(self, econ):
        econ.enable = False
        econ.outdoor_temp = 60.0
        econ.return_air_temp = 75.0
        econ.scan()
        assert econ.free_cooling is False
        assert econ.damper_cmd == pytest.approx(10.0)


class TestFilterAlarm:
    @pytest.fixture
    def fa(self):
        return simulate(FilterAlarm)

    def test_no_alarm_below_threshold(self, fa):
        fa.filter_dp = 2.0  # Below alarm_sp=2.5
        fa.scan()
        assert fa.alarm is False
        assert fa.alarm_latched is False

    def test_debounce_blocks_short_spike(self, fa):
        fa.filter_dp = 3.0  # Above threshold
        fa.tick(seconds=29)
        assert fa.alarm is False  # Not yet 30s

    def test_alarm_triggers_after_30s(self, fa):
        fa.filter_dp = 3.0
        fa.tick(seconds=31)
        assert fa.alarm is True
        assert fa.alarm_latched is True

    def test_latch_until_ack(self, fa):
        fa.filter_dp = 3.0
        fa.tick(seconds=31)
        assert fa.alarm_latched is True

        # DP drops but alarm stays latched
        fa.filter_dp = 1.0
        fa.scan()
        assert fa.alarm_latched is True

        # ACK with DP low clears latch
        fa.alarm_ack = True
        fa.scan()
        assert fa.alarm_latched is False

    def test_ack_ignored_while_dp_high(self, fa):
        fa.filter_dp = 3.0
        fa.tick(seconds=31)
        assert fa.alarm_latched is True

        # ACK while DP still high — stays latched
        fa.alarm_ack = True
        fa.scan()
        assert fa.alarm_latched is True


class TestCentralPlant:
    @pytest.fixture
    def plant(self):
        ctx = simulate(CentralPlant)
        ctx.system_enable = True
        return ctx

    def test_fans_on_with_demand(self, plant):
        plant.max_cool_demand = 50.0
        plant.outdoor_temp = 80.0
        plant.scan()
        assert plant.supply_fan is True
        assert plant.return_fan is True

    def test_fans_off_no_demand(self, plant):
        plant.max_heat_demand = 0.0
        plant.max_cool_demand = 0.0
        plant.scan()
        assert plant.supply_fan is False
        assert plant.return_fan is False

    def test_chiller_enabled_warm_outdoor(self, plant):
        plant.max_cool_demand = 50.0
        plant.outdoor_temp = 80.0  # Above chiller_lockout=40
        plant.scan()
        assert plant.chiller_enable is True

    def test_chiller_locked_out_cold_outdoor(self, plant):
        plant.max_cool_demand = 50.0
        plant.outdoor_temp = 35.0  # Below chiller_lockout=40
        plant.scan()
        assert plant.chiller_enable is False

    def test_boiler_enabled_cold_outdoor(self, plant):
        plant.max_heat_demand = 50.0
        plant.outdoor_temp = 30.0  # Below boiler_lockout=75
        plant.scan()
        assert plant.boiler_enable is True

    def test_boiler_locked_out_warm_outdoor(self, plant):
        plant.max_heat_demand = 50.0
        plant.outdoor_temp = 80.0  # Above boiler_lockout=75
        plant.scan()
        assert plant.boiler_enable is False

    def test_disabled(self, plant):
        plant.system_enable = False
        plant.max_cool_demand = 50.0
        plant.scan()
        assert plant.supply_fan is False
        assert plant.chiller_enable is False
        assert plant.boiler_enable is False


class TestHVACSystem:
    @pytest.fixture
    def hvac(self):
        ctx = simulate(
            HVACSystem,
            pous=[
                BaseZoneController,
                OccupancyZoneController,
                FullZoneController,
                EconomizerController,
                FilterAlarm,
                CentralPlant,
            ],
            data_types=[ZoneConfig, ZoneStatus],
        )
        return ctx

    def test_first_scan_initialization(self, hvac):
        hvac.scan()
        assert hvac.initialized is True

    def test_zones_respond_independently(self, hvac):
        hvac.zone1_temp = 65.0  # Cold → heating
        hvac.zone2_temp = 74.0  # Comfortable → no demand
        hvac.zone3_temp = 82.0  # Hot → cooling (cool_error=82-76=6, demand=30)
        hvac.scan()

        assert hvac.zone1_heat_valve > 0.0
        assert hvac.zone1_cool_valve == pytest.approx(0.0)
        assert hvac.zone2_heat_valve == pytest.approx(0.0)
        assert hvac.zone2_cool_valve == pytest.approx(0.0)
        assert hvac.zone3_heat_valve == pytest.approx(0.0)
        assert hvac.zone3_cool_valve > 0.0

    def test_system_disable_stops_everything(self, hvac):
        hvac.zone1_temp = 65.0
        hvac.outdoor_temp = 80.0
        hvac.scan()
        assert hvac.zone1_heat_valve > 0.0

        hvac.system_enable = False
        hvac.scan()
        assert hvac.zone1_heat_valve == pytest.approx(0.0)
        assert hvac.supply_fan is False
        assert hvac.chiller_enable is False

    def test_central_plant_responds_to_zone_demands(self, hvac):
        hvac.zone1_temp = 65.0  # Heating demand
        hvac.outdoor_temp = 30.0  # Cold outdoor
        hvac.scan()

        assert hvac.supply_fan is True
        assert hvac.return_fan is True
        # Heat demand + outdoor below boiler lockout → boiler on
        assert hvac.chiller_enable is False

    def test_economizer_activates(self, hvac):
        hvac.outdoor_temp = 60.0
        hvac.return_air_temp = 75.0
        hvac.mixed_air_temp = 55.0
        hvac.scan()
        assert hvac.economizer_active is True

    def test_filter_alarm_propagates(self, hvac):
        hvac.filter_dp = 3.0  # Above alarm threshold
        hvac.tick(seconds=31)
        assert hvac.filter_alarm is True


class TestHVACProjectCompilation:
    def test_project_compiles_with_all_features(self):
        @program
        class TrendProgram:
            def logic(self):
                pass

        prj = project(
            "HVACProject",
            pous=[
                BaseZoneController,
                OccupancyZoneController,
                FullZoneController,
                EconomizerController,
                FilterAlarm,
                CentralPlant,
                HVACSystem,
                TrendProgram,
            ],
            data_types=[ZoneConfig, ZoneStatus],
            tasks=[
                task(
                    "TempControl",
                    periodic=timedelta(milliseconds=100),
                    pous=[HVACSystem],
                    priority=2,
                ),
                task(
                    "Trending",
                    periodic=timedelta(seconds=1),
                    pous=[TrendProgram],
                    priority=10,
                ),
            ],
        ).compile()

        assert len(prj.pous) >= 7
        assert len(prj.tasks) == 2
        assert len(prj.data_types) == 2

        # Verify 3-level inheritance chain
        pou_map = {p.name: p for p in prj.pous}
        assert pou_map["FullZoneController"].extends == "OccupancyZoneController"
        assert pou_map["OccupancyZoneController"].extends == "BaseZoneController"
        assert pou_map["BaseZoneController"].extends is None

        # Verify @fb_method(access=PROTECTED) on BaseZoneController
        base_methods = pou_map["BaseZoneController"].methods
        assert len(base_methods) == 1
        assert base_methods[0].name == "compute_demand"
        assert base_methods[0].access == AccessSpecifier.PROTECTED

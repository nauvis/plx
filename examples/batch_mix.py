"""Batch mixing system — fill, mix, drain, CIP.

Three ingredient valves meter product into a tank by volume,
then an agitator mixes for a set time, the batch drains out,
and a CIP (clean-in-place) cycle flushes the system.
"""

from datetime import timedelta

from plx.framework import (
    TIME,
    fb,
    program,
    function,
    Input,
    Output,
    delayed,
    rising,
    sustained,
    project,
    Field,
)

# -- States ----------------------------------------------------------------
IDLE       = 0
FILL_A     = 1
FILL_B     = 2
FILL_C     = 3
MIX        = 4
DRAIN      = 5
CIP_RINSE  = 6
CIP_WASH   = 7
CIP_FINAL  = 8
COMPLETE   = 9
FAULT      = 99


# -------------------------------------------------------------------------
# Valve controller — opens a valve and watches for feedback
# -------------------------------------------------------------------------

@fb
class ValveCtrl:
    cmd_open: Input[bool] = Field(description="Command to open")
    feedback: Input[bool] = Field(description="Open limit switch")
    fault_time: Input[TIME] = Field(initial=timedelta(seconds=3), description="Fault timeout")

    valve_out: Output[bool] = Field(description="Solenoid output")
    is_open: Output[bool] = Field(description="Confirmed open")
    fault: Output[bool] = Field(description="Failed to open in time")

    def logic(self):
        self.valve_out = self.cmd_open

        if self.cmd_open:
            self.is_open = self.feedback
            if delayed(self.cmd_open and not self.feedback, timedelta(seconds=3)):
                self.fault = True
        else:
            self.is_open = False
            self.fault = False


# -------------------------------------------------------------------------
# Volume dosing — counts flow pulses until a target is reached
# -------------------------------------------------------------------------

@fb
class VolumeDose:
    start: Input[bool] = Field(description="Start dosing")
    flow_pulse: Input[bool] = Field(description="Flowmeter pulse input")
    target_vol: Input[float] = Field(description="Target volume (liters)")
    vol_per_pulse: Input[float] = Field(initial=0.1, description="Liters per pulse")

    done: Output[bool] = Field(description="Target reached")
    actual_vol: Output[float] = Field(description="Accumulated volume")
    valve_cmd: Output[bool] = Field(description="Open command to valve")

    def logic(self):
        if not self.start:
            self.actual_vol = 0.0
            self.done = False
            self.valve_cmd = False
            return

        if rising(self.flow_pulse):
            self.actual_vol += self.vol_per_pulse

        if self.actual_vol >= self.target_vol:
            self.done = True
            self.valve_cmd = False
        else:
            self.valve_cmd = True


# -------------------------------------------------------------------------
# Main batch sequencer
# -------------------------------------------------------------------------

@program
class BatchMix:
    # --- operator commands ---
    cmd_start: Input[bool] = Field(description="Start batch")
    cmd_reset: Input[bool] = Field(description="Reset after fault/complete")
    cmd_cip: Input[bool] = Field(description="Start CIP cycle")

    # --- field I/O ---
    level: Input[float] = Field(description="Tank level (liters)")
    level_low: Input[bool] = Field(description="Low level switch")
    flow_a: Input[bool] = Field(description="Ingredient A flow pulse")
    flow_b: Input[bool] = Field(description="Ingredient B flow pulse")
    flow_c: Input[bool] = Field(description="Ingredient C flow pulse")

    # --- outputs ---
    valve_a: Output[bool] = Field(description="Ingredient A valve")
    valve_b: Output[bool] = Field(description="Ingredient B valve")
    valve_c: Output[bool] = Field(description="Ingredient C valve")
    drain_valve: Output[bool] = Field(description="Drain valve")
    cip_valve: Output[bool] = Field(description="CIP supply valve")
    agitator: Output[bool] = Field(description="Mixer motor")

    # --- status ---
    state: Output[int] = Field(description="Current step")
    batch_done: Output[bool] = Field(description="Batch complete")
    cip_done: Output[bool] = Field(description="CIP complete")

    # --- internal ---
    step: int = 0
    dose_a_start: bool = False
    dose_b_start: bool = False
    dose_c_start: bool = False
    dose_a_done: bool = False
    dose_b_done: bool = False
    dose_c_done: bool = False

    def logic(self):
        # Reset command returns to idle from complete or fault
        if self.cmd_reset:
            self.step = IDLE
            self.batch_done = False
            self.cip_done = False

        # Default outputs off
        self.agitator = False
        self.drain_valve = False
        self.cip_valve = False
        self.dose_a_start = False
        self.dose_b_start = False
        self.dose_c_start = False

        match self.step:
            # ---- idle ------------------------------------------------
            case 0:
                if rising(self.cmd_start):
                    self.step = FILL_A
                elif rising(self.cmd_cip):
                    self.step = CIP_RINSE

            # ---- fill ingredient A -----------------------------------
            case 1:
                self.dose_a_start = True
                if self.dose_a_done:
                    self.step = FILL_B

            # ---- fill ingredient B -----------------------------------
            case 2:
                self.dose_b_start = True
                if self.dose_b_done:
                    self.step = FILL_C

            # ---- fill ingredient C -----------------------------------
            case 3:
                self.dose_c_start = True
                if self.dose_c_done:
                    self.step = MIX

            # ---- mix for 30 seconds ----------------------------------
            case 4:
                self.agitator = True
                if delayed(self.agitator, timedelta(seconds=30)):
                    self.step = DRAIN

            # ---- drain until low level -------------------------------
            case 5:
                self.drain_valve = True
                self.agitator = True
                if self.level_low:
                    self.step = COMPLETE

            # ---- CIP rinse -------------------------------------------
            case 6:
                self.cip_valve = True
                self.drain_valve = True
                if delayed(self.cip_valve, timedelta(seconds=60)):
                    self.step = CIP_WASH

            # ---- CIP wash (with agitation) ---------------------------
            case 7:
                self.cip_valve = True
                self.drain_valve = True
                self.agitator = True
                if delayed(self.agitator, timedelta(seconds=120)):
                    self.step = CIP_FINAL

            # ---- CIP final rinse -------------------------------------
            case 8:
                self.cip_valve = True
                self.drain_valve = True
                if delayed(self.cip_valve, timedelta(seconds=60)):
                    self.step = COMPLETE

            # ---- complete --------------------------------------------
            case 9:
                self.batch_done = True
                self.cip_done = True

        self.state = self.step


# -------------------------------------------------------------------------
# Assemble project
# -------------------------------------------------------------------------

proj = project("BatchMixPlant", pous=[ValveCtrl, VolumeDose, BatchMix])


if __name__ == "__main__":
    import json

    ir = proj.compile()
    print(f"Project: {ir.name}")
    print(f"POUs:    {len(ir.pous)}")
    for pou in ir.pous:
        iface = pou.interface
        n_stmts = sum(len(n.statements) for n in pou.networks)
        print(f"  {pou.pou_type.value:<20s} {pou.name}")
        print(f"    inputs={len(iface.input_vars)}  outputs={len(iface.output_vars)}  "
              f"statics={len(iface.static_vars)}  temps={len(iface.temp_vars)}  "
              f"statements={n_stmts}")
    print()
    print(json.dumps(ir.model_dump(), indent=2)[:2000])
    print("...")

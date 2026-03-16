"""Batch mixing system — with proper FB instantiation.

Same process, but the program instantiates ValveCtrl and VolumeDose
FBs as static vars and calls them properly.
"""

from datetime import timedelta

from plx.framework import (
    REAL,
    TIME,
    fb,
    program,
    Input,
    Output,
    delayed,
    rising,
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


@fb
class ValveCtrl:
    cmd_open: Input[bool] = Field(description="Command to open")
    feedback: Input[bool] = Field(description="Open limit switch")
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


@fb
class VolumeDose:
    start: Input[bool]
    flow_pulse: Input[bool]
    target_vol: Input[REAL]
    done: Output[bool]
    actual_vol: Output[REAL]
    valve_cmd: Output[bool]

    def logic(self):
        if not self.start:
            self.actual_vol = 0.0
            self.done = False
            self.valve_cmd = False
            return

        if rising(self.flow_pulse):
            self.actual_vol += 0.1

        if self.actual_vol >= self.target_vol:
            self.done = True
            self.valve_cmd = False
        else:
            self.valve_cmd = True


@program
class BatchMix:
    # --- operator ---
    cmd_start: Input[bool]
    cmd_reset: Input[bool]
    cmd_cip: Input[bool]

    # --- field I/O ---
    level_low: Input[bool]
    flow_a: Input[bool]
    flow_b: Input[bool]
    flow_c: Input[bool]
    fb_valve_a: Input[bool] = Field(description="Valve A feedback")
    fb_valve_b: Input[bool] = Field(description="Valve B feedback")
    fb_valve_c: Input[bool] = Field(description="Valve C feedback")

    # --- outputs ---
    sol_a: Output[bool]
    sol_b: Output[bool]
    sol_c: Output[bool]
    drain_valve: Output[bool]
    cip_valve: Output[bool]
    agitator: Output[bool]
    state: Output[int]
    batch_done: Output[bool]

    # --- FB instances ---
    valve_a: "ValveCtrl"
    valve_b: "ValveCtrl"
    valve_c: "ValveCtrl"
    dose_a: "VolumeDose"
    dose_b: "VolumeDose"
    dose_c: "VolumeDose"
    step: int = 0

    def logic(self):
        if self.cmd_reset:
            self.step = IDLE
            self.batch_done = False

        # Default outputs
        self.agitator = False
        self.drain_valve = False
        self.cip_valve = False

        match self.step:
            case 0:
                if rising(self.cmd_start):
                    self.step = FILL_A

            case 1:
                self.dose_a(start=True, flow_pulse=self.flow_a, target_vol=100.0)
                self.valve_a(cmd_open=self.dose_a.valve_cmd, feedback=self.fb_valve_a)
                self.sol_a = self.valve_a.valve_out
                if self.dose_a.done:
                    self.step = FILL_B

            case 2:
                self.dose_b(start=True, flow_pulse=self.flow_b, target_vol=50.0)
                self.valve_b(cmd_open=self.dose_b.valve_cmd, feedback=self.fb_valve_b)
                self.sol_b = self.valve_b.valve_out
                if self.dose_b.done:
                    self.step = FILL_C

            case 3:
                self.dose_c(start=True, flow_pulse=self.flow_c, target_vol=25.0)
                self.valve_c(cmd_open=self.dose_c.valve_cmd, feedback=self.fb_valve_c)
                self.sol_c = self.valve_c.valve_out
                if self.dose_c.done:
                    self.step = MIX

            case 4:
                self.agitator = True
                if delayed(self.agitator, timedelta(seconds=30)):
                    self.step = DRAIN

            case 5:
                self.drain_valve = True
                self.agitator = True
                if self.level_low:
                    self.step = COMPLETE

            case 9:
                self.batch_done = True

        self.state = self.step


proj = project("BatchMixPlant", pous=[ValveCtrl, VolumeDose, BatchMix])


if __name__ == "__main__":
    ir = proj.compile()
    print(f"Project: {ir.name}")
    for pou in ir.pous:
        iface = pou.interface
        n_stmts = sum(len(n.statements) for n in pou.networks)
        print(f"\n  {pou.pou_type.value} {pou.name}")
        print(f"    inputs:  {[v.name for v in iface.input_vars]}")
        print(f"    outputs: {[v.name for v in iface.output_vars]}")
        print(f"    statics: {[v.name for v in iface.static_vars]}")
        print(f"    statements: {n_stmts}")

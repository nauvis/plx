"""FB inheritance with super().logic() in the plx framework.

Demonstrates:
  - Base FB with common logic
  - Derived FB that calls super().logic() then adds behavior
  - Three-level inheritance (grandparent → parent → child)
  - Variable override
"""

from datetime import timedelta

from plx.framework import (
    fb,
    Input,
    Output,
    delayed,
    project,
    Field,
)


# =========================================================================
# Base valve — on/off with fault detection
# =========================================================================

@fb
class BaseValve:
    cmd: Input[bool] = Field(description="Open command")
    feedback: Input[bool] = Field(description="Open limit switch")
    valve_out: Output[bool] = Field(description="Solenoid output")
    is_open: Output[bool] = Field(description="Confirmed open")
    fault: Output[bool] = Field(description="Open timeout fault")

    def logic(self):
        self.valve_out = self.cmd
        self.is_open = self.cmd and self.feedback
        if delayed(self.cmd and not self.feedback, timedelta(seconds=3)):
            self.fault = True
        if not self.cmd:
            self.fault = False


# =========================================================================
# Double-acting — adds close fault on top of base
# =========================================================================

@fb
class DoubleActingValve(BaseValve):
    close_feedback: Input[bool] = Field(description="Close limit switch")
    close_fault: Output[bool] = Field(description="Close timeout fault")

    def logic(self):
        super().logic()
        # Additional close fault detection
        if delayed(not self.cmd and not self.close_feedback, timedelta(seconds=3)):
            self.close_fault = True
        if self.cmd:
            self.close_fault = False


# =========================================================================
# Modulating — adds analog position on top of double-acting
#              (three-level inheritance)
# =========================================================================

@fb
class ModulatingValve(DoubleActingValve):
    position_sp: Input[float] = Field(description="Position setpoint 0-100%")
    position_pv: Input[float] = Field(description="Position feedback 0-100%")
    position_out: Output[float] = Field(description="Analog output 0-100%")
    in_position: Output[bool] = Field(description="At setpoint")

    def logic(self):
        super().logic()  # runs DoubleActingValve.logic() which runs BaseValve.logic()
        if self.cmd:
            self.position_out = self.position_sp
            self.in_position = abs(self.position_sp - self.position_pv) < 2.0
        else:
            self.position_out = 0.0
            self.in_position = False


# =========================================================================
# Print results
# =========================================================================

if __name__ == "__main__":
    proj = project("InheritanceDemo", pous=[
        BaseValve, DoubleActingValve, ModulatingValve,
    ])
    ir = proj.compile()

    for pou in ir.pous:
        iface = pou.interface
        ext = f" EXTENDS {pou.extends}" if pou.extends else ""
        n_stmts = sum(len(n.statements) for n in pou.networks)
        print(f"{pou.pou_type.value} {pou.name}{ext}")
        print(f"  inputs:  {[v.name for v in iface.input_vars]}")
        print(f"  outputs: {[v.name for v in iface.output_vars]}")
        print(f"  statics: {[v.name for v in iface.static_vars]}")
        print(f"  statements: {n_stmts}")
        print()

"""Direct On-Line (DOL) motor starter.

A basic motor control block that handles start/stop commands with
safety interlocking (E-stop), overload detection, and run feedback.
"""

from plx.framework import (
    BOOL,
    Field,
    Input,
    Output,
    fb,
)


@fb(folder="stdlib/motors")
class DOLStarter:
    """Direct On-Line motor starter with safety interlock.

    Inputs:
        run_cmd: Start command (momentary or maintained)
        stop_cmd: Stop command (momentary, normally False)
        e_stop: Emergency stop circuit healthy (True = OK)
        overload: Thermal overload contact (True = tripped)
        feedback: Motor contactor feedback (True = running)

    Outputs:
        motor_on: Contactor output command
        running: Confirmed running (feedback received)
        faulted: Fault condition active
    """

    run_cmd: Input[BOOL] = Field(description="Start command")
    stop_cmd: Input[BOOL] = Field(description="Stop command")
    e_stop: Input[BOOL] = Field(initial=True, description="E-stop healthy (True=OK)")
    overload: Input[BOOL] = Field(description="Thermal overload (True=tripped)")
    feedback: Input[BOOL] = Field(description="Contactor feedback")

    motor_on: Output[BOOL] = Field(description="Contactor output command")
    running: Output[BOOL] = Field(description="Confirmed running")
    faulted: Output[BOOL] = Field(description="Fault active")

    latched: BOOL = Field(description="Latched run command")

    def logic(self):
        # Fault detection
        self.faulted = self.overload or not self.e_stop

        # Latch run command, clear on stop or fault
        if self.run_cmd and not self.faulted:
            self.latched = True
        if self.stop_cmd or self.faulted:
            self.latched = False

        # Output
        self.motor_on = self.latched
        self.running = self.motor_on and self.feedback

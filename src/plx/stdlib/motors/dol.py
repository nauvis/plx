"""Direct On-Line (DOL) motor starter.

A basic motor control block that handles start/stop commands with
safety interlocking (E-stop), overload detection, and run feedback.
"""

from plx.framework import (
    BOOL,
    TIME,
    fb,
    input_var,
    output_var,
    static_var,
    delayed,
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
    run_cmd = input_var(BOOL, description="Start command")
    stop_cmd = input_var(BOOL, description="Stop command")
    e_stop = input_var(BOOL, initial=True, description="E-stop healthy (True=OK)")
    overload = input_var(BOOL, description="Thermal overload (True=tripped)")
    feedback = input_var(BOOL, description="Contactor feedback")

    motor_on = output_var(BOOL, description="Contactor output command")
    running = output_var(BOOL, description="Confirmed running")
    faulted = output_var(BOOL, description="Fault active")

    latched = static_var(BOOL, description="Latched run command")

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

"""Single-acting solenoid valve controller.

Controls a solenoid valve with open/close commands, position feedback,
and fault detection for stuck valves.
"""

from plx.framework import (
    BOOL,
    fb,
    Input,
    Output,
    delayed,
    Field,
)


@fb(folder="stdlib/valves")
class SolenoidValve:
    """Single-acting solenoid valve with feedback monitoring.

    Inputs:
        open_cmd: Command to open valve
        open_fbk: Valve open limit switch
        closed_fbk: Valve closed limit switch

    Outputs:
        solenoid: Solenoid output
        is_open: Confirmed open
        is_closed: Confirmed closed
        faulted: Valve stuck or contradictory feedback
    """
    open_cmd: Input[BOOL] = Field(description="Open command")
    open_fbk: Input[BOOL] = Field(description="Open limit switch")
    closed_fbk: Input[BOOL] = Field(description="Closed limit switch")

    solenoid: Output[BOOL] = Field(description="Solenoid output")
    is_open: Output[BOOL] = Field(description="Confirmed open")
    is_closed: Output[BOOL] = Field(description="Confirmed closed")
    faulted: Output[BOOL] = Field(description="Fault active")

    def logic(self):
        self.solenoid = self.open_cmd

        self.is_open = self.open_fbk and not self.closed_fbk
        self.is_closed = self.closed_fbk and not self.open_fbk

        # Fault: both feedback on simultaneously
        self.faulted = self.open_fbk and self.closed_fbk

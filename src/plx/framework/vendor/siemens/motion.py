"""Siemens motion control function blocks.

TIA Portal S7-1500T motion control via Technology Objects.  These FBs
implement PLCopen-style motion control for speed axes, positioning axes,
and synchronized (geared) axes.

Available types:

Structs (Technology Object references):
    TO_SpeedAxis        Speed-controlled axis reference
    TO_PositioningAxis  Position-controlled axis reference

Axis Administration:
    MC_Power    (Enable/disable axis)
    MC_Reset    (Reset axis errors)
    MC_Home     (Home/reference axis)

Motion Commands:
    MC_Halt           (Controlled deceleration to standstill)
    MC_MoveAbsolute   (Move to absolute position)
    MC_MoveRelative   (Move relative distance)
    MC_MoveVelocity   (Continuous velocity motion)
    MC_MoveJog        (Manual jog mode)
    MC_Stop           (Emergency stop and lock)

Coupling:
    MC_GearIn    (Engage electronic gearing)
    MC_GearOut   (Disengage electronic gearing)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB, LibraryStruct
from plx.framework._types import BOOL, DINT, DWORD, INT, LREAL, WORD

# ===================================================================
# Structs (Technology Object references)
# ===================================================================


class TO_SpeedAxis(LibraryStruct, vendor="siemens", library="siemens_motion"):
    """Technology Object reference for a speed-controlled axis.

    In TIA Portal, the real Technology Object contains hundreds of
    configuration and status fields (encoder config, drive interface,
    limits, diagnostics).  This stub exposes only minimal status
    fields — the simulator populates fields on demand.
    """

    StatusWord: DWORD
    ErrorWord: DWORD


class TO_PositioningAxis(LibraryStruct, vendor="siemens", library="siemens_motion"):
    """Technology Object reference for a position-controlled axis.

    Extends the speed axis concept with position feedback, homing
    configuration, and software limits.  In TIA Portal, this is
    configured via the Technology Object wizard and contains
    extensive parameterization.  This stub is a minimal placeholder.
    """

    StatusWord: DWORD
    ErrorWord: DWORD


# ===================================================================
# Axis Administration
# ===================================================================


class MC_Power(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Enable or disable the servo drive of an axis.

    Enable=TRUE requests servo on.  Status=TRUE confirms the drive is
    powered and ready for motion commands.

    StartMode selects the axis behavior on enable:
    - 0: Default (depends on axis type configuration).
    - 1: Position control.
    - 3: Speed control.

    StopMode selects behavior when Enable goes FALSE:
    - 0: Emergency stop (immediate).
    - 1: Controlled stop (uses configured deceleration).
    - 2: Coast to stop (drive disabled immediately, axis coasts).

    Typical usage::

        @fb(target=siemens)
        class AxisEnable:
            power: MC_Power
            axis: InOut[TO_PositioningAxis]
            enable: Input[BOOL]
            ready: Output[BOOL]

            def logic(self):
                self.power(Axis=self.axis, Enable=self.enable, StartMode=0, StopMode=1)
                self.ready = self.power.Status
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Enable: Input[BOOL]
    StartMode: Input[DINT]
    StopMode: Input[INT]

    # --- Outputs ---
    Status: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Simplified stand-in: Status follows Enable after 1 scan."""
        state["Status"] = state["Enable"]
        state["Busy"] = False
        state["Error"] = False
        state["ErrorID"] = 0


class MC_Reset(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Reset axis errors and transition out of error state.

    Rising edge on Execute clears the axis error state.  The axis
    must be re-enabled with MC_Power after a successful reset.

    Typical usage::

        @fb(target=siemens)
        class AxisReset:
            reset: MC_Reset
            axis: InOut[TO_PositioningAxis]
            reset_req: Input[BOOL]
            reset_done: Output[BOOL]

            def logic(self):
                self.reset(Axis=self.axis, Execute=self.reset_req)
                self.reset_done = self.reset.Done
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Restart: Input[BOOL]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_Home(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Home (reference) an axis.

    Executes the configured homing procedure to establish a reference
    point.  The Mode parameter selects the homing method:
    - 0: Use configured homing procedure (default).
    - 1: Direct homing — set position without movement.
    - 2-5: Various sensor-based homing modes.

    Position: the reference position value to set at the home point.

    Typical usage::

        @fb(target=siemens)
        class AxisHoming:
            home: MC_Home
            axis: InOut[TO_PositioningAxis]
            home_req: Input[BOOL]
            home_done: Output[BOOL]

            def logic(self):
                self.home(Axis=self.axis, Execute=self.home_req, Position=0.0, Mode=0)
                self.home_done = self.home.Done
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Position: Input[LREAL]
    Mode: Input[INT]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]
    ReferenceMarkPosition: Output[LREAL]


# ===================================================================
# Motion Commands
# ===================================================================


class MC_Halt(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Controlled halt — decelerates axis to standstill.

    Unlike MC_Stop, MC_Halt allows new motion commands to be accepted
    while the axis is decelerating.  The axis transitions to standstill
    after reaching zero velocity.

    Typical usage::

        @fb(target=siemens)
        class AxisHalt:
            halt: MC_Halt
            axis: InOut[TO_PositioningAxis]
            halt_req: Input[BOOL]
            halted: Output[BOOL]

            def logic(self):
                self.halt(Axis=self.axis, Execute=self.halt_req)
                self.halted = self.halt.Done
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_MoveAbsolute(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Move axis to an absolute target position.

    Rising edge on Execute starts the motion.  The axis moves to the
    specified Position at the given Velocity, Acceleration, Deceleration,
    and Jerk parameters.

    Direction selects the travel direction for modulo axes:
    - 1: Positive direction.
    - 2: Negative direction.
    - 3: Shortest way (for modulo axes only).

    Jerk=0 selects trapezoidal acceleration profile; Jerk>0 selects
    S-curve (jerk-limited) profile.

    Typical usage::

        @fb(target=siemens)
        class PositionMove:
            move: MC_MoveAbsolute
            axis: InOut[TO_PositioningAxis]
            go: Input[BOOL]
            target: Input[LREAL]
            done: Output[BOOL]

            def logic(self):
                self.move(
                    Axis=self.axis,
                    Execute=self.go,
                    Position=self.target,
                    Velocity=100.0,
                    Acceleration=500.0,
                    Deceleration=500.0,
                    Jerk=0.0,
                    Direction=0,
                )
                self.done = self.move.Done
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Position: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    Direction: Input[INT]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_MoveRelative(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Move axis a relative distance from the current position.

    Rising edge on Execute starts the motion.  Distance is added to the
    actual position at the moment of the rising edge.  Positive distance
    moves in the positive direction, negative in the negative direction.

    Typical usage::

        @fb(target=siemens)
        class RelativeMove:
            move: MC_MoveRelative
            axis: InOut[TO_PositioningAxis]
            go: Input[BOOL]
            distance: Input[LREAL]
            done: Output[BOOL]

            def logic(self):
                self.move(
                    Axis=self.axis,
                    Execute=self.go,
                    Distance=self.distance,
                    Velocity=50.0,
                    Acceleration=200.0,
                    Deceleration=200.0,
                    Jerk=0.0,
                )
                self.done = self.move.Done
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Distance: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_MoveVelocity(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Start continuous velocity motion (no target position).

    Rising edge on Execute starts the move.  The axis accelerates to the
    commanded Velocity and continues indefinitely until another motion
    command is issued.  InVelocity=TRUE when the axis has reached the
    commanded speed.

    Direction:
    - 0: Sign of Velocity determines direction.
    - 1: Positive direction.
    - 2: Negative direction.

    Typical usage::

        @fb(target=siemens)
        class ConveyorDrive:
            move: MC_MoveVelocity
            axis: InOut[TO_SpeedAxis]
            run: Input[BOOL]
            speed: Input[LREAL]
            at_speed: Output[BOOL]

            def logic(self):
                self.move(
                    Axis=self.axis,
                    Execute=self.run,
                    Velocity=self.speed,
                    Acceleration=100.0,
                    Deceleration=100.0,
                    Jerk=0.0,
                    Direction=0,
                )
                self.at_speed = self.move.InVelocity
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    Direction: Input[INT]

    # --- Outputs ---
    InVelocity: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_MoveJog(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Manual jog mode for commissioning and setup.

    JogForward/JogBackward are level-triggered — the axis moves while
    the button is held.  The axis decelerates to standstill when both
    inputs are FALSE.

    Typical usage::

        @fb(target=siemens)
        class ManualJog:
            jog: MC_MoveJog
            axis: InOut[TO_PositioningAxis]
            jog_fwd: Input[BOOL]
            jog_rev: Input[BOOL]
            in_velocity: Output[BOOL]

            def logic(self):
                self.jog(
                    Axis=self.axis,
                    JogForward=self.jog_fwd,
                    JogBackward=self.jog_rev,
                    Velocity=10.0,
                    Acceleration=50.0,
                    Deceleration=50.0,
                )
                self.in_velocity = self.jog.InVelocity
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    JogForward: Input[BOOL]
    JogBackward: Input[BOOL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    # --- Outputs ---
    InVelocity: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_Stop(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Emergency stop — decelerates axis and locks out new commands.

    While Execute is TRUE the axis is in stopping state and rejects
    all other motion commands.  New commands are accepted only after
    Execute is released AND the axis has reached standstill.

    This is the S7-1500T equivalent of an E-stop for a single axis.

    Typical usage::

        @fb(target=siemens)
        class EmergencyStop:
            stop: MC_Stop
            axis: InOut[TO_PositioningAxis]
            estop: Input[BOOL]
            stopped: Output[BOOL]

            def logic(self):
                self.stop(Axis=self.axis, Execute=self.estop)
                self.stopped = self.stop.Done
    """

    # --- InOut ---
    Axis: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Mode: Input[DINT]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


# ===================================================================
# Coupling
# ===================================================================


class MC_GearIn(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Activate electronic gear coupling between master and slave axes.

    The slave follows the master at a gear ratio of RatioNumerator /
    RatioDenominator.  InGear=TRUE when the slave has synchronized to
    the master's motion profile.

    The slave accelerates to match the master using the specified
    Acceleration and Deceleration parameters.

    Typical usage::

        @fb(target=siemens)
        class GearCoupling:
            gear: MC_GearIn
            master: InOut[TO_PositioningAxis]
            slave: InOut[TO_PositioningAxis]
            engage: Input[BOOL]
            in_gear: Output[BOOL]

            def logic(self):
                self.gear(
                    Master=self.master,
                    Slave=self.slave,
                    Execute=self.engage,
                    RatioNumerator=2,
                    RatioDenominator=1,
                    Acceleration=500.0,
                    Deceleration=500.0,
                )
                self.in_gear = self.gear.InGear
    """

    # --- InOut ---
    Master: InOut[TO_PositioningAxis]
    Slave: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    RatioNumerator: Input[DINT]
    RatioDenominator: Input[DINT]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    # --- Outputs ---
    InGear: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]


class MC_GearOut(LibraryFB, vendor="siemens", library="siemens_motion"):
    """Disengage electronic gear coupling on the slave axis.

    Rising edge on Execute decouples the slave from its master.
    The slave continues at its current velocity after decoupling
    (does not stop automatically).

    Typical usage::

        @fb(target=siemens)
        class GearDisengage:
            gear_out: MC_GearOut
            slave: InOut[TO_PositioningAxis]
            disengage: Input[BOOL]
            done: Output[BOOL]

            def logic(self):
                self.gear_out(Slave=self.slave, Execute=self.disengage)
                self.done = self.gear_out.Done
    """

    # --- InOut ---
    Slave: InOut[TO_PositioningAxis]

    # --- Inputs ---
    Execute: Input[BOOL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    # --- Outputs ---
    Done: Output[BOOL]
    Busy: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[WORD]

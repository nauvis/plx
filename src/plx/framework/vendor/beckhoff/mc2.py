"""Tc2_MC2 — PLCopen motion control library stubs.

Beckhoff's implementation of the PLCopen MC function blocks for
single-axis motion control.  These FBs are compiled into the
Tc2_MC2 library and are not available as source.

Available types:

Enums:
    MC_BufferMode, MC_Direction, MC_HomingMode, E_JogMode

Structs:
    AXIS_REF, ST_AxisStatus, ST_MoveOptions, ST_HomingOptions

Axis Administration:
    MC_Power, MC_Reset, MC_SetPosition

Status / Parameter:
    MC_ReadActualPosition, MC_ReadActualVelocity, MC_ReadStatus,
    MC_ReadAxisError, MC_SetOverride

Parameter Read / Write:
    MC_ReadParameter, MC_ReadBoolParameter, MC_ReadParameterSet,
    MC_WriteParameter, MC_WriteBoolParameter,
    MC_WriteParameterPersistent, MC_WriteBoolParameterPersistent

Point-to-Point Motion:
    MC_MoveAbsolute, MC_MoveRelative, MC_MoveAdditive, MC_MoveModulo,
    MC_MoveVelocity, MC_MoveContinuousAbsolute, MC_MoveContinuousRelative

Stop / Halt:
    MC_Halt, MC_Stop

Homing:
    MC_Home

Manual:
    MC_Jog

Coupling:
    MC_GearIn, MC_GearInDyn, MC_GearOut

Touch Probe:
    MC_TouchProbe, MC_AbortTrigger

Advanced:
    MC_MoveSuperImposed, MC_TorqueControl

Note: do NOT use ``from __future__ import annotations`` in stub files —
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryEnum, LibraryFB, LibraryStruct
from plx.framework._types import BOOL, DINT, DWORD, LREAL, UDINT, WORD


# ===================================================================
# Enums (defined first — FBs reference these as parameter types)
# ===================================================================

class MC_BufferMode(LibraryEnum, vendor="beckhoff", library="Tc2_MC2"):
    """PLCopen buffer mode for queuing motion commands.

    Controls how a new motion command interacts with an active one.
    MC_Aborting cancels the current command; MC_Buffered queues it;
    blending modes merge the deceleration/acceleration profiles.
    """

    MC_Aborting = 0
    MC_Buffered = 1
    MC_BlendingLow = 2
    MC_BlendingPrevious = 3
    MC_BlendingNext = 4
    MC_BlendingHigh = 5


class MC_Direction(LibraryEnum, vendor="beckhoff", library="Tc2_MC2"):
    """Direction of motion for velocity and modulo moves.

    MC_Positive_Direction and MC_Negative_Direction force direction.
    MC_Shortest_Way picks the shorter path for modulo axes.
    MC_Current_Direction continues in the current travel direction.
    """

    MC_Positive_Direction = 1
    MC_Shortest_Way = 2
    MC_Negative_Direction = 3
    MC_Current_Direction = 4
    MC_Undefined_Direction = 128


class MC_HomingMode(LibraryEnum, vendor="beckhoff", library="Tc2_MC2"):
    """Homing mode selection for MC_Home.

    MC_DefaultHoming uses the axis's configured homing procedure.
    MC_Direct sets the position without physical homing travel.
    MC_ForceCalibration/MC_ResetCalibration control the calibration flag.
    """

    MC_DefaultHoming = 0
    MC_Direct = 1
    MC_ForceCalibration = 2
    MC_ResetCalibration = 3


class E_JogMode(LibraryEnum, vendor="beckhoff", library="Tc2_MC2"):
    """Jog mode selection for MC_Jog.

    STANDARD_SLOW/FAST use the axis's jog velocity parameters.
    CONTINOUS moves at the specified velocity while the jog button
    is held. INCHING moves a fixed distance per press.
    """

    MC_JOGMODE_STANDARD_SLOW = 0
    MC_JOGMODE_STANDARD_FAST = 1
    MC_JOGMODE_CONTINOUS = 2
    MC_JOGMODE_INCHING = 3
    MC_JOGMODE_INCHING_MODULO = 4


# ===================================================================
# Structs (defined before FBs that reference them)
# ===================================================================

class AXIS_REF(LibraryStruct, vendor="beckhoff", library="Tc2_MC2"):
    """Central axis reference handle passed to all MC function blocks.

    In TwinCAT the real AXIS_REF is a deeply nested structure containing
    NcToPlc, PlcToNc, and Status sub-structs with hundreds of fields
    (actual position, velocity, torque, drive status bits, etc.).
    This stub exposes only Status as a shallow placeholder — the
    simulator populates fields on demand.
    """

    Status: WORD


class ST_AxisStatus(LibraryStruct, vendor="beckhoff", library="Tc2_MC2"):
    """Axis status struct mirroring the PLCopen state machine flags.

    Each boolean field corresponds to a state or condition of the axis.
    Typically read via MC_ReadStatus or directly from AXIS_REF.Status.
    """

    UpdateTaskIndex: UDINT
    CycleCounter: UDINT
    Error: BOOL
    ErrorId: UDINT
    Disabled: BOOL
    Standstill: BOOL
    DiscreteMotion: BOOL
    ContinuousMotion: BOOL
    SynchronizedMotion: BOOL
    Homing: BOOL
    ConstantVelocity: BOOL
    Accelerating: BOOL
    Decelerating: BOOL
    Stopping: BOOL
    ErrorStop: BOOL
    NotMoving: BOOL
    Moving: BOOL
    HasBeenStopped: BOOL
    HasJob: BOOL
    Enabled: BOOL
    ControlLoopClosed: BOOL
    CamTableQueued: BOOL


class ST_MoveOptions(LibraryStruct, vendor="beckhoff", library="Tc2_MC2"):
    """Additional motion command options. Usually left at defaults.

    In TwinCAT this struct contains gap control, blending, and override
    settings. Most applications use the default (zero-initialized) values.
    """

    pass


class ST_HomingOptions(LibraryStruct, vendor="beckhoff", library="Tc2_MC2"):
    """Additional homing command options. Usually left at defaults.

    Contains settings for homing velocity, acceleration, and search
    direction. Most applications rely on the axis's configured defaults.
    """

    pass


# ===================================================================
# Function Blocks — Axis Administration
# ===================================================================

class MC_Power(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Enable or disable the servo drive (power stage) of an axis.

    Enable=TRUE requests servo on; Status=TRUE confirms the drive is
    enabled and ready for motion commands. Enable_Positive/Enable_Negative
    control directional enables. Override (0.0-1.0) scales velocity.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]
    Enable_Positive: Input[BOOL]
    Enable_Negative: Input[BOOL]
    Override: Input[LREAL]

    Status: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Simplified stand-in: Status follows Enable after 1 scan."""
        state["Status"] = state["Enable"]
        state["Active"] = state["Enable"]
        state["Busy"] = False
        state["Error"] = False
        state["ErrorID"] = 0
        state["CommandAborted"] = False


class MC_Reset(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Reset axis errors and transition from ErrorStop to Disabled state.

    Rising edge on Execute clears the axis error state. The axis must
    be re-enabled with MC_Power after a successful reset.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_SetPosition(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Set (shift) the axis position without physical movement.

    Used to define a new reference point. Mode=FALSE sets absolute
    position; Mode=TRUE adds a relative offset to the current position.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Position: Input[LREAL]
    Mode: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Status / Parameter
# ===================================================================

class MC_ReadActualPosition(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Continuously read the actual (encoder) position of an axis.

    Level-triggered: set Enable=TRUE to start reading, Valid=TRUE
    indicates Position output is current. Not edge-triggered.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]

    Valid: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]
    Position: Output[LREAL]


class MC_ReadActualVelocity(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Continuously read the actual velocity of an axis.

    Level-triggered: Enable=TRUE starts reading. ActualVelocity is
    updated every scan while Valid=TRUE.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]

    Valid: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]
    ActualVelocity: Output[LREAL]


class MC_ReadStatus(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Read the PLCopen state machine status of an axis.

    Level-triggered: Enable=TRUE starts reading. The output booleans
    reflect the current PLCopen state (exactly one is TRUE at a time
    under normal operation). Useful for state-dependent logic.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]

    Valid: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]
    ErrorStop: Output[BOOL]
    Disabled: Output[BOOL]
    Stopping: Output[BOOL]
    StandStill: Output[BOOL]
    DiscreteMotion: Output[BOOL]
    ContinuousMotion: Output[BOOL]
    SynchronizedMotion: Output[BOOL]
    Homing: Output[BOOL]


class MC_ReadAxisError(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Read the current error state of an axis.

    Level-triggered: Enable=TRUE starts monitoring. AxisError=TRUE
    indicates an active error; AxisErrorId provides the error code.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]

    Valid: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]
    AxisError: Output[BOOL]
    AxisErrorId: Output[UDINT]


class MC_SetOverride(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Set the velocity override factor for an axis.

    Level-triggered: Enable=TRUE activates the override. VelFactor
    (0.0 to 1.0) scales the commanded velocity of all active and
    future motion commands on this axis.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]
    VelFactor: Input[LREAL]

    Enabled: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Point-to-Point Motion
# ===================================================================

class MC_MoveAbsolute(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Move axis to an absolute target position.

    Rising edge on Execute starts the move. Jerk=0 selects trapezoidal
    acceleration profile; Jerk>0 selects S-curve. BufferMode controls
    queuing behavior when another command is active.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Position: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_MoveRelative(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Move axis a relative distance from the current position.

    Rising edge on Execute starts the move. Distance is added to the
    position at the moment of the rising edge. Positive distance moves
    in positive direction, negative in negative direction.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Distance: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_MoveAdditive(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Additive positioning — distance is added to the current target.

    Unlike MC_MoveRelative (which adds to the actual position at trigger
    time), MC_MoveAdditive adds Distance to the commanded target position
    of the previous motion command, enabling precise chained moves.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Distance: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_MoveModulo(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Modulo positioning for rotary axes.

    Moves to an absolute modulo position (within one revolution).
    Direction controls which way the axis travels to reach the target.
    MC_Shortest_Way picks the shorter rotation.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Position: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    Direction: Input[MC_Direction]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_MoveVelocity(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Start continuous velocity motion (no target position).

    Rising edge on Execute starts the move. The axis accelerates to the
    commanded Velocity and continues indefinitely. InVelocity=TRUE when
    the axis has reached the commanded speed.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    Direction: Input[MC_Direction]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    InVelocity: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_MoveContinuousAbsolute(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Non-stop move to an absolute position at a specified end velocity.

    Unlike MC_MoveAbsolute (which decelerates to zero at the target),
    this FB passes through the target position at EndVelocity without
    stopping. Used for blending between motion segments.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Position: Input[LREAL]
    Velocity: Input[LREAL]
    EndVelocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    InPosition: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_MoveContinuousRelative(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Non-stop relative move at a specified end velocity.

    Same as MC_MoveContinuousAbsolute but with a relative Distance
    instead of an absolute Position. The axis passes through the
    target without stopping.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Distance: Input[LREAL]
    Velocity: Input[LREAL]
    EndVelocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    InPosition: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Stop / Halt
# ===================================================================

class MC_Halt(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Controlled halt — decelerates axis to zero velocity.

    Unlike MC_Stop, MC_Halt allows new motion commands to be accepted
    while the axis is decelerating. The axis transitions to StandStill
    after reaching zero velocity.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_MoveOptions]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_Stop(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Emergency stop — decelerates axis and locks out new commands.

    While Execute is TRUE the axis is in Stopping state and rejects
    all other motion commands. New commands are accepted only after
    Execute is released AND the axis has reached StandStill.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Homing
# ===================================================================

class MC_Home(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Execute a homing (reference) sequence on an axis.

    HomingMode selects the procedure: MC_DefaultHoming runs the axis's
    configured homing routine (sensor search + index pulse), MC_Direct
    sets the reference without movement, MC_ForceCalibration marks the
    axis as calibrated, MC_ResetCalibration clears the calibration flag.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Position: Input[LREAL]
    HomingMode: Input[MC_HomingMode]
    BufferMode: Input[MC_BufferMode]
    Options: Input[ST_HomingOptions]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Manual
# ===================================================================

class MC_Jog(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Manual jog control for commissioning and setup.

    JogForward/JogBackward are level-triggered. Mode selects the jog
    behavior (standard slow/fast, continuous, or inching). In INCHING
    mode the axis moves a fixed distance per button press.
    """

    Axis: InOut[AXIS_REF]
    JogForward: Input[BOOL]
    JogBackward: Input[BOOL]
    Mode: Input[E_JogMode]
    Position: Input[LREAL]
    Velocity: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Coupling
# ===================================================================

class MC_GearIn(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Activate electronic gear coupling between master and slave axes.

    The slave follows the master at GearRatio = RatioNumerator /
    RatioDenominator. InGear=TRUE when the slave has synchronized.
    The slave accelerates to match the master's velocity profile.
    """

    Master: InOut[AXIS_REF]
    Slave: InOut[AXIS_REF]
    Execute: Input[BOOL]
    RatioNumerator: Input[DINT]
    RatioDenominator: Input[DINT]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]
    BufferMode: Input[MC_BufferMode]

    InGear: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_GearInDyn(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Dynamic gear coupling with continuously adjustable gear ratio.

    Unlike MC_GearIn (which uses fixed integer numerator/denominator),
    MC_GearInDyn accepts a floating-point GearRatio that can be changed
    while the coupling is active. InGear=TRUE when synchronized.
    """

    Master: InOut[AXIS_REF]
    Slave: InOut[AXIS_REF]
    Enable: Input[BOOL]
    GearRatio: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    InGear: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_GearOut(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Deactivate an electronic gear coupling on the slave axis.

    Rising edge on Execute decouples the slave from its master.
    The slave continues at its current velocity after decoupling.
    """

    Slave: InOut[AXIS_REF]
    Execute: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Touch Probe
# ===================================================================

class MC_TouchProbe(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Latch axis position on a hardware trigger event.

    Rising edge on Execute arms the probe. When TriggerInput fires,
    the axis position is captured in RecordedPosition with hardware
    timestamp precision. WindowOnly=TRUE restricts capture to a
    position window between FirstPosition and LastPosition.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    TriggerInput: Input[BOOL]
    WindowOnly: Input[BOOL]
    FirstPosition: Input[LREAL]
    LastPosition: Input[LREAL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]
    RecordedPosition: Output[LREAL]


class MC_AbortTrigger(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Abort an active touch probe trigger (disarm MC_TouchProbe).

    Rising edge on Execute cancels a pending probe trigger on the axis.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Advanced
# ===================================================================

class MC_MoveSuperImposed(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Superimpose a relative move on top of an active motion command.

    The superimposed Distance is added to the axis's current motion
    profile without aborting it. VelocityDiff is the maximum additional
    velocity. Useful for registration corrections and print-mark offsets.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Distance: Input[LREAL]
    VelocityDiff: Input[LREAL]
    Acceleration: Input[LREAL]
    Deceleration: Input[LREAL]
    Jerk: Input[LREAL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_TorqueControl(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Switch axis to torque (force) control mode.

    Rising edge on Execute activates torque control. Torque is the
    setpoint, TorqueRamp limits the rate of change, Velocity caps
    the maximum speed. InTorque=TRUE when the setpoint is reached.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    Torque: Input[LREAL]
    TorqueRamp: Input[LREAL]
    Velocity: Input[LREAL]
    Direction: Input[MC_Direction]
    BufferMode: Input[MC_BufferMode]

    InTorque: Output[BOOL]
    Busy: Output[BOOL]
    Active: Output[BOOL]
    CommandAborted: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


# ===================================================================
# Function Blocks — Parameter Read / Write
# ===================================================================

class MC_ReadParameter(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Read a single NC axis parameter by number.

    Level-triggered: Enable=TRUE starts continuous reading of the
    parameter identified by ParameterNumber. Valid=TRUE indicates
    the Value output is current. ReadMode selects one-shot (0) or
    cyclic (1) reading. Consult the Beckhoff NC parameter
    documentation for valid parameter numbers.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]
    ParameterNumber: Input[UDINT]
    ReadMode: Input[DINT]

    Valid: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[DWORD]
    Value: Output[LREAL]


class MC_ReadBoolParameter(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Read a boolean NC axis parameter by number.

    Level-triggered: Enable=TRUE starts continuous reading of the
    boolean parameter identified by ParameterNumber. Valid=TRUE
    indicates the Value output is current. ReadMode selects one-shot
    (0) or cyclic (1) reading.
    """

    Axis: InOut[AXIS_REF]
    Enable: Input[BOOL]
    ParameterNumber: Input[UDINT]
    ReadMode: Input[DINT]

    Valid: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]
    Value: Output[BOOL]


class MC_ReadParameterSet(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Read the full NC axis parameter set.

    Edge-triggered: rising edge on Execute reads all axis parameters.
    Done=TRUE indicates the parameter set has been successfully read
    and is available in the axis data.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_WriteParameter(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Write a single NC axis parameter by number.

    Rising edge on Execute writes Value to the parameter identified
    by ParameterNumber. Done=TRUE confirms the write completed
    successfully. The change is volatile — lost on power cycle.
    Use MC_WriteParameterPersistent for non-volatile writes.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    ParameterNumber: Input[UDINT]
    Value: Input[LREAL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_WriteBoolParameter(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Write a boolean NC axis parameter by number.

    Rising edge on Execute writes Value to the boolean parameter
    identified by ParameterNumber. Done=TRUE confirms the write
    completed successfully. The change is volatile — lost on
    power cycle. Use MC_WriteBoolParameterPersistent for
    non-volatile writes.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    ParameterNumber: Input[UDINT]
    Value: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_WriteParameterPersistent(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Write a single NC axis parameter and persist it across power cycles.

    Same interface as MC_WriteParameter but the value is saved to
    non-volatile storage. Rising edge on Execute writes Value to
    the parameter identified by ParameterNumber. Done=TRUE confirms
    the write and persistence completed successfully.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    ParameterNumber: Input[UDINT]
    Value: Input[LREAL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]


class MC_WriteBoolParameterPersistent(LibraryFB, vendor="beckhoff", library="Tc2_MC2"):
    """Write a boolean NC axis parameter and persist it across power cycles.

    Same interface as MC_WriteBoolParameter but the value is saved to
    non-volatile storage. Rising edge on Execute writes Value to the
    boolean parameter identified by ParameterNumber. Done=TRUE confirms
    the write and persistence completed successfully.
    """

    Axis: InOut[AXIS_REF]
    Execute: Input[BOOL]
    ParameterNumber: Input[UDINT]
    Value: Input[BOOL]

    Done: Output[BOOL]
    Busy: Output[BOOL]
    Error: Output[BOOL]
    ErrorID: Output[UDINT]

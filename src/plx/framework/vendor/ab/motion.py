"""Allen Bradley CIP Motion library stubs.

Rockwell Automation CIP Motion instructions for ControlLogix and
CompactLogix servo/drive control.  These are native RSLogix/Studio 5000
instructions — not PLCopen MC_ function blocks.

Available types:

Enums:
    MC_AB_Direction, MC_AB_MoveType, MC_AB_StopType

Structs:
    AXIS_SERVO, AXIS_SERVO_DRIVE, AXIS_CIP_DRIVE, AXIS_VIRTUAL,
    MOTION_INSTRUCTION, MOTION_GROUP, COORDINATE_SYSTEM

Motion State:
    MSO, MSF, MASD, MASR, MAFR

Motion Move:
    MAJ, MAM, MAS, MAH, MAG, MCD, MAHD

Cam / Position Cam:
    MAPC, MATC

Motion Group:
    MGS, MGSD, MGSR, MGSP

Motion Events:
    MAW, MDW, MAR, MDR, MAOC, MDOC

Coordinated Motion:
    MCLM, MCCM, MCCD, MCS, MCT

Note: do NOT use ``from __future__ import annotations`` in stub files —
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryEnum, LibraryFB, LibraryStruct
from plx.framework._types import BOOL, DINT, REAL

# ===================================================================
# Enums (defined first — FBs reference these as parameter types)
# ===================================================================


class MC_AB_Direction(LibraryEnum, vendor="ab", library="ab_motion"):
    """Motion direction for AB motion instructions.

    Prefixed MC_AB_ to avoid collision with Beckhoff MC_Direction.
    """

    forward = 0
    reverse = 1


class MC_AB_MoveType(LibraryEnum, vendor="ab", library="ab_motion"):
    """Absolute vs incremental move type for MAM instruction.

    absolute: move to an absolute target position.
    incremental: move a relative distance from the current position.
    """

    absolute = 0
    incremental = 1


class MC_AB_StopType(LibraryEnum, vendor="ab", library="ab_motion"):
    """Stop mode for MAS (Motion Axis Stop) instruction.

    controlled: decelerate to stop using programmed decel rate.
    fast_stop: maximum deceleration using drive capability.
    hard_stop: immediate disable of drive output (coast to stop).
    coast: remove torque and allow axis to coast.
    """

    controlled = 0
    fast_stop = 1
    hard_stop = 2
    coast = 3


# ===================================================================
# Structs (defined before FBs that reference them)
# ===================================================================


class AXIS_SERVO(LibraryStruct, vendor="ab", library="ab_motion"):
    """Servo axis tag for CIP-connected servo drive axes."""


class AXIS_SERVO_DRIVE(LibraryStruct, vendor="ab", library="ab_motion"):
    """Servo drive axis tag for integrated motion on CIP drives."""


class AXIS_CIP_DRIVE(LibraryStruct, vendor="ab", library="ab_motion"):
    """CIP drive axis tag. The standard axis type for modern CIP Motion systems."""


class AXIS_VIRTUAL(LibraryStruct, vendor="ab", library="ab_motion"):
    """Virtual axis tag for simulated axes with no physical drive."""


class MOTION_INSTRUCTION(LibraryStruct, vendor="ab", library="ab_motion"):
    """Status structure for motion instructions. Each motion instruction needs its own unique MOTION_INSTRUCTION tag.

    IP: Instruction in progress.
    AC: Axis is actively controlled by this instruction.
    PC: Process complete — move finished successfully.
    ER: Error occurred during instruction execution.
    Status: Detailed status code (DINT).
    """

    IP: BOOL
    AC: BOOL
    PC: BOOL
    ER: BOOL
    Status: DINT


class MOTION_GROUP(LibraryStruct, vendor="ab", library="ab_motion"):
    """Motion group tag. Groups axes for coordinated motion."""


class COORDINATE_SYSTEM(LibraryStruct, vendor="ab", library="ab_motion"):
    """Coordinate system tag for multi-axis coordinated motion."""


# ===================================================================
# Function Blocks — Motion State
# ===================================================================


class MSO(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Servo On — enables the servo drive.

    Activates closed-loop position control on the axis. The drive is
    energized and the axis transitions to the servo-enabled state.
    IP is set while the instruction is in progress; AC indicates the
    axis is actively controlled; PC confirms the servo is on.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MSF(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Servo Off — disables the servo drive.

    Removes power from the servo drive. The axis transitions to the
    servo-disabled state. The drive is de-energized and the motor
    is free to coast.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MASD(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Shutdown — controlled shutdown of an axis.

    Decelerates the axis to a stop at the specified DecelRate, then
    disables the servo drive. Used for orderly machine shutdown
    sequences where an immediate stop is not required.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    DecelRate: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MASR(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Shutdown Reset — resets an axis from shutdown state.

    Clears the shutdown condition and axis faults, allowing the axis
    to be re-enabled with MSO. Must be called after MASD before the
    axis can resume operation.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAFR(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Fault Reset — clears motion faults on an axis.

    Clears active fault conditions on the axis. Does not re-enable
    the servo — use MSO after MAFR to resume operation. Used to
    recover from drive faults, encoder errors, and position errors.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


# ===================================================================
# Function Blocks — Motion Move
# ===================================================================


class MAJ(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Jog — continuous jog at specified speed.

    Jogs the axis at the specified Speed until stopped by MAS or
    superseded by another motion instruction. Direction selects
    forward or reverse. AccelJerk/DecelJerk of 0 select trapezoidal
    profiles; nonzero values select S-curve profiles.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Direction: Input[DINT]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    AccelJerk: Input[REAL]
    DecelJerk: Input[REAL]
    MergeSpeed: Input[REAL]
    Merge: Input[DINT]
    LockDirection: Input[BOOL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAM(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Move — move to absolute or incremental position.

    Performs a point-to-point move. MoveType selects absolute (move to
    Position) or incremental (move Position distance from current).
    Speed, AccelRate, DecelRate control the motion profile. Merge and
    MergeSpeed control blending with active motion commands.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    MoveType: Input[DINT]
    Position: Input[REAL]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    AccelJerk: Input[REAL]
    DecelJerk: Input[REAL]
    Merge: Input[DINT]
    MergeSpeed: Input[REAL]
    LockPosition: Input[BOOL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAS(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Stop — stops axis motion.

    Stops the axis using the specified StopType:
    0 = controlled deceleration at DecelRate,
    1 = fast stop using maximum drive deceleration,
    2 = hard stop (immediate drive disable).
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    StopType: Input[DINT]
    DecelRate: Input[REAL]
    DecelJerk: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAH(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Home — execute homing sequence.

    Performs a homing (reference) sequence to establish the axis
    position reference. Speed and AccelRate/DecelRate control the
    homing travel profile. HomeMode selects the homing procedure.
    HomeLimitSwitch provides the home sensor input.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Position: Input[REAL]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    HomeMode: Input[DINT]
    HomeLimitSwitch: Input[BOOL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAG(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Gear — electronic gearing between master and slave.

    Establishes an electronic gear coupling where the slave axis
    follows the master axis at the ratio RatioNumerator/RatioDenominator.
    Direction controls whether the slave follows in the same or
    opposite direction. Clutch enables/disables the coupling dynamically.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MasterAxis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Direction: Input[DINT]
    RatioNumerator: Input[REAL]
    RatioDenominator: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    Clutch: Input[BOOL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MCD(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Change Dynamics — change speed/accel/decel of active move.

    Modifies the dynamics of a motion instruction that is currently
    in progress. The axis transitions smoothly to the new Speed,
    AccelRate, and DecelRate without stopping or aborting the move.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    AccelJerk: Input[REAL]
    DecelJerk: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAHD(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Apply Hookup Diagnostic — commissioning diagnostic.

    Used during commissioning to verify wiring and encoder
    configuration. Applies test signals to check motor phasing,
    encoder direction, and feedback integrity.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


# ===================================================================
# Function Blocks — Cam / Position Cam
# ===================================================================


class MAPC(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Position Cam — position-based cam profile.

    Establishes a cam coupling where the slave axis follows a
    position-based cam profile relative to the master axis.
    ExecutionMode controls whether the cam runs once or repeats.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MasterAxis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Direction: Input[DINT]
    ExecutionMode: Input[DINT]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MATC(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Axis Time Cam — time-based cam profile.

    Establishes a cam coupling where the slave axis follows a
    time-based cam profile. The cam position is a function of
    elapsed time rather than a master axis position.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Direction: Input[DINT]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


# ===================================================================
# Function Blocks — Motion Group
# ===================================================================


class MGS(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Group Stop — stops all axes in a motion group.

    Simultaneously stops all axes in the specified motion group.
    Used for group-level emergency stop or coordinated shutdown.
    """

    Group: InOut[MOTION_GROUP]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MGSD(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Group Shutdown — controlled shutdown of all group axes.

    Performs an orderly shutdown of all axes in the motion group,
    decelerating each to a stop before disabling servo drives.
    """

    Group: InOut[MOTION_GROUP]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MGSR(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Group Shutdown Reset — resets group from shutdown state.

    Clears the shutdown condition for all axes in the motion group,
    allowing them to be re-enabled individually with MSO.
    """

    Group: InOut[MOTION_GROUP]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MGSP(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Group Strobe Position — capture all group axis positions.

    Simultaneously captures the actual positions of all axes in the
    motion group. Used for coordinated position measurement and
    synchronization verification.
    """

    Group: InOut[MOTION_GROUP]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


# ===================================================================
# Function Blocks — Motion Events
# ===================================================================


class MAW(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Arm Watch — arm a watch position event.

    Arms a position-based event that triggers when the axis crosses
    the specified Position. Used for precise position-triggered
    actions such as firing outputs at specific points in a move.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Position: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MDW(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Disarm Watch — disarm a watch position event.

    Cancels a previously armed watch position event on the axis.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAR(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Arm Registration — arm registration event for high-speed position capture.

    Arms a hardware registration event that captures the axis position
    with high precision when a registration sensor fires. Used for
    print registration, cut-to-length, and mark-to-mark applications.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MDR(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Disarm Registration — disarm a registration event.

    Cancels a previously armed registration event on the axis.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MAOC(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Arm Output Cam — arm a position-based output cam.

    Arms a cam-driven output that toggles based on the axis position.
    The output cam activates and deactivates at configured position
    thresholds, enabling high-speed position-synchronized outputs.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MDOC(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Disarm Output Cam — disarm a position-based output cam.

    Cancels a previously armed output cam on the axis.
    """

    Axis: InOut[AXIS_CIP_DRIVE]
    MotionControl: InOut[MOTION_INSTRUCTION]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


# ===================================================================
# Function Blocks — Coordinated Motion
# ===================================================================


class MCLM(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Coordinated Linear Move — linear multi-axis move.

    Performs a linear coordinated move where all axes in the
    coordinate system start and stop together, maintaining a
    straight-line path. MoveType selects absolute or incremental.
    """

    CoordSystem: InOut[COORDINATE_SYSTEM]
    MotionControl: InOut[MOTION_INSTRUCTION]
    MoveType: Input[DINT]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    AccelJerk: Input[REAL]
    DecelJerk: Input[REAL]
    Merge: Input[DINT]
    MergeSpeed: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MCCM(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Coordinated Circular Move — circular multi-axis move.

    Performs a circular arc move in the coordinate system. Direction
    selects clockwise or counterclockwise. Radius specifies the arc
    radius. The move interpolates a circular path through the axes.
    """

    CoordSystem: InOut[COORDINATE_SYSTEM]
    MotionControl: InOut[MOTION_INSTRUCTION]
    MoveType: Input[DINT]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]
    Direction: Input[DINT]
    Radius: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MCCD(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Coordinated Change Dynamics — change dynamics of coordinated move.

    Modifies the speed, acceleration, and deceleration of a
    coordinated motion instruction that is currently in progress.
    """

    CoordSystem: InOut[COORDINATE_SYSTEM]
    MotionControl: InOut[MOTION_INSTRUCTION]
    Speed: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MCS(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Coordinated Stop — stop coordinated motion.

    Stops all axes in the coordinate system. StopType controls
    the stop behavior (controlled decel, fast stop, etc.).
    DecelRate specifies the deceleration rate for controlled stops.
    """

    CoordSystem: InOut[COORDINATE_SYSTEM]
    MotionControl: InOut[MOTION_INSTRUCTION]
    StopType: Input[DINT]
    DecelRate: Input[REAL]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]


class MCT(LibraryFB, vendor="ab", library="ab_motion"):
    """Motion Coordinated Transform — transform between coordinate systems.

    Establishes a transform between source and target coordinate
    systems. Supports robot kinematics (Cartesian, delta, SCARA, etc.)
    via TransformType selection. Enables programming in Cartesian
    coordinates while the controller handles the kinematic conversion.
    """

    SourceSystem: InOut[COORDINATE_SYSTEM]
    TargetSystem: InOut[COORDINATE_SYSTEM]
    MotionControl: InOut[MOTION_INSTRUCTION]
    TransformType: Input[DINT]

    IP: Output[BOOL]
    AC: Output[BOOL]
    PC: Output[BOOL]
    ER: Output[BOOL]

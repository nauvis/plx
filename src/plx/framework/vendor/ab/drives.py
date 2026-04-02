"""Allen Bradley drives, filter, statistics, and enhanced timer library stubs.

AB-specific function blocks from the ControlLogix/CompactLogix instruction
set (1756-RM006).  These are ST/FBD instructions — not available in ladder.

Available types:

Backing Structs:
    FBD_TIMER, FBD_ONESHOT, MESSAGE

Enhanced Timers:
    TONR, TOFR, RTOR

One-Shot:
    OSRI, OSFI

Filters:
    HPF, LPF, NTCH, DERV, INTG

Statistics:
    MAVE, MSTD, MAXC, MINC

Drives / Control:
    PMUL, SCRV, PI, SOC, UPDN, CC

I/O:
    MSG

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB, LibraryStruct
from plx.framework._types import BOOL, DINT, REAL

# ===================================================================
# Backing Structs
# ===================================================================


class FBD_TIMER(LibraryStruct, vendor="ab", library="ab_drives"):
    """Backing structure for enhanced timer instructions (TONR, TOFR, RTOR).

    Contains the timer preset, accumulator, and status bits.  In Logix
    this structure is allocated automatically when the timer FB is
    instantiated.
    """

    PRE: DINT
    ACC: DINT
    EN: BOOL
    TT: BOOL
    DN: BOOL


class FBD_ONESHOT(LibraryStruct, vendor="ab", library="ab_drives"):
    """Backing structure for one-shot instructions (OSRI, OSFI).

    Holds the input and output bits used by the one-shot FBs.
    """

    InputBit: BOOL
    OutputBit: BOOL


# ===================================================================
# Enhanced Timers (AB-specific, ST/FBD only)
# ===================================================================


class TONR(LibraryFB, vendor="ab", library="ab_drives"):
    """Non-retentive timer on delay with built-in reset input.

    Uses FBD_TIMER backing structure.  Timer accumulates while
    TimerEnable is TRUE.  When ACC reaches PRE, DN is set TRUE.
    The Reset input clears ACC to zero and resets all status bits.
    Unlike the standard TON, TONR is non-retentive -- ACC resets
    to zero when TimerEnable goes FALSE (unless DN is already set).
    """

    TimerEnable: Input[BOOL]
    PRE: Input[DINT]
    Reset: Input[BOOL]

    ACC: Output[DINT]
    EN: Output[BOOL]
    TT: Output[BOOL]
    DN: Output[BOOL]


class TOFR(LibraryFB, vendor="ab", library="ab_drives"):
    """Off-delay timer with reset.

    Uses FBD_TIMER backing structure.  Starts timing when TimerEnable
    goes FALSE.  While TimerEnable is TRUE, EN and DN are TRUE and ACC
    is zero.  When TimerEnable goes FALSE, the timer begins accumulating.
    DN remains TRUE until ACC reaches PRE.  Reset clears ACC and all
    status bits.
    """

    TimerEnable: Input[BOOL]
    PRE: Input[DINT]
    Reset: Input[BOOL]

    ACC: Output[DINT]
    EN: Output[BOOL]
    TT: Output[BOOL]
    DN: Output[BOOL]


class RTOR(LibraryFB, vendor="ab", library="ab_drives"):
    """Retentive timer on delay with reset.

    Uses FBD_TIMER backing structure.  Retains ACC when TimerEnable
    goes FALSE.  Resumes accumulating from the retained value when
    TimerEnable is re-enabled.  ACC is only cleared via the Reset
    input.  DN is set when ACC reaches PRE and remains set until
    Reset is asserted.
    """

    TimerEnable: Input[BOOL]
    PRE: Input[DINT]
    Reset: Input[BOOL]

    ACC: Output[DINT]
    EN: Output[BOOL]
    TT: Output[BOOL]
    DN: Output[BOOL]


# ===================================================================
# One-Shot (AB-specific, ST/FBD only)
# ===================================================================


class OSRI(LibraryFB, vendor="ab", library="ab_drives"):
    """One-shot rising with input.

    OutputBit is TRUE for exactly one scan on the false-to-true
    transition (rising edge) of InputBit.  This is the ST/FBD
    equivalent of the ladder OSR instruction.  Uses FBD_ONESHOT
    backing structure.
    """

    InputBit: Input[BOOL]

    OutputBit: Output[BOOL]


class OSFI(LibraryFB, vendor="ab", library="ab_drives"):
    """One-shot falling with input.

    OutputBit is TRUE for exactly one scan on the true-to-false
    transition (falling edge) of InputBit.  This is the ST/FBD
    equivalent of the ladder OSF instruction.  Uses FBD_ONESHOT
    backing structure.
    """

    InputBit: Input[BOOL]

    OutputBit: Output[BOOL]


# ===================================================================
# Filters (1756-RM006, ST/FBD only)
# ===================================================================


class HPF(LibraryFB, vendor="ab", library="ab_drives"):
    """First-order high pass filter.

    Passes high-frequency components and attenuates low-frequency
    signals.  Configure the cutoff via FilterFrequency (Hz).
    Commonly used to remove DC offset or slow drift from a signal
    before further processing.
    """

    In: Input[REAL]
    FilterFrequency: Input[REAL]

    Out: Output[REAL]


class LPF(LibraryFB, vendor="ab", library="ab_drives"):
    """First-order low pass filter.

    Attenuates high-frequency noise while passing low-frequency
    signal content.  Commonly used to filter noisy analog sensor
    readings before PID processing.  Configure the cutoff via
    FilterFrequency (Hz).
    """

    In: Input[REAL]
    FilterFrequency: Input[REAL]

    Out: Output[REAL]


class NTCH(LibraryFB, vendor="ab", library="ab_drives"):
    """Band-reject (notch) filter.

    Attenuates a narrow frequency band centered at NotchFrequency.
    Q controls the bandwidth of the rejection band -- higher Q
    gives a narrower notch.  Used to suppress mechanical resonance
    or electrical interference at a known frequency.
    """

    In: Input[REAL]
    NotchFrequency: Input[REAL]
    Q: Input[REAL]

    Out: Output[REAL]


class DERV(LibraryFB, vendor="ab", library="ab_drives"):
    """Time-based derivative (rate of change) with noise filter.

    Computes the derivative of the input signal, scaled by Gain.
    FilterFrequency provides a built-in low pass filter on the
    derivative output to reduce noise amplification.  Output
    units are input-units per second multiplied by Gain.
    """

    In: Input[REAL]
    Gain: Input[REAL]
    FilterFrequency: Input[REAL]

    Out: Output[REAL]


class INTG(LibraryFB, vendor="ab", library="ab_drives"):
    """Time-based integrator with output limits and reset.

    Integrates the input signal over time.  Output is clamped
    between LLimit and HLimit to prevent windup.  Reset clears
    the accumulated integral to zero.
    """

    In: Input[REAL]
    HLimit: Input[REAL]
    LLimit: Input[REAL]
    Reset: Input[BOOL]

    Out: Output[REAL]


# ===================================================================
# Statistics (1756-RM006, ST/FBD only)
# ===================================================================


class MAVE(LibraryFB, vendor="ab", library="ab_drives"):
    """Moving average over a configurable sample window.

    Computes a rolling average of the last NumberOfSamples input
    values.  Each scan adds one sample.  Reset clears the sample
    buffer and restarts the average calculation.
    """

    In: Input[REAL]
    NumberOfSamples: Input[DINT]
    Reset: Input[BOOL]

    Out: Output[REAL]


class MSTD(LibraryFB, vendor="ab", library="ab_drives"):
    """Moving standard deviation over a configurable sample window.

    Computes the rolling standard deviation of the last
    NumberOfSamples input values.  Reset clears the sample buffer.
    """

    In: Input[REAL]
    NumberOfSamples: Input[DINT]
    Reset: Input[BOOL]

    Out: Output[REAL]


class MAXC(LibraryFB, vendor="ab", library="ab_drives"):
    """Maximum capture -- tracks the highest input value seen.

    Out holds the maximum value of In observed since the last
    Reset.  Assert Reset to restart tracking from the current
    input value.
    """

    In: Input[REAL]
    Reset: Input[BOOL]

    Out: Output[REAL]


class MINC(LibraryFB, vendor="ab", library="ab_drives"):
    """Minimum capture -- tracks the lowest input value seen.

    Out holds the minimum value of In observed since the last
    Reset.  Assert Reset to restart tracking from the current
    input value.
    """

    In: Input[REAL]
    Reset: Input[BOOL]

    Out: Output[REAL]


# ===================================================================
# Drives / Control (1756-RM006, ST/FBD only)
# ===================================================================


class PMUL(LibraryFB, vendor="ab", library="ab_drives"):
    """Pulse multiplier.

    Scales a pulse count input by Multiplier / Divisor.  Used for
    encoder pulse scaling when the mechanical ratio between the
    encoder and the measured quantity is not 1:1.
    """

    In: Input[DINT]
    Multiplier: Input[REAL]
    Divisor: Input[REAL]

    Out: Output[DINT]


class SCRV(LibraryFB, vendor="ab", library="ab_drives"):
    """S-curve profile generator.

    Produces a smooth motion profile with configurable jerk, accel,
    and decel rates.  The output ramps from current value toward the
    input setpoint using an S-curve (jerk-limited) profile.  InAccel
    and InDecel indicate the current profile phase.
    """

    In: Input[REAL]
    JerkRate: Input[REAL]
    AccelRate: Input[REAL]
    DecelRate: Input[REAL]

    Out: Output[REAL]
    InAccel: Output[BOOL]
    InDecel: Output[BOOL]


class PI(LibraryFB, vendor="ab", library="ab_drives"):
    """Simplified proportional + integral controller.

    A lightweight PI loop without derivative action.  Computes
    CV = PGain * error + IGain * integral(error).  CV is clamped
    between CVLLimit and CVHLimit.  Suitable for simpler control
    loops that do not require full PIDE functionality.
    """

    PV: Input[REAL]
    SP: Input[REAL]
    PGain: Input[REAL]
    IGain: Input[REAL]
    CVHLimit: Input[REAL]
    CVLLimit: Input[REAL]

    CV: Output[REAL]


class SOC(LibraryFB, vendor="ab", library="ab_drives"):
    """Second-order controller.

    Implements a second-order transfer function parameterized by
    NaturalFrequency, DampingRatio, and Gain.  Used for vibration
    suppression, notch compensation, and advanced loop shaping.
    """

    In: Input[REAL]
    NaturalFrequency: Input[REAL]
    DampingRatio: Input[REAL]
    Gain: Input[REAL]

    Out: Output[REAL]


class UPDN(LibraryFB, vendor="ab", library="ab_drives"):
    """Up/down accumulator.

    Increments Out on each scan where InUp is TRUE, decrements on
    each scan where InDown is TRUE.  Output is clamped between
    LLimit and HLimit.  Reset clears the accumulator to zero.
    """

    InUp: Input[BOOL]
    InDown: Input[BOOL]
    HLimit: Input[REAL]
    LLimit: Input[REAL]
    Reset: Input[BOOL]

    Out: Output[REAL]


class CC(LibraryFB, vendor="ab", library="ab_drives"):
    """Coordinated control.

    Coordinates two control outputs to drive two process variables
    toward their respective targets.  Gain controls the coupling
    strength between the two loops.  Used for cross-coupled control
    applications such as tension/speed coordination.
    """

    In1: Input[REAL]
    In2: Input[REAL]
    Target1: Input[REAL]
    Target2: Input[REAL]
    Gain: Input[REAL]

    Out1: Output[REAL]
    Out2: Output[REAL]


# ===================================================================
# I/O — MESSAGE struct and MSG instruction
# ===================================================================


class MESSAGE(LibraryStruct, vendor="ab", library="ab_io"):
    """MESSAGE structure for the MSG instruction.

    Complex internal structure used by CIP messaging.  Key status
    fields (.DN, .ER, .EN, .ERR) are accessed as member references
    on the MESSAGE tag in user logic.
    """

    # Complex internal structure -- key status accessed via .DN, .ER, .EN, .ERR


class MSG(LibraryFB, vendor="ab", library="ab_drives"):
    """Asynchronous CIP messaging between controllers.

    Sends or receives data to/from remote controllers over CIP
    (EtherNet/IP, ControlNet, or backplane).  Executes on a
    false-to-true transition of the enable rung/input.  Check DN
    for successful completion or ER for error.  ERR contains the
    error code on failure.

    Max 16 concurrent messages on standard controllers (64+ on
    5580-series).  MessageType selects the CIP service (read, write,
    etc.).  ConnectedFlag controls connected vs. unconnected messaging.
    """

    MessageType: Input[DINT]
    RequestedLength: Input[DINT]
    ConnectedFlag: Input[BOOL]

    DN: Output[BOOL]
    EN: Output[BOOL]
    ER: Output[BOOL]
    ERR: Output[DINT]

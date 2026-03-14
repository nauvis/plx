"""Allen Bradley process control library stubs.

Rockwell Automation process control and loop instructions from the
ControlLogix/CompactLogix instruction set (1756-RM006).  These are
Add-On Instructions (AOIs) and built-in instructions used in
continuous and batch process applications.

Available types:

PID:
    PIDE (Enhanced PID)

Scaling:
    SCL (Scale)

Alarms:
    ALMD (Digital Alarm), ALMA (Analog Alarm)

Profile:
    RMPS (Ramp/Soak)

Valve / Actuator:
    POSP (Position Proportional), SRTP (Split Range Time Proportional),
    D2SD (Discrete 2-State Device), D3SD (Discrete 3-State Device)

Dynamic Compensation:
    LDLG (Lead-Lag), DEDT (Deadtime)

Function Generator:
    FGEN (Piecewise Linear Function Generator)

Totalizer:
    TOT (Totalizer)

Select / Mux:
    SEL (Select), MUX (Multiplexer), ESEL (Enhanced Select)

Limit / Clamp:
    HLL (High/Low Limit), RLIM (Rate Limiter)

Math:
    SNEG (Selected Negate), SSUM (Selected Summer)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DINT, REAL


# ===================================================================
# PID
# ===================================================================

class PIDE(LibraryFB, vendor="ab", library="ab_process"):
    """Enhanced PID controller (PIDE) -- the core Rockwell process control FB.

    Implements a full-featured ISA-standard PID algorithm with support for
    independent (ISA/parallel), dependent, and velocity forms.  Provides
    comprehensive anti-windup protection, bumpless transfer between modes,
    and flexible setpoint/CV sourcing.

    Operating modes:
    - **Program/Operator**: determines who (program or operator) controls
      the setpoint and CV source.  ProgProgReq/ProgOperReq select from the
      program side; operator requests come from HMI faceplate writes.
    - **Auto/Manual/Cascade/Override/Hand**: the control mode.  In Auto,
      the PIDE calculates CV from PV and SP.  In Manual, CV is directly
      written.  Cascade accepts SP from an upstream loop.  Override forces
      CV from an external source.  Hand bypasses everything (hardwired).

    Setpoint tracking:
    - SPProg / SPOper / SPCascade feed into the active SP based on mode.
    - SPHLimit / SPLLimit clamp the active setpoint.

    CV limiting:
    - CVHLimit / CVLLimit clamp the control variable output.
    - CVROCPosLimit / CVROCNegLimit limit the rate of change of CV.
    - CVEUMax / CVEUMin define the engineering-unit range for CV scaling.

    PV monitoring:
    - PVHHAlarm / PVHAlarm / PVLAlarm / PVLLAlarm flag high-high, high,
      low, and low-low process variable excursions.
    - PVROCPosAlarm / PVROCNegAlarm flag excessive rate-of-change.
    - PVEUMax / PVEUMin define the engineering-unit range for PV scaling.

    Tuning parameters:
    - PGain: proportional gain (dimensionless).
    - IGain: integral gain (repeats/minute or 1/seconds depending on config).
    - DGain: derivative gain (minutes).
    - FF: feed-forward input added directly to CV.

    Anti-windup:
    - Integral action is automatically clamped when CV hits limits.
    - Bumpless transfer ensures smooth transitions between Auto/Manual
      and Program/Operator modes.

    Typical usage::

        @fb(target=ab)
        class TemperatureLoop:
            pid: PIDE
            pv: Input[REAL]
            sp: Input[REAL]
            cv: Output[REAL]

            def logic(self):
                self.pid(PV=self.pv, SPProg=self.sp,
                         PGain=1.2, IGain=0.5, DGain=0.1,
                         CVHLimit=100.0, CVLLimit=0.0,
                         ProgAutoReq=True, ProgProgReq=True)
                self.cv = self.pid.CV
    """

    # --- Inputs ---
    PV: Input[REAL]
    SPProg: Input[REAL]
    SPOper: Input[REAL]
    SPCascade: Input[REAL]
    CVProg: Input[REAL]
    CVOper: Input[REAL]
    FF: Input[REAL]
    PGain: Input[REAL]
    IGain: Input[REAL]
    DGain: Input[REAL]
    PVHLimit: Input[REAL]
    PVLLimit: Input[REAL]
    CVHLimit: Input[REAL]
    CVLLimit: Input[REAL]
    CVROCPosLimit: Input[REAL]
    CVROCNegLimit: Input[REAL]
    CVEUMax: Input[REAL]
    CVEUMin: Input[REAL]
    PVEUMax: Input[REAL]
    PVEUMin: Input[REAL]
    SPHLimit: Input[REAL]
    SPLLimit: Input[REAL]
    ProgProgReq: Input[BOOL]
    ProgOperReq: Input[BOOL]
    ProgCasRat: Input[BOOL]
    ProgAutoReq: Input[BOOL]
    ProgManualReq: Input[BOOL]
    ProgOverrideReq: Input[BOOL]
    ProgHandReq: Input[BOOL]

    # --- Outputs ---
    SP: Output[REAL]
    CV: Output[REAL]
    CVInitializing: Output[BOOL]
    CVHAlarm: Output[BOOL]
    CVLAlarm: Output[BOOL]
    PVHHAlarm: Output[BOOL]
    PVHAlarm: Output[BOOL]
    PVLAlarm: Output[BOOL]
    PVLLAlarm: Output[BOOL]
    PVROCPosAlarm: Output[BOOL]
    PVROCNegAlarm: Output[BOOL]
    InAuto: Output[BOOL]
    InCascade: Output[BOOL]
    InManual: Output[BOOL]


# ===================================================================
# Scaling
# ===================================================================

class SCL(LibraryFB, vendor="ab", library="ab_process"):
    """Linear analog scaling (SCL).

    Performs a simple linear transformation from one engineering-unit
    range to another:

        Out = (In - InMin) * (OutMax - OutMin) / (InMax - InMin) + OutMin

    Commonly used to convert raw analog input counts to engineering units
    (e.g., 0-32767 counts to 0.0-100.0 PSI) or to rescale between
    different engineering-unit ranges.

    Typical usage::

        @fb(target=ab)
        class PressureScaling:
            scaler: SCL
            raw_counts: Input[REAL]
            pressure_psi: Output[REAL]

            def logic(self):
                self.scaler(In=self.raw_counts,
                            InMin=0.0, InMax=32767.0,
                            OutMin=0.0, OutMax=100.0)
                self.pressure_psi = self.scaler.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    InMin: Input[REAL]
    InMax: Input[REAL]
    OutMin: Input[REAL]
    OutMax: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Linear interpolation: Out = (In - InMin) * (OutMax - OutMin) / (InMax - InMin) + OutMin."""
        in_range = state["InMax"] - state["InMin"]
        if in_range == 0.0:
            state["Out"] = state["OutMin"]
        else:
            state["Out"] = (
                (state["In"] - state["InMin"])
                * (state["OutMax"] - state["OutMin"])
                / in_range
                + state["OutMin"]
            )


# ===================================================================
# Alarms
# ===================================================================

class ALMD(LibraryFB, vendor="ab", library="ab_process"):
    """Digital alarm (ALMD) -- discrete condition monitoring.

    Monitors a boolean input condition and manages the alarm lifecycle
    including latching, acknowledgement, shelving, and suppression.
    Integrates with Rockwell's alarm and events infrastructure for
    FactoryTalk View alarm summaries and historian logging.

    Alarm states:
    - **Normal**: In=FALSE, no alarm condition present.
    - **InAlarm**: In=TRUE (or latched TRUE), alarm condition active.
    - **Acked**: operator has acknowledged the alarm via ProgAck or HMI.
    - **Shelved**: alarm is temporarily suppressed (still detected but
      not annunciated).  Shelving is time-limited and auto-expires.
    - **Disabled**: alarm detection is turned off entirely.

    Severity (0-1000) controls alarm priority and sorting in alarm
    summaries.  Higher values = more critical.

    Typical usage::

        @fb(target=ab)
        class HighPressureAlarm:
            alarm: ALMD
            pressure_high: Input[BOOL]
            alarm_active: Output[BOOL]

            def logic(self):
                self.alarm(In=self.pressure_high, Severity=500)
                self.alarm_active = self.alarm.InAlarm
    """

    # --- Inputs ---
    In: Input[BOOL]
    ProgAck: Input[BOOL]
    ProgReset: Input[BOOL]
    ProgDisable: Input[BOOL]
    ProgEnable: Input[BOOL]
    Severity: Input[DINT]

    # --- Outputs ---
    InAlarm: Output[BOOL]
    Acked: Output[BOOL]
    Shelved: Output[BOOL]
    Disabled: Output[BOOL]


class ALMA(LibraryFB, vendor="ab", library="ab_process"):
    """Analog alarm (ALMA) -- analog limit monitoring with multiple thresholds.

    Monitors a REAL input against up to four level thresholds (HH, H, L, LL)
    and two rate-of-change thresholds (ROCPos, ROCNeg).  Each condition has
    independent enable, severity, and deadband settings.

    Alarm levels:
    - **HHInAlarm**: In >= HHLimit (high-high, most critical).
    - **HInAlarm**: In >= HLimit (high warning).
    - **LInAlarm**: In <= LLimit (low warning).
    - **LLInAlarm**: In <= LLLimit (low-low, most critical).
    - **ROCPosInAlarm**: rate of increase exceeds ROCPosLimit per ROCPeriod.
    - **ROCNegInAlarm**: rate of decrease exceeds ROCNegLimit per ROCPeriod.

    Deadband prevents alarm chatter near thresholds.  An alarm activates
    when the input crosses the limit, but does not clear until the input
    returns past the limit minus the deadband.

    Each alarm condition has its own severity (0-1000) for priority sorting.

    Typical usage::

        @fb(target=ab)
        class TankLevelAlarms:
            alarm: ALMA
            level: Input[REAL]

            def logic(self):
                self.alarm(In=self.level,
                           HHLimit=95.0, HLimit=85.0,
                           LLimit=15.0, LLLimit=5.0,
                           Deadband=2.0,
                           HHSeverity=1000, HSeverity=500,
                           LSeverity=500, LLSeverity=1000)
    """

    # --- Inputs ---
    In: Input[REAL]
    HHLimit: Input[REAL]
    HLimit: Input[REAL]
    LLimit: Input[REAL]
    LLLimit: Input[REAL]
    Deadband: Input[REAL]
    ROCPosLimit: Input[REAL]
    ROCNegLimit: Input[REAL]
    ROCPeriod: Input[REAL]
    HHSeverity: Input[DINT]
    HSeverity: Input[DINT]
    LSeverity: Input[DINT]
    LLSeverity: Input[DINT]
    ProgAck: Input[BOOL]
    ProgReset: Input[BOOL]
    ProgDisable: Input[BOOL]
    ProgEnable: Input[BOOL]

    # --- Outputs ---
    InAlarm: Output[BOOL]
    HHInAlarm: Output[BOOL]
    HInAlarm: Output[BOOL]
    LInAlarm: Output[BOOL]
    LLInAlarm: Output[BOOL]
    ROCPosInAlarm: Output[BOOL]
    ROCNegInAlarm: Output[BOOL]
    Acked: Output[BOOL]
    Shelved: Output[BOOL]
    Disabled: Output[BOOL]


# ===================================================================
# Profile
# ===================================================================

class RMPS(LibraryFB, vendor="ab", library="ab_process"):
    """Ramp/Soak profile controller (RMPS).

    Generates a time-based setpoint profile consisting of ramp segments
    (linear transitions between temperatures) and soak segments (hold at
    a target temperature for a specified duration).  Supports up to 16
    segments for complex heat-treat, kiln, and furnace profiles.

    Profile execution:
    - **Start**: begins profile execution from segment 1.
    - **Hold**: pauses the profile at the current setpoint; the soak timer
      is suspended.  Useful for operator intervention.
    - **Resume**: continues from the held position.
    - **Complete**: signals that the profile has finished all segments.

    Guaranteed soak:
    - When GuarSetpoint is configured, the soak timer does not count
      unless the process variable is within the guaranteed soak band
      around the target setpoint.  This ensures the process actually
      reaches temperature before the soak time starts counting.

    Program/Operator mode:
    - ProgProgReq / ProgOperReq select whether the program or operator
      controls profile execution commands.

    Typical usage::

        @fb(target=ab)
        class KilnProfile:
            ramp_soak: RMPS
            kiln_temp: Input[REAL]
            sp_out: Output[REAL]

            def logic(self):
                self.ramp_soak(In=self.kiln_temp,
                               ProgStart=True, ProgProgReq=True,
                               NumberOfSegs=4, GuarSetpoint=5.0)
                self.sp_out = self.ramp_soak.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    ProgProgReq: Input[BOOL]
    ProgOperReq: Input[BOOL]
    ProgStart: Input[BOOL]
    ProgHold: Input[BOOL]
    ProgResume: Input[BOOL]
    ProgComplete: Input[BOOL]
    NumberOfSegs: Input[DINT]
    GuarSetpoint: Input[REAL]
    SoakTimeProg: Input[DINT]

    # --- Outputs ---
    Out: Output[REAL]
    SegNumber: Output[DINT]
    SegType: Output[DINT]
    Guaranteed: Output[BOOL]
    InHold: Output[BOOL]
    Complete: Output[BOOL]
    Faulted: Output[BOOL]


# ===================================================================
# Valve / Actuator
# ===================================================================

class POSP(LibraryFB, vendor="ab", library="ab_process"):
    """Position proportional valve control (POSP).

    Controls a valve or damper actuator using raise/lower pulse outputs
    to drive a motor-operated valve to a target position.  The position
    demand (In) is compared against position feedback (PositionFdbk) to
    determine whether to raise or lower.

    The DeadBand parameter defines an acceptable error band around the
    setpoint -- no action is taken when the position is within the
    deadband, which prevents continuous hunting.

    StrokeTime defines the full-stroke travel time (seconds) and is used
    to calculate pulse duration.  OpenedFdbk and ClosedFdbk are limit
    switch inputs that indicate the valve has reached its end positions.

    Outputs:
    - Raise: TRUE to drive valve toward open.
    - Lower: TRUE to drive valve toward closed.
    - Position: calculated or feedback-based current position.

    Typical usage::

        @fb(target=ab)
        class DamperControl:
            positioner: POSP
            demand: Input[REAL]
            position_fdbk: Input[REAL]
            raise_cmd: Output[BOOL]
            lower_cmd: Output[BOOL]

            def logic(self):
                self.positioner(In=self.demand,
                                PositionFdbk=self.position_fdbk,
                                DeadBand=2.0, StrokeTime=30.0)
                self.raise_cmd = self.positioner.Raise
                self.lower_cmd = self.positioner.Lower
    """

    # --- Inputs ---
    In: Input[REAL]
    PositionFdbk: Input[REAL]
    DeadBand: Input[REAL]
    OpenedFdbk: Input[BOOL]
    ClosedFdbk: Input[BOOL]
    StrokeTime: Input[REAL]

    # --- Outputs ---
    Raise: Output[BOOL]
    Lower: Output[BOOL]
    Position: Output[REAL]


class SRTP(LibraryFB, vendor="ab", library="ab_process"):
    """Split range time proportional output (SRTP).

    Converts a continuous 0-100% control signal into pulsed discrete
    outputs suitable for heating/cooling applications.  The input signal
    is split into two ranges: one for heating (Out1) and one for cooling
    (Out2), with a configurable split point.

    Time proportioning:
    - CyclePeriod defines the on/off cycle time (seconds).
    - The duty cycle within each period is proportional to the input
      signal magnitude within that output's range.

    Split range:
    - SplitRangeHL (high limit) and SplitRangeLL (low limit) define the
      boundary between Out1 and Out2 operation.
    - Typically SplitRangeLL=50.0 and SplitRangeHL=50.0 for a 50/50 split
      where 0-50% drives Out2 (cooling) and 50-100% drives Out1 (heating).

    Typical usage::

        @fb(target=ab)
        class HeatingCooling:
            srtp: SRTP
            pid_output: Input[REAL]
            heater: Output[BOOL]
            cooler: Output[BOOL]

            def logic(self):
                self.srtp(In=self.pid_output, CyclePeriod=10.0,
                          SplitRangeHL=50.0, SplitRangeLL=50.0)
                self.heater = self.srtp.Out1
                self.cooler = self.srtp.Out2
    """

    # --- Inputs ---
    In: Input[REAL]
    CyclePeriod: Input[REAL]
    SplitRangeHL: Input[REAL]
    SplitRangeLL: Input[REAL]

    # --- Outputs ---
    Out1: Output[BOOL]
    Out2: Output[BOOL]


class D2SD(LibraryFB, vendor="ab", library="ab_process"):
    """Discrete 2-state device control (D2SD).

    Controls a simple on/off device (solenoid valve, pump starter, heater
    contactor) with command output, feedback monitoring, and fault detection.

    Command/feedback model:
    - Cmd: the desired state of the device.
    - Out: the actual output command sent to the device.
    - Fdbk: feedback input confirming the device state (e.g., auxiliary
      contact, flow switch, pressure switch).
    - FdbkStatus: TRUE when feedback matches the commanded state.

    Fault detection:
    - CmdTime: maximum time (seconds) allowed for the device to respond
      after a command change.
    - FaultTime: maximum time (seconds) for feedback to confirm the
      command.  If feedback does not match within FaultTime, Fault=TRUE.

    Program/Operator mode:
    - ProgProgReq / ProgOperReq select command source.

    Typical usage::

        @fb(target=ab)
        class PumpControl:
            pump: D2SD
            start_cmd: Input[BOOL]
            running_fdbk: Input[BOOL]
            pump_output: Output[BOOL]
            pump_fault: Output[BOOL]

            def logic(self):
                self.pump(Cmd=self.start_cmd, Fdbk=self.running_fdbk,
                          CmdTime=5.0, FaultTime=10.0, ProgProgReq=True)
                self.pump_output = self.pump.Out
                self.pump_fault = self.pump.Fault
    """

    # --- Inputs ---
    Cmd: Input[BOOL]
    Fdbk: Input[BOOL]
    CmdTime: Input[REAL]
    FaultTime: Input[REAL]
    ProgProgReq: Input[BOOL]
    ProgOperReq: Input[BOOL]

    # --- Outputs ---
    Out: Output[BOOL]
    Fault: Output[BOOL]
    FdbkStatus: Output[BOOL]


class D3SD(LibraryFB, vendor="ab", library="ab_process"):
    """Discrete 3-state device control (D3SD).

    Controls a device with three states: open, closed, and stopped/off
    (e.g., a motor-operated valve with open and close commands, or a
    reversing motor starter).  Provides independent open/close command
    outputs with feedback monitoring and fault detection.

    Command/feedback model:
    - OpenCmd / CloseCmd: the desired state commands.
    - OpenFdbk / ClosedFdbk: limit switch or proximity sensor feedback
      confirming the device has reached the open or closed position.
    - OpenOut / CloseOut: the actual output commands.
    - Opened / Closed: confirmed position status.

    Fault detection:
    - CmdTime: time allowed for a command transition to begin.
    - FaultTime: time allowed for feedback to confirm the commanded
      position.  If not confirmed within FaultTime, Fault=TRUE.

    Interlocking:
    - OpenCmd and CloseCmd are mutually exclusive -- both TRUE simultaneously
      is treated as a fault condition.

    Typical usage::

        @fb(target=ab)
        class MOVControl:
            valve: D3SD
            open_cmd: Input[BOOL]
            close_cmd: Input[BOOL]
            open_ls: Input[BOOL]
            closed_ls: Input[BOOL]
            open_out: Output[BOOL]
            close_out: Output[BOOL]

            def logic(self):
                self.valve(OpenCmd=self.open_cmd, CloseCmd=self.close_cmd,
                           OpenFdbk=self.open_ls, ClosedFdbk=self.closed_ls,
                           CmdTime=5.0, FaultTime=60.0)
                self.open_out = self.valve.OpenOut
                self.close_out = self.valve.CloseOut
    """

    # --- Inputs ---
    OpenCmd: Input[BOOL]
    CloseCmd: Input[BOOL]
    OpenFdbk: Input[BOOL]
    ClosedFdbk: Input[BOOL]
    CmdTime: Input[REAL]
    FaultTime: Input[REAL]

    # --- Outputs ---
    OpenOut: Output[BOOL]
    CloseOut: Output[BOOL]
    Fault: Output[BOOL]
    Opened: Output[BOOL]
    Closed: Output[BOOL]


# ===================================================================
# Dynamic Compensation
# ===================================================================

class LDLG(LibraryFB, vendor="ab", library="ab_process"):
    """Lead-Lag dynamic compensator (LDLG).

    Implements a first-order lead-lag transfer function:

        G(s) = Gain * (LeadTime * s + 1) / (LagTime * s + 1)

    Used in feed-forward control paths to compensate for process dynamics.
    The lead term adds anticipatory action (derivative-like), while the
    lag term provides filtering (first-order low-pass).

    When LeadTime = 0, the block acts as a pure first-order lag filter.
    When LagTime = 0, the block acts as a pure lead (differentiator with
    gain).  When both are 0, Out = Gain * In (static gain).

    Typical usage::

        @fb(target=ab)
        class FeedForwardCompensation:
            compensator: LDLG
            ff_signal: Input[REAL]
            ff_output: Output[REAL]

            def logic(self):
                self.compensator(In=self.ff_signal,
                                 LeadTime=5.0, LagTime=10.0, Gain=1.0)
                self.ff_output = self.compensator.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    LeadTime: Input[REAL]
    LagTime: Input[REAL]
    Gain: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]


class DEDT(LibraryFB, vendor="ab", library="ab_process"):
    """Deadtime delay (DEDT).

    Delays the input signal by a specified time (DeadTime, in seconds).
    The output reproduces the input waveform shifted in time by the
    deadtime value.  Internally uses a circular buffer to store
    historical input samples.

    Used in process simulation (Smith Predictor) and model-based control
    where the process deadtime must be explicitly modeled.  Also useful
    for testing control loops by injecting a known transport delay.

    Typical usage::

        @fb(target=ab)
        class SmithPredictor:
            delay: DEDT
            model_output: Input[REAL]
            delayed_output: Output[REAL]

            def logic(self):
                self.delay(In=self.model_output, DeadTime=15.0)
                self.delayed_output = self.delay.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    DeadTime: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]


# ===================================================================
# Function Generator
# ===================================================================

class FGEN(LibraryFB, vendor="ab", library="ab_process"):
    """Piecewise-linear function generator (FGEN).

    Defines a transfer function as a set of up to 5 (X, Y) breakpoints.
    The output is linearly interpolated between adjacent breakpoints.
    For input values outside the defined range, the output is extrapolated
    from the nearest segment.

    Breakpoints must be ordered: X1 < X2 < X3 < X4 < X5.  Unused
    breakpoints should have X and Y set to 0.

    Common applications:
    - Nonlinear valve characterization (equal-percentage to linear).
    - Sensor linearization (thermocouple, RTD).
    - Custom scaling curves.
    - pH neutralization curve compensation.

    Typical usage::

        @fb(target=ab)
        class ValveCharacterization:
            fgen: FGEN
            demand: Input[REAL]
            characterized_output: Output[REAL]

            def logic(self):
                self.fgen(In=self.demand,
                          X1=0.0,  Y1=0.0,
                          X2=25.0, Y2=10.0,
                          X3=50.0, Y3=35.0,
                          X4=75.0, Y4=70.0,
                          X5=100.0, Y5=100.0)
                self.characterized_output = self.fgen.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    X1: Input[REAL]
    Y1: Input[REAL]
    X2: Input[REAL]
    Y2: Input[REAL]
    X3: Input[REAL]
    Y3: Input[REAL]
    X4: Input[REAL]
    Y4: Input[REAL]
    X5: Input[REAL]
    Y5: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]


# ===================================================================
# Totalizer
# ===================================================================

class TOT(LibraryFB, vendor="ab", library="ab_process"):
    """Flow totalizer (TOT).

    Integrates a rate-of-flow input over time to produce a running total.
    Used for batch totalization, custody transfer metering, and
    consumption tracking.

    The input (In) is the instantaneous flow rate in engineering units
    per time unit (e.g., gallons/minute, liters/hour).  Total accumulates
    the integrated flow.  OldTotal stores the previous total before the
    last reset.

    Control:
    - Running=TRUE indicates the totalizer is actively integrating.
    - ProgReset resets Total to zero and saves the current total to
      OldTotal.

    Program/Operator mode:
    - ProgProgReq / ProgOperReq select the control source for
      start/stop/reset commands.

    Typical usage::

        @fb(target=ab)
        class BatchTotalizer:
            totalizer: TOT
            flow_rate: Input[REAL]
            total_gallons: Output[REAL]

            def logic(self):
                self.totalizer(In=self.flow_rate,
                               ProgProgReq=True)
                self.total_gallons = self.totalizer.Total
    """

    # --- Inputs ---
    In: Input[REAL]
    ProgProgReq: Input[BOOL]
    ProgOperReq: Input[BOOL]
    ProgReset: Input[BOOL]

    # --- Outputs ---
    Total: Output[REAL]
    OldTotal: Output[REAL]
    Running: Output[BOOL]


# ===================================================================
# Select / Mux
# ===================================================================

class SEL(LibraryFB, vendor="ab", library="ab_process"):
    """Two-input selector (SEL).

    Selects between two REAL inputs based on a boolean selector.  When
    SelectorIn is FALSE, Out=In1.  When SelectorIn is TRUE, Out=In2.

    This is the process control version of the IEC SEL function, provided
    as an FB with output tracking for bumpless transfer and HMI
    integration.

    Typical usage::

        @fb(target=ab)
        class RedundantSensor:
            selector: SEL
            sensor_a: Input[REAL]
            sensor_b: Input[REAL]
            use_b: Input[BOOL]
            selected: Output[REAL]

            def logic(self):
                self.selector(SelectorIn=self.use_b,
                              In1=self.sensor_a, In2=self.sensor_b)
                self.selected = self.selector.Out
    """

    # --- Inputs ---
    SelectorIn: Input[BOOL]
    In1: Input[REAL]
    In2: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Select In2 when SelectorIn is TRUE, otherwise In1."""
        state["Out"] = state["In2"] if state["SelectorIn"] else state["In1"]


class MUX(LibraryFB, vendor="ab", library="ab_process"):
    """Multi-input multiplexer (MUX) -- up to 8 inputs.

    Selects one of up to 8 REAL inputs based on an integer Selector
    (1-8).  Selector=1 routes In1 to Out, Selector=2 routes In2 to Out,
    and so on.  Out-of-range Selector values hold the last valid output.

    Used for multi-point temperature monitoring, redundant transmitter
    selection, and recipe-driven setpoint selection.

    Typical usage::

        @fb(target=ab)
        class RecipeSelector:
            mux: MUX
            recipe_number: Input[DINT]
            sp1: Input[REAL]
            sp2: Input[REAL]
            sp3: Input[REAL]
            setpoint: Output[REAL]

            def logic(self):
                self.mux(Selector=self.recipe_number,
                         In1=self.sp1, In2=self.sp2, In3=self.sp3)
                self.setpoint = self.mux.Out
    """

    # --- Inputs ---
    Selector: Input[DINT]
    In1: Input[REAL]
    In2: Input[REAL]
    In3: Input[REAL]
    In4: Input[REAL]
    In5: Input[REAL]
    In6: Input[REAL]
    In7: Input[REAL]
    In8: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]


class ESEL(LibraryFB, vendor="ab", library="ab_process"):
    """Enhanced selector (ESEL) -- advanced multi-input selector with bumpless transfer.

    Selects one of up to 4 REAL inputs with automatic bumpless transfer
    between inputs.  Unlike the basic SEL, ESEL provides:

    - **Selector modes**: manual selection, high select, low select,
      median select, average.  SelectorMode controls the algorithm.
    - **Bumpless transfer**: when the selected input changes, the output
      ramps smoothly to the new value to avoid process upsets.
    - **Program/Operator mode**: ProgProgReq / ProgOperReq select who
      controls the selector.

    SelectorMode values:
    - 0: Manual (operator/program selects which input).
    - 1: High select (Out = max of enabled inputs).
    - 2: Low select (Out = min of enabled inputs).
    - 3: Median select (Out = median of enabled inputs).
    - 4: Average (Out = average of enabled inputs).

    SelectedIn output indicates which input (1-4) is currently driving
    the output.

    Typical usage::

        @fb(target=ab)
        class TripleRedundancy:
            esel: ESEL
            sensor1: Input[REAL]
            sensor2: Input[REAL]
            sensor3: Input[REAL]
            selected: Output[REAL]

            def logic(self):
                self.esel(In1=self.sensor1, In2=self.sensor2,
                          In3=self.sensor3, SelectorMode=3,
                          ProgProgReq=True)
                self.selected = self.esel.Out
    """

    # --- Inputs ---
    In1: Input[REAL]
    In2: Input[REAL]
    In3: Input[REAL]
    In4: Input[REAL]
    SelectorMode: Input[DINT]
    ProgProgReq: Input[BOOL]
    ProgOperReq: Input[BOOL]

    # --- Outputs ---
    Out: Output[REAL]
    SelectedIn: Output[DINT]


# ===================================================================
# Limit / Clamp
# ===================================================================

class HLL(LibraryFB, vendor="ab", library="ab_process"):
    """High/Low limit clamp (HLL).

    Clamps the input value between HLimit and LLimit:

        Out = max(LLimit, min(In, HLimit))

    Sets HAlarm=TRUE when the input exceeds HLimit, and LAlarm=TRUE
    when the input falls below LLimit.  The output is always within
    [LLimit, HLimit].

    Used to protect downstream equipment from out-of-range signals,
    enforce safe operating envelopes, and provide limit violation alarms.

    Typical usage::

        @fb(target=ab)
        class SpeedLimit:
            limiter: HLL
            speed_demand: Input[REAL]
            limited_speed: Output[REAL]

            def logic(self):
                self.limiter(In=self.speed_demand,
                             HLimit=1800.0, LLimit=0.0)
                self.limited_speed = self.limiter.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    HLimit: Input[REAL]
    LLimit: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]
    HAlarm: Output[BOOL]
    LAlarm: Output[BOOL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Clamp In between LLimit and HLimit."""
        val = state["In"]
        h = state["HLimit"]
        lo = state["LLimit"]
        state["HAlarm"] = val > h
        state["LAlarm"] = val < lo
        if val > h:
            state["Out"] = h
        elif val < lo:
            state["Out"] = lo
        else:
            state["Out"] = val


class RLIM(LibraryFB, vendor="ab", library="ab_process"):
    """Rate of change limiter (RLIM).

    Limits how fast the output can change, preventing sudden steps in
    the control signal from reaching downstream equipment.

    - ROCPosLimit: maximum positive rate of change (units/second).
    - ROCNegLimit: maximum negative rate of change (units/second,
      specified as a positive value).

    The output tracks the input but is rate-limited.  If the input
    changes faster than the configured limits, the output ramps at the
    maximum allowed rate until it catches up.

    Common applications:
    - Protecting mechanical equipment from sudden load changes.
    - Smoothing setpoint changes for operator comfort.
    - Preventing thermal shock in heat exchangers and boilers.

    Typical usage::

        @fb(target=ab)
        class SetpointRamp:
            ramp: RLIM
            sp_target: Input[REAL]
            sp_ramped: Output[REAL]

            def logic(self):
                self.ramp(In=self.sp_target,
                          ROCPosLimit=5.0, ROCNegLimit=5.0)
                self.sp_ramped = self.ramp.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    ROCPosLimit: Input[REAL]
    ROCNegLimit: Input[REAL]

    # --- Outputs ---
    Out: Output[REAL]


# ===================================================================
# Math
# ===================================================================

class SNEG(LibraryFB, vendor="ab", library="ab_process"):
    """Selected negate (SNEG).

    Conditionally negates the input based on a boolean selector:

        Out = -In  when SelectorIn is TRUE
        Out =  In  when SelectorIn is FALSE

    Used for reversing the sign of a signal based on a process condition,
    such as reversing the direction of a control action when switching
    between heating and cooling modes.

    Typical usage::

        @fb(target=ab)
        class DirectionControl:
            negate: SNEG
            signal: Input[REAL]
            reverse: Input[BOOL]
            output: Output[REAL]

            def logic(self):
                self.negate(In=self.signal, SelectorIn=self.reverse)
                self.output = self.negate.Out
    """

    # --- Inputs ---
    In: Input[REAL]
    SelectorIn: Input[BOOL]

    # --- Outputs ---
    Out: Output[REAL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Negate In when SelectorIn is TRUE."""
        state["Out"] = -state["In"] if state["SelectorIn"] else state["In"]


class SSUM(LibraryFB, vendor="ab", library="ab_process"):
    """Selected summer (SSUM) -- 4-input summer with selectable sign.

    Sums up to 4 REAL inputs with per-input sign selection.  Each input
    has a corresponding Select parameter that controls how it contributes:

    - Select = 0: input is excluded (not added).
    - Select = 1: input is added (positive).
    - Select = 2: input is subtracted (negative).

    Result: Out = sum of (In_i * sign_i) for all selected inputs.

    Used for combining multiple control signals, calculating error terms,
    and building complex setpoint calculations from multiple sources.

    Typical usage::

        @fb(target=ab)
        class CompensatedSetpoint:
            summer: SSUM
            base_sp: Input[REAL]
            bias: Input[REAL]
            correction: Input[REAL]
            setpoint: Output[REAL]

            def logic(self):
                self.summer(In1=self.base_sp, Select1=1,
                            In2=self.bias, Select2=1,
                            In3=self.correction, Select3=2)
                self.setpoint = self.summer.Out
    """

    # --- Inputs ---
    In1: Input[REAL]
    In2: Input[REAL]
    In3: Input[REAL]
    In4: Input[REAL]
    Select1: Input[DINT]
    Select2: Input[DINT]
    Select3: Input[DINT]
    Select4: Input[DINT]

    # --- Outputs ---
    Out: Output[REAL]

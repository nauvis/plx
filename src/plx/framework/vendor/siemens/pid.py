"""Siemens Technology PID controllers.

TIA Portal Technology Objects for closed-loop control on S7-1200/S7-1500.
These are the primary PID function blocks in the Siemens ecosystem, providing
self-tuning, cascade, and split-range control.

Available types:

PID:
    PID_Compact  (Self-tuning PID for continuous actuators)
    PID_3Step    (PID for integrating actuators — valves with motor drive)
    PID_Temp     (Temperature PID with heating/cooling outputs)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DWORD, INT, REAL

# ===================================================================
# PID_Compact
# ===================================================================


class PID_Compact(LibraryFB, vendor="siemens", library="siemens_technology"):
    """Self-tuning PID controller for continuous actuators.

    The standard Siemens PID block for S7-1200/S7-1500.  Supports automatic
    first-time tuning and fine tuning via TIA Portal's PID commissioning
    wizard.  The controller operates in several modes:

    Mode values (set via Mode input with ModeActivate rising edge):
    - 0: Inactive
    - 1: Pretuning (initial tuning)
    - 2: Fine tuning
    - 3: Automatic mode
    - 4: Manual mode

    Input sources:
    - Input: scaled engineering-unit process variable (REAL).
    - Input_PER: raw analog input (INT, 0-27648 typical for S7).
      Only one should be used at a time — configured in the technology
      object settings.

    ManualEnable / ManualValue allow direct CV override in manual mode.
    Reset performs a controller restart (clears integral, resets state).

    State output:
    - 0: Inactive
    - 1: Pretuning active
    - 2: Fine tuning active
    - 3: Automatic mode active
    - 4: Manual mode active

    Typical usage::

        @fb(target=siemens)
        class TemperatureLoop:
            pid: PID_Compact
            pv: Input[REAL]
            sp: Input[REAL]
            cv: Output[REAL]

            def logic(self):
                self.pid(Setpoint=self.sp, Input=self.pv, ModeActivate=True, Mode=3)
                self.cv = self.pid.Output
    """

    # --- Inputs ---
    Setpoint: Input[REAL]
    Input: Input[REAL]
    Input_PER: Input[INT]
    Disturbance: Input[REAL]
    ManualEnable: Input[BOOL]
    ManualValue: Input[REAL]
    ErrorAck: Input[BOOL]
    Reset: Input[BOOL]
    ModeActivate: Input[BOOL]

    # --- InOuts ---
    Mode: InOut[INT]

    # --- Outputs ---
    Output: Output[REAL]
    Output_PER: Output[INT]
    Output_PWM: Output[BOOL]
    ScaledInput: Output[REAL]
    SetpointLimit_H: Output[BOOL]
    SetpointLimit_L: Output[BOOL]
    InputWarning_H: Output[BOOL]
    InputWarning_L: Output[BOOL]
    State: Output[INT]
    Error: Output[BOOL]
    ErrorBits: Output[DWORD]


# ===================================================================
# PID_3Step
# ===================================================================


class PID_3Step(LibraryFB, vendor="siemens", library="siemens_technology"):
    """PID controller for integrating actuators (motor-operated valves).

    Designed for actuators with raise/lower motor drive (e.g., globe valves,
    butterfly valves, dampers).  Outputs discrete raise (Output_UP) and
    lower (Output_DN) signals with configurable motor operating time,
    deadband, and minimum on-time.

    Feedback can come from either a position transmitter (Feedback, REAL)
    or a raw analog input (Feedback_PER, INT).  When no position feedback
    is available, the controller estimates position from motor run time.

    Manual_UP / Manual_DN allow direct raise/lower override in manual mode.
    Actuator_H / Actuator_L provide end stop feedback from the actuator.

    Mode values (same as PID_Compact):
    - 0: Inactive
    - 1: Pretuning
    - 2: Fine tuning
    - 3: Automatic
    - 4: Manual

    Typical usage::

        @fb(target=siemens)
        class ValveControl:
            pid: PID_3Step
            pv: Input[REAL]
            sp: Input[REAL]
            position: Input[REAL]
            open_cmd: Output[BOOL]
            close_cmd: Output[BOOL]

            def logic(self):
                self.pid(Setpoint=self.sp, Input=self.pv, Feedback=self.position, ModeActivate=True, Mode=3)
                self.open_cmd = self.pid.Output_UP
                self.close_cmd = self.pid.Output_DN
    """

    # --- Inputs ---
    Setpoint: Input[REAL]
    Input: Input[REAL]
    Input_PER: Input[INT]
    Feedback: Input[REAL]
    Feedback_PER: Input[INT]
    Disturbance: Input[REAL]
    Manual_UP: Input[BOOL]
    Manual_DN: Input[BOOL]
    Actuator_H: Input[BOOL]
    Actuator_L: Input[BOOL]
    ManualEnable: Input[BOOL]
    ManualValue: Input[REAL]
    ErrorAck: Input[BOOL]
    Reset: Input[BOOL]
    ModeActivate: Input[BOOL]

    # --- InOuts ---
    Mode: InOut[INT]

    # --- Outputs ---
    Output: Output[REAL]
    Output_PER: Output[INT]
    Output_UP: Output[BOOL]
    Output_DN: Output[BOOL]
    ScaledInput: Output[REAL]
    ScaledFeedback: Output[REAL]
    SetpointLimit_H: Output[BOOL]
    SetpointLimit_L: Output[BOOL]
    InputWarning_H: Output[BOOL]
    InputWarning_L: Output[BOOL]
    State: Output[INT]
    Error: Output[BOOL]
    ErrorBits: Output[DWORD]


# ===================================================================
# PID_Temp
# ===================================================================


class PID_Temp(LibraryFB, vendor="siemens", library="siemens_technology"):
    """Temperature PID controller with heating and cooling outputs.

    Extends PID_Compact with separate heating and cooling output channels
    for split-range temperature control.  The controller automatically
    manages the handoff between heating and cooling zones with configurable
    deadband to prevent simultaneous operation.

    Output channels:
    - OutputHeat / OutputHeat_PER / OutputHeat_PWM: heating actuator.
    - OutputCool / OutputCool_PER / OutputCool_PWM: cooling actuator.

    The heating/cooling split is configured in the technology object
    settings within TIA Portal (not via input parameters).

    Typical usage::

        @fb(target=siemens)
        class OvenControl:
            pid: PID_Temp
            temp_pv: Input[REAL]
            temp_sp: Input[REAL]
            heater_on: Output[BOOL]
            cooler_on: Output[BOOL]

            def logic(self):
                self.pid(Setpoint=self.temp_sp, Input=self.temp_pv, ModeActivate=True, Mode=3)
                self.heater_on = self.pid.OutputHeat_PWM
                self.cooler_on = self.pid.OutputCool_PWM
    """

    # --- Inputs ---
    Setpoint: Input[REAL]
    Input: Input[REAL]
    Input_PER: Input[INT]
    Disturbance: Input[REAL]
    ManualEnable: Input[BOOL]
    ManualValue: Input[REAL]
    ErrorAck: Input[BOOL]
    Reset: Input[BOOL]
    ModeActivate: Input[BOOL]

    # --- InOuts ---
    Mode: InOut[INT]

    # --- Outputs ---
    OutputHeat: Output[REAL]
    OutputCool: Output[REAL]
    OutputHeat_PER: Output[INT]
    OutputCool_PER: Output[INT]
    OutputHeat_PWM: Output[BOOL]
    OutputCool_PWM: Output[BOOL]
    ScaledInput: Output[REAL]
    SetpointLimit_H: Output[BOOL]
    SetpointLimit_L: Output[BOOL]
    InputWarning_H: Output[BOOL]
    InputWarning_L: Output[BOOL]
    State: Output[INT]
    Error: Output[BOOL]
    ErrorBits: Output[DWORD]

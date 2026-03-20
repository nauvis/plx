"""Siemens alarm function blocks.

TIA Portal program alarm instructions for S7-1200/S7-1500 diagnostic
and alarm management.

Available types:

Alarms:
    Program_Alarm  (Generate program alarm with associated values)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, DINT, WORD


# ===================================================================
# Program Alarm
# ===================================================================

class Program_Alarm(LibraryFB, vendor="siemens", library="siemens_alarms"):
    """Generate a program alarm with up to 10 associated data values.

    Creates a supervisory alarm that appears in the TIA Portal alarm
    display, HMI alarm views, and diagnostic buffer.  The alarm is
    active while SIG=TRUE and clears when SIG=FALSE.

    Associated values (SD_1 through SD_10) carry diagnostic context
    with the alarm — for example, the measured value that triggered
    the alarm, the setpoint, equipment ID, etc.  These values are
    displayed alongside the alarm message in the HMI.

    The alarm message text is configured in the TIA Portal alarm
    configuration (not via the FB parameters).  Each FB instance
    corresponds to one alarm class/number pair.

    Acknowledgment status is accessed via the Get_AlarmState
    instruction, not through a direct output of this FB.

    Typical usage::

        @fb(target=siemens)
        class HighPressureAlarm:
            alarm: Program_Alarm
            pressure_high: Input[BOOL]
            pressure_value: Input[DINT]

            def logic(self):
                self.alarm(SIG=self.pressure_high,
                           SD_1=self.pressure_value)
    """

    # --- Inputs ---
    SIG: Input[BOOL]
    SD_1: Input[DINT]
    SD_2: Input[DINT]
    SD_3: Input[DINT]
    SD_4: Input[DINT]
    SD_5: Input[DINT]
    SD_6: Input[DINT]
    SD_7: Input[DINT]
    SD_8: Input[DINT]
    SD_9: Input[DINT]
    SD_10: Input[DINT]

    # --- Outputs ---
    ERROR: Output[BOOL]
    STATUS: Output[WORD]

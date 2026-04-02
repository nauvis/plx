"""Siemens extended timer function blocks.

The standard IEC 61131-3 timers (TON, TOF, TP) are provided by
``plx.framework._iec_builtins``.  This module adds Siemens-specific
timer extensions not covered by the IEC standard.

Available types:

Timers:
    TONR  (Retentive on-delay timer with reset)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, TIME

# ===================================================================
# Retentive On-Delay Timer
# ===================================================================


class TONR(LibraryFB, vendor="siemens", library="siemens_standard"):
    """Retentive on-delay timer with explicit reset (TONR).

    Accumulates elapsed time while IN=TRUE.  Unlike the standard TON,
    TONR retains the accumulated time when IN goes FALSE — the timer
    resumes from where it left off when IN is re-asserted.

    Q becomes TRUE when ET reaches PT.  The accumulated time is only
    cleared when R (reset) is asserted.

    This is the Siemens equivalent of the AB RTOR instruction and the
    IEC RTO (provided as a framework sentinel via ``retentive()``).

    Inputs:
    - IN: timer enable (accumulates while TRUE, holds while FALSE).
    - R: reset — clears ET to zero and Q to FALSE.
    - PT: preset time (TIME).

    Outputs:
    - Q: done — TRUE when ET >= PT.
    - ET: elapsed time (retained between IN cycles).

    Typical usage::

        @fb(target=siemens)
        class RunTimeTracker:
            timer: TONR
            motor_running: Input[BOOL]
            reset_hours: Input[BOOL]
            runtime_exceeded: Output[BOOL]

            def logic(self):
                self.timer(IN=self.motor_running, R=self.reset_hours, PT=TIME("T#8H"))
                self.runtime_exceeded = self.timer.Q
    """

    # --- Inputs ---
    IN: Input[BOOL]
    R: Input[BOOL]
    PT: Input[TIME]

    # --- Outputs ---
    Q: Output[BOOL]
    ET: Output[TIME]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_start_time"] = None
        state["_accumulated"] = 0
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        reset = state["R"]
        pt = state["PT"]

        if reset:
            state["Q"] = False
            state["ET"] = 0
            state["_start_time"] = None
            state["_accumulated"] = 0
            return

        if in_val:
            if state["_start_time"] is None:
                state["_start_time"] = clock_ms

            elapsed = state["_accumulated"] + (clock_ms - state["_start_time"])
            state["ET"] = min(elapsed, pt)

            if elapsed >= pt:
                state["Q"] = True
            else:
                state["Q"] = False
        else:
            if state["_start_time"] is not None:
                state["_accumulated"] += clock_ms - state["_start_time"]
                state["_start_time"] = None

            state["ET"] = min(state["_accumulated"], pt)

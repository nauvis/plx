"""Tc2_Standard — Beckhoff-specific extensions to IEC 61131-3.

The IEC standard FBs (TON, TOF, TP, etc.) are already provided by
``plx.framework._iec_builtins``.  This module adds Beckhoff-only
additions from the Tc2_Standard library.

Available types:

  Timers (LTIME variants):
    LTON  — On-delay timer with LTIME resolution
    LTOF  — Off-delay timer with LTIME resolution
    LTP   — Pulse timer with LTIME resolution

Note: do NOT use ``from __future__ import annotations`` in stub files —
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, LTIME

# ---------------------------------------------------------------------------
# LTIME timer variants (64-bit time resolution)
# ---------------------------------------------------------------------------


class LTON(LibraryFB, vendor="beckhoff", library="Tc2_Standard"):
    """On-delay timer with LTIME precision.

    Q becomes TRUE after IN is held TRUE for >= PT.
    Identical behaviour to TON but uses LTIME for 64-bit resolution.
    """

    IN: Input[BOOL]
    PT: Input[LTIME]
    Q: Output[BOOL]
    ET: Output[LTIME]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_start_time"] = None
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]

        if not in_val:
            state["Q"] = False
            state["ET"] = 0
            state["_start_time"] = None
        else:
            if state["_start_time"] is None:
                state["_start_time"] = clock_ms

            elapsed = clock_ms - state["_start_time"]
            state["ET"] = min(elapsed, pt)

            if elapsed >= pt:
                state["Q"] = True
            else:
                state["Q"] = False


class LTOF(LibraryFB, vendor="beckhoff", library="Tc2_Standard"):
    """Off-delay timer with LTIME precision.

    Q stays TRUE for PT after IN goes FALSE.
    Identical behaviour to TOF but uses LTIME for 64-bit resolution.
    """

    IN: Input[BOOL]
    PT: Input[LTIME]
    Q: Output[BOOL]
    ET: Output[LTIME]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_in"] = False
        state["_off_time"] = None
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]
        prev_in = state["_prev_in"]

        if in_val:
            state["Q"] = True
            state["ET"] = 0
            state["_off_time"] = None
        else:
            if prev_in and not in_val:
                state["_off_time"] = clock_ms

            if state["_off_time"] is not None:
                elapsed = clock_ms - state["_off_time"]
                state["ET"] = min(elapsed, pt)
                if elapsed >= pt:
                    state["Q"] = False
                    state["ET"] = pt
                else:
                    state["Q"] = True
            else:
                state["Q"] = False
                state["ET"] = 0

        state["_prev_in"] = in_val


class LTP(LibraryFB, vendor="beckhoff", library="Tc2_Standard"):
    """Pulse timer with LTIME precision.

    Q is TRUE for exactly PT on rising edge of IN.
    Identical behaviour to TP but uses LTIME for 64-bit resolution.
    """

    IN: Input[BOOL]
    PT: Input[LTIME]
    Q: Output[BOOL]
    ET: Output[LTIME]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_in"] = False
        state["_pulse_start"] = None
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]
        prev_in = state["_prev_in"]

        if state["_pulse_start"] is not None:
            elapsed = clock_ms - state["_pulse_start"]
            if elapsed >= pt:
                state["Q"] = False
                state["ET"] = pt
                state["_pulse_start"] = None
            else:
                state["Q"] = True
                state["ET"] = elapsed
        else:
            if in_val and not prev_in:
                state["_pulse_start"] = clock_ms
                state["Q"] = True
                state["ET"] = 0
            else:
                state["Q"] = False
                state["ET"] = 0

        state["_prev_in"] = in_val

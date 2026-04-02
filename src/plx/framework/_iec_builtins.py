"""IEC 61131-3 standard function blocks as LibraryFB stubs.

These are universal across all PLC vendors — no vendor or library
metadata needed.  Each class declares its IEC interface and provides
a full simulation implementation via ``execute()``.

Note: do NOT use ``from __future__ import annotations`` in this file —
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import BOOL, INT, TIME

# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------


class TON(LibraryFB):
    """On-delay timer. Q becomes TRUE after IN held TRUE for >= PT ms."""

    IN: Input[BOOL]
    PT: Input[TIME]
    Q: Output[BOOL]
    ET: Output[TIME]

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


class TOF(LibraryFB):
    """Off-delay timer. Q stays TRUE for PT ms after IN goes FALSE."""

    IN: Input[BOOL]
    PT: Input[TIME]
    Q: Output[BOOL]
    ET: Output[TIME]

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


class TP(LibraryFB):
    """Pulse timer. Q is TRUE for exactly PT ms on rising edge of IN."""

    IN: Input[BOOL]
    PT: Input[TIME]
    Q: Output[BOOL]
    ET: Output[TIME]

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


class RTO(LibraryFB):
    """Retentive on-delay timer. Accumulated time retained when IN goes FALSE."""

    IN: Input[BOOL]
    PT: Input[TIME]
    Q: Output[BOOL]
    ET: Output[TIME]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_last_clock"] = None
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]

        if in_val:
            if state["_last_clock"] is not None:
                delta = clock_ms - state["_last_clock"]
                state["ET"] = min(state["ET"] + delta, pt)
            state["_last_clock"] = clock_ms

            if state["ET"] >= pt:
                state["Q"] = True
            else:
                state["Q"] = False
        else:
            state["_last_clock"] = None
            if state["ET"] >= pt:
                state["Q"] = True
            else:
                state["Q"] = False


# ---------------------------------------------------------------------------
# Edge detectors
# ---------------------------------------------------------------------------


class R_TRIG(LibraryFB):
    """Rising edge detector. Q is TRUE for one scan on FALSE->TRUE."""

    CLK: Input[BOOL]
    Q: Output[BOOL]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_clk"] = False
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        clk = state["CLK"]
        state["Q"] = clk and not state["_prev_clk"]
        state["_prev_clk"] = clk


class F_TRIG(LibraryFB):
    """Falling edge detector. Q is TRUE for one scan on TRUE->FALSE."""

    CLK: Input[BOOL]
    Q: Output[BOOL]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_clk"] = False
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        clk = state["CLK"]
        state["Q"] = not clk and state["_prev_clk"]
        state["_prev_clk"] = clk


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


class CTU(LibraryFB):
    """Up counter. Rising edge of CU increments CV. Q = CV >= PV."""

    CU: Input[BOOL]
    PV: Input[INT]
    RESET: Input[BOOL]
    Q: Output[BOOL]
    CV: Output[INT]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_cu"] = False
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        if state["RESET"]:
            state["CV"] = 0
            state["Q"] = False
        else:
            cu = state["CU"]
            if cu and not state["_prev_cu"]:
                state["CV"] = state["CV"] + 1
            state["Q"] = state["CV"] >= state["PV"]
        state["_prev_cu"] = state["CU"]


class CTD(LibraryFB):
    """Down counter. Rising edge of CD decrements CV. Q = CV <= 0."""

    CD: Input[BOOL]
    PV: Input[INT]
    LOAD: Input[BOOL]
    Q: Output[BOOL]
    CV: Output[INT]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_cd"] = False
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        if state["LOAD"]:
            state["CV"] = state["PV"]
        else:
            cd = state["CD"]
            if cd and not state["_prev_cd"]:
                state["CV"] = state["CV"] - 1
        state["Q"] = state["CV"] <= 0
        state["_prev_cd"] = state["CD"]


class CTUD(LibraryFB):
    """Up/down counter. CU increments, CD decrements.

    QU = CV >= PV, QD = CV <= 0.
    RESET sets CV to 0, LOAD sets CV to PV.
    """

    CU: Input[BOOL]
    CD: Input[BOOL]
    PV: Input[INT]
    RESET: Input[BOOL]
    LOAD: Input[BOOL]
    QU: Output[BOOL]
    QD: Output[BOOL]
    CV: Output[INT]

    @classmethod
    def initial_state(cls) -> dict:
        state = super().initial_state()
        state["_prev_cu"] = False
        state["_prev_cd"] = False
        return state

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        if state["RESET"]:
            state["CV"] = 0
        elif state["LOAD"]:
            state["CV"] = state["PV"]
        else:
            cu = state["CU"]
            cd = state["CD"]
            if cu and not state["_prev_cu"]:
                state["CV"] = state["CV"] + 1
            if cd and not state["_prev_cd"]:
                state["CV"] = state["CV"] - 1
        state["QU"] = state["CV"] >= state["PV"]
        state["QD"] = state["CV"] <= 0
        state["_prev_cu"] = state["CU"]
        state["_prev_cd"] = state["CD"]


# ---------------------------------------------------------------------------
# Bistables
# ---------------------------------------------------------------------------


class SR(LibraryFB):
    """Set-dominant bistable. Q1 = SET1 OR (NOT RESET AND Q1_prev)."""

    SET1: Input[BOOL]
    RESET: Input[BOOL]
    Q1: Output[BOOL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        state["Q1"] = state["SET1"] or (not state["RESET"] and state["Q1"])


class RS(LibraryFB):
    """Reset-dominant bistable. Q1 = NOT RESET1 AND (SET OR Q1_prev)."""

    SET: Input[BOOL]
    RESET1: Input[BOOL]
    Q1: Output[BOOL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        state["Q1"] = not state["RESET1"] and (state["SET"] or state["Q1"])


# ---------------------------------------------------------------------------
# Convenience set for backwards compatibility
# ---------------------------------------------------------------------------

IEC_STANDARD_FB_TYPES: frozenset[str] = frozenset(
    {
        "TON",
        "TOF",
        "TP",
        "RTO",
        "R_TRIG",
        "F_TRIG",
        "CTU",
        "CTD",
        "CTUD",
        "SR",
        "RS",
    }
)

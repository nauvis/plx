"""Standard FB implementations and stdlib functions for the simulator.

Each builtin FB is a class with:
- ``initial_state() -> dict``: returns the initial instance state
- ``execute(state, clock_ms)``: runs one scan cycle, mutating state in-place
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Builtin Function Blocks
# ---------------------------------------------------------------------------

class TON:
    """On-delay timer. Q becomes TRUE after IN held TRUE for >= PT ms."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "IN": False,
            "PT": 0,
            "Q": False,
            "ET": 0,
            "_start_time": None,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]

        if not in_val:
            # Input is FALSE — reset
            state["Q"] = False
            state["ET"] = 0
            state["_start_time"] = None
        else:
            # Input is TRUE
            if state["_start_time"] is None:
                state["_start_time"] = clock_ms

            elapsed = clock_ms - state["_start_time"]
            state["ET"] = min(elapsed, pt)

            if elapsed >= pt:
                state["Q"] = True
            else:
                state["Q"] = False


class TOF:
    """Off-delay timer. Q stays TRUE for PT ms after IN goes FALSE."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "IN": False,
            "PT": 0,
            "Q": False,
            "ET": 0,
            "_prev_in": False,
            "_off_time": None,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]
        prev_in = state["_prev_in"]

        if in_val:
            # Input is TRUE — output is TRUE, reset timer
            state["Q"] = True
            state["ET"] = 0
            state["_off_time"] = None
        else:
            # Input is FALSE
            if prev_in and not in_val:
                # Falling edge — start off-delay
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
                # Never been TRUE — output stays FALSE
                state["Q"] = False
                state["ET"] = 0

        state["_prev_in"] = in_val


class TP:
    """Pulse timer. Q is TRUE for exactly PT ms on rising edge of IN."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "IN": False,
            "PT": 0,
            "Q": False,
            "ET": 0,
            "_prev_in": False,
            "_pulse_start": None,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]
        prev_in = state["_prev_in"]

        if state["_pulse_start"] is not None:
            # Pulse is active
            elapsed = clock_ms - state["_pulse_start"]
            if elapsed >= pt:
                # Pulse complete
                state["Q"] = False
                state["ET"] = pt
                state["_pulse_start"] = None
            else:
                state["Q"] = True
                state["ET"] = elapsed
        else:
            # No active pulse — check for rising edge
            if in_val and not prev_in:
                state["_pulse_start"] = clock_ms
                state["Q"] = True
                state["ET"] = 0
            else:
                state["Q"] = False
                state["ET"] = 0

        state["_prev_in"] = in_val


class R_TRIG:
    """Rising edge detector. Q is TRUE for one scan on FALSE->TRUE."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "CLK": False,
            "Q": False,
            "_prev_clk": False,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        clk = state["CLK"]
        state["Q"] = clk and not state["_prev_clk"]
        state["_prev_clk"] = clk


class F_TRIG:
    """Falling edge detector. Q is TRUE for one scan on TRUE->FALSE."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "CLK": False,
            "Q": False,
            "_prev_clk": False,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        clk = state["CLK"]
        state["Q"] = not clk and state["_prev_clk"]
        state["_prev_clk"] = clk


BUILTIN_FBS: dict[str, type] = {
    "TON": TON,
    "TOF": TOF,
    "TP": TP,
    "R_TRIG": R_TRIG,
    "F_TRIG": F_TRIG,
}


# ---------------------------------------------------------------------------
# Standard library functions
# ---------------------------------------------------------------------------

def _limit(mn: object, val: object, mx: object) -> object:
    """LIMIT(MN, IN, MX) — clamp val between mn and mx."""
    return max(mn, min(val, mx))


def _sel(g: object, in0: object, in1: object) -> object:
    """SEL(G, IN0, IN1) — select in1 if G is truthy, else in0."""
    return in1 if g else in0


def _mux(k: int, *values: object) -> object:
    """MUX(K, val0, val1, ...) — select by index."""
    k = int(k)
    if 0 <= k < len(values):
        return values[k]
    return values[-1] if values else 0


def _shl(value: int, n: int) -> int:
    return value << n


def _shr(value: int, n: int) -> int:
    return value >> n


def _trunc(value: object) -> int:
    return int(value)


def _round_val(value: object) -> int:
    return round(value)


def _time_constructor(
    seconds: float = 0, *, hours: float = 0, minutes: float = 0,
    ms: float = 0, us: float = 0,
) -> int:
    """Runtime T() — returns milliseconds (int)."""
    total_ms = hours * 3_600_000 + minutes * 60_000 + seconds * 1_000 + ms + us / 1_000
    return int(round(total_ms))


STDLIB_FUNCTIONS: dict[str, object] = {
    "ABS": abs,
    "SQRT": math.sqrt,
    "MIN": min,
    "MAX": max,
    "LIMIT": _limit,
    "SEL": _sel,
    "MUX": _mux,
    "TRUNC": _trunc,
    "ROUND": _round_val,
    "SIN": math.sin,
    "COS": math.cos,
    "TAN": math.tan,
    "ASIN": math.asin,
    "ACOS": math.acos,
    "ATAN": math.atan,
    "ATAN2": math.atan2,
    "LN": math.log,
    "LOG": math.log10,
    "EXP": math.exp,
    "EXPT": pow,
    "SHL": _shl,
    "SHR": _shr,
    "T": _time_constructor,
    "LT": _time_constructor,
}

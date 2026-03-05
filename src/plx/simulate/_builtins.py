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


class RTO:
    """Retentive timer on. Q becomes TRUE after IN held TRUE for >= PT ms total.

    Unlike TON, accumulated time is retained when IN goes FALSE.
    Must be explicitly reset (ET set to 0) to restart.
    """

    @staticmethod
    def initial_state() -> dict:
        return {
            "IN": False,
            "PT": 0,
            "Q": False,
            "ET": 0,
            "_last_clock": None,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        in_val = state["IN"]
        pt = state["PT"]

        if in_val:
            # Input is TRUE — accumulate time
            if state["_last_clock"] is not None:
                delta = clock_ms - state["_last_clock"]
                state["ET"] = min(state["ET"] + delta, pt)
            state["_last_clock"] = clock_ms

            if state["ET"] >= pt:
                state["Q"] = True
            else:
                state["Q"] = False
        else:
            # Input is FALSE — retain ET, stop accumulating
            state["_last_clock"] = None
            # Q stays based on current ET
            if state["ET"] >= pt:
                state["Q"] = True
            else:
                state["Q"] = False


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


class CTU:
    """Up counter. Rising edge of CU increments CV. Q = CV >= PV."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "CU": False,
            "PV": 0,
            "RESET": False,
            "Q": False,
            "CV": 0,
            "_prev_cu": False,
        }

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


class CTD:
    """Down counter. Rising edge of CD decrements CV. Q = CV <= 0."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "CD": False,
            "PV": 0,
            "LOAD": False,
            "Q": False,
            "CV": 0,
            "_prev_cd": False,
        }

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


class CTUD:
    """Up/down counter. CU rising edge increments, CD rising edge decrements.

    Q_UP = CV >= PV, Q_DOWN = CV <= 0.
    RESET sets CV to 0, LOAD sets CV to PV.
    """

    @staticmethod
    def initial_state() -> dict:
        return {
            "CU": False,
            "CD": False,
            "PV": 0,
            "RESET": False,
            "LOAD": False,
            "QU": False,
            "QD": False,
            "CV": 0,
            "_prev_cu": False,
            "_prev_cd": False,
        }

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


class SR:
    """Set-dominant bistable. Q1 = SET1 OR (NOT RESET AND Q1_prev)."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "SET1": False,
            "RESET": False,
            "Q1": False,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        state["Q1"] = state["SET1"] or (not state["RESET"] and state["Q1"])


class RS:
    """Reset-dominant bistable. Q1 = NOT RESET1 AND (SET OR Q1_prev)."""

    @staticmethod
    def initial_state() -> dict:
        return {
            "SET": False,
            "RESET1": False,
            "Q1": False,
        }

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        state["Q1"] = not state["RESET1"] and (state["SET"] or state["Q1"])


BUILTIN_FBS: dict[str, type] = {
    "TON": TON,
    "TOF": TOF,
    "TP": TP,
    "RTO": RTO,
    "R_TRIG": R_TRIG,
    "F_TRIG": F_TRIG,
    "CTU": CTU,
    "CTD": CTD,
    "CTUD": CTUD,
    "SR": SR,
    "RS": RS,
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


def _rol(value: int, n: int) -> int:
    value, n = int(value) & 0xFFFFFFFF, int(n) % 32
    return ((value << n) | (value >> (32 - n))) & 0xFFFFFFFF


def _ror(value: int, n: int) -> int:
    value, n = int(value) & 0xFFFFFFFF, int(n) % 32
    return ((value >> n) | (value << (32 - n))) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# String functions (IEC 61131-3, 1-based indexing)
# ---------------------------------------------------------------------------

def _len(s: str) -> int:
    return len(s)


def _left(s: str, n: int) -> str:
    return s[:int(n)]


def _right(s: str, n: int) -> str:
    n = int(n)
    if n >= len(s):
        return s
    return s[len(s) - n:]


def _mid(s: str, pos: int, n: int) -> str:
    pos, n = int(pos), int(n)
    return s[pos - 1:pos - 1 + n]


def _concat(*args: object) -> str:
    return "".join(str(a) for a in args)


def _find(s1: str, s2: str) -> int:
    return s1.find(s2) + 1  # 0 = not found


def _replace(s: str, s2: str, n: int, pos: int) -> str:
    pos, n = int(pos), int(n)
    return s[:pos - 1] + s2 + s[pos - 1 + n:]


def _insert(s: str, s2: str, pos: int) -> str:
    pos = int(pos)
    return s[:pos - 1] + s2 + s[pos - 1:]


def _delete(s: str, n: int, pos: int) -> str:
    pos, n = int(pos), int(n)
    return s[:pos - 1] + s[pos - 1 + n:]


# ---------------------------------------------------------------------------
# Bitwise function-call forms
# ---------------------------------------------------------------------------

def _and_func(a: object, b: object) -> object:
    if isinstance(a, bool) and isinstance(b, bool):
        return a and b
    return int(a) & int(b)


def _or_func(a: object, b: object) -> object:
    if isinstance(a, bool) and isinstance(b, bool):
        return a or b
    return int(a) | int(b)


def _xor_func(a: object, b: object) -> object:
    if isinstance(a, bool) and isinstance(b, bool):
        return a ^ b
    return int(a) ^ int(b)


def _not_func(a: object) -> object:
    if isinstance(a, bool):
        return not a
    return ~int(a)


def _trunc(value: object) -> int:
    return int(value)


def _round_val(value: object) -> int:
    return round(value)


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
    "LN": math.log,
    "LOG": math.log10,
    "EXP": math.exp,
    "CEIL": math.ceil,
    "FLOOR": math.floor,
    "EXPT": pow,
    "SHL": _shl,
    "SHR": _shr,
    "ROL": _rol,
    "ROR": _ror,
    # String functions
    "LEN": _len,
    "LEFT": _left,
    "RIGHT": _right,
    "MID": _mid,
    "CONCAT": _concat,
    "FIND": _find,
    "REPLACE": _replace,
    "INSERT": _insert,
    "DELETE": _delete,
    # Bitwise function-call forms
    "AND": _and_func,
    "OR": _or_func,
    "XOR": _xor_func,
    "NOT": _not_func,
}

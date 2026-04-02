"""Stdlib functions for the simulator.

Builtin FB implementations (TON, TOF, etc.) have moved to
``plx.framework._iec_builtins`` and are registered in the library
type registry.  This module retains only the stdlib functions
(ABS, SQRT, MIN, etc.) used by the execution engine.
"""

from __future__ import annotations

import math

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
    """SHL — shift left."""
    return value << n


def _shr(value: int, n: int) -> int:
    """SHR — shift right."""
    return value >> n


def _rol(value: int, n: int) -> int:
    """ROL — rotate left (32-bit)."""
    value, n = int(value) & 0xFFFFFFFF, int(n) % 32
    return ((value << n) | (value >> (32 - n))) & 0xFFFFFFFF


def _ror(value: int, n: int) -> int:
    """ROR — rotate right (32-bit)."""
    value, n = int(value) & 0xFFFFFFFF, int(n) % 32
    return ((value >> n) | (value << (32 - n))) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# String functions (IEC 61131-3, 1-based indexing)
# ---------------------------------------------------------------------------


def _len(s: str) -> int:
    return len(s)


def _left(s: str, n: int) -> str:
    return s[: int(n)]


def _right(s: str, n: int) -> str:
    n = int(n)
    if n >= len(s):
        return s
    return s[len(s) - n :]


def _mid(s: str, pos: int, n: int) -> str:
    pos, n = int(pos), int(n)
    return s[pos - 1 : pos - 1 + n]


def _concat(*args: object) -> str:
    return "".join(str(a) for a in args)


def _find(s1: str, s2: str) -> int:
    return s1.find(s2) + 1  # 0 = not found


def _replace(s: str, s2: str, n: int, pos: int) -> str:
    pos, n = int(pos), int(n)
    return s[: pos - 1] + s2 + s[pos - 1 + n :]


def _insert(s: str, s2: str, pos: int) -> str:
    pos = int(pos)
    return s[: pos - 1] + s2 + s[pos - 1 :]


def _delete(s: str, n: int, pos: int) -> str:
    pos, n = int(pos), int(n)
    return s[: pos - 1] + s[pos - 1 + n :]


# ---------------------------------------------------------------------------
# Bitwise function-call forms
# ---------------------------------------------------------------------------


def _and_func(a: object, b: object) -> object:
    """AND — logical for bools, bitwise for integers."""
    if isinstance(a, bool) and isinstance(b, bool):
        return a and b
    return int(a) & int(b)


def _or_func(a: object, b: object) -> object:
    """OR — logical for bools, bitwise for integers."""
    if isinstance(a, bool) and isinstance(b, bool):
        return a or b
    return int(a) | int(b)


def _xor_func(a: object, b: object) -> object:
    """XOR — logical for bools, bitwise for integers."""
    if isinstance(a, bool) and isinstance(b, bool):
        return a ^ b
    return int(a) ^ int(b)


def _not_func(a: object) -> object:
    """NOT — logical for bools, bitwise complement for integers."""
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

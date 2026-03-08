"""PLC data types — Python subclasses with IEC 61131-3 overflow semantics.

These types serve dual purposes:

1. **Annotations** — ``speed: Input[real]`` in framework variable declarations
2. **Runtime values** — correct overflow/precision behavior for simulation

Naming follows IEC 61131-3 conventions, lowercased for Python::

    sint, int, dint, lint          — signed integers (8/16/32/64-bit)
    usint, uint, udint, ulint     — unsigned integers
    real, lreal                   — floating point (32/64-bit)
    byte, word, dword, lword      — bit-strings

``int`` shadows Python's builtin ``int``. Use ``builtins.int`` if you
need arbitrary-precision integers in a module that imports these types.
"""

import builtins
import struct as _struct


# ---------------------------------------------------------------------------
# Integer base
# ---------------------------------------------------------------------------

class _PlcInt(builtins.int):
    """Base for PLC integer types with bit-width overflow wrapping."""

    _bits: builtins.int
    _signed: builtins.bool
    _iec_name: str

    def __init_subclass__(cls, *, bits: builtins.int = 0, signed: builtins.bool = True,
                          iec_name: str = "", **kw: object) -> None:
        super().__init_subclass__(**kw)
        if bits:
            cls._bits = bits
            cls._signed = signed
            cls._iec_name = iec_name
            cls._mod = 1 << bits
            if signed:
                cls._half = 1 << (bits - 1)

    def __new__(cls, value: object = 0) -> "_PlcInt":
        v = builtins.int(value)
        if cls._signed:
            v = (v + cls._half) % cls._mod - cls._half
        else:
            v = v % cls._mod
        return builtins.int.__new__(cls, v)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({builtins.int.__repr__(self)})"

    def __str__(self) -> str:
        return builtins.int.__repr__(self)

    # --- Arithmetic ---

    def __add__(self, other: object) -> "_PlcInt":
        r = builtins.int.__add__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __radd__(self, other: object) -> "_PlcInt":
        r = builtins.int.__radd__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __sub__(self, other: object) -> "_PlcInt":
        r = builtins.int.__sub__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rsub__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rsub__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __mul__(self, other: object) -> "_PlcInt":
        r = builtins.int.__mul__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rmul__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rmul__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __floordiv__(self, other: object) -> "_PlcInt":
        r = builtins.int.__floordiv__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rfloordiv__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rfloordiv__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __mod__(self, other: object) -> "_PlcInt":
        r = builtins.int.__mod__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rmod__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rmod__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __pow__(self, other: object, mod: object = None) -> "_PlcInt | builtins.float":
        if mod is not None:
            r = builtins.int.__pow__(self, other, mod)  # type: ignore[arg-type]
        else:
            r = builtins.int.__pow__(self, other)
        if r is NotImplemented:
            return r  # type: ignore[return-value]
        if isinstance(r, builtins.float):
            return r  # negative exponent → float, don't wrap
        return type(self)(r)

    def __rpow__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rpow__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __neg__(self) -> "_PlcInt":
        return type(self)(builtins.int.__neg__(self))

    def __pos__(self) -> "_PlcInt":
        return type(self)(builtins.int.__pos__(self))

    def __abs__(self) -> "_PlcInt":
        return type(self)(builtins.int.__abs__(self))

    # --- Bitwise ---

    def __and__(self, other: object) -> "_PlcInt":
        r = builtins.int.__and__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rand__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rand__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __or__(self, other: object) -> "_PlcInt":
        r = builtins.int.__or__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __ror__(self, other: object) -> "_PlcInt":
        r = builtins.int.__ror__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __xor__(self, other: object) -> "_PlcInt":
        r = builtins.int.__xor__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rxor__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rxor__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __lshift__(self, other: object) -> "_PlcInt":
        r = builtins.int.__lshift__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rlshift__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rlshift__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rshift__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rshift__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rrshift__(self, other: object) -> "_PlcInt":
        r = builtins.int.__rrshift__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __invert__(self) -> "_PlcInt":
        return type(self)(builtins.int.__invert__(self))


# ---------------------------------------------------------------------------
# Float base
# ---------------------------------------------------------------------------

class _PlcFloat(builtins.float):
    """Base for PLC floating-point types with precision control."""

    _bits: builtins.int
    _iec_name: str

    def __repr__(self) -> str:
        return f"{type(self).__name__}({builtins.float.__repr__(self)})"

    def __str__(self) -> str:
        return builtins.float.__repr__(self)

    # --- Arithmetic ---

    def __add__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__add__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __radd__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__radd__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __sub__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__sub__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rsub__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__rsub__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __mul__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__mul__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rmul__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__rmul__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __truediv__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__truediv__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rtruediv__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__rtruediv__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __floordiv__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__floordiv__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rfloordiv__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__rfloordiv__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __mod__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__mod__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rmod__(self, other: object) -> "_PlcFloat":
        r = builtins.float.__rmod__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __pow__(self, other: object, mod: object = None) -> "_PlcFloat":
        r = builtins.float.__pow__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __rpow__(self, other: object, mod: object = None) -> "_PlcFloat":
        r = builtins.float.__rpow__(self, other)
        return type(self)(r) if r is not NotImplemented else r  # type: ignore[return-value]

    def __neg__(self) -> "_PlcFloat":
        return type(self)(builtins.float.__neg__(self))

    def __pos__(self) -> "_PlcFloat":
        return type(self)(builtins.float.__pos__(self))

    def __abs__(self) -> "_PlcFloat":
        return type(self)(builtins.float.__abs__(self))


# ---------------------------------------------------------------------------
# Signed integers
# ---------------------------------------------------------------------------

class sint(_PlcInt, bits=8, signed=True, iec_name="SINT"):
    """8-bit signed integer (-128 to 127)."""


class int(_PlcInt, bits=16, signed=True, iec_name="INT"):
    """16-bit signed integer (-32768 to 32767)."""


class dint(_PlcInt, bits=32, signed=True, iec_name="DINT"):
    """32-bit signed integer (-2147483648 to 2147483647)."""


class lint(_PlcInt, bits=64, signed=True, iec_name="LINT"):
    """64-bit signed integer."""


# ---------------------------------------------------------------------------
# Unsigned integers
# ---------------------------------------------------------------------------

class usint(_PlcInt, bits=8, signed=False, iec_name="USINT"):
    """8-bit unsigned integer (0 to 255)."""


class uint(_PlcInt, bits=16, signed=False, iec_name="UINT"):
    """16-bit unsigned integer (0 to 65535)."""


class udint(_PlcInt, bits=32, signed=False, iec_name="UDINT"):
    """32-bit unsigned integer (0 to 4294967295)."""


class ulint(_PlcInt, bits=64, signed=False, iec_name="ULINT"):
    """64-bit unsigned integer."""


# ---------------------------------------------------------------------------
# Bit-strings
# ---------------------------------------------------------------------------

class byte(_PlcInt, bits=8, signed=False, iec_name="BYTE"):
    """8-bit bit-string."""


class word(_PlcInt, bits=16, signed=False, iec_name="WORD"):
    """16-bit bit-string."""


class dword(_PlcInt, bits=32, signed=False, iec_name="DWORD"):
    """32-bit bit-string."""


class lword(_PlcInt, bits=64, signed=False, iec_name="LWORD"):
    """64-bit bit-string."""


# ---------------------------------------------------------------------------
# Floating point
# ---------------------------------------------------------------------------

class real(_PlcFloat):
    """32-bit float (IEC REAL, IEEE 754 single precision)."""

    _bits = 32
    _iec_name = "REAL"

    def __new__(cls, value: object = 0.0) -> "real":
        v = _struct.unpack("f", _struct.pack("f", builtins.float(value)))[0]
        return builtins.float.__new__(cls, v)


class lreal(_PlcFloat):
    """64-bit float (IEC LREAL, IEEE 754 double precision)."""

    _bits = 64
    _iec_name = "LREAL"

    def __new__(cls, value: object = 0.0) -> "lreal":
        return builtins.float.__new__(cls, builtins.float(value))

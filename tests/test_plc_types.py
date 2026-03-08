"""Tests for PLC data type classes with IEC 61131-3 overflow semantics."""

import builtins
import math

import pytest

from plx.framework._plc_types import (
    _PlcInt,
    _PlcFloat,
    sint,
    int as plc_int,
    dint,
    lint,
    usint,
    uint,
    udint,
    ulint,
    real,
    lreal,
    byte,
    word,
    dword,
    lword,
)
from plx.framework._types import _resolve_type_ref
from plx.model.types import PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# Construction and overflow wrapping
# ---------------------------------------------------------------------------

class TestSignedOverflow:
    def test_sint_positive_overflow(self):
        assert sint(128) == -128

    def test_sint_negative_overflow(self):
        assert sint(-129) == 127

    def test_sint_range(self):
        assert sint(127) == 127
        assert sint(-128) == -128

    def test_int_positive_overflow(self):
        assert plc_int(32768) == -32768

    def test_int_negative_overflow(self):
        assert plc_int(-32769) == 32767

    def test_int_range(self):
        assert plc_int(32767) == 32767
        assert plc_int(-32768) == -32768

    def test_dint_positive_overflow(self):
        assert dint(2**31) == -(2**31)

    def test_dint_negative_overflow(self):
        assert dint(-(2**31) - 1) == 2**31 - 1

    def test_dint_range(self):
        assert dint(2**31 - 1) == 2**31 - 1
        assert dint(-(2**31)) == -(2**31)

    def test_lint_positive_overflow(self):
        assert lint(2**63) == -(2**63)

    def test_lint_negative_overflow(self):
        assert lint(-(2**63) - 1) == 2**63 - 1

    def test_dint_wrap_around(self):
        """Two's complement: max + 1 wraps to min."""
        assert dint(2_147_483_647) + dint(1) == dint(-2_147_483_648)

    def test_sint_wrap_around(self):
        assert sint(-128) - sint(1) == sint(127)


class TestUnsignedOverflow:
    def test_usint_overflow(self):
        assert usint(256) == 0
        assert usint(300) == 44

    def test_usint_underflow(self):
        assert usint(-1) == 255

    def test_uint_overflow(self):
        assert uint(65536) == 0

    def test_uint_underflow(self):
        assert uint(-1) == 65535

    def test_udint_overflow(self):
        assert udint(2**32) == 0

    def test_udint_underflow(self):
        assert udint(-1) == 2**32 - 1

    def test_ulint_overflow(self):
        assert ulint(2**64) == 0

    def test_usint_wrap_around(self):
        assert usint(250) + usint(10) == usint(4)


class TestBitStrings:
    def test_byte_range(self):
        assert byte(255) == 255
        assert byte(256) == 0
        assert byte(-1) == 255

    def test_word_range(self):
        assert word(65535) == 65535
        assert word(65536) == 0

    def test_dword_range(self):
        assert dword(2**32 - 1) == 2**32 - 1
        assert dword(2**32) == 0

    def test_lword_range(self):
        assert lword(2**64 - 1) == 2**64 - 1
        assert lword(2**64) == 0


class TestDefaults:
    def test_default_zero(self):
        assert dint() == 0
        assert real() == 0.0
        assert usint() == 0
        assert lreal() == 0.0


# ---------------------------------------------------------------------------
# Float precision
# ---------------------------------------------------------------------------

class TestFloatPrecision:
    def test_real_32bit_truncation(self):
        """REAL loses precision compared to Python float."""
        # Python float (64-bit) can distinguish these
        a = 1.00000001
        b = 1.00000002
        assert a != b
        # REAL (32-bit) cannot — both round to the same single-precision value
        assert real(a) == real(b)

    def test_lreal_64bit_precision(self):
        """LREAL preserves full Python float precision."""
        a = 1.0000001
        b = 1.0000002
        assert lreal(a) != lreal(b)

    def test_real_arithmetic_stays_32bit(self):
        """Arithmetic on REAL stays 32-bit."""
        r = real(1.0) + real(1e-8)
        assert r == real(1.0)  # 1e-8 is below 32-bit precision

    def test_lreal_arithmetic_preserves_precision(self):
        r = lreal(1.0) + lreal(1e-15)
        assert r != lreal(1.0)

    def test_real_nan(self):
        r = real(float("nan"))
        assert math.isnan(r)

    def test_real_inf(self):
        r = real(float("inf"))
        assert math.isinf(r)


# ---------------------------------------------------------------------------
# Type preservation in arithmetic
# ---------------------------------------------------------------------------

class TestTypePreservation:
    def test_add_preserves_type(self):
        assert type(dint(1) + dint(2)) is dint

    def test_sub_preserves_type(self):
        assert type(dint(10) - dint(3)) is dint

    def test_mul_preserves_type(self):
        assert type(sint(2) * sint(3)) is sint

    def test_floordiv_preserves_type(self):
        assert type(dint(10) // dint(3)) is dint

    def test_mod_preserves_type(self):
        assert type(dint(10) % dint(3)) is dint

    def test_neg_preserves_type(self):
        assert type(-dint(5)) is dint

    def test_abs_preserves_type(self):
        assert type(abs(sint(-5))) is sint

    def test_bitwise_and_preserves_type(self):
        assert type(dword(0xFF) & dword(0x0F)) is dword

    def test_bitwise_or_preserves_type(self):
        assert type(byte(0xF0) | byte(0x0F)) is byte

    def test_bitwise_xor_preserves_type(self):
        assert type(word(0xFF) ^ word(0x0F)) is word

    def test_lshift_preserves_type(self):
        assert type(dword(1) << 8) is dword

    def test_rshift_preserves_type(self):
        assert type(dword(256) >> 4) is dword

    def test_invert_preserves_type(self):
        assert type(~byte(0)) is byte

    def test_real_add_preserves_type(self):
        assert type(real(1.0) + real(2.0)) is real

    def test_real_mul_preserves_type(self):
        assert type(real(2.0) * real(3.0)) is real

    def test_real_truediv_preserves_type(self):
        assert type(real(10.0) / real(3.0)) is real

    def test_lreal_add_preserves_type(self):
        assert type(lreal(1.0) + lreal(2.0)) is lreal

    def test_radd_preserves_type(self):
        """5 + dint(3) should return dint."""
        result = 5 + dint(3)
        assert type(result) is dint
        assert result == dint(8)

    def test_pow_preserves_type(self):
        assert type(dint(2) ** 3) is dint
        assert dint(2) ** 3 == dint(8)

    def test_pow_negative_returns_float(self):
        """Negative exponent returns Python float, not wrapped int."""
        result = dint(2) ** -1
        assert isinstance(result, builtins.float)


# ---------------------------------------------------------------------------
# Repr and str
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_dint(self):
        assert repr(dint(42)) == "dint(42)"

    def test_repr_sint(self):
        assert repr(sint(-5)) == "sint(-5)"

    def test_repr_real(self):
        assert repr(real(3.14)).startswith("real(")

    def test_repr_lreal(self):
        assert repr(lreal(3.14)).startswith("lreal(")

    def test_repr_byte(self):
        assert repr(byte(255)) == "byte(255)"

    def test_str_dint(self):
        """str() returns plain number, not type-wrapped."""
        assert str(dint(42)) == "42"

    def test_str_real(self):
        # float str should be a plain number
        s = str(real(3.14))
        assert "real" not in s


# ---------------------------------------------------------------------------
# isinstance compatibility
# ---------------------------------------------------------------------------

class TestIsinstance:
    def test_dint_is_int(self):
        assert isinstance(dint(5), builtins.int)

    def test_sint_is_int(self):
        assert isinstance(sint(5), builtins.int)

    def test_real_is_float(self):
        assert isinstance(real(3.14), builtins.float)

    def test_lreal_is_float(self):
        assert isinstance(lreal(3.14), builtins.float)

    def test_dint_is_plcint(self):
        assert isinstance(dint(5), _PlcInt)

    def test_real_is_plcfloat(self):
        assert isinstance(real(3.14), _PlcFloat)

    def test_bool_not_plcint(self):
        assert not isinstance(True, _PlcInt)

    def test_byte_is_plcint(self):
        assert isinstance(byte(42), _PlcInt)


# ---------------------------------------------------------------------------
# Hash compatibility
# ---------------------------------------------------------------------------

class TestHash:
    def test_dint_hash_matches_int(self):
        assert hash(dint(42)) == hash(42)

    def test_real_hash_matches_float(self):
        r = real(3.14)
        assert hash(r) == hash(builtins.float(r))


# ---------------------------------------------------------------------------
# Type resolution (framework integration)
# ---------------------------------------------------------------------------

class TestResolveTypeRef:
    def test_dint_resolves(self):
        ref = _resolve_type_ref(dint)
        assert isinstance(ref, PrimitiveTypeRef)
        assert ref.type == PrimitiveType.DINT

    def test_sint_resolves(self):
        ref = _resolve_type_ref(sint)
        assert ref.type == PrimitiveType.SINT

    def test_plc_int_resolves_to_int(self):
        ref = _resolve_type_ref(plc_int)
        assert ref.type == PrimitiveType.INT

    def test_real_resolves(self):
        ref = _resolve_type_ref(real)
        assert ref.type == PrimitiveType.REAL

    def test_lreal_resolves(self):
        ref = _resolve_type_ref(lreal)
        assert ref.type == PrimitiveType.LREAL

    def test_byte_resolves(self):
        ref = _resolve_type_ref(byte)
        assert ref.type == PrimitiveType.BYTE

    def test_word_resolves(self):
        ref = _resolve_type_ref(word)
        assert ref.type == PrimitiveType.WORD

    def test_uint_resolves(self):
        ref = _resolve_type_ref(uint)
        assert ref.type == PrimitiveType.UINT

    def test_udint_resolves(self):
        ref = _resolve_type_ref(udint)
        assert ref.type == PrimitiveType.UDINT

    def test_builtin_int_still_dint(self):
        """builtins.int should still map to DINT for backwards compat."""
        ref = _resolve_type_ref(builtins.int)
        assert ref.type == PrimitiveType.DINT

    def test_builtin_float_still_real(self):
        ref = _resolve_type_ref(builtins.float)
        assert ref.type == PrimitiveType.REAL

    def test_builtin_bool_still_bool(self):
        ref = _resolve_type_ref(builtins.bool)
        assert ref.type == PrimitiveType.BOOL


# ---------------------------------------------------------------------------
# Compiler integration — lowercase type annotations in logic()
# ---------------------------------------------------------------------------

class TestCompilerAnnotations:
    def test_dint_annotation_in_logic(self):
        """x: dint = 0 inside logic() should compile."""
        from conftest import compile_stmts
        from plx.framework._compiler_core import CompileContext
        ctx = CompileContext()
        stmts = compile_stmts("x: dint = 0", ctx)
        # Should produce an assignment and register the temp var
        assert any(v.name == "x" for v in ctx.generated_temp_vars)

    def test_real_annotation_in_logic(self):
        from conftest import compile_stmts
        from plx.framework._compiler_core import CompileContext
        ctx = CompileContext()
        stmts = compile_stmts("x: real = 0.0", ctx)
        assert any(v.name == "x" for v in ctx.generated_temp_vars)

    def test_lowercase_type_conversion(self):
        """dint(x) in logic() should compile to TypeConversionExpr."""
        from conftest import compile_expr
        from plx.model.expressions import TypeConversionExpr
        result = compile_expr("dint(x)")
        assert isinstance(result, TypeConversionExpr)
        assert isinstance(result.target_type, PrimitiveTypeRef)
        assert result.target_type.type == PrimitiveType.DINT

    def test_lowercase_real_conversion(self):
        from conftest import compile_expr
        from plx.model.expressions import TypeConversionExpr
        result = compile_expr("real(x)")
        assert isinstance(result, TypeConversionExpr)
        assert result.target_type.type == PrimitiveType.REAL


# ---------------------------------------------------------------------------
# Parametrized overflow tests across all types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,bits,signed", [
    (sint, 8, True),
    (plc_int, 16, True),
    (dint, 32, True),
    (lint, 64, True),
    (usint, 8, False),
    (uint, 16, False),
    (udint, 32, False),
    (ulint, 64, False),
    (byte, 8, False),
    (word, 16, False),
    (dword, 32, False),
    (lword, 64, False),
])
class TestParametrizedOverflow:
    def test_max_value(self, cls, bits, signed):
        if signed:
            max_val = 2 ** (bits - 1) - 1
        else:
            max_val = 2 ** bits - 1
        assert cls(max_val) == max_val

    def test_min_value(self, cls, bits, signed):
        if signed:
            min_val = -(2 ** (bits - 1))
        else:
            min_val = 0
        assert cls(min_val) == min_val

    def test_overflow_wraps(self, cls, bits, signed):
        if signed:
            max_val = 2 ** (bits - 1) - 1
            assert cls(max_val + 1) == -(2 ** (bits - 1))
        else:
            max_val = 2 ** bits - 1
            assert cls(max_val + 1) == 0

    def test_zero(self, cls, bits, signed):
        assert cls(0) == 0

    def test_type_identity(self, cls, bits, signed):
        assert type(cls(42 if not signed else -1)) is cls

"""Tests for math module integration in the framework compiler."""

import math

import pytest

from plx.framework import (
    REAL,
    CompileError,
    Input,
    Output,
    fb,
    function,
)
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    FunctionCallExpr,
    LiteralExpr,
    VariableRef,
)
from plx.model.statements import Assignment

# ---------------------------------------------------------------------------
# math functions → IEC function calls
# ---------------------------------------------------------------------------


class TestMathFunctions:
    """math.func(x) compiles to IEC FunctionCallExpr."""

    def _get_assignment(self, cls):
        pou = cls.compile()
        body = pou.networks[0].statements if pou.networks else pou.sfc_body
        return body[0]

    def test_math_sqrt(self):
        @fb
        class MathFB:
            x: Input[REAL]
            y: Output[REAL]

            def logic(self):
                self.y = math.sqrt(self.x)

        stmt = self._get_assignment(MathFB)
        assert isinstance(stmt, Assignment)
        call = stmt.value
        assert isinstance(call, FunctionCallExpr)
        assert call.function_name == "SQRT"
        assert len(call.args) == 1
        assert isinstance(call.args[0].value, VariableRef)
        assert call.args[0].value.name == "x"

    def test_math_sin(self):
        @fb
        class SinFB:
            angle: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.sin(self.angle)

        stmt = self._get_assignment(SinFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "SIN"

    def test_math_cos(self):
        @fb
        class CosFB:
            angle: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.cos(self.angle)

        stmt = self._get_assignment(CosFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "COS"

    def test_math_tan(self):
        @fb
        class TanFB:
            angle: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.tan(self.angle)

        stmt = self._get_assignment(TanFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "TAN"

    def test_math_asin(self):
        @fb
        class AsinFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.asin(self.x)

        stmt = self._get_assignment(AsinFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "ASIN"

    def test_math_acos(self):
        @fb
        class AcosFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.acos(self.x)

        stmt = self._get_assignment(AcosFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "ACOS"

    def test_math_atan(self):
        @fb
        class AtanFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.atan(self.x)

        stmt = self._get_assignment(AtanFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "ATAN"

    def test_atan2_rejected(self):
        """math.atan2() is not supported — no vendor supports it natively."""
        with pytest.raises(CompileError, match=r"math\.atan2.*not supported"):

            @fb
            class Atan2FB:
                y: Input[REAL]
                x: Input[REAL]
                result: Output[REAL]

                def logic(self):
                    self.result = math.atan2(self.y, self.x)

    def test_ceil_uppercase(self):
        """CEIL() works as a direct IEC function name."""

        @fb
        class CeilUpperFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = CEIL(self.x)  # noqa: F821

        stmt = self._get_assignment(CeilUpperFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "CEIL"

    def test_floor_uppercase(self):
        """FLOOR() works as a direct IEC function name."""

        @fb
        class FloorUpperFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = FLOOR(self.x)  # noqa: F821

        stmt = self._get_assignment(FloorUpperFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "FLOOR"

    def test_math_log_natural(self):
        @fb
        class LogFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.log(self.x)

        stmt = self._get_assignment(LogFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "LN"

    def test_math_log10(self):
        @fb
        class Log10FB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.log10(self.x)

        stmt = self._get_assignment(Log10FB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "LOG"

    def test_math_exp(self):
        @fb
        class ExpFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.exp(self.x)

        stmt = self._get_assignment(ExpFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "EXP"

    def test_math_fabs(self):
        @fb
        class FabsFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.fabs(self.x)

        stmt = self._get_assignment(FabsFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "ABS"

    def test_math_trunc(self):
        @fb
        class TruncFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.trunc(self.x)

        stmt = self._get_assignment(TruncFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "TRUNC"

    def test_math_ceil(self):
        @fb
        class CeilFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.ceil(self.x)

        stmt = self._get_assignment(CeilFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "CEIL"

    def test_math_floor(self):
        @fb
        class FloorFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.floor(self.x)

        stmt = self._get_assignment(FloorFB)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "FLOOR"


# ---------------------------------------------------------------------------
# math constants
# ---------------------------------------------------------------------------


class TestMathConstants:
    """math.pi, math.e, math.tau compile to LiteralExpr."""

    def _get_assignment(self, cls):
        pou = cls.compile()
        return pou.networks[0].statements[0]

    def test_math_pi(self):
        @fb
        class PiFB:
            result: Output[REAL]

            def logic(self):
                self.result = math.pi

        stmt = self._get_assignment(PiFB)
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, LiteralExpr)
        assert stmt.value.value == "3.141592653589793"

    def test_math_e(self):
        @fb
        class EFB:
            result: Output[REAL]

            def logic(self):
                self.result = math.e

        stmt = self._get_assignment(EFB)
        assert isinstance(stmt.value, LiteralExpr)
        assert stmt.value.value == "2.718281828459045"

    def test_math_tau(self):
        @fb
        class TauFB:
            result: Output[REAL]

            def logic(self):
                self.result = math.tau

        stmt = self._get_assignment(TauFB)
        assert isinstance(stmt.value, LiteralExpr)
        assert stmt.value.value == "6.283185307179586"

    def test_math_pi_in_expression(self):
        @fb
        class CircleFB:
            radius: Input[REAL]
            area: Output[REAL]

            def logic(self):
                self.area = math.pi * self.radius**2

        stmt = self._get_assignment(CircleFB)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == BinaryOp.MUL
        assert isinstance(stmt.value.left, LiteralExpr)
        assert stmt.value.left.value == "3.141592653589793"


# ---------------------------------------------------------------------------
# Expressions with math
# ---------------------------------------------------------------------------


class TestMathExpressions:
    """math functions used in complex expressions."""

    def _get_assignment(self, cls):
        pou = cls.compile()
        return pou.networks[0].statements[0]

    def test_math_in_complex_expression(self):
        @fb
        class ComplexFB:
            x: Input[REAL]
            y: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.sqrt(self.x**2 + self.y**2)

        stmt = self._get_assignment(ComplexFB)
        call = stmt.value
        assert isinstance(call, FunctionCallExpr)
        assert call.function_name == "SQRT"
        inner = call.args[0].value
        assert isinstance(inner, BinaryExpr)
        assert inner.op == BinaryOp.ADD

    def test_math_nested_calls(self):
        @fb
        class NestedFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.sin(math.sqrt(self.x))

        stmt = self._get_assignment(NestedFB)
        outer = stmt.value
        assert isinstance(outer, FunctionCallExpr)
        assert outer.function_name == "SIN"
        inner = outer.args[0].value
        assert isinstance(inner, FunctionCallExpr)
        assert inner.function_name == "SQRT"

    def test_math_in_function_return(self):
        @function
        class Hypotenuse:
            a: Input[REAL]
            b: Input[REAL]

            def logic(self) -> REAL:
                return math.sqrt(self.a**2 + self.b**2)

        pou = Hypotenuse.compile()
        ret_stmt = pou.networks[0].statements[0]
        call = ret_stmt.value
        assert isinstance(call, FunctionCallExpr)
        assert call.function_name == "SQRT"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestMathErrors:
    """Unsupported math functions/attributes produce clear errors."""

    def test_unsupported_math_function(self):
        with pytest.raises(CompileError, match=r"math\.factorial.*not supported"):

            @fb
            class BadFB:
                x: Input[REAL]
                result: Output[REAL]

                def logic(self):
                    self.result = math.factorial(self.x)

    def test_unsupported_math_constant(self):
        with pytest.raises(CompileError, match=r"math\.nan.*not supported"):

            @fb
            class BadFB2:
                result: Output[REAL]

                def logic(self):
                    self.result = math.nan

    def test_clamp_wrong_arg_count(self):
        with pytest.raises(CompileError, match="exactly 3"):

            @fb
            class BadClamp:
                x: Input[REAL]
                result: Output[REAL]

                def logic(self):
                    self.result = math.clamp(self.x, 0.0)

    def test_clamp_in_error_message(self):
        """math.clamp should appear in the supported functions list."""
        with pytest.raises(CompileError, match="clamp"):

            @fb
            class BadMathFB:
                x: Input[REAL]
                result: Output[REAL]

                def logic(self):
                    self.result = math.factorial(self.x)


# ---------------------------------------------------------------------------
# math.clamp → LIMIT
# ---------------------------------------------------------------------------


class TestMathClamp:
    """math.clamp(value, min, max) → LIMIT(min, value, max)."""

    def _get_assignment(self, cls):
        pou = cls.compile()
        return pou.networks[0].statements[0]

    def test_clamp_basic(self):
        @fb
        class ClampFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.clamp(self.x, 0.0, 100.0)

        stmt = self._get_assignment(ClampFB)
        call = stmt.value
        assert isinstance(call, FunctionCallExpr)
        assert call.function_name == "LIMIT"
        assert len(call.args) == 3
        # Arg order: LIMIT(mn, value, mx)
        assert isinstance(call.args[0].value, LiteralExpr)
        assert call.args[0].value.value == "0.0"
        assert isinstance(call.args[1].value, VariableRef)
        assert call.args[1].value.name == "x"
        assert isinstance(call.args[2].value, LiteralExpr)
        assert call.args[2].value.value == "100.0"

    def test_clamp_with_variables(self):
        @fb
        class ClampVarFB:
            x: Input[REAL]
            lo: Input[REAL]
            hi: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.clamp(self.x, self.lo, self.hi)

        stmt = self._get_assignment(ClampVarFB)
        call = stmt.value
        assert call.function_name == "LIMIT"
        # LIMIT(lo, x, hi)
        assert call.args[0].value.name == "lo"
        assert call.args[1].value.name == "x"
        assert call.args[2].value.name == "hi"

    def test_clamp_in_expression(self):
        @fb
        class ClampExprFB:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.clamp(self.x, 0.0, 100.0) * 2.0

        stmt = self._get_assignment(ClampExprFB)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == BinaryOp.MUL
        assert isinstance(stmt.value.left, FunctionCallExpr)
        assert stmt.value.left.function_name == "LIMIT"

    def test_clamp_round_trip(self):
        """LIMIT(mn, val, mx) → math.clamp(val, mn, mx) in Python export."""
        from plx.export.py import generate
        from plx.model.project import Project

        @fb
        class ClampRT:
            x: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = math.clamp(self.x, 0.0, 100.0)

        pou = ClampRT.compile()
        code = generate(Project(name="test", pous=[pou]))
        assert "math.clamp(self.x, 0.0, 100.0)" in code

"""Tests for AB math function expression rewrite rules."""

import pytest

from plx.framework._math_rewrites import (
    make_ab_name_rewriter,
    rewrite_ceil,
    rewrite_exp_to_expt,
    rewrite_floor,
    rewrite_function_name,
)
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    CallArg,
    FunctionCallExpr,
    LiteralExpr,
    VariableRef,
)


def _make_call(name: str, *args: str) -> FunctionCallExpr:
    """Helper: build FunctionCallExpr with VariableRef args."""
    return FunctionCallExpr(
        function_name=name,
        args=[CallArg(value=VariableRef(name=a)) for a in args],
    )


# ---------------------------------------------------------------------------
# rewrite_exp_to_expt
# ---------------------------------------------------------------------------


class TestRewriteExp:
    def test_exp_to_expt(self):
        expr = _make_call("EXP", "x")
        result = rewrite_exp_to_expt(expr)
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.EXPT
        assert isinstance(result.left, LiteralExpr)
        assert result.left.value == "2.718281828459045"
        assert isinstance(result.right, VariableRef)
        assert result.right.name == "x"

    def test_non_exp_returns_none(self):
        expr = _make_call("SIN", "x")
        assert rewrite_exp_to_expt(expr) is None

    def test_non_function_returns_none(self):
        expr = VariableRef(name="x")
        assert rewrite_exp_to_expt(expr) is None


# ---------------------------------------------------------------------------
# rewrite_ceil
# ---------------------------------------------------------------------------


class TestRewriteCeil:
    def test_ceil_structure(self):
        expr = _make_call("CEIL", "x")
        result = rewrite_ceil(expr)
        # TRUNC(x) + SEL(x > TRUNC(x), 0, 1)
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.ADD
        # Left: TRUNC(x)
        trunc = result.left
        assert isinstance(trunc, FunctionCallExpr)
        assert trunc.function_name == "TRUNC"
        # Right: SEL(...)
        sel = result.right
        assert isinstance(sel, FunctionCallExpr)
        assert sel.function_name == "SEL"
        assert len(sel.args) == 3
        # SEL condition: x > TRUNC(x)
        cmp = sel.args[0].value
        assert isinstance(cmp, BinaryExpr)
        assert cmp.op == BinaryOp.GT

    def test_non_ceil_returns_none(self):
        assert rewrite_ceil(_make_call("FLOOR", "x")) is None

    def test_non_function_returns_none(self):
        assert rewrite_ceil(VariableRef(name="x")) is None


# ---------------------------------------------------------------------------
# rewrite_floor
# ---------------------------------------------------------------------------


class TestRewriteFloor:
    def test_floor_structure(self):
        expr = _make_call("FLOOR", "x")
        result = rewrite_floor(expr)
        # TRUNC(x) - SEL(TRUNC(x) > x, 1, 0)
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.SUB
        # Left: TRUNC(x)
        trunc = result.left
        assert isinstance(trunc, FunctionCallExpr)
        assert trunc.function_name == "TRUNC"
        # Right: SEL(...)
        sel = result.right
        assert isinstance(sel, FunctionCallExpr)
        assert sel.function_name == "SEL"
        assert len(sel.args) == 3
        # SEL condition: TRUNC(x) > x
        cmp = sel.args[0].value
        assert isinstance(cmp, BinaryExpr)
        assert cmp.op == BinaryOp.GT
        # For FLOOR, comparison is TRUNC(x) > x (opposite of CEIL)
        assert isinstance(cmp.left, FunctionCallExpr)
        assert cmp.left.function_name == "TRUNC"

    def test_non_floor_returns_none(self):
        assert rewrite_floor(_make_call("CEIL", "x")) is None


# ---------------------------------------------------------------------------
# rewrite_function_name
# ---------------------------------------------------------------------------


class TestRewriteFunctionName:
    @pytest.mark.parametrize(
        "iec_name,ab_name",
        [
            ("SQRT", "SQR"),
            ("ASIN", "ASN"),
            ("ACOS", "ACS"),
            ("ATAN", "ATN"),
            ("TRUNC", "TRN"),
        ],
    )
    def test_ab_remap(self, iec_name, ab_name):
        expr = _make_call(iec_name, "x")
        result = rewrite_function_name(expr)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == ab_name
        assert len(result.args) == 1

    def test_no_remap_returns_none(self):
        expr = _make_call("SIN", "x")
        assert rewrite_function_name(expr) is None

    def test_custom_remap(self):
        expr = _make_call("FOO", "x")
        result = rewrite_function_name(expr, remap={"FOO": "BAR"})
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "BAR"

    def test_non_function_returns_none(self):
        assert rewrite_function_name(VariableRef(name="x")) is None

    def test_make_ab_name_rewriter(self):
        rewriter = make_ab_name_rewriter()
        expr = _make_call("SQRT", "x")
        result = rewriter(expr)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "SQR"

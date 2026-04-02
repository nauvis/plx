"""Regression tests for quality review fixes (2026-03-19).

Covers: precedence table fix, FOR loop var type, method-call receiver,
walker BitAccessExpr traversal.
"""

from plx.export.py._helpers import _BINOP_PRECEDENCE
from plx.export.py._writer import PyWriter
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    Expression,
    VariableRef,
)
from plx.model.statements import FunctionCallStatement
from plx.model.types import PrimitiveType, PrimitiveTypeRef
from plx.model.walk import walk_expressions

# ---------------------------------------------------------------------------
# Fix 1: Precedence table — bitwise must bind tighter than comparisons
# ---------------------------------------------------------------------------


class TestPrecedenceTable:
    """Verify Python precedence: comparisons < bitwise < arithmetic."""

    def test_bitwise_tighter_than_comparisons(self):
        """BAND/BOR/XOR must have higher precedence than EQ/NE/LT/GT/LE/GE."""
        for cmp_op in (BinaryOp.EQ, BinaryOp.NE, BinaryOp.LT, BinaryOp.GT, BinaryOp.LE, BinaryOp.GE):
            for bit_op in (BinaryOp.BAND, BinaryOp.BOR, BinaryOp.XOR):
                assert _BINOP_PRECEDENCE[bit_op] > _BINOP_PRECEDENCE[cmp_op], (
                    f"{bit_op.value} (prec={_BINOP_PRECEDENCE[bit_op]}) should "
                    f"bind tighter than {cmp_op.value} (prec={_BINOP_PRECEDENCE[cmp_op]})"
                )

    def test_band_eq_parenthesization(self):
        """BAND(EQ(a, b), c) must emit ``(a == b) & c``, not ``a == b & c``."""
        # IR: BAND(EQ(a, b), c)
        expr = BinaryExpr(
            op=BinaryOp.BAND,
            left=BinaryExpr(
                op=BinaryOp.EQ,
                left=VariableRef(name="a"),
                right=VariableRef(name="b"),
            ),
            right=VariableRef(name="c"),
        )
        w = PyWriter()
        result = w._expr(expr)
        assert result == "(a == b) & c", f"Got: {result}"

    def test_bor_ne_parenthesization(self):
        """BOR(NE(x, y), z) must emit ``(x != y) | z``."""
        expr = BinaryExpr(
            op=BinaryOp.BOR,
            left=BinaryExpr(
                op=BinaryOp.NE,
                left=VariableRef(name="x"),
                right=VariableRef(name="y"),
            ),
            right=VariableRef(name="z"),
        )
        w = PyWriter()
        result = w._expr(expr)
        assert result == "(x != y) | z", f"Got: {result}"

    def test_comparison_inside_bitwise_gets_parens(self):
        """a & (b == c) — comparison as child of bitwise needs parens."""
        expr = BinaryExpr(
            op=BinaryOp.BAND,
            left=VariableRef(name="a"),
            right=BinaryExpr(
                op=BinaryOp.EQ,
                left=VariableRef(name="b"),
                right=VariableRef(name="c"),
            ),
        )
        w = PyWriter()
        result = w._expr(expr)
        assert "(b == c)" in result, f"Got: {result}"

    def test_bitwise_no_parens_when_not_needed(self):
        """a & b — no parens when both sides are simple."""
        expr = BinaryExpr(
            op=BinaryOp.BAND,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        w = PyWriter()
        result = w._expr(expr)
        assert result == "a & b", f"Got: {result}"


# ---------------------------------------------------------------------------
# Fix 7a: FOR loop auto-generated var is DINT (not INT)
# ---------------------------------------------------------------------------


class TestForLoopVarType:
    """Verify auto-generated FOR loop variable is DINT."""

    def test_for_loop_var_is_dint(self):
        from plx.framework import DINT, Output, fb

        @fb
        class ForLoopTest:
            result: Output[DINT] = 0

            def logic(self):
                for i in range(10):
                    self.result = self.result + i

        pou = ForLoopTest._compiled_pou
        # The auto-generated loop variable 'i' should be DINT
        temp_vars = pou.interface.temp_vars
        loop_var = next((v for v in temp_vars if v.name == "i"), None)
        assert loop_var is not None, "Loop variable 'i' not found in temp_vars"
        assert isinstance(loop_var.data_type, PrimitiveTypeRef)
        assert loop_var.data_type.type == PrimitiveType.DINT


# ---------------------------------------------------------------------------
# Fix 7b: Method call receiver preserved in IR
# ---------------------------------------------------------------------------


class TestMethodCallReceiver:
    """Verify self.fb.Method() compiles with dotted function_name."""

    def test_method_call_has_dotted_name(self):
        from plx.framework import BOOL, Output, Static, fb

        @fb
        class InnerFB:
            done: Output[BOOL] = False

            def logic(self):
                self.done = True

        @fb
        class OuterFB:
            inner: Static[InnerFB]

            def logic(self):
                self.inner.Reset()

        pou = OuterFB._compiled_pou
        stmts = pou.networks[0].statements
        # Find the FunctionCallStatement
        call_stmts = [s for s in stmts if isinstance(s, FunctionCallStatement)]
        assert len(call_stmts) == 1
        call = call_stmts[0]
        # function_name should be "inner.Reset", not just "Reset"
        assert call.function_name == "inner.Reset", f"Got: {call.function_name}"
        # No receiver arg should be present
        assert len(call.args) == 0


# ---------------------------------------------------------------------------
# Fix 7c: walk_expressions visits BitAccessExpr.bit_index
# ---------------------------------------------------------------------------


class TestWalkerBitAccessExpr:
    """Verify walk_expressions descends into BitAccessExpr.bit_index."""

    def test_bit_index_expression_visited(self):
        """Dynamic bit_index (Expression) must be yielded by walk_expressions."""
        inner = VariableRef(name="bit_idx")
        expr = BitAccessExpr(
            target=VariableRef(name="word_var"),
            bit_index=inner,
        )
        visited: list[Expression] = []
        walk_expressions(expr, visited.append)
        # Should visit: BitAccessExpr, VariableRef("word_var"), VariableRef("bit_idx")
        assert inner in visited, "BitAccessExpr.bit_index not visited"

    def test_bit_index_int_not_yielded(self):
        """Static bit_index (int) should not produce extra expression nodes."""
        expr = BitAccessExpr(
            target=VariableRef(name="word_var"),
            bit_index=3,
        )
        visited: list[Expression] = []
        walk_expressions(expr, visited.append)
        # Should visit: BitAccessExpr, VariableRef("word_var") — that's it
        names = [e.name for e in visited if isinstance(e, VariableRef)]
        assert "word_var" in names
        assert len(visited) == 2  # BitAccessExpr + VariableRef

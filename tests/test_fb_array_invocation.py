"""Tests for array-subscripted FB invocations (self.fb_array[i](...))."""

import ast
import textwrap

import pytest

from conftest import compile_stmts, make_pou

from plx.model.expressions import (
    ArrayAccessExpr,
    Expression,
    LiteralExpr,
    MemberAccessExpr,
    VariableRef,
)
from plx.model.pou import Network, POU, POUInterface, POUType
from plx.model.statements import FBInvocation
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
)
from plx.model.variables import Variable


BOOL_REF = PrimitiveTypeRef(type=PrimitiveType.BOOL)
INT_REF = PrimitiveTypeRef(type=PrimitiveType.INT)
DINT_REF = PrimitiveTypeRef(type=PrimitiveType.DINT)
TIME_REF = PrimitiveTypeRef(type=PrimitiveType.TIME)


# ---------------------------------------------------------------------------
# IR model: str | Expression instance_name
# ---------------------------------------------------------------------------

class TestFBInvocationModel:
    """FBInvocation accepts both str and Expression for instance_name."""

    def test_str_instance_name(self):
        inv = FBInvocation(instance_name="timer", fb_type="TON")
        assert inv.instance_name == "timer"

    def test_expression_instance_name(self):
        expr = ArrayAccessExpr(
            array=VariableRef(name="timers"),
            indices=[LiteralExpr(value="0")],
        )
        inv = FBInvocation(instance_name=expr, fb_type="TON")
        assert isinstance(inv.instance_name, ArrayAccessExpr)
        assert inv.instance_name.array.name == "timers"

    def test_json_roundtrip_str(self):
        inv = FBInvocation(
            instance_name="timer",
            fb_type="TON",
            inputs={"IN": LiteralExpr(value="TRUE", data_type=BOOL_REF)},
        )
        json_str = inv.model_dump_json()
        restored = FBInvocation.model_validate_json(json_str)
        assert restored.instance_name == "timer"
        assert restored.fb_type == "TON"

    def test_json_roundtrip_expression(self):
        expr = ArrayAccessExpr(
            array=VariableRef(name="timers"),
            indices=[LiteralExpr(value="2")],
        )
        inv = FBInvocation(
            instance_name=expr,
            fb_type="TON",
            inputs={"IN": LiteralExpr(value="TRUE", data_type=BOOL_REF)},
        )
        json_str = inv.model_dump_json()
        restored = FBInvocation.model_validate_json(json_str)
        assert isinstance(restored.instance_name, ArrayAccessExpr)
        assert restored.instance_name.array.name == "timers"
        assert restored.fb_type == "TON"

    def test_member_access_expression_instance(self):
        """MemberAccessExpr as instance_name (e.g. group.timer)."""
        expr = MemberAccessExpr(
            struct=VariableRef(name="group"),
            member="timer",
        )
        inv = FBInvocation(instance_name=expr, fb_type="TON")
        json_str = inv.model_dump_json()
        restored = FBInvocation.model_validate_json(json_str)
        assert isinstance(restored.instance_name, MemberAccessExpr)


# ---------------------------------------------------------------------------
# ST export
# ---------------------------------------------------------------------------

class TestSTExportFBArray:
    def test_export_array_access_instance(self):
        from plx.export.st import format_statement

        inv = FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name="timers"),
                indices=[VariableRef(name="i")],
            ),
            fb_type="TON",
            inputs={
                "IN": VariableRef(name="signal"),
                "PT": LiteralExpr(value="T#5s"),
            },
        )
        st = format_statement(inv)
        assert "timers[i](" in st
        assert "IN := signal" in st
        assert "PT := T#5s" in st

    def test_export_str_instance_unchanged(self):
        from plx.export.st import format_statement

        inv = FBInvocation(
            instance_name="timer",
            fb_type="TON",
            inputs={"IN": LiteralExpr(value="TRUE", data_type=BOOL_REF)},
        )
        st = format_statement(inv)
        assert st.startswith("timer(")


# ---------------------------------------------------------------------------
# Python export
# ---------------------------------------------------------------------------

class TestPyExportFBArray:
    def test_export_array_access_instance(self):
        from plx.export.py import PyWriter

        inv = FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name="timers"),
                indices=[VariableRef(name="i")],
            ),
            fb_type="TON",
            inputs={
                "IN": VariableRef(name="signal"),
                "PT": LiteralExpr(value="T#5s"),
            },
        )
        w = PyWriter()
        w._self_vars = {"timers", "signal"}
        w._write_fb_invocation(inv)
        text = w.getvalue()
        assert "self.timers[i](" in text


# ---------------------------------------------------------------------------
# LD transform
# ---------------------------------------------------------------------------

class TestLDTransformFBArray:
    def test_fb_array_box_label(self):
        from plx.export.ld._transform import ir_to_ld

        inv = FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name="timers"),
                indices=[LiteralExpr(value="0")],
            ),
            fb_type="TON",
            inputs={"IN": LiteralExpr(value="TRUE", data_type=BOOL_REF)},
        )
        net = Network(statements=[inv])
        ld = ir_to_ld([net])
        box = ld.rungs[0].outputs[0]
        assert "timers[0]" in box.name


# ---------------------------------------------------------------------------
# Framework compiler
# ---------------------------------------------------------------------------

class TestFrameworkCompilerFBArray:
    def _make_ctx(self):
        from plx.framework._compiler import CompileContext
        from plx.framework._descriptors import VarDirection
        ctx = CompileContext()
        ctx.static_var_types["timers"] = ArrayTypeRef(
            element_type=NamedTypeRef(name="TON"),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        ctx.declared_vars["timers"] = VarDirection.STATIC
        ctx.declared_vars["i"] = VarDirection.TEMP
        ctx.declared_vars["signal"] = VarDirection.STATIC
        return ctx

    def test_compile_fb_array_as_statement(self):
        ctx = self._make_ctx()
        stmts = compile_stmts("self.timers[i](IN=self.signal)", ctx=ctx)
        assert len(stmts) == 1
        inv = stmts[0]
        assert isinstance(inv, FBInvocation)
        assert isinstance(inv.instance_name, ArrayAccessExpr)
        assert inv.instance_name.array.name == "timers"
        assert inv.fb_type == "TON"
        assert "IN" in inv.inputs

    def test_compile_fb_array_as_expression(self):
        """FB array call in an if condition."""
        ctx = self._make_ctx()
        stmts = compile_stmts(
            """\
            if self.timers[i](IN=self.signal):
                self.signal = True
            """,
            ctx=ctx,
        )
        # Should produce: FBInvocation + IfStatement
        assert len(stmts) == 2
        inv = stmts[0]
        assert isinstance(inv, FBInvocation)
        assert isinstance(inv.instance_name, ArrayAccessExpr)

    def test_compile_fb_array_with_literal_index(self):
        ctx = self._make_ctx()
        stmts = compile_stmts("self.timers[0](IN=self.signal)", ctx=ctx)
        assert len(stmts) == 1
        inv = stmts[0]
        assert isinstance(inv, FBInvocation)
        assert isinstance(inv.instance_name, ArrayAccessExpr)
        # Index should be LiteralExpr("0")
        assert inv.instance_name.indices[0].value == "0"

    def test_non_array_subscript_not_treated_as_fb(self):
        """Subscript on a non-FB-array type should raise CompileError."""
        from plx.framework._compiler import CompileContext, CompileError
        from plx.framework._descriptors import VarDirection
        ctx = CompileContext()
        ctx.static_var_types["data"] = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        ctx.declared_vars["data"] = VarDirection.STATIC
        ctx.declared_vars["i"] = VarDirection.TEMP
        # self.data[i](...) on ARRAY OF INT is not an FB call → CompileError
        with pytest.raises(CompileError):
            compile_stmts("self.data[i](IN=True)", ctx=ctx)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class TestSimulatorFBArray:
    def test_execute_array_fb_invocation(self):
        """Execute an FBInvocation with ArrayAccessExpr instance_name."""
        from plx.simulate._executor import ExecutionEngine
        from plx.simulate._builtins import TON

        inv = FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name="timers"),
                indices=[LiteralExpr(value="1")],
            ),
            fb_type="TON",
            inputs={
                "IN": LiteralExpr(value="TRUE", data_type=BOOL_REF),
                "PT": LiteralExpr(value="1000"),
            },
        )

        pou = make_pou(stmts=[inv])

        # State: timers is a list of TON state dicts
        state = {
            "timers": [TON.initial_state() for _ in range(3)],
        }

        engine = ExecutionEngine(pou=pou, state=state, clock_ms=0)
        engine.execute()

        # Timer at index 1 should have IN=True, PT=1000
        assert state["timers"][1]["IN"] is True
        assert state["timers"][1]["PT"] == 1000

    def test_array_fb_timed_output(self):
        """Array FB timer should produce Q=True after PT elapsed."""
        from plx.simulate._executor import ExecutionEngine
        from plx.simulate._builtins import TON

        inv = FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name="timers"),
                indices=[LiteralExpr(value="0")],
            ),
            fb_type="TON",
            inputs={
                "IN": LiteralExpr(value="TRUE", data_type=BOOL_REF),
                "PT": LiteralExpr(value="500"),
            },
        )

        pou = make_pou(stmts=[inv])
        state = {"timers": [TON.initial_state()]}

        # First scan at t=0
        ExecutionEngine(pou=pou, state=state, clock_ms=0).execute()
        assert state["timers"][0]["Q"] is False

        # Second scan at t=500
        ExecutionEngine(pou=pou, state=state, clock_ms=500).execute()
        assert state["timers"][0]["Q"] is True

    def test_array_of_fb_state_allocation(self):
        """Verify _context.py allocates arrays of FB instances correctly."""
        from plx.simulate._context import SimulationContext

        pou = POU(
            name="Test",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(
                        name="timers",
                        data_type=ArrayTypeRef(
                            element_type=NamedTypeRef(name="TON"),
                            dimensions=[DimensionRange(lower=0, upper=2)],
                        ),
                    ),
                ],
            ),
        )
        ctx = SimulationContext(pou)
        state = ctx._state

        # Should be a list of 3 TON state dicts
        assert isinstance(state["timers"], list)
        assert len(state["timers"]) == 3
        for i in range(3):
            assert isinstance(state["timers"][i], dict)
            assert "IN" in state["timers"][i]
            assert "PT" in state["timers"][i]
            assert "Q" in state["timers"][i]

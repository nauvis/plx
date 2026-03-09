"""Tests for AST compiler — call resolution (sentinels, FB calls, builtins)."""

from conftest import compile_stmts, compile_expr

from plx.framework._compiler import CompileContext
from plx.framework._descriptors import Field, VarDirection
from plx.model.expressions import (
    BinaryExpr,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SystemFlag,
    SystemFlagExpr,
    VariableRef,
)
from plx.model.statements import (
    Assignment,
    FBInvocation,
    FunctionCallStatement,
    IfStatement,
)
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# Timer sentinels (delayed, sustained, pulse)
# ---------------------------------------------------------------------------

class TestDelayed:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = delayed(self.input, timedelta(seconds=5))", ctx)
        # Should have: FBInvocation (TON), Assignment
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "TON"
        assert "IN" in stmts[0].inputs
        assert "PT" in stmts[0].inputs
        # PT should be T#5s
        pt = stmts[0].inputs["PT"]
        assert isinstance(pt, LiteralExpr)
        assert pt.value == "T#5s"

        # Assignment uses .Q
        assert isinstance(stmts[1], Assignment)
        assert isinstance(stmts[1].value, MemberAccessExpr)
        assert stmts[1].value.member == "Q"

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.output = delayed(self.input, timedelta(seconds=5))", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="TON")
        assert var.name.startswith("_plx_ton_")

    def test_ms_duration(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = delayed(self.input, timedelta(milliseconds=500))", ctx)
        pt = stmts[0].inputs["PT"]
        assert pt.value == "T#500ms"

    def test_combined_duration(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = delayed(self.input, timedelta(seconds=1, milliseconds=500))", ctx)
        pt = stmts[0].inputs["PT"]
        assert pt.value == "T#1s500ms"

    def test_multiple_instances_unique_names(self):
        ctx = CompileContext()
        compile_stmts("""\
self.a = delayed(self.x, timedelta(seconds=1))
self.b = delayed(self.y, timedelta(seconds=2))
""", ctx)
        assert len(ctx.generated_static_vars) == 2
        names = [v.name for v in ctx.generated_static_vars]
        assert len(set(names)) == 2  # unique names


class TestSustained:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = sustained(self.input, timedelta(seconds=3))", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "TOF"


class TestPulse:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = pulse(self.input, timedelta(milliseconds=500))", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "TP"


class TestRetentive:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = retentive(self.input, timedelta(seconds=5))", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "RTO"
        assert "IN" in stmts[0].inputs
        assert "PT" in stmts[0].inputs
        pt = stmts[0].inputs["PT"]
        assert isinstance(pt, LiteralExpr)
        assert pt.value == "T#5s"
        # Assignment uses .Q
        assert isinstance(stmts[1], Assignment)
        assert isinstance(stmts[1].value, MemberAccessExpr)
        assert stmts[1].value.member == "Q"

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.output = retentive(self.input, timedelta(seconds=5))", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="RTO")
        assert var.name.startswith("_plx_rto_")

    def test_ms_duration(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = retentive(self.input, timedelta(milliseconds=750))", ctx)
        pt = stmts[0].inputs["PT"]
        assert pt.value == "T#750ms"

    def test_in_if_condition(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
if retentive(self.signal, timedelta(seconds=10)):
    self.done = True
""", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "RTO"
        assert isinstance(stmts[1], IfStatement)
        cond = stmts[1].if_branch.condition
        assert isinstance(cond, MemberAccessExpr)
        assert cond.member == "Q"


# ---------------------------------------------------------------------------
# Edge sentinels (rising, falling)
# ---------------------------------------------------------------------------

class TestRising:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = rising(self.input)", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "R_TRIG"
        assert "CLK" in stmts[0].inputs

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.output = rising(self.input)", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="R_TRIG")

    def test_in_if_condition(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
if rising(self.button):
    self.count += 1
""", ctx)
        # Should have: FBInvocation (R_TRIG), IfStatement
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], IfStatement)
        # Condition should be MemberAccessExpr(.Q)
        cond = stmts[1].if_branch.condition
        assert isinstance(cond, MemberAccessExpr)
        assert cond.member == "Q"


class TestFalling:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = falling(self.input)", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "F_TRIG"


# ---------------------------------------------------------------------------
# FB invocation (self.instance(...))
# ---------------------------------------------------------------------------

class TestFBInvocation:
    def test_as_statement(self):
        ctx = CompileContext(
            declared_vars={"timer": VarDirection.STATIC},
            static_var_types={"timer": NamedTypeRef(name="TON")},
        )
        stmts = compile_stmts("self.timer(IN=self.start, PT=self.preset)", ctx)
        assert len(stmts) == 1
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].instance_name == "timer"
        assert stmts[0].fb_type == "TON"
        assert "IN" in stmts[0].inputs
        assert "PT" in stmts[0].inputs

    def test_as_expression(self):
        ctx = CompileContext(
            declared_vars={"timer": VarDirection.STATIC},
            static_var_types={"timer": NamedTypeRef(name="TON")},
        )
        stmts = compile_stmts("self.output = self.timer(IN=self.start, PT=self.preset)", ctx)
        # FBInvocation + Assignment
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], Assignment)

    def test_member_access_after_invocation(self):
        """self.timer(IN=signal).Q pattern — the .Q is accessed separately."""
        ctx = CompileContext(
            declared_vars={"timer": VarDirection.STATIC},
            static_var_types={"timer": NamedTypeRef(name="TON")},
        )
        stmts = compile_stmts("self.output = self.timer.Q", ctx)
        assert len(stmts) == 1
        assert isinstance(stmts[0], Assignment)
        assert isinstance(stmts[0].value, MemberAccessExpr)


# ---------------------------------------------------------------------------
# Function call as statement
# ---------------------------------------------------------------------------

class TestFunctionCallStatement:
    def test_basic(self):
        stmts = compile_stmts("MyFunc(1, 2)")
        assert len(stmts) == 1
        assert isinstance(stmts[0], FunctionCallStatement)
        assert stmts[0].function_name == "MyFunc"
        assert len(stmts[0].args) == 2

    def test_builtin_mapped(self):
        stmts = compile_stmts("abs(self.x)")
        assert isinstance(stmts[0], FunctionCallStatement)
        assert stmts[0].function_name == "ABS"


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

class TestDurationParsing:
    def test_variable_duration(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = delayed(self.input, duration=self.preset)", ctx)
        pt = stmts[0].inputs["PT"]
        assert isinstance(pt, VariableRef)
        assert pt.name == "preset"

    def test_seconds_only(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = delayed(self.input, timedelta(seconds=10))", ctx)
        pt = stmts[0].inputs["PT"]
        assert pt.value == "T#10s"

    def test_ms_only(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = delayed(self.input, timedelta(milliseconds=250))", ctx)
        pt = stmts[0].inputs["PT"]
        assert pt.value == "T#250ms"


# ---------------------------------------------------------------------------
# Pending FB invocation flushing
# ---------------------------------------------------------------------------

class TestPendingFlush:
    def test_sentinel_in_if_condition(self):
        """Sentinel used in condition should flush before the if statement."""
        ctx = CompileContext()
        stmts = compile_stmts("""\
if delayed(self.sensor, timedelta(seconds=3)):
    self.output = True
""", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], IfStatement)

    def test_multiple_sentinels_in_expression(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
self.output = delayed(self.a, timedelta(seconds=1)) and delayed(self.b, timedelta(seconds=2))
""", ctx)
        # Two FBInvocations + one Assignment
        assert len(stmts) == 3
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], FBInvocation)
        assert isinstance(stmts[2], Assignment)


# ---------------------------------------------------------------------------
# Counter sentinels (count_up, count_down)
# ---------------------------------------------------------------------------

class TestCountUp:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_up(self.input, preset=10)", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "CTU"
        assert "CU" in stmts[0].inputs
        assert "PV" in stmts[0].inputs
        pv = stmts[0].inputs["PV"]
        assert isinstance(pv, LiteralExpr)
        assert pv.value == "10"

        assert isinstance(stmts[1], Assignment)
        assert isinstance(stmts[1].value, MemberAccessExpr)
        assert stmts[1].value.member == "Q"

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.output = count_up(self.input, preset=10)", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="CTU")
        assert var.name.startswith("_plx_ctu_")

    def test_with_reset(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_up(self.input, preset=10, reset=self.reset)", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert "RESET" in stmts[0].inputs
        reset = stmts[0].inputs["RESET"]
        assert isinstance(reset, VariableRef)
        assert reset.name == "reset"

    def test_preset_required(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="preset="):
            compile_stmts("self.output = count_up(self.input)", ctx)

    def test_variable_preset(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_up(self.input, preset=self.limit)", ctx)
        pv = stmts[0].inputs["PV"]
        assert isinstance(pv, VariableRef)
        assert pv.name == "limit"

    def test_multiple_instances_unique_names(self):
        ctx = CompileContext()
        compile_stmts("""\
self.a = count_up(self.x, preset=10)
self.b = count_up(self.y, preset=20)
""", ctx)
        assert len(ctx.generated_static_vars) == 2
        names = [v.name for v in ctx.generated_static_vars]
        assert len(set(names)) == 2

    def test_returns_q(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_up(self.input, preset=10)", ctx)
        assign = stmts[1]
        assert isinstance(assign, Assignment)
        assert isinstance(assign.value, MemberAccessExpr)
        assert assign.value.member == "Q"

    def test_in_if_condition(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
if count_up(self.sensor, preset=100):
    self.done = True
""", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], IfStatement)
        cond = stmts[1].if_branch.condition
        assert isinstance(cond, MemberAccessExpr)
        assert cond.member == "Q"

    def test_as_statement_error(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="must be used in an expression"):
            compile_stmts("count_up(self.input, preset=10)", ctx)


class TestCountDown:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_down(self.input, preset=50)", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "CTD"
        assert "CD" in stmts[0].inputs
        assert "PV" in stmts[0].inputs
        pv = stmts[0].inputs["PV"]
        assert isinstance(pv, LiteralExpr)
        assert pv.value == "50"

    def test_with_load(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_down(self.input, preset=50, load=self.reload)", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert "LOAD" in stmts[0].inputs
        load = stmts[0].inputs["LOAD"]
        assert isinstance(load, VariableRef)
        assert load.name == "reload"

    def test_preset_required(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="preset="):
            compile_stmts("self.output = count_down(self.input)", ctx)

    def test_returns_q(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = count_down(self.input, preset=50)", ctx)
        assign = stmts[1]
        assert isinstance(assign, Assignment)
        assert isinstance(assign.value, MemberAccessExpr)
        assert assign.value.member == "Q"


# ---------------------------------------------------------------------------
# CTUD sentinel (count_up_down)
# ---------------------------------------------------------------------------

class TestCountUpDown:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.full = count_up_down(self.part_in, self.part_out, preset=100)", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "CTUD"
        assert "CU" in stmts[0].inputs
        assert "CD" in stmts[0].inputs
        assert "PV" in stmts[0].inputs
        pv = stmts[0].inputs["PV"]
        assert isinstance(pv, LiteralExpr)
        assert pv.value == "100"

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.full = count_up_down(self.up, self.down, preset=10)", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="CTUD")
        assert var.name.startswith("_plx_ctud_")

    def test_with_reset(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.full = count_up_down(self.up, self.down, preset=10, reset=self.rst)", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert "RESET" in stmts[0].inputs
        reset = stmts[0].inputs["RESET"]
        assert isinstance(reset, VariableRef)
        assert reset.name == "rst"

    def test_with_load(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.full = count_up_down(self.up, self.down, preset=10, load=self.ld)", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert "LOAD" in stmts[0].inputs
        load = stmts[0].inputs["LOAD"]
        assert isinstance(load, VariableRef)
        assert load.name == "ld"

    def test_with_reset_and_load(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.full = count_up_down(self.up, self.down, preset=10, reset=self.rst, load=self.ld)", ctx)
        assert isinstance(stmts[0], FBInvocation)
        assert "RESET" in stmts[0].inputs
        assert "LOAD" in stmts[0].inputs

    def test_preset_required(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="preset="):
            compile_stmts("self.full = count_up_down(self.up, self.down)", ctx)

    def test_requires_two_signals(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="two arguments"):
            compile_stmts("self.full = count_up_down(self.up, preset=10)", ctx)

    def test_returns_qu(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.full = count_up_down(self.up, self.down, preset=10)", ctx)
        assign = stmts[1]
        assert isinstance(assign, Assignment)
        assert isinstance(assign.value, MemberAccessExpr)
        assert assign.value.member == "QU"

    def test_variable_preset(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.full = count_up_down(self.up, self.down, preset=self.limit)", ctx)
        pv = stmts[0].inputs["PV"]
        assert isinstance(pv, VariableRef)
        assert pv.name == "limit"

    def test_in_if_condition(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
if count_up_down(self.up, self.down, preset=50):
    self.full = True
""", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], IfStatement)
        cond = stmts[1].if_branch.condition
        assert isinstance(cond, MemberAccessExpr)
        assert cond.member == "QU"

    def test_named_instance(self):
        ctx = CompileContext()
        compile_stmts('self.full = count_up_down(self.up, self.down, preset=10, name="parts")', ctx)
        assert len(ctx.generated_static_vars) == 1
        assert ctx.generated_static_vars[0].name == "parts"


# ---------------------------------------------------------------------------
# System flag sentinels (first_scan)
# ---------------------------------------------------------------------------

class TestFirstScan:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
if first_scan():
    self.init = True
""", ctx)
        assert len(stmts) == 1
        assert isinstance(stmts[0], IfStatement)
        cond = stmts[0].if_branch.condition
        assert isinstance(cond, SystemFlagExpr)
        assert cond.flag == SystemFlag.FIRST_SCAN

    def test_no_static_vars_generated(self):
        ctx = CompileContext()
        compile_stmts("self.flag = first_scan()", ctx)
        assert len(ctx.generated_static_vars) == 0

    def test_no_pending_invocations(self):
        ctx = CompileContext()
        compile_stmts("self.flag = first_scan()", ctx)
        assert len(ctx.pending_fb_invocations) == 0

    def test_no_args_allowed(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="takes no arguments"):
            compile_stmts("self.flag = first_scan(self.x)", ctx)

    def test_in_assignment(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.flag = first_scan()", ctx)
        assert len(stmts) == 1
        assert isinstance(stmts[0], Assignment)
        assert isinstance(stmts[0].value, SystemFlagExpr)
        assert stmts[0].value.flag == SystemFlag.FIRST_SCAN

    def test_in_boolean_expression(self):
        ctx = CompileContext()
        ctx.declared_vars["enable"] = VarDirection.INPUT
        stmts = compile_stmts("""\
if first_scan() and self.enable:
    self.init = True
""", ctx)
        assert len(stmts) == 1
        cond = stmts[0].if_branch.condition
        assert isinstance(cond, BinaryExpr)
        assert isinstance(cond.left, SystemFlagExpr)
        assert isinstance(cond.right, VariableRef)


# ---------------------------------------------------------------------------
# Bistable sentinels (set_dominant, reset_dominant)
# ---------------------------------------------------------------------------

class TestSetDominant:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = set_dominant(self.set_sig, self.reset_sig)", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "SR"
        assert "SET1" in stmts[0].inputs
        assert "RESET" in stmts[0].inputs

        assert isinstance(stmts[1], Assignment)
        assert isinstance(stmts[1].value, MemberAccessExpr)
        assert stmts[1].value.member == "Q1"

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.output = set_dominant(self.s, self.r)", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="SR")
        assert var.name.startswith("_plx_sr_")

    def test_requires_two_args(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="two arguments"):
            compile_stmts("self.output = set_dominant(self.s)", ctx)


class TestResetDominant:
    def test_basic(self):
        ctx = CompileContext()
        stmts = compile_stmts("self.output = reset_dominant(self.set_sig, self.reset_sig)", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "RS"
        assert "SET" in stmts[0].inputs
        assert "RESET1" in stmts[0].inputs

        assert isinstance(stmts[1], Assignment)
        assert isinstance(stmts[1].value, MemberAccessExpr)
        assert stmts[1].value.member == "Q1"

    def test_generates_static_var(self):
        ctx = CompileContext()
        compile_stmts("self.output = reset_dominant(self.s, self.r)", ctx)
        assert len(ctx.generated_static_vars) == 1
        var = ctx.generated_static_vars[0]
        assert var.data_type == NamedTypeRef(name="RS")
        assert var.name.startswith("_plx_rs_")

    def test_in_if_condition(self):
        ctx = CompileContext()
        stmts = compile_stmts("""\
if reset_dominant(self.s, self.r):
    self.active = True
""", ctx)
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[1], IfStatement)
        cond = stmts[1].if_branch.condition
        assert isinstance(cond, MemberAccessExpr)
        assert cond.member == "Q1"


# ---------------------------------------------------------------------------
# Named sentinels (name= kwarg)
# ---------------------------------------------------------------------------

class TestNamedSentinels:
    def test_delayed_with_name(self):
        ctx = CompileContext()
        stmts = compile_stmts('self.output = delayed(self.input, timedelta(seconds=5), name="cure_timer")', ctx)
        assert stmts[0].instance_name == "cure_timer"
        assert ctx.generated_static_vars[0].name == "cure_timer"

    def test_rising_with_name(self):
        ctx = CompileContext()
        stmts = compile_stmts('self.output = rising(self.input, name="start_edge")', ctx)
        assert stmts[0].instance_name == "start_edge"
        assert ctx.generated_static_vars[0].name == "start_edge"

    def test_count_up_with_name(self):
        ctx = CompileContext()
        stmts = compile_stmts('self.output = count_up(self.input, preset=10, name="part_counter")', ctx)
        assert stmts[0].instance_name == "part_counter"
        assert ctx.generated_static_vars[0].name == "part_counter"

    def test_bistable_with_name(self):
        ctx = CompileContext()
        stmts = compile_stmts('self.output = set_dominant(self.s, self.r, name="latch")', ctx)
        assert stmts[0].instance_name == "latch"
        assert ctx.generated_static_vars[0].name == "latch"

    def test_without_name_uses_auto(self):
        ctx = CompileContext()
        compile_stmts("self.output = delayed(self.input, timedelta(seconds=5))", ctx)
        assert ctx.generated_static_vars[0].name.startswith("_plx_")

    def test_name_must_be_string_literal(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="name= must be a string literal"):
            compile_stmts("self.output = delayed(self.input, timedelta(seconds=5), name=my_var)", ctx)

    def test_name_must_be_valid_identifier(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="not a valid identifier"):
            compile_stmts('self.output = delayed(self.input, timedelta(seconds=5), name="123bad")', ctx)

    def test_name_conflict_with_declared_var(self):
        import pytest
        from plx.framework._descriptors import VarDirection
        ctx = CompileContext(declared_vars={"cure_timer": VarDirection.STATIC})
        with pytest.raises(Exception, match="conflicts with a declared variable"):
            compile_stmts('self.output = delayed(self.input, timedelta(seconds=5), name="cure_timer")', ctx)

    def test_name_conflict_with_generated_var(self):
        import pytest
        ctx = CompileContext()
        # First sentinel uses the name
        compile_stmts('self.a = delayed(self.x, timedelta(seconds=1), name="my_timer")', ctx)
        # Second sentinel tries the same name
        with pytest.raises(Exception, match="conflicts with an existing generated variable"):
            compile_stmts('self.b = delayed(self.y, timedelta(seconds=2), name="my_timer")', ctx)

    def test_first_scan_rejects_name(self):
        import pytest
        ctx = CompileContext()
        with pytest.raises(Exception, match="takes no arguments"):
            compile_stmts('self.flag = first_scan(name="init")', ctx)

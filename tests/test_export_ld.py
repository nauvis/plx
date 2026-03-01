"""Tests for the IR → Ladder Diagram transformer (plx.export.ld)."""

from plx.export.ld import (
    Box,
    Coil,
    CoilType,
    Contact,
    ContactType,
    LDNetwork,
    Parallel,
    Pin,
    Rung,
    STBox,
    Series,
    ir_to_ld,
)
from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.pou import (
    POU,
    Language,
    Network,
    POUInterface,
    POUType,
)
from plx.model.statements import (
    Assignment,
    CaseStatement,
    CaseBranch,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfStatement,
    IfBranch,
    RepeatStatement,
    ReturnStatement,
    WhileStatement,
    ContinueStatement,
)
from plx.model.types import PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref(name: str) -> VariableRef:
    return VariableRef(name=name)


def _lit(val: str) -> LiteralExpr:
    return LiteralExpr(value=val)


def _bool() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _int() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.INT)


def _net(*stmts) -> Network:
    return Network(statements=list(stmts))


# ---------------------------------------------------------------------------
# 1. Boolean assignments → contacts → coil
# ---------------------------------------------------------------------------

class TestBooleanAssignments:
    def test_simple_variable_assignment(self):
        """y := x  →  Contact(x, NO) → Coil(y)"""
        stmt = Assignment(target=_ref("y"), value=_ref("x"))
        ld = ir_to_ld([_net(stmt)])

        assert len(ld.rungs) == 1
        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="x", contact_type=ContactType.NO)
        assert rung.outputs == [Coil(variable="y")]

    def test_not_variable(self):
        """y := NOT x  →  Contact(x, NC) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(op=UnaryOp.NOT, operand=_ref("x")),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="x", contact_type=ContactType.NC)
        assert rung.outputs == [Coil(variable="y")]

    def test_and_two_variables(self):
        """y := a AND b  →  Series([Contact(a), Contact(b)]) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Series)
        assert len(rung.input_circuit.elements) == 2
        assert rung.input_circuit.elements[0] == Contact(variable="a", contact_type=ContactType.NO)
        assert rung.input_circuit.elements[1] == Contact(variable="b", contact_type=ContactType.NO)
        assert rung.outputs == [Coil(variable="y")]

    def test_or_two_variables(self):
        """y := a OR b  →  Parallel([Contact(a), Contact(b)]) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.OR, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Parallel)
        assert len(rung.input_circuit.branches) == 2
        assert rung.input_circuit.branches[0] == Contact(variable="a")
        assert rung.input_circuit.branches[1] == Contact(variable="b")

    def test_and_with_not(self):
        """y := a AND NOT b  →  Series([Contact(a, NO), Contact(b, NC)])"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(
                op=BinaryOp.AND,
                left=_ref("a"),
                right=UnaryExpr(op=UnaryOp.NOT, operand=_ref("b")),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Series)
        assert rung.input_circuit.elements[0] == Contact(variable="a", contact_type=ContactType.NO)
        assert rung.input_circuit.elements[1] == Contact(variable="b", contact_type=ContactType.NC)

    def test_or_with_not(self):
        """y := a OR NOT b  →  Parallel([Contact(a), Contact(b, NC)])"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(
                op=BinaryOp.OR,
                left=_ref("a"),
                right=UnaryExpr(op=UnaryOp.NOT, operand=_ref("b")),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Parallel)
        assert rung.input_circuit.branches[1] == Contact(variable="b", contact_type=ContactType.NC)

    def test_literal_true(self):
        """y := TRUE  →  unconditional SET coil (latch)"""
        stmt = Assignment(target=_ref("y"), value=_lit("TRUE"))
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit is None
        assert rung.outputs == [Coil(variable="y", coil_type=CoilType.SET)]

    def test_literal_false(self):
        """y := FALSE  →  unconditional RESET coil (unlatch)"""
        stmt = Assignment(target=_ref("y"), value=_lit("FALSE"))
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit is None
        assert rung.outputs == [Coil(variable="y", coil_type=CoilType.RESET)]

    def test_member_access(self):
        """y := fb.Q  →  Contact("fb.Q") → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=MemberAccessExpr(struct=_ref("fb"), member="Q"),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="fb.Q", contact_type=ContactType.NO)

    def test_system_flag_first_scan(self):
        """y := FirstScan  →  Contact("FirstScan") → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=SystemFlagExpr(flag=SystemFlag.FIRST_SCAN),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="FirstScan")


# ---------------------------------------------------------------------------
# 2. Flattening — chained AND/OR produce flat Series/Parallel
# ---------------------------------------------------------------------------

class TestFlattening:
    def test_chained_and(self):
        """a AND b AND c  →  Series([a, b, c])  (not nested)"""
        expr = BinaryExpr(
            op=BinaryOp.AND,
            left=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
            right=_ref("c"),
        )
        stmt = Assignment(target=_ref("y"), value=expr)
        ld = ir_to_ld([_net(stmt)])

        series = ld.rungs[0].input_circuit
        assert isinstance(series, Series)
        assert len(series.elements) == 3
        assert series.elements[0] == Contact(variable="a")
        assert series.elements[1] == Contact(variable="b")
        assert series.elements[2] == Contact(variable="c")

    def test_chained_or(self):
        """a OR b OR c  →  Parallel([a, b, c])  (not nested)"""
        expr = BinaryExpr(
            op=BinaryOp.OR,
            left=BinaryExpr(op=BinaryOp.OR, left=_ref("a"), right=_ref("b")),
            right=_ref("c"),
        )
        stmt = Assignment(target=_ref("y"), value=expr)
        ld = ir_to_ld([_net(stmt)])

        par = ld.rungs[0].input_circuit
        assert isinstance(par, Parallel)
        assert len(par.branches) == 3

    def test_deeply_nested_and(self):
        """(a AND b) AND (c AND d)  →  Series([a, b, c, d])"""
        expr = BinaryExpr(
            op=BinaryOp.AND,
            left=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
            right=BinaryExpr(op=BinaryOp.AND, left=_ref("c"), right=_ref("d")),
        )
        stmt = Assignment(target=_ref("y"), value=expr)
        ld = ir_to_ld([_net(stmt)])

        series = ld.rungs[0].input_circuit
        assert isinstance(series, Series)
        assert len(series.elements) == 4

    def test_and_containing_or(self):
        """a AND (b OR c)  →  Series([Contact(a), Parallel([Contact(b), Contact(c)])])"""
        expr = BinaryExpr(
            op=BinaryOp.AND,
            left=_ref("a"),
            right=BinaryExpr(op=BinaryOp.OR, left=_ref("b"), right=_ref("c")),
        )
        stmt = Assignment(target=_ref("y"), value=expr)
        ld = ir_to_ld([_net(stmt)])

        series = ld.rungs[0].input_circuit
        assert isinstance(series, Series)
        assert len(series.elements) == 2
        assert isinstance(series.elements[0], Contact)
        assert isinstance(series.elements[1], Parallel)
        assert len(series.elements[1].branches) == 2

    def test_or_containing_and(self):
        """(a AND b) OR c  →  Parallel([Series([a, b]), Contact(c)])"""
        expr = BinaryExpr(
            op=BinaryOp.OR,
            left=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
            right=_ref("c"),
        )
        stmt = Assignment(target=_ref("y"), value=expr)
        ld = ir_to_ld([_net(stmt)])

        par = ld.rungs[0].input_circuit
        assert isinstance(par, Parallel)
        assert len(par.branches) == 2
        assert isinstance(par.branches[0], Series)
        assert isinstance(par.branches[1], Contact)


# ---------------------------------------------------------------------------
# 3. FBInvocation → Box
# ---------------------------------------------------------------------------

class TestFBInvocation:
    def test_simple_fb_invocation(self):
        stmt = FBInvocation(
            instance_name="timer1",
            fb_type="TON",
            inputs={"IN": _ref("start"), "PT": _lit("T#5s")},
            outputs={"Q": _ref("done")},
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit is None
        assert len(rung.outputs) == 1
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.name == "timer1"
        assert box.type_name == "TON"
        assert len(box.input_pins) == 2
        assert box.input_pins[0] == Pin(name="IN", expression="start")
        assert box.input_pins[1] == Pin(name="PT", expression="T#5s")
        assert len(box.output_pins) == 1
        assert box.output_pins[0] == Pin(name="Q", expression="done")

    def test_fb_no_type(self):
        """When fb_type is None, use instance_name as type_name."""
        stmt = FBInvocation(instance_name="myFB", inputs={"x": _lit("1")})
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "myFB"


# ---------------------------------------------------------------------------
# 4. IfStatement → LD patterns
# ---------------------------------------------------------------------------

class TestIfStatement:
    def test_simple_if_bool_assign_true(self):
        """IF cond THEN y := TRUE  →  Contact(cond) → SET Coil(y)"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("cond"),
                body=[Assignment(target=_ref("y"), value=_lit("TRUE"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="cond")
        assert rung.outputs == [Coil(variable="y", coil_type=CoilType.SET)]

    def test_simple_if_bool_assign_false(self):
        """IF cond THEN y := FALSE  →  Contact(cond) → RESET Coil(y)"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("cond"),
                body=[Assignment(target=_ref("y"), value=_lit("FALSE"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="cond")
        assert rung.outputs == [Coil(variable="y", coil_type=CoilType.RESET)]

    def test_if_and_condition_assign_true(self):
        """IF a AND b THEN y := TRUE  →  Series → SET Coil"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
                body=[Assignment(target=_ref("y"), value=_lit("TRUE"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Series)
        assert rung.outputs == [Coil(variable="y", coil_type=CoilType.SET)]

    def test_if_fb_invocation(self):
        """IF cond THEN fb_call  →  Box with EN input"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("enable"),
                body=[FBInvocation(
                    instance_name="timer1",
                    fb_type="TON",
                    inputs={"IN": _ref("start")},
                )],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.name == "timer1"
        assert box.en_input == Contact(variable="enable")

    def test_if_with_elsif_falls_back(self):
        """IF with ELSIF → STBox fallback"""
        stmt = IfStatement(
            if_branch=IfBranch(condition=_ref("a"), body=[Assignment(target=_ref("y"), value=_lit("TRUE"))]),
            elsif_branches=[IfBranch(condition=_ref("b"), body=[Assignment(target=_ref("z"), value=_lit("TRUE"))])],
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert any(isinstance(o, STBox) for o in rung.outputs)

    def test_if_with_else_falls_back(self):
        """IF with ELSE → STBox fallback"""
        stmt = IfStatement(
            if_branch=IfBranch(condition=_ref("a"), body=[Assignment(target=_ref("y"), value=_lit("TRUE"))]),
            else_body=[Assignment(target=_ref("y"), value=_lit("FALSE"))],
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert any(isinstance(o, STBox) for o in rung.outputs)

    def test_if_multi_set_produces_multi_coil(self):
        """IF with multiple SET assignments → multi-coil rung"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("a"),
                body=[
                    Assignment(target=_ref("x"), value=_lit("TRUE")),
                    Assignment(target=_ref("y"), value=_lit("TRUE")),
                ],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="a")
        assert len(rung.outputs) == 2
        assert rung.outputs[0] == Coil(variable="x", coil_type=CoilType.SET)
        assert rung.outputs[1] == Coil(variable="y", coil_type=CoilType.SET)


# ---------------------------------------------------------------------------
# 5. Comparisons → Box elements
# ---------------------------------------------------------------------------

class TestComparisons:
    def test_eq_comparison(self):
        """y := (count = 10)  →  Box("EQ", [count, 10]) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.EQ, left=_ref("count"), right=_lit("10")),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Box)
        assert rung.input_circuit.name == "EQ"
        assert rung.input_circuit.input_pins[0] == Pin(name="IN1", expression="count")
        assert rung.input_circuit.input_pins[1] == Pin(name="IN2", expression="10")
        assert rung.outputs == [Coil(variable="y")]

    def test_gt_comparison(self):
        stmt = Assignment(
            target=_ref("alarm"),
            value=BinaryExpr(op=BinaryOp.GT, left=_ref("temp"), right=_lit("100")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].input_circuit
        assert isinstance(box, Box)
        assert box.name == "GT"

    def test_ne_comparison(self):
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.NE, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].input_circuit
        assert isinstance(box, Box)
        assert box.name == "NE"

    def test_le_comparison(self):
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.LE, left=_ref("x"), right=_lit("50")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].input_circuit
        assert isinstance(box, Box)
        assert box.name == "LE"

    def test_comparison_in_and_chain(self):
        """a AND (count > 5)  →  Series([Contact(a), Box(GT)])"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(
                op=BinaryOp.AND,
                left=_ref("a"),
                right=BinaryExpr(op=BinaryOp.GT, left=_ref("count"), right=_lit("5")),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        series = ld.rungs[0].input_circuit
        assert isinstance(series, Series)
        assert isinstance(series.elements[0], Contact)
        assert isinstance(series.elements[1], Box)
        assert series.elements[1].name == "GT"


# ---------------------------------------------------------------------------
# 6. ST fallback — non-LD constructs
# ---------------------------------------------------------------------------

class TestSTFallback:
    def test_for_statement(self):
        stmt = ForStatement(
            loop_var="i",
            from_expr=_lit("0"),
            to_expr=_lit("9"),
            body=[Assignment(target=_ref("x"), value=_ref("i"))],
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert len(rung.outputs) == 1
        st_box = rung.outputs[0]
        assert isinstance(st_box, STBox)
        assert "FOR" in st_box.st_text

    def test_while_statement(self):
        stmt = WhileStatement(
            condition=_ref("running"),
            body=[Assignment(target=_ref("x"), value=_lit("0"))],
        )
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "WHILE" in st_box.st_text

    def test_case_statement(self):
        stmt = CaseStatement(
            selector=_ref("state"),
            branches=[CaseBranch(values=[0], body=[Assignment(target=_ref("x"), value=_lit("1"))])],
        )
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "CASE" in st_box.st_text

    def test_repeat_statement(self):
        stmt = RepeatStatement(
            body=[Assignment(target=_ref("x"), value=_lit("0"))],
            until=_ref("done"),
        )
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "REPEAT" in st_box.st_text

    def test_return_statement(self):
        stmt = ReturnStatement()
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "RETURN" in st_box.st_text

    def test_exit_statement(self):
        stmt = ExitStatement()
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "EXIT" in st_box.st_text

    def test_continue_statement(self):
        stmt = ContinueStatement()
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "CONTINUE" in st_box.st_text

    def test_non_boolean_assignment(self):
        """x := 42  →  STBox (non-boolean RHS)"""
        stmt = Assignment(target=_ref("x"), value=_lit("42"))
        ld = ir_to_ld([_net(stmt)])

        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)
        assert "42" in st_box.st_text

    def test_xor_falls_back_to_st(self):
        """XOR is not AND/OR, so the expression becomes an STBox."""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.XOR, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        # XOR not in boolean heuristic → non-boolean assignment fallback
        st_box = ld.rungs[0].outputs[0]
        assert isinstance(st_box, STBox)


# ---------------------------------------------------------------------------
# 7. Function call statement → Box
# ---------------------------------------------------------------------------

class TestFunctionCallStatement:
    def test_function_call(self):
        stmt = FunctionCallStatement(
            function_name="RESET",
            args=[CallArg(value=_ref("counter"))],
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.name == "RESET"
        assert box.type_name == "RESET"
        assert len(box.input_pins) == 1
        assert box.input_pins[0].name == "IN1"

    def test_function_call_with_named_args(self):
        stmt = FunctionCallStatement(
            function_name="MoveAbs",
            args=[
                CallArg(name="Axis", value=_ref("ax1")),
                CallArg(name="Position", value=_lit("100.0")),
            ],
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.input_pins[0] == Pin(name="Axis", expression="ax1")
        assert box.input_pins[1] == Pin(name="Position", expression="100.0")


# ---------------------------------------------------------------------------
# 8. Integration — full POU
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_pou_with_multiple_networks(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            language=Language.LD,
            interface=POUInterface(
                input_vars=[
                    Variable(name="a", data_type=_bool()),
                    Variable(name="b", data_type=_bool()),
                ],
                output_vars=[Variable(name="y", data_type=_bool())],
            ),
            networks=[
                Network(
                    comment="Rung 1",
                    statements=[Assignment(target=_ref("y"), value=_ref("a"))],
                ),
                Network(
                    comment="Rung 2",
                    statements=[Assignment(
                        target=_ref("y"),
                        value=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
                    )],
                ),
            ],
        )
        ld = ir_to_ld(pou)

        assert len(ld.rungs) == 2
        # Rung 1: simple contact → coil
        assert isinstance(ld.rungs[0].input_circuit, Contact)
        assert ld.rungs[0].outputs == [Coil(variable="y")]
        # Rung 2: series → coil
        assert isinstance(ld.rungs[1].input_circuit, Series)

    def test_mixed_ld_and_st_rungs(self):
        """POU with both LD-native and ST-fallback rungs."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MixedFB",
            networks=[
                Network(statements=[
                    Assignment(target=_ref("y"), value=_ref("a")),  # LD
                    ForStatement(  # ST fallback
                        loop_var="i",
                        from_expr=_lit("0"),
                        to_expr=_lit("9"),
                        body=[Assignment(target=_ref("x"), value=_ref("i"))],
                    ),
                ]),
            ],
        )
        ld = ir_to_ld(pou)

        assert len(ld.rungs) == 2
        assert isinstance(ld.rungs[0].input_circuit, Contact)
        assert isinstance(ld.rungs[1].outputs[0], STBox)

    def test_accepts_network_list(self):
        """ir_to_ld accepts list[Network] directly."""
        networks = [
            Network(statements=[Assignment(target=_ref("y"), value=_ref("x"))]),
        ]
        ld = ir_to_ld(networks)

        assert len(ld.rungs) == 1

    def test_type_error_for_invalid_input(self):
        import pytest
        with pytest.raises(TypeError, match="expects POU or list"):
            ir_to_ld("not a POU")  # type: ignore


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_network(self):
        ld = ir_to_ld([Network(statements=[])])
        assert len(ld.rungs) == 0

    def test_empty_network_list(self):
        ld = ir_to_ld([])
        assert len(ld.rungs) == 0
        assert ld == LDNetwork(rungs=[])

    def test_deeply_nested_booleans(self):
        """((a AND b) OR c) AND d  →  properly structured"""
        inner_and = BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b"))
        inner_or = BinaryExpr(op=BinaryOp.OR, left=inner_and, right=_ref("c"))
        outer = BinaryExpr(op=BinaryOp.AND, left=inner_or, right=_ref("d"))

        stmt = Assignment(target=_ref("y"), value=outer)
        ld = ir_to_ld([_net(stmt)])

        # Should be Series([Parallel([Series([a,b]), c]), d])
        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Series)
        series = rung.input_circuit
        assert len(series.elements) == 2
        assert isinstance(series.elements[0], Parallel)
        assert isinstance(series.elements[1], Contact)

    def test_function_call_expr_assignment(self):
        """y := FUNC(x)  →  Box(FUNC) with output pin assigned to y"""
        stmt = Assignment(
            target=_ref("y"),
            value=FunctionCallExpr(
                function_name="IsValid",
                args=[CallArg(value=_ref("data"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.name == "IsValid"
        assert box.output_pins[0] == Pin(name="OUT", expression="y")

    def test_not_complex_expression(self):
        """NOT (a AND b) → STBox fallback for NOT of complex expr"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        # NOT of complex expression becomes STBox in contact position
        assert isinstance(rung.input_circuit, STBox)


# ---------------------------------------------------------------------------
# 10. JSON serialization roundtrip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_model_dump_roundtrip(self):
        """LDNetwork.model_dump() → LDNetwork.model_validate() roundtrips."""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(
                op=BinaryOp.AND,
                left=_ref("a"),
                right=BinaryExpr(op=BinaryOp.OR, left=_ref("b"), right=_ref("c")),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        data = ld.model_dump()
        restored = LDNetwork.model_validate(data)
        assert restored == ld

    def test_model_dump_json(self):
        """model_dump_json produces valid JSON that can be parsed back."""
        stmt = Assignment(target=_ref("y"), value=_ref("x"))
        ld = ir_to_ld([_net(stmt)])

        json_str = ld.model_dump_json()
        assert '"kind":"contact"' in json_str
        assert '"kind":"coil"' in json_str

        restored = LDNetwork.model_validate_json(json_str)
        assert restored == ld

    def test_box_with_en_serializes(self):
        """Box with en_input serializes and deserializes correctly."""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("enable"),
                body=[FBInvocation(
                    instance_name="timer1",
                    fb_type="TON",
                    inputs={"IN": _ref("start")},
                )],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        data = ld.model_dump()
        restored = LDNetwork.model_validate(data)
        assert restored == ld

        box = restored.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert isinstance(box.en_input, Contact)


# ---------------------------------------------------------------------------
# 11. NOT of non-VariableRef operands
# ---------------------------------------------------------------------------

class TestNOTExpressions:
    """NOT should produce NC contacts for member access, bit access, etc.,
    not just for bare VariableRef."""

    def test_not_member_access(self):
        """y := NOT fb.Q  →  Contact("fb.Q", NC) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=MemberAccessExpr(struct=_ref("fb"), member="Q"),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="fb.Q", contact_type=ContactType.NC)
        assert rung.outputs == [Coil(variable="y")]

    def test_not_member_access_in_and(self):
        """y := a AND NOT fb.done  →  Series([Contact(a), Contact(fb.done, NC)])"""
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(
                op=BinaryOp.AND,
                left=_ref("a"),
                right=UnaryExpr(
                    op=UnaryOp.NOT,
                    operand=MemberAccessExpr(struct=_ref("fb"), member="done"),
                ),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        series = ld.rungs[0].input_circuit
        assert isinstance(series, Series)
        assert series.elements[1] == Contact(variable="fb.done", contact_type=ContactType.NC)

    def test_not_literal_true(self):
        """y := NOT TRUE  →  Contact("TRUE", NC) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(op=UnaryOp.NOT, operand=_lit("TRUE")),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="TRUE", contact_type=ContactType.NC)

    def test_not_function_call(self):
        """y := NOT IsValid(x)  →  Box negation, not STBox fallback"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=FunctionCallExpr(
                    function_name="IsValid",
                    args=[CallArg(value=_ref("x"))],
                ),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        # Should at minimum not be an STBox — function call box with
        # a negated coil output is acceptable
        rung = ld.rungs[0]
        assert rung.input_circuit is not None
        assert not isinstance(rung.input_circuit, STBox)


# ---------------------------------------------------------------------------
# 12. IF with boolean variable assignment (not literal TRUE/FALSE)
# ---------------------------------------------------------------------------

class TestIfBooleanAssignment:
    """IF cond THEN y := x  should produce contact network → coil,
    not fall back to ST."""

    def test_if_then_bool_var_assign(self):
        """IF enable THEN output := sensor  →  Series → Coil

        In LD, this is: Contact(enable) in series with Contact(sensor) → Coil(output).
        The condition and the value are ANDed in the contact network.
        """
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("enable"),
                body=[Assignment(target=_ref("output"), value=_ref("sensor"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        # Should NOT be an STBox fallback
        assert rung.input_circuit is not None
        assert not isinstance(rung.input_circuit, STBox)
        assert len(rung.outputs) == 1
        assert isinstance(rung.outputs[0], Coil)
        assert rung.outputs[0].variable == "output"

    def test_if_then_not_var_assign(self):
        """IF enable THEN output := NOT sensor  →  Series([enable, NC(sensor)]) → Coil"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("enable"),
                body=[Assignment(
                    target=_ref("output"),
                    value=UnaryExpr(op=UnaryOp.NOT, operand=_ref("sensor")),
                )],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit is not None
        assert not isinstance(rung.input_circuit, STBox)
        assert rung.outputs[0].variable == "output"

    def test_if_then_and_expr_assign(self):
        """IF enable THEN y := a AND b  →  Series([enable, a, b]) → Coil"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("enable"),
                body=[Assignment(
                    target=_ref("y"),
                    value=BinaryExpr(op=BinaryOp.AND, left=_ref("a"), right=_ref("b")),
                )],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit is not None
        assert not isinstance(rung.input_circuit, STBox)
        assert rung.outputs[0].variable == "y"

    def test_if_comparison_then_set(self):
        """IF temp > 100 THEN alarm := TRUE  →  Box(GT) → SET Coil"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=BinaryExpr(
                    op=BinaryOp.GT, left=_ref("temp"), right=_lit("100"),
                ),
                body=[Assignment(target=_ref("alarm"), value=_lit("TRUE"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Box)
        assert rung.input_circuit.name == "GT"
        assert rung.outputs == [Coil(variable="alarm", coil_type=CoilType.SET)]


# ---------------------------------------------------------------------------
# 13. IF with multiple body statements → multiple coils
# ---------------------------------------------------------------------------

class TestIfMultipleOutputs:
    """IF cond THEN x := TRUE; y := TRUE  should produce a single rung
    with the condition as input and multiple SET coils as outputs."""

    def test_if_then_two_set_coils(self):
        """IF cond THEN x := TRUE; y := TRUE  →  Contact(cond) → [Coil(x,S), Coil(y,S)]"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("cond"),
                body=[
                    Assignment(target=_ref("x"), value=_lit("TRUE")),
                    Assignment(target=_ref("y"), value=_lit("TRUE")),
                ],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="cond")
        assert len(rung.outputs) == 2
        assert rung.outputs[0] == Coil(variable="x", coil_type=CoilType.SET)
        assert rung.outputs[1] == Coil(variable="y", coil_type=CoilType.SET)

    def test_if_then_set_and_reset(self):
        """IF cond THEN motor := TRUE; brake := FALSE  →  [SET(motor), RESET(brake)]"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("cond"),
                body=[
                    Assignment(target=_ref("motor"), value=_lit("TRUE")),
                    Assignment(target=_ref("brake"), value=_lit("FALSE")),
                ],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert rung.input_circuit == Contact(variable="cond")
        assert len(rung.outputs) == 2
        assert rung.outputs[0] == Coil(variable="motor", coil_type=CoilType.SET)
        assert rung.outputs[1] == Coil(variable="brake", coil_type=CoilType.RESET)

    def test_if_then_mixed_falls_back(self):
        """IF cond THEN x := TRUE; fb_call  → fallback (mixed types)"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("cond"),
                body=[
                    Assignment(target=_ref("x"), value=_lit("TRUE")),
                    FBInvocation(instance_name="timer1", fb_type="TON", inputs={"IN": _ref("start")}),
                ],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        # Should still produce something (not crash), STBox fallback is fine
        assert len(ld.rungs) == 1


# ---------------------------------------------------------------------------
# 14. IF with FunctionCallStatement (not FBInvocation)
# ---------------------------------------------------------------------------

class TestIfFunctionCall:
    """IF cond THEN RESET(counter) should produce a Box with EN,
    not fall back to ST."""

    def test_if_then_function_call(self):
        """IF cond THEN RESET(counter)  →  Box(RESET, EN=cond)"""
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("cond"),
                body=[FunctionCallStatement(
                    function_name="RESET",
                    args=[CallArg(value=_ref("counter"))],
                )],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert len(rung.outputs) == 1
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "RESET"
        assert box.en_input == Contact(variable="cond")


# ---------------------------------------------------------------------------
# 15. Arithmetic assignments → boxes (ADD, SUB, MUL, DIV, MOD)
# ---------------------------------------------------------------------------

class TestArithmeticBoxes:
    """Arithmetic assignments like x := a + b should produce
    Box(ADD, IN1=a, IN2=b) → target, not ST fallback."""

    def test_add(self):
        """x := a + b  →  Box(ADD, [a, b]) assigned to x"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(op=BinaryOp.ADD, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert len(rung.outputs) >= 1
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "ADD"
        assert box.input_pins[0] == Pin(name="IN1", expression="a")
        assert box.input_pins[1] == Pin(name="IN2", expression="b")
        assert box.output_pins[0] == Pin(name="OUT", expression="x")

    def test_sub(self):
        """x := a - b  →  Box(SUB)"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(op=BinaryOp.SUB, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "SUB"

    def test_mul(self):
        """x := a * b  →  Box(MUL)"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(op=BinaryOp.MUL, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "MUL"

    def test_div(self):
        """x := a / b  →  Box(DIV)"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(op=BinaryOp.DIV, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "DIV"

    def test_mod(self):
        """x := a MOD b  →  Box(MOD)"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(op=BinaryOp.MOD, left=_ref("a"), right=_ref("b")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "MOD"

    def test_nested_arithmetic(self):
        """x := (a + b) * c  →  Box(MUL, [Box(ADD, [a,b]).OUT, c]) or equivalent"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(
                op=BinaryOp.MUL,
                left=BinaryExpr(op=BinaryOp.ADD, left=_ref("a"), right=_ref("b")),
                right=_ref("c"),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        # Should produce *something* — at least not crash.
        # Outer box is MUL, inner expression for IN1 can be ST text.
        assert len(rung.outputs) >= 1
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "MUL"

    def test_augmented_add(self):
        """x := x + 1  →  Box(ADD, [x, 1]) → x"""
        stmt = Assignment(
            target=_ref("x"),
            value=BinaryExpr(op=BinaryOp.ADD, left=_ref("x"), right=_lit("1")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "ADD"
        assert box.output_pins[0] == Pin(name="OUT", expression="x")


# ---------------------------------------------------------------------------
# 16. Function call as expression assigned to variable → Box
# ---------------------------------------------------------------------------

class TestFunctionCallAssignment:
    """y := ABS(x) should produce Box(ABS) with output pin, not ST."""

    def test_function_result_assignment(self):
        """y := ABS(x)  →  Box(ABS, IN1=x, OUT=y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=FunctionCallExpr(
                function_name="ABS",
                args=[CallArg(value=_ref("x"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "ABS"
        assert box.output_pins[0] == Pin(name="OUT", expression="y")

    def test_function_with_named_args_assignment(self):
        """result := LIMIT(MN:=0, IN:=x, MX:=100)  →  Box with named pins"""
        stmt = Assignment(
            target=_ref("result"),
            value=FunctionCallExpr(
                function_name="LIMIT",
                args=[
                    CallArg(name="MN", value=_lit("0")),
                    CallArg(name="IN", value=_ref("x")),
                    CallArg(name="MX", value=_lit("100")),
                ],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "LIMIT"
        assert box.input_pins[0] == Pin(name="MN", expression="0")
        assert box.output_pins[0] == Pin(name="OUT", expression="result")


# ---------------------------------------------------------------------------
# 17. Bit access and array access in contact position
# ---------------------------------------------------------------------------

class TestAccessExpressions:
    """BitAccessExpr and ArrayAccessExpr should produce contacts, not STBox."""

    def test_bit_access_contact(self):
        """y := status.5  →  Contact("status.5") → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=BitAccessExpr(target=_ref("status"), bit_index=5),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Contact)
        assert rung.input_circuit.variable == "status.5"
        assert rung.outputs == [Coil(variable="y")]

    def test_not_bit_access(self):
        """y := NOT status.5  →  Contact("status.5", NC) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=BitAccessExpr(target=_ref("status"), bit_index=5),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Contact)
        assert rung.input_circuit.contact_type == ContactType.NC

    def test_array_access_in_boolean_context(self):
        """y := flags[3]  →  Contact("flags[3]") → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=ArrayAccessExpr(
                array=_ref("flags"),
                indices=[_lit("3")],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Contact)
        assert "flags" in rung.input_circuit.variable
        assert rung.outputs == [Coil(variable="y")]


# ---------------------------------------------------------------------------
# 18. Type conversion → Box
# ---------------------------------------------------------------------------

class TestTypeConversion:
    """Type conversions should map to boxes."""

    def test_type_conversion_assignment(self):
        """y := INT_TO_REAL(x)  →  Box(INT_TO_REAL) with output"""
        stmt = Assignment(
            target=_ref("y"),
            value=TypeConversionExpr(
                target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                source=_ref("x"),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        box = rung.outputs[0]
        assert isinstance(box, Box)
        assert "REAL" in box.type_name  # e.g., "TO_REAL" or "INT_TO_REAL"
        assert box.output_pins[0] == Pin(name="OUT", expression="y")


# ---------------------------------------------------------------------------
# 19. Negated coil from NOT expression
# ---------------------------------------------------------------------------

class TestNegatedCoil:
    """y := NOT x  already works (NC contact → normal coil).
    But NOT of member access should also work, not fall to ST."""

    def test_not_member_gives_nc_coil(self):
        """y := NOT timer.Q  →  Contact(timer.Q, NC) → Coil(y)"""
        stmt = Assignment(
            target=_ref("y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=MemberAccessExpr(struct=_ref("timer"), member="Q"),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Contact)
        assert rung.input_circuit.contact_type == ContactType.NC
        assert rung.input_circuit.variable == "timer.Q"


# ---------------------------------------------------------------------------
# 20. Realistic composite patterns (framework-emitted IR)
# ---------------------------------------------------------------------------

class TestRealisticPatterns:
    """Patterns commonly emitted by the plx framework compiler."""

    def test_timer_pattern(self):
        """Timer FB invocation followed by output read:
           timer1(IN := start, PT := T#5s)
           done := timer1.Q
        Should produce two rungs: Box(TON) then Contact(timer1.Q) → Coil(done).
        """
        stmts = [
            FBInvocation(
                instance_name="timer1", fb_type="TON",
                inputs={"IN": _ref("start"), "PT": _lit("T#5s")},
            ),
            Assignment(
                target=_ref("done"),
                value=MemberAccessExpr(struct=_ref("timer1"), member="Q"),
            ),
        ]
        ld = ir_to_ld([_net(*stmts)])

        assert len(ld.rungs) == 2
        # Rung 1: TON box
        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "TON"
        # Rung 2: Contact → Coil
        assert ld.rungs[1].input_circuit == Contact(variable="timer1.Q")
        assert ld.rungs[1].outputs == [Coil(variable="done")]

    def test_conditional_latch_pattern(self):
        """Common pattern: IF overflow THEN alarm := TRUE
        Then later: IF reset THEN alarm := FALSE
        """
        stmts = [
            IfStatement(
                if_branch=IfBranch(
                    condition=_ref("overflow"),
                    body=[Assignment(target=_ref("alarm"), value=_lit("TRUE"))],
                ),
            ),
            IfStatement(
                if_branch=IfBranch(
                    condition=_ref("reset_btn"),
                    body=[Assignment(target=_ref("alarm"), value=_lit("FALSE"))],
                ),
            ),
        ]
        ld = ir_to_ld([_net(*stmts)])

        assert len(ld.rungs) == 2
        # Rung 1: overflow → SET alarm
        assert ld.rungs[0].input_circuit == Contact(variable="overflow")
        assert ld.rungs[0].outputs == [Coil(variable="alarm", coil_type=CoilType.SET)]
        # Rung 2: reset_btn → RESET alarm
        assert ld.rungs[1].input_circuit == Contact(variable="reset_btn")
        assert ld.rungs[1].outputs == [Coil(variable="alarm", coil_type=CoilType.RESET)]

    def test_seal_in_circuit(self):
        """Classic seal-in: output := (start OR output) AND NOT stop
        →  Parallel([start, output]) in Series with Contact(stop, NC) → Coil(output)
        """
        stmt = Assignment(
            target=_ref("output"),
            value=BinaryExpr(
                op=BinaryOp.AND,
                left=BinaryExpr(
                    op=BinaryOp.OR,
                    left=_ref("start"),
                    right=_ref("output"),
                ),
                right=UnaryExpr(op=UnaryOp.NOT, operand=_ref("stop")),
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        series = rung.input_circuit
        assert isinstance(series, Series)
        assert len(series.elements) == 2
        assert isinstance(series.elements[0], Parallel)
        assert series.elements[1] == Contact(variable="stop", contact_type=ContactType.NC)
        assert rung.outputs == [Coil(variable="output")]

    def test_comparison_and_latch(self):
        """IF temp > 100 AND pressure > 50 THEN emergency := TRUE
        →  Series([Box(GT,temp,100), Box(GT,pressure,50)]) → SET(emergency)
        """
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=BinaryExpr(
                    op=BinaryOp.AND,
                    left=BinaryExpr(op=BinaryOp.GT, left=_ref("temp"), right=_lit("100")),
                    right=BinaryExpr(op=BinaryOp.GT, left=_ref("pressure"), right=_lit("50")),
                ),
                body=[Assignment(target=_ref("emergency"), value=_lit("TRUE"))],
            ),
        )
        ld = ir_to_ld([_net(stmt)])

        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Series)
        assert all(isinstance(e, Box) for e in rung.input_circuit.elements)
        assert rung.outputs == [Coil(variable="emergency", coil_type=CoilType.SET)]

    def test_counter_increment(self):
        """count := count + 1  →  Box(ADD, [count, 1], OUT=count)"""
        stmt = Assignment(
            target=_ref("count"),
            value=BinaryExpr(op=BinaryOp.ADD, left=_ref("count"), right=_lit("1")),
        )
        ld = ir_to_ld([_net(stmt)])

        box = ld.rungs[0].outputs[0]
        assert isinstance(box, Box)
        assert box.type_name == "ADD"
        assert box.input_pins[0] == Pin(name="IN1", expression="count")
        assert box.input_pins[1] == Pin(name="IN2", expression="1")
        assert box.output_pins[0] == Pin(name="OUT", expression="count")

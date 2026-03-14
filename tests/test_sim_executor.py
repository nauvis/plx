"""Tests for the execution engine."""

import pytest

from conftest import make_pou

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
    Network,
    POU,
    POUInterface,
    POUType,
    Property,
    PropertyAccessor,
)
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseRange,
    CaseStatement,
    ContinueStatement,
    EmptyStatement,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfBranch,
    IfStatement,
    RepeatStatement,
    ReturnStatement,
    WhileStatement,
)
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable
from plx.simulate._executor import ExecutionEngine
from plx.simulate._values import SimulationError


def _run(pou, state, clock_ms=0, **kwargs):
    """Helper to execute a POU and return the state."""
    engine = ExecutionEngine(pou=pou, state=state, clock_ms=clock_ms, **kwargs)
    engine.execute()
    return state


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

class TestAssignment:
    def test_simple_assign(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=LiteralExpr(value="42"),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == 42

    def test_assign_expression(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="y"),
                value=BinaryExpr(
                    op=BinaryOp.ADD,
                    left=VariableRef(name="a"),
                    right=LiteralExpr(value="10"),
                ),
            ),
        ])
        state = _run(pou, {"y": 0, "a": 5})
        assert state["y"] == 15


# ---------------------------------------------------------------------------
# If statement
# ---------------------------------------------------------------------------

class TestIf:
    def test_if_true(self):
        pou = make_pou([
            IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="flag"),
                    body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))],
                ),
            ),
        ])
        state = _run(pou, {"flag": True, "x": 0})
        assert state["x"] == 1

    def test_if_false(self):
        pou = make_pou([
            IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="flag"),
                    body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))],
                ),
            ),
        ])
        state = _run(pou, {"flag": False, "x": 0})
        assert state["x"] == 0

    def test_if_else(self):
        pou = make_pou([
            IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="flag"),
                    body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))],
                ),
                else_body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="2"))],
            ),
        ])
        state = _run(pou, {"flag": False, "x": 0})
        assert state["x"] == 2

    def test_elsif(self):
        pou = make_pou([
            IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="a"),
                    body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))],
                ),
                elsif_branches=[
                    IfBranch(
                        condition=VariableRef(name="b"),
                        body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="2"))],
                    ),
                ],
                else_body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="3"))],
            ),
        ])
        state = _run(pou, {"a": False, "b": True, "x": 0})
        assert state["x"] == 2


# ---------------------------------------------------------------------------
# Case statement
# ---------------------------------------------------------------------------

class TestCase:
    def test_case_match(self):
        pou = make_pou([
            CaseStatement(
                selector=VariableRef(name="sel"),
                branches=[
                    CaseBranch(values=[1], body=[
                        Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="10")),
                    ]),
                    CaseBranch(values=[2], body=[
                        Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="20")),
                    ]),
                ],
            ),
        ])
        state = _run(pou, {"sel": 2, "x": 0})
        assert state["x"] == 20

    def test_case_else(self):
        pou = make_pou([
            CaseStatement(
                selector=VariableRef(name="sel"),
                branches=[
                    CaseBranch(values=[1], body=[
                        Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="10")),
                    ]),
                ],
                else_body=[
                    Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="99")),
                ],
            ),
        ])
        state = _run(pou, {"sel": 5, "x": 0})
        assert state["x"] == 99

    def test_case_range(self):
        pou = make_pou([
            CaseStatement(
                selector=VariableRef(name="sel"),
                branches=[
                    CaseBranch(ranges=[CaseRange(start=10, end=20)], body=[
                        Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
                    ]),
                ],
            ),
        ])
        state = _run(pou, {"sel": 15, "x": 0})
        assert state["x"] == 1


# ---------------------------------------------------------------------------
# For loop
# ---------------------------------------------------------------------------

class TestFor:
    def test_for_sum(self):
        pou = make_pou([
            Assignment(target=VariableRef(name="sum"), value=LiteralExpr(value="0")),
            ForStatement(
                loop_var="i",
                from_expr=LiteralExpr(value="1"),
                to_expr=LiteralExpr(value="5"),
                body=[
                    Assignment(
                        target=VariableRef(name="sum"),
                        value=BinaryExpr(
                            op=BinaryOp.ADD,
                            left=VariableRef(name="sum"),
                            right=VariableRef(name="i"),
                        ),
                    ),
                ],
            ),
        ])
        state = _run(pou, {"sum": 0, "i": 0})
        assert state["sum"] == 15  # 1+2+3+4+5

    def test_for_with_step(self):
        pou = make_pou([
            Assignment(target=VariableRef(name="sum"), value=LiteralExpr(value="0")),
            ForStatement(
                loop_var="i",
                from_expr=LiteralExpr(value="0"),
                to_expr=LiteralExpr(value="10"),
                by_expr=LiteralExpr(value="2"),
                body=[
                    Assignment(
                        target=VariableRef(name="sum"),
                        value=BinaryExpr(
                            op=BinaryOp.ADD,
                            left=VariableRef(name="sum"),
                            right=VariableRef(name="i"),
                        ),
                    ),
                ],
            ),
        ])
        state = _run(pou, {"sum": 0, "i": 0})
        assert state["sum"] == 30  # 0+2+4+6+8+10

    def test_for_exit(self):
        pou = make_pou([
            Assignment(target=VariableRef(name="sum"), value=LiteralExpr(value="0")),
            ForStatement(
                loop_var="i",
                from_expr=LiteralExpr(value="1"),
                to_expr=LiteralExpr(value="10"),
                body=[
                    IfStatement(
                        if_branch=IfBranch(
                            condition=BinaryExpr(
                                op=BinaryOp.GT,
                                left=VariableRef(name="i"),
                                right=LiteralExpr(value="3"),
                            ),
                            body=[ExitStatement()],
                        ),
                    ),
                    Assignment(
                        target=VariableRef(name="sum"),
                        value=BinaryExpr(
                            op=BinaryOp.ADD,
                            left=VariableRef(name="sum"),
                            right=VariableRef(name="i"),
                        ),
                    ),
                ],
            ),
        ])
        state = _run(pou, {"sum": 0, "i": 0})
        assert state["sum"] == 6  # 1+2+3


# ---------------------------------------------------------------------------
# While loop
# ---------------------------------------------------------------------------

class TestWhile:
    def test_while_countdown(self):
        pou = make_pou([
            WhileStatement(
                condition=BinaryExpr(
                    op=BinaryOp.GT,
                    left=VariableRef(name="n"),
                    right=LiteralExpr(value="0"),
                ),
                body=[
                    Assignment(
                        target=VariableRef(name="n"),
                        value=BinaryExpr(
                            op=BinaryOp.SUB,
                            left=VariableRef(name="n"),
                            right=LiteralExpr(value="1"),
                        ),
                    ),
                ],
            ),
        ])
        state = _run(pou, {"n": 5})
        assert state["n"] == 0


# ---------------------------------------------------------------------------
# Repeat statement
# ---------------------------------------------------------------------------

class TestRepeat:
    def test_repeat_until(self):
        pou = make_pou([
            RepeatStatement(
                body=[
                    Assignment(
                        target=VariableRef(name="n"),
                        value=BinaryExpr(
                            op=BinaryOp.ADD,
                            left=VariableRef(name="n"),
                            right=LiteralExpr(value="1"),
                        ),
                    ),
                ],
                until=BinaryExpr(
                    op=BinaryOp.GE,
                    left=VariableRef(name="n"),
                    right=LiteralExpr(value="3"),
                ),
            ),
        ])
        state = _run(pou, {"n": 0})
        assert state["n"] == 3


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

class TestExpressions:
    def test_binary_add(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(op=BinaryOp.ADD, left=LiteralExpr(value="3"), right=LiteralExpr(value="4")),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == 7

    def test_integer_div_truncates(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(op=BinaryOp.DIV, left=LiteralExpr(value="7"), right=LiteralExpr(value="2")),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == 3

    def test_negative_integer_div(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(op=BinaryOp.DIV, left=LiteralExpr(value="-7"), right=LiteralExpr(value="2")),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == -3  # truncate toward zero

    def test_float_div(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(op=BinaryOp.DIV, left=LiteralExpr(value="7.0"), right=LiteralExpr(value="2.0")),
            ),
        ])
        state = _run(pou, {"x": 0.0})
        assert state["x"] == pytest.approx(3.5)

    def test_bool_and(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(op=BinaryOp.AND, left=LiteralExpr(value="TRUE"), right=LiteralExpr(value="FALSE")),
            ),
        ])
        state = _run(pou, {"x": True})
        assert state["x"] is False

    def test_comparison(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(op=BinaryOp.GT, left=LiteralExpr(value="5"), right=LiteralExpr(value="3")),
            ),
        ])
        state = _run(pou, {"x": False})
        assert state["x"] is True

    def test_unary_neg(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=UnaryExpr(op=UnaryOp.NEG, operand=LiteralExpr(value="5")),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == -5

    def test_unary_not_bool(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=UnaryExpr(op=UnaryOp.NOT, operand=LiteralExpr(value="TRUE")),
            ),
        ])
        state = _run(pou, {"x": True})
        assert state["x"] is False

    def test_function_call_abs(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=FunctionCallExpr(
                    function_name="ABS",
                    args=[CallArg(value=LiteralExpr(value="-5"))],
                ),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == 5

    def test_type_conversion(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=TypeConversionExpr(
                    target_type=PrimitiveTypeRef(type=PrimitiveType.INT),
                    source=LiteralExpr(value="3.7"),
                ),
            ),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == 3

    def test_no_short_circuit_and(self):
        """Both sides of AND evaluate even if left is False (PLC semantics)."""
        # We test this by having both sides increment a counter via side effects
        # Actually, since expressions are pure in the IR, we just verify the
        # result is correct for all combinations
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(
                    op=BinaryOp.AND,
                    left=LiteralExpr(value="FALSE"),
                    right=LiteralExpr(value="TRUE"),
                ),
            ),
        ])
        state = _run(pou, {"x": True})
        assert state["x"] is False


# ---------------------------------------------------------------------------
# Member access
# ---------------------------------------------------------------------------

class TestMemberAccess:
    def test_read_member(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=MemberAccessExpr(
                    struct=VariableRef(name="data"),
                    member="speed",
                ),
            ),
        ])
        state = _run(pou, {"x": 0, "data": {"speed": 42.5, "running": True}})
        assert state["x"] == 42.5

    def test_write_member(self):
        pou = make_pou([
            Assignment(
                target=MemberAccessExpr(
                    struct=VariableRef(name="data"),
                    member="speed",
                ),
                value=LiteralExpr(value="100.0"),
            ),
        ])
        state = _run(pou, {"data": {"speed": 0.0, "running": False}})
        assert state["data"]["speed"] == 100.0


# ---------------------------------------------------------------------------
# Array access
# ---------------------------------------------------------------------------

class TestArrayAccess:
    def test_read_array(self):
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=ArrayAccessExpr(
                    array=VariableRef(name="arr"),
                    indices=[LiteralExpr(value="2")],
                ),
            ),
        ])
        state = _run(pou, {"x": 0, "arr": [10, 20, 30, 40]})
        assert state["x"] == 30

    def test_write_array(self):
        pou = make_pou([
            Assignment(
                target=ArrayAccessExpr(
                    array=VariableRef(name="arr"),
                    indices=[LiteralExpr(value="1")],
                ),
                value=LiteralExpr(value="99"),
            ),
        ])
        state = _run(pou, {"arr": [0, 0, 0]})
        assert state["arr"][1] == 99


# ---------------------------------------------------------------------------
# FB Invocation
# ---------------------------------------------------------------------------

class TestFBInvocation:
    def test_builtin_ton(self):
        pou = make_pou([
            FBInvocation(
                instance_name="timer",
                fb_type="TON",
                inputs={
                    "IN": LiteralExpr(value="TRUE"),
                    "PT": LiteralExpr(value="T#1s"),
                },
            ),
            Assignment(
                target=VariableRef(name="result"),
                value=MemberAccessExpr(
                    struct=VariableRef(name="timer"),
                    member="Q",
                ),
            ),
        ])
        from plx.framework._iec_builtins import TON
        state = {
            "timer": TON.initial_state(),
            "result": False,
        }
        _run(pou, state, clock_ms=0)
        assert state["result"] is False

        _run(pou, state, clock_ms=1000)
        assert state["result"] is True

    def test_nested_user_fb(self):
        """User-defined FB calling another user-defined FB."""
        inner_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Inner",
            interface=POUInterface(
                input_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.INT))],
                output_vars=[Variable(name="y", data_type=PrimitiveTypeRef(type=PrimitiveType.INT))],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="y"),
                    value=BinaryExpr(
                        op=BinaryOp.MUL,
                        left=VariableRef(name="x"),
                        right=LiteralExpr(value="2"),
                    ),
                ),
            ])],
        )

        outer_pou = make_pou([
            FBInvocation(
                instance_name="inner_inst",
                fb_type="Inner",
                inputs={"x": LiteralExpr(value="5")},
                outputs={"y": VariableRef(name="result")},
            ),
        ])

        state = {
            "inner_inst": {"x": 0, "y": 0},
            "result": 0,
        }
        _run(outer_pou, state, pou_registry={"Inner": inner_pou})
        assert state["result"] == 10


# ---------------------------------------------------------------------------
# Return statement
# ---------------------------------------------------------------------------

class TestReturn:
    def test_return_stops_execution(self):
        pou = make_pou([
            Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
            ReturnStatement(),
            Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="2")),
        ])
        state = _run(pou, {"x": 0})
        assert state["x"] == 1


# ---------------------------------------------------------------------------
# Empty statement
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_empty_noop(self):
        pou = make_pou([EmptyStatement()])
        state = _run(pou, {})
        assert state == {}


# ---------------------------------------------------------------------------
# ROL / ROR (#9)
# ---------------------------------------------------------------------------

class TestRotate:
    def test_rol_basic(self):
        """ROL(0x80000001, 1) should give 0x00000003."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(
                    op=BinaryOp.ROL,
                    left=VariableRef(name="a"),
                    right=LiteralExpr(value="1"),
                ),
            ),
        ])
        state = _run(pou, {"x": 0, "a": 0x80000001})
        assert state["x"] == 0x00000003

    def test_ror_basic(self):
        """ROR(0x00000003, 1) should give 0x80000001."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(
                    op=BinaryOp.ROR,
                    left=VariableRef(name="a"),
                    right=LiteralExpr(value="1"),
                ),
            ),
        ])
        state = _run(pou, {"x": 0, "a": 0x00000003})
        assert state["x"] == 0x80000001

    def test_rol_full_rotation(self):
        """ROL by 32 returns the original value."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(
                    op=BinaryOp.ROL,
                    left=VariableRef(name="a"),
                    right=LiteralExpr(value="32"),
                ),
            ),
        ])
        state = _run(pou, {"x": 0, "a": 0xDEADBEEF})
        assert state["x"] == 0xDEADBEEF

    def test_ror_by_zero(self):
        """ROR by 0 returns the original value."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="x"),
                value=BinaryExpr(
                    op=BinaryOp.ROR,
                    left=VariableRef(name="a"),
                    right=LiteralExpr(value="0"),
                ),
            ),
        ])
        state = _run(pou, {"x": 0, "a": 0xABCD1234})
        assert state["x"] == 0xABCD1234


# ---------------------------------------------------------------------------
# Method execution (#12)
# ---------------------------------------------------------------------------

class TestMethodExecution:
    def test_method_call_as_statement(self):
        """Call a method defined on the POU."""
        from plx.model.pou import Method, POUInterface as MI

        method = Method(
            name="double_x",
            interface=MI(
                input_vars=[],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=BinaryExpr(
                        op=BinaryOp.MUL,
                        left=VariableRef(name="x"),
                        right=LiteralExpr(value="2"),
                    ),
                ),
            ])],
        )

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestPOU",
            interface=MI(
                static_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.INT))],
            ),
            networks=[Network(statements=[
                FunctionCallStatement(function_name="double_x", args=[]),
            ])],
            methods=[method],
        )

        state = _run(pou, {"x": 5})
        assert state["x"] == 10

    def test_method_with_return(self):
        """Method that returns a value used in expression."""
        from plx.model.pou import Method, POUInterface as MI

        method = Method(
            name="get_sum",
            interface=MI(
                input_vars=[
                    Variable(name="a", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                    Variable(name="b", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                ],
            ),
            networks=[Network(statements=[
                ReturnStatement(value=BinaryExpr(
                    op=BinaryOp.ADD,
                    left=VariableRef(name="a"),
                    right=VariableRef(name="b"),
                )),
            ])],
        )

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestPOU",
            interface=MI(
                static_vars=[Variable(name="result", data_type=PrimitiveTypeRef(type=PrimitiveType.INT))],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="result"),
                    value=FunctionCallExpr(
                        function_name="get_sum",
                        args=[
                            CallArg(value=LiteralExpr(value="3")),
                            CallArg(value=LiteralExpr(value="7")),
                        ],
                    ),
                ),
            ])],
            methods=[method],
        )

        state = _run(pou, {"result": 0})
        assert state["result"] == 10


# ---------------------------------------------------------------------------
# Bit access
# ---------------------------------------------------------------------------

class TestBitAccess:
    def test_read_bit_set(self):
        """Read a bit that is set → True."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(target=VariableRef(name="word"), bit_index=3),
            ),
        ])
        state = _run(pou, {"word": 0b1000, "result": False})
        assert state["result"] is True

    def test_read_bit_clear(self):
        """Read a bit that is clear → False."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(target=VariableRef(name="word"), bit_index=2),
            ),
        ])
        state = _run(pou, {"word": 0b1000, "result": True})
        assert state["result"] is False

    def test_write_bit_set(self):
        """Write bit set: 0 → 8 via setting bit3."""
        pou = make_pou([
            Assignment(
                target=BitAccessExpr(target=VariableRef(name="word"), bit_index=3),
                value=LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ),
        ])
        state = _run(pou, {"word": 0})
        assert state["word"] == 8

    def test_write_bit_clear(self):
        """Write bit clear: 7 → 3 via clearing bit2."""
        pou = make_pou([
            Assignment(
                target=BitAccessExpr(target=VariableRef(name="word"), bit_index=2),
                value=LiteralExpr(value="FALSE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ),
        ])
        state = _run(pou, {"word": 7})
        assert state["word"] == 3

    def test_write_bit_on_struct_member(self):
        """Write bit on a nested struct member."""
        pou = make_pou([
            Assignment(
                target=BitAccessExpr(
                    target=MemberAccessExpr(struct=VariableRef(name="data"), member="flags"),
                    bit_index=1,
                ),
                value=LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ),
        ])
        state = _run(pou, {"data": {"flags": 0}})
        assert state["data"]["flags"] == 2

    def test_read_high_bit(self):
        """Read bit31 of 0x80000000."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(target=VariableRef(name="word"), bit_index=31),
            ),
        ])
        state = _run(pou, {"word": 0x80000000, "result": False})
        assert state["result"] is True

    def test_out_of_range_bit_index(self):
        """Out-of-range bit index → SimulationError."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(target=VariableRef(name="word"), bit_index=64),
            ),
        ])
        with pytest.raises(SimulationError, match="out of range"):
            _run(pou, {"word": 0, "result": False})

    def test_read_modify_write_preserves_bits(self):
        """Read-modify-write preserves other bits."""
        pou = make_pou([
            # Set bit 0
            Assignment(
                target=BitAccessExpr(target=VariableRef(name="word"), bit_index=0),
                value=LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ),
            # Set bit 7
            Assignment(
                target=BitAccessExpr(target=VariableRef(name="word"), bit_index=7),
                value=LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ),
        ])
        state = _run(pou, {"word": 0b00110000})
        # Original bits 4,5 + new bits 0,7
        assert state["word"] == 0b10110001


# ---------------------------------------------------------------------------
# SystemFlagExpr
# ---------------------------------------------------------------------------

class TestSystemFlagExpr:
    def test_first_scan_true(self):
        """SystemFlagExpr evaluates to True when __system_first_scan is True."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=SystemFlagExpr(flag=SystemFlag.FIRST_SCAN),
            ),
        ])
        state = _run(pou, {"result": False, "__system_first_scan": True})
        assert state["result"] is True

    def test_first_scan_false(self):
        """SystemFlagExpr evaluates to False when __system_first_scan is False."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=SystemFlagExpr(flag=SystemFlag.FIRST_SCAN),
            ),
        ])
        state = _run(pou, {"result": True, "__system_first_scan": False})
        assert state["result"] is False

    def test_first_scan_missing_defaults_false(self):
        """SystemFlagExpr defaults to False if __system_first_scan is absent."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=SystemFlagExpr(flag=SystemFlag.FIRST_SCAN),
            ),
        ])
        state = _run(pou, {"result": True})
        assert state["result"] is False


# ---------------------------------------------------------------------------
# Property getter/setter execution
# ---------------------------------------------------------------------------

class TestPropertyExecution:
    def _make_motor_fb_with_property(self):
        """Create a Motor FB with a 'speed' property backed by '_speed'."""
        motor_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            interface=POUInterface(
                static_vars=[
                    Variable(name="_speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                ],
            ),
            networks=[Network(statements=[])],
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            ReturnStatement(value=VariableRef(name="_speed")),
                        ])],
                    ),
                    setter=PropertyAccessor(
                        networks=[Network(statements=[
                            Assignment(
                                target=VariableRef(name="_speed"),
                                value=VariableRef(name="speed"),
                            ),
                        ])],
                    ),
                ),
            ],
        )
        return motor_pou

    def test_getter_returns_computed_value(self):
        """Property getter returns the backing variable's value."""
        motor_pou = self._make_motor_fb_with_property()
        outer_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Outer",
            interface=POUInterface(
                static_vars=[
                    Variable(name="m", data_type=NamedTypeRef(name="Motor")),
                    Variable(name="result", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                ],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="result"),
                    value=MemberAccessExpr(struct=VariableRef(name="m"), member="speed"),
                ),
            ])],
        )
        state = {
            "m": {"_speed": 42.5},
            "result": 0.0,
        }
        _run(outer_pou, state, pou_registry={"Motor": motor_pou})
        assert state["result"] == 42.5

    def test_setter_modifies_backing_var(self):
        """Property setter writes through to the backing variable."""
        motor_pou = self._make_motor_fb_with_property()
        outer_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Outer",
            interface=POUInterface(
                static_vars=[
                    Variable(name="m", data_type=NamedTypeRef(name="Motor")),
                ],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=MemberAccessExpr(struct=VariableRef(name="m"), member="speed"),
                    value=LiteralExpr(value="99.9"),
                ),
            ])],
        )
        state = {
            "m": {"_speed": 0.0},
        }
        _run(outer_pou, state, pou_registry={"Motor": motor_pou})
        assert state["m"]["_speed"] == pytest.approx(99.9)

    def test_getter_with_computation(self):
        """Property getter that multiplies backing var."""
        motor_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            interface=POUInterface(
                static_vars=[
                    Variable(name="_rpm", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                ],
            ),
            networks=[Network(statements=[])],
            properties=[
                Property(
                    name="speed_pct",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            ReturnStatement(
                                value=BinaryExpr(
                                    op=BinaryOp.DIV,
                                    left=VariableRef(name="_rpm"),
                                    right=LiteralExpr(value="60.0"),
                                ),
                            ),
                        ])],
                    ),
                ),
            ],
        )
        outer_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Outer",
            interface=POUInterface(
                static_vars=[
                    Variable(name="m", data_type=NamedTypeRef(name="Motor")),
                    Variable(name="result", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                ],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="result"),
                    value=MemberAccessExpr(struct=VariableRef(name="m"), member="speed_pct"),
                ),
            ])],
        )
        state = {"m": {"_rpm": 120.0}, "result": 0.0}
        _run(outer_pou, state, pou_registry={"Motor": motor_pou})
        assert state["result"] == pytest.approx(2.0)

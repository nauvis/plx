"""Tests verifying fixes for critical issues found during deep scan.

Each test class corresponds to one critical fix and would have failed
before the fix was applied.
"""

import pytest
from enum import IntEnum

from conftest import make_pou

from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    FunctionCallExpr,
    LiteralExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.pou import Network, POU, POUInterface, POUType
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    FBInvocation,
    ReturnStatement,
)
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable
from plx.simulate._executor import ExecutionEngine
from plx.simulate._values import SimulationError


def _run(pou, state, clock_ms=0, **kwargs):
    engine = ExecutionEngine(pou=pou, state=state, clock_ms=clock_ms, **kwargs)
    return engine.execute()


# ---------------------------------------------------------------------------
# Fix #1: Dynamic bit_index (Expression) must be evaluated, not compared raw
# ---------------------------------------------------------------------------

class TestDynamicBitAccess:
    """BitAccessExpr.bit_index can be an Expression (dynamic bit access)."""

    def test_read_dynamic_bit_index(self):
        """Reading a bit via a variable index should evaluate the expression."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(
                    target=VariableRef(name="word"),
                    bit_index=VariableRef(name="idx"),
                ),
            ),
        ])
        state = {"word": 0b1010, "idx": 3, "result": False}
        _run(pou, state)
        assert state["result"] is True

    def test_read_dynamic_bit_index_clear(self):
        """Dynamic bit read returns False when the target bit is 0."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(
                    target=VariableRef(name="word"),
                    bit_index=VariableRef(name="idx"),
                ),
            ),
        ])
        state = {"word": 0b1010, "idx": 2, "result": True}
        _run(pou, state)
        assert state["result"] is False

    def test_write_dynamic_bit_index(self):
        """Writing a bit via a variable index should evaluate the expression."""
        pou = make_pou([
            Assignment(
                target=BitAccessExpr(
                    target=VariableRef(name="word"),
                    bit_index=VariableRef(name="idx"),
                ),
                value=LiteralExpr(value="TRUE"),
            ),
        ])
        state = {"word": 0b0000, "idx": 5, "result": 0}
        _run(pou, state)
        assert state["word"] == 0b100000

    def test_write_dynamic_bit_index_clear(self):
        """Clearing a bit via a dynamic index."""
        pou = make_pou([
            Assignment(
                target=BitAccessExpr(
                    target=VariableRef(name="word"),
                    bit_index=VariableRef(name="idx"),
                ),
                value=LiteralExpr(value="FALSE"),
            ),
        ])
        state = {"word": 0b11111111, "idx": 3}
        _run(pou, state)
        assert state["word"] == 0b11110111

    def test_dynamic_bit_index_with_expression(self):
        """Bit index is a computed expression (e.g. idx + 1)."""
        pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=BitAccessExpr(
                    target=VariableRef(name="word"),
                    bit_index=BinaryExpr(
                        op=BinaryOp.ADD,
                        left=VariableRef(name="idx"),
                        right=LiteralExpr(value="1"),
                    ),
                ),
            ),
        ])
        # word = 0b0100 → bit 2 is set; idx=1, so idx+1=2
        state = {"word": 0b0100, "idx": 1, "result": False}
        _run(pou, state)
        assert state["result"] is True


# ---------------------------------------------------------------------------
# Fix #2: CASE branches with enum literal strings must resolve to int
# ---------------------------------------------------------------------------

class TestCaseEnumLiterals:
    """CaseBranch.values can contain 'EnumName#MEMBER' strings."""

    def test_case_matches_enum_literal(self):
        """Enum string literal in branch.values should match integer selector."""

        class Color(IntEnum):
            RED = 0
            GREEN = 1
            BLUE = 2

        pou = make_pou([
            CaseStatement(
                selector=VariableRef(name="sel"),
                branches=[
                    CaseBranch(
                        values=["Color#RED"],
                        body=[Assignment(
                            target=VariableRef(name="x"),
                            value=LiteralExpr(value="10"),
                        )],
                    ),
                    CaseBranch(
                        values=["Color#GREEN"],
                        body=[Assignment(
                            target=VariableRef(name="x"),
                            value=LiteralExpr(value="20"),
                        )],
                    ),
                    CaseBranch(
                        values=["Color#BLUE"],
                        body=[Assignment(
                            target=VariableRef(name="x"),
                            value=LiteralExpr(value="30"),
                        )],
                    ),
                ],
            ),
        ])
        state = {"sel": 1, "x": 0}
        _run(pou, state, enum_registry={"Color": Color})
        assert state["x"] == 20

    def test_case_enum_else(self):
        """Unmatched enum selector falls through to else."""

        class State(IntEnum):
            IDLE = 0
            RUNNING = 1

        pou = make_pou([
            CaseStatement(
                selector=VariableRef(name="sel"),
                branches=[
                    CaseBranch(
                        values=["State#IDLE"],
                        body=[Assignment(
                            target=VariableRef(name="x"),
                            value=LiteralExpr(value="1"),
                        )],
                    ),
                ],
                else_body=[
                    Assignment(
                        target=VariableRef(name="x"),
                        value=LiteralExpr(value="99"),
                    ),
                ],
            ),
        ])
        state = {"sel": 1, "x": 0}
        _run(pou, state, enum_registry={"State": State})
        assert state["x"] == 99

    def test_case_mixed_int_and_enum(self):
        """Branch with both plain int and enum literal values."""

        class Mode(IntEnum):
            AUTO = 10
            MANUAL = 20

        pou = make_pou([
            CaseStatement(
                selector=VariableRef(name="sel"),
                branches=[
                    CaseBranch(
                        values=[10, "Mode#AUTO"],
                        body=[Assignment(
                            target=VariableRef(name="x"),
                            value=LiteralExpr(value="1"),
                        )],
                    ),
                ],
            ),
        ])
        # Integer 10 matches the plain int value before the enum literal
        state = {"sel": 10, "x": 0}
        _run(pou, state, enum_registry={"Mode": Mode})
        assert state["x"] == 1


# ---------------------------------------------------------------------------
# Fix #3: Abstract POU ST export must use END_FUNCTION_BLOCK, not
#          END_FUNCTION_BLOCK ABSTRACT
# ---------------------------------------------------------------------------

class TestAbstractPOUSTExport:
    """ST exporter must produce valid closing tags for abstract POUs."""

    def test_abstract_fb_closing_tag(self):
        from plx.export.st import to_structured_text

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="AbstractBase",
            abstract=True,
            interface=POUInterface(),
            networks=[Network(statements=[])],
        )
        st = to_structured_text(pou)

        assert "FUNCTION_BLOCK ABSTRACT AbstractBase" in st
        assert "END_FUNCTION_BLOCK" in st
        # Must NOT contain the invalid "END_FUNCTION_BLOCK ABSTRACT"
        assert "END_FUNCTION_BLOCK ABSTRACT" not in st

    def test_abstract_fb_with_extends(self):
        from plx.export.st import to_structured_text

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="DerivedAbstract",
            abstract=True,
            extends="BaseClass",
            interface=POUInterface(),
            networks=[Network(statements=[])],
        )
        st = to_structured_text(pou)

        assert "FUNCTION_BLOCK ABSTRACT DerivedAbstract EXTENDS BaseClass" in st
        assert "END_FUNCTION_BLOCK\n" in st
        assert "END_FUNCTION_BLOCK ABSTRACT" not in st

    def test_non_abstract_fb_unaffected(self):
        """Non-abstract FB should still work normally."""
        from plx.export.st import to_structured_text

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="ConcreteFB",
            interface=POUInterface(),
            networks=[Network(statements=[])],
        )
        st = to_structured_text(pou)

        assert "FUNCTION_BLOCK ConcreteFB" in st
        assert "END_FUNCTION_BLOCK" in st
        assert "ABSTRACT" not in st


# ---------------------------------------------------------------------------
# Fix #4: _call_user_function must allocate output_vars and constant_vars
# ---------------------------------------------------------------------------

class TestFunctionOutputVars:
    """User-defined FUNCTIONs with output_vars must be simulable."""

    def test_function_with_output_var(self):
        """FUNCTION with VAR_OUTPUT should not crash on assignment to output."""
        func_pou = POU(
            pou_type=POUType.FUNCTION,
            name="SplitValue",
            interface=POUInterface(
                input_vars=[
                    Variable(name="raw", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                ],
                output_vars=[
                    Variable(name="high_byte", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                    Variable(name="low_byte", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                ],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="high_byte"),
                    value=BinaryExpr(
                        op=BinaryOp.DIV,
                        left=VariableRef(name="raw"),
                        right=LiteralExpr(value="256"),
                    ),
                ),
                Assignment(
                    target=VariableRef(name="low_byte"),
                    value=BinaryExpr(
                        op=BinaryOp.MOD,
                        left=VariableRef(name="raw"),
                        right=LiteralExpr(value="256"),
                    ),
                ),
            ])],
        )

        # Call the function from an outer POU via FunctionCallExpr
        # We use a FunctionCallStatement + output read pattern
        outer_pou = make_pou([
            FBInvocation(
                instance_name="split_inst",
                fb_type="SplitValue",
                inputs={"raw": LiteralExpr(value="770")},
                outputs={"high_byte": VariableRef(name="h"), "low_byte": VariableRef(name="l")},
            ),
        ])
        state = {"split_inst": {"raw": 0, "high_byte": 0, "low_byte": 0}, "h": 0, "l": 0}
        _run(outer_pou, state, pou_registry={"SplitValue": func_pou})
        assert state["h"] == 3
        assert state["l"] == 2

    def test_function_with_constant_var_no_crash(self):
        """FUNCTION with VAR CONSTANT must not crash with KeyError on read.

        Before the fix, constant_vars were not allocated in func_state,
        so reading a constant would raise KeyError.  Now they are allocated
        with type defaults (initial_value parsing is a separate concern).
        """
        func_pou = POU(
            pou_type=POUType.FUNCTION,
            name="AddOffset",
            interface=POUInterface(
                input_vars=[
                    Variable(name="raw", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                ],
                constant_vars=[
                    Variable(
                        name="OFFSET",
                        data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
                    ),
                ],
            ),
            networks=[Network(statements=[
                ReturnStatement(
                    value=BinaryExpr(
                        op=BinaryOp.ADD,
                        left=VariableRef(name="raw"),
                        right=VariableRef(name="OFFSET"),
                    ),
                ),
            ])],
        )

        outer_pou = make_pou([
            Assignment(
                target=VariableRef(name="result"),
                value=FunctionCallExpr(
                    function_name="AddOffset",
                    args=[CallArg(value=LiteralExpr(value="5"))],
                ),
            ),
        ])
        state = {"result": 0}
        # Should not raise KeyError — OFFSET is allocated (default 0)
        _run(outer_pou, state, pou_registry={"AddOffset": func_pou})
        assert state["result"] == 5  # 5 + 0 (default)


# ---------------------------------------------------------------------------
# Fix #5: LD export NOT(function_call) must preserve the negation
# ---------------------------------------------------------------------------

class TestLDNotFunctionCall:
    """NOT applied to a function call must not be silently dropped."""

    def test_not_function_call_preserves_negation(self):
        """NOT(Func(x)) must include NOT in the LD output."""
        from plx.export.ld import STBox, ir_to_ld
        from plx.model.pou import Network

        stmt = Assignment(
            target=VariableRef(name="y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=FunctionCallExpr(
                    function_name="IsReady",
                    args=[CallArg(value=VariableRef(name="x"))],
                ),
            ),
        )
        ld = ir_to_ld([Network(statements=[stmt])])
        rung = ld.rungs[0]
        # The circuit must contain "NOT" — whether as STBox or otherwise
        assert isinstance(rung.input_circuit, STBox)
        assert "NOT" in rung.input_circuit.st_text
        assert "IsReady" in rung.input_circuit.st_text

    def test_not_simple_variable_unaffected(self):
        """NOT on a simple variable still produces NC contact (not STBox)."""
        from plx.export.ld import Contact, ContactType, ir_to_ld
        from plx.model.pou import Network

        stmt = Assignment(
            target=VariableRef(name="y"),
            value=UnaryExpr(
                op=UnaryOp.NOT,
                operand=VariableRef(name="x"),
            ),
        )
        ld = ir_to_ld([Network(statements=[stmt])])
        rung = ld.rungs[0]
        assert isinstance(rung.input_circuit, Contact)
        assert rung.input_circuit.contact_type == ContactType.NC

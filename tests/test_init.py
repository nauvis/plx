"""Tests for ``def init(self)`` on function blocks."""

import pytest

from plx.export.py import PyWriter
from plx.framework._compiler import CompileError, delayed
from plx.framework._decorators import fb, function, program
from plx.framework._descriptors import Input, Output, Static
from plx.framework._types import BOOL, DINT, REAL
from plx.model.expressions import LiteralExpr, UnaryExpr, UnaryOp, VariableRef
from plx.model.init_pattern import INIT_FLAG_NAME, detect_init_pattern
from plx.model.pou import Network, POUType
from plx.model.statements import Assignment, IfBranch, IfStatement
from plx.model.types import PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable

# ============================================================================
# Framework compilation
# ============================================================================


class TestInitCompilation:
    def test_basic_init(self):
        @fb
        class BasicInit:
            speed: Static[REAL] = 0.0

            def init(self):
                self.speed = 100.0

            def logic(self):
                pass

        pou = BasicInit.compile()
        assert pou.pou_type == POUType.FUNCTION_BLOCK

        # _plx_initialized should be in static vars
        flag_vars = [v for v in pou.interface.static_vars if v.name == INIT_FLAG_NAME]
        assert len(flag_vars) == 1
        assert isinstance(flag_vars[0].data_type, PrimitiveTypeRef)
        assert flag_vars[0].data_type.type == PrimitiveType.BOOL
        assert flag_vars[0].initial_value == "FALSE"

        # First network should be the IF guard
        assert len(pou.networks) >= 1
        first_stmt = pou.networks[0].statements[0]
        assert isinstance(first_stmt, IfStatement)
        cond = first_stmt.if_branch.condition
        assert isinstance(cond, UnaryExpr)
        assert cond.op == UnaryOp.NOT
        assert isinstance(cond.operand, VariableRef)
        assert cond.operand.name == INIT_FLAG_NAME

        # IF body has init assignment + flag set
        body = first_stmt.if_branch.body
        assert len(body) == 2  # speed := 100.0 + _plx_initialized := TRUE

        # Last statement sets flag
        last = body[-1]
        assert isinstance(last, Assignment)
        assert isinstance(last.target, VariableRef)
        assert last.target.name == INIT_FLAG_NAME
        assert isinstance(last.value, LiteralExpr)
        assert last.value.value == "TRUE"

    def test_init_with_multiple_statements(self):
        @fb
        class MultiInit:
            x: Static[DINT] = 0
            y: Static[REAL] = 0.0
            ready: Output[BOOL]

            def init(self):
                self.x = 42
                self.y = 3.14
                self.ready = True

            def logic(self):
                pass

        pou = MultiInit.compile()
        first_stmt = pou.networks[0].statements[0]
        assert isinstance(first_stmt, IfStatement)
        # 3 init stmts + 1 flag assignment
        assert len(first_stmt.if_branch.body) == 4

    def test_init_and_logic_both_present(self):
        @fb
        class InitAndLogic:
            counter: Static[DINT] = 0
            value: Output[DINT]

            def init(self):
                self.counter = 10

            def logic(self):
                self.counter = self.counter + 1
                self.value = self.counter

        pou = InitAndLogic.compile()
        # Should have at least 2 networks: init guard + logic
        assert len(pou.networks) >= 2
        # First is the init guard
        assert isinstance(pou.networks[0].statements[0], IfStatement)

    def test_init_references_self_vars(self):
        @fb
        class InitSelfRef:
            target: Input[REAL]
            speed: Static[REAL] = 0.0

            def init(self):
                self.speed = self.target

            def logic(self):
                pass

        pou = InitSelfRef.compile()
        first_stmt = pou.networks[0].statements[0]
        assert isinstance(first_stmt, IfStatement)
        # Init body: speed := target + flag assignment
        assert len(first_stmt.if_branch.body) == 2

    def test_fb_without_init_no_regression(self):
        @fb
        class NoInit:
            sensor: Input[BOOL]
            output: Output[BOOL]

            def logic(self):
                self.output = self.sensor

        pou = NoInit.compile()
        # No _plx_initialized var
        flag_vars = [v for v in pou.interface.static_vars if v.name == INIT_FLAG_NAME]
        assert len(flag_vars) == 0
        # No IF guard wrapping
        assert len(pou.networks) == 1
        assert not isinstance(pou.networks[0].statements[0], IfStatement)


# ============================================================================
# Error cases
# ============================================================================


class TestInitErrors:
    def test_init_on_function_rejected(self):
        with pytest.raises(CompileError, match="only supported on @fb"):

            @function
            class BadFunc:
                x: Input[REAL]

                def init(self):
                    pass

                def logic(self) -> REAL:
                    return self.x

    def test_init_on_program_rejected(self):
        with pytest.raises(CompileError, match="only supported on @fb"):

            @program
            class BadProg:
                x: Static[REAL] = 0.0

                def init(self):
                    self.x = 1.0

                def logic(self):
                    pass

    def test_sentinel_in_init_rejected(self):
        with pytest.raises(CompileError, match="Sentinel functions"):

            @fb
            class BadSentinel:
                sensor: Input[BOOL]
                ready: Output[BOOL]

                def init(self):
                    self.ready = delayed(self.sensor, "T#1s")

                def logic(self):
                    pass

    def test_init_with_params_rejected(self):
        """init() must take only self."""
        with pytest.raises(CompileError, match="must take exactly one parameter"):

            @fb
            class BadParams:
                x: Static[REAL] = 0.0

                def init(self, value):
                    self.x = value

                def logic(self):
                    pass


# ============================================================================
# Init pattern detection (shared helper)
# ============================================================================


class TestInitPatternDetection:
    def _make_init_ir(self) -> tuple[list[Variable], list[Network]]:
        """Build the canonical init pattern IR."""
        flag = Variable(
            name=INIT_FLAG_NAME,
            data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
            initial_value="FALSE",
        )
        init_assign = Assignment(
            target=VariableRef(name="speed"),
            value=LiteralExpr(value="100.0"),
        )
        set_flag = Assignment(
            target=VariableRef(name=INIT_FLAG_NAME),
            value=LiteralExpr(value="TRUE"),
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=UnaryExpr(
                    op=UnaryOp.NOT,
                    operand=VariableRef(name=INIT_FLAG_NAME),
                ),
                body=[init_assign, set_flag],
            ),
        )
        networks = [Network(statements=[if_stmt])]
        return [flag], networks

    def test_detect_valid_pattern(self):
        static_vars, networks = self._make_init_ir()
        result = detect_init_pattern(static_vars, networks)
        assert result is not None
        assert len(result.init_body) == 1
        assert isinstance(result.init_body[0], Assignment)

    def test_no_flag_var(self):
        _, networks = self._make_init_ir()
        result = detect_init_pattern([], networks)
        assert result is None

    def test_no_if_statement(self):
        static_vars, _ = self._make_init_ir()
        networks = [
            Network(
                statements=[
                    Assignment(
                        target=VariableRef(name="x"),
                        value=LiteralExpr(value="1"),
                    )
                ]
            )
        ]
        result = detect_init_pattern(static_vars, networks)
        assert result is None

    def test_wrong_condition(self):
        """IF _plx_initialized (without NOT) should not match."""
        flag = Variable(
            name=INIT_FLAG_NAME,
            data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
            initial_value="FALSE",
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name=INIT_FLAG_NAME),
                body=[
                    Assignment(
                        target=VariableRef(name=INIT_FLAG_NAME),
                        value=LiteralExpr(value="TRUE"),
                    )
                ],
            ),
        )
        result = detect_init_pattern([flag], [Network(statements=[if_stmt])])
        assert result is None

    def test_with_elsif_no_match(self):
        """Pattern with elsif branches should not match."""
        flag = Variable(
            name=INIT_FLAG_NAME,
            data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
            initial_value="FALSE",
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=UnaryExpr(
                    op=UnaryOp.NOT,
                    operand=VariableRef(name=INIT_FLAG_NAME),
                ),
                body=[
                    Assignment(
                        target=VariableRef(name=INIT_FLAG_NAME),
                        value=LiteralExpr(value="TRUE"),
                    )
                ],
            ),
            elsif_branches=[
                IfBranch(
                    condition=LiteralExpr(value="TRUE"),
                    body=[],
                )
            ],
        )
        result = detect_init_pattern([flag], [Network(statements=[if_stmt])])
        assert result is None


# ============================================================================
# Python export round-trip
# ============================================================================


def _gen(pou):
    """Generate Python code for a single POU using PyWriter."""
    w = PyWriter()
    w._write_pou(pou)
    return w.getvalue()


class TestInitPythonExport:
    def test_round_trip_basic(self):
        @fb
        class ConveyorInit:
            speed: Static[REAL] = 0.0

            def init(self):
                self.speed = 100.0

            def logic(self):
                pass

        pou = ConveyorInit.compile()
        code = _gen(pou)

        assert "def init(self):" in code
        assert "def logic(self):" in code
        assert INIT_FLAG_NAME not in code
        assert "self.speed = 100.0" in code

    def test_round_trip_preserves_init_body(self):
        @fb
        class MultiStmt:
            x: Static[DINT] = 0
            y: Static[REAL] = 0.0

            def init(self):
                self.x = 42
                self.y = 3.14

            def logic(self):
                self.x = self.x + 1

        pou = MultiStmt.compile()
        code = _gen(pou)

        assert "def init(self):" in code
        assert "self.x = 42" in code
        assert "self.y = 3.14" in code
        assert INIT_FLAG_NAME not in code

    def test_no_init_passes_through(self):
        @fb
        class PlainFB:
            sensor: Input[BOOL]
            output: Output[BOOL]

            def logic(self):
                self.output = self.sensor

        pou = PlainFB.compile()
        code = _gen(pou)

        assert "def init(self):" not in code
        assert "def logic(self):" in code

    def test_round_trip_structure(self):
        """Compile → generate → verify generated code is valid and has init()."""

        @fb
        class RoundTripFB:
            speed: Static[REAL] = 0.0
            count: Static[DINT] = 0

            def init(self):
                self.speed = 100.0

            def logic(self):
                self.count = self.count + 1

        pou = RoundTripFB.compile()
        code = _gen(pou)

        # Generated code should have init + logic
        assert "def init(self):" in code
        assert "def logic(self):" in code
        assert INIT_FLAG_NAME not in code

        # init() should appear before logic()
        init_pos = code.index("def init(self):")
        logic_pos = code.index("def logic(self):")
        assert init_pos < logic_pos

        # _plx_initialized should be in the IR static vars
        flag_vars = [v for v in pou.interface.static_vars if v.name == INIT_FLAG_NAME]
        assert len(flag_vars) == 1


# ============================================================================
# Simulation
# ============================================================================


class TestInitSimulation:
    def test_init_runs_on_first_scan(self):
        from plx.simulate import SimulationContext

        @fb
        class SimInit:
            speed: Static[REAL] = 0.0
            count: Static[DINT] = 0

            def init(self):
                self.speed = 100.0

            def logic(self):
                self.count = self.count + 1

        pou = SimInit.compile()
        ctx = SimulationContext(pou)

        # Before any scan
        assert ctx.speed == 0.0
        assert ctx.count == 0

        # First scan: init runs, then logic
        ctx.scan()
        assert ctx.speed == 100.0
        assert ctx.count == 1

        # Second scan: init does NOT run again
        ctx.scan()
        assert ctx.speed == 100.0
        assert ctx.count == 2

    def test_reinit_on_flag_reset(self):
        from plx.simulate import SimulationContext

        @fb
        class ReInit:
            speed: Static[REAL] = 0.0

            def init(self):
                self.speed = 50.0

            def logic(self):
                self.speed = self.speed + 1.0

        pou = ReInit.compile()
        ctx = SimulationContext(pou)

        # First scan
        ctx.scan()
        assert ctx.speed == 51.0  # init sets 50, logic adds 1

        # Second scan
        ctx.scan()
        assert ctx.speed == 52.0

        # Reset flag to trigger re-init
        ctx._plx_initialized = False
        ctx.scan()
        assert ctx.speed == 51.0  # init runs again: 50 + 1

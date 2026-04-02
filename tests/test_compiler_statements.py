"""Tests for AST compiler — statement handlers."""

from conftest import compile_stmts
from plx.framework._compiler import CompileContext
from plx.framework._descriptors import VarDirection
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    LiteralExpr,
    VariableRef,
)
from plx.model.statements import (
    Assignment,
    CaseStatement,
    ContinueStatement,
    ExitStatement,
    ForStatement,
    IfStatement,
    ReturnStatement,
    WhileStatement,
)
from plx.model.types import PrimitiveType, PrimitiveTypeRef

# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


class TestAssignment:
    def test_self_attr_assign(self):
        stmts = compile_stmts("self.x = 42")
        assert len(stmts) == 1
        assert isinstance(stmts[0], Assignment)
        assert isinstance(stmts[0].target, VariableRef)
        assert stmts[0].target.name == "x"
        assert isinstance(stmts[0].value, LiteralExpr)
        assert stmts[0].value.value == "42"

    def test_self_attr_assign_expr(self):
        stmts = compile_stmts("self.x = self.a + self.b")
        assert len(stmts) == 1
        assert isinstance(stmts[0].value, BinaryExpr)

    def test_bare_name_declared(self):
        ctx = CompileContext(declared_vars={"x": VarDirection.TEMP})
        stmts = compile_stmts("x = 10", ctx)
        assert len(stmts) == 1
        assert stmts[0].target.name == "x"

    def test_bare_name_inferred_int(self):
        """Bare assignment with int literal infers INT temp."""
        ctx = CompileContext()
        stmts = compile_stmts("x = 10", ctx)
        assert len(stmts) == 1
        assert stmts[0].target.name == "x"
        assert ctx.declared_vars["x"] == VarDirection.TEMP
        assert len(ctx.generated_temp_vars) == 1
        assert ctx.generated_temp_vars[0].name == "x"
        assert ctx.generated_temp_vars[0].data_type.type.value == "INT"

    def test_bare_name_inferred_bitwise_ops(self):
        """Bitwise ops (& | ^) should infer type from operands."""
        for op_sym in ("&", "|", "^"):
            ctx = CompileContext(
                declared_vars={"a": VarDirection.TEMP, "b": VarDirection.TEMP},
                static_var_types={
                    "a": PrimitiveTypeRef(type=PrimitiveType.DINT),
                    "b": PrimitiveTypeRef(type=PrimitiveType.DINT),
                },
            )
            stmts = compile_stmts(f"x = a {op_sym} b", ctx)
            assert len(stmts) == 1
            assert ctx.declared_vars["x"] == VarDirection.TEMP
            assert len(ctx.generated_temp_vars) == 1
            assert ctx.generated_temp_vars[0].data_type.type.value == "DINT"

    def test_bare_name_undeclared_no_inference_raises(self):
        """Bare assignment where type cannot be inferred still raises."""
        import pytest

        from plx.framework._compiler import CompileError

        # fn_call() return type is unknown — cannot infer
        with pytest.raises(CompileError, match="Undeclared variable"):
            compile_stmts("x = self.unknown_fb.call()")


# ---------------------------------------------------------------------------
# Augmented assignment
# ---------------------------------------------------------------------------


class TestAugAssign:
    def test_add_assign(self):
        stmts = compile_stmts("self.x += 1")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == BinaryOp.ADD
        assert isinstance(stmt.value.left, VariableRef)
        assert stmt.value.left.name == "x"

    def test_sub_assign(self):
        stmts = compile_stmts("self.x -= 5")
        assert stmts[0].value.op == BinaryOp.SUB

    def test_mul_assign(self):
        stmts = compile_stmts("self.x *= 2")
        assert stmts[0].value.op == BinaryOp.MUL


# ---------------------------------------------------------------------------
# Annotated assignment (temp vars)
# ---------------------------------------------------------------------------


class TestAnnAssign:
    def test_typed_temp_with_value(self):
        stmts = compile_stmts("x: INT = 0")
        assert len(stmts) == 1
        assert isinstance(stmts[0], Assignment)
        assert stmts[0].target.name == "x"

    def test_typed_temp_no_value(self):
        stmts = compile_stmts("x: REAL")
        assert len(stmts) == 0

    def test_typed_temp_registers_var(self):
        ctx = CompileContext()
        compile_stmts("x: DINT = 0", ctx)
        assert "x" in ctx.declared_vars
        assert ctx.declared_vars["x"] == VarDirection.TEMP
        assert len(ctx.generated_temp_vars) == 1
        assert ctx.generated_temp_vars[0].name == "x"
        assert ctx.generated_temp_vars[0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_typed_temp_allows_subsequent_assign(self):
        ctx = CompileContext()
        stmts = compile_stmts("x: INT = 0\nx = 42", ctx)
        assert len(stmts) == 2


# ---------------------------------------------------------------------------
# If statements
# ---------------------------------------------------------------------------


class TestIfStatement:
    def test_simple_if(self):
        stmts = compile_stmts("""\
if self.sensor:
    self.output = True
""")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, IfStatement)
        assert isinstance(stmt.if_branch.condition, VariableRef)
        assert len(stmt.if_branch.body) == 1

    def test_if_else(self):
        stmts = compile_stmts("""\
if self.sensor:
    self.output = True
else:
    self.output = False
""")
        stmt = stmts[0]
        assert len(stmt.else_body) == 1

    def test_if_elif_else(self):
        stmts = compile_stmts("""\
if self.a:
    self.x = 1
elif self.b:
    self.x = 2
elif self.c:
    self.x = 3
else:
    self.x = 0
""")
        stmt = stmts[0]
        assert isinstance(stmt, IfStatement)
        assert len(stmt.elsif_branches) == 2
        assert len(stmt.else_body) == 1

    def test_nested_if(self):
        stmts = compile_stmts("""\
if self.a:
    if self.b:
        self.x = 1
""")
        stmt = stmts[0]
        assert isinstance(stmt.if_branch.body[0], IfStatement)


# ---------------------------------------------------------------------------
# For loops
# ---------------------------------------------------------------------------


class TestForStatement:
    def test_range_one_arg(self):
        stmts = compile_stmts("""\
for i in range(10):
    self.x = i
""")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, ForStatement)
        assert stmt.loop_var == "i"
        assert isinstance(stmt.from_expr, LiteralExpr)
        assert stmt.from_expr.value == "0"
        # to_expr = 10 - 1
        assert isinstance(stmt.to_expr, BinaryExpr)
        assert stmt.by_expr is None

    def test_range_two_args(self):
        stmts = compile_stmts("""\
for i in range(1, 10):
    self.x = i
""")
        stmt = stmts[0]
        assert isinstance(stmt.from_expr, LiteralExpr)
        assert stmt.from_expr.value == "1"

    def test_range_three_args(self):
        stmts = compile_stmts("""\
for i in range(0, 20, 2):
    self.x = i
""")
        stmt = stmts[0]
        assert stmt.by_expr is not None

    def test_range_negative_step(self):
        """range(10, 0, -1) → FOR i := 10 TO (0 + 1) BY -1 (descending)."""
        stmts = compile_stmts("""\
for i in range(10, 0, -1):
    self.x = i
""")
        stmt = stmts[0]
        assert isinstance(stmt, ForStatement)
        assert isinstance(stmt.from_expr, LiteralExpr)
        assert stmt.from_expr.value == "10"
        # Descending: to_expr = stop + 1 (not stop - 1)
        assert isinstance(stmt.to_expr, BinaryExpr)
        assert stmt.to_expr.op == BinaryOp.ADD
        assert isinstance(stmt.to_expr.left, LiteralExpr)
        assert stmt.to_expr.left.value == "0"
        assert isinstance(stmt.to_expr.right, LiteralExpr)
        assert stmt.to_expr.right.value == "1"
        # by = -1
        assert stmt.by_expr is not None

    def test_range_positive_step_uses_sub(self):
        """range(0, 20, 2) → FOR i := 0 TO (20 - 1) BY 2 (ascending)."""
        stmts = compile_stmts("""\
for i in range(0, 20, 2):
    self.x = i
""")
        stmt = stmts[0]
        assert isinstance(stmt.to_expr, BinaryExpr)
        assert stmt.to_expr.op == BinaryOp.SUB

    def test_loop_var_auto_declared(self):
        ctx = CompileContext()
        compile_stmts(
            """\
for i in range(10):
    self.x = i
""",
            ctx,
        )
        assert "i" in ctx.declared_vars
        assert len(ctx.generated_temp_vars) == 1

    def test_for_else_rejected(self):
        import pytest

        from plx.framework._compiler import CompileError

        with pytest.raises(CompileError, match="for/else is not supported"):
            compile_stmts("""\
for i in range(10):
    self.x = i
else:
    self.x = -1
""")


# ---------------------------------------------------------------------------
# While loops
# ---------------------------------------------------------------------------


class TestWhileStatement:
    def test_basic(self):
        stmts = compile_stmts("""\
while self.running:
    self.x += 1
""")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, WhileStatement)
        assert isinstance(stmt.condition, VariableRef)
        assert len(stmt.body) == 1

    def test_while_else_rejected(self):
        import pytest

        from plx.framework._compiler import CompileError

        with pytest.raises(CompileError, match="while/else is not supported"):
            compile_stmts("""\
while self.running:
    self.x += 1
else:
    self.x = 0
""")


# ---------------------------------------------------------------------------
# Match/case
# ---------------------------------------------------------------------------


class TestMatchStatement:
    def test_basic_match(self):
        stmts = compile_stmts("""\
match self.state:
    case 0:
        self.x = 1
    case 1:
        self.x = 2
    case _:
        self.x = 0
""")
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, CaseStatement)
        assert len(stmt.branches) == 2
        assert stmt.branches[0].values == [0]
        assert stmt.branches[1].values == [1]
        assert len(stmt.else_body) == 1

    def test_or_pattern(self):
        stmts = compile_stmts("""\
match self.state:
    case 1 | 2 | 3:
        self.x = 1
    case _:
        self.x = 0
""")
        stmt = stmts[0]
        assert stmt.branches[0].values == [1, 2, 3]

    def test_no_wildcard(self):
        stmts = compile_stmts("""\
match self.state:
    case 0:
        self.x = 1
    case 1:
        self.x = 2
""")
        stmt = stmts[0]
        assert len(stmt.branches) == 2
        assert len(stmt.else_body) == 0


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------


class TestControlFlow:
    def test_return_none(self):
        stmts = compile_stmts("return")
        assert len(stmts) == 1
        assert isinstance(stmts[0], ReturnStatement)
        assert stmts[0].value is None

    def test_return_value(self):
        stmts = compile_stmts("return self.x + 1")
        stmt = stmts[0]
        assert isinstance(stmt, ReturnStatement)
        assert isinstance(stmt.value, BinaryExpr)

    def test_break(self):
        stmts = compile_stmts("break")
        assert len(stmts) == 1
        assert isinstance(stmts[0], ExitStatement)

    def test_continue(self):
        stmts = compile_stmts("continue")
        assert len(stmts) == 1
        assert isinstance(stmts[0], ContinueStatement)

    def test_pass(self):
        stmts = compile_stmts("pass")
        assert len(stmts) == 0


# ---------------------------------------------------------------------------
# Multiple statements
# ---------------------------------------------------------------------------


class TestMultipleStatements:
    def test_sequence(self):
        stmts = compile_stmts("""\
self.a = 1
self.b = 2
self.c = self.a + self.b
""")
        assert len(stmts) == 3
        assert all(isinstance(s, Assignment) for s in stmts)


# ---------------------------------------------------------------------------
# Bit access as assignment target
# ---------------------------------------------------------------------------


class TestBitAccessAssignment:
    def test_bit_access_write(self):
        stmts = compile_stmts("self.status.bit5 = True")
        assert len(stmts) == 1
        assert isinstance(stmts[0], Assignment)
        target = stmts[0].target
        assert isinstance(target, BitAccessExpr)
        assert isinstance(target.target, VariableRef)
        assert target.target.name == "status"
        assert target.bit_index == 5
        assert isinstance(stmts[0].value, LiteralExpr)
        assert stmts[0].value.value == "TRUE"

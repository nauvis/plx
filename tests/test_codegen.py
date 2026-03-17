"""Tests for IR-to-Python code generator."""

import pytest

from plx.export.py import (
    PyWriter,
    _format_initial_value,
    _parse_iec_time,
    generate,
    generate_files,
)
from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    FunctionCallExpr,
    CallArg,
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
    AccessSpecifier,
    Method,
    Network,
    POUAction,
    POUInterface,
    POUType,
    Property,
    PropertyAccessor,
)
from plx.model.project import GlobalVariableList, Project
from plx.model.sfc import Action, ActionQualifier, SFCBody, Step, Transition
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
    IfStatement,
    JumpStatement,
    LabelStatement,
    RepeatStatement,
    ReturnStatement,
    TryCatchStatement,
    WhileStatement,
)
from plx.model.task import PeriodicTask
from plx.model.types import (
    AliasType,
    ArrayTypeRef,
    DimensionRange,
    EnumMember,
    EnumType,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
    StructMember,
    StructType,
    SubrangeType,
    UnionType,
)
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# Helper to get output from writer methods
# ---------------------------------------------------------------------------

def _make_writer(self_vars: set[str] | None = None) -> PyWriter:
    w = PyWriter()
    if self_vars:
        w._self_vars = self_vars
    return w


# ===========================================================================
# IEC time parsing
# ===========================================================================

class TestParseIecTime:
    def test_milliseconds(self):
        assert _parse_iec_time("T#100ms") == "timedelta(milliseconds=100)"

    def test_seconds(self):
        assert _parse_iec_time("T#5s") == "timedelta(seconds=5)"

    def test_minutes(self):
        assert _parse_iec_time("T#2m") == "timedelta(minutes=2)"

    def test_hours(self):
        assert _parse_iec_time("T#1h") == "timedelta(hours=1)"

    def test_composite(self):
        result = _parse_iec_time("T#1h30m")
        assert result == "timedelta(hours=1, minutes=30)"

    def test_ltime(self):
        assert _parse_iec_time("LTIME#500ms") == "timedelta(milliseconds=500)"

    def test_not_time(self):
        assert _parse_iec_time("42") is None

    def test_time_prefix_variation(self):
        assert _parse_iec_time("TIME#100ms") == "timedelta(milliseconds=100)"


# ===========================================================================
# Initial value formatting
# ===========================================================================

class TestFormatInitialValue:
    def test_true(self):
        assert _format_initial_value("TRUE") == "True"

    def test_false(self):
        assert _format_initial_value("FALSE") == "False"

    def test_int(self):
        assert _format_initial_value("42") == "42"

    def test_float(self):
        assert _format_initial_value("3.14") == "3.14"

    def test_time(self):
        assert _format_initial_value("T#100ms") == "timedelta(milliseconds=100)"

    def test_enum(self):
        assert _format_initial_value("MachineState#RUNNING") == "MachineState.RUNNING"

    def test_hex_not_enum(self):
        # Hex literals like 16#FF should not be treated as enum
        assert _format_initial_value("16#FF") != "16.FF"

    def test_fb_init_simple(self):
        result = _format_initial_value("(Name := 'Pull Wheel', LogStateChanges := TRUE)")
        assert result == '{"Name": \'Pull Wheel\', "LogStateChanges": True}'

    def test_fb_init_numeric(self):
        result = _format_initial_value("(nValue := 42, fGain := 3.14)")
        assert result == '{"nValue": 42, "fGain": 3.14}'

    def test_fb_init_time(self):
        result = _format_initial_value("(PT := T#5S, bEnabled := TRUE)")
        assert result == '{"PT": timedelta(seconds=5), "bEnabled": True}'

    def test_fb_init_nested(self):
        result = _format_initial_value("(nValue := 42, stConfig := (nParam := 1))")
        assert result == '{"nValue": 42, "stConfig": {"nParam": 1}}'

    def test_fb_init_enum(self):
        result = _format_initial_value("(eMode := E_Mode#Auto)")
        assert result == '{"eMode": E_Mode.Auto}'

    def test_fb_init_round_trip(self):
        """IEC init → Python dict → IEC init round-trips correctly."""
        from plx.framework._descriptors import _format_initial
        iec = "(Name := 'Pull Wheel', LogStateChanges := TRUE)"
        py = _format_initial_value(iec)
        d = eval(py)  # noqa: S307
        assert _format_initial(d) == iec

    def test_fb_init_static_var_output(self):
        """FB instance with init renders as Field(initial={...})."""
        w = _make_writer()
        v = Variable(
            name="PullWheels",
            data_type=NamedTypeRef(name="FB_PullWheel"),
            initial_value="(Name := 'Pull Wheel', LogStateChanges := TRUE)",
        )
        w._self_vars = set()
        w._write_static_var(v)
        out = w.getvalue().strip()
        assert out == "PullWheels: FB_PullWheel = Field(initial={\"Name\": 'Pull Wheel', \"LogStateChanges\": True})"


# ===========================================================================
# Type references
# ===========================================================================

class TestTypeRef:
    def test_primitive(self):
        w = _make_writer()
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.BOOL)) == "bool"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.INT)) == "int"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.REAL)) == "real"

    def test_primitive_python_aliases(self):
        w = _make_writer()
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.DINT)) == "dint"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.BOOL)) == "bool"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.REAL)) == "real"

    def test_primitive_lowercase(self):
        w = _make_writer()
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.SINT)) == "sint"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.LINT)) == "lint"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.LREAL)) == "lreal"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.UDINT)) == "udint"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.UINT)) == "uint"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.BYTE)) == "byte"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.WORD)) == "word"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.DWORD)) == "dword"

    def test_string_with_max_length(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(wide=False, max_length=255)) == "string(255)"

    def test_string_non_default_unchanged(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(wide=False, max_length=80)) == "string(80)"

    def test_string_no_length(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef()) == "string"

    def test_string_with_length(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(max_length=80)) == "string(80)"

    def test_wstring(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(wide=True, max_length=100)) == "wstring(100)"

    def test_named(self):
        w = _make_writer()
        assert w._type_ref(NamedTypeRef(name="MotorData")) == "MotorData"

    def test_array_zero_based(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert w._type_ref(tr) == "array(int, 10)"

    def test_array_one_based(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=1, upper=10)],
        )
        assert w._type_ref(tr) == "array(int, (1, 10))"

    def test_array_with_dint(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert w._type_ref(tr) == "array(dint, 10)"

    def test_array_expression_upper_bound(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=NamedTypeRef(name="I_Module"),
            dimensions=[DimensionRange(
                lower=1,
                upper=MemberAccessExpr(
                    struct=VariableRef(name="Params"),
                    member="MAX_MODULES",
                ),
            )],
        )
        assert w._type_ref(tr) == "array(I_Module, (1, Params.MAX_MODULES))"

    def test_array_expression_both_bounds(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(
                lower=VariableRef(name="MIN_IDX"),
                upper=VariableRef(name="MAX_IDX"),
            )],
        )
        assert w._type_ref(tr) == "array(int, (MIN_IDX, MAX_IDX))"

    def test_pointer(self):
        w = _make_writer()
        tr = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.INT))
        assert w._type_ref(tr) == "pointer_to(int)"

    def test_pointer_with_real(self):
        w = _make_writer()
        tr = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert w._type_ref(tr) == "pointer_to(real)"

    def test_reference(self):
        w = _make_writer()
        tr = ReferenceTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert w._type_ref(tr) == "reference_to(real)"


# ===========================================================================
# Expressions
# ===========================================================================

class TestExpressions:
    def test_literal_true(self):
        w = _make_writer()
        assert w._expr(LiteralExpr(value="TRUE")) == "True"

    def test_literal_false(self):
        w = _make_writer()
        assert w._expr(LiteralExpr(value="FALSE")) == "False"

    def test_literal_int(self):
        w = _make_writer()
        assert w._expr(LiteralExpr(value="42")) == "42"

    def test_literal_float(self):
        w = _make_writer()
        assert w._expr(LiteralExpr(value="3.14")) == "3.14"

    def test_literal_time(self):
        w = _make_writer()
        assert w._expr(LiteralExpr(value="T#100ms")) == "timedelta(milliseconds=100)"

    def test_literal_enum(self):
        w = _make_writer()
        assert w._expr(LiteralExpr(value="State#IDLE")) == "State.IDLE"

    def test_variable_ref_self(self):
        w = _make_writer(self_vars={"sensor"})
        assert w._expr(VariableRef(name="sensor")) == "self.sensor"

    def test_variable_ref_local(self):
        w = _make_writer(self_vars={"x"})
        assert w._expr(VariableRef(name="i")) == "i"

    def test_binary_add(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.ADD,
            left=LiteralExpr(value="1"),
            right=LiteralExpr(value="2"),
        )
        assert w._expr(expr) == "1 + 2"

    def test_binary_and(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.AND,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        assert w._expr(expr) == "a and b"

    def test_binary_or(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.OR,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        assert w._expr(expr) == "a or b"

    def test_binary_eq(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.EQ,
            left=VariableRef(name="x"),
            right=LiteralExpr(value="10"),
        )
        assert w._expr(expr) == "x == 10"

    def test_binary_precedence_parens(self):
        w = _make_writer()
        # (a + b) * c — the add needs parens when inside mul
        inner = BinaryExpr(
            op=BinaryOp.ADD,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        outer = BinaryExpr(
            op=BinaryOp.MUL,
            left=inner,
            right=VariableRef(name="c"),
        )
        assert w._expr(outer) == "(a + b) * c"

    def test_binary_no_unnecessary_parens(self):
        w = _make_writer()
        # a * b + c — no parens needed
        inner = BinaryExpr(
            op=BinaryOp.MUL,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        outer = BinaryExpr(
            op=BinaryOp.ADD,
            left=inner,
            right=VariableRef(name="c"),
        )
        assert w._expr(outer) == "a * b + c"

    def test_unary_not(self):
        w = _make_writer()
        expr = UnaryExpr(op=UnaryOp.NOT, operand=VariableRef(name="x"))
        assert w._expr(expr) == "not x"

    def test_unary_neg(self):
        w = _make_writer()
        expr = UnaryExpr(op=UnaryOp.NEG, operand=VariableRef(name="x"))
        assert w._expr(expr) == "-x"

    def test_unary_bnot(self):
        w = _make_writer()
        expr = UnaryExpr(op=UnaryOp.BNOT, operand=VariableRef(name="mask"))
        assert w._expr(expr) == "~mask"

    def test_band(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.BAND,
            left=VariableRef(name="status"),
            right=LiteralExpr(value="16#00FF"),
        )
        assert w._expr(expr) == "status & 0x00FF"

    def test_bor(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.BOR,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        assert w._expr(expr) == "a | b"

    def test_band_bor_precedence(self):
        """a | b & c → a | (b & c) — BAND binds tighter than BOR."""
        w = _make_writer()
        band = BinaryExpr(
            op=BinaryOp.BAND,
            left=VariableRef(name="b"),
            right=VariableRef(name="c"),
        )
        bor = BinaryExpr(
            op=BinaryOp.BOR,
            left=VariableRef(name="a"),
            right=band,
        )
        assert w._expr(bor) == "a | b & c"

    def test_bor_needs_parens_in_band(self):
        """(a | b) & c → needs parens."""
        w = _make_writer()
        bor = BinaryExpr(
            op=BinaryOp.BOR,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        band = BinaryExpr(
            op=BinaryOp.BAND,
            left=bor,
            right=VariableRef(name="c"),
        )
        assert w._expr(band) == "(a | b) & c"

    def test_function_call(self):
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="ABS",
            args=[CallArg(value=VariableRef(name="x"))],
        )
        assert w._expr(expr) == "abs(x)"

    def test_function_call_round(self):
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="ROUND",
            args=[CallArg(value=VariableRef(name="x"))],
        )
        assert w._expr(expr) == "round(x)"

    def test_function_call_min(self):
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="MIN",
            args=[
                CallArg(value=VariableRef(name="a")),
                CallArg(value=VariableRef(name="b")),
            ],
        )
        assert w._expr(expr) == "min(a, b)"

    def test_array_access(self):
        w = _make_writer(self_vars={"arr"})
        expr = ArrayAccessExpr(
            array=VariableRef(name="arr"),
            indices=[LiteralExpr(value="0")],
        )
        assert w._expr(expr) == "self.arr[0]"

    def test_member_access(self):
        w = _make_writer(self_vars={"motor"})
        expr = MemberAccessExpr(
            struct=VariableRef(name="motor"),
            member="speed",
        )
        assert w._expr(expr) == "self.motor.speed"

    def test_type_conversion(self):
        w = _make_writer()
        expr = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            source=VariableRef(name="x"),
        )
        assert w._expr(expr) == "x"

    def test_system_flag_first_scan(self):
        w = _make_writer()
        expr = SystemFlagExpr(flag=SystemFlag.FIRST_SCAN)
        assert w._expr(expr) == "first_scan()"

    def test_bit_access(self):
        w = _make_writer(self_vars={"status"})
        expr = BitAccessExpr(
            target=VariableRef(name="status"),
            bit_index=5,
        )
        assert w._expr(expr) == "self.status.bit5"

    def test_bit_access_dynamic(self):
        w = _make_writer(self_vars={"status"})
        expr = BitAccessExpr(
            target=VariableRef(name="status"),
            bit_index=VariableRef(name="idx"),
        )
        assert w._expr(expr) == "self.status.bit[idx]"

    def test_shift_ops(self):
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.SHL,
            left=VariableRef(name="x"),
            right=LiteralExpr(value="2"),
        )
        assert w._expr(expr) == "SHL(x, 2)"

    def test_named_args(self):
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="CUSTOM_FUNC",
            args=[CallArg(name="IN", value=LiteralExpr(value="42"))],
        )
        assert w._expr(expr) == "CUSTOM_FUNC(IN=42)"


# ===========================================================================
# Statements
# ===========================================================================

class TestStatements:
    def test_assignment(self):
        w = _make_writer(self_vars={"x"})
        stmt = Assignment(
            target=VariableRef(name="x"),
            value=LiteralExpr(value="42"),
        )
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "self.x = 42"

    def test_if_simple(self):
        w = _make_writer(self_vars={"flag", "out"})
        stmt = IfStatement(
            if_branch={"condition": VariableRef(name="flag"), "body": [
                Assignment(target=VariableRef(name="out"), value=LiteralExpr(value="TRUE")),
            ]},
        )
        out = w.getvalue().strip() if (w._write_stmt(stmt) or True) else ""
        out = w.getvalue().strip()
        lines = out.splitlines()
        assert lines[0] == "if self.flag:"
        assert lines[1].strip() == "self.out = True"

    def test_if_elif_else(self):
        w = _make_writer(self_vars={"x", "y"})
        stmt = IfStatement(
            if_branch={"condition": VariableRef(name="x"), "body": [
                Assignment(target=VariableRef(name="y"), value=LiteralExpr(value="1")),
            ]},
            elsif_branches=[{
                "condition": VariableRef(name="y"),
                "body": [Assignment(target=VariableRef(name="y"), value=LiteralExpr(value="2"))],
            }],
            else_body=[Assignment(target=VariableRef(name="y"), value=LiteralExpr(value="3"))],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "if self.x:" in out
        assert "elif self.y:" in out
        assert "else:" in out

    def test_for(self):
        w = _make_writer()
        stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[EmptyStatement()],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "for i in range(0, 10):" in out

    def test_while(self):
        w = _make_writer(self_vars={"running"})
        stmt = WhileStatement(
            condition=VariableRef(name="running"),
            body=[EmptyStatement()],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "while self.running:" in out

    def test_repeat(self):
        w = _make_writer(self_vars={"done"})
        stmt = RepeatStatement(
            body=[EmptyStatement()],
            until=VariableRef(name="done"),
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "while True:" in out
        assert "if self.done:" in out
        assert "break" in out

    def test_case_as_match(self):
        w = _make_writer(self_vars={"state"})
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(values=[0], body=[EmptyStatement()]),
                CaseBranch(values=[1], body=[EmptyStatement()]),
            ],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "match self.state:" in out
        assert "case 0:" in out
        assert "case 1:" in out

    def test_case_with_ranges_as_if(self):
        w = _make_writer(self_vars={"val"})
        stmt = CaseStatement(
            selector=VariableRef(name="val"),
            branches=[
                CaseBranch(values=[0], body=[EmptyStatement()]),
                CaseBranch(ranges=[CaseRange(start=10, end=20)], body=[EmptyStatement()]),
            ],
            else_body=[EmptyStatement()],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "if self.val == 0:" in out
        assert "elif 10 <= self.val <= 20:" in out
        assert "else:" in out

    def test_fb_invocation(self):
        w = _make_writer(self_vars={"my_ton", "output"})
        stmt = FBInvocation(
            instance_name="my_ton",
            fb_type="TON",
            inputs={"IN": VariableRef(name="output"), "PT": LiteralExpr(value="T#100ms")},
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "self.my_ton(IN=self.output, PT=timedelta(milliseconds=100))" in out

    def test_fb_invocation_with_outputs(self):
        w = _make_writer(self_vars={"timer", "done"})
        stmt = FBInvocation(
            instance_name="timer",
            fb_type="TON",
            inputs={"IN": LiteralExpr(value="TRUE")},
            outputs={"Q": VariableRef(name="done")},
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "self.timer(IN=True)" in out
        assert "self.done = self.timer.Q" in out

    def test_function_call_stmt(self):
        w = _make_writer()
        stmt = FunctionCallStatement(
            function_name="ABS",
            args=[CallArg(value=LiteralExpr(value="42"))],
        )
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "abs(42)"

    def test_function_call_stmt_positional_after_named(self):
        """ST allows positional args after named — Python does not.

        MoveRelative(Distance := Length, FALSE)
        must emit: MoveRelative(False, Distance=Length)
        """
        w = _make_writer()
        stmt = FunctionCallStatement(
            function_name="MoveRelative",
            args=[
                CallArg(name="Distance", value=VariableRef(name="Length")),
                CallArg(value=LiteralExpr(value="FALSE")),
            ],
        )
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "MoveRelative(False, Distance=Length)"

    def test_function_call_expr_positional_after_named(self):
        """Same reordering for function call expressions."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="Compute",
            args=[
                CallArg(name="X", value=LiteralExpr(value="1")),
                CallArg(name="Y", value=LiteralExpr(value="2")),
                CallArg(value=LiteralExpr(value="3")),
            ],
        )
        assert w._expr(expr) == "Compute(3, X=1, Y=2)"

    def test_function_call_all_positional_unchanged(self):
        """All positional args should remain in original order."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="ADD",
            args=[
                CallArg(value=VariableRef(name="a")),
                CallArg(value=VariableRef(name="b")),
                CallArg(value=VariableRef(name="c")),
            ],
        )
        assert w._expr(expr) == "ADD(a, b, c)"

    def test_function_call_all_named_unchanged(self):
        """All named args should remain in original order."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="Move",
            args=[
                CallArg(name="X", value=LiteralExpr(value="1")),
                CallArg(name="Y", value=LiteralExpr(value="2")),
            ],
        )
        assert w._expr(expr) == "Move(X=1, Y=2)"

    def test_return(self):
        w = _make_writer()
        stmt = ReturnStatement(value=LiteralExpr(value="42"))
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "return 42"

    def test_return_no_value(self):
        w = _make_writer()
        stmt = ReturnStatement()
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "return"

    def test_exit(self):
        w = _make_writer()
        stmt = ExitStatement()
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "break"

    def test_continue(self):
        w = _make_writer()
        stmt = ContinueStatement()
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "continue"

    def test_empty(self):
        w = _make_writer()
        stmt = EmptyStatement()
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "pass"

    def test_case_multiple_values(self):
        w = _make_writer(self_vars={"state"})
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(values=[1, 2, 3], body=[EmptyStatement()]),
            ],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "case 1 | 2 | 3:" in out

    def test_case_else(self):
        w = _make_writer(self_vars={"state"})
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(values=[0], body=[EmptyStatement()]),
            ],
            else_body=[EmptyStatement()],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "case _:" in out


# ===========================================================================
# Type definitions
# ===========================================================================

class TestTypeDefinitions:
    def test_struct(self):
        td = StructType(
            name="MotorData",
            members=[
                StructMember(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                StructMember(name="running", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), initial_value="FALSE"),
            ],
        )
        w = _make_writer()
        w._write_type_definition(td)
        out = w.getvalue().strip()
        assert "@struct" in out
        assert "class MotorData:" in out
        assert "speed: real" in out
        assert "running: bool = False" in out

    def test_enum(self):
        td = EnumType(
            name="MachineState",
            members=[
                EnumMember(name="IDLE", value=0),
                EnumMember(name="RUNNING", value=1),
                EnumMember(name="ERROR", value=2),
            ],
        )
        w = _make_writer()
        w._write_type_definition(td)
        out = w.getvalue().strip()
        assert "@enumeration" in out
        assert "class MachineState:" in out
        assert "IDLE = 0" in out
        assert "RUNNING = 1" in out

    def test_enum_with_base_type(self):
        td = EnumType(
            name="SmallEnum",
            base_type=PrimitiveType.DINT,
            members=[EnumMember(name="A", value=0)],
        )
        w = _make_writer()
        w._write_type_definition(td)
        out = w.getvalue().strip()
        assert "@enumeration(base_type=DINT)" in out

    def test_union_commented(self):
        td = UnionType(
            name="MyUnion",
            members=[
                StructMember(name="i", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
            ],
        )
        w = _make_writer()
        w._write_type_definition(td)
        out = w.getvalue().strip()
        assert "# UnionType 'MyUnion'" in out

    def test_alias_commented(self):
        td = AliasType(
            name="MyAlias",
            base_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        w = _make_writer()
        w._write_type_definition(td)
        out = w.getvalue().strip()
        assert "# AliasType 'MyAlias'" in out

    def test_subrange_commented(self):
        td = SubrangeType(
            name="Percent",
            base_type=PrimitiveType.INT,
            lower_bound=0,
            upper_bound=100,
        )
        w = _make_writer()
        w._write_type_definition(td)
        out = w.getvalue().strip()
        assert "# SubrangeType 'Percent'" in out


# ===========================================================================
# Global variable lists
# ===========================================================================

class TestGlobalVarLists:
    def test_simple_gvl(self):
        gvl = GlobalVariableList(
            name="SystemIO",
            variables=[
                Variable(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL), initial_value="0.0"),
                Variable(name="running", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ],
        )
        w = _make_writer()
        w._write_global_variable_list(gvl)
        out = w.getvalue().strip()
        assert "@global_vars" in out
        assert "class SystemIO:" in out
        assert "speed: real = 0.0" in out
        assert "running: bool" in out

    def test_gvl_with_complex_vars(self):
        gvl = GlobalVariableList(
            name="HardwareIO",
            variables=[
                Variable(
                    name="valve",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
                    retain=True,
                ),
            ],
        )
        w = _make_writer()
        w._write_global_variable_list(gvl)
        out = w.getvalue().strip()
        assert "valve: bool = Field(retain=True)" in out

    def test_gvl_with_description(self):
        gvl = GlobalVariableList(
            name="SystemVars",
            description="System variables",
            variables=[],
        )
        w = _make_writer()
        w._write_global_variable_list(gvl)
        out = w.getvalue().strip()
        assert '@global_vars(description="System variables")' in out

    def test_gvl_header_comment(self):
        gvl = GlobalVariableList(
            name="IO",
            variables=[
                Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
            ],
            metadata={"header_comment": "Hardware I/O mapping"},
        )
        w = _make_writer()
        w._write_global_variable_list(gvl)
        out = w.getvalue()
        lines = out.strip().splitlines()
        assert lines[0] == "# Hardware I/O mapping"
        assert lines[1] == "@global_vars"


# ===========================================================================
# POU emission
# ===========================================================================

class TestPOUEmission:
    def test_simple_fb(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="SimpleFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                output_vars=[Variable(name="valve", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=VariableRef(name="sensor"),
                ),
            ])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@fb" in out
        assert "class SimpleFB:" in out
        assert "sensor: Input[bool]" in out
        assert "valve: Output[bool]" in out
        assert "def logic(self):" in out
        assert "self.valve = self.sensor" in out

    def test_program(self):
        pou = POU(
            pou_type=POUType.PROGRAM,
            name="Main",
            interface=POUInterface(
                input_vars=[Variable(name="start", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@program" in out
        assert "class Main:" in out

    def test_function_with_return_type(self):
        pou = POU(
            pou_type=POUType.FUNCTION,
            name="AddOne",
            return_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            interface=POUInterface(
                input_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            networks=[Network(statements=[
                ReturnStatement(value=BinaryExpr(
                    op=BinaryOp.ADD,
                    left=VariableRef(name="x"),
                    right=LiteralExpr(value="1.0"),
                )),
            ])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@function" in out
        assert "def logic(self) -> real:" in out
        assert "return self.x + 1.0" in out

    def test_fb_extends(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Derived",
            extends="BaseFB",
            interface=POUInterface(),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "class Derived(BaseFB):" in out

    def test_standard_fb_shorthand(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TimerFB",
            interface=POUInterface(
                static_vars=[
                    Variable(name="timer", data_type=NamedTypeRef(name="TON")),
                ],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "timer: ton" in out

    def test_method(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="WithMethod",
            interface=POUInterface(),
            methods=[
                Method(
                    name="Calculate",
                    return_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    interface=POUInterface(
                        input_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
                    ),
                    networks=[Network(statements=[
                        ReturnStatement(value=VariableRef(name="x")),
                    ])],
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@fb_method" in out
        assert "def Calculate(self, x: real) -> real:" in out

    def test_private_method(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="WithPrivate",
            interface=POUInterface(),
            methods=[
                Method(
                    name="Internal",
                    access=AccessSpecifier.PRIVATE,
                    interface=POUInterface(),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@fb_method(access=AccessSpecifier.PRIVATE)" in out

    def test_network_comments(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Commented",
            interface=POUInterface(),
            networks=[
                Network(comment="First section", statements=[EmptyStatement()]),
                Network(comment="Second section", statements=[EmptyStatement()]),
            ],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "# First section" in out
        assert "# Second section" in out

    def test_empty_logic(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="EmptyFB",
            interface=POUInterface(),
            networks=[],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "def logic(self):" in out
        assert "pass" in out

    def test_header_comment(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Documented",
            interface=POUInterface(),
            networks=[Network(statements=[EmptyStatement()])],
            metadata={"header_comment": "Motor drive controller\nAuthor: J. Doe"},
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        lines = out.strip().splitlines()
        assert lines[0] == "# Motor drive controller"
        assert lines[1] == "# Author: J. Doe"
        assert lines[2] == "@fb"

    def test_header_comment_sfc(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="SeqWithComment",
            interface=POUInterface(),
            sfc_body=SFCBody(
                steps=[Step(name="IDLE", is_initial=True)],
                transitions=[],
            ),
            metadata={"header_comment": "Sequence controller"},
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        lines = out.strip().splitlines()
        assert lines[0] == "# Sequence controller"
        assert lines[1] == "@sfc"


# ===========================================================================
# SFC emission
# ===========================================================================

class TestSFCEmission:
    def test_basic_sfc(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FillSequence",
            interface=POUInterface(
                output_vars=[Variable(name="valve", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
            ),
            sfc_body=SFCBody(
                steps=[
                    Step(
                        name="IDLE",
                        is_initial=True,
                        actions=[Action(
                            name="idle_action",
                            body=[Assignment(
                                target=VariableRef(name="valve"),
                                value=LiteralExpr(value="FALSE"),
                            )],
                        )],
                    ),
                    Step(name="FILLING"),
                ],
                transitions=[
                    Transition(
                        source_steps=["IDLE"],
                        target_steps=["FILLING"],
                        condition=VariableRef(name="start_cmd"),
                    ),
                ],
            ),
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@sfc" in out
        assert "class FillSequence:" in out
        assert "IDLE = step(initial=True)" in out
        assert "FILLING = step()" in out
        assert "@IDLE.action" in out
        assert "def idle_action(self):" in out
        assert "@transition(IDLE >> FILLING)" in out

    def test_sfc_entry_exit_actions(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="WithEntryExit",
            interface=POUInterface(),
            sfc_body=SFCBody(
                steps=[
                    Step(
                        name="ACTIVE",
                        is_initial=True,
                        entry_actions=[Action(name="on_enter", qualifier="P1", body=[EmptyStatement()])],
                        exit_actions=[Action(name="on_exit", qualifier="P0", body=[EmptyStatement()])],
                    ),
                ],
                transitions=[],
            ),
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@ACTIVE.entry" in out
        assert "def on_enter(self):" in out
        assert "@ACTIVE.exit" in out
        assert "def on_exit(self):" in out

    def test_sfc_parallel_transition(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Parallel",
            interface=POUInterface(),
            sfc_body=SFCBody(
                steps=[
                    Step(name="START", is_initial=True),
                    Step(name="A"),
                    Step(name="B"),
                ],
                transitions=[
                    Transition(
                        source_steps=["START"],
                        target_steps=["A", "B"],
                        condition=LiteralExpr(value="TRUE"),
                    ),
                ],
            ),
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue().strip()
        assert "@transition(START >> (A & B))" in out


# ===========================================================================
# Full project generation
# ===========================================================================

class TestFullProject:
    def test_empty_project(self):
        proj = Project(name="Empty")
        out = generate(proj)
        assert "from plx.framework import *" in out
        assert 'project("Empty"' in out
        assert "pous=[" in out

    def test_project_with_pou(self):
        proj = Project(
            name="TestProj",
            pous=[
                POU(
                    pou_type=POUType.FUNCTION_BLOCK,
                    name="Motor",
                    interface=POUInterface(
                        input_vars=[Variable(name="cmd", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                        output_vars=[Variable(name="run", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                    ),
                    networks=[Network(statements=[
                        Assignment(
                            target=VariableRef(name="run"),
                            value=VariableRef(name="cmd"),
                        ),
                    ])],
                ),
            ],
        )
        out = generate(proj)
        assert "from plx.framework import *" in out
        assert "@fb" in out
        assert "class Motor:" in out
        assert "pous=[" in out

    def test_project_with_tasks(self):
        proj = Project(
            name="TaskProj",
            pous=[
                POU(
                    pou_type=POUType.PROGRAM,
                    name="Main",
                    interface=POUInterface(),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
            tasks=[
                PeriodicTask(
                    name="MainTask",
                    interval="T#10ms",
                    priority=1,
                    assigned_pous=["Main"],
                ),
            ],
        )
        out = generate(proj)
        assert 'MainTask = task("MainTask"' in out
        assert "periodic=timedelta(milliseconds=10)" in out
        assert "pous=[Main]" in out
        assert "priority=1" in out

    def test_project_with_data_types(self):
        proj = Project(
            name="TypeProj",
            data_types=[
                StructType(
                    name="SensorData",
                    members=[
                        StructMember(name="value", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                    ],
                ),
                EnumType(
                    name="State",
                    members=[
                        EnumMember(name="OFF", value=0),
                        EnumMember(name="ON", value=1),
                    ],
                ),
            ],
            pous=[],
        )
        out = generate(proj)
        assert "@struct" in out
        assert "class SensorData:" in out
        assert "@enumeration" in out
        assert "class State:" in out
        assert "pous=[" in out

    def test_project_with_global_vars(self):
        proj = Project(
            name="GVLProj",
            global_variable_lists=[
                GlobalVariableList(
                    name="SystemIO",
                    variables=[
                        Variable(name="temp", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL), initial_value="0.0"),
                    ],
                ),
            ],
            pous=[],
        )
        out = generate(proj)
        assert "@global_vars" in out
        assert "class SystemIO:" in out
        assert "pous=[" in out

    def test_pou_ordering(self):
        """FUNCTIONs before FUNCTION_BLOCKs before PROGRAMs."""
        proj = Project(
            name="OrderTest",
            pous=[
                POU(pou_type=POUType.PROGRAM, name="Main",
                    interface=POUInterface(), networks=[Network(statements=[EmptyStatement()])]),
                POU(pou_type=POUType.FUNCTION, name="Calc",
                    return_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    interface=POUInterface(), networks=[Network(statements=[ReturnStatement(value=LiteralExpr(value="0.0"))])]),
                POU(pou_type=POUType.FUNCTION_BLOCK, name="Driver",
                    interface=POUInterface(), networks=[Network(statements=[EmptyStatement()])]),
            ],
        )
        out = generate(proj)
        # Function should appear before FB which should appear before Program
        calc_pos = out.index("class Calc:")
        driver_pos = out.index("class Driver:")
        main_pos = out.index("class Main:")
        assert calc_pos < driver_pos < main_pos

    def test_fb_topo_sort(self):
        """Derived FB should come after base FB."""
        proj = Project(
            name="InheritTest",
            pous=[
                POU(pou_type=POUType.FUNCTION_BLOCK, name="Derived",
                    extends="BaseFB",
                    interface=POUInterface(), networks=[Network(statements=[EmptyStatement()])]),
                POU(pou_type=POUType.FUNCTION_BLOCK, name="BaseFB",
                    interface=POUInterface(), networks=[Network(statements=[EmptyStatement()])]),
            ],
        )
        out = generate(proj)
        base_pos = out.index("class BaseFB:")
        derived_pos = out.index("class Derived(BaseFB):")
        assert base_pos < derived_pos

    def test_interface_as_code(self):
        proj = Project(
            name="IfaceProj",
            pous=[
                POU(pou_type=POUType.INTERFACE, name="IMotor",
                    interface=POUInterface(),
                    methods=[
                        Method(name="Start", interface=POUInterface()),
                    ]),
            ],
        )
        out = generate(proj)
        assert "@interface" in out
        assert "class IMotor:" in out
        assert "def Start(self): ..." in out


# ===========================================================================
# Round-trip test: framework → IR → generate → compile → compare IR
# ===========================================================================

class TestRoundTrip:
    def test_simple_fb_round_trip(self):
        """Compile framework → IR → generate Python → verify it's valid Python."""
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import BOOL

        @fb
        class RoundTripFB:
            sensor: Input[bool]
            valve: Output[bool]

            def logic(self):
                self.valve = self.sensor

        pou_ir = RoundTripFB.compile()
        proj_ir = Project(name="RTTest", pous=[pou_ir])
        code = generate(proj_ir)

        # Verify the generated code is valid Python (can be parsed)
        compile(code, "<generated>", "exec")

        # Verify key elements
        assert "class RoundTripFB:" in code
        assert "sensor: Input[bool]" in code
        assert "valve: Output[bool]" in code
        assert "self.valve = self.sensor" in code

    def test_function_round_trip(self):
        from plx.framework._decorators import function
        from plx.framework._descriptors import Input
        from plx.framework._plc_types import real

        @function
        class AddOne:
            x: Input[real]

            def logic(self) -> real:
                return self.x + 1.0

        pou_ir = AddOne.compile()
        proj_ir = Project(name="FuncRT", pous=[pou_ir])
        code = generate(proj_ir)

        compile(code, "<generated>", "exec")
        assert "def logic(self) -> real:" in code

    def test_if_else_round_trip(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import BOOL, DINT

        @fb
        class IfElseFB:
            enable: Input[bool]
            count: Output[DINT]

            def logic(self):
                if self.enable:
                    self.count = 1
                else:
                    self.count = 0

        pou_ir = IfElseFB.compile()
        proj_ir = Project(name="IfElseRT", pous=[pou_ir])
        code = generate(proj_ir)
        compile(code, "<generated>", "exec")

        assert "if self.enable:" in code
        assert "else:" in code

    def test_for_loop_round_trip(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Output
        from plx.framework._types import DINT

        @fb
        class ForLoopFB:
            total: Output[DINT]

            def logic(self):
                for i in range(0, 10):
                    self.total = self.total + 1

        pou_ir = ForLoopFB.compile()
        proj_ir = Project(name="ForRT", pous=[pou_ir])
        code = generate(proj_ir)
        compile(code, "<generated>", "exec")
        assert "for i in range(" in code

    def test_data_types_round_trip(self):
        from plx.framework._data_types import enumeration, struct
        from plx.framework._plc_types import real

        @struct
        class MotorData:
            speed: real
            running: bool = False

        @enumeration
        class Mode:
            OFF = 0
            ON = 1

        proj_ir = Project(
            name="DTTest",
            data_types=[MotorData.compile(), Mode.compile()],
        )
        code = generate(proj_ir)
        compile(code, "<generated>", "exec")

        assert "class MotorData:" in code
        assert "speed: real" in code
        assert "class Mode:" in code

    def test_global_vars_round_trip(self):
        from plx.framework._global_vars import global_vars
        from plx.framework._plc_types import real

        @global_vars
        class IO:
            speed: real = 0.0
            running: bool

        proj_ir = Project(
            name="GVLTest",
            global_variable_lists=[IO.compile()],
        )
        code = generate(proj_ir)
        compile(code, "<generated>", "exec")

        assert "class IO:" in code

    def test_project_assembly_round_trip(self):
        from plx.framework._decorators import fb, program
        from plx.framework._descriptors import Input, Output
        from plx.framework._project import project
        from plx.framework._task import task
        from datetime import timedelta
        from plx.framework._types import BOOL

        @fb
        class MotorCtrl:
            cmd: Input[bool]
            out: Output[bool]

            def logic(self):
                self.out = self.cmd

        @program
        class MainProg:
            def logic(self):
                pass

        t = task("Main", periodic=timedelta(milliseconds=10), pous=[MainProg], priority=1)
        p = project("TestApp", pous=[MotorCtrl, MainProg], tasks=[t])
        ir = p.compile()

        code = generate(ir)
        compile(code, "<generated>", "exec")

        assert 'project("TestApp"' in code
        assert "periodic=timedelta(milliseconds=10)" in code


# ===========================================================================
# Annotation syntax emission
# ===========================================================================

class TestAnnotationSyntaxEmission:
    def test_simple_fb_uses_annotation_syntax(self):
        """Variables without metadata should use annotation syntax."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="AnnotFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                output_vars=[Variable(name="valve", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                inout_vars=[Variable(name="ref", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
                static_vars=[Variable(name="count", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT), initial_value="0")],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "sensor: Input[bool]" in out
        assert "valve: Output[bool]" in out
        assert "ref: InOut[real]" in out
        assert "count: dint = 0" in out

    def test_metadata_uses_field_syntax(self):
        """Variables with description/retain should use annotation + Field() syntax."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MetaFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), description="Main sensor")],
                output_vars=[Variable(name="valve", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), retain=True)],
                static_vars=[Variable(name="count", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert 'sensor: Input[bool] = Field(description="Main sensor")' in out
        assert "valve: Output[bool] = Field(retain=True)" in out
        assert "count: dint" in out

    def test_hardware_metadata_emits_field(self):
        """Variables with hardware metadata should use Field() syntax."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="HardwareFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), metadata={"hardware": "input"})],
                output_vars=[Variable(name="motor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), metadata={"hardware": "output"})],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert 'sensor: Input[bool] = Field(hardware="input")' in out
        assert 'motor: Output[bool] = Field(hardware="output")' in out

    def test_external_readwrite_emits_true(self):
        """external="readwrite" should emit external=True in Field()."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="ExternalFB",
            interface=POUInterface(
                static_vars=[Variable(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL), metadata={"external": "readwrite"})],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "speed: real = Field(external=True)" in out

    def test_external_read_emits_string(self):
        """external="read" should emit external="read" in Field()."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="ReadOnlyFB",
            interface=POUInterface(
                static_vars=[Variable(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL), metadata={"external": "read"})],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert 'speed: real = Field(external="read")' in out

    def test_hardware_and_external_together(self):
        """Both hardware and external on the same variable."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FullFB",
            interface=POUInterface(
                output_vars=[Variable(name="motor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), metadata={"hardware": "output", "external": "readwrite"})],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert 'motor: Output[bool] = Field(hardware="output", external=True)' in out

    def test_gvl_hardware_metadata(self):
        """GVL variables with hardware metadata should use Field() syntax."""
        from plx.model.project import GlobalVariableList
        gvl = GlobalVariableList(
            name="IO",
            variables=[
                Variable(name="sensor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), metadata={"hardware": "input"}),
                Variable(name="motor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), metadata={"hardware": "output", "external": "readwrite"}),
                Variable(name="plain", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT)),
            ],
        )
        w = _make_writer()
        w._write_global_variable_list(gvl)
        out = w.getvalue()
        assert 'sensor: bool = Field(hardware="input")' in out
        assert 'motor: bool = Field(hardware="output", external=True)' in out
        assert "plain: dint" in out

    def test_standard_fb_shorthand_preserved(self):
        """Standard FB types (TON, etc.) should still use annotation shorthand."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TimerFB",
            interface=POUInterface(
                static_vars=[Variable(name="timer", data_type=NamedTypeRef(name="TON"))],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "timer: ton" in out

    def test_static_var_no_initial_uses_annotation(self):
        """Static var without initial value uses bare annotation."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="BareStaticFB",
            interface=POUInterface(
                static_vars=[Variable(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "speed: real" in out

    def test_input_with_initial_value(self):
        """Input var with initial value uses annotation syntax with default."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="InitInputFB",
            interface=POUInterface(
                input_vars=[Variable(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL), initial_value="100.0")],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "speed: Input[real] = 100.0" in out

    def test_constant_simple_uses_field(self):
        """Constant var with just initial value uses Field(constant=True)."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="ConstFB",
            interface=POUInterface(
                constant_vars=[
                    Variable(name="SEALER_ALARM_COUNT", data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
                             initial_value="6", constant=True),
                ],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "SEALER_ALARM_COUNT: int = Field(initial=6, constant=True)" in out

    def test_constant_with_description_uses_field(self):
        """Constant with description uses Field() with constant=True."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="ConstDescFB",
            interface=POUInterface(
                constant_vars=[
                    Variable(name="FAULTID", data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
                             initial_value="1", description="Fault number", constant=True),
                ],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert 'FAULTID: int = Field(initial=1, description="Fault number", constant=True)' in out

    def test_constant_bare_no_initial(self):
        """Constant without initial value uses Field(constant=True)."""
        w = _make_writer()
        w._self_vars = set()
        v = Variable(name="MAX", data_type=PrimitiveTypeRef(type=PrimitiveType.INT), constant=True)
        w._write_static_var(v)
        out = w.getvalue().strip()
        assert out == "MAX: int = Field(constant=True)"

    def test_static_constant_flag_preserved(self):
        """Static var with constant=True emits the flag in Field()."""
        w = _make_writer()
        w._self_vars = set()
        v = Variable(name="PI", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                     initial_value="3.14", constant=True)
        w._write_static_var(v)
        out = w.getvalue().strip()
        assert "constant=True" in out


# ===========================================================================
# Multi-file generation
# ===========================================================================

class TestGenerateFiles:
    def test_empty_project(self):
        proj = Project(name="Empty")
        files = generate_files(proj)
        assert "project.py" in files
        assert 'project("Empty"' in files["project.py"]
        assert "pous=[" in files["project.py"]

    def test_one_file_per_pou(self):
        proj = Project(
            name="MultiFile",
            pous=[
                POU(
                    pou_type=POUType.FUNCTION_BLOCK,
                    name="Motor",
                    interface=POUInterface(
                        input_vars=[Variable(name="cmd", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                        output_vars=[Variable(name="run", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                    ),
                    networks=[Network(statements=[
                        Assignment(target=VariableRef(name="run"), value=VariableRef(name="cmd")),
                    ])],
                ),
                POU(
                    pou_type=POUType.PROGRAM,
                    name="Main",
                    interface=POUInterface(),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
        )
        files = generate_files(proj)
        assert "Motor.py" in files
        assert "Main.py" in files
        assert "project.py" in files

        # Each POU file has its own import
        assert "from plx.framework import *" in files["Motor.py"]
        assert "class Motor:" in files["Motor.py"]
        assert "from plx.framework import *" in files["Main.py"]
        assert "class Main:" in files["Main.py"]

        # project.py uses packages discovery, no explicit imports
        assert "pous=[" in files["project.py"]

    def test_one_file_per_data_type(self):
        proj = Project(
            name="TypeFiles",
            data_types=[
                StructType(name="SensorData", members=[
                    StructMember(name="value", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                ]),
                EnumType(name="State", members=[
                    EnumMember(name="OFF", value=0),
                    EnumMember(name="ON", value=1),
                ]),
            ],
            pous=[],
        )
        files = generate_files(proj)
        assert "SensorData.py" in files
        assert "State.py" in files
        assert "@struct" in files["SensorData.py"]
        assert "@enumeration" in files["State.py"]

        # project.py uses packages discovery
        assert "pous=[" in files["project.py"]

    def test_one_file_per_gvl(self):
        proj = Project(
            name="GVLFiles",
            global_variable_lists=[
                GlobalVariableList(
                    name="SystemIO",
                    variables=[
                        Variable(name="temp", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                    ],
                ),
            ],
            pous=[],
        )
        files = generate_files(proj)
        assert "SystemIO.py" in files
        assert "@global_vars" in files["SystemIO.py"]
        # project.py uses packages discovery
        assert "pous=[" in files["project.py"]

    def test_pou_imports_data_type_dep(self):
        """A POU that references a struct type should import it."""
        proj = Project(
            name="DepTest",
            data_types=[
                StructType(name="MotorData", members=[
                    StructMember(name="speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL)),
                ]),
            ],
            pous=[
                POU(
                    pou_type=POUType.FUNCTION_BLOCK,
                    name="Controller",
                    interface=POUInterface(
                        static_vars=[Variable(name="data", data_type=NamedTypeRef(name="MotorData"))],
                    ),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
        )
        files = generate_files(proj)
        assert "from MotorData import MotorData" in files["Controller.py"]

    def test_extends_dep_imported(self):
        """A derived FB should import its base."""
        proj = Project(
            name="InheritFiles",
            pous=[
                POU(pou_type=POUType.FUNCTION_BLOCK, name="BaseFB",
                    interface=POUInterface(),
                    networks=[Network(statements=[EmptyStatement()])]),
                POU(pou_type=POUType.FUNCTION_BLOCK, name="Derived",
                    extends="BaseFB",
                    interface=POUInterface(),
                    networks=[Network(statements=[EmptyStatement()])]),
            ],
        )
        files = generate_files(proj)
        assert "from BaseFB import BaseFB" in files["Derived.py"]

    def test_standard_fb_not_imported(self):
        """Standard FB types like TON should NOT be imported from sibling files."""
        proj = Project(
            name="StdFBTest",
            pous=[
                POU(
                    pou_type=POUType.FUNCTION_BLOCK,
                    name="TimerFB",
                    interface=POUInterface(
                        static_vars=[Variable(name="t", data_type=NamedTypeRef(name="TON"))],
                    ),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
        )
        files = generate_files(proj)
        assert "from .TON" not in files["TimerFB.py"]

    def test_each_file_is_valid_python(self):
        """All generated files should be parseable Python."""
        proj = Project(
            name="ValidPy",
            data_types=[
                StructType(name="Cfg", members=[
                    StructMember(name="val", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                ]),
            ],
            global_variable_lists=[
                GlobalVariableList(name="Globals", variables=[
                    Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
                ]),
            ],
            pous=[
                POU(
                    pou_type=POUType.FUNCTION_BLOCK,
                    name="FB1",
                    interface=POUInterface(
                        input_vars=[Variable(name="a", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))],
                    ),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
        )
        files = generate_files(proj)
        for fname, code in files.items():
            compile(code, f"<{fname}>", "exec")


# ===========================================================================
# Property export
# ===========================================================================

class TestPropertyExport:
    def test_property_getter_only(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            interface=POUInterface(
                static_vars=[Variable(name="_speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            ReturnStatement(value=VariableRef(name="_speed")),
                        ])],
                    ),
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        code = generate(Project(name="Test", pous=[pou]))
        assert "@fb_property(real)" in code
        assert "def speed(self):" in code
        assert "return self._speed" in code
        assert "@speed.setter" not in code

    def test_property_getter_setter(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Tank",
            interface=POUInterface(
                static_vars=[Variable(name="_level", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            properties=[
                Property(
                    name="level",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            ReturnStatement(value=VariableRef(name="_level")),
                        ])],
                    ),
                    setter=PropertyAccessor(
                        networks=[Network(statements=[
                            Assignment(
                                target=VariableRef(name="_level"),
                                value=VariableRef(name="level"),
                            ),
                        ])],
                    ),
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        code = generate(Project(name="Test", pous=[pou]))
        assert "@fb_property(real)" in code
        assert "def level(self):" in code
        assert "@level.setter" in code
        assert "def level(self, level: real):" in code

    def test_property_abstract(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Base",
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    abstract=True,
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        code = generate(Project(name="Test", pous=[pou]))
        assert "abstract=True" in code
        assert "def speed(self):" in code
        assert "pass" in code

    def test_property_access_and_final(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Sealed",
            interface=POUInterface(
                static_vars=[Variable(name="_val", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            properties=[
                Property(
                    name="value",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    access=AccessSpecifier.PROTECTED,
                    final=True,
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            ReturnStatement(value=VariableRef(name="_val")),
                        ])],
                    ),
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        code = generate(Project(name="Test", pous=[pou]))
        assert "access=AccessSpecifier.PROTECTED" in code
        assert "final=True" in code


# ===========================================================================
# Interface export
# ===========================================================================

class TestInterfaceExport:
    def test_interface_export(self):
        pou = POU(
            pou_type=POUType.INTERFACE,
            name="IMoveable",
            methods=[
                Method(
                    name="move_to",
                    return_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
                    interface=POUInterface(
                        input_vars=[Variable(name="target", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
                    ),
                ),
            ],
            properties=[
                Property(
                    name="position",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                ),
            ],
        )
        code = generate(Project(name="Test", pous=[pou]))
        assert "@interface" in code
        assert "class IMoveable:" in code
        assert "@fb_method" in code
        assert "def move_to(self, target: real) -> bool: ..." in code
        assert "@fb_property(real)" in code
        assert "def position(self): ..." in code

    def test_interface_extends(self):
        base = POU(
            pou_type=POUType.INTERFACE,
            name="IBase",
            methods=[
                Method(name="reset", interface=POUInterface()),
            ],
        )
        derived = POU(
            pou_type=POUType.INTERFACE,
            name="IDerived",
            extends="IBase",
            methods=[
                Method(name="run", interface=POUInterface()),
            ],
        )
        code = generate(Project(name="Test", pous=[base, derived]))
        assert "class IDerived(IBase):" in code

    def test_interface_import_in_generate_files(self):
        iface = POU(
            pou_type=POUType.INTERFACE,
            name="IMoveable",
            methods=[
                Method(name="move", interface=POUInterface()),
            ],
        )
        fb_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            implements=["IMoveable"],
            networks=[Network(statements=[EmptyStatement()])],
        )
        proj = Project(name="Test", pous=[iface, fb_pou])
        files = generate_files(proj)
        # project.py uses packages discovery
        assert "pous=[" in files["project.py"]
        # FB should import the interface it implements
        assert "from IMoveable import IMoveable" in files["Motor.py"]


# ===========================================================================
# Type conversion export
# ===========================================================================

class TestTypeConversionExport:
    """Type conversions are implicit in Python — the py exporter strips them."""

    def test_primitive_cast_stripped(self):
        """Simple primitive cast REAL(x) exports as just x."""
        w = _make_writer()
        for prim in [PrimitiveType.INT, PrimitiveType.SINT, PrimitiveType.LREAL,
                      PrimitiveType.UINT, PrimitiveType.UDINT, PrimitiveType.LINT,
                      PrimitiveType.BOOL, PrimitiveType.DINT, PrimitiveType.REAL]:
            expr = TypeConversionExpr(
                target_type=PrimitiveTypeRef(type=prim),
                source=VariableRef(name="x"),
            )
            assert w._expr(expr) == "x", f"Failed for {prim}"

    def test_explicit_conversion_stripped(self):
        """LREAL_TO_DINT(x) (with source_type set) exports as just x."""
        w = _make_writer()
        expr = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
            source=VariableRef(name="timeToUpdate"),
            source_type=PrimitiveTypeRef(type=PrimitiveType.LREAL),
        )
        assert w._expr(expr) == "timeToUpdate"

    def test_nested_conversions_stripped(self):
        """Nested DINT_TO_REAL(BOOL_TO_INT(x)) exports as just x."""
        w = _make_writer()
        inner = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            source=VariableRef(name="x"),
            source_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
        )
        outer = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            source=inner,
            source_type=PrimitiveTypeRef(type=PrimitiveType.INT),
        )
        assert w._expr(outer) == "x"

    def test_string_conversion_stripped(self):
        """DINT_TO_STRING(x) also exports as just x (implicit in Python)."""
        w = _make_writer()
        expr = TypeConversionExpr(
            target_type=StringTypeRef(),
            source=VariableRef(name="count"),
            source_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        assert w._expr(expr) == "count"

    def test_named_type_conversion_stripped(self):
        """Conversion targeting a named type exports as just x."""
        w = _make_writer()
        expr = TypeConversionExpr(
            target_type=NamedTypeRef(name="E_PackMode"),
            source=VariableRef(name="modeInt"),
        )
        assert w._expr(expr) == "modeInt"

    def test_conversion_in_binary_expr(self):
        """Type conversion inside a binary expression is transparent."""
        w = _make_writer()
        conv = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
            source=VariableRef(name="val"),
            source_type=PrimitiveTypeRef(type=PrimitiveType.LREAL),
        )
        expr = BinaryExpr(op=BinaryOp.ADD, left=VariableRef(name="total"), right=conv)
        assert w._expr(expr) == "total + val"


# ===========================================================================
# Round-trip fidelity fixes
# ===========================================================================

class TestRoundTripFixes:
    def test_access_specifier_in_method_export(self):
        """AccessSpecifier.PRIVATE in method export produces importable code."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(),
            methods=[
                Method(
                    name="Internal",
                    access=AccessSpecifier.PRIVATE,
                    interface=POUInterface(),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "@fb_method(access=AccessSpecifier.PRIVATE)" in out
        # Verify AccessSpecifier is importable from framework
        from plx.framework import AccessSpecifier as AS
        assert AS.PRIVATE is not None

    def test_enum_auto_values(self):
        """EnumMember with value=None emits integer, not auto()."""
        td = EnumType(
            name="Color",
            members=[
                EnumMember(name="RED"),
                EnumMember(name="GREEN"),
                EnumMember(name="BLUE"),
            ],
        )
        w = _make_writer()
        w._write_enum(td)
        out = w.getvalue()
        assert "auto()" not in out
        assert "RED = 0" in out
        assert "GREEN = 1" in out
        assert "BLUE = 2" in out

    def test_enum_auto_values_with_gaps(self):
        """EnumMember with mixed explicit/None values auto-increments correctly."""
        td = EnumType(
            name="Status",
            members=[
                EnumMember(name="OFF", value=0),
                EnumMember(name="STARTING"),
                EnumMember(name="RUNNING", value=10),
                EnumMember(name="STOPPING"),
            ],
        )
        w = _make_writer()
        w._write_enum(td)
        out = w.getvalue()
        assert "OFF = 0" in out
        assert "STARTING = 1" in out
        assert "RUNNING = 10" in out
        assert "STOPPING = 11" in out

    def test_fb_invocation_expression_instance_no_double_self(self):
        """Expression instance_name doesn't get double self. prefix."""
        w = _make_writer(self_vars={"arr"})
        stmt = FBInvocation(
            instance_name=ArrayAccessExpr(
                array=VariableRef(name="arr"),
                indices=[LiteralExpr(value="0")],
            ),
            fb_type="TON",
            inputs={"IN": LiteralExpr(value="TRUE")},
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "self.arr[0](IN=True)" in out
        assert "self.self." not in out

    def test_external_var_gets_self_prefix(self):
        """External vars get self. prefix in generated logic."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(
                external_vars=[
                    Variable(name="gCounter", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT)),
                ],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="gCounter"),
                    value=LiteralExpr(value="42"),
                ),
            ])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "self.gCounter" in out


# ===========================================================================
# Regression tests for Beckhoff import code generation fixes
# ===========================================================================

class TestPropertyGetterReturn:
    """Property getter: assignment to property name becomes return statement."""

    def test_getter_assign_to_prop_name_becomes_return(self):
        """IEC pattern: PropName := value → return value."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            interface=POUInterface(
                static_vars=[Variable(name="_speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            properties=[
                Property(
                    name="Speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            Assignment(
                                target=VariableRef(name="Speed"),
                                value=VariableRef(name="_speed"),
                            ),
                        ])],
                    ),
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "return self._speed" in out
        assert "Speed = self._speed" not in out

    def test_getter_return_stmt_unchanged(self):
        """Explicit ReturnStatement in getter is preserved as-is."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            interface=POUInterface(
                static_vars=[Variable(name="_speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            properties=[
                Property(
                    name="Speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            ReturnStatement(value=VariableRef(name="_speed")),
                        ])],
                    ),
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "return self._speed" in out

    def test_setter_does_not_rewrite_assignment(self):
        """Setter assignments are normal assignments, NOT return statements."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Motor",
            interface=POUInterface(
                static_vars=[Variable(name="_speed", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
            ),
            properties=[
                Property(
                    name="Speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[Network(statements=[
                            Assignment(
                                target=VariableRef(name="Speed"),
                                value=VariableRef(name="_speed"),
                            ),
                        ])],
                    ),
                    setter=PropertyAccessor(
                        networks=[Network(statements=[
                            Assignment(
                                target=VariableRef(name="_speed"),
                                value=VariableRef(name="Speed"),
                            ),
                        ])],
                    ),
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        # Getter: return
        assert "return self._speed" in out
        # Setter: regular assignment (no return)
        assert "self._speed = Speed" in out


class TestSuperAndThisHandling:
    """SUPER^ and THIS^ → Python OOP syntax."""

    def test_super_function_call_stmt(self):
        """SUPER^.Method() → super().Method()."""
        w = _make_writer()
        stmt = FunctionCallStatement(function_name="SUPER^.CyclicLogic", args=[])
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert out == "super().CyclicLogic()"

    def test_super_function_call_with_args(self):
        """SUPER^.Method(arg) → super().Method(arg)."""
        w = _make_writer()
        stmt = FunctionCallStatement(
            function_name="SUPER^.Init",
            args=[CallArg(value=LiteralExpr(value="TRUE"))],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert out == "super().Init(True)"

    def test_super_in_expression(self):
        """SUPER^.Method() as expression → super().Method()."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="SUPER^.Initialize",
            args=[],
        )
        result = w._expr(expr)
        assert result == "super().Initialize()"

    def test_this_in_variable_ref(self):
        """THIS^ as variable ref → self."""
        w = _make_writer()
        expr = VariableRef(name="THIS^")
        result = w._expr(expr)
        assert result == "self"

    def test_this_member_access(self):
        """THIS^.member → self.member via MemberAccessExpr."""
        w = _make_writer()
        expr = MemberAccessExpr(
            struct=VariableRef(name="THIS^"),
            member="Output",
        )
        result = w._expr(expr)
        assert result == "self.Output"

    def test_this_function_call_stmt(self):
        """THIS^.Method() → self.Method()."""
        w = _make_writer()
        stmt = FunctionCallStatement(function_name="THIS^.Reset", args=[])
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert out == "self.Reset()"

    def test_super_variable_ref(self):
        """Bare SUPER^ → super()."""
        w = _make_writer()
        expr = VariableRef(name="SUPER^")
        result = w._expr(expr)
        assert result == "super()"

    def test_normal_function_call_not_affected(self):
        """Regular function calls are not affected by SUPER^/THIS^ handling."""
        w = _make_writer()
        stmt = FunctionCallStatement(function_name="ABS", args=[
            CallArg(value=LiteralExpr(value="42")),
        ])
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert out == "abs(42)"


class TestCaseEnumValues:
    """CASE branches with string enum references."""

    def test_case_with_enum_string_values(self):
        """Enum references in CASE branches preserve names."""
        w = _make_writer(self_vars={"mode"})
        stmt = CaseStatement(
            selector=VariableRef(name="mode"),
            branches=[
                CaseBranch(
                    values=["E_Mode.Production"],
                    body=[EmptyStatement()],
                ),
                CaseBranch(
                    values=["E_Mode.Manual", "E_Mode.Maintenance"],
                    body=[EmptyStatement()],
                ),
            ],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "case E_Mode.Production:" in out
        assert "case E_Mode.Manual | E_Mode.Maintenance:" in out

    def test_case_mixed_int_and_enum(self):
        """Mixed integer and enum values in CASE."""
        w = _make_writer(self_vars={"state"})
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(values=[0], body=[EmptyStatement()]),
                CaseBranch(values=["E_State.Running"], body=[EmptyStatement()]),
                CaseBranch(values=[5, 6], body=[EmptyStatement()]),
            ],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "case 0:" in out
        assert "case E_State.Running:" in out
        assert "case 5 | 6:" in out

    def test_case_enum_values_in_if_mode(self):
        """Enum values work in if/elif mode (ranges present)."""
        w = _make_writer(self_vars={"val"})
        stmt = CaseStatement(
            selector=VariableRef(name="val"),
            branches=[
                CaseBranch(values=["E_State.Idle"], body=[EmptyStatement()]),
                CaseBranch(
                    ranges=[CaseRange(start=10, end=20)],
                    body=[EmptyStatement()],
                ),
            ],
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "self.val == E_State.Idle" in out
        assert "10 <= self.val <= 20" in out


class TestArrayEmptyDimensions:
    """Variable-length arrays ARRAY[*] OF T."""

    def test_variable_length_array(self):
        """ARRAY[*] → ARRAY(elem) with no size."""
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=NamedTypeRef(name="SomeType"),
            dimensions=[DimensionRange(lower=0, upper=-1)],
        )
        result = w._type_ref(tr)
        assert result == "array(SomeType)"

    def test_normal_array_unchanged(self):
        """Normal arrays still emit size."""
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        result = w._type_ref(tr)
        assert result == "array(int, 10)"

    def test_explicit_bounds_unchanged(self):
        """ARRAY[1..10] emits explicit bounds."""
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            dimensions=[DimensionRange(lower=1, upper=10)],
        )
        result = w._type_ref(tr)
        assert result == "array(real, (1, 10))"


class TestInOutParamsInMethodSignature:
    """InOut params appear in method signature, not body."""

    def test_inout_in_signature(self):
        """VAR_IN_OUT params go in the method signature."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(),
            methods=[
                Method(
                    name="Process",
                    interface=POUInterface(
                        input_vars=[
                            Variable(name="cmd", data_type=PrimitiveTypeRef(type=PrimitiveType.INT)),
                        ],
                        inout_vars=[
                            Variable(name="buffer", data_type=NamedTypeRef(name="DataBuffer")),
                        ],
                    ),
                    networks=[Network(statements=[EmptyStatement()])],
                ),
            ],
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert "def Process(self, cmd: int, buffer: DataBuffer):" in out
        # InOut should NOT appear as local declaration
        assert "InOut[DataBuffer]" not in out

    def test_inout_and_input_both_in_signature(self):
        """Input params come before InOut params in signature."""
        m = Method(
            name="Transfer",
            interface=POUInterface(
                input_vars=[
                    Variable(name="enable", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
                ],
                inout_vars=[
                    Variable(name="data", data_type=NamedTypeRef(name="MyStruct")),
                ],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._self_vars = set()
        w._write_method(m)
        out = w.getvalue()
        assert "def Transfer(self, enable: bool, data: MyStruct):" in out


# ===========================================================================
# New statement types: latch assignment, TryCatch, Jump, Label
# ===========================================================================

class TestLatchAssignmentExport:
    def test_set_latch_emits_comment(self):
        w = _make_writer()
        stmt = Assignment(
            target=VariableRef(name="flag"),
            value=VariableRef(name="cond"),
            latch="S",
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "# flag S= cond" in out
        assert "pass" in out

    def test_reset_latch_emits_comment(self):
        w = _make_writer()
        stmt = Assignment(
            target=VariableRef(name="flag"),
            value=VariableRef(name="cond"),
            latch="R",
        )
        w._write_stmt(stmt)
        out = w.getvalue().strip()
        assert "# flag R= cond" in out
        assert "pass" in out

    def test_normal_assignment_unaffected(self):
        w = _make_writer()
        stmt = Assignment(
            target=VariableRef(name="x"),
            value=LiteralExpr(value="42"),
        )
        w._write_stmt(stmt)
        assert w.getvalue().strip() == "x = 42"


class TestTryCatchExport:
    def test_try_catch_emits_comment_block(self):
        w = _make_writer()
        stmt = TryCatchStatement(
            try_body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))],
            catch_body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="0"))],
        )
        w._write_stmt(stmt)
        out = w.getvalue()
        assert "# __TRY" in out
        assert "# __CATCH" in out
        assert "# __ENDTRY" in out
        # Body statements are still emitted (not commented out)
        assert "x = 1" in out
        assert "x = 0" in out

    def test_try_catch_with_var(self):
        w = _make_writer()
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            catch_var="exc",
            catch_body=[],
        )
        w._write_stmt(stmt)
        assert "# __CATCH(exc)" in w.getvalue()

    def test_try_finally(self):
        w = _make_writer()
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            finally_body=[Assignment(target=VariableRef(name="done"), value=LiteralExpr(value="TRUE"))],
        )
        w._write_stmt(stmt)
        out = w.getvalue()
        assert "# __FINALLY" in out
        assert "done = True" in out

    def test_try_no_catch_no_finally(self):
        w = _make_writer()
        stmt = TryCatchStatement(try_body=[EmptyStatement()])
        w._write_stmt(stmt)
        out = w.getvalue()
        assert "# __TRY" in out
        assert "__CATCH" not in out
        assert "__FINALLY" not in out
        assert "# __ENDTRY" in out


class TestJumpLabelExport:
    def test_jump_emits_comment(self):
        w = _make_writer()
        w._write_stmt(JumpStatement(label="loop_start"))
        assert w.getvalue().strip() == "# JMP loop_start"

    def test_label_emits_comment(self):
        w = _make_writer()
        w._write_stmt(LabelStatement(name="loop_start"))
        assert w.getvalue().strip() == "# loop_start:"


class TestNewStatementIRModel:
    def test_latch_defaults_to_empty(self):
        stmt = Assignment(
            target=VariableRef(name="x"),
            value=LiteralExpr(value="1"),
        )
        assert stmt.latch == ""

    def test_latch_accepts_s_and_r(self):
        s_stmt = Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="TRUE"), latch="S")
        r_stmt = Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="FALSE"), latch="R")
        assert s_stmt.latch == "S"
        assert r_stmt.latch == "R"

    def test_try_catch_construction(self):
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            catch_var="exc",
            catch_body=[EmptyStatement()],
            finally_body=[EmptyStatement()],
        )
        assert stmt.kind == "try_catch"
        assert stmt.catch_var == "exc"
        assert len(stmt.try_body) == 1
        assert len(stmt.catch_body) == 1
        assert len(stmt.finally_body) == 1

    def test_jump_construction(self):
        stmt = JumpStatement(label="target")
        assert stmt.kind == "jump"
        assert stmt.label == "target"

    def test_label_construction(self):
        stmt = LabelStatement(name="target")
        assert stmt.kind == "label"
        assert stmt.name == "target"

    def test_new_types_in_statement_union(self):
        """New types round-trip through the Statement discriminated union."""
        import json
        from plx.model.statements import Statement
        from pydantic import TypeAdapter
        ta = TypeAdapter(Statement)
        for data in [
            {"kind": "jump", "label": "lbl"},
            {"kind": "label", "name": "lbl"},
            {"kind": "try_catch", "try_body": []},
        ]:
            stmt = ta.validate_python(data)
            restored = ta.validate_json(ta.dump_json(stmt))
            assert restored == stmt


# ===========================================================================
# Membership reconstruction (in / not in)
# ===========================================================================

class TestMembershipReconstruction:
    """Test that OR/EQ chains are reconstructed as ``in`` and AND/NE as ``not in``."""

    # -- Helper to build the left-folded chain the compiler produces --

    @staticmethod
    def _make_membership_ir(target, values, negate=False):
        """Build the same left-folded tree that _compile_membership_test produces."""
        eq_op = BinaryOp.NE if negate else BinaryOp.EQ
        chain_op = BinaryOp.AND if negate else BinaryOp.OR
        result = BinaryExpr(op=eq_op, left=target, right=values[0])
        for v in values[1:]:
            result = BinaryExpr(
                op=chain_op,
                left=result,
                right=BinaryExpr(op=eq_op, left=target, right=v),
            )
        return result

    # -- Basic reconstruction --

    def test_in_two_elements(self):
        w = _make_writer()
        expr = self._make_membership_ir(
            VariableRef(name="state"),
            [LiteralExpr(value="1"), LiteralExpr(value="2")],
        )
        assert w._expr(expr) == "state in (1, 2)"

    def test_in_three_elements(self):
        w = _make_writer()
        expr = self._make_membership_ir(
            VariableRef(name="x"),
            [LiteralExpr(value="1"), LiteralExpr(value="2"), LiteralExpr(value="3")],
        )
        assert w._expr(expr) == "x in (1, 2, 3)"

    def test_in_five_elements(self):
        w = _make_writer()
        expr = self._make_membership_ir(
            VariableRef(name="mode"),
            [LiteralExpr(value=str(i)) for i in range(5)],
        )
        assert w._expr(expr) == "mode in (0, 1, 2, 3, 4)"

    def test_not_in_two_elements(self):
        w = _make_writer()
        expr = self._make_membership_ir(
            VariableRef(name="state"),
            [LiteralExpr(value="1"), LiteralExpr(value="2")],
            negate=True,
        )
        assert w._expr(expr) == "state not in (1, 2)"

    def test_not_in_three_elements(self):
        w = _make_writer()
        expr = self._make_membership_ir(
            VariableRef(name="x"),
            [LiteralExpr(value="1"), LiteralExpr(value="2"), LiteralExpr(value="3")],
            negate=True,
        )
        assert w._expr(expr) == "x not in (1, 2, 3)"

    def test_preserves_value_order(self):
        w = _make_writer()
        expr = self._make_membership_ir(
            VariableRef(name="x"),
            [LiteralExpr(value="10"), LiteralExpr(value="20"), LiteralExpr(value="30")],
        )
        assert w._expr(expr) == "x in (10, 20, 30)"

    def test_self_prefix(self):
        w = _make_writer(self_vars={"state"})
        expr = self._make_membership_ir(
            VariableRef(name="state"),
            [LiteralExpr(value="1"), LiteralExpr(value="2")],
        )
        assert w._expr(expr) == "self.state in (1, 2)"

    def test_enum_values(self):
        w = _make_writer(self_vars={"mode"})
        expr = self._make_membership_ir(
            VariableRef(name="mode"),
            [LiteralExpr(value="Mode#IDLE"), LiteralExpr(value="Mode#RUNNING")],
        )
        assert w._expr(expr) == "self.mode in (Mode.IDLE, Mode.RUNNING)"

    # -- Non-matching patterns --

    def test_no_match_different_targets(self):
        """OR(EQ(x, 1), EQ(y, 2)) — different targets, should not match."""
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.OR,
            left=BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="1")),
            right=BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="y"), right=LiteralExpr(value="2")),
        )
        assert "in" not in w._expr(expr)

    def test_no_match_mixed_ops(self):
        """OR(GT(x, 1), EQ(x, 2)) — not all EQ leaves, should not match."""
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.OR,
            left=BinaryExpr(op=BinaryOp.GT, left=VariableRef(name="x"), right=LiteralExpr(value="1")),
            right=BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="2")),
        )
        assert "in (" not in w._expr(expr)

    def test_no_match_and_with_eq(self):
        """AND(EQ(x, 1), EQ(x, 2)) — AND requires NE leaves, not EQ."""
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.AND,
            left=BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="1")),
            right=BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="2")),
        )
        assert "in (" not in w._expr(expr)

    def test_no_match_simple_or(self):
        """OR(a, b) — plain boolean OR, not EQ chain."""
        w = _make_writer()
        expr = BinaryExpr(
            op=BinaryOp.OR,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        assert w._expr(expr) == "a or b"

    # -- Full round-trip: framework → IR → Python --

    def test_round_trip_in(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._plc_types import dint

        @fb
        class InTestFB:
            state: Input[dint]
            active: Output[bool]

            def logic(self):
                self.active = self.state in (1, 2, 3)

        pou = InTestFB.compile()
        proj = Project(name="InTest", pous=[pou])
        code = generate(proj)
        compile(code, "<generated>", "exec")
        assert "self.state in (1, 2, 3)" in code

    def test_round_trip_not_in(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._plc_types import dint

        @fb
        class NotInTestFB:
            state: Input[dint]
            inactive: Output[bool]

            def logic(self):
                self.inactive = self.state not in (0, 99)

        pou = NotInTestFB.compile()
        proj = Project(name="NotInTest", pous=[pou])
        code = generate(proj)
        compile(code, "<generated>", "exec")
        assert "self.state not in (0, 99)" in code


# ===========================================================================
# Ternary reconstruction (SEL → if/else)
# ===========================================================================

class TestTernaryReconstruction:
    """Test that SEL(cond, false_val, true_val) is reconstructed as ternary."""

    def test_basic_ternary(self):
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=VariableRef(name="running")),
                CallArg(value=LiteralExpr(value="0")),
                CallArg(value=LiteralExpr(value="100")),
            ],
        )
        assert w._expr(expr) == "100 if running else 0"

    def test_ternary_with_self(self):
        w = _make_writer(self_vars={"running", "high", "low"})
        expr = FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=VariableRef(name="running")),
                CallArg(value=VariableRef(name="low")),
                CallArg(value=VariableRef(name="high")),
            ],
        )
        assert w._expr(expr) == "self.high if self.running else self.low"

    def test_ternary_nested_in_expression(self):
        """Ternary inside a higher-precedence context gets parenthesised."""
        w = _make_writer()
        sel = FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=VariableRef(name="flag")),
                CallArg(value=LiteralExpr(value="0")),
                CallArg(value=LiteralExpr(value="10")),
            ],
        )
        expr = BinaryExpr(
            op=BinaryOp.ADD,
            left=sel,
            right=LiteralExpr(value="1"),
        )
        assert w._expr(expr) == "(10 if flag else 0) + 1"

    def test_ternary_at_top_level(self):
        """Ternary at statement level — no parentheses needed."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=VariableRef(name="cond")),
                CallArg(value=LiteralExpr(value="'off'")),
                CallArg(value=LiteralExpr(value="'on'")),
            ],
        )
        assert w._expr(expr, 0) == "'on' if cond else 'off'"

    def test_sel_with_named_args_not_reconstructed(self):
        """SEL with named args is not from a ternary — fall through."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(name="G", value=VariableRef(name="cond")),
                CallArg(name="IN0", value=LiteralExpr(value="0")),
                CallArg(name="IN1", value=LiteralExpr(value="1")),
            ],
        )
        # Named args → generic function call, not ternary
        result = w._expr(expr)
        assert "if" not in result
        assert "SEL(" in result

    def test_sel_wrong_arg_count_not_reconstructed(self):
        """SEL with != 3 args should not be reconstructed."""
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=VariableRef(name="cond")),
                CallArg(value=LiteralExpr(value="0")),
            ],
        )
        result = w._expr(expr)
        assert "if" not in result

    def test_round_trip_ternary(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output

        @fb
        class TernaryFB:
            running: Input[bool]
            speed: Output[int]

            def logic(self):
                self.speed = 100 if self.running else 0

        pou = TernaryFB.compile()
        proj = Project(name="TernaryTest", pous=[pou])
        code = generate(proj)
        compile(code, "<generated>", "exec")
        assert "100 if self.running else 0" in code

    def test_round_trip_ternary_in_expression(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output

        @fb
        class TernaryExprFB:
            flag: Input[bool]
            result: Output[int]

            def logic(self):
                self.result = (10 if self.flag else 5) + 1

        pou = TernaryExprFB.compile()
        proj = Project(name="TernaryExprTest", pous=[pou])
        code = generate(proj)
        compile(code, "<generated>", "exec")
        assert "if self.flag else" in code

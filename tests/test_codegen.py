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
    RepeatStatement,
    ReturnStatement,
    WhileStatement,
)
from plx.model.task import Task, TaskType
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


# ===========================================================================
# Type references
# ===========================================================================

class TestTypeRef:
    def test_primitive(self):
        w = _make_writer()
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.BOOL)) == "bool"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.INT)) == "INT"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.REAL)) == "float"

    def test_primitive_python_aliases(self):
        w = _make_writer()
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.DINT)) == "int"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.BOOL)) == "bool"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.REAL)) == "float"

    def test_primitive_non_default_preserved(self):
        w = _make_writer()
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.SINT)) == "SINT"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.LINT)) == "LINT"
        assert w._type_ref(PrimitiveTypeRef(type=PrimitiveType.LREAL)) == "LREAL"

    def test_string_default_as_str(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(wide=False, max_length=255)) == "str"

    def test_string_non_default_unchanged(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(wide=False, max_length=80)) == "STRING(80)"

    def test_string_default(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef()) == "STRING()"

    def test_string_with_length(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(max_length=80)) == "STRING(80)"

    def test_wstring(self):
        w = _make_writer()
        assert w._type_ref(StringTypeRef(wide=True, max_length=100)) == "WSTRING(100)"

    def test_named(self):
        w = _make_writer()
        assert w._type_ref(NamedTypeRef(name="MotorData")) == "MotorData"

    def test_array_zero_based(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert w._type_ref(tr) == "ARRAY(INT, 10)"

    def test_array_one_based(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=1, upper=10)],
        )
        assert w._type_ref(tr) == "ARRAY(INT, (1, 10))"

    def test_array_with_python_types(self):
        w = _make_writer()
        tr = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert w._type_ref(tr) == "ARRAY(int, 10)"

    def test_pointer(self):
        w = _make_writer()
        tr = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.INT))
        assert w._type_ref(tr) == "POINTER_TO(INT)"

    def test_pointer_with_python_types(self):
        w = _make_writer()
        tr = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert w._type_ref(tr) == "POINTER_TO(float)"

    def test_reference(self):
        w = _make_writer()
        tr = ReferenceTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert w._type_ref(tr) == "REFERENCE_TO(float)"


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

    def test_function_call(self):
        w = _make_writer()
        expr = FunctionCallExpr(
            function_name="ABS",
            args=[CallArg(value=VariableRef(name="x"))],
        )
        assert w._expr(expr) == "abs(x)"

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
        assert w._expr(expr) == "float(x)"

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
        assert "for i in range(0, 9 + 1):" in out

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
        assert "speed: float" in out
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
        assert "speed: float = 0.0" in out
        assert "running: bool" in out

    def test_gvl_with_complex_vars(self):
        gvl = GlobalVariableList(
            name="HardwareIO",
            variables=[
                Variable(
                    name="valve",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL),
                    address="%Q0.0",
                    retain=True,
                ),
            ],
        )
        w = _make_writer()
        w._write_global_variable_list(gvl)
        out = w.getvalue().strip()
        assert 'valve: bool = Field(retain=True, address="%Q0.0")' in out

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
        assert "def logic(self) -> float:" in out
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
        assert "timer: TON" in out

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
        assert "@method" in out
        assert "def Calculate(self, x: float) -> float:" in out

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
        assert "@method(access=AccessSpecifier.PRIVATE)" in out

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
        assert 'proj = project("Empty")' in out

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
        assert "pous=[Motor]" in out

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
                Task(
                    name="MainTask",
                    task_type=TaskType.PERIODIC,
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
        assert "data_types=[SensorData, State]" in out

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
        assert "global_var_lists=[SystemIO]" in out

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
            sensor: Input[BOOL]
            valve: Output[BOOL]

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
        from plx.framework._types import REAL

        @function
        class AddOne:
            x: Input[REAL]

            def logic(self) -> REAL:
                return self.x + 1.0

        pou_ir = AddOne.compile()
        proj_ir = Project(name="FuncRT", pous=[pou_ir])
        code = generate(proj_ir)

        compile(code, "<generated>", "exec")
        assert "def logic(self) -> float:" in code

    def test_if_else_round_trip(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import BOOL, DINT

        @fb
        class IfElseFB:
            enable: Input[BOOL]
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
        from plx.framework._types import BOOL, REAL

        @struct
        class MotorData:
            speed: REAL
            running: BOOL = False

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
        assert "speed: float" in code
        assert "class Mode:" in code

    def test_global_vars_round_trip(self):
        from plx.framework._global_vars import global_vars
        from plx.framework._types import BOOL, REAL

        @global_vars
        class IO:
            speed: REAL = 0.0
            running: BOOL

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
        from plx.framework._project import project, task
        from datetime import timedelta
        from plx.framework._types import BOOL

        @fb
        class MotorCtrl:
            cmd: Input[BOOL]
            out: Output[BOOL]

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
        assert "ref: InOut[float]" in out
        assert "count: int = 0" in out

    def test_metadata_uses_field_syntax(self):
        """Variables with description/retain should use annotation + Field() syntax."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MetaFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), description="Main sensor")],
                output_vars=[Variable(name="valve", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL), retain=True)],
                static_vars=[Variable(name="count", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT), address="%MW100")],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        w = _make_writer()
        w._write_pou(pou)
        out = w.getvalue()
        assert 'sensor: Input[bool] = Field(description="Main sensor")' in out
        assert "valve: Output[bool] = Field(retain=True)" in out
        assert 'count: int = Field(address="%MW100")' in out

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
        assert "timer: TON" in out

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
        assert "speed: float" in out

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
        assert "speed: Input[float] = 100.0" in out


# ===========================================================================
# Multi-file generation
# ===========================================================================

class TestGenerateFiles:
    def test_empty_project(self):
        proj = Project(name="Empty")
        files = generate_files(proj)
        assert "project.py" in files
        assert 'project("Empty")' in files["project.py"]

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

        # project.py imports from siblings
        assert "from .Motor import Motor" in files["project.py"]
        assert "from .Main import Main" in files["project.py"]

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

        # project.py imports data types
        assert "from .SensorData import SensorData" in files["project.py"]
        assert "from .State import State" in files["project.py"]

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
        assert "from .SystemIO import SystemIO" in files["project.py"]

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
        assert "from .MotorData import MotorData" in files["Controller.py"]

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
        assert "from .BaseFB import BaseFB" in files["Derived.py"]

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
        assert "@fb_property(float)" in code
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
        assert "@fb_property(float)" in code
        assert "def level(self):" in code
        assert "@level.setter" in code
        assert "def level(self, level: float):" in code

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
        assert "@method" in code
        assert "def move_to(self, target: float) -> bool: ..." in code
        assert "@fb_property(float)" in code
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
        # Interface should appear in project.py imports
        assert "from .IMoveable import IMoveable" in files["project.py"]
        # FB should import the interface it implements
        assert "from .IMoveable import IMoveable" in files["Motor.py"]


# ===========================================================================
# Type conversion export
# ===========================================================================

class TestTypeConversionExport:
    def test_type_conversion_iec_name(self):
        """IEC type names like INT(x), SINT(x), LREAL(x) round-trip correctly."""
        w = _make_writer()
        # Types NOT in _PYTHON_TYPE_NAMES keep their IEC name
        for type_name in ("INT", "SINT", "LREAL", "UINT", "UDINT", "LINT"):
            prim = PrimitiveType(type_name)
            expr = TypeConversionExpr(
                target_type=PrimitiveTypeRef(type=prim),
                source=VariableRef(name="x"),
            )
            assert w._expr(expr) == f"{type_name}(x)", f"Failed for {type_name}"

    def test_type_conversion_python_mapped(self):
        """BOOL/DINT/REAL map to Python builtins bool()/int()/float()."""
        w = _make_writer()
        cases = [
            (PrimitiveType.BOOL, "bool(x)"),
            (PrimitiveType.DINT, "int(x)"),
            (PrimitiveType.REAL, "float(x)"),
        ]
        for prim, expected in cases:
            expr = TypeConversionExpr(
                target_type=PrimitiveTypeRef(type=prim),
                source=VariableRef(name="x"),
            )
            assert w._expr(expr) == expected

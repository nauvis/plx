"""Tests for the ST pretty-printer (plx.export.st)."""

from plx.export.st import _build_source_map, to_structured_text
from plx.model import (
    POU,
    AccessSpecifier,
    Language,
    Method,
    POUType,
    POUInterface,
    Network,
    Property,
    PropertyAccessor,
    Variable,
    PrimitiveTypeRef,
    PrimitiveType,
    NamedTypeRef,
    ArrayTypeRef,
    DimensionRange,
    StringTypeRef,
    PointerTypeRef,
    ReferenceTypeRef,
    Assignment,
    VariableRef,
    LiteralExpr,
    BinaryExpr,
    BinaryOp,
    UnaryExpr,
    UnaryOp,
    IfStatement,
    IfBranch,
    CaseStatement,
    CaseBranch,
    CaseRange,
    ForStatement,
    WhileStatement,
    RepeatStatement,
    ExitStatement,
    ContinueStatement,
    ReturnStatement,
    FunctionCallStatement,
    FBInvocation,
    CallArg,
    FunctionCallExpr,
    ArrayAccessExpr,
    MemberAccessExpr,
    BitAccessExpr,
    TypeConversionExpr,
    EmptyStatement,
    Project,
    StructType,
    StructMember,
    EnumType,
    EnumMember,
    UnionType,
    AliasType,
    SubrangeType,
    GlobalVariableList,
    SFCBody,
    Step,
    Action,
    ActionQualifier,
)
from plx.model.sfc import Transition as SFCTransition


def _bool() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _int() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.INT)


def _real() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.REAL)


def _ref(name: str) -> VariableRef:
    return VariableRef(name=name)


def _lit(val: str) -> LiteralExpr:
    return LiteralExpr(value=val)


# -----------------------------------------------------------------------
# Type references
# -----------------------------------------------------------------------

class TestTypeRef:
    def test_primitive(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(input_vars=[Variable(name="x", data_type=_bool())]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "x : BOOL;" in st

    def test_string(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(input_vars=[
                Variable(name="s", data_type=StringTypeRef(max_length=80)),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "s : STRING[80];" in st

    def test_wstring(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(input_vars=[
                Variable(name="s", data_type=StringTypeRef(wide=True)),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "s : WSTRING;" in st

    def test_array(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(static_vars=[
                Variable(name="a", data_type=ArrayTypeRef(
                    element_type=_int(),
                    dimensions=[DimensionRange(lower=0, upper=9)],
                )),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "a : ARRAY[0..9] OF INT;" in st

    def test_pointer(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(static_vars=[
                Variable(name="p", data_type=PointerTypeRef(target_type=_int())),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "p : POINTER TO INT;" in st

    def test_reference(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(static_vars=[
                Variable(name="r", data_type=ReferenceTypeRef(target_type=_real())),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "r : REFERENCE TO REAL;" in st

    def test_named(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(static_vars=[
                Variable(name="m", data_type=NamedTypeRef(name="MotorData")),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "m : MotorData;" in st


# -----------------------------------------------------------------------
# Expressions
# -----------------------------------------------------------------------

class TestExpressions:
    def test_binary_arithmetic(self):
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.ADD, left=_ref("a"), right=_lit("1")),
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := a + 1;" in st

    def test_binary_comparison(self):
        stmt = Assignment(
            target=_ref("y"),
            value=BinaryExpr(op=BinaryOp.NE, left=_ref("a"), right=_ref("b")),
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := a <> b;" in st

    def test_binary_precedence(self):
        # (a + b) * c should emit a + b without parens for a + b at top,
        # but with parens when nested in *
        inner = BinaryExpr(op=BinaryOp.ADD, left=_ref("a"), right=_ref("b"))
        outer = BinaryExpr(op=BinaryOp.MUL, left=inner, right=_ref("c"))
        stmt = Assignment(target=_ref("y"), value=outer)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := (a + b) * c;" in st

    def test_unary_not(self):
        expr = UnaryExpr(op=UnaryOp.NOT, operand=_ref("x"))
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := NOT x;" in st

    def test_unary_neg(self):
        expr = UnaryExpr(op=UnaryOp.NEG, operand=_lit("5"))
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := -5;" in st

    def test_function_call(self):
        expr = FunctionCallExpr(
            function_name="ABS",
            args=[CallArg(value=_ref("x"))],
        )
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := ABS(x);" in st

    def test_array_access(self):
        expr = ArrayAccessExpr(array=_ref("arr"), indices=[_lit("3")])
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := arr[3];" in st

    def test_member_access(self):
        expr = MemberAccessExpr(struct=_ref("motor"), member="speed")
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := motor.speed;" in st

    def test_bit_access(self):
        expr = BitAccessExpr(target=_ref("w"), bit_index=5)
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := w.5;" in st

    def test_type_conversion(self):
        expr = TypeConversionExpr(target_type=_real(), source=_ref("x"))
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := REAL(x);" in st

    def test_shift_as_function(self):
        expr = BinaryExpr(op=BinaryOp.SHL, left=_ref("x"), right=_lit("2"))
        stmt = Assignment(target=_ref("y"), value=expr)
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "y := SHL(x, 2);" in st


# -----------------------------------------------------------------------
# Statements
# -----------------------------------------------------------------------

class TestStatements:
    def test_if_elsif_else(self):
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=_ref("a"),
                body=[Assignment(target=_ref("x"), value=_lit("1"))],
            ),
            elsif_branches=[
                IfBranch(
                    condition=_ref("b"),
                    body=[Assignment(target=_ref("x"), value=_lit("2"))],
                ),
            ],
            else_body=[Assignment(target=_ref("x"), value=_lit("3"))],
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "IF a THEN" in st
        assert "ELSIF b THEN" in st
        assert "ELSE" in st
        assert "END_IF;" in st

    def test_case(self):
        stmt = CaseStatement(
            selector=_ref("state"),
            branches=[
                CaseBranch(values=[0], body=[
                    Assignment(target=_ref("x"), value=_lit("0")),
                ]),
                CaseBranch(values=[1, 2], ranges=[CaseRange(start=10, end=20)], body=[
                    Assignment(target=_ref("x"), value=_lit("1")),
                ]),
            ],
            else_body=[Assignment(target=_ref("x"), value=_lit("99"))],
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "CASE state OF" in st
        assert "0:" in st
        assert "1, 2, 10..20:" in st
        assert "ELSE" in st
        assert "END_CASE;" in st

    def test_for(self):
        stmt = ForStatement(
            loop_var="i",
            from_expr=_lit("0"),
            to_expr=_lit("10"),
            by_expr=_lit("2"),
            body=[Assignment(target=_ref("x"), value=_ref("i"))],
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "FOR i := 0 TO 10 BY 2 DO" in st
        assert "END_FOR;" in st

    def test_while(self):
        stmt = WhileStatement(
            condition=_ref("running"),
            body=[Assignment(target=_ref("x"), value=BinaryExpr(
                op=BinaryOp.ADD, left=_ref("x"), right=_lit("1"),
            ))],
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "WHILE running DO" in st
        assert "END_WHILE;" in st

    def test_repeat(self):
        stmt = RepeatStatement(
            body=[Assignment(target=_ref("x"), value=BinaryExpr(
                op=BinaryOp.ADD, left=_ref("x"), right=_lit("1"),
            ))],
            until=BinaryExpr(op=BinaryOp.GE, left=_ref("x"), right=_lit("10")),
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "REPEAT" in st
        assert "UNTIL x >= 10" in st
        assert "END_REPEAT;" in st

    def test_exit_continue_return(self):
        stmts = [ExitStatement(), ContinueStatement(), ReturnStatement()]
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=stmts)],
        )
        st = to_structured_text(pou)
        assert "EXIT;" in st
        assert "CONTINUE;" in st
        assert "RETURN;" in st

    def test_return_value(self):
        stmt = ReturnStatement(value=_ref("result"))
        pou = POU(
            pou_type=POUType.FUNCTION, name="Calc", return_type=_int(),
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "RETURN result;" in st

    def test_function_call_stmt(self):
        stmt = FunctionCallStatement(
            function_name="LOG",
            args=[CallArg(name="msg", value=_lit("'hello'"))],
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "LOG(msg := 'hello');" in st

    def test_fb_invocation(self):
        stmt = FBInvocation(
            instance_name="ton1",
            fb_type="TON",
            inputs={"IN": _ref("start"), "PT": _lit("T#5s")},
            outputs={"Q": _ref("done")},
        )
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "ton1(" in st
        assert "IN := start" in st
        assert "PT := T#5s" in st
        assert "Q => done" in st

    def test_empty(self):
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[EmptyStatement()])],
        )
        st = to_structured_text(pou)
        assert ";" in st


# -----------------------------------------------------------------------
# POU structure
# -----------------------------------------------------------------------

class TestPOUStructure:
    def test_function_block(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="Motor",
            interface=POUInterface(
                input_vars=[Variable(name="cmd", data_type=_bool())],
                output_vars=[Variable(name="running", data_type=_bool())],
            ),
            networks=[Network(statements=[
                Assignment(target=_ref("running"), value=_ref("cmd")),
            ])],
        )
        st = to_structured_text(pou)
        assert st.startswith("FUNCTION_BLOCK Motor\n")
        assert "END_FUNCTION_BLOCK\n" in st
        assert "VAR_INPUT" in st
        assert "VAR_OUTPUT" in st

    def test_program(self):
        pou = POU(
            pou_type=POUType.PROGRAM, name="Main",
            networks=[],
        )
        st = to_structured_text(pou)
        assert "PROGRAM Main" in st
        assert "END_PROGRAM" in st

    def test_function_with_return_type(self):
        pou = POU(
            pou_type=POUType.FUNCTION, name="Add",
            return_type=_int(),
            interface=POUInterface(
                input_vars=[
                    Variable(name="a", data_type=_int()),
                    Variable(name="b", data_type=_int()),
                ],
            ),
            networks=[Network(statements=[
                ReturnStatement(value=BinaryExpr(
                    op=BinaryOp.ADD, left=_ref("a"), right=_ref("b"),
                )),
            ])],
        )
        st = to_structured_text(pou)
        assert "FUNCTION Add : INT" in st
        assert "END_FUNCTION" in st

    def test_extends_implements(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="Derived",
            extends="Base",
            implements=["IMotor", "ISensor"],
            networks=[],
        )
        st = to_structured_text(pou)
        assert "FUNCTION_BLOCK Derived EXTENDS Base IMPLEMENTS IMotor, ISensor" in st

    def test_initial_value(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(input_vars=[
                Variable(name="x", data_type=_int(), initial_value="42"),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "x : INT := 42;" in st

    def test_retain_persistent(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="T",
            interface=POUInterface(static_vars=[
                Variable(name="x", data_type=_int(), retain=True, persistent=True),
            ]),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "RETAIN PERSISTENT x : INT;" in st


# -----------------------------------------------------------------------
# Type definitions
# -----------------------------------------------------------------------

class TestTypeDefinitions:
    def test_struct(self):
        proj = Project(
            name="T",
            data_types=[StructType(
                name="MotorData",
                members=[
                    StructMember(name="speed", data_type=_real()),
                    StructMember(name="running", data_type=_bool(), initial_value="FALSE"),
                ],
            )],
        )
        st = to_structured_text(proj)
        assert "TYPE MotorData :" in st
        assert "STRUCT" in st
        assert "speed : REAL;" in st
        assert "running : BOOL := FALSE;" in st
        assert "END_STRUCT" in st
        assert "END_TYPE" in st

    def test_enum(self):
        proj = Project(
            name="T",
            data_types=[EnumType(
                name="State",
                members=[
                    EnumMember(name="IDLE", value=0),
                    EnumMember(name="RUN", value=1),
                ],
            )],
        )
        st = to_structured_text(proj)
        assert "TYPE State : (" in st
        assert "IDLE := 0" in st
        assert "RUN := 1" in st
        assert "END_TYPE" in st

    def test_enum_with_base_type(self):
        proj = Project(
            name="T",
            data_types=[EnumType(
                name="State",
                base_type=PrimitiveType.DINT,
                members=[EnumMember(name="A", value=0)],
            )],
        )
        st = to_structured_text(proj)
        assert "TYPE State : DINT (" in st

    def test_alias(self):
        proj = Project(
            name="T",
            data_types=[AliasType(name="Speed", base_type=_real())],
        )
        st = to_structured_text(proj)
        assert "TYPE Speed : REAL;" in st

    def test_subrange(self):
        proj = Project(
            name="T",
            data_types=[SubrangeType(
                name="Pct", base_type=PrimitiveType.INT,
                lower_bound=0, upper_bound=100,
            )],
        )
        st = to_structured_text(proj)
        assert "TYPE Pct : INT(0..100);" in st


# -----------------------------------------------------------------------
# Global variable list
# -----------------------------------------------------------------------

class TestGVL:
    def test_basic(self):
        proj = Project(
            name="T",
            global_variable_lists=[GlobalVariableList(
                name="GVL",
                description="Global vars",
                variables=[
                    Variable(name="speed", data_type=_real(), address="%Q0.0"),
                ],
            )],
        )
        st = to_structured_text(proj)
        assert "VAR_GLOBAL" in st
        assert "speed AT %Q0.0 : REAL;" in st
        assert "END_VAR" in st


# -----------------------------------------------------------------------
# SFC
# -----------------------------------------------------------------------

class TestSFC:
    def test_basic_sfc(self):
        pou = POU(
            pou_type=POUType.PROGRAM, name="Seq",
            sfc_body=SFCBody(
                steps=[
                    Step(name="S0", is_initial=True, actions=[
                        Action(name="act0", qualifier=ActionQualifier.N),
                    ]),
                    Step(name="S1", actions=[
                        Action(name="act1", qualifier=ActionQualifier.N),
                    ]),
                ],
                transitions=[
                    SFCTransition(
                        source_steps=["S0"], target_steps=["S1"],
                        condition=_ref("start"),
                    ),
                ],
            ),
        )
        st = to_structured_text(pou)
        assert "INITIAL_STEP S0:" in st
        assert "act0(N);" in st
        assert "STEP S1:" in st
        assert "TRANSITION FROM S0 TO S1" in st
        assert ":= start;" in st


# -----------------------------------------------------------------------
# Framework integration
# -----------------------------------------------------------------------

class TestFrameworkIntegration:
    def test_compiled_pou(self):
        """Compile a framework @fb and ST-print the result."""
        # Use the sandbox to compile since we need inspect.getsource
        from web.backend.sandbox import compile_source

        result = compile_source(
            "from plx.framework import *\n\n"
            "@fb\n"
            "class Motor:\n"
            "    cmd = input_var(BOOL)\n"
            "    running = output_var(BOOL)\n\n"
            "    def logic(self):\n"
            "        self.running = self.cmd\n"
        )
        assert result.success
        assert "FUNCTION_BLOCK Motor" in result.st
        assert "running := cmd;" in result.st


# -----------------------------------------------------------------------
# Source map
# -----------------------------------------------------------------------

class TestSourceMap:
    def test_build_source_map_basic(self):
        st = "count := count + 1;\n"
        entries = _build_source_map(st, {"count"})
        # De-duplicates: first occurrence per variable per line
        assert len(entries) == 1
        assert entries[0] == {"name": "count", "line": 1, "column": 1}

    def test_build_source_map_no_partial_match(self):
        st = "max_count := 10;\n"
        entries = _build_source_map(st, {"count"})
        assert len(entries) == 0

    def test_build_source_map_multiline(self):
        st = "IF enable THEN\n    count := count + 1;\nEND_IF;\n"
        entries = _build_source_map(st, {"enable", "count"})
        names = [(e["name"], e["line"]) for e in entries]
        assert ("enable", 1) in names
        assert ("count", 2) in names

    def test_build_source_map_empty(self):
        assert _build_source_map("x := 1;\n", set()) == []

    def test_build_source_map_skips_var_blocks(self):
        st = "VAR_INPUT\n    enable : BOOL;\nEND_VAR\nIF enable THEN\nEND_IF;\n"
        entries = _build_source_map(st, {"enable"})
        assert len(entries) == 1
        assert entries[0]["line"] == 4  # body, not declaration

    def test_build_source_map_skips_comments(self):
        st = "count := 0; // Reset count\n"
        entries = _build_source_map(st, {"count"})
        # Only the code occurrence, not the comment one
        assert len(entries) == 1
        assert entries[0] == {"name": "count", "line": 1, "column": 1}

    def test_to_structured_text_source_map_flag(self):
        """to_structured_text(source_map=True) returns (str, list)."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="Counter",
            interface=POUInterface(
                input_vars=[
                    Variable(name="enable", data_type=_bool()),
                    Variable(name="reset", data_type=_bool()),
                    Variable(name="max_count", data_type=_int()),
                ],
                output_vars=[
                    Variable(name="count", data_type=_int()),
                    Variable(name="done", data_type=_bool()),
                ],
            ),
            networks=[Network(statements=[
                IfStatement(
                    if_branch=IfBranch(
                        condition=_ref("reset"),
                        body=[
                            Assignment(target=_ref("count"), value=_lit("0")),
                            Assignment(target=_ref("done"), value=_lit("FALSE")),
                        ],
                    ),
                    elsif_branches=[IfBranch(
                        condition=_ref("enable"),
                        body=[
                            IfStatement(
                                if_branch=IfBranch(
                                    condition=BinaryExpr(
                                        op=BinaryOp.LT,
                                        left=_ref("count"),
                                        right=_ref("max_count"),
                                    ),
                                    body=[Assignment(
                                        target=_ref("count"),
                                        value=BinaryExpr(
                                            op=BinaryOp.ADD,
                                            left=_ref("count"),
                                            right=_lit("1"),
                                        ),
                                    )],
                                ),
                            ),
                            IfStatement(
                                if_branch=IfBranch(
                                    condition=BinaryExpr(
                                        op=BinaryOp.GE,
                                        left=_ref("count"),
                                        right=_ref("max_count"),
                                    ),
                                    body=[Assignment(
                                        target=_ref("done"),
                                        value=_lit("TRUE"),
                                    )],
                                ),
                            ),
                        ],
                    )],
                ),
            ])],
        )
        st, smap = to_structured_text(pou, source_map=True)

        # Should be a tuple
        assert isinstance(st, str)
        assert isinstance(smap, list)

        # All variable names should appear
        found_names = {e["name"] for e in smap}
        assert {"enable", "reset", "max_count", "count", "done"} <= found_names

        # All entries have correct structure
        for entry in smap:
            assert "name" in entry
            assert "line" in entry
            assert "column" in entry
            assert entry["line"] >= 1
            assert entry["column"] >= 1

    def test_to_structured_text_without_source_map(self):
        """to_structured_text() without source_map returns plain str."""
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            interface=POUInterface(input_vars=[
                Variable(name="x", data_type=_bool()),
            ]),
            networks=[],
        )
        result = to_structured_text(pou)
        assert isinstance(result, str)

    def test_source_map_columns_correct(self):
        """Verify column positions point to the actual variable start."""
        pou = POU(
            pou_type=POUType.PROGRAM, name="T",
            networks=[Network(statements=[
                Assignment(target=_ref("y"), value=_ref("x")),
            ])],
            interface=POUInterface(
                input_vars=[Variable(name="x", data_type=_int())],
                output_vars=[Variable(name="y", data_type=_int())],
            ),
        )
        st, smap = to_structured_text(pou, source_map=True)
        lines = st.splitlines()

        for entry in smap:
            line_text = lines[entry["line"] - 1]
            col = entry["column"] - 1  # 0-indexed
            name = entry["name"]
            assert line_text[col:col + len(name)] == name


# -----------------------------------------------------------------------
# New IR fields (Phase 2)
# -----------------------------------------------------------------------

class TestAbstractPOU:
    def test_abstract_function_block(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="BaseFB",
            abstract=True,
            networks=[],
        )
        st = to_structured_text(pou)
        assert "FUNCTION_BLOCK ABSTRACT BaseFB" in st

    def test_non_abstract_function_block(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="ConcreteFB",
            networks=[],
        )
        st = to_structured_text(pou)
        assert "FUNCTION_BLOCK ConcreteFB" in st
        assert "ABSTRACT" not in st


class TestMethodAbstractFinal:
    def test_abstract_method(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="FB1",
            methods=[Method(name="Run", abstract=True, return_type=_bool())],
            networks=[],
        )
        st = to_structured_text(pou)
        assert "METHOD ABSTRACT Run : BOOL" in st

    def test_final_method(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="FB1",
            methods=[Method(name="Run", final=True)],
            networks=[],
        )
        st = to_structured_text(pou)
        assert "METHOD FINAL Run" in st

    def test_private_abstract_method(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="FB1",
            methods=[Method(
                name="InternalRun",
                access=AccessSpecifier.PRIVATE,
                abstract=True,
            )],
            networks=[],
        )
        st = to_structured_text(pou)
        assert "METHOD PRIVATE ABSTRACT InternalRun" in st


class TestPropertyAbstractFinal:
    def test_abstract_property(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="FB1",
            properties=[Property(name="Speed", data_type=_real(), abstract=True)],
            networks=[],
        )
        st = to_structured_text(pou)
        assert "PROPERTY ABSTRACT Speed : REAL" in st

    def test_final_property(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="FB1",
            properties=[Property(name="Speed", data_type=_real(), final=True)],
            networks=[],
        )
        st = to_structured_text(pou)
        assert "PROPERTY FINAL Speed : REAL" in st


class TestExternalVarsExport:
    def test_var_external_block(self):
        pou = POU(
            pou_type=POUType.PROGRAM, name="Main",
            interface=POUInterface(
                external_vars=[Variable(name="global_speed", data_type=_real())],
            ),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "VAR_EXTERNAL" in st
        assert "global_speed : REAL;" in st
        assert "END_VAR" in st

    def test_no_external_block_when_empty(self):
        pou = POU(
            pou_type=POUType.PROGRAM, name="Main",
            interface=POUInterface(),
            networks=[],
        )
        st = to_structured_text(pou)
        assert "VAR_EXTERNAL" not in st


class TestStructExtends:
    def test_struct_with_extends(self):
        proj = Project(
            name="T",
            data_types=[StructType(
                name="Derived",
                extends="Base",
                members=[StructMember(name="extra", data_type=_int())],
            )],
        )
        st = to_structured_text(proj)
        assert "TYPE Derived EXTENDS Base :" in st
        assert "STRUCT" in st

    def test_struct_without_extends(self):
        proj = Project(
            name="T",
            data_types=[StructType(
                name="Simple",
                members=[StructMember(name="x", data_type=_int())],
            )],
        )
        st = to_structured_text(proj)
        assert "TYPE Simple :" in st
        assert "EXTENDS" not in st


class TestGVLQualifiedOnly:
    def test_qualified_only(self):
        proj = Project(
            name="T",
            global_variable_lists=[GlobalVariableList(
                name="GVL",
                qualified_only=True,
                variables=[Variable(name="x", data_type=_bool())],
            )],
        )
        st = to_structured_text(proj)
        assert "{attribute 'qualified_only'}" in st
        assert "VAR_GLOBAL" in st

    def test_no_qualified_only(self):
        proj = Project(
            name="T",
            global_variable_lists=[GlobalVariableList(
                name="GVL",
                variables=[Variable(name="x", data_type=_bool())],
            )],
        )
        st = to_structured_text(proj)
        assert "qualified_only" not in st

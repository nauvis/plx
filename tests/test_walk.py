"""Tests for the shared IR tree walker (plx.model.walk)."""

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.pou import (
    POU,
    Method,
    Network,
    POUAction,
    POUType,
    Property,
    PropertyAccessor,
)
from plx.model.project import Project
from plx.model.sfc import Action, SFCBody, Step, Transition
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    ContinueStatement,
    EmptyStatement,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfBranch,
    IfStatement,
    JumpStatement,
    LabelStatement,
    PragmaStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    TryCatchStatement,
    WhileStatement,
)
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef
from plx.model.walk import (
    _expr_children,
    _stmt_bodies,
    _stmt_expressions,
    walk_expressions,
    walk_pou,
    walk_project,
    walk_statements,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lit(v: str = "0") -> LiteralExpr:
    return LiteralExpr(value=v)


def _var(n: str = "x") -> VariableRef:
    return VariableRef(name=n)


def _collect_kinds(expr: Expression) -> list[str]:
    """Walk an expression and return all visited node kinds in order."""
    kinds: list[str] = []
    walk_expressions(expr, lambda e: kinds.append(e.kind))
    return kinds


def _collect_stmt_kinds(stmts: list[Statement]) -> list[str]:
    """Walk statements and return all visited statement kinds in order."""
    kinds: list[str] = []
    walk_statements(stmts, on_stmt=lambda s: kinds.append(s.kind))
    return kinds


def _collect_expr_kinds_from_stmts(stmts: list[Statement]) -> list[str]:
    """Walk statements and return all expression kinds found."""
    kinds: list[str] = []
    walk_statements(stmts, on_expr=lambda e: kinds.append(e.kind))
    return kinds


# ===========================================================================
# Expression walking
# ===========================================================================


class TestExprChildren:
    """Test _expr_children returns correct children for each type."""

    def test_literal_leaf(self):
        assert _expr_children(_lit()) == []

    def test_variable_ref_leaf(self):
        assert _expr_children(_var()) == []

    def test_system_flag_leaf(self):
        assert _expr_children(SystemFlagExpr(flag=SystemFlag.FIRST_SCAN)) == []

    def test_binary(self):
        left, right = _lit("1"), _lit("2")
        expr = BinaryExpr(op=BinaryOp.ADD, left=left, right=right)
        assert _expr_children(expr) == [left, right]

    def test_unary(self):
        operand = _var()
        expr = UnaryExpr(op=UnaryOp.NOT, operand=operand)
        assert _expr_children(expr) == [operand]

    def test_function_call(self):
        a, b = _lit("1"), _var("y")
        expr = FunctionCallExpr(function_name="ABS", args=[CallArg(value=a), CallArg(value=b)])
        assert _expr_children(expr) == [a, b]

    def test_function_call_no_args(self):
        expr = FunctionCallExpr(function_name="NOP", args=[])
        assert _expr_children(expr) == []

    def test_array_access(self):
        arr, i, j = _var("arr"), _lit("0"), _lit("1")
        expr = ArrayAccessExpr(array=arr, indices=[i, j])
        assert _expr_children(expr) == [arr, i, j]

    def test_member_access(self):
        s = _var("fb")
        expr = MemberAccessExpr(struct=s, member="field")
        assert _expr_children(expr) == [s]

    def test_bit_access(self):
        t = _var("word")
        expr = BitAccessExpr(target=t, bit_index=3)
        assert _expr_children(expr) == [t]

    def test_type_conversion(self):
        src = _var("x")
        expr = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            source=src,
        )
        assert _expr_children(expr) == [src]

    def test_deref(self):
        ptr = _var("ptr")
        expr = DerefExpr(pointer=ptr)
        assert _expr_children(expr) == [ptr]

    def test_substring_both(self):
        s, start, end = _var("str"), _lit("1"), _lit("5")
        expr = SubstringExpr(string=s, start=start, end=end)
        assert _expr_children(expr) == [s, start, end]

    def test_substring_start_only(self):
        s, start = _var("str"), _lit("3")
        expr = SubstringExpr(string=s, start=start)
        assert _expr_children(expr) == [s, start]

    def test_substring_end_only(self):
        s, end = _var("str"), _lit("3")
        expr = SubstringExpr(string=s, end=end)
        assert _expr_children(expr) == [s, end]

    def test_substring_neither(self):
        s = _var("str")
        expr = SubstringExpr(string=s)
        assert _expr_children(expr) == [s]


class TestWalkExpressions:
    """Test walk_expressions visits all nodes in pre-order."""

    def test_leaf(self):
        assert _collect_kinds(_lit()) == ["literal"]

    def test_binary_tree(self):
        expr = BinaryExpr(op=BinaryOp.ADD, left=_lit("1"), right=_var("x"))
        assert _collect_kinds(expr) == ["binary", "literal", "variable_ref"]

    def test_nested_binary(self):
        inner = BinaryExpr(op=BinaryOp.MUL, left=_var("a"), right=_var("b"))
        outer = BinaryExpr(op=BinaryOp.ADD, left=inner, right=_lit("1"))
        kinds = _collect_kinds(outer)
        assert kinds == ["binary", "binary", "variable_ref", "variable_ref", "literal"]

    def test_function_call_with_args(self):
        expr = FunctionCallExpr(
            function_name="ABS",
            args=[CallArg(value=BinaryExpr(op=BinaryOp.SUB, left=_var("a"), right=_var("b")))],
        )
        kinds = _collect_kinds(expr)
        assert kinds == ["function_call", "binary", "variable_ref", "variable_ref"]

    def test_array_access_nested(self):
        expr = ArrayAccessExpr(
            array=MemberAccessExpr(struct=_var("fb"), member="data"),
            indices=[_lit("0")],
        )
        kinds = _collect_kinds(expr)
        assert kinds == ["array_access", "member_access", "variable_ref", "literal"]

    def test_deref_nested(self):
        expr = DerefExpr(pointer=MemberAccessExpr(struct=_var("s"), member="ptr"))
        kinds = _collect_kinds(expr)
        assert kinds == ["deref", "member_access", "variable_ref"]


# ===========================================================================
# Expression exhaustiveness
# ===========================================================================


class TestExpressionExhaustiveness:
    """Verify every Expression union member is handled by _expr_children."""

    def test_all_expression_types_handled(self):
        """Construct one instance of each Expression type and verify it's visited."""
        from typing import get_args

        # Get all types from the Expression union
        expr_union = get_args(Expression)
        # The Annotated wrapper: get_args returns (Union[...], Field(...))
        if len(expr_union) == 2 and hasattr(expr_union[1], "discriminator"):
            expr_union = get_args(expr_union[0])

        # Build one instance of each
        instances = {
            "literal": LiteralExpr(value="0"),
            "variable_ref": VariableRef(name="x"),
            "system_flag": SystemFlagExpr(flag=SystemFlag.FIRST_SCAN),
            "binary": BinaryExpr(op=BinaryOp.ADD, left=_lit(), right=_lit()),
            "unary": UnaryExpr(op=UnaryOp.NOT, operand=_lit()),
            "function_call": FunctionCallExpr(function_name="F"),
            "array_access": ArrayAccessExpr(array=_var(), indices=[_lit()]),
            "member_access": MemberAccessExpr(struct=_var(), member="m"),
            "bit_access": BitAccessExpr(target=_var(), bit_index=0),
            "type_conversion": TypeConversionExpr(
                target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                source=_var(),
            ),
            "deref": DerefExpr(pointer=_var()),
            "substring": SubstringExpr(string=_var()),
        }

        # Verify we have an instance for every union member
        union_kinds = {t.model_fields["kind"].default for t in expr_union}
        assert union_kinds == set(instances.keys()), (
            f"Missing expression types in test: {union_kinds - set(instances.keys())}"
        )

        # Verify each can be walked without error
        for kind, instance in instances.items():
            visited = []
            walk_expressions(instance, lambda e: visited.append(e.kind))
            assert kind in visited, f"{kind} was not visited"


# ===========================================================================
# Statement body/expression extraction
# ===========================================================================


class TestStmtBodies:
    """Test _stmt_bodies returns correct child body lists."""

    def test_if_all_branches(self):
        stmt = IfStatement(
            if_branch=IfBranch(condition=_lit("TRUE"), body=[EmptyStatement()]),
            elsif_branches=[IfBranch(condition=_lit("FALSE"), body=[EmptyStatement()])],
            else_body=[EmptyStatement()],
        )
        bodies = _stmt_bodies(stmt)
        assert len(bodies) == 3

    def test_if_no_else(self):
        stmt = IfStatement(
            if_branch=IfBranch(condition=_lit("TRUE"), body=[EmptyStatement()]),
        )
        bodies = _stmt_bodies(stmt)
        assert len(bodies) == 1

    def test_case(self):
        stmt = CaseStatement(
            selector=_var(),
            branches=[
                CaseBranch(values=[1], body=[EmptyStatement()]),
                CaseBranch(values=[2], body=[EmptyStatement()]),
            ],
            else_body=[EmptyStatement()],
        )
        bodies = _stmt_bodies(stmt)
        assert len(bodies) == 3  # 2 branches + else

    def test_case_no_else(self):
        stmt = CaseStatement(
            selector=_var(),
            branches=[CaseBranch(values=[1], body=[EmptyStatement()])],
        )
        bodies = _stmt_bodies(stmt)
        assert len(bodies) == 1

    def test_for(self):
        stmt = ForStatement(
            loop_var="i",
            from_expr=_lit("0"),
            to_expr=_lit("10"),
            body=[EmptyStatement()],
        )
        assert len(_stmt_bodies(stmt)) == 1

    def test_while(self):
        stmt = WhileStatement(condition=_lit("TRUE"), body=[EmptyStatement()])
        assert len(_stmt_bodies(stmt)) == 1

    def test_repeat(self):
        stmt = RepeatStatement(body=[EmptyStatement()], until=_lit("TRUE"))
        assert len(_stmt_bodies(stmt)) == 1

    def test_try_catch_all(self):
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            catch_body=[EmptyStatement()],
            finally_body=[EmptyStatement()],
        )
        assert len(_stmt_bodies(stmt)) == 3

    def test_try_catch_no_finally(self):
        stmt = TryCatchStatement(try_body=[EmptyStatement()])
        bodies = _stmt_bodies(stmt)
        assert len(bodies) == 1

    def test_leaf_statements(self):
        for stmt in [
            Assignment(target=_var(), value=_lit()),
            ExitStatement(),
            ContinueStatement(),
            ReturnStatement(),
            EmptyStatement(),
            PragmaStatement(text="test"),
            JumpStatement(label="lbl"),
            LabelStatement(name="lbl"),
            FunctionCallStatement(function_name="F"),
            FBInvocation(instance_name="fb", fb_type=NamedTypeRef(name="TON")),
        ]:
            assert _stmt_bodies(stmt) == [], f"{type(stmt).__name__} should have no child bodies"


class TestStmtExpressions:
    """Test _stmt_expressions returns correct expression fields."""

    def test_assignment(self):
        t, v = _var("out"), _lit("42")
        stmt = Assignment(target=t, value=v)
        assert _stmt_expressions(stmt) == [t, v]

    def test_if_conditions(self):
        c1, c2 = _var("a"), _var("b")
        stmt = IfStatement(
            if_branch=IfBranch(condition=c1, body=[]),
            elsif_branches=[IfBranch(condition=c2, body=[])],
        )
        assert _stmt_expressions(stmt) == [c1, c2]

    def test_case_selector(self):
        sel = _var("state")
        stmt = CaseStatement(
            selector=sel,
            branches=[CaseBranch(values=[1], body=[])],
        )
        assert _stmt_expressions(stmt) == [sel]

    def test_for_expressions(self):
        f, t, b = _lit("0"), _lit("10"), _lit("2")
        stmt = ForStatement(loop_var="i", from_expr=f, to_expr=t, by_expr=b, body=[])
        assert _stmt_expressions(stmt) == [f, t, b]

    def test_for_no_by(self):
        f, t = _lit("0"), _lit("10")
        stmt = ForStatement(loop_var="i", from_expr=f, to_expr=t, body=[])
        assert _stmt_expressions(stmt) == [f, t]

    def test_while_condition(self):
        c = _var("running")
        stmt = WhileStatement(condition=c, body=[])
        assert _stmt_expressions(stmt) == [c]

    def test_repeat_until(self):
        u = _var("done")
        stmt = RepeatStatement(body=[], until=u)
        assert _stmt_expressions(stmt) == [u]

    def test_return_with_value(self):
        v = _lit("42")
        stmt = ReturnStatement(value=v)
        assert _stmt_expressions(stmt) == [v]

    def test_return_no_value(self):
        stmt = ReturnStatement()
        assert _stmt_expressions(stmt) == []

    def test_function_call_args(self):
        a, b = _lit("1"), _var("x")
        stmt = FunctionCallStatement(
            function_name="F",
            args=[CallArg(value=a), CallArg(name="p", value=b)],
        )
        assert _stmt_expressions(stmt) == [a, b]

    def test_fb_invocation_inputs_outputs(self):
        v1, v2 = _lit("1"), _var("out")
        stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={"IN": v1},
            outputs={"Q": v2},
        )
        exprs = _stmt_expressions(stmt)
        assert v1 in exprs
        assert v2 in exprs

    def test_fb_invocation_expr_instance_name(self):
        """instance_name can be an expression (e.g. arr[0])."""
        inst = ArrayAccessExpr(array=_var("timers"), indices=[_lit("0")])
        stmt = FBInvocation(
            instance_name=inst,
            fb_type=NamedTypeRef(name="TON"),
        )
        exprs = _stmt_expressions(stmt)
        assert inst in exprs

    def test_fb_invocation_str_instance_name(self):
        """String instance_name should NOT appear in expressions."""
        stmt = FBInvocation(instance_name="fb", fb_type=NamedTypeRef(name="TON"))
        exprs = _stmt_expressions(stmt)
        assert all(not isinstance(e, str) for e in exprs)

    def test_leaf_statements_no_expressions(self):
        for stmt in [
            ExitStatement(),
            ContinueStatement(),
            EmptyStatement(),
            PragmaStatement(text="test"),
            JumpStatement(label="lbl"),
            LabelStatement(name="lbl"),
        ]:
            assert _stmt_expressions(stmt) == [], f"{type(stmt).__name__} should have no expressions"


# ===========================================================================
# Statement walking
# ===========================================================================


class TestWalkStatements:
    """Test walk_statements visits statements and recurses correctly."""

    def test_flat_list(self):
        stmts = [EmptyStatement(), ExitStatement(), ContinueStatement()]
        assert _collect_stmt_kinds(stmts) == ["empty", "exit", "continue"]

    def test_nested_if(self):
        inner = EmptyStatement()
        stmt = IfStatement(
            if_branch=IfBranch(condition=_lit("TRUE"), body=[inner]),
        )
        kinds = _collect_stmt_kinds([stmt])
        assert kinds == ["if", "empty"]

    def test_deeply_nested(self):
        """For → While → Assignment should all be visited."""
        assign = Assignment(target=_var("x"), value=_lit("1"))
        while_stmt = WhileStatement(condition=_lit("TRUE"), body=[assign])
        for_stmt = ForStatement(
            loop_var="i",
            from_expr=_lit("0"),
            to_expr=_lit("10"),
            body=[while_stmt],
        )
        kinds = _collect_stmt_kinds([for_stmt])
        assert kinds == ["for", "while", "assignment"]

    def test_case_branches_and_else(self):
        stmt = CaseStatement(
            selector=_var("state"),
            branches=[
                CaseBranch(values=[1], body=[EmptyStatement()]),
                CaseBranch(values=[2], body=[ExitStatement()]),
            ],
            else_body=[ContinueStatement()],
        )
        kinds = _collect_stmt_kinds([stmt])
        assert kinds == ["case", "empty", "exit", "continue"]

    def test_try_catch(self):
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            catch_body=[EmptyStatement()],
            finally_body=[EmptyStatement()],
        )
        kinds = _collect_stmt_kinds([stmt])
        assert kinds == ["try_catch", "empty", "empty", "empty"]

    def test_expr_walking_from_statements(self):
        """on_expr should find expressions inside statements."""
        stmt = Assignment(
            target=_var("out"),
            value=BinaryExpr(op=BinaryOp.ADD, left=_var("a"), right=_lit("1")),
        )
        expr_kinds = _collect_expr_kinds_from_stmts([stmt])
        assert "variable_ref" in expr_kinds
        assert "binary" in expr_kinds
        assert "literal" in expr_kinds

    def test_expr_in_nested_if_condition(self):
        """Expressions in if conditions should be visited."""
        cond = BinaryExpr(op=BinaryOp.GT, left=_var("x"), right=_lit("0"))
        stmt = IfStatement(
            if_branch=IfBranch(condition=cond, body=[EmptyStatement()]),
        )
        expr_kinds = _collect_expr_kinds_from_stmts([stmt])
        assert "binary" in expr_kinds
        assert "variable_ref" in expr_kinds

    def test_on_stmt_none_still_walks_exprs(self):
        """When on_stmt is None but on_expr is provided, expressions are still walked."""
        stmt = Assignment(target=_var("x"), value=_lit("1"))
        expr_kinds: list[str] = []
        walk_statements([stmt], on_stmt=None, on_expr=lambda e: expr_kinds.append(e.kind))
        assert "variable_ref" in expr_kinds
        assert "literal" in expr_kinds

    def test_on_expr_none_skips_exprs(self):
        """When on_expr is None, no expression callback is invoked."""
        stmt = Assignment(target=_var("x"), value=_lit("1"))
        called = []
        walk_statements([stmt], on_stmt=lambda s: called.append("stmt"))
        assert called == ["stmt"]  # only statement callback


# ===========================================================================
# Statement exhaustiveness
# ===========================================================================


class TestStatementExhaustiveness:
    """Verify every Statement union member is handled by the walker."""

    def test_all_statement_types_visited(self):
        """Construct one instance of each Statement type and verify it's visited."""
        from typing import get_args

        stmt_union = get_args(Statement)
        if len(stmt_union) == 2 and hasattr(stmt_union[1], "discriminator"):
            stmt_union = get_args(stmt_union[0])

        instances = {
            "assignment": Assignment(target=_var(), value=_lit()),
            "if": IfStatement(if_branch=IfBranch(condition=_lit("TRUE"), body=[])),
            "case": CaseStatement(selector=_var(), branches=[CaseBranch(values=[1])]),
            "for": ForStatement(loop_var="i", from_expr=_lit("0"), to_expr=_lit("10"), body=[]),
            "while": WhileStatement(condition=_lit("TRUE"), body=[]),
            "repeat": RepeatStatement(body=[], until=_lit("TRUE")),
            "exit": ExitStatement(),
            "continue": ContinueStatement(),
            "return": ReturnStatement(),
            "function_call_stmt": FunctionCallStatement(function_name="F"),
            "fb_invocation": FBInvocation(instance_name="fb", fb_type=NamedTypeRef(name="TON")),
            "empty": EmptyStatement(),
            "pragma": PragmaStatement(text="test"),
            "try_catch": TryCatchStatement(try_body=[]),
            "jump": JumpStatement(label="lbl"),
            "label": LabelStatement(name="lbl"),
        }

        union_kinds = {t.model_fields["kind"].default for t in stmt_union}
        assert union_kinds == set(instances.keys()), (
            f"Missing statement types in test: {union_kinds - set(instances.keys())}"
        )

        for kind, instance in instances.items():
            visited = []
            walk_statements([instance], on_stmt=lambda s: visited.append(s.kind))
            assert kind in visited, f"{kind} was not visited"


# ===========================================================================
# POU walking
# ===========================================================================


class TestWalkPOU:
    """Test walk_pou visits all code locations."""

    def _make_pou(self, **kwargs) -> POU:
        defaults = dict(pou_type=POUType.FUNCTION_BLOCK, name="TestFB")
        defaults.update(kwargs)
        return POU(**defaults)

    def test_walks_networks(self):
        pou = self._make_pou(
            networks=[Network(statements=[EmptyStatement()])],
        )
        kinds = []
        walk_pou(pou, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == ["empty"]

    def test_walks_methods(self):
        pou = self._make_pou(
            methods=[Method(name="do_thing", networks=[Network(statements=[EmptyStatement()])])],
        )
        kinds = []
        walk_pou(pou, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == ["empty"]

    def test_walks_actions(self):
        pou = self._make_pou(
            actions=[POUAction(name="act1", body=[Network(statements=[EmptyStatement()])])],
        )
        kinds = []
        walk_pou(pou, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == ["empty"]

    def test_walks_property_getter(self):
        pou = self._make_pou(
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(networks=[Network(statements=[EmptyStatement()])]),
                )
            ],
        )
        kinds = []
        walk_pou(pou, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == ["empty"]

    def test_walks_property_setter(self):
        pou = self._make_pou(
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    setter=PropertyAccessor(networks=[Network(statements=[EmptyStatement()])]),
                )
            ],
        )
        kinds = []
        walk_pou(pou, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == ["empty"]

    def test_walks_sfc_body(self):
        pou = self._make_pou(
            sfc_body=SFCBody(
                steps=[
                    Step(
                        name="S0",
                        is_initial=True,
                        actions=[
                            Action(name="A0", body=[EmptyStatement()]),
                        ],
                    ),
                ],
                transitions=[
                    Transition(
                        source_steps=["S0"],
                        target_steps=["S0"],
                        condition=_var("go"),
                    ),
                ],
            ),
        )
        stmt_kinds = []
        expr_kinds = []
        walk_pou(pou, on_stmt=lambda s: stmt_kinds.append(s.kind), on_expr=lambda e: expr_kinds.append(e.kind))
        assert "empty" in stmt_kinds
        assert "variable_ref" in expr_kinds  # transition condition

    def test_walks_sfc_entry_exit_actions(self):
        pou = self._make_pou(
            sfc_body=SFCBody(
                steps=[
                    Step(
                        name="S0",
                        is_initial=True,
                        entry_actions=[Action(name="entry", body=[EmptyStatement()])],
                        exit_actions=[Action(name="exit", body=[ExitStatement()])],
                    ),
                ],
            ),
        )
        kinds = []
        walk_pou(pou, on_stmt=lambda s: kinds.append(s.kind))
        assert "empty" in kinds
        assert "exit" in kinds

    def test_walks_all_locations(self):
        """POU with code in every possible location."""
        pou = self._make_pou(
            networks=[Network(statements=[Assignment(target=_var("a"), value=_lit("1"))])],
            methods=[
                Method(
                    name="m",
                    networks=[
                        Network(
                            statements=[
                                Assignment(target=_var("b"), value=_lit("2")),
                            ]
                        )
                    ],
                )
            ],
            actions=[
                POUAction(
                    name="act",
                    body=[
                        Network(
                            statements=[
                                Assignment(target=_var("c"), value=_lit("3")),
                            ]
                        )
                    ],
                )
            ],
            properties=[
                Property(
                    name="prop",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    getter=PropertyAccessor(
                        networks=[
                            Network(
                                statements=[
                                    ReturnStatement(value=_lit("4")),
                                ]
                            )
                        ]
                    ),
                    setter=PropertyAccessor(
                        networks=[
                            Network(
                                statements=[
                                    Assignment(target=_var("d"), value=_lit("5")),
                                ]
                            )
                        ]
                    ),
                )
            ],
        )
        stmt_kinds = []
        walk_pou(pou, on_stmt=lambda s: stmt_kinds.append(s.kind))
        assert stmt_kinds.count("assignment") == 4  # network + method + action + setter
        assert "return" in stmt_kinds


# ===========================================================================
# Project walking
# ===========================================================================


class TestWalkProject:
    def test_walks_all_pous(self):
        proj = Project(
            name="Test",
            pous=[
                POU(
                    pou_type=POUType.PROGRAM,
                    name="Main",
                    networks=[Network(statements=[EmptyStatement()])],
                ),
                POU(
                    pou_type=POUType.FUNCTION_BLOCK,
                    name="FB1",
                    networks=[Network(statements=[ExitStatement()])],
                ),
            ],
        )
        kinds = []
        walk_project(proj, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == ["empty", "exit"]

    def test_empty_project(self):
        proj = Project(name="Empty", pous=[])
        kinds = []
        walk_project(proj, on_stmt=lambda s: kinds.append(s.kind))
        assert kinds == []

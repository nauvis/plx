"""Tests verifying fixes for significant issues (#6-#18) found during deep scan.

Each test class contains a 'before' test (demonstrating the old broken behavior
would have failed) and 'after' test (verifying the fix works correctly).
"""

import pytest
from pydantic import ValidationError

from conftest import make_pou
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    LiteralExpr,
    MemberAccessExpr,
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
)
from plx.model.project import Project
from plx.model.statements import (
    Assignment,
    FBInvocation,
    ForStatement,
)
from plx.model.task import PeriodicTask
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StructMember,
    StructType,
)
from plx.model.variables import Variable
from plx.simulate._executor import ExecutionEngine
from plx.simulate._values import SimulationError


def _run(pou, state, clock_ms=0, **kwargs):
    engine = ExecutionEngine(pou=pou, state=state, clock_ms=clock_ms, **kwargs)
    engine.execute()
    return state


def _int_type():
    return PrimitiveTypeRef(type=PrimitiveType.INT)


def _bool_type():
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _make_project_pou(name, stmts=None, **iface_kwargs):
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name=name,
        interface=POUInterface(**iface_kwargs),
        networks=[Network(statements=stmts or [])],
    )


# ---------------------------------------------------------------------------
# Fix #6: Dotted string instance_name traversal in simulator
# ---------------------------------------------------------------------------


class TestDottedInstanceName:
    def test_dotted_instance_name_resolved(self):
        """'parent.child' should traverse nested state dicts."""
        pou = make_pou(
            [
                FBInvocation(
                    instance_name="parent.child",
                    fb_type="TON",
                    inputs={"IN": LiteralExpr(value="TRUE")},
                ),
            ]
        )
        state = {
            "parent": {
                "child": {"IN": False, "Q": False, "ET": 0, "PT": 0, "_prev_in": False, "_start_time": None},
            },
        }
        _run(pou, state)
        # The nested child FB should have been invoked
        assert state["parent"]["child"]["IN"] is True

    def test_flat_instance_name_still_works(self):
        """Plain (non-dotted) instance names should still work as before."""
        pou = make_pou(
            [
                FBInvocation(
                    instance_name="timer",
                    fb_type="TON",
                    inputs={"IN": LiteralExpr(value="TRUE")},
                ),
            ]
        )
        state = {"timer": {"IN": False, "Q": False, "ET": 0, "PT": 0, "_prev_in": False, "_start_time": None}}
        _run(pou, state)
        assert state["timer"]["IN"] is True

    def test_dotted_instance_name_not_found(self):
        """Missing nested path should raise SimulationError."""
        pou = make_pou(
            [
                FBInvocation(
                    instance_name="parent.missing",
                    fb_type="TON",
                    inputs={},
                ),
            ]
        )
        state = {"parent": {"other": {}}}
        with pytest.raises(SimulationError, match="not found"):
            _run(pou, state)


# ---------------------------------------------------------------------------
# Fix #7: FOR loop iteration guard
# ---------------------------------------------------------------------------


class TestForLoopIterationGuard:
    def test_normal_for_loop_works(self):
        """A normal FOR loop should complete without hitting the guard."""
        pou = make_pou(
            [
                Assignment(target=VariableRef(name="sum"), value=LiteralExpr(value="0")),
                ForStatement(
                    loop_var="i",
                    from_expr=LiteralExpr(value="1"),
                    to_expr=LiteralExpr(value="10"),
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
            ]
        )
        state = {"sum": 0, "i": 0}
        _run(pou, state)
        assert state["sum"] == 55

    def test_excessive_for_loop_raises(self):
        """A FOR loop exceeding MAX_LOOP_ITERATIONS should raise SimulationError."""
        pou = make_pou(
            [
                ForStatement(
                    loop_var="i",
                    from_expr=LiteralExpr(value="0"),
                    to_expr=LiteralExpr(value="2000000"),
                    body=[
                        Assignment(
                            target=VariableRef(name="x"),
                            value=LiteralExpr(value="0"),
                        ),
                    ],
                ),
            ]
        )
        state = {"i": 0, "x": 0}
        with pytest.raises(SimulationError, match="FOR loop exceeded"):
            _run(pou, state)


# ---------------------------------------------------------------------------
# Fix #8: _build_var_context records types for all var directions
# ---------------------------------------------------------------------------


class TestInferTypeAllDirections:
    def test_input_string_concat_rejected(self):
        """String += on an INPUT var should be caught by type inference."""
        from plx.framework import STRING, Input, fb
        from plx.framework._errors import PlxError

        # @fb compiles logic() at decoration time, so the error is raised
        # by the decorator itself, not by .compile()
        with pytest.raises(PlxError, match=r"[Ss]tring|f-string"):

            @fb
            class StringInputFB:
                msg: Input[STRING]

                def logic(self):
                    self.msg += " suffix"

    def test_static_fb_invocation_still_works(self):
        """FB invocation detection should still work for STATIC vars."""
        from datetime import timedelta

        from plx.framework import TON, Static, fb

        @fb
        class TimerFB:
            timer: Static[TON]
            run: Static[bool] = False

            def logic(self):
                self.timer(IN=self.run, PT=timedelta(seconds=1))

        pou = TimerFB.compile()
        # Should have produced an FBInvocation statement
        stmts = pou.networks[0].statements
        assert any(s.kind == "fb_invocation" for s in stmts)


# ---------------------------------------------------------------------------
# Fix #9: PlxProject.compile() is idempotent
# ---------------------------------------------------------------------------


class TestCompileIdempotent:
    def test_compile_twice_no_error(self):
        """Calling compile() twice on the same PlxProject should not raise."""
        from plx.framework import fb, program, project

        @fb
        class HelperFB:
            x: int = 0

            def logic(self):
                pass

        @program
        class Main:
            def logic(self):
                pass

        proj = project("TestIdempotent", pous=[Main, HelperFB])
        result1 = proj.compile()
        result2 = proj.compile()

        assert result1.name == result2.name
        assert len(result1.pous) == len(result2.pous)


# ---------------------------------------------------------------------------
# Fix #10: _format_init_param raises on None instead of producing "None"
# ---------------------------------------------------------------------------


class TestFormatInitParamNone:
    def test_none_value_raises(self):
        """Passing None as a dict value to _format_init_param should raise."""
        from plx.framework._descriptors import _format_init_param
        from plx.framework._errors import DeclarationError

        with pytest.raises(DeclarationError, match="None"):
            _format_init_param(None)

    def test_valid_dict_values_still_work(self):
        """Normal dict values should still format correctly."""
        from plx.framework._descriptors import _dict_to_iec_init

        result = _dict_to_iec_init({"PT": "T#5s", "IN": True})
        assert "PT := T#5s" in result
        assert "IN := TRUE" in result


# ---------------------------------------------------------------------------
# Fix #11: FOR loop var escaped with _safe_name() in Python export
# ---------------------------------------------------------------------------


class TestForLoopVarSafeName:
    def test_python_keyword_loop_var_escaped(self):
        """A FOR loop var that is a Python keyword should be escaped."""
        from plx.export.py import generate

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(
                temp_vars=[Variable(name="in_", data_type=_int_type())],
            ),
            networks=[
                Network(
                    statements=[
                        ForStatement(
                            loop_var="in",
                            from_expr=LiteralExpr(value="0"),
                            to_expr=LiteralExpr(value="10"),
                            body=[
                                Assignment(
                                    target=VariableRef(name="x"),
                                    value=LiteralExpr(value="0"),
                                ),
                            ],
                        ),
                    ]
                )
            ],
        )
        proj = Project(name="Test", pous=[pou])
        code = generate(proj)
        # Should have "in_" not bare "in" as the loop variable
        assert "for in_" in code
        assert "for in in" not in code

    def test_normal_loop_var_unchanged(self):
        """A non-keyword loop var should be emitted as-is."""
        from plx.export.py import generate

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(
                temp_vars=[Variable(name="i", data_type=_int_type())],
            ),
            networks=[
                Network(
                    statements=[
                        ForStatement(
                            loop_var="i",
                            from_expr=LiteralExpr(value="0"),
                            to_expr=LiteralExpr(value="10"),
                            body=[
                                Assignment(
                                    target=VariableRef(name="x"),
                                    value=LiteralExpr(value="0"),
                                ),
                            ],
                        ),
                    ]
                )
            ],
        )
        proj = Project(name="Test", pous=[pou])
        code = generate(proj)
        assert "for i in range" in code


# ---------------------------------------------------------------------------
# Fix #12: _try_format_fb_init bails on unrepresentable nested values
# ---------------------------------------------------------------------------


class TestTryFormatFBInit:
    def test_unrepresentable_nested_value_returns_none(self):
        """An unrepresentable nested value should make the whole function bail."""
        from plx.export.py._helpers import _try_format_fb_init

        # "FUNC_CALL(x)" is not representable as a Python literal
        result = _try_format_fb_init("(A := FUNC_CALL(x), B := 5)")
        assert result is None

    def test_representable_values_still_work(self):
        """Normal FB init values should produce valid Python dict literals."""
        from plx.export.py._helpers import _try_format_fb_init

        result = _try_format_fb_init("(Name := 'test', Count := 42)")
        assert result is not None
        assert '"Name"' in result
        assert '"Count"' in result
        assert "None" not in result


# ---------------------------------------------------------------------------
# Fix #13: SFCBody rejects orphan transitions when steps=[]
# ---------------------------------------------------------------------------


class TestSFCOrphanTransitions:
    def test_orphan_transition_with_empty_steps_rejected(self):
        """Transitions referencing nonexistent steps should be rejected."""
        from plx.model.sfc import SFCBody, Transition

        with pytest.raises(ValueError, match="unknown source step"):
            SFCBody(
                steps=[],
                transitions=[
                    Transition(
                        source_steps=["S1"],
                        target_steps=["S2"],
                        condition=LiteralExpr(value="TRUE"),
                    ),
                ],
            )

    def test_no_transitions_no_error(self):
        """Empty transitions with empty steps should be fine."""
        from plx.model.sfc import SFCBody

        body = SFCBody(steps=[], transitions=[])
        assert body.steps == []
        assert body.transitions == []

    def test_valid_transitions_accepted(self):
        """Transitions referencing existing steps should pass."""
        from plx.model.sfc import SFCBody, Step, Transition

        body = SFCBody(
            steps=[
                Step(name="S1", is_initial=True),
                Step(name="S2"),
            ],
            transitions=[
                Transition(
                    source_steps=["S1"],
                    target_steps=["S2"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        assert len(body.transitions) == 1


# ---------------------------------------------------------------------------
# Fix #14: FBInvocation._validate_instance_name rejects malformed paths
# ---------------------------------------------------------------------------


class TestFBInvocationInstanceNameValidation:
    def test_leading_dot_rejected(self):
        with pytest.raises(ValidationError):
            FBInvocation(instance_name=".a", fb_type="TON")

    def test_trailing_dot_rejected(self):
        with pytest.raises(ValidationError):
            FBInvocation(instance_name="a.", fb_type="TON")

    def test_double_dot_rejected(self):
        with pytest.raises(ValidationError):
            FBInvocation(instance_name="a..b", fb_type="TON")

    def test_bare_caret_rejected(self):
        with pytest.raises(ValidationError):
            FBInvocation(instance_name="^", fb_type="TON")

    def test_valid_dotted_path_accepted(self):
        inv = FBInvocation(instance_name="parent.child", fb_type="TON")
        assert inv.instance_name == "parent.child"

    def test_valid_caret_path_accepted(self):
        inv = FBInvocation(instance_name="SUPER^", fb_type="TON")
        assert inv.instance_name == "SUPER^"

    def test_valid_simple_name_accepted(self):
        inv = FBInvocation(instance_name="timer", fb_type="TON")
        assert inv.instance_name == "timer"


# ---------------------------------------------------------------------------
# Fix #15: TempFBInstanceRule no false positives on structs
# ---------------------------------------------------------------------------


class TestTempFBInstanceRuleStructs:
    def test_temp_struct_no_finding(self):
        """A VAR_TEMP of a struct type should NOT be flagged."""
        from plx.analyze import TempFBInstanceRule

        struct_type = StructType(
            name="MyStruct",
            members=[
                StructMember(name="x", data_type=_int_type()),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestPOU",
            interface=POUInterface(
                temp_vars=[Variable(name="s", data_type=NamedTypeRef(name="MyStruct"))],
            ),
            networks=[Network(statements=[])],
        )
        project = Project(
            name="TestProject",
            pous=[pou],
            data_types=[struct_type],
        )
        rule = TempFBInstanceRule()
        result = rule.analyze_project(project)
        assert len(result.findings) == 0

    def test_temp_fb_still_flagged(self):
        """A VAR_TEMP of an FB type should still be flagged."""
        from plx.analyze import TempFBInstanceRule

        fb_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MyFB",
            interface=POUInterface(),
            networks=[Network(statements=[])],
        )
        using_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestPOU",
            interface=POUInterface(
                temp_vars=[Variable(name="fb", data_type=NamedTypeRef(name="MyFB"))],
            ),
            networks=[Network(statements=[])],
        )
        project = Project(name="TestProject", pous=[fb_pou, using_pou])
        rule = TempFBInstanceRule()
        result = rule.analyze_project(project)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "temp-fb-instance"


# ---------------------------------------------------------------------------
# Fix #16: RecursiveCallRule and UnusedPOURule find calls in methods
# ---------------------------------------------------------------------------


class TestCallDetectionInMethods:
    def _make_fb_with_method_call(self, caller_name, callee_name):
        """Create an FB that calls callee_name from inside a method."""
        return POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name=caller_name,
            interface=POUInterface(
                static_vars=[Variable(name="inst", data_type=NamedTypeRef(name=callee_name))],
            ),
            methods=[
                Method(
                    name="DoWork",
                    access=AccessSpecifier.PUBLIC,
                    interface=POUInterface(),
                    networks=[
                        Network(
                            statements=[
                                FBInvocation(instance_name="inst", fb_type=callee_name),
                            ]
                        )
                    ],
                ),
            ],
            networks=[Network(statements=[])],
        )

    def test_unused_pou_rule_finds_call_in_method(self):
        """A POU called only from a method should NOT be flagged as unused."""
        from plx.analyze import UnusedPOURule

        callee = _make_project_pou("CalleeFB")
        caller = self._make_fb_with_method_call("CallerFB", "CalleeFB")
        project = Project(name="Test", pous=[caller, callee])
        rule = UnusedPOURule()
        result = rule.analyze_project(project)
        unused_names = {f.pou_name for f in result.findings}
        # CalleeFB should NOT be in the unused set
        assert "CalleeFB" not in unused_names

    def test_recursive_call_rule_detects_cycle_through_method(self):
        """A recursive cycle through a method should be detected."""
        from plx.analyze import RecursiveCallRule

        # A calls B from its method, B calls A from its network
        fb_a = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="A",
            interface=POUInterface(
                static_vars=[Variable(name="b", data_type=NamedTypeRef(name="B"))],
            ),
            methods=[
                Method(
                    name="Run",
                    access=AccessSpecifier.PUBLIC,
                    interface=POUInterface(),
                    networks=[
                        Network(
                            statements=[
                                FBInvocation(instance_name="b", fb_type="B"),
                            ]
                        )
                    ],
                ),
            ],
            networks=[Network(statements=[])],
        )
        fb_b = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="B",
            interface=POUInterface(
                static_vars=[Variable(name="a", data_type=NamedTypeRef(name="A"))],
            ),
            networks=[
                Network(
                    statements=[
                        FBInvocation(instance_name="a", fb_type="A"),
                    ]
                )
            ],
        )
        project = Project(name="Test", pous=[fb_a, fb_b])
        rule = RecursiveCallRule()
        result = rule.analyze_project(project)
        assert len(result.findings) > 0
        assert result.findings[0].rule_id == "recursive-call"


# ---------------------------------------------------------------------------
# Fix #17: IgnoredFBOutputRule finds invocations in actions
# ---------------------------------------------------------------------------


class TestIgnoredFBOutputRuleActions:
    def test_invocation_in_action_detected(self):
        """FB invoked in a POU action should be included in the invoked set."""
        from plx.analyze import IgnoredFBOutputRule

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestPOU",
            interface=POUInterface(
                static_vars=[
                    Variable(name="timer", data_type=NamedTypeRef(name="TON")),
                ],
            ),
            actions=[
                POUAction(
                    name="RunTimers",
                    body=[
                        Network(
                            statements=[
                                FBInvocation(
                                    instance_name="timer",
                                    fb_type="TON",
                                    inputs={"IN": LiteralExpr(value="TRUE")},
                                ),
                            ]
                        )
                    ],
                ),
            ],
            # Read timer.Q in the main network so it's not "ignored"
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="done"),
                            value=MemberAccessExpr(
                                struct=VariableRef(name="timer"),
                                member="Q",
                            ),
                        ),
                    ]
                )
            ],
        )
        project = Project(name="Test", pous=[pou])
        rule = IgnoredFBOutputRule()
        result = rule.analyze_project(project)
        # timer is invoked in action AND read in network → should NOT be flagged
        assert len(result.findings) == 0


# ---------------------------------------------------------------------------
# Fix #18: CrossTaskWriteRule no false positives on output vars
# ---------------------------------------------------------------------------


class TestCrossTaskWriteOutputVars:
    def test_output_vars_not_flagged_as_cross_task(self):
        """Output vars with the same name in different POUs should not conflict."""
        from plx.analyze import CrossTaskWriteRule

        prog_a = POU(
            pou_type=POUType.PROGRAM,
            name="ProgA",
            interface=POUInterface(
                output_vars=[Variable(name="valve", data_type=_bool_type())],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="valve"),
                            value=LiteralExpr(value="TRUE"),
                        ),
                    ]
                )
            ],
        )
        prog_b = POU(
            pou_type=POUType.PROGRAM,
            name="ProgB",
            interface=POUInterface(
                output_vars=[Variable(name="valve", data_type=_bool_type())],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="valve"),
                            value=LiteralExpr(value="FALSE"),
                        ),
                    ]
                )
            ],
        )
        project = Project(
            name="Test",
            pous=[prog_a, prog_b],
            tasks=[
                PeriodicTask(name="Task1", interval="T#10ms", assigned_pous=["ProgA"]),
                PeriodicTask(name="Task2", interval="T#20ms", assigned_pous=["ProgB"]),
            ],
        )
        rule = CrossTaskWriteRule()
        result = rule.analyze_project(project)
        valve_findings = [f for f in result.findings if "valve" in f.message]
        assert len(valve_findings) == 0

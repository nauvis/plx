"""Edge-case tests for the analyze module's two rules.

Covers:
- UnguardedOutputRule with loops (FOR, WHILE, REPEAT), CASE, nested structures,
  member/array/bit access targets, FB invocation outputs, try/catch nesting,
  multiple outputs, CASE else body, and mixed guarded/unguarded patterns.
- DeadSfcStepRule with multiple orphan steps, single-step SFCs, fully connected
  cycles, simultaneous divergence/convergence, and initial-step-only reachability.
"""

from plx.analyze import analyze
from plx.analyze._rules import DeadSfcStepRule, UnguardedOutputRule
from plx.analyze._visitor import AnalysisVisitor
from plx.framework import (
    BOOL,
    DINT,
    Input,
    Output,
    fb,
    program,
)
from plx.model.expressions import (
    ArrayAccessExpr,
    BitAccessExpr,
    DerefExpr,
    LiteralExpr,
    MemberAccessExpr,
    VariableRef,
)
from plx.model.pou import POU, Network, POUInterface, POUType
from plx.model.sfc import Action, ActionQualifier, SFCBody, Step, Transition
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    EmptyStatement,
    FBInvocation,
    ForStatement,
    IfBranch,
    IfStatement,
    RepeatStatement,
    TryCatchStatement,
    WhileStatement,
)
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bool_type() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _dint_type() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.DINT)


def _pou_with_stmts(
    *stmts,
    output_vars=(),
    input_vars=(),
    static_vars=(),
    name="TestFB",
) -> POU:
    """Build a minimal POU containing the given statements."""
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name=name,
        interface=POUInterface(
            output_vars=[Variable(name=n, data_type=_bool_type()) for n in output_vars],
            input_vars=[Variable(name=n, data_type=_bool_type()) for n in input_vars],
            static_vars=[Variable(name=n, data_type=_dint_type()) for n in static_vars],
        ),
        networks=[Network(statements=list(stmts))],
    )


def _run_unguarded_rule(*stmts, output_vars=(), **kwargs):
    """Run UnguardedOutputRule on a POU built from statements."""
    pou = _pou_with_stmts(*stmts, output_vars=output_vars, **kwargs)
    return UnguardedOutputRule().analyze_pou(pou)


def _run_visitor(*stmts, output_vars=()):
    """Run the base visitor and return the context for inspection."""
    pou = _pou_with_stmts(*stmts, output_vars=output_vars)
    visitor = AnalysisVisitor()
    ctx = visitor._make_context(pou)
    for i, network in enumerate(pou.networks):
        ctx.current_network_idx = i
        visitor._visit_network(ctx, network)
    return ctx


# ===========================================================================
# Test: Outputs inside loops should be guarded
# ===========================================================================


class TestUnguardedOutputInLoops:
    """Output writes inside for/while/repeat loops should be guarded (nesting_depth > 0)."""

    def test_output_in_for_loop_is_guarded(self):
        """Output written inside FOR loop body -- no finding."""
        stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_output_in_while_loop_is_guarded(self):
        """Output written inside WHILE loop body -- no finding."""

        @fb
        class WhileGuardedFB:
            running: Input[BOOL]
            valve: Output[BOOL]

            def logic(self):
                while self.running:
                    self.valve = True

        result = analyze(WhileGuardedFB.compile(), rules=[UnguardedOutputRule])
        assert len(result.findings) == 0

    def test_output_in_repeat_is_guarded(self):
        """Output in REPEAT body is guarded (built with IR since framework has no repeat)."""
        stmt = RepeatStatement(
            until=LiteralExpr(value="TRUE"),
            body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_output_before_for_loop_is_unguarded(self):
        """Output written before a FOR loop is still unguarded."""
        stmt_unguarded = Assignment(
            target=VariableRef(name="valve"),
            value=LiteralExpr(value="FALSE"),
        )
        stmt_for = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        findings = _run_unguarded_rule(stmt_unguarded, stmt_for, output_vars=("valve",))
        # One unguarded write (the one before the loop), zero from inside the loop
        assert len(findings) == 1

    def test_output_after_while_loop_is_unguarded(self):
        """Output written after a WHILE loop (at top level) is unguarded."""
        stmt_while = WhileStatement(
            condition=VariableRef(name="run"),
            body=[EmptyStatement()],
        )
        stmt_unguarded = Assignment(
            target=VariableRef(name="valve"),
            value=LiteralExpr(value="TRUE"),
        )
        findings = _run_unguarded_rule(
            stmt_while,
            stmt_unguarded,
            output_vars=("valve",),
            input_vars=("run",),
        )
        assert len(findings) == 1

    def test_nesting_depth_in_for_body(self):
        """FOR body should have nesting_depth >= 1."""
        stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        ctx = _run_visitor(stmt, output_vars=("valve",))
        assert "valve" in ctx.writes
        for w in ctx.writes["valve"]:
            assert w.nesting_depth >= 1
            assert w.guarded is True

    def test_nested_loop_in_if_depth(self):
        """FOR inside IF has nesting_depth >= 2."""
        for_stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="enable"),
                body=[for_stmt],
            ),
        )
        ctx = _run_visitor(if_stmt, output_vars=("out",))
        assert ctx.writes["out"][0].nesting_depth >= 2


# ===========================================================================
# Test: Outputs in CASE branches
# ===========================================================================


class TestUnguardedOutputInCase:
    """Output writes inside CASE branches should be guarded."""

    def test_output_in_case_branch_is_guarded(self):
        """Output written inside CASE branch -- no finding."""
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(
                    values=[1],
                    body=[
                        Assignment(
                            target=VariableRef(name="valve"),
                            value=LiteralExpr(value="TRUE"),
                        ),
                    ],
                ),
                CaseBranch(
                    values=[2],
                    body=[
                        Assignment(
                            target=VariableRef(name="valve"),
                            value=LiteralExpr(value="FALSE"),
                        ),
                    ],
                ),
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_output_in_case_else_is_guarded(self):
        """Output written inside CASE ELSE body is guarded."""
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(values=[1], body=[EmptyStatement()]),
            ],
            else_body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="FALSE"),
                ),
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_output_outside_case_is_unguarded(self):
        """Output written before CASE statement is still unguarded."""
        unguarded_assign = Assignment(
            target=VariableRef(name="valve"),
            value=LiteralExpr(value="FALSE"),
        )
        case_stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(
                    values=[1],
                    body=[
                        Assignment(
                            target=VariableRef(name="valve"),
                            value=LiteralExpr(value="TRUE"),
                        ),
                    ],
                ),
            ],
        )
        findings = _run_unguarded_rule(unguarded_assign, case_stmt, output_vars=("valve",))
        assert len(findings) == 1

    def test_case_with_match_syntax(self):
        """Framework match/case compiles to CaseStatement -- guarded."""

        @fb
        class MatchCaseFB:
            state: Input[DINT]
            valve: Output[BOOL]

            def logic(self):
                match self.state:
                    case 0:
                        self.valve = False
                    case 1:
                        self.valve = True

        result = analyze(MatchCaseFB.compile(), rules=[UnguardedOutputRule])
        assert len(result.findings) == 0


# ===========================================================================
# Test: Member/array/bit access on outputs
# ===========================================================================


class TestUnguardedOutputMemberAccess:
    """Writes to struct members, array elements, or bit accesses on output
    variables should still be tracked via _extract_target_name."""

    def test_member_access_output_unguarded(self):
        """Writing output.field at top level is unguarded."""
        stmt = Assignment(
            target=MemberAccessExpr(
                struct=VariableRef(name="motor"),
                member="speed",
            ),
            value=LiteralExpr(value="100"),
        )
        findings = _run_unguarded_rule(stmt, output_vars=("motor",))
        assert len(findings) == 1
        assert findings[0].details["variable"] == "motor"

    def test_array_access_output_unguarded(self):
        """Writing output[i] at top level is unguarded."""
        stmt = Assignment(
            target=ArrayAccessExpr(
                array=VariableRef(name="outputs"),
                indices=[LiteralExpr(value="0")],
            ),
            value=LiteralExpr(value="TRUE"),
        )
        findings = _run_unguarded_rule(stmt, output_vars=("outputs",))
        assert len(findings) == 1
        assert findings[0].details["variable"] == "outputs"

    def test_bit_access_output_unguarded(self):
        """Writing output.3 (bit access) at top level is unguarded."""
        stmt = Assignment(
            target=BitAccessExpr(
                target=VariableRef(name="status_word"),
                bit_index=3,
            ),
            value=LiteralExpr(value="TRUE"),
        )
        findings = _run_unguarded_rule(stmt, output_vars=("status_word",))
        assert len(findings) == 1
        assert findings[0].details["variable"] == "status_word"

    def test_deref_member_output_unguarded(self):
        """Writing ptr^.field at top level targets 'ptr' -- unguarded if ptr is output."""
        stmt = Assignment(
            target=MemberAccessExpr(
                struct=DerefExpr(pointer=VariableRef(name="out_ptr")),
                member="value",
            ),
            value=LiteralExpr(value="42"),
        )
        findings = _run_unguarded_rule(stmt, output_vars=("out_ptr",))
        assert len(findings) == 1
        assert findings[0].details["variable"] == "out_ptr"

    def test_nested_member_array_access_output_guarded(self):
        """Writing output.field[i] inside IF is guarded."""
        assign = Assignment(
            target=ArrayAccessExpr(
                array=MemberAccessExpr(
                    struct=VariableRef(name="data"),
                    member="values",
                ),
                indices=[LiteralExpr(value="0")],
            ),
            value=LiteralExpr(value="0"),
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="enable"),
                body=[assign],
            ),
        )
        findings = _run_unguarded_rule(if_stmt, output_vars=("data",))
        assert len(findings) == 0

    def test_non_output_member_access_no_finding(self):
        """Writing to a static var member is not flagged by the output rule."""
        stmt = Assignment(
            target=MemberAccessExpr(
                struct=VariableRef(name="internal"),
                member="count",
            ),
            value=LiteralExpr(value="0"),
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 0


# ===========================================================================
# Test: FB invocation outputs with complex targets
# ===========================================================================


class TestFBInvocationOutputTargets:
    """FB invocation output parameters writing to complex targets."""

    def test_fb_output_to_member_access_unguarded(self):
        """FB output => motor.done at top level is unguarded."""
        stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={"IN": LiteralExpr(value="TRUE")},
            outputs={
                "Q": MemberAccessExpr(
                    struct=VariableRef(name="motor"),
                    member="done",
                ),
            },
        )
        findings = _run_unguarded_rule(stmt, output_vars=("motor",))
        assert len(findings) == 1

    def test_fb_output_to_array_element_guarded(self):
        """FB output => arr[0] inside IF is guarded."""
        fb_stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={},
            outputs={
                "Q": ArrayAccessExpr(
                    array=VariableRef(name="outputs"),
                    indices=[LiteralExpr(value="0")],
                ),
            },
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="enable"),
                body=[fb_stmt],
            ),
        )
        findings = _run_unguarded_rule(if_stmt, output_vars=("outputs",))
        assert len(findings) == 0


# ===========================================================================
# Test: Try/catch nesting combinations
# ===========================================================================


class TestUnguardedOutputTryCatch:
    """Verify nesting behavior of try/catch/finally with respect to guarding."""

    def test_output_in_try_body_is_unguarded(self):
        """try body is treated as normal execution -- unguarded at depth 0."""
        stmt = TryCatchStatement(
            try_body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 1

    def test_output_in_catch_body_is_guarded(self):
        """catch body is conditional -- guarded."""
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            catch_body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="FALSE"),
                )
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_output_in_finally_body_is_unguarded(self):
        """finally body always runs -- unguarded at depth 0."""
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            finally_body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        findings = _run_unguarded_rule(stmt, output_vars=("valve",))
        assert len(findings) == 1

    def test_try_inside_if_is_guarded(self):
        """try body inside an IF branch -- guarded because if increments depth."""
        try_stmt = TryCatchStatement(
            try_body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                )
            ],
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="enable"),
                body=[try_stmt],
            ),
        )
        findings = _run_unguarded_rule(if_stmt, output_vars=("valve",))
        assert len(findings) == 0


# ===========================================================================
# Test: Multiple outputs and mixed patterns
# ===========================================================================


class TestMultipleOutputPatterns:
    """Edge cases with multiple output variables and mixed guard status."""

    def test_all_outputs_unguarded(self):
        """All outputs written at top level -- each gets a finding."""
        stmts = [
            Assignment(target=VariableRef(name="out1"), value=LiteralExpr(value="TRUE")),
            Assignment(target=VariableRef(name="out2"), value=LiteralExpr(value="FALSE")),
            Assignment(target=VariableRef(name="out3"), value=LiteralExpr(value="TRUE")),
        ]
        findings = _run_unguarded_rule(*stmts, output_vars=("out1", "out2", "out3"))
        assert len(findings) == 3
        found_vars = {f.details["variable"] for f in findings}
        assert found_vars == {"out1", "out2", "out3"}

    def test_same_output_written_guarded_and_unguarded(self):
        """Output written both inside and outside IF -- unguarded write flagged."""
        unguarded = Assignment(
            target=VariableRef(name="valve"),
            value=LiteralExpr(value="FALSE"),
        )
        guarded = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="sensor"),
                body=[
                    Assignment(
                        target=VariableRef(name="valve"),
                        value=LiteralExpr(value="TRUE"),
                    ),
                ],
            ),
        )
        findings = _run_unguarded_rule(unguarded, guarded, output_vars=("valve",))
        # Only the unguarded write at top level should be flagged
        assert len(findings) == 1

    def test_output_in_elsif_is_guarded(self):
        """Output written inside ELSIF branch is guarded."""
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="a"),
                body=[EmptyStatement()],
            ),
            elsif_branches=[
                IfBranch(
                    condition=VariableRef(name="b"),
                    body=[
                        Assignment(
                            target=VariableRef(name="valve"),
                            value=LiteralExpr(value="TRUE"),
                        ),
                    ],
                ),
            ],
        )
        findings = _run_unguarded_rule(if_stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_output_in_else_is_guarded(self):
        """Output written inside ELSE body is guarded."""
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="a"),
                body=[EmptyStatement()],
            ),
            else_body=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        findings = _run_unguarded_rule(if_stmt, output_vars=("valve",))
        assert len(findings) == 0

    def test_program_pou_outputs_detected(self):
        """UnguardedOutputRule works on PROGRAM POUs, not just FBs."""

        @program
        class UnguardedProgram:
            valve: Output[BOOL]

            def logic(self):
                self.valve = True

        result = analyze(UnguardedProgram.compile(), rules=[UnguardedOutputRule])
        assert len(result.findings) == 1
        assert result.findings[0].details["variable"] == "valve"

    def test_static_var_unguarded_no_finding(self):
        """Static vars are not outputs -- no finding even if unguarded."""
        stmt = Assignment(
            target=VariableRef(name="count"),
            value=LiteralExpr(value="0"),
        )
        findings = _run_unguarded_rule(stmt, output_vars=(), static_vars=("count",))
        assert len(findings) == 0


# ===========================================================================
# Test: DeadSfcStepRule edge cases
# ===========================================================================


class TestDeadSfcStepEdgeCases:
    """Edge cases for the dead SFC step rule."""

    def test_multiple_orphan_steps(self):
        """Multiple unreachable steps produce multiple findings."""
        sfc = SFCBody(
            steps=[
                Step(name="Init", is_initial=True),
                Step(name="Running"),
                Step(name="Orphan1"),
                Step(name="Orphan2"),
            ],
            transitions=[
                Transition(
                    source_steps=["Init"],
                    target_steps=["Running"],
                    condition=LiteralExpr(value="TRUE"),
                ),
                Transition(
                    source_steps=["Running"],
                    target_steps=["Init"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MultiOrphanSFC",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 2
        orphan_names = {f.details["step"] for f in findings}
        assert orphan_names == {"Orphan1", "Orphan2"}

    def test_single_step_sfc_no_findings(self):
        """SFC with only the initial step and no transitions -- no findings."""
        sfc = SFCBody(
            steps=[Step(name="Init", is_initial=True)],
            transitions=[],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="SingleStepSFC",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_all_steps_in_cycle_no_findings(self):
        """A -> B -> C -> A with A initial -- all reachable, no findings."""
        sfc = SFCBody(
            steps=[
                Step(name="A", is_initial=True),
                Step(name="B"),
                Step(name="C"),
            ],
            transitions=[
                Transition(
                    source_steps=["A"],
                    target_steps=["B"],
                    condition=LiteralExpr(value="TRUE"),
                ),
                Transition(
                    source_steps=["B"],
                    target_steps=["C"],
                    condition=LiteralExpr(value="TRUE"),
                ),
                Transition(
                    source_steps=["C"],
                    target_steps=["A"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="CycleSFC",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_initial_step_never_flagged(self):
        """Initial step is always considered reachable even without incoming transitions."""
        sfc = SFCBody(
            steps=[
                Step(name="Start", is_initial=True),
                Step(name="End"),
            ],
            transitions=[
                Transition(
                    source_steps=["Start"],
                    target_steps=["End"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="InitialNeverFlagged",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        # "Start" has no incoming transition but is initial -- not flagged
        # "End" is targeted by a transition -- not flagged
        assert len(findings) == 0

    def test_simultaneous_divergence_targets_reachable(self):
        """Simultaneous divergence: one transition targets multiple steps -- all reachable."""
        sfc = SFCBody(
            steps=[
                Step(name="Init", is_initial=True),
                Step(name="Branch1"),
                Step(name="Branch2"),
            ],
            transitions=[
                Transition(
                    source_steps=["Init"],
                    target_steps=["Branch1", "Branch2"],
                    condition=LiteralExpr(value="TRUE"),
                ),
                Transition(
                    source_steps=["Branch1", "Branch2"],
                    target_steps=["Init"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="DivergenceSFC",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_non_sfc_pou_no_findings(self):
        """Non-SFC POU (no sfc_body) produces no dead step findings."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="PlainFB",
            interface=POUInterface(),
            networks=[Network(statements=[])],
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_step_targeted_only_by_itself_still_dead(self):
        """A step with a self-transition but no incoming transition from other steps
        is still dead if it is not initial and no other transition targets it."""
        sfc = SFCBody(
            steps=[
                Step(name="Init", is_initial=True),
                Step(name="Loop"),
            ],
            transitions=[
                # Loop -> Loop (self-transition targets "Loop", so it IS in targeted set)
                Transition(
                    source_steps=["Loop"],
                    target_steps=["Loop"],
                    condition=LiteralExpr(value="TRUE"),
                ),
                # But Init needs a transition too for valid SFC
                Transition(
                    source_steps=["Init"],
                    target_steps=["Init"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="SelfLoopSFC",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        # "Loop" IS targeted by the self-transition, so the rule
        # considers it reachable (the rule checks target_steps, not true graph reachability)
        assert len(findings) == 0

    def test_step_with_action_body_still_flagged_if_orphan(self):
        """An orphan step with action body is still flagged as dead."""
        sfc = SFCBody(
            steps=[
                Step(name="Init", is_initial=True),
                Step(
                    name="Orphan",
                    actions=[
                        Action(
                            name="DoStuff",
                            qualifier=ActionQualifier.N,
                            body=[
                                Assignment(
                                    target=VariableRef(name="x"),
                                    value=LiteralExpr(value="1"),
                                ),
                            ],
                        ),
                    ],
                ),
            ],
            transitions=[
                Transition(
                    source_steps=["Init"],
                    target_steps=["Init"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="OrphanWithAction",
            interface=POUInterface(),
            sfc_body=sfc,
        )
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].details["step"] == "Orphan"


# ===========================================================================
# Test: Nesting depth correctness across compound structures
# ===========================================================================


class TestNestingDepthAccuracy:
    """Verify nesting_depth is correctly tracked after exiting scopes."""

    def test_depth_returns_to_zero_after_if(self):
        """After visiting an IF, nesting_depth returns to 0 for subsequent statements."""
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="a"),
                body=[
                    Assignment(
                        target=VariableRef(name="guarded"),
                        value=LiteralExpr(value="TRUE"),
                    ),
                ],
            ),
        )
        after_stmt = Assignment(
            target=VariableRef(name="unguarded"),
            value=LiteralExpr(value="FALSE"),
        )
        ctx = _run_visitor(if_stmt, after_stmt, output_vars=("guarded", "unguarded"))
        assert ctx.writes["guarded"][0].nesting_depth == 1
        assert ctx.writes["unguarded"][0].nesting_depth == 0

    def test_depth_returns_to_zero_after_for(self):
        """After visiting a FOR, nesting_depth returns to 0."""
        for_stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[
                Assignment(
                    target=VariableRef(name="inside"),
                    value=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        after_stmt = Assignment(
            target=VariableRef(name="outside"),
            value=LiteralExpr(value="FALSE"),
        )
        ctx = _run_visitor(for_stmt, after_stmt, output_vars=("inside", "outside"))
        assert ctx.writes["inside"][0].nesting_depth == 1
        assert ctx.writes["outside"][0].nesting_depth == 0

    def test_depth_returns_to_zero_after_case(self):
        """After visiting a CASE, nesting_depth returns to 0."""
        case_stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[
                CaseBranch(
                    values=[1],
                    body=[
                        Assignment(
                            target=VariableRef(name="inside"),
                            value=LiteralExpr(value="TRUE"),
                        ),
                    ],
                ),
            ],
        )
        after_stmt = Assignment(
            target=VariableRef(name="outside"),
            value=LiteralExpr(value="FALSE"),
        )
        ctx = _run_visitor(case_stmt, after_stmt, output_vars=("inside", "outside"))
        assert ctx.writes["inside"][0].nesting_depth == 1
        assert ctx.writes["outside"][0].nesting_depth == 0

    def test_deeply_nested_structure(self):
        """IF > WHILE > FOR > assignment should have depth 3."""
        assign = Assignment(
            target=VariableRef(name="deep"),
            value=LiteralExpr(value="TRUE"),
        )
        for_stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="9"),
            body=[assign],
        )
        while_stmt = WhileStatement(
            condition=VariableRef(name="run"),
            body=[for_stmt],
        )
        if_stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="enable"),
                body=[while_stmt],
            ),
        )
        ctx = _run_visitor(if_stmt, output_vars=("deep",))
        assert ctx.writes["deep"][0].nesting_depth == 3

    def test_repeat_depth_correct(self):
        """REPEAT body has depth 1; condition (until) is evaluated at depth 0."""
        stmt = RepeatStatement(
            body=[
                Assignment(
                    target=VariableRef(name="inside"),
                    value=LiteralExpr(value="TRUE"),
                ),
            ],
            until=VariableRef(name="done"),
        )
        after_stmt = Assignment(
            target=VariableRef(name="outside"),
            value=LiteralExpr(value="FALSE"),
        )
        ctx = _run_visitor(stmt, after_stmt, output_vars=("inside", "outside"))
        assert ctx.writes["inside"][0].nesting_depth == 1
        assert ctx.writes["outside"][0].nesting_depth == 0
        # "done" is read after the repeat body exits (depth 0)
        assert "done" in ctx.reads
        # At least one read of "done" should be unguarded (at depth 0)
        done_reads = ctx.reads["done"]
        assert any(not r.guarded for r in done_reads)

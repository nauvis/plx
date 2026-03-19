"""Tests for the static analysis framework."""

import pytest

from plx.analyze import (
    ALL_RULES,
    AnalysisResult,
    AnalysisVisitor,
    Finding,
    Severity,
    analyze,
)
from plx.analyze._context import AnalysisContext, ReadInfo, WriteInfo
from plx.analyze._rules import (
    DeadSfcStepRule,
    EmptyBodyRule,
    ForCounterWriteRule,
    MissingCaseElseRule,
    MultipleOutputWriteRule,
    RealEqualityRule,
    SfcMultipleInitialStepsRule,
    SfcNoInitialStepRule,
    TempFBInstanceRule,
    UnguardedOutputRule,
    UnusedInputRule,
    UnusedOutputRule,
    UnusedVariableRule,
    WriteToInputRule,
)
from plx.framework import (
    BOOL,
    DINT,
    INT,
    REAL,
    fb,
    Input,
    Output,
    program,
    project,
    sfc,
    step,
    transition,
    Field,
)
from plx.model.pou import (
    Method,
    Network,
    POU,
    POUAction,
    POUInterface,
    POUType,
    Property,
    PropertyAccessor,
)
from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    DerefExpr,
    LiteralExpr,
    MemberAccessExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.statements import (
    Assignment,
    EmptyStatement,
    FBInvocation,
    JumpStatement,
    LabelStatement,
    PragmaStatement,
    TryCatchStatement,
)
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
)
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# Helper: compile a decorated class to POU
# ---------------------------------------------------------------------------


def _compile_pou(cls) -> POU:
    return cls.compile()


def _compile_project(*classes, **kwargs):
    return project("Test", pous=list(classes), **kwargs).compile()


# ---------------------------------------------------------------------------
# Test fixtures: small FBs/programs for analysis
# ---------------------------------------------------------------------------


@fb
class GuardedOutputFB:
    """Output only written inside an if — should produce no findings."""

    sensor: Input[BOOL]
    valve: Output[BOOL]

    def logic(self):
        if self.sensor:
            self.valve = True
        else:
            self.valve = False


@fb
class UnguardedOutputFB:
    """Output written unconditionally at top level."""

    valve: Output[BOOL]

    def logic(self):
        self.valve = True


@fb
class MixedOutputFB:
    """One guarded output, one unguarded."""

    sensor: Input[BOOL]
    guarded_out: Output[BOOL]
    unguarded_out: Output[BOOL]

    def logic(self):
        self.unguarded_out = False
        if self.sensor:
            self.guarded_out = True


@fb
class NestedGuardedFB:
    """Output written inside nested if — still guarded."""

    a: Input[BOOL]
    b: Input[BOOL]
    out: Output[BOOL]

    def logic(self):
        if self.a:
            if self.b:
                self.out = True


@fb
class EmptyFB:
    """No logic, no variables."""

    def logic(self):
        pass


@fb
class StaticOnlyFB:
    """Only static vars, no outputs."""

    count: INT

    def logic(self):
        self.count = self.count + 1


@sfc
class ReachableSFC:
    """All steps are reachable via transitions."""

    cmd: Input[BOOL]

    IDLE = step(initial=True)
    RUNNING = step()

    @IDLE.action
    def idle_act(self):
        pass

    @RUNNING.action
    def run_act(self):
        pass

    @transition(IDLE >> RUNNING)
    def start(self):
        return self.cmd

    @transition(RUNNING >> IDLE)
    def stop(self):
        return not self.cmd


@sfc
class DeadStepSFC:
    """ORPHAN step is never targeted by any transition."""

    cmd: Input[BOOL]

    IDLE = step(initial=True)
    RUNNING = step()
    ORPHAN = step()

    @IDLE.action
    def idle_act(self):
        pass

    @RUNNING.action
    def run_act(self):
        pass

    @ORPHAN.action
    def orphan_act(self):
        pass

    @transition(IDLE >> RUNNING)
    def start(self):
        return self.cmd

    @transition(RUNNING >> IDLE)
    def stop(self):
        return not self.cmd


# ===========================================================================
# Test: Visitor framework basics
# ===========================================================================


class TestVisitorFramework:
    def test_empty_pou_no_crash(self):
        pou = _compile_pou(EmptyFB)
        visitor = AnalysisVisitor()
        findings = visitor.analyze_pou(pou)
        assert findings == []

    def test_writes_recorded(self):
        pou = _compile_pou(UnguardedOutputFB)
        visitor = AnalysisVisitor()
        ctx = visitor._make_context(pou)
        visitor.on_pou_enter(ctx)
        for i, network in enumerate(pou.networks):
            ctx.current_network_idx = i
            visitor._visit_network(ctx, network)
        # "valve" should have at least one write
        assert "valve" in ctx.writes
        assert len(ctx.writes["valve"]) >= 1

    def test_writes_guarded_flag(self):
        pou = _compile_pou(GuardedOutputFB)
        visitor = AnalysisVisitor()
        ctx = visitor._make_context(pou)
        visitor.on_pou_enter(ctx)
        for i, network in enumerate(pou.networks):
            ctx.current_network_idx = i
            visitor._visit_network(ctx, network)
        # All writes to "valve" should be guarded
        assert "valve" in ctx.writes
        for w in ctx.writes["valve"]:
            assert w.guarded is True

    def test_nesting_depth_tracks_correctly(self):
        pou = _compile_pou(NestedGuardedFB)
        visitor = AnalysisVisitor()
        ctx = visitor._make_context(pou)
        visitor.on_pou_enter(ctx)
        for i, network in enumerate(pou.networks):
            ctx.current_network_idx = i
            visitor._visit_network(ctx, network)
        # Write to "out" is inside nested if — depth >= 2
        assert "out" in ctx.writes
        for w in ctx.writes["out"]:
            assert w.nesting_depth >= 2

    def test_reads_collected(self):
        pou = _compile_pou(GuardedOutputFB)
        visitor = AnalysisVisitor()
        ctx = visitor._make_context(pou)
        visitor.on_pou_enter(ctx)
        for i, network in enumerate(pou.networks):
            ctx.current_network_idx = i
            visitor._visit_network(ctx, network)
        assert "sensor" in ctx.reads

    def test_output_names_precomputed(self):
        pou = _compile_pou(MixedOutputFB)
        ctx = AnalysisVisitor._make_context(pou)
        assert "guarded_out" in ctx.output_names
        assert "unguarded_out" in ctx.output_names
        assert "sensor" not in ctx.output_names

    def test_input_names_precomputed(self):
        pou = _compile_pou(MixedOutputFB)
        ctx = AnalysisVisitor._make_context(pou)
        assert "sensor" in ctx.input_names
        assert "guarded_out" not in ctx.input_names

    def test_project_level_analysis(self):
        proj = _compile_project(EmptyFB, StaticOnlyFB)
        visitor = AnalysisVisitor()
        result = visitor.analyze_project(proj)
        assert result.pou_count == 2
        assert result.findings == []

    def test_static_var_write_not_output(self):
        pou = _compile_pou(StaticOnlyFB)
        visitor = AnalysisVisitor()
        ctx = visitor._make_context(pou)
        # "count" is a static var, not an output
        assert "count" not in ctx.output_names


# ===========================================================================
# Test: UnguardedOutputRule
# ===========================================================================


class TestUnguardedOutputRule:
    def test_guarded_output_no_finding(self):
        pou = _compile_pou(GuardedOutputFB)
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        # All outputs are inside if/else — no findings
        assert len(findings) == 0

    def test_unconditional_output_finding(self):
        pou = _compile_pou(UnguardedOutputFB)
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "unguarded-output"
        assert f.severity == Severity.WARNING
        assert f.pou_name == "UnguardedOutputFB"
        assert "valve" in f.message
        assert f.details["variable"] == "valve"

    def test_mixed_outputs(self):
        pou = _compile_pou(MixedOutputFB)
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        # Only unguarded_out should be flagged
        assert len(findings) == 1
        assert findings[0].details["variable"] == "unguarded_out"

    def test_nested_if_still_guarded(self):
        pou = _compile_pou(NestedGuardedFB)
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_no_outputs_no_findings(self):
        pou = _compile_pou(StaticOnlyFB)
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_empty_fb_no_findings(self):
        pou = _compile_pou(EmptyFB)
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0


# ===========================================================================
# Test: DeadSfcStepRule
# ===========================================================================


class TestDeadSfcStepRule:
    def test_all_steps_reachable_no_finding(self):
        pou = _compile_pou(ReachableSFC)
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0

    def test_orphan_step_finding(self):
        pou = _compile_pou(DeadStepSFC)
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "sfc-dead-step"
        assert f.severity == Severity.WARNING
        assert "ORPHAN" in f.message
        assert f.details["step"] == "ORPHAN"

    def test_non_sfc_pou_no_crash(self):
        pou = _compile_pou(GuardedOutputFB)
        rule = DeadSfcStepRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 0


# ===========================================================================
# Test: analyze() public API
# ===========================================================================


class TestAnalyzeAPI:
    def test_project_all_rules(self):
        proj = _compile_project(UnguardedOutputFB, GuardedOutputFB)
        result = analyze(proj)
        assert isinstance(result, AnalysisResult)
        assert result.pou_count == 2
        assert result.rule_count == len(ALL_RULES)
        # At least the unguarded-output finding
        unguarded = [f for f in result.findings if f.rule_id == "unguarded-output"]
        assert len(unguarded) >= 1

    def test_single_pou(self):
        pou = _compile_pou(UnguardedOutputFB)
        result = analyze(pou)
        assert result.pou_count == 1
        assert len(result.findings) >= 1

    def test_custom_rule_list(self):
        proj = _compile_project(UnguardedOutputFB)
        # Only run the SFC rule — should find nothing on a non-SFC POU
        result = analyze(proj, rules=[DeadSfcStepRule])
        assert result.rule_count == 1
        assert len(result.findings) == 0

    def test_empty_rule_list(self):
        proj = _compile_project(UnguardedOutputFB)
        result = analyze(proj, rules=[])
        assert result.rule_count == 0
        assert result.findings == []

    def test_result_counts_correct(self):
        proj = _compile_project(
            UnguardedOutputFB, GuardedOutputFB, EmptyFB
        )
        result = analyze(proj)
        assert result.pou_count == 3

    def test_sfc_project(self):
        proj = _compile_project(DeadStepSFC)
        result = analyze(proj)
        dead = [f for f in result.findings if f.rule_id == "sfc-dead-step"]
        assert len(dead) == 1

    def test_mixed_project(self):
        """Project with both ST and SFC POUs runs all rules correctly."""
        proj = _compile_project(UnguardedOutputFB, DeadStepSFC)
        result = analyze(proj)
        assert result.pou_count == 2
        unguarded = [f for f in result.findings if f.rule_id == "unguarded-output"]
        dead = [f for f in result.findings if f.rule_id == "sfc-dead-step"]
        assert len(unguarded) >= 1
        assert len(dead) == 1


# ===========================================================================
# Test: Finding model
# ===========================================================================


class TestFindingModel:
    def test_finding_serialization(self):
        f = Finding(
            rule_id="test-rule",
            severity=Severity.WARNING,
            pou_name="TestFB",
            message="Test message",
            location="network 0 -> if_branch",
            details={"key": "value"},
        )
        d = f.model_dump()
        assert d["rule_id"] == "test-rule"
        assert d["severity"] == "warning"
        roundtrip = Finding.model_validate(d)
        assert roundtrip == f

    def test_analysis_result_serialization(self):
        result = AnalysisResult(
            findings=[
                Finding(
                    rule_id="test",
                    severity=Severity.INFO,
                    pou_name="X",
                    message="msg",
                )
            ],
            pou_count=1,
            rule_count=1,
        )
        j = result.model_dump_json()
        roundtrip = AnalysisResult.model_validate_json(j)
        assert roundtrip == result


# ===========================================================================
# Test: visitor handles newly added statement types
# ===========================================================================

def _bool_type() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _pou_with_stmts(*stmts, output_vars=()) -> POU:
    """Build a minimal POU containing the given statements."""
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name="TestFB",
        interface=POUInterface(
            output_vars=[
                Variable(name=name, data_type=_bool_type())
                for name in output_vars
            ]
        ),
        networks=[Network(statements=list(stmts))],
    )


def _run_visitor(*stmts, output_vars=()) -> AnalysisContext:
    pou = _pou_with_stmts(*stmts, output_vars=output_vars)
    visitor = AnalysisVisitor()
    ctx = visitor._make_context(pou)
    for i, network in enumerate(pou.networks):
        ctx.current_network_idx = i
        visitor._visit_network(ctx, network)
    return ctx


class TestVisitorNewStatements:
    def test_pragma_no_crash(self):
        ctx = _run_visitor(PragmaStatement(text="{attribute 'foo'}"))
        assert ctx.findings == []

    def test_jump_no_crash(self):
        ctx = _run_visitor(JumpStatement(label="loop_top"))
        assert ctx.findings == []

    def test_label_no_crash(self):
        ctx = _run_visitor(LabelStatement(name="loop_top"))
        assert ctx.findings == []

    def test_try_body_writes_recorded(self):
        """Assignments inside try body are visible to the visitor."""
        stmt = TryCatchStatement(
            try_body=[
                Assignment(
                    target=VariableRef(name="flag"),
                    value=VariableRef(name="flag"),
                )
            ],
        )
        ctx = _run_visitor(stmt, output_vars=("flag",))
        assert "flag" in ctx.writes

    def test_try_body_is_unguarded(self):
        """try body is treated as normal execution — not guarded."""
        stmt = TryCatchStatement(
            try_body=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="out"),
                )
            ],
        )
        ctx = _run_visitor(stmt, output_vars=("out",))
        assert ctx.writes["out"][0].guarded is False

    def test_catch_body_is_guarded(self):
        """catch body is conditional on exception — treated as guarded."""
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            catch_body=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="out"),
                )
            ],
        )
        ctx = _run_visitor(stmt, output_vars=("out",))
        assert ctx.writes["out"][0].guarded is True

    def test_finally_body_is_unguarded(self):
        """finally body always runs — treated as unguarded."""
        stmt = TryCatchStatement(
            try_body=[EmptyStatement()],
            finally_body=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="out"),
                )
            ],
        )
        ctx = _run_visitor(stmt, output_vars=("out",))
        assert ctx.writes["out"][0].guarded is False

    def test_try_reads_collected(self):
        stmt = TryCatchStatement(
            try_body=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="sensor"),
                )
            ],
        )
        ctx = _run_visitor(stmt)
        assert "sensor" in ctx.reads

    def test_on_try_catch_hook_called(self):
        hook_calls = []

        class TrackingVisitor(AnalysisVisitor):
            def on_try_catch(self, ctx, stmt):
                hook_calls.append(stmt)

        stmt = TryCatchStatement(try_body=[EmptyStatement()])
        pou = _pou_with_stmts(stmt)
        TrackingVisitor().analyze_pou(pou)
        assert len(hook_calls) == 1
        assert hook_calls[0] is stmt

    def test_unguarded_output_rule_traverses_try_body(self):
        """UnguardedOutputRule sees assignments inside try body."""
        stmt = TryCatchStatement(
            try_body=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="out"),
                )
            ],
        )
        pou = _pou_with_stmts(stmt, output_vars=("out",))
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        # Assignment in try body is unguarded → should produce a finding
        assert any(f.pou_name == "TestFB" for f in findings)


# ===========================================================================
# Test: Fix 1a — Recursive _extract_target_name
# ===========================================================================


class TestExtractTargetName:
    """Verify _extract_target_name handles nested access patterns."""

    ext = staticmethod(AnalysisVisitor._extract_target_name)

    def test_variable_ref(self):
        assert self.ext(VariableRef(name="x")) == "x"

    def test_member_access(self):
        # a.b -> 'a'
        expr = MemberAccessExpr(struct=VariableRef(name="a"), member="b")
        assert self.ext(expr) == "a"

    def test_array_access(self):
        # a[0] -> 'a'
        expr = ArrayAccessExpr(
            array=VariableRef(name="a"),
            indices=[LiteralExpr(value="0")],
        )
        assert self.ext(expr) == "a"

    def test_array_then_member(self):
        # a[0].b -> 'a'
        arr = ArrayAccessExpr(
            array=VariableRef(name="a"),
            indices=[LiteralExpr(value="0")],
        )
        expr = MemberAccessExpr(struct=arr, member="b")
        assert self.ext(expr) == "a"

    def test_member_then_array(self):
        # a.b[0] -> 'a'
        mem = MemberAccessExpr(struct=VariableRef(name="a"), member="b")
        expr = ArrayAccessExpr(
            array=mem, indices=[LiteralExpr(value="0")],
        )
        assert self.ext(expr) == "a"

    def test_nested_array(self):
        # a[0][1] -> 'a'
        inner = ArrayAccessExpr(
            array=VariableRef(name="a"),
            indices=[LiteralExpr(value="0")],
        )
        expr = ArrayAccessExpr(
            array=inner, indices=[LiteralExpr(value="1")],
        )
        assert self.ext(expr) == "a"

    def test_bit_of_array(self):
        # a[0].5 -> 'a'
        arr = ArrayAccessExpr(
            array=VariableRef(name="a"),
            indices=[LiteralExpr(value="0")],
        )
        expr = BitAccessExpr(target=arr, bit_index=5)
        assert self.ext(expr) == "a"

    def test_deref_member(self):
        # ptr^.x -> 'ptr'
        deref = DerefExpr(pointer=VariableRef(name="ptr"))
        expr = MemberAccessExpr(struct=deref, member="x")
        assert self.ext(expr) == "ptr"

    def test_literal_returns_none(self):
        assert self.ext(LiteralExpr(value="42")) is None


# ===========================================================================
# Test: Fix 1c — FB invocation outputs as writes
# ===========================================================================


class TestFBInvocationOutputs:

    def test_output_recorded_as_write(self):
        stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={"IN": LiteralExpr(value="TRUE")},
            outputs={"Q": VariableRef(name="valve")},
        )
        ctx = _run_visitor(stmt, output_vars=("valve",))
        assert "valve" in ctx.writes

    def test_output_guarded_in_if(self):
        from plx.model.statements import IfStatement, IfBranch

        fb_stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={},
            outputs={"Q": VariableRef(name="valve")},
        )
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="enable"),
                body=[fb_stmt],
            ),
        )
        ctx = _run_visitor(stmt, output_vars=("valve",))
        assert ctx.writes["valve"][0].guarded is True

    def test_unguarded_output_finding(self):
        stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={},
            outputs={"Q": VariableRef(name="valve")},
        )
        pou = _pou_with_stmts(stmt, output_vars=("valve",))
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "unguarded-output"

    def test_output_target_not_recorded_as_read(self):
        """Output write target should not be tracked as a read."""
        stmt = FBInvocation(
            instance_name="timer",
            fb_type=NamedTypeRef(name="TON"),
            inputs={},
            outputs={"Q": VariableRef(name="valve")},
        )
        ctx = _run_visitor(stmt)
        assert "valve" in ctx.writes
        assert "valve" not in ctx.reads


# ===========================================================================
# Test: Fix 1d — Read tracking with ReadInfo
# ===========================================================================


class TestReadTracking:

    def test_read_info_recorded(self):
        stmt = Assignment(
            target=VariableRef(name="out"),
            value=VariableRef(name="sensor"),
        )
        ctx = _run_visitor(stmt)
        assert "sensor" in ctx.reads
        infos = ctx.reads["sensor"]
        assert len(infos) == 1
        assert isinstance(infos[0], ReadInfo)
        assert infos[0].guarded is False

    def test_read_guarded_in_if(self):
        from plx.model.statements import IfStatement, IfBranch

        stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="cond"),
                body=[
                    Assignment(
                        target=VariableRef(name="out"),
                        value=VariableRef(name="sensor"),
                    ),
                ],
            ),
        )
        ctx = _run_visitor(stmt)
        # 'sensor' read inside if branch is guarded
        sensor_reads = ctx.reads["sensor"]
        assert all(r.guarded for r in sensor_reads)

    def test_read_location_tracked(self):
        stmt = Assignment(
            target=VariableRef(name="out"),
            value=VariableRef(name="sensor"),
        )
        ctx = _run_visitor(stmt)
        assert ctx.reads["sensor"][0].location == "network 0"


# ===========================================================================
# Test: Fix 1b — Method / Property / Action traversal
# ===========================================================================


_BOOL_REF = PrimitiveTypeRef(type=PrimitiveType.BOOL)
_INT_REF = PrimitiveTypeRef(type=PrimitiveType.INT)


def _base_pou(**kwargs) -> POU:
    """Minimal FB POU for traversal tests."""
    defaults = dict(
        pou_type=POUType.FUNCTION_BLOCK,
        name="TestFB",
        interface=POUInterface(
            output_vars=[Variable(name="main_out", data_type=_BOOL_REF)],
        ),
        networks=[],
    )
    defaults.update(kwargs)
    return POU(**defaults)


class TestMethodTraversal:

    def test_method_writes_detected(self):
        method = Method(
            name="DoWork",
            interface=POUInterface(
                output_vars=[Variable(name="result", data_type=_BOOL_REF)],
            ),
            networks=[
                Network(statements=[
                    Assignment(
                        target=VariableRef(name="result"),
                        value=LiteralExpr(value="TRUE"),
                    ),
                ]),
            ],
        )
        pou = _base_pou(methods=[method])
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        # Unguarded write to output 'result' in method
        method_findings = [f for f in findings if "DoWork" in f.pou_name]
        assert len(method_findings) == 1
        assert method_findings[0].pou_name == "TestFB.DoWork"

    def test_method_independent_scope(self):
        """Method context uses the method's interface, not the parent's."""
        method = Method(
            name="Calc",
            interface=POUInterface(
                input_vars=[Variable(name="x", data_type=_INT_REF)],
            ),
            networks=[
                Network(statements=[
                    Assignment(
                        target=VariableRef(name="main_out"),
                        value=LiteralExpr(value="TRUE"),
                    ),
                ]),
            ],
        )
        pou = _base_pou(methods=[method])
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        # main_out is NOT an output in the method's scope, so no finding
        method_findings = [f for f in findings if "Calc" in f.pou_name]
        assert len(method_findings) == 0


class TestPropertyTraversal:

    def test_property_getter_traversed(self):
        prop = Property(
            name="Value",
            data_type=_INT_REF,
            getter=PropertyAccessor(
                networks=[
                    Network(statements=[
                        Assignment(
                            target=VariableRef(name="temp"),
                            value=LiteralExpr(value="42"),
                        ),
                    ]),
                ],
            ),
        )
        pou = _base_pou(properties=[prop])
        visitor = AnalysisVisitor()
        findings = visitor.analyze_pou(pou)
        # Just verify no crash — getter was traversed
        assert isinstance(findings, list)

    def test_property_setter_traversed(self):
        prop = Property(
            name="Speed",
            data_type=_INT_REF,
            setter=PropertyAccessor(
                networks=[
                    Network(statements=[
                        Assignment(
                            target=VariableRef(name="internal"),
                            value=VariableRef(name="Speed"),
                        ),
                    ]),
                ],
            ),
        )
        pou = _base_pou(properties=[prop])
        visitor = AnalysisVisitor()
        findings = visitor.analyze_pou(pou)
        assert isinstance(findings, list)


class TestActionTraversal:

    def test_action_shares_parent_scope(self):
        """Action writes appear in the parent POU's write tracking."""
        action = POUAction(
            name="Reset",
            body=[
                Network(statements=[
                    Assignment(
                        target=VariableRef(name="main_out"),
                        value=LiteralExpr(value="FALSE"),
                    ),
                ]),
            ],
        )
        pou = _base_pou(actions=[action])
        rule = UnguardedOutputRule()
        findings = rule.analyze_pou(pou)
        # Unguarded write to 'main_out' (parent's output) in action
        assert len(findings) == 1
        assert findings[0].pou_name == "TestFB"


# ===========================================================================
# Test: Fix 1e — TypeEnvironment
# ===========================================================================


class TestTypeEnvironment:

    def _make_env(self, *vars: tuple[str, PrimitiveType]) -> "TypeEnvironment":
        from plx.analyze._types import TypeEnvironment

        iface = POUInterface(
            input_vars=[
                Variable(name=n, data_type=PrimitiveTypeRef(type=t))
                for n, t in vars
            ],
        )
        return TypeEnvironment(iface)

    def test_lookup_variable(self):
        env = self._make_env(("speed", PrimitiveType.INT))
        result = env.lookup("speed")
        assert result == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_lookup_missing(self):
        env = self._make_env(("speed", PrimitiveType.INT))
        assert env.lookup("nonexistent") is None

    def test_resolve_variable_ref(self):
        env = self._make_env(("x", PrimitiveType.DINT))
        result = env.resolve_expr_type(VariableRef(name="x"))
        assert result == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_resolve_literal_bool(self):
        env = self._make_env()
        result = env.resolve_expr_type(LiteralExpr(value="TRUE"))
        assert result == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_resolve_literal_time(self):
        env = self._make_env()
        result = env.resolve_expr_type(LiteralExpr(value="T#5s"))
        assert result == PrimitiveTypeRef(type=PrimitiveType.TIME)

    def test_resolve_literal_tod_not_time(self):
        """TOD# must not match T# prefix."""
        env = self._make_env()
        result = env.resolve_expr_type(LiteralExpr(value="TOD#12:30:00"))
        assert result == PrimitiveTypeRef(type=PrimitiveType.TOD)

    def test_resolve_literal_with_explicit_type(self):
        env = self._make_env()
        expr = LiteralExpr(
            value="42",
            data_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_resolve_type_conversion(self):
        env = self._make_env(("x", PrimitiveType.INT))
        expr = TypeConversionExpr(
            target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            source=VariableRef(name="x"),
        )
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_resolve_binary_same_type(self):
        env = self._make_env(("a", PrimitiveType.DINT), ("b", PrimitiveType.DINT))
        expr = BinaryExpr(
            op=BinaryOp.ADD,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_resolve_comparison_returns_bool(self):
        env = self._make_env(("a", PrimitiveType.INT))
        expr = BinaryExpr(
            op=BinaryOp.GT,
            left=VariableRef(name="a"),
            right=LiteralExpr(
                value="10",
                data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            ),
        )
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_resolve_logical_returns_bool(self):
        env = self._make_env(("a", PrimitiveType.BOOL), ("b", PrimitiveType.BOOL))
        expr = BinaryExpr(
            op=BinaryOp.AND,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_resolve_binary_different_types_returns_none(self):
        env = self._make_env(("a", PrimitiveType.INT), ("b", PrimitiveType.REAL))
        expr = BinaryExpr(
            op=BinaryOp.ADD,
            left=VariableRef(name="a"),
            right=VariableRef(name="b"),
        )
        assert env.resolve_expr_type(expr) is None

    def test_resolve_array_access(self):
        from plx.analyze._types import TypeEnvironment

        iface = POUInterface(
            input_vars=[
                Variable(
                    name="arr",
                    data_type=ArrayTypeRef(
                        element_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                        dimensions=[DimensionRange(lower=0, upper=9)],
                    ),
                ),
            ],
        )
        env = TypeEnvironment(iface)
        expr = ArrayAccessExpr(
            array=VariableRef(name="arr"),
            indices=[LiteralExpr(value="0")],
        )
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_resolve_unary(self):
        env = self._make_env(("x", PrimitiveType.DINT))
        expr = UnaryExpr(op=UnaryOp.NEG, operand=VariableRef(name="x"))
        result = env.resolve_expr_type(expr)
        assert result == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_resolve_member_access_returns_none(self):
        env = self._make_env(("s", PrimitiveType.INT))
        expr = MemberAccessExpr(struct=VariableRef(name="s"), member="field")
        assert env.resolve_expr_type(expr) is None

    def test_resolve_plain_number_returns_none(self):
        env = self._make_env()
        assert env.resolve_expr_type(LiteralExpr(value="42")) is None

    def test_context_has_type_env(self):
        pou = _base_pou()
        ctx = AnalysisVisitor._make_context(pou)
        assert ctx.type_env is not None

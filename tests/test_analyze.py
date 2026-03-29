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
    ConstantOutOfRangeRule,
    CrossTaskWriteRule,
    CyclomaticComplexityRule,
    DeadSfcStepRule,
    DivisionByZeroRule,
    EmptyBodyRule,
    EnumCastRule,
    ForCounterWriteRule,
    IgnoredFBOutputRule,
    IncompleteCaseEnumRule,
    MaxNestingDepthRule,
    MissingCaseElseRule,
    MultipleOutputWriteRule,
    NarrowingConversionRule,
    RealEqualityRule,
    RecursiveCallRule,
    SfcMultipleInitialStepsRule,
    SfcNoInitialStepRule,
    TempFBInstanceRule,
    UnguardedOutputRule,
    UnreachableCodeRule,
    UnusedInputRule,
    UnusedOutputRule,
    UnusedPOURule,
    UnusedVariableRule,
    UseBeforeDefRule,
    VariableShadowRule,
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
    CaseBranch,
    CaseStatement,
    EmptyStatement,
    FBInvocation,
    ForStatement,
    IfBranch,
    IfStatement,
    JumpStatement,
    LabelStatement,
    PragmaStatement,
    RepeatStatement,
    TryCatchStatement,
    WhileStatement,
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


def _pou_with_stmts(*stmts, output_vars=(), input_vars=()) -> POU:
    """Build a minimal POU containing the given statements."""
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name="TestFB",
        interface=POUInterface(
            input_vars=[
                Variable(name=name, data_type=_bool_type())
                for name in input_vars
            ],
            output_vars=[
                Variable(name=name, data_type=_bool_type())
                for name in output_vars
            ],
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


# ===========================================================================
# Test: Phase 2 — Wave 1 Rules
# ===========================================================================


class TestMultipleOutputWriteRule:

    def test_single_write_no_finding(self):
        pou = _pou_with_stmts(
            Assignment(target=VariableRef(name="out"), value=LiteralExpr(value="TRUE")),
            output_vars=("out",),
        )
        assert MultipleOutputWriteRule().analyze_pou(pou) == []

    def test_two_writes_finding(self):

        stmts = [
            IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="cond"),
                    body=[Assignment(target=VariableRef(name="out"), value=LiteralExpr(value="TRUE"))],
                ),
            ),
            Assignment(target=VariableRef(name="out"), value=LiteralExpr(value="FALSE")),
        ]
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="out", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=stmts)],
        )
        findings = MultipleOutputWriteRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "multiple-output-write"
        assert findings[0].details["write_count"] == 2

    def test_non_output_multiple_writes_no_finding(self):
        stmts = [
            Assignment(target=VariableRef(name="temp"), value=LiteralExpr(value="1")),
            Assignment(target=VariableRef(name="temp"), value=LiteralExpr(value="2")),
        ]
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="temp", data_type=_INT_REF)],
            ),
            networks=[Network(statements=stmts)],
        )
        assert MultipleOutputWriteRule().analyze_pou(pou) == []


class TestWriteToInputRule:

    def test_no_write_to_input_no_finding(self):
        pou = _pou_with_stmts(
            Assignment(target=VariableRef(name="out"), value=VariableRef(name="inp")),
            output_vars=("out",), input_vars=("inp",),
        )
        assert WriteToInputRule().analyze_pou(pou) == []

    def test_write_to_input_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="speed", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="speed"), value=LiteralExpr(value="0")),
            ])],
        )
        findings = WriteToInputRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "write-to-input"
        assert findings[0].details["variable"] == "speed"


class TestRealEqualityRule:

    def test_int_equality_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="a", data_type=_INT_REF)],
                static_vars=[Variable(name="b", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="b"),
                    value=BinaryExpr(
                        op=BinaryOp.EQ,
                        left=VariableRef(name="a"),
                        right=LiteralExpr(value="10", data_type=_INT_REF),
                    ),
                ),
            ])],
        )
        assert RealEqualityRule().analyze_pou(pou) == []

    def test_real_equality_finding(self):
        real_ref = PrimitiveTypeRef(type=PrimitiveType.REAL)
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="a", data_type=real_ref)],
                static_vars=[Variable(name="b", data_type=real_ref)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="b"),
                    value=BinaryExpr(
                        op=BinaryOp.EQ,
                        left=VariableRef(name="a"),
                        right=LiteralExpr(value="10.0", data_type=real_ref),
                    ),
                ),
            ])],
        )
        findings = RealEqualityRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "real-equality"

    def test_real_ne_also_flagged(self):
        real_ref = PrimitiveTypeRef(type=PrimitiveType.REAL)
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="a", data_type=real_ref)],
                output_vars=[Variable(name="out", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=BinaryExpr(
                        op=BinaryOp.NE,
                        left=VariableRef(name="a"),
                        right=LiteralExpr(value="0.0", data_type=real_ref),
                    ),
                ),
            ])],
        )
        findings = RealEqualityRule().analyze_pou(pou)
        assert len(findings) == 1

    def test_real_equality_in_if_condition(self):
        """REAL == in IF condition is caught (not just assignments)."""
        real_ref = PrimitiveTypeRef(type=PrimitiveType.REAL)
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="speed", data_type=real_ref)],
            ),
            networks=[Network(statements=[
                IfStatement(
                    if_branch=IfBranch(
                        condition=BinaryExpr(
                            op=BinaryOp.EQ,
                            left=VariableRef(name="speed"),
                            right=LiteralExpr(value="0.0", data_type=real_ref),
                        ),
                        body=[EmptyStatement()],
                    ),
                ),
            ])],
        )
        findings = RealEqualityRule().analyze_pou(pou)
        assert len(findings) == 1


class TestMissingCaseElseRule:

    def test_case_with_else_no_finding(self):
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[CaseBranch(values=[1], body=[EmptyStatement()])],
            else_body=[EmptyStatement()],
        )
        pou = _pou_with_stmts(stmt)
        assert MissingCaseElseRule().analyze_pou(pou) == []

    def test_case_without_else_finding(self):
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[CaseBranch(values=[1], body=[EmptyStatement()])],
        )
        pou = _pou_with_stmts(stmt)
        findings = MissingCaseElseRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "missing-case-else"


class TestForCounterWriteRule:

    def test_no_counter_write_no_finding(self):
        stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="10"),
            body=[
                Assignment(
                    target=VariableRef(name="arr"),
                    value=LiteralExpr(value="0"),
                ),
            ],
        )
        pou = _pou_with_stmts(stmt)
        assert ForCounterWriteRule().analyze_pou(pou) == []

    def test_counter_write_finding(self):
        stmt = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="10"),
            body=[
                Assignment(
                    target=VariableRef(name="i"),
                    value=LiteralExpr(value="0"),
                ),
            ],
        )
        pou = _pou_with_stmts(stmt)
        findings = ForCounterWriteRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "for-counter-write"
        assert findings[0].details["variable"] == "i"

    def test_nested_for_inner_counter_write(self):
        """Writing outer counter inside inner loop is still caught."""
        inner = ForStatement(
            loop_var="j",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="5"),
            body=[
                Assignment(
                    target=VariableRef(name="i"),
                    value=LiteralExpr(value="0"),
                ),
            ],
        )
        outer = ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="10"),
            body=[inner],
        )
        pou = _pou_with_stmts(outer)
        findings = ForCounterWriteRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].details["variable"] == "i"

    def test_assignment_after_loop_not_flagged(self):
        """Assignment to former loop var AFTER the loop is not a violation."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="i", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                ForStatement(
                    loop_var="i",
                    from_expr=LiteralExpr(value="0"),
                    to_expr=LiteralExpr(value="10"),
                    body=[],
                ),
                Assignment(
                    target=VariableRef(name="i"),
                    value=LiteralExpr(value="99"),
                ),
            ])],
        )
        assert ForCounterWriteRule().analyze_pou(pou) == []


class TestUnusedVariableRule:

    def test_used_variable_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=_BOOL_REF)],
                output_vars=[Variable(name="valve", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="valve"),
                    value=VariableRef(name="sensor"),
                ),
            ])],
        )
        assert UnusedVariableRule().analyze_pou(pou) == []

    def test_unused_variable_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="unused", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        findings = UnusedVariableRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].details["variable"] == "unused"

    def test_constants_and_externals_excluded(self):
        """Constant and external vars are not flagged as unused."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                constant_vars=[Variable(name="PI", data_type=_INT_REF)],
                external_vars=[Variable(name="global_flag", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        assert UnusedVariableRule().analyze_pou(pou) == []


class TestUnusedInputRule:

    def test_read_input_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=_BOOL_REF)],
                output_vars=[Variable(name="out", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="sensor"),
                ),
            ])],
        )
        assert UnusedInputRule().analyze_pou(pou) == []

    def test_unused_input_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="sensor", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        findings = UnusedInputRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "unused-input"


class TestUnusedOutputRule:

    def test_written_output_no_finding(self):
        pou = _pou_with_stmts(
            Assignment(target=VariableRef(name="out"), value=LiteralExpr(value="TRUE")),
            output_vars=("out",),
        )
        assert UnusedOutputRule().analyze_pou(pou) == []

    def test_unused_output_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="valve", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[EmptyStatement()])],
        )
        findings = UnusedOutputRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "unused-output"


class TestTempFBInstanceRule:

    def test_static_fb_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="timer", data_type=NamedTypeRef(name="TON"))],
            ),
            networks=[],
        )
        assert TempFBInstanceRule().analyze_pou(pou) == []

    def test_temp_fb_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                temp_vars=[Variable(name="timer", data_type=NamedTypeRef(name="TON"))],
            ),
            networks=[],
        )
        findings = TempFBInstanceRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "temp-fb-instance"
        assert findings[0].details["fb_type"] == "TON"

    def test_temp_primitive_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                temp_vars=[Variable(name="scratch", data_type=_INT_REF)],
            ),
            networks=[],
        )
        assert TempFBInstanceRule().analyze_pou(pou) == []


class TestEmptyBodyRule:

    def test_non_empty_no_finding(self):
        pou = _pou_with_stmts(
            Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
        )
        assert EmptyBodyRule().analyze_pou(pou) == []

    def test_empty_body_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="EmptyFB",
            interface=POUInterface(),
            networks=[],
        )
        findings = EmptyBodyRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "empty-body"

    def test_empty_network_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="EmptyFB",
            interface=POUInterface(),
            networks=[Network(statements=[])],
        )
        findings = EmptyBodyRule().analyze_pou(pou)
        assert len(findings) == 1

    def test_interface_excluded(self):
        """INTERFACE POUs have no body by design."""
        pou = POU(
            pou_type=POUType.INTERFACE, name="IMovable",
            interface=POUInterface(),
            networks=[],
        )
        assert EmptyBodyRule().analyze_pou(pou) == []


class TestSfcNoInitialStepRule:

    def test_has_initial_step_no_finding(self):
        from plx.model.sfc import SFCBody, Step, Transition

        pou = POU(
            pou_type=POUType.PROGRAM, name="TestProg",
            interface=POUInterface(),
            sfc_body=SFCBody(
                steps=[Step(name="IDLE", is_initial=True), Step(name="RUN")],
                transitions=[Transition(
                    source_steps=["IDLE"], target_steps=["RUN"],
                    condition=LiteralExpr(value="TRUE"),
                )],
            ),
        )
        assert SfcNoInitialStepRule().analyze_pou(pou) == []

    def test_no_initial_step_finding(self):
        """SFCBody validates initial step count, so we construct_without_validation."""
        from plx.model.sfc import SFCBody, Step, Transition

        sfc = SFCBody.model_construct(
            steps=[Step(name="A"), Step(name="B")],
            transitions=[Transition(
                source_steps=["A"], target_steps=["B"],
                condition=LiteralExpr(value="TRUE"),
            )],
        )
        pou = POU.model_construct(
            pou_type=POUType.PROGRAM, name="TestProg",
            interface=POUInterface(), networks=[],
            sfc_body=sfc, actions=[], methods=[], properties=[],
            abstract=False, description="", safety=False, language=None,
            return_type=None, extends=None, implements=[], folder="",
            metadata={},
        )
        findings = SfcNoInitialStepRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "sfc-no-initial"


class TestSfcMultipleInitialStepsRule:

    def test_single_initial_no_finding(self):
        from plx.model.sfc import SFCBody, Step

        pou = POU(
            pou_type=POUType.PROGRAM, name="TestProg",
            interface=POUInterface(),
            sfc_body=SFCBody(
                steps=[Step(name="IDLE", is_initial=True), Step(name="RUN")],
                transitions=[],
            ),
        )
        assert SfcMultipleInitialStepsRule().analyze_pou(pou) == []

    def test_multiple_initial_finding(self):
        """SFCBody validates initial step count, so we construct_without_validation."""
        from plx.model.sfc import SFCBody, Step

        sfc = SFCBody.model_construct(
            steps=[
                Step(name="A", is_initial=True),
                Step(name="B", is_initial=True),
            ],
            transitions=[],
        )
        pou = POU.model_construct(
            pou_type=POUType.PROGRAM, name="TestProg",
            interface=POUInterface(), networks=[],
            sfc_body=sfc, actions=[], methods=[], properties=[],
            abstract=False, description="", safety=False, language=None,
            return_type=None, extends=None, implements=[], folder="",
            metadata={},
        )
        findings = SfcMultipleInitialStepsRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "sfc-multiple-initial"
        assert findings[0].details["steps"] == ["A", "B"]


# ===========================================================================
# Test: Phase 3 — Wave 2 Rules
# ===========================================================================


class TestNarrowingConversionRule:

    def test_same_type_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="a", data_type=_INT_REF)],
                output_vars=[Variable(name="b", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="b"), value=VariableRef(name="a")),
            ])],
        )
        assert NarrowingConversionRule().analyze_pou(pou) == []

    def test_widening_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="a", data_type=_INT_REF)],
                static_vars=[Variable(name="b", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="b"), value=VariableRef(name="a")),
            ])],
        )
        assert NarrowingConversionRule().analyze_pou(pou) == []

    def test_narrowing_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="big", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))],
                output_vars=[Variable(name="small", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="small"), value=VariableRef(name="big")),
            ])],
        )
        findings = NarrowingConversionRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "narrowing-conversion"


class TestConstantOutOfRangeRule:

    def test_in_range_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.BYTE))],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=LiteralExpr(value="200"),
                ),
            ])],
        )
        assert ConstantOutOfRangeRule().analyze_pou(pou) == []

    def test_out_of_range_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.BYTE))],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=LiteralExpr(value="300"),
                ),
            ])],
        )
        findings = ConstantOutOfRangeRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "constant-out-of-range"

    def test_negative_in_unsigned_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.UINT))],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=LiteralExpr(value="-1"),
                ),
            ])],
        )
        findings = ConstantOutOfRangeRule().analyze_pou(pou)
        assert len(findings) == 1


class TestDivisionByZeroRule:

    def test_non_zero_divisor_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="x", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=BinaryExpr(
                        op=BinaryOp.DIV,
                        left=LiteralExpr(value="10"),
                        right=LiteralExpr(value="2"),
                    ),
                ),
            ])],
        )
        assert DivisionByZeroRule().analyze_pou(pou) == []

    def test_literal_zero_divisor_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="x", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=BinaryExpr(
                        op=BinaryOp.DIV,
                        left=VariableRef(name="x"),
                        right=LiteralExpr(value="0"),
                    ),
                ),
            ])],
        )
        findings = DivisionByZeroRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "division-by-zero"

    def test_mod_by_zero_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="x", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(
                    target=VariableRef(name="x"),
                    value=BinaryExpr(
                        op=BinaryOp.MOD,
                        left=VariableRef(name="x"),
                        right=LiteralExpr(value="0"),
                    ),
                ),
            ])],
        )
        findings = DivisionByZeroRule().analyze_pou(pou)
        assert len(findings) == 1
        assert "Modulo" in findings[0].message


class TestCyclomaticComplexityRule:

    def test_simple_pou_no_finding(self):
        pou = _pou_with_stmts(
            Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
        )
        assert CyclomaticComplexityRule(max_complexity=15).analyze_pou(pou) == []

    def test_complex_pou_finding(self):
        """POU with CC > threshold triggers finding."""
        # Build a POU with many if-statements
        stmts = []
        for i in range(10):
            stmts.append(IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="cond"),
                    body=[EmptyStatement()],
                ),
            ))
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(),
            networks=[Network(statements=stmts)],
        )
        # CC = 1 + 10 = 11
        findings = CyclomaticComplexityRule(max_complexity=5).analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].details["complexity"] == 11


class TestMaxNestingDepthRule:

    def test_shallow_no_finding(self):
        stmt = IfStatement(
            if_branch=IfBranch(
                condition=VariableRef(name="cond"),
                body=[Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))],
            ),
        )
        pou = _pou_with_stmts(stmt)
        assert MaxNestingDepthRule(max_depth=5).analyze_pou(pou) == []

    def test_deep_nesting_finding(self):
        # Build deeply nested if statements
        inner = Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1"))
        for _ in range(4):
            inner = IfStatement(
                if_branch=IfBranch(
                    condition=VariableRef(name="cond"),
                    body=[inner],
                ),
            )
        pou = _pou_with_stmts(inner)
        findings = MaxNestingDepthRule(max_depth=2).analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].details["depth"] == 4


class TestRecursiveCallRule:

    def test_no_recursion_no_finding(self):
        from plx.model.project import Project

        pou_a = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="A",
            interface=POUInterface(),
            networks=[Network(statements=[
                FBInvocation(
                    instance_name="b_inst",
                    fb_type=NamedTypeRef(name="B"),
                    inputs={},
                ),
            ])],
        )
        pou_b = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="B",
            interface=POUInterface(),
            networks=[],
        )
        proj = Project(name="Test", pous=[pou_a, pou_b])
        findings = RecursiveCallRule().analyze_project(proj).findings
        assert findings == []

    def test_direct_recursion_finding(self):
        from plx.model.project import Project

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="SelfCall",
            interface=POUInterface(),
            networks=[Network(statements=[
                FBInvocation(
                    instance_name="me",
                    fb_type=NamedTypeRef(name="SelfCall"),
                    inputs={},
                ),
            ])],
        )
        proj = Project(name="Test", pous=[pou])
        findings = RecursiveCallRule().analyze_project(proj).findings
        assert len(findings) == 1
        assert findings[0].rule_id == "recursive-call"

    def test_mutual_recursion_finding(self):
        from plx.model.project import Project

        pou_a = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="A",
            interface=POUInterface(),
            networks=[Network(statements=[
                FBInvocation(instance_name="b", fb_type=NamedTypeRef(name="B"), inputs={}),
            ])],
        )
        pou_b = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="B",
            interface=POUInterface(),
            networks=[Network(statements=[
                FBInvocation(instance_name="a", fb_type=NamedTypeRef(name="A"), inputs={}),
            ])],
        )
        proj = Project(name="Test", pous=[pou_a, pou_b])
        findings = RecursiveCallRule().analyze_project(proj).findings
        assert len(findings) >= 1
        assert any(f.rule_id == "recursive-call" for f in findings)


class TestVariableShadowRule:

    def test_no_shadow_no_finding(self):
        from plx.model.project import GlobalVariableList, Project

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="local_var", data_type=_INT_REF)],
            ),
            networks=[],
        )
        proj = Project(
            name="Test", pous=[pou],
            global_variable_lists=[
                GlobalVariableList(name="GVL", variables=[
                    Variable(name="global_var", data_type=_INT_REF),
                ]),
            ],
        )
        findings = VariableShadowRule().analyze_project(proj).findings
        assert findings == []

    def test_shadow_finding(self):
        from plx.model.project import GlobalVariableList, Project

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="speed", data_type=_INT_REF)],
            ),
            networks=[],
        )
        proj = Project(
            name="Test", pous=[pou],
            global_variable_lists=[
                GlobalVariableList(name="GVL", variables=[
                    Variable(name="speed", data_type=_INT_REF),
                ]),
            ],
        )
        findings = VariableShadowRule().analyze_project(proj).findings
        assert len(findings) == 1
        assert findings[0].rule_id == "variable-shadow"
        assert findings[0].details["variable"] == "speed"


class TestIncompleteCaseEnumRule:

    def test_complete_enum_no_finding(self):
        from plx.model.project import Project
        from plx.model.types import EnumMember, EnumType

        enum = EnumType(name="Color", members=[
            EnumMember(name="RED", value=0),
            EnumMember(name="GREEN", value=1),
            EnumMember(name="BLUE", value=2),
        ])
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="c", data_type=NamedTypeRef(name="Color"))],
            ),
            networks=[Network(statements=[
                CaseStatement(
                    selector=VariableRef(name="c"),
                    branches=[
                        CaseBranch(values=[0], body=[EmptyStatement()]),
                        CaseBranch(values=[1], body=[EmptyStatement()]),
                        CaseBranch(values=[2], body=[EmptyStatement()]),
                    ],
                ),
            ])],
        )
        proj = Project(name="Test", pous=[pou], data_types=[enum])
        findings = IncompleteCaseEnumRule().analyze_project(proj).findings
        assert findings == []

    def test_missing_member_finding(self):
        from plx.model.project import Project
        from plx.model.types import EnumMember, EnumType

        enum = EnumType(name="Color", members=[
            EnumMember(name="RED", value=0),
            EnumMember(name="GREEN", value=1),
            EnumMember(name="BLUE", value=2),
        ])
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="c", data_type=NamedTypeRef(name="Color"))],
            ),
            networks=[Network(statements=[
                CaseStatement(
                    selector=VariableRef(name="c"),
                    branches=[
                        CaseBranch(values=[0], body=[EmptyStatement()]),
                        CaseBranch(values=[1], body=[EmptyStatement()]),
                    ],
                ),
            ])],
        )
        proj = Project(name="Test", pous=[pou], data_types=[enum])
        findings = IncompleteCaseEnumRule().analyze_project(proj).findings
        assert len(findings) == 1
        assert findings[0].rule_id == "incomplete-enum-case"
        assert "BLUE" in findings[0].details["missing"]

    def test_else_branch_suppresses_finding(self):
        from plx.model.project import Project
        from plx.model.types import EnumMember, EnumType

        enum = EnumType(name="Color", members=[
            EnumMember(name="RED", value=0),
            EnumMember(name="GREEN", value=1),
        ])
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                input_vars=[Variable(name="c", data_type=NamedTypeRef(name="Color"))],
            ),
            networks=[Network(statements=[
                CaseStatement(
                    selector=VariableRef(name="c"),
                    branches=[CaseBranch(values=[0], body=[EmptyStatement()])],
                    else_body=[EmptyStatement()],
                ),
            ])],
        )
        proj = Project(name="Test", pous=[pou], data_types=[enum])
        findings = IncompleteCaseEnumRule().analyze_project(proj).findings
        assert findings == []


# ===========================================================================
# Test: Phase 4 — Wave 3 Rules
# ===========================================================================


class TestCrossTaskWriteRule:

    def test_no_overlap_no_finding(self):
        from plx.model.project import Project
        from plx.model.task import PeriodicTask

        pou_a = POU(
            pou_type=POUType.PROGRAM, name="ProgA",
            interface=POUInterface(
                output_vars=[Variable(name="valve1", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="valve1"), value=LiteralExpr(value="TRUE")),
            ])],
        )
        pou_b = POU(
            pou_type=POUType.PROGRAM, name="ProgB",
            interface=POUInterface(
                output_vars=[Variable(name="valve2", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="valve2"), value=LiteralExpr(value="TRUE")),
            ])],
        )
        proj = Project(
            name="Test", pous=[pou_a, pou_b],
            tasks=[
                PeriodicTask(name="Fast", interval="T#10ms", assigned_pous=["ProgA"]),
                PeriodicTask(name="Slow", interval="T#100ms", assigned_pous=["ProgB"]),
            ],
        )
        assert CrossTaskWriteRule().analyze_project(proj).findings == []

    def test_cross_task_write_finding(self):
        from plx.model.project import Project
        from plx.model.task import PeriodicTask

        pou_a = POU(
            pou_type=POUType.PROGRAM, name="ProgA",
            interface=POUInterface(),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="shared"), value=LiteralExpr(value="1")),
            ])],
        )
        pou_b = POU(
            pou_type=POUType.PROGRAM, name="ProgB",
            interface=POUInterface(),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="shared"), value=LiteralExpr(value="2")),
            ])],
        )
        proj = Project(
            name="Test", pous=[pou_a, pou_b],
            tasks=[
                PeriodicTask(name="Fast", interval="T#10ms", assigned_pous=["ProgA"]),
                PeriodicTask(name="Slow", interval="T#100ms", assigned_pous=["ProgB"]),
            ],
        )
        findings = CrossTaskWriteRule().analyze_project(proj).findings
        assert len(findings) == 1
        assert findings[0].rule_id == "cross-task-write"
        assert "shared" in findings[0].message


class TestUnusedPOURule:

    def test_used_pou_no_finding(self):
        from plx.model.project import Project
        from plx.model.task import PeriodicTask

        pou = POU(
            pou_type=POUType.PROGRAM, name="Main",
            interface=POUInterface(), networks=[],
        )
        proj = Project(
            name="Test", pous=[pou],
            tasks=[PeriodicTask(name="T1", interval="T#10ms", assigned_pous=["Main"])],
        )
        assert UnusedPOURule().analyze_project(proj).findings == []

    def test_called_pou_no_finding(self):
        from plx.model.project import Project
        from plx.model.task import PeriodicTask

        helper = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="Helper",
            interface=POUInterface(), networks=[],
        )
        main = POU(
            pou_type=POUType.PROGRAM, name="Main",
            interface=POUInterface(),
            networks=[Network(statements=[
                FBInvocation(instance_name="h", fb_type=NamedTypeRef(name="Helper"), inputs={}),
            ])],
        )
        proj = Project(
            name="Test", pous=[main, helper],
            tasks=[PeriodicTask(name="T1", interval="T#10ms", assigned_pous=["Main"])],
        )
        assert UnusedPOURule().analyze_project(proj).findings == []

    def test_unused_pou_finding(self):
        from plx.model.project import Project

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="Orphan",
            interface=POUInterface(), networks=[],
        )
        proj = Project(name="Test", pous=[pou])
        findings = UnusedPOURule().analyze_project(proj).findings
        assert len(findings) == 1
        assert findings[0].rule_id == "unused-pou"
        assert findings[0].pou_name == "Orphan"


class TestUnreachableCodeRule:

    def test_no_unreachable_no_finding(self):
        pou = _pou_with_stmts(
            Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
            Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="2")),
        )
        assert UnreachableCodeRule().analyze_pou(pou) == []

    def test_code_after_return_finding(self):
        from plx.model.statements import ReturnStatement

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(),
            networks=[Network(statements=[
                ReturnStatement(),
                Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
            ])],
        )
        findings = UnreachableCodeRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "unreachable-code"
        assert "RETURN" in findings[0].message

    def test_code_after_exit_in_loop(self):
        from plx.model.statements import ExitStatement

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(),
            networks=[Network(statements=[
                ForStatement(
                    loop_var="i",
                    from_expr=LiteralExpr(value="0"),
                    to_expr=LiteralExpr(value="10"),
                    body=[
                        ExitStatement(),
                        Assignment(target=VariableRef(name="x"), value=LiteralExpr(value="1")),
                    ],
                ),
            ])],
        )
        findings = UnreachableCodeRule().analyze_pou(pou)
        assert len(findings) == 1
        assert "EXIT" in findings[0].message


class TestIgnoredFBOutputRule:

    def test_output_read_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="timer", data_type=NamedTypeRef(name="TON"))],
                output_vars=[Variable(name="done", data_type=_BOOL_REF)],
            ),
            networks=[Network(statements=[
                FBInvocation(
                    instance_name="timer",
                    fb_type=NamedTypeRef(name="TON"),
                    inputs={"IN": LiteralExpr(value="TRUE")},
                ),
                Assignment(
                    target=VariableRef(name="done"),
                    value=MemberAccessExpr(
                        struct=VariableRef(name="timer"), member="Q",
                    ),
                ),
            ])],
        )
        assert IgnoredFBOutputRule().analyze_pou(pou) == []

    def test_output_ignored_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="timer", data_type=NamedTypeRef(name="TON"))],
            ),
            networks=[Network(statements=[
                FBInvocation(
                    instance_name="timer",
                    fb_type=NamedTypeRef(name="TON"),
                    inputs={"IN": LiteralExpr(value="TRUE")},
                ),
            ])],
        )
        findings = IgnoredFBOutputRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "ignored-fb-output"
        assert findings[0].details["instance"] == "timer"


class TestUseBeforeDefRule:

    def test_write_then_read_no_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                temp_vars=[Variable(name="scratch", data_type=_INT_REF)],
                output_vars=[Variable(name="out", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="scratch"), value=LiteralExpr(value="42")),
                Assignment(target=VariableRef(name="out"), value=VariableRef(name="scratch")),
            ])],
        )
        assert UseBeforeDefRule().analyze_pou(pou) == []

    def test_read_before_write_finding(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                temp_vars=[Variable(name="scratch", data_type=_INT_REF)],
                output_vars=[Variable(name="out", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="out"), value=VariableRef(name="scratch")),
                Assignment(target=VariableRef(name="scratch"), value=LiteralExpr(value="42")),
            ])],
        )
        findings = UseBeforeDefRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "use-before-def"
        assert findings[0].details["variable"] == "scratch"

    def test_static_var_not_flagged(self):
        """Static vars persist across scans — not flagged."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK, name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="counter", data_type=_INT_REF)],
                output_vars=[Variable(name="out", data_type=_INT_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="out"), value=VariableRef(name="counter")),
            ])],
        )
        assert UseBeforeDefRule().analyze_pou(pou) == []


# ===========================================================================
# Phase 5: Hardening — Parametrized, Integration, Fuzz, Performance
# ===========================================================================


# ---------------------------------------------------------------------------
# Parametrized: unguarded output across all control flow variants
# ---------------------------------------------------------------------------

def _wrap_in_control_flow(inner_stmt, kind):
    """Wrap a statement inside a control flow construct."""
    cond = VariableRef(name="cond")
    if kind == "if":
        return IfStatement(
            if_branch=IfBranch(condition=cond, body=[inner_stmt]),
        )
    if kind == "case":
        return CaseStatement(
            selector=cond,
            branches=[CaseBranch(values=[1], body=[inner_stmt])],
        )
    if kind == "for":
        return ForStatement(
            loop_var="i",
            from_expr=LiteralExpr(value="0"),
            to_expr=LiteralExpr(value="10"),
            body=[inner_stmt],
        )
    if kind == "while":
        return WhileStatement(condition=cond, body=[inner_stmt])
    if kind == "repeat":
        return RepeatStatement(body=[inner_stmt], until=cond)
    raise ValueError(kind)


class TestUnguardedOutputParametrized:
    """Verify unguarded-output rule across all control flow wrappers."""

    @pytest.mark.parametrize("kind", ["if", "case", "for", "while", "repeat"])
    def test_guarded_in_control_flow(self, kind):
        assign = Assignment(
            target=VariableRef(name="out"),
            value=LiteralExpr(value="TRUE"),
        )
        wrapped = _wrap_in_control_flow(assign, kind)
        pou = _pou_with_stmts(wrapped, output_vars=("out",))
        findings = UnguardedOutputRule().analyze_pou(pou)
        assert findings == [], f"Should be guarded inside {kind}"

    def test_unguarded_at_top_level(self):
        assign = Assignment(
            target=VariableRef(name="out"),
            value=LiteralExpr(value="TRUE"),
        )
        pou = _pou_with_stmts(assign, output_vars=("out",))
        findings = UnguardedOutputRule().analyze_pou(pou)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# Parametrized: missing-case-else with various branch counts
# ---------------------------------------------------------------------------

class TestMissingCaseElseParametrized:

    @pytest.mark.parametrize("n_branches", [1, 3, 5])
    def test_no_else_any_branch_count(self, n_branches):
        branches = [
            CaseBranch(values=[i], body=[EmptyStatement()])
            for i in range(n_branches)
        ]
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=branches,
        )
        pou = _pou_with_stmts(stmt)
        findings = MissingCaseElseRule().analyze_pou(pou)
        assert len(findings) == 1

    @pytest.mark.parametrize("n_branches", [1, 3, 5])
    def test_with_else_any_branch_count(self, n_branches):
        branches = [
            CaseBranch(values=[i], body=[EmptyStatement()])
            for i in range(n_branches)
        ]
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=branches,
            else_body=[EmptyStatement()],
        )
        pou = _pou_with_stmts(stmt)
        assert MissingCaseElseRule().analyze_pou(pou) == []


# ---------------------------------------------------------------------------
# Integration: compile framework POUs and analyze
# ---------------------------------------------------------------------------

class TestIntegration:
    """Round-trip: compile framework POU → analyze → verify findings."""

    def test_guarded_fb_no_unguarded_finding(self):
        """A properly guarded FB produces no unguarded-output findings."""
        pou = _compile_pou(GuardedOutputFB)
        findings = UnguardedOutputRule().analyze_pou(pou)
        assert findings == []

    def test_unguarded_fb_produces_finding(self):
        pou = _compile_pou(UnguardedOutputFB)
        findings = UnguardedOutputRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "unguarded-output"

    def test_full_analysis_on_compiled_project(self):
        """Run ALL_RULES on a compiled project — no crashes."""
        proj = _compile_project(
            GuardedOutputFB, UnguardedOutputFB, MixedOutputFB, EmptyFB,
        )
        result = analyze(proj)
        assert isinstance(result, AnalysisResult)
        assert result.pou_count >= 4
        assert result.rule_count == len(ALL_RULES)

    def test_sfc_analysis_no_crash(self):
        """SFC POUs can be analyzed without errors."""
        pou = _compile_pou(ReachableSFC)
        result = analyze(pou)
        assert isinstance(result, AnalysisResult)

    def test_unused_input_on_compiled_fb(self):
        """Compiled FB with unused input triggers unused-input rule."""
        @fb
        class HasUnusedInput:
            unused_sensor: Input[BOOL]
            valve: Output[BOOL]
            def logic(self):
                self.valve = True

        pou = _compile_pou(HasUnusedInput)
        findings = UnusedInputRule().analyze_pou(pou)
        assert any(f.details.get("variable") == "unused_sensor" for f in findings)


# ---------------------------------------------------------------------------
# Fuzz: Hypothesis property-based tests
# ---------------------------------------------------------------------------

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


def _literal(value="0"):
    return LiteralExpr(value=value)


def _var(name="x"):
    return VariableRef(name=name)


@st.composite
def st_expression(draw, max_depth=3):
    """Generate random Expression trees."""
    if max_depth <= 0:
        return draw(st.sampled_from([_literal("42"), _var("x"), _var("y")]))

    kind = draw(st.sampled_from(["literal", "var", "binary", "unary", "member"]))
    if kind == "literal":
        return _literal(draw(st.sampled_from(["0", "1", "TRUE", "FALSE", "42"])))
    if kind == "var":
        return _var(draw(st.sampled_from(["x", "y", "z", "cond", "out"])))
    if kind == "binary":
        op = draw(st.sampled_from(list(BinaryOp)))
        left = draw(st_expression(max_depth=max_depth - 1))
        right = draw(st_expression(max_depth=max_depth - 1))
        return BinaryExpr(op=op, left=left, right=right)
    if kind == "unary":
        from plx.model.expressions import UnaryOp as UOp, UnaryExpr as UExpr
        op = draw(st.sampled_from(list(UOp)))
        operand = draw(st_expression(max_depth=max_depth - 1))
        return UExpr(op=op, operand=operand)
    # member
    struct = draw(st_expression(max_depth=max_depth - 1))
    member = draw(st.sampled_from(["Q", "ET", "field", "value"]))
    return MemberAccessExpr(struct=struct, member=member)


@st.composite
def st_statement(draw, max_depth=2):
    """Generate random Statement trees."""
    if max_depth <= 0:
        expr = draw(st_expression(max_depth=1))
        return Assignment(target=_var("out"), value=expr)

    kind = draw(st.sampled_from(["assign", "if", "for", "empty"]))
    if kind == "assign":
        target = _var(draw(st.sampled_from(["x", "y", "out"])))
        value = draw(st_expression(max_depth=2))
        return Assignment(target=target, value=value)
    if kind == "if":
        cond = draw(st_expression(max_depth=1))
        body = [draw(st_statement(max_depth=max_depth - 1))]
        return IfStatement(if_branch=IfBranch(condition=cond, body=body))
    if kind == "for":
        body = [draw(st_statement(max_depth=max_depth - 1))]
        return ForStatement(
            loop_var="i",
            from_expr=_literal("0"),
            to_expr=_literal("10"),
            body=body,
        )
    return EmptyStatement()


class TestFuzz:
    """Property-based tests — visitor never crashes on valid IR."""

    @given(stmts=st.lists(st_statement(), min_size=0, max_size=5))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_visitor_never_crashes(self, stmts):
        """Base visitor handles any valid statement tree without error."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FuzzFB",
            interface=POUInterface(
                input_vars=[Variable(name="cond", data_type=_BOOL_REF)],
                output_vars=[Variable(name="out", data_type=_BOOL_REF)],
                static_vars=[
                    Variable(name="x", data_type=_INT_REF),
                    Variable(name="y", data_type=_INT_REF),
                    Variable(name="z", data_type=_INT_REF),
                ],
            ),
            networks=[Network(statements=list(stmts))],
        )
        visitor = AnalysisVisitor()
        findings = visitor.analyze_pou(pou)
        assert isinstance(findings, list)

    @given(stmts=st.lists(st_statement(), min_size=0, max_size=5))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_all_rules_never_crash(self, stmts):
        """Every rule handles random IR without crashing."""
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FuzzFB",
            interface=POUInterface(
                input_vars=[Variable(name="cond", data_type=_BOOL_REF)],
                output_vars=[Variable(name="out", data_type=_BOOL_REF)],
                static_vars=[
                    Variable(name="x", data_type=_INT_REF),
                    Variable(name="y", data_type=_INT_REF),
                    Variable(name="z", data_type=_INT_REF),
                ],
            ),
            networks=[Network(statements=list(stmts))],
        )
        result = analyze(pou)
        assert isinstance(result, AnalysisResult)


# ---------------------------------------------------------------------------
# Performance: large project completes quickly
# ---------------------------------------------------------------------------

class TestPerformance:

    def test_100_pou_project_under_1s(self):
        """Analyze a project with 100 POUs in under 1 second."""
        import time
        from plx.model.project import Project
        from plx.model.task import PeriodicTask

        pous = []
        for i in range(100):
            pou = POU(
                pou_type=POUType.FUNCTION_BLOCK,
                name=f"FB_{i}",
                interface=POUInterface(
                    input_vars=[Variable(name="sensor", data_type=_BOOL_REF)],
                    output_vars=[Variable(name="valve", data_type=_BOOL_REF)],
                    static_vars=[Variable(name="timer", data_type=NamedTypeRef(name="TON"))],
                ),
                networks=[Network(statements=[
                    IfStatement(
                        if_branch=IfBranch(
                            condition=VariableRef(name="sensor"),
                            body=[
                                FBInvocation(
                                    instance_name="timer",
                                    fb_type=NamedTypeRef(name="TON"),
                                    inputs={"IN": VariableRef(name="sensor")},
                                ),
                                Assignment(
                                    target=VariableRef(name="valve"),
                                    value=MemberAccessExpr(
                                        struct=VariableRef(name="timer"),
                                        member="Q",
                                    ),
                                ),
                            ],
                        ),
                        else_body=[
                            Assignment(
                                target=VariableRef(name="valve"),
                                value=LiteralExpr(value="FALSE"),
                            ),
                        ],
                    ),
                ])],
            )
            pous.append(pou)

        proj = Project(
            name="PerfTest",
            pous=pous,
            tasks=[PeriodicTask(
                name="Main", interval="T#10ms",
                assigned_pous=[f"FB_{i}" for i in range(100)],
            )],
        )

        start = time.perf_counter()
        result = analyze(proj)
        elapsed = time.perf_counter() - start

        assert isinstance(result, AnalysisResult)
        assert result.pou_count == 100
        assert elapsed < 1.0, f"Took {elapsed:.2f}s — should be under 1s"


# ---------------------------------------------------------------------------
# EnumCastRule — R2: flag TypeConversionExpr(primitive, enum literal)
# ---------------------------------------------------------------------------

_INT_TYPE_REF = PrimitiveTypeRef(type=PrimitiveType.INT)


class TestEnumCastRule:
    """EnumCastRule detects INT(EnumName#MEMBER) patterns in the IR."""

    def _pou_with_expr(self, expr):
        """Build a POU whose single network assigns *expr* to an INT var."""
        return POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(
                static_vars=[Variable(name="x", data_type=_INT_TYPE_REF)],
            ),
            networks=[Network(statements=[
                Assignment(target=VariableRef(name="x"), value=expr),
            ])],
        )

    def test_no_finding_for_plain_variable_cast(self):
        """INT(some_var) is valid ST and must not be flagged."""
        pou = self._pou_with_expr(
            TypeConversionExpr(
                target_type=_INT_TYPE_REF,
                source=VariableRef(name="y"),
            )
        )
        assert EnumCastRule().analyze_pou(pou) == []

    def test_no_finding_for_numeric_literal_cast(self):
        """INT(42) is valid ST and must not be flagged."""
        pou = self._pou_with_expr(
            TypeConversionExpr(
                target_type=_INT_TYPE_REF,
                source=LiteralExpr(value="42"),
            )
        )
        assert EnumCastRule().analyze_pou(pou) == []

    def test_finding_for_enum_literal_cast(self):
        """INT(BoxType#METAL) is invalid ST — must produce an ERROR finding."""
        pou = self._pou_with_expr(
            TypeConversionExpr(
                target_type=_INT_TYPE_REF,
                source=LiteralExpr(
                    value="BoxType#METAL",
                    data_type=NamedTypeRef(name="BoxType"),
                ),
            )
        )
        findings = EnumCastRule().analyze_pou(pou)
        assert len(findings) == 1
        assert findings[0].rule_id == "enum-cast-to-int"
        assert findings[0].severity == Severity.ERROR
        assert "BoxType#METAL" in findings[0].message

    def test_finding_in_all_rules(self):
        """EnumCastRule is included in ALL_RULES."""
        assert EnumCastRule in ALL_RULES

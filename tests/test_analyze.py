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
from plx.analyze._context import AnalysisContext, WriteInfo
from plx.analyze._rules import DeadSfcStepRule, UnguardedOutputRule
from plx.framework import (
    BOOL,
    DINT,
    INT,
    REAL,
    fb,
    input_var,
    output_var,
    program,
    project,
    sfc,
    static_var,
    step,
    transition,
)
from plx.model.pou import POU


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

    sensor = input_var(BOOL)
    valve = output_var(BOOL)

    def logic(self):
        if self.sensor:
            self.valve = True
        else:
            self.valve = False


@fb
class UnguardedOutputFB:
    """Output written unconditionally at top level."""

    valve = output_var(BOOL)

    def logic(self):
        self.valve = True


@fb
class MixedOutputFB:
    """One guarded output, one unguarded."""

    sensor = input_var(BOOL)
    guarded_out = output_var(BOOL)
    unguarded_out = output_var(BOOL)

    def logic(self):
        self.unguarded_out = False
        if self.sensor:
            self.guarded_out = True


@fb
class NestedGuardedFB:
    """Output written inside nested if — still guarded."""

    a = input_var(BOOL)
    b = input_var(BOOL)
    out = output_var(BOOL)

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

    count = static_var(INT)

    def logic(self):
        self.count = self.count + 1


@sfc
class ReachableSFC:
    """All steps are reachable via transitions."""

    cmd = input_var(BOOL)

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

    cmd = input_var(BOOL)

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

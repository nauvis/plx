"""Static analysis for compiled plx IR.

Examples
--------
::

    from plx.analyze import analyze
    result = analyze(project_ir)
    for f in result.findings:
        print(f"{f.severity.value}: {f.pou_name}: {f.message}")
"""

from __future__ import annotations

from typing import Union

from plx.model.pou import POU
from plx.model.project import Project

from ._results import AnalysisResult, Finding, Severity
from ._rules import (
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
from ._types import TypeEnvironment
from ._visitor import AnalysisVisitor

ALL_RULES: list[type[AnalysisVisitor]] = [
    # Safety
    UnguardedOutputRule,
    MultipleOutputWriteRule,
    WriteToInputRule,
    DivisionByZeroRule,
    # Correctness
    RealEqualityRule,
    MissingCaseElseRule,
    ForCounterWriteRule,
    TempFBInstanceRule,
    NarrowingConversionRule,
    ConstantOutOfRangeRule,
    EnumCastRule,
    IncompleteCaseEnumRule,
    # Complexity
    CyclomaticComplexityRule,
    MaxNestingDepthRule,
    # Style / Unused
    UnusedVariableRule,
    UnusedInputRule,
    UnusedOutputRule,
    EmptyBodyRule,
    VariableShadowRule,
    # SFC
    DeadSfcStepRule,
    SfcNoInitialStepRule,
    SfcMultipleInitialStepsRule,
    # Project-level
    RecursiveCallRule,
    CrossTaskWriteRule,
    UnusedPOURule,
    # Data flow
    UnreachableCodeRule,
    IgnoredFBOutputRule,
    UseBeforeDefRule,
]


def analyze(
    target: Union[Project, POU],
    *,
    rules: list[type[AnalysisVisitor]] | None = None,
) -> AnalysisResult:
    """Run static analysis rules on a compiled Project or POU.

    Parameters
    ----------
    target : Project or POU
        A compiled ``Project`` or single ``POU`` to analyze.
    rules : list[type[AnalysisVisitor]] or None, optional
        Rule classes to run. Defaults to ``ALL_RULES``.

    Returns
    -------
    AnalysisResult
        Aggregated result containing all findings from all rules.
    """
    rule_classes = rules if rules is not None else ALL_RULES
    all_findings: list[Finding] = []
    pou_count = 0

    for rule_cls in rule_classes:
        visitor = rule_cls()
        if isinstance(target, Project):
            result = visitor.analyze_project(target)
            pou_count = max(pou_count, result.pou_count)
        else:
            findings = visitor.analyze_pou(target)
            result = AnalysisResult(findings=findings, pou_count=1, rule_count=1)
            pou_count = 1
        all_findings.extend(result.findings)

    return AnalysisResult(
        findings=all_findings,
        pou_count=pou_count,
        rule_count=len(rule_classes),
    )


__all__ = [
    "analyze",
    "AnalysisResult",
    "AnalysisVisitor",
    "Finding",
    "Severity",
    "TypeEnvironment",
    "ALL_RULES",
]

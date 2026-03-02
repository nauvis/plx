"""Built-in analysis rules."""

from __future__ import annotations

from plx.model.sfc import SFCBody, Step

from ._context import AnalysisContext
from ._results import Finding, Severity
from ._visitor import AnalysisVisitor


class UnguardedOutputRule(AnalysisVisitor):
    """Flag output variables written unconditionally (not inside any if/case/loop).

    rule_id: ``"unguarded-output"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        for var_name, writes in ctx.writes.items():
            if var_name not in ctx.output_names:
                continue
            for w in writes:
                if not w.guarded:
                    ctx.findings.append(
                        Finding(
                            rule_id="unguarded-output",
                            severity=Severity.WARNING,
                            pou_name=ctx.pou_name,
                            message=(
                                f"Output '{var_name}' is written unconditionally"
                            ),
                            location=w.location,
                            details={"variable": var_name},
                        )
                    )


class DeadSfcStepRule(AnalysisVisitor):
    """Flag SFC steps that are neither initial nor targeted by any transition.

    rule_id: ``"sfc-dead-step"``
    """

    def on_sfc_exit(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        # Collect all step names that are transition targets
        targeted: set[str] = set()
        for trans in sfc.transitions:
            targeted.update(trans.target_steps)

        for step in sfc.steps:
            if step.is_initial:
                continue
            if step.name not in targeted:
                ctx.findings.append(
                    Finding(
                        rule_id="sfc-dead-step",
                        severity=Severity.WARNING,
                        pou_name=ctx.pou_name,
                        message=(
                            f"Step '{step.name}' is unreachable — "
                            f"no transition targets it and it is not the initial step"
                        ),
                        details={"step": step.name},
                    )
                )

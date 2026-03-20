"""Result models for static analysis findings."""

from __future__ import annotations

from enum import Enum

from plx.model._base import IRModel


class Severity(str, Enum):
    """Severity level for analysis findings.

    Attributes
    ----------
    INFO : str
        Informational finding that does not indicate a problem.
    WARNING : str
        Potential issue that may indicate a bug or bad practice.
    ERROR : str
        Definite problem that will likely cause incorrect PLC behavior.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Finding(IRModel):
    """A single analysis finding produced by a rule.

    Attributes
    ----------
    rule_id : str
        Unique identifier for the rule that produced this finding
        (e.g. ``"unguarded_output"``).
    severity : Severity
        How serious the finding is.
    pou_name : str
        Name of the POU (or ``"POU.Method"``) where the finding occurred.
    message : str
        Human-readable description of the issue.
    location : str
        Path within the POU body (e.g. ``"network 0 -> if_branch"``).
        Empty string if not applicable.
    details : dict[str, object]
        Rule-specific structured data (e.g. variable names, counts).
    """

    rule_id: str
    severity: Severity
    pou_name: str
    message: str
    location: str = ""
    details: dict[str, object] = {}


class AnalysisResult(IRModel):
    """Aggregated results from one or more analysis rules.

    Attributes
    ----------
    findings : list[Finding]
        All findings across all rules and POUs.
    pou_count : int
        Number of POUs that were analyzed.
    rule_count : int
        Number of rules that were run.
    """

    findings: list[Finding] = []
    pou_count: int = 0
    rule_count: int = 0

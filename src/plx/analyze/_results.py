"""Result models for static analysis findings."""

from __future__ import annotations

from enum import Enum

from plx.model._base import IRModel


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Finding(IRModel):
    """A single analysis finding."""

    rule_id: str
    severity: Severity
    pou_name: str
    message: str
    location: str = ""
    details: dict[str, object] = {}


class AnalysisResult(IRModel):
    """Aggregated results from one or more analysis rules."""

    findings: list[Finding] = []
    pou_count: int = 0
    rule_count: int = 0

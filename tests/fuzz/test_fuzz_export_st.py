"""Fuzz tests for the Structured Text exporter.

Properties tested:
1. to_structured_text() never crashes on valid IR
2. Output is always a non-empty string
3. Specific IR constructs produce expected ST keywords
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck

pytestmark = pytest.mark.fuzz

from plx.model import (
    POU,
    POUType,
    Network,
    POUInterface,
    Variable,
    PrimitiveTypeRef,
    PrimitiveType,
    Project,
    PeriodicTask,
)
from plx.export.st import to_structured_text

from tests.fuzz.strategies import (
    expressions,
    statements,
    statement_lists,
    pous,
    projects,
    pou_interfaces,
)


def _wrap_in_pou(stmts) -> POU:
    """Wrap statements in a minimal FB for export."""
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name="FuzzFB",
        networks=[Network(statements=stmts if isinstance(stmts, list) else [stmts])],
    )


# ---------------------------------------------------------------------------
# Expression export
# ---------------------------------------------------------------------------

class TestExpressionExport:

    @given(expr=expressions(max_depth=4))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes(self, expr):
        """ST exporter handles any valid expression without crashing."""
        from plx.model import Assignment, VariableRef
        stmt = Assignment(target=VariableRef(name="x"), value=expr)
        pou = _wrap_in_pou(stmt)
        result = to_structured_text(pou)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(expr=expressions(max_depth=5))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_deep_nesting(self, expr):
        """Deeply nested expressions don't cause stack overflow."""
        from plx.model import Assignment, VariableRef
        stmt = Assignment(target=VariableRef(name="result"), value=expr)
        pou = _wrap_in_pou(stmt)
        result = to_structured_text(pou)
        assert "result" in result


# ---------------------------------------------------------------------------
# Statement export
# ---------------------------------------------------------------------------

class TestStatementExport:

    @given(stmt=statements(max_depth=3))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes(self, stmt):
        """ST exporter handles any valid statement without crashing."""
        pou = _wrap_in_pou(stmt)
        result = to_structured_text(pou)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(stmts=statement_lists(min_size=1, max_size=10, max_depth=3))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_statement_list(self, stmts):
        """Multiple statements export without crashing."""
        pou = _wrap_in_pou(stmts)
        result = to_structured_text(pou)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# POU export
# ---------------------------------------------------------------------------

class TestPOUExport:

    @given(pou=pous(max_networks=3, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes(self, pou):
        """ST exporter handles any valid POU without crashing."""
        result = to_structured_text(pou)
        assert isinstance(result, str)
        assert pou.name in result

    @given(pou=pous(max_networks=3, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_contains_pou_type(self, pou):
        """Output contains the POU type keyword."""
        result = to_structured_text(pou)
        assert pou.pou_type.value in result

    @given(pou=pous(max_networks=2, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_contains_end_keyword(self, pou):
        """Output contains the matching END_ keyword."""
        result = to_structured_text(pou)
        end_keyword = f"END_{pou.pou_type.value}"
        assert end_keyword in result

    @given(pou=pous(max_networks=2, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_variables_declared(self, pou):
        """All interface variables appear in the output."""
        result = to_structured_text(pou)
        for var in pou.interface.input_vars:
            assert var.name in result
        for var in pou.interface.output_vars:
            assert var.name in result


# ---------------------------------------------------------------------------
# Project export
# ---------------------------------------------------------------------------

class TestProjectExport:

    @given(proj=projects(max_pous=3, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_never_crashes(self, proj):
        """ST exporter handles any valid project without crashing."""
        result = to_structured_text(proj)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(proj=projects(max_pous=4, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_all_pous_present(self, proj):
        """All POU names appear in the exported output."""
        result = to_structured_text(proj)
        for pou in proj.pous:
            assert pou.name in result


# ---------------------------------------------------------------------------
# Source map generation
# ---------------------------------------------------------------------------

class TestSourceMap:

    @given(pou=pous(max_networks=2, max_depth=2))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_source_map_never_crashes(self, pou):
        """Source map generation doesn't crash on random POUs."""
        text, source_map = to_structured_text(pou, source_map=True)
        assert isinstance(text, str)
        assert isinstance(source_map, list)

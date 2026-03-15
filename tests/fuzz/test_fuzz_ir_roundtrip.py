"""Fuzz tests for IR model construction and JSON serialization roundtrip.

Properties tested:
1. Random IR trees construct without crashing (Pydantic validation)
2. model_dump_json() → model_validate_json() is identity (lossless serialization)
3. model_dump() → model_validate() is identity (dict roundtrip)
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck

pytestmark = pytest.mark.fuzz

from plx.model import (
    Project,
    POU,
    POUType,
    POUInterface,
    Network,
    Variable,
    GlobalVariableList,
    PeriodicTask,
)

from tests.fuzz.strategies import (
    expressions,
    statements,
    variables,
    variable_lists,
    pou_interfaces,
    pous,
    projects,
    type_refs,
    type_definitions,
    global_variable_lists,
    literal_exprs,
    all_primitive_type_refs,
    struct_types,
    enum_types,
    statement_lists,
)


# ---------------------------------------------------------------------------
# Expression roundtrip
# ---------------------------------------------------------------------------

class TestExpressionRoundtrip:
    """Expression trees survive JSON serialization."""

    @given(expr=expressions(max_depth=4))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, expr):
        """Serialize to JSON and back — result must equal original."""
        # Wrap in a statement to use the discriminated union
        from plx.model import Assignment, VariableRef
        stmt = Assignment(target=VariableRef(name="x"), value=expr)
        json_str = stmt.model_dump_json()
        restored = Assignment.model_validate_json(json_str)
        assert restored == stmt

    @given(expr=expressions(max_depth=4))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_dict_roundtrip(self, expr):
        """Serialize to dict and back — result must equal original."""
        from plx.model import Assignment, VariableRef
        stmt = Assignment(target=VariableRef(name="x"), value=expr)
        data = stmt.model_dump()
        restored = Assignment.model_validate(data)
        assert restored == stmt

    @given(expr=expressions(max_depth=5))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_deep_expressions_construct(self, expr):
        """Deeply nested expressions don't crash Pydantic."""
        assert expr.kind is not None


# ---------------------------------------------------------------------------
# TypeRef roundtrip
# ---------------------------------------------------------------------------

class TestTypeRefRoundtrip:

    @given(tr=type_refs(max_depth=3))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, tr):
        """TypeRef survives JSON roundtrip via Variable wrapper."""
        var = Variable(name="x", data_type=tr)
        json_str = var.model_dump_json()
        restored = Variable.model_validate_json(json_str)
        assert restored == var

    @given(tr=all_primitive_type_refs())
    @settings(max_examples=50)
    def test_all_primitives(self, tr):
        """Every primitive type can be used in a Variable."""
        var = Variable(name="test_var", data_type=tr)
        assert var.data_type.type == tr.type


# ---------------------------------------------------------------------------
# TypeDefinition roundtrip
# ---------------------------------------------------------------------------

class TestTypeDefinitionRoundtrip:

    @given(td=type_definitions())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, td):
        data = td.model_dump()
        # Use Project as wrapper for discriminated union deserialization
        proj = Project(name="test", data_types=[td])
        json_str = proj.model_dump_json()
        restored = Project.model_validate_json(json_str)
        assert restored.data_types[0] == td

    @given(st=struct_types())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_struct_members_unique(self, st):
        """Generated structs always have unique member names."""
        names = [m.name for m in st.members]
        assert len(names) == len(set(names))

    @given(et=enum_types())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_enum_members_unique(self, et):
        """Generated enums always have unique member names."""
        names = [m.name for m in et.members]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Statement roundtrip
# ---------------------------------------------------------------------------

class TestStatementRoundtrip:

    @given(stmt=statements(max_depth=3))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, stmt):
        """Statement trees survive JSON serialization."""
        # Wrap in Network → POU for discriminated union context
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Fuzz",
            networks=[Network(statements=[stmt])],
        )
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored.networks[0].statements[0] == stmt

    @given(stmts=statement_lists(min_size=1, max_size=8, max_depth=3))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_statement_list_roundtrip(self, stmts):
        """Lists of statements survive roundtrip."""
        pou = POU(
            pou_type=POUType.PROGRAM,
            name="FuzzProg",
            networks=[Network(statements=stmts)],
        )
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored.networks[0].statements == stmts


# ---------------------------------------------------------------------------
# Variable roundtrip
# ---------------------------------------------------------------------------

class TestVariableRoundtrip:

    @given(var=variables())
    @settings(max_examples=100)
    def test_json_roundtrip(self, var):
        json_str = var.model_dump_json()
        restored = Variable.model_validate_json(json_str)
        assert restored == var

    @given(vl=variable_lists(min_size=1, max_size=8))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_variable_list_unique_names(self, vl):
        """Generated variable lists always have unique names."""
        names = [v.name for v in vl]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# POUInterface roundtrip
# ---------------------------------------------------------------------------

class TestPOUInterfaceRoundtrip:

    @given(iface=pou_interfaces())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, iface):
        json_str = iface.model_dump_json()
        restored = POUInterface.model_validate_json(json_str)
        assert restored == iface

    @given(iface=pou_interfaces())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_no_duplicate_var_names(self, iface):
        """All variable names across all sections are unique."""
        all_names = (
            [v.name for v in iface.input_vars]
            + [v.name for v in iface.output_vars]
            + [v.name for v in iface.static_vars]
            + [v.name for v in iface.temp_vars]
            + [v.name for v in iface.constant_vars]
            + [v.name for v in iface.external_vars]
        )
        assert len(all_names) == len(set(all_names))


# ---------------------------------------------------------------------------
# POU roundtrip
# ---------------------------------------------------------------------------

class TestPOURoundtrip:

    @given(pou=pous(max_networks=3, max_depth=2))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, pou):
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored == pou

    @given(pou=pous(max_networks=2, max_depth=3))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_dict_roundtrip(self, pou):
        data = pou.model_dump()
        restored = POU.model_validate(data)
        assert restored == pou


# ---------------------------------------------------------------------------
# Project roundtrip
# ---------------------------------------------------------------------------

class TestProjectRoundtrip:

    @given(proj=projects(max_pous=3, max_depth=2))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, proj):
        """Full projects survive JSON serialization."""
        json_str = proj.model_dump_json()
        restored = Project.model_validate_json(json_str)
        assert restored == proj

    @given(proj=projects(max_pous=4, max_depth=2))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_dict_roundtrip(self, proj):
        data = proj.model_dump()
        restored = Project.model_validate(data)
        assert restored == proj

    @given(proj=projects(max_pous=3))
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_unique_pou_names(self, proj):
        """Generated projects always have unique POU names."""
        names = [p.name for p in proj.pous]
        assert len(names) == len(set(names))

    @given(proj=projects(max_pous=3))
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_unique_type_names(self, proj):
        """Generated projects always have unique type names."""
        names = [t.name for t in proj.data_types]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# GVL roundtrip
# ---------------------------------------------------------------------------

class TestGVLRoundtrip:

    @given(gvl=global_variable_lists())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_json_roundtrip(self, gvl):
        json_str = gvl.model_dump_json()
        restored = GlobalVariableList.model_validate_json(json_str)
        assert restored == gvl

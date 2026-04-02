"""Tests for metadata and scope fields on IR model nodes."""

from plx.model.pou import (
    POU,
    Language,
    Method,
    POUInterface,
    POUType,
    Property,
)
from plx.model.project import GlobalVariableList
from plx.model.types import PrimitiveType, PrimitiveTypeRef, StructMember, StructType
from plx.model.variables import Variable

BOOL_REF = PrimitiveTypeRef(type=PrimitiveType.BOOL)


# ---------------------------------------------------------------------------
# Variable.metadata
# ---------------------------------------------------------------------------


class TestVariableMetadata:
    def test_default_empty(self):
        v = Variable(name="x", data_type=BOOL_REF)
        assert v.metadata == {}

    def test_set_metadata(self):
        v = Variable(name="x", data_type=BOOL_REF, metadata={"vendor": "ab", "attr": True})
        assert v.metadata == {"vendor": "ab", "attr": True}

    def test_json_roundtrip(self):
        v = Variable(name="x", data_type=BOOL_REF, metadata={"s7_accessible": True})
        restored = Variable.model_validate_json(v.model_dump_json())
        assert restored == v
        assert restored.metadata == {"s7_accessible": True}


# ---------------------------------------------------------------------------
# POU.metadata
# ---------------------------------------------------------------------------


class TestPOUMetadata:
    def test_default_empty(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1")
        assert pou.metadata == {}

    def test_set_metadata(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            metadata={"vendor": "beckhoff", "pragmas": ["{attribute 'call_after_init'}"]},
        )
        assert pou.metadata["vendor"] == "beckhoff"
        assert len(pou.metadata["pragmas"]) == 1

    def test_json_roundtrip(self):
        pou = POU(
            pou_type=POUType.PROGRAM,
            name="Main",
            metadata={"compile_time": True},
        )
        restored = POU.model_validate_json(pou.model_dump_json())
        assert restored == pou
        assert restored.metadata == {"compile_time": True}


# ---------------------------------------------------------------------------
# GlobalVariableList.metadata
# ---------------------------------------------------------------------------


class TestGVLMetadata:
    def test_default_empty(self):
        gvl = GlobalVariableList(name="GVL1")
        assert gvl.metadata == {}

    def test_set_metadata(self):
        gvl = GlobalVariableList(name="GVL1", metadata={"volatile": True})
        assert gvl.metadata == {"volatile": True}

    def test_json_roundtrip(self):
        gvl = GlobalVariableList(name="GVL1", metadata={"pragma": "pack_mode=1"})
        restored = GlobalVariableList.model_validate_json(gvl.model_dump_json())
        assert restored == gvl
        assert restored.metadata == {"pragma": "pack_mode=1"}


# ---------------------------------------------------------------------------
# GlobalVariableList.scope
# ---------------------------------------------------------------------------


class TestGVLScope:
    def test_default_empty(self):
        gvl = GlobalVariableList(name="GVL1")
        assert gvl.scope == ""

    def test_controller_scope(self):
        gvl = GlobalVariableList(name="Tags", scope="controller")
        assert gvl.scope == "controller"

    def test_program_scope(self):
        gvl = GlobalVariableList(name="Local", scope="program")
        assert gvl.scope == "program"

    def test_json_roundtrip(self):
        gvl = GlobalVariableList(name="Tags", scope="controller")
        restored = GlobalVariableList.model_validate_json(gvl.model_dump_json())
        assert restored == gvl
        assert restored.scope == "controller"

    def test_backward_compat_no_scope(self):
        """Constructing without scope still works (default empty string)."""
        gvl = GlobalVariableList(
            name="X",
            variables=[
                Variable(name="v", data_type=BOOL_REF),
            ],
        )
        assert gvl.scope == ""
        assert len(gvl.variables) == 1


# ---------------------------------------------------------------------------
# POU.abstract / POU.description / POU.safety
# ---------------------------------------------------------------------------


class TestPOUAbstract:
    def test_default_false(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1")
        assert pou.abstract is False

    def test_set_abstract(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1", abstract=True)
        assert pou.abstract is True

    def test_json_roundtrip(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1", abstract=True)
        restored = POU.model_validate_json(pou.model_dump_json())
        assert restored.abstract is True


class TestPOUDescription:
    def test_default_empty(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1")
        assert pou.description == ""

    def test_set_description(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1", description="Motor controller")
        assert pou.description == "Motor controller"

    def test_json_roundtrip(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1", description="Motor controller")
        restored = POU.model_validate_json(pou.model_dump_json())
        assert restored.description == "Motor controller"


class TestPOUSafety:
    def test_default_false(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1")
        assert pou.safety is False

    def test_set_safety(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1", safety=True)
        assert pou.safety is True

    def test_json_roundtrip(self):
        pou = POU(pou_type=POUType.FUNCTION_BLOCK, name="FB1", safety=True)
        restored = POU.model_validate_json(pou.model_dump_json())
        assert restored.safety is True


# ---------------------------------------------------------------------------
# Method.abstract / Method.final / Method.description
# ---------------------------------------------------------------------------

REAL_REF = PrimitiveTypeRef(type=PrimitiveType.REAL)


class TestMethodAbstractFinal:
    def test_defaults(self):
        m = Method(name="Run")
        assert m.abstract is False
        assert m.final is False
        assert m.description == ""

    def test_set_abstract(self):
        m = Method(name="Run", abstract=True)
        assert m.abstract is True

    def test_set_final(self):
        m = Method(name="Run", final=True)
        assert m.final is True

    def test_set_description(self):
        m = Method(name="Run", description="Runs the motor")
        assert m.description == "Runs the motor"

    def test_json_roundtrip(self):
        m = Method(name="Run", abstract=True, final=False, description="desc")
        restored = Method.model_validate_json(m.model_dump_json())
        assert restored.abstract is True
        assert restored.final is False
        assert restored.description == "desc"


# ---------------------------------------------------------------------------
# Property.abstract / Property.final
# ---------------------------------------------------------------------------


class TestPropertyAbstractFinal:
    def test_defaults(self):
        p = Property(name="Speed", data_type=REAL_REF)
        assert p.abstract is False
        assert p.final is False

    def test_set_abstract(self):
        p = Property(name="Speed", data_type=REAL_REF, abstract=True)
        assert p.abstract is True

    def test_set_final(self):
        p = Property(name="Speed", data_type=REAL_REF, final=True)
        assert p.final is True

    def test_json_roundtrip(self):
        p = Property(name="Speed", data_type=REAL_REF, abstract=True, final=True)
        restored = Property.model_validate_json(p.model_dump_json())
        assert restored.abstract is True
        assert restored.final is True


# ---------------------------------------------------------------------------
# POUInterface.external_vars
# ---------------------------------------------------------------------------


class TestExternalVars:
    def test_default_empty(self):
        iface = POUInterface()
        assert iface.external_vars == []

    def test_set_external_vars(self):
        iface = POUInterface(
            external_vars=[Variable(name="global_speed", data_type=REAL_REF)],
        )
        assert len(iface.external_vars) == 1
        assert iface.external_vars[0].name == "global_speed"

    def test_json_roundtrip(self):
        iface = POUInterface(
            external_vars=[Variable(name="x", data_type=BOOL_REF)],
        )
        restored = POUInterface.model_validate_json(iface.model_dump_json())
        assert len(restored.external_vars) == 1
        assert restored.external_vars[0].name == "x"


# ---------------------------------------------------------------------------
# StructType.extends
# ---------------------------------------------------------------------------


class TestStructExtends:
    def test_default_none(self):
        st = StructType(
            name="Base",
            members=[
                StructMember(name="x", data_type=BOOL_REF),
            ],
        )
        assert st.extends is None

    def test_set_extends(self):
        st = StructType(
            name="Derived",
            extends="Base",
            members=[
                StructMember(name="y", data_type=REAL_REF),
            ],
        )
        assert st.extends == "Base"

    def test_json_roundtrip(self):
        st = StructType(
            name="Derived",
            extends="Base",
            members=[
                StructMember(name="y", data_type=REAL_REF),
            ],
        )
        restored = StructType.model_validate_json(st.model_dump_json())
        assert restored.extends == "Base"


# ---------------------------------------------------------------------------
# GlobalVariableList.qualified_only
# ---------------------------------------------------------------------------


class TestGVLQualifiedOnly:
    def test_default_false(self):
        gvl = GlobalVariableList(name="GVL1")
        assert gvl.qualified_only is False

    def test_set_qualified_only(self):
        gvl = GlobalVariableList(name="GVL1", qualified_only=True)
        assert gvl.qualified_only is True

    def test_json_roundtrip(self):
        gvl = GlobalVariableList(name="GVL1", qualified_only=True)
        restored = GlobalVariableList.model_validate_json(gvl.model_dump_json())
        assert restored.qualified_only is True


# ---------------------------------------------------------------------------
# Language.SFC
# ---------------------------------------------------------------------------


class TestLanguageSFC:
    def test_sfc_value(self):
        assert Language.SFC == "SFC"
        assert Language.SFC.value == "SFC"

    def test_from_string(self):
        assert Language("SFC") is Language.SFC

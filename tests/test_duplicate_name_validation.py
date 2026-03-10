"""Tests for duplicate name validation across the IR."""

from __future__ import annotations

import pytest

from plx.model.expressions import BitAccessExpr, LiteralExpr, VariableRef
from plx.model.pou import (
    Method,
    Network,
    POU,
    POUAction,
    POUInterface,
    POUType,
    Property,
)
from plx.model.project import GlobalVariableList, Project
from plx.model.sfc import SFCBody, Step, Transition
from plx.model.statements import CaseBranch, CaseStatement
from plx.model.task import ContinuousTask, PeriodicTask
from plx.model.types import (
    EnumMember,
    EnumType,
    PrimitiveTypeRef,
    StringTypeRef,
    StructMember,
    StructType,
    UnionType,
)
from plx.model.variables import Variable


# ---------- POUInterface: duplicate variable names ----------

class TestPOUInterfaceDuplicateVars:
    def test_same_section_rejects_duplicate(self):
        with pytest.raises(ValueError, match="Duplicate variable name 'x'"):
            POUInterface(
                input_vars=[
                    Variable(name="x", data_type=PrimitiveTypeRef(type="BOOL")),
                    Variable(name="x", data_type=PrimitiveTypeRef(type="BOOL")),
                ],
            )

    def test_cross_section_rejects_duplicate(self):
        with pytest.raises(ValueError, match="Duplicate variable name 'x'"):
            POUInterface(
                input_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type="BOOL"))],
                output_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type="BOOL"))],
            )

    def test_unique_names_accepted(self):
        iface = POUInterface(
            input_vars=[Variable(name="a", data_type=PrimitiveTypeRef(type="BOOL"))],
            output_vars=[Variable(name="b", data_type=PrimitiveTypeRef(type="BOOL"))],
            static_vars=[Variable(name="c", data_type=PrimitiveTypeRef(type="INT"))],
        )
        assert len(iface.input_vars) == 1

    def test_error_mentions_sections(self):
        with pytest.raises(ValueError, match="input_vars.*output_vars"):
            POUInterface(
                input_vars=[Variable(name="val", data_type=PrimitiveTypeRef(type="INT"))],
                output_vars=[Variable(name="val", data_type=PrimitiveTypeRef(type="INT"))],
            )


# ---------- POU: duplicate method / property / action names ----------

class TestPOUDuplicateMethods:
    def test_duplicate_method_rejected(self):
        with pytest.raises(ValueError, match="Duplicate method name 'Run'"):
            POU(
                pou_type=POUType.FUNCTION_BLOCK,
                name="MyFB",
                methods=[
                    Method(name="Run"),
                    Method(name="Run"),
                ],
            )

    def test_unique_methods_accepted(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MyFB",
            methods=[Method(name="Run"), Method(name="Stop")],
        )
        assert len(pou.methods) == 2


class TestPOUDuplicateProperties:
    def test_duplicate_property_rejected(self):
        with pytest.raises(ValueError, match="Duplicate property name 'Value'"):
            POU(
                pou_type=POUType.FUNCTION_BLOCK,
                name="MyFB",
                properties=[
                    Property(name="Value", data_type=PrimitiveTypeRef(type="REAL")),
                    Property(name="Value", data_type=PrimitiveTypeRef(type="REAL")),
                ],
            )

    def test_unique_properties_accepted(self):
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="MyFB",
            properties=[
                Property(name="Value", data_type=PrimitiveTypeRef(type="REAL")),
                Property(name="Status", data_type=PrimitiveTypeRef(type="INT")),
            ],
        )
        assert len(pou.properties) == 2


class TestPOUDuplicateActions:
    def test_duplicate_action_rejected(self):
        with pytest.raises(ValueError, match="Duplicate action name 'Init'"):
            POU(
                pou_type=POUType.PROGRAM,
                name="Main",
                actions=[
                    POUAction(name="Init"),
                    POUAction(name="Init"),
                ],
            )

    def test_unique_actions_accepted(self):
        pou = POU(
            pou_type=POUType.PROGRAM,
            name="Main",
            actions=[POUAction(name="Init"), POUAction(name="Cleanup")],
        )
        assert len(pou.actions) == 2


# ---------- INTERFACE POU constraints ----------

class TestInterfacePOUConstraints:
    def test_interface_rejects_static_vars(self):
        with pytest.raises(ValueError, match="INTERFACE POUs must not have static_vars"):
            POU(
                pou_type=POUType.INTERFACE,
                name="IMotor",
                interface=POUInterface(
                    static_vars=[Variable(name="x", data_type=PrimitiveTypeRef(type="INT"))],
                ),
            )

    def test_interface_rejects_temp_vars(self):
        with pytest.raises(ValueError, match="INTERFACE POUs must not have temp_vars"):
            POU(
                pou_type=POUType.INTERFACE,
                name="IMotor",
                interface=POUInterface(
                    temp_vars=[Variable(name="t", data_type=PrimitiveTypeRef(type="INT"))],
                ),
            )

    def test_interface_rejects_actions(self):
        with pytest.raises(ValueError, match="INTERFACE POUs must not have actions"):
            POU(
                pou_type=POUType.INTERFACE,
                name="IMotor",
                actions=[POUAction(name="Init")],
            )

    def test_interface_with_methods_accepted(self):
        pou = POU(
            pou_type=POUType.INTERFACE,
            name="IMotor",
            methods=[Method(name="Start")],
        )
        assert len(pou.methods) == 1


# ---------- Project: duplicate POU / data type / GVL / task names ----------

def _simple_fb(name: str) -> POU:
    return POU(pou_type=POUType.FUNCTION_BLOCK, name=name)


def _simple_program(name: str) -> POU:
    return POU(pou_type=POUType.PROGRAM, name=name)


class TestProjectDuplicatePOUs:
    def test_duplicate_pou_rejected(self):
        with pytest.raises(ValueError, match="Duplicate POU name 'Motor'"):
            Project(
                name="Test",
                pous=[_simple_fb("Motor"), _simple_fb("Motor")],
            )

    def test_unique_pous_accepted(self):
        proj = Project(
            name="Test",
            pous=[_simple_fb("Motor"), _simple_fb("Valve")],
        )
        assert len(proj.pous) == 2

    def test_same_name_different_type_rejected(self):
        """A PROGRAM and FB with the same name should still be rejected."""
        with pytest.raises(ValueError, match="Duplicate POU name 'Main'"):
            Project(
                name="Test",
                pous=[_simple_program("Main"), _simple_fb("Main")],
            )


class TestProjectDuplicateDataTypes:
    def test_duplicate_data_type_rejected(self):
        dt = StructType(name="MyStruct", members=[
            StructMember(name="x", data_type=PrimitiveTypeRef(type="INT")),
        ])
        with pytest.raises(ValueError, match="Duplicate data type name 'MyStruct'"):
            Project(name="Test", data_types=[dt, dt])

    def test_unique_data_types_accepted(self):
        dt1 = StructType(name="Struct1", members=[
            StructMember(name="x", data_type=PrimitiveTypeRef(type="INT")),
        ])
        dt2 = StructType(name="Struct2", members=[
            StructMember(name="y", data_type=PrimitiveTypeRef(type="REAL")),
        ])
        proj = Project(name="Test", data_types=[dt1, dt2])
        assert len(proj.data_types) == 2


class TestProjectDuplicateGVLs:
    def test_duplicate_gvl_rejected(self):
        with pytest.raises(ValueError, match="Duplicate global variable list name 'Globals'"):
            Project(
                name="Test",
                global_variable_lists=[
                    GlobalVariableList(name="Globals"),
                    GlobalVariableList(name="Globals"),
                ],
            )

    def test_unique_gvls_accepted(self):
        proj = Project(
            name="Test",
            global_variable_lists=[
                GlobalVariableList(name="Globals"),
                GlobalVariableList(name="IOTags"),
            ],
        )
        assert len(proj.global_variable_lists) == 2


class TestProjectDuplicateTasks:
    def test_duplicate_task_rejected(self):
        with pytest.raises(ValueError, match="Duplicate task name 'Main'"):
            Project(
                name="Test",
                tasks=[
                    ContinuousTask(name="Main"),
                    ContinuousTask(name="Main"),
                ],
            )

    def test_unique_tasks_accepted(self):
        proj = Project(
            name="Test",
            tasks=[
                ContinuousTask(name="Main"),
                PeriodicTask(name="Fast", interval="T#10ms"),
            ],
        )
        assert len(proj.tasks) == 2


# ---------- GVL: duplicate variable names ----------

class TestGVLDuplicateVars:
    def test_duplicate_var_rejected(self):
        with pytest.raises(ValueError, match="Duplicate variable name 'speed'"):
            GlobalVariableList(
                name="Globals",
                variables=[
                    Variable(name="speed", data_type=PrimitiveTypeRef(type="REAL")),
                    Variable(name="speed", data_type=PrimitiveTypeRef(type="REAL")),
                ],
            )

    def test_unique_vars_accepted(self):
        gvl = GlobalVariableList(
            name="Globals",
            variables=[
                Variable(name="speed", data_type=PrimitiveTypeRef(type="REAL")),
                Variable(name="temp", data_type=PrimitiveTypeRef(type="REAL")),
            ],
        )
        assert len(gvl.variables) == 2


# ---------- Type definitions: duplicate member names ----------

class TestStructDuplicateMembers:
    def test_duplicate_member_rejected(self):
        with pytest.raises(ValueError, match="Duplicate member name 'x'.*struct.*MyStruct"):
            StructType(name="MyStruct", members=[
                StructMember(name="x", data_type=PrimitiveTypeRef(type="INT")),
                StructMember(name="x", data_type=PrimitiveTypeRef(type="REAL")),
            ])

    def test_unique_members_accepted(self):
        st = StructType(name="MyStruct", members=[
            StructMember(name="x", data_type=PrimitiveTypeRef(type="INT")),
            StructMember(name="y", data_type=PrimitiveTypeRef(type="REAL")),
        ])
        assert len(st.members) == 2


class TestEnumDuplicateMembers:
    def test_duplicate_member_rejected(self):
        with pytest.raises(ValueError, match="Duplicate member name 'RED'.*enum.*Colors"):
            EnumType(name="Colors", members=[
                EnumMember(name="RED", value=0),
                EnumMember(name="RED", value=1),
            ])

    def test_unique_members_accepted(self):
        et = EnumType(name="Colors", members=[
            EnumMember(name="RED", value=0),
            EnumMember(name="GREEN", value=1),
            EnumMember(name="BLUE", value=2),
        ])
        assert len(et.members) == 3

    def test_duplicate_values_allowed(self):
        """Enum aliases (same value, different name) are valid."""
        et = EnumType(name="Status", members=[
            EnumMember(name="OK", value=0),
            EnumMember(name="SUCCESS", value=0),
        ])
        assert len(et.members) == 2


class TestUnionDuplicateMembers:
    def test_duplicate_member_rejected(self):
        with pytest.raises(ValueError, match="Duplicate member name 'val'.*union.*MyUnion"):
            UnionType(name="MyUnion", members=[
                StructMember(name="val", data_type=PrimitiveTypeRef(type="INT")),
                StructMember(name="val", data_type=PrimitiveTypeRef(type="REAL")),
            ])

    def test_unique_members_accepted(self):
        ut = UnionType(name="MyUnion", members=[
            StructMember(name="int_val", data_type=PrimitiveTypeRef(type="INT")),
            StructMember(name="real_val", data_type=PrimitiveTypeRef(type="REAL")),
        ])
        assert len(ut.members) == 2


# ---------- SFC: step names and transition references ----------

class TestSFCStepNames:
    def test_duplicate_step_names_rejected(self):
        with pytest.raises(ValueError, match="Duplicate step name 'IDLE'"):
            SFCBody(steps=[
                Step(name="IDLE", is_initial=True),
                Step(name="IDLE"),
            ])

    def test_unique_step_names_accepted(self):
        body = SFCBody(steps=[
            Step(name="IDLE", is_initial=True),
            Step(name="RUN"),
        ])
        assert len(body.steps) == 2


class TestSFCTransitionRefs:
    def test_invalid_source_step_rejected(self):
        with pytest.raises(ValueError, match="unknown source step 'MISSING'"):
            SFCBody(
                steps=[Step(name="S1", is_initial=True), Step(name="S2")],
                transitions=[
                    Transition(
                        source_steps=["MISSING"],
                        target_steps=["S2"],
                        condition=LiteralExpr(value="TRUE"),
                    ),
                ],
            )

    def test_invalid_target_step_rejected(self):
        with pytest.raises(ValueError, match="unknown target step 'MISSING'"):
            SFCBody(
                steps=[Step(name="S1", is_initial=True), Step(name="S2")],
                transitions=[
                    Transition(
                        source_steps=["S1"],
                        target_steps=["MISSING"],
                        condition=LiteralExpr(value="TRUE"),
                    ),
                ],
            )

    def test_valid_refs_accepted(self):
        body = SFCBody(
            steps=[Step(name="S1", is_initial=True), Step(name="S2")],
            transitions=[
                Transition(
                    source_steps=["S1"],
                    target_steps=["S2"],
                    condition=LiteralExpr(value="TRUE"),
                ),
            ],
        )
        assert len(body.transitions) == 1

    def test_empty_steps_skips_validation(self):
        """Transitions without steps don't trigger ref validation."""
        body = SFCBody(steps=[], transitions=[])
        assert body.steps == []


# ---------- CaseStatement: non-empty branches ----------

class TestCaseStatementBranches:
    def test_empty_branches_rejected(self):
        with pytest.raises(ValueError, match="at least one branch"):
            CaseStatement(
                selector=VariableRef(name="state"),
                branches=[],
            )

    def test_with_branches_accepted(self):
        stmt = CaseStatement(
            selector=VariableRef(name="state"),
            branches=[CaseBranch(values=[0], body=[])],
        )
        assert len(stmt.branches) == 1


# ---------- StringTypeRef: positive max_length ----------

class TestStringTypeRefMaxLength:
    def test_zero_max_length_rejected(self):
        with pytest.raises(ValueError, match="max_length must be >= 1"):
            StringTypeRef(max_length=0)

    def test_negative_max_length_rejected(self):
        with pytest.raises(ValueError, match="max_length must be >= 1"):
            StringTypeRef(max_length=-5)

    def test_positive_max_length_accepted(self):
        s = StringTypeRef(max_length=255)
        assert s.max_length == 255

    def test_none_max_length_accepted(self):
        s = StringTypeRef()
        assert s.max_length is None


# ---------- BitAccessExpr: non-negative index ----------

class TestBitAccessExprIndex:
    def test_negative_index_rejected(self):
        with pytest.raises(Exception):
            BitAccessExpr(
                target=VariableRef(name="word"),
                bit_index=-1,
            )

    def test_zero_index_accepted(self):
        expr = BitAccessExpr(
            target=VariableRef(name="word"),
            bit_index=0,
        )
        assert expr.bit_index == 0

    def test_positive_index_accepted(self):
        expr = BitAccessExpr(
            target=VariableRef(name="word"),
            bit_index=15,
        )
        assert expr.bit_index == 15

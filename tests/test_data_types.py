"""Tests for @struct and @enumeration decorators."""

import pytest

from plx.framework._compiler import CompileError
from plx.framework._errors import DefinitionError, ProjectAssemblyError
from plx.framework._data_types import (
    _is_data_type,
    _is_enumeration,
    _is_struct,
    enumeration,
    struct,
)
from plx.framework._decorators import fb, program
from plx.framework._descriptors import Input, Field, Output
from plx.framework._project import project
from plx.framework._types import (
    ARRAY,
    BOOL,
    DINT,
    INT,
    REAL,
    _resolve_type_ref,
)
from plx.model.expressions import BinaryExpr, BinaryOp, LiteralExpr, VariableRef
from plx.model.pou import POU
from plx.model.statements import Assignment, CaseStatement
from plx.model.types import (
    EnumType,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
    StructMember,
    StructType,
)


# ---------------------------------------------------------------------------
# @struct
# ---------------------------------------------------------------------------

class TestStruct:
    def test_basic_struct(self):
        @struct
        class MotorData:
            speed: REAL = 0.0
            running: BOOL = False
            fault_code: INT = 0

        compiled = MotorData.compile()
        assert isinstance(compiled, StructType)
        assert compiled.name == "MotorData"
        assert len(compiled.members) == 3

    def test_member_names(self):
        @struct
        class Pair:
            x: REAL = 0.0
            y: REAL = 0.0

        compiled = Pair.compile()
        assert compiled.members[0].name == "x"
        assert compiled.members[1].name == "y"

    def test_member_types(self):
        @struct
        class Mixed:
            flag: BOOL = True
            count: DINT = 0
            value: REAL = 1.5

        compiled = Mixed.compile()
        assert compiled.members[0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert compiled.members[1].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)
        assert compiled.members[2].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_member_defaults(self):
        @struct
        class WithDefaults:
            speed: REAL = 1500.0
            running: BOOL = True
            code: INT = 42

        compiled = WithDefaults.compile()
        assert compiled.members[0].initial_value == "1500.0"
        assert compiled.members[1].initial_value == "TRUE"
        assert compiled.members[2].initial_value == "42"

    def test_no_defaults(self):
        @struct
        class NoDefaults:
            x: REAL
            y: REAL

        compiled = NoDefaults.compile()
        assert compiled.members[0].initial_value is None
        assert compiled.members[1].initial_value is None

    def test_nested_struct_type(self):
        @struct
        class Inner:
            value: REAL = 0.0

        @struct
        class Outer:
            data: Inner

        compiled = Outer.compile()
        assert compiled.members[0].data_type == NamedTypeRef(name="Inner")

    def test_array_member(self):
        @struct
        class WithArray:
            values: ARRAY(REAL, 10)

        compiled = WithArray.compile()
        assert compiled.members[0].data_type.kind == "array"

    def test_empty_struct_error(self):
        with pytest.raises(DefinitionError, match="no annotated members"):
            @struct
            class Empty:
                pass

    def test_struct_marker(self):
        @struct
        class Marked:
            x: INT = 0

        assert _is_struct(Marked)
        assert not _is_enumeration(Marked)
        assert _is_data_type(Marked)

    def test_struct_json_roundtrip(self):
        @struct
        class RoundTrip:
            a: BOOL = True
            b: INT = 5

        compiled = RoundTrip.compile()
        json_str = compiled.model_dump_json()
        restored = StructType.model_validate_json(json_str)
        assert restored == compiled

    def test_compiled_type_attribute(self):
        @struct
        class HasAttr:
            x: REAL = 0.0

        assert hasattr(HasAttr, '_compiled_type')
        assert isinstance(HasAttr._compiled_type, StructType)

    def test_struct_python_types(self):
        @struct
        class PythonTyped:
            speed: float = 0.0
            count: int = 0
            active: bool = False
            name: str = ""

        compiled = PythonTyped.compile()
        assert compiled.members[0].name == "speed"
        assert compiled.members[0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert compiled.members[0].initial_value == "0.0"
        assert compiled.members[1].name == "count"
        assert compiled.members[1].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)
        assert compiled.members[1].initial_value == "0"
        assert compiled.members[2].name == "active"
        assert compiled.members[2].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert compiled.members[2].initial_value == "FALSE"
        assert compiled.members[3].name == "name"
        assert compiled.members[3].data_type == StringTypeRef(wide=False, max_length=255)
        assert compiled.members[3].initial_value == ""


# ---------------------------------------------------------------------------
# @enumeration
# ---------------------------------------------------------------------------

class TestEnum:
    def test_basic_enum(self):
        @enumeration
        class MachineState:
            STOPPED = 0
            RUNNING = 1
            FAULTED = 2

        compiled = MachineState.compile()
        assert isinstance(compiled, EnumType)
        assert compiled.name == "MachineState"
        assert len(compiled.members) == 3

    def test_member_values(self):
        @enumeration
        class State:
            OFF = 0
            ON = 1

        compiled = State.compile()
        assert compiled.members[0].name == "OFF"
        assert compiled.members[0].value == 0
        assert compiled.members[1].name == "ON"
        assert compiled.members[1].value == 1

    def test_base_type(self):
        @enumeration(base_type=DINT)
        class AlarmCode:
            NONE = 0
            OVERHEAT = 100

        compiled = AlarmCode.compile()
        assert compiled.base_type == PrimitiveType.DINT

    def test_no_base_type(self):
        @enumeration
        class Simple:
            A = 0
            B = 1

        compiled = Simple.compile()
        assert compiled.base_type is None

    def test_empty_enum_error(self):
        with pytest.raises(DefinitionError, match="has no members"):
            @enumeration
            class Empty:
                pass

    def test_non_int_member_error(self):
        with pytest.raises(DefinitionError, match="must be an int"):
            @enumeration
            class Bad:
                GOOD = 0
                BAD = "hello"

    def test_enum_marker(self):
        @enumeration
        class Marked:
            A = 0

        assert _is_enumeration(Marked)
        assert not _is_struct(Marked)
        assert _is_data_type(Marked)

    def test_enum_values_dict(self):
        @enumeration
        class Colors:
            RED = 0
            GREEN = 1
            BLUE = 2

        assert Colors._enum_values == {"RED": 0, "GREEN": 1, "BLUE": 2}

    def test_enum_json_roundtrip(self):
        @enumeration
        class RoundTrip:
            X = 10
            Y = 20

        compiled = RoundTrip.compile()
        json_str = compiled.model_dump_json()
        restored = EnumType.model_validate_json(json_str)
        assert restored == compiled

    def test_enum_with_parentheses_no_args(self):
        @enumeration()
        class NoArgs:
            A = 0
            B = 1

        compiled = NoArgs.compile()
        assert compiled.name == "NoArgs"
        assert compiled.base_type is None

    def test_enum_non_contiguous_values(self):
        @enumeration
        class Sparse:
            FIRST = 0
            SECOND = 10
            THIRD = 100

        compiled = Sparse.compile()
        assert compiled.members[0].value == 0
        assert compiled.members[1].value == 10
        assert compiled.members[2].value == 100


# ---------------------------------------------------------------------------
# Data types as type arguments in descriptors
# ---------------------------------------------------------------------------

class TestDataTypeAsTypeArg:
    def test_struct_in_resolve_type_ref(self):
        @struct
        class MyStruct:
            x: INT = 0

        ref = _resolve_type_ref(MyStruct)
        assert isinstance(ref, NamedTypeRef)
        assert ref.name == "MyStruct"

    def test_enum_in_resolve_type_ref(self):
        @enumeration
        class MyEnum:
            A = 0

        ref = _resolve_type_ref(MyEnum)
        assert isinstance(ref, NamedTypeRef)
        assert ref.name == "MyEnum"

    def test_struct_in_static_var(self):
        @struct
        class SensorData:
            value: REAL = 0.0

        @fb
        class UsesStruct:
            data: SensorData

            def logic(self):
                pass

        pou = UsesStruct.compile()
        assert pou.interface.static_vars[0].data_type == NamedTypeRef(name="SensorData")

    def test_enum_in_static_var(self):
        @enumeration
        class Mode:
            AUTO = 0
            MANUAL = 1

        @fb
        class UsesEnum:
            mode: Mode

            def logic(self):
                pass

        pou = UsesEnum.compile()
        assert pou.interface.static_vars[0].data_type == NamedTypeRef(name="Mode")

    def test_struct_in_input_var(self):
        @struct
        class Params:
            speed: REAL = 0.0

        @fb
        class HasInput:
            config: Input[Params]

            def logic(self):
                pass

        pou = HasInput.compile()
        assert pou.interface.input_vars[0].data_type == NamedTypeRef(name="Params")

    def test_struct_in_array(self):
        @struct
        class Point:
            x: REAL = 0.0
            y: REAL = 0.0

        arr_type = ARRAY(Point, 10)
        assert arr_type.element_type == NamedTypeRef(name="Point")


# ---------------------------------------------------------------------------
# Enum literals in logic()
# ---------------------------------------------------------------------------

class TestEnumInLogic:
    def test_enum_attribute_access(self):
        @enumeration
        class Color:
            RED = 0
            GREEN = 1
            BLUE = 2

        @fb
        class UsesColor:
            out: Output[INT]

            def logic(self):
                self.out = Color.GREEN

        pou = UsesColor.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, LiteralExpr)
        assert stmt.value.value == "Color#GREEN"
        assert stmt.value.data_type == NamedTypeRef(name="Color")

    def test_enum_comparison(self):
        @enumeration
        class State:
            OFF = 0
            ON = 1

        @fb
        class Checker:
            state: Input[INT]
            active: Output[BOOL]

            def logic(self):
                if self.state == State.ON:
                    self.active = True

        pou = Checker.compile()
        stmt = pou.networks[0].statements[0]
        # If statement with enum comparison
        cond = stmt.if_branch.condition
        assert isinstance(cond, BinaryExpr)
        assert cond.op == BinaryOp.EQ
        assert isinstance(cond.right, LiteralExpr)
        assert cond.right.value == "State#ON"

    def test_enum_match_case(self):
        @enumeration
        class Phase:
            IDLE = 0
            RUNNING = 1
            DONE = 2

        @fb
        class StateMachine:
            phase: INT = 0
            out: Output[INT]

            def logic(self):
                match self.phase:
                    case Phase.IDLE:
                        self.out = 0
                    case Phase.RUNNING:
                        self.out = 1
                    case Phase.DONE:
                        self.out = 2

        pou = StateMachine.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, CaseStatement)
        assert stmt.branches[0].values == [0]  # Phase.IDLE
        assert stmt.branches[1].values == [1]  # Phase.RUNNING
        assert stmt.branches[2].values == [2]  # Phase.DONE

    def test_enum_match_case_or(self):
        @enumeration
        class Status:
            OK = 0
            WARN = 1
            ERROR = 2

        @fb
        class Handler:
            status: INT = 0
            alarm: Output[BOOL]

            def logic(self):
                match self.status:
                    case Status.WARN | Status.ERROR:
                        self.alarm = True
                    case _:
                        self.alarm = False

        pou = Handler.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, CaseStatement)
        assert stmt.branches[0].values == [1, 2]  # WARN | ERROR

    def test_unknown_enum_member_error(self):
        @enumeration
        class Valid:
            A = 0
            B = 1

        with pytest.raises(CompileError, match="not a member of enum"):
            @fb
            class Bad:
                out: Output[INT]

                def logic(self):
                    self.out = Valid.NONEXISTENT

    def test_unknown_enum_member_in_match(self):
        @enumeration
        class Known:
            X = 0

        with pytest.raises(CompileError, match="not a member of enum"):
            @fb
            class BadMatch:
                val: INT = 0

                def logic(self):
                    match self.val:
                        case Known.MISSING:
                            pass

    def test_enum_in_method(self):
        from plx.framework._decorators import method

        @enumeration
        class Cmd:
            START = 0
            STOP = 1

        @fb
        class WithMethod:
            cmd: INT = 0

            def logic(self):
                pass

            @method
            def set_cmd(self):
                self.cmd = Cmd.START

        pou = WithMethod.compile()
        m = pou.methods[0]
        stmt = m.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, LiteralExpr)
        assert stmt.value.value == "Cmd#START"


# ---------------------------------------------------------------------------
# Project with data types
# ---------------------------------------------------------------------------

class TestProjectWithDataTypes:
    def test_project_with_struct(self):
        @struct
        class ProjStruct:
            val: INT = 0

        @fb
        class ProjFB:
            def logic(self):
                pass

        proj = project("Test", pous=[ProjFB], data_types=[ProjStruct])
        ir = proj.compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "ProjStruct"
        assert ir.data_types[0].kind == "struct"

    def test_project_with_enum(self):
        @enumeration
        class ProjEnum:
            A = 0
            B = 1

        @fb
        class ProjFB2:
            def logic(self):
                pass

        proj = project("Test", pous=[ProjFB2], data_types=[ProjEnum])
        ir = proj.compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "ProjEnum"
        assert ir.data_types[0].kind == "enum"

    def test_project_with_mixed(self):
        @struct
        class MixedStruct:
            x: REAL = 0.0

        @enumeration
        class MixedEnum:
            A = 0

        @fb
        class MixedFB:
            def logic(self):
                pass

        proj = project("Test", pous=[MixedFB], data_types=[MixedStruct, MixedEnum])
        ir = proj.compile()
        assert len(ir.data_types) == 2

    def test_project_non_data_type_error(self):
        class NotDecorated:
            pass

        with pytest.raises(ProjectAssemblyError, match="not a data type"):
            proj = project("Test", data_types=[NotDecorated])
            proj.compile()

    def test_project_no_data_types(self):
        @fb
        class NoDT:
            def logic(self):
                pass

        proj = project("Test", pous=[NoDT])
        ir = proj.compile()
        assert ir.data_types == []


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

class TestIntrospectionHelpers:
    def test_is_struct_on_plain_class(self):
        class Plain:
            pass
        assert not _is_struct(Plain)

    def test_is_enum_on_plain_class(self):
        class Plain:
            pass
        assert not _is_enumeration(Plain)

    def test_is_data_type_on_plain_class(self):
        class Plain:
            pass
        assert not _is_data_type(Plain)

    def test_is_struct_not_on_fb(self):
        @fb
        class SomeFB:
            def logic(self):
                pass
        assert not _is_struct(SomeFB)
        assert not _is_enumeration(SomeFB)


# ---------------------------------------------------------------------------
# folder= kwarg
# ---------------------------------------------------------------------------

class TestDataTypeFolderKwarg:
    def test_struct_folder(self):
        @struct(folder="types/motor")
        class FolderStruct:
            speed: REAL = 0.0
            running: BOOL = False

        assert FolderStruct.compile().folder == "types/motor"

    def test_struct_bare_default_folder(self):
        @struct
        class BareStruct:
            x: INT = 0

        assert BareStruct.compile().folder == ""

    def test_enum_folder(self):
        @enumeration(folder="types/enums")
        class FolderEnum:
            A = 0
            B = 1

        assert FolderEnum.compile().folder == "types/enums"

    def test_enum_bare_default_folder(self):
        @enumeration
        class BareEnum:
            X = 0
            Y = 1

        assert BareEnum.compile().folder == ""

    def test_enum_with_base_type_and_folder(self):
        @enumeration(base_type=DINT, folder="enums")
        class TypedFolderEnum:
            LOW = 0
            HIGH = 100

        compiled = TypedFolderEnum.compile()
        assert compiled.folder == "enums"
        assert compiled.base_type == PrimitiveType.DINT


# ---------------------------------------------------------------------------
# IntEnum support
# ---------------------------------------------------------------------------

class TestIntEnum:
    def test_basic_intenum(self):
        from enum import IntEnum

        class State(IntEnum):
            IDLE = 0
            RUNNING = 1
            DONE = 2

        ref = _resolve_type_ref(State)
        assert isinstance(ref, NamedTypeRef)
        assert ref.name == "State"

    def test_intenum_compiles(self):
        from enum import IntEnum

        class Phase(IntEnum):
            INIT = 0
            RUN = 1
            STOP = 2

        ref = _resolve_type_ref(Phase)
        compiled = Phase.compile()
        assert isinstance(compiled, EnumType)
        assert compiled.name == "Phase"
        assert len(compiled.members) == 3
        assert compiled.members[0].name == "INIT"
        assert compiled.members[0].value == 0

    def test_intenum_in_static_var(self):
        from enum import IntEnum

        class Mode(IntEnum):
            AUTO = 0
            MANUAL = 1

        @fb
        class UsesIntEnum:
            mode: Mode

            def logic(self):
                pass

        pou = UsesIntEnum.compile()
        assert pou.interface.static_vars[0].data_type == NamedTypeRef(name="Mode")

    def test_intenum_literal_in_logic(self):
        from enum import IntEnum

        class Color(IntEnum):
            RED = 0
            GREEN = 1
            BLUE = 2

        @fb
        class UsesIntEnumLiteral:
            out: Output[INT]

            def logic(self):
                self.out = Color.GREEN

        pou = UsesIntEnumLiteral.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, LiteralExpr)
        assert stmt.value.value == "Color#GREEN"

    def test_intenum_match_case(self):
        from enum import IntEnum

        class Step(IntEnum):
            IDLE = 0
            ACTIVE = 1
            DONE = 2

        @fb
        class IntEnumMatch:
            state: INT = 0
            out: Output[INT]

            def logic(self):
                match self.state:
                    case Step.IDLE:
                        self.out = 0
                    case Step.ACTIVE:
                        self.out = 1

        pou = IntEnumMatch.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, CaseStatement)
        assert stmt.branches[0].values == [0]
        assert stmt.branches[1].values == [1]

    def test_intenum_is_enumeration(self):
        from enum import IntEnum

        class TestEnum(IntEnum):
            A = 0
            B = 1

        assert _is_enumeration(TestEnum)
        assert _is_data_type(TestEnum)
        assert not _is_struct(TestEnum)

    def test_intenum_in_project(self):
        from enum import IntEnum

        class ProjectEnum(IntEnum):
            X = 10
            Y = 20

        @fb
        class ProjFB_IE:
            def logic(self):
                pass

        proj = project("IETest", pous=[ProjFB_IE], data_types=[ProjectEnum])
        ir = proj.compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "ProjectEnum"
        assert ir.data_types[0].kind == "enum"

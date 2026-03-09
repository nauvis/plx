"""Tests for @global_vars decorator and Field() metadata."""

import pytest

from plx.framework._data_types import struct, enumeration
from plx.framework._decorators import fb
from plx.framework._errors import DefinitionError, ProjectAssemblyError
from plx.framework._global_vars import global_vars
from plx.framework._descriptors import Field
from plx.framework._project import project
from plx.framework._protocols import CompiledGlobalVarList
from datetime import timedelta
from plx.framework._types import (
    ARRAY,
    BOOL,
    DINT,
    INT,
    REAL,
    STRING,
    TIME,
    POINTER_TO,
)
from plx.model.project import GlobalVariableList
from plx.model.types import (
    ArrayTypeRef,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
)


# ---------------------------------------------------------------------------
# Bare annotation style
# ---------------------------------------------------------------------------

class TestBareAnnotations:
    def test_type_only(self):
        @global_vars
        class Signals:
            motor_on: BOOL
            speed: REAL

        gvl = Signals.compile()
        assert isinstance(gvl, GlobalVariableList)
        assert gvl.name == "Signals"
        assert len(gvl.variables) == 2
        assert gvl.variables[0].name == "motor_on"
        assert gvl.variables[0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert gvl.variables[0].initial_value is None
        assert gvl.variables[1].name == "speed"
        assert gvl.variables[1].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_type_with_default(self):
        @global_vars
        class Defaults:
            enabled: BOOL = True
            max_speed: REAL = 100.0
            count: INT = 42

        gvl = Defaults.compile()
        assert gvl.variables[0].initial_value == "TRUE"
        assert gvl.variables[1].initial_value == "100.0"
        assert gvl.variables[2].initial_value == "42"

    def test_mixed_with_and_without_defaults(self):
        @global_vars
        class Mixed:
            flag: BOOL
            limit: REAL = 50.0

        gvl = Mixed.compile()
        assert gvl.variables[0].initial_value is None
        assert gvl.variables[1].initial_value == "50.0"


# ---------------------------------------------------------------------------
# Field() style
# ---------------------------------------------------------------------------

class TestFieldStyle:
    def test_basic(self):
        @global_vars
        class IO:
            motor: BOOL

        gvl = IO.compile()
        assert len(gvl.variables) == 1
        assert gvl.variables[0].name == "motor"
        assert gvl.variables[0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_initial_value(self):
        @global_vars
        class WithInit:
            speed: REAL = 75.0

        gvl = WithInit.compile()
        assert gvl.variables[0].initial_value == "75.0"

    def test_description(self):
        @global_vars
        class WithDesc:
            temp: REAL = Field(description="Process temperature in C")

        gvl = WithDesc.compile()
        assert gvl.variables[0].description == "Process temperature in C"

    def test_constant(self):
        @global_vars
        class Constants:
            pi: REAL = Field(initial=3.14159, constant=True)

        gvl = Constants.compile()
        assert gvl.variables[0].constant is True

    def test_retain(self):
        @global_vars
        class Retained:
            counter: DINT = Field(retain=True)

        gvl = Retained.compile()
        assert gvl.variables[0].retain is True

    def test_persistent(self):
        @global_vars
        class Persistent:
            recipe_id: DINT = Field(persistent=True)

        gvl = Persistent.compile()
        assert gvl.variables[0].persistent is True

    def test_all_fields(self):
        @global_vars
        class FullSpec:
            valve: BOOL = Field(
                initial=False,
                description="Main valve",
                retain=True,
                persistent=True,
            )

        gvl = FullSpec.compile()
        v = gvl.variables[0]
        assert v.name == "valve"
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert v.initial_value == "FALSE"
        assert v.description == "Main valve"
        assert v.constant is False
        assert v.retain is True
        assert v.persistent is True

    def test_bare_annotation_defaults_no_extra_fields(self):
        """Bare annotations produce variables with default constant/retain/persistent."""
        @global_vars
        class BareOnly:
            flag: BOOL = True

        gvl = BareOnly.compile()
        v = gvl.variables[0]
        assert v.constant is False
        assert v.retain is False
        assert v.persistent is False


# ---------------------------------------------------------------------------
# Hybrid: mix bare annotations and Field() descriptors
# ---------------------------------------------------------------------------

class TestHybridStyle:
    def test_mixed_bare_and_field(self):
        @global_vars
        class Hybrid:
            simple_flag: BOOL = False
            retained_counter: DINT = Field(retain=True, initial=0)

        gvl = Hybrid.compile()
        assert len(gvl.variables) == 2
        # All annotations, so order follows declaration order
        assert gvl.variables[0].name == "simple_flag"
        assert gvl.variables[0].initial_value == "FALSE"
        assert gvl.variables[1].name == "retained_counter"
        assert gvl.variables[1].retain is True


# ---------------------------------------------------------------------------
# @global_vars(description=...) form
# ---------------------------------------------------------------------------

class TestGlobalVarsWithDescription:
    def test_description(self):
        @global_vars(description="System-wide constants")
        class SysConst:
            max_speed: REAL = 1500.0

        gvl = SysConst.compile()
        assert gvl.description == "System-wide constants"

    def test_no_description(self):
        @global_vars
        class NoDes:
            x: INT = 0

        gvl = NoDes.compile()
        assert gvl.description == ""

    def test_empty_parens(self):
        @global_vars()
        class EmptyParens:
            x: BOOL = True

        gvl = EmptyParens.compile()
        assert gvl.name == "EmptyParens"
        assert gvl.description == ""


# ---------------------------------------------------------------------------
# Type constructors
# ---------------------------------------------------------------------------

class TestTypeConstructors:
    def test_array_type(self):
        @global_vars
        class WithArray:
            values: ARRAY(REAL, 10)

        gvl = WithArray.compile()
        assert isinstance(gvl.variables[0].data_type, ArrayTypeRef)

    def test_string_type(self):
        @global_vars
        class WithString:
            name: STRING(80)

        gvl = WithString.compile()
        assert isinstance(gvl.variables[0].data_type, StringTypeRef)

    def test_struct_ref(self):
        @struct
        class MotorData:
            speed: REAL = 0.0

        @global_vars
        class WithStruct:
            motor: MotorData

        gvl = WithStruct.compile()
        assert gvl.variables[0].data_type == NamedTypeRef(name="MotorData")

    def test_enum_ref(self):
        @enumeration
        class MachineMode:
            AUTO = 0
            MANUAL = 1

        @global_vars
        class WithEnum:
            mode: MachineMode

        gvl = WithEnum.compile()
        assert gvl.variables[0].data_type == NamedTypeRef(name="MachineMode")

    def test_pointer_type(self):
        @global_vars
        class WithPtr:
            ptr: POINTER_TO(INT)

        gvl = WithPtr.compile()
        assert gvl.variables[0].data_type.kind == "pointer"

    def test_array_in_descriptor(self):
        @global_vars
        class ArrDesc:
            data: ARRAY(DINT, 5) = "[0,0,0,0,0]"

        gvl = ArrDesc.compile()
        assert isinstance(gvl.variables[0].data_type, ArrayTypeRef)

    def test_time_initial_value(self):
        @global_vars
        class WithTime:
            timeout: TIME = timedelta(seconds=5)

        gvl = WithTime.compile()
        assert gvl.variables[0].initial_value == "T#5s"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_empty_class(self):
        with pytest.raises(DefinitionError, match="has no variables"):
            @global_vars
            class Empty:
                pass

    def test_empty_class_with_description(self):
        with pytest.raises(DefinitionError, match="has no variables"):
            @global_vars(description="nothing here")
            class AlsoEmpty:
                pass

    def test_only_dunder_attrs(self):
        """A class with only dunder attributes should be treated as empty."""
        with pytest.raises(DefinitionError, match="has no variables"):
            @global_vars
            class DunderOnly:
                __doc__ = "some doc"


# ---------------------------------------------------------------------------
# Protocol check
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_isinstance_check(self):
        @global_vars
        class ProtoCheck:
            x: INT = 0

        assert isinstance(ProtoCheck, CompiledGlobalVarList)

    def test_plain_class_not_protocol(self):
        class Plain:
            pass

        assert not isinstance(Plain, CompiledGlobalVarList)

    def test_plx_marker(self):
        @global_vars
        class Marked:
            v: BOOL = True

        assert Marked.__plx_global_vars__ is True


# ---------------------------------------------------------------------------
# compile() returns correct IR
# ---------------------------------------------------------------------------

class TestCompile:
    def test_returns_global_variable_list(self):
        @global_vars
        class GVL:
            a: BOOL = True
            b: INT = 5

        result = GVL.compile()
        assert isinstance(result, GlobalVariableList)

    def test_compiled_gvl_attribute(self):
        @global_vars
        class HasAttr:
            x: REAL = 0.0

        assert hasattr(HasAttr, "_compiled_gvl")
        assert isinstance(HasAttr._compiled_gvl, GlobalVariableList)

    def test_compile_idempotent(self):
        @global_vars
        class Idem:
            x: INT = 0

        first = Idem.compile()
        second = Idem.compile()
        assert first is second

    def test_json_roundtrip(self):
        @global_vars
        class RoundTrip:
            flag: BOOL = True
            count: INT = 10

        compiled = RoundTrip.compile()
        json_str = compiled.model_dump_json()
        restored = GlobalVariableList.model_validate_json(json_str)
        assert restored == compiled


# ---------------------------------------------------------------------------
# Project integration
# ---------------------------------------------------------------------------

class TestProjectIntegration:
    def test_single_gvl(self):
        @global_vars
        class ProjGVL:
            enabled: BOOL = True

        @fb
        class ProjFB:
            def logic(self):
                pass

        proj = project("Test", pous=[ProjFB], global_var_lists=[ProjGVL])
        ir = proj.compile()
        assert len(ir.global_variable_lists) == 1
        assert ir.global_variable_lists[0].name == "ProjGVL"

    def test_multiple_gvls(self):
        @global_vars
        class GVL_A:
            x: INT = 0

        @global_vars
        class GVL_B:
            y: REAL = 1.0

        proj = project("MultiGVL", global_var_lists=[GVL_A, GVL_B])
        ir = proj.compile()
        assert len(ir.global_variable_lists) == 2
        assert ir.global_variable_lists[0].name == "GVL_A"
        assert ir.global_variable_lists[1].name == "GVL_B"

    def test_no_gvls(self):
        @fb
        class NoGVLFB:
            def logic(self):
                pass

        proj = project("NoGVL", pous=[NoGVLFB])
        ir = proj.compile()
        assert ir.global_variable_lists == []

    def test_non_gvl_error(self):
        class NotDecorated:
            pass

        with pytest.raises(ProjectAssemblyError, match="not a global variable list"):
            proj = project("Bad", global_var_lists=[NotDecorated])
            proj.compile()

    def test_gvl_with_data_types_and_pous(self):
        @struct
        class MyStruct:
            val: INT = 0

        @global_vars
        class MyGVL:
            data: MyStruct

        @fb
        class MyFB:
            def logic(self):
                pass

        proj = project(
            "Full",
            pous=[MyFB],
            data_types=[MyStruct],
            global_var_lists=[MyGVL],
        )
        ir = proj.compile()
        assert len(ir.pous) == 1
        assert len(ir.data_types) == 1
        assert len(ir.global_variable_lists) == 1


# ---------------------------------------------------------------------------
# Public API exports
# ---------------------------------------------------------------------------

class TestExports:
    def test_global_vars_importable(self):
        from plx.framework import global_vars as gv
        assert gv is global_vars

    def test_field_importable(self):
        from plx.framework import Field as f
        assert f is Field

    def test_compiled_global_var_list_importable(self):
        from plx.framework import CompiledGlobalVarList as proto
        assert proto is CompiledGlobalVarList


# ---------------------------------------------------------------------------
# folder= kwarg
# ---------------------------------------------------------------------------

class TestGlobalVarsFolderKwarg:
    def test_global_vars_folder(self):
        @global_vars(folder="io/digital")
        class FolderGVL:
            x: BOOL = False

        assert FolderGVL.compile().folder == "io/digital"

    def test_global_vars_bare_default_folder(self):
        @global_vars
        class NoFolderGVL:
            x: BOOL = True

        assert NoFolderGVL.compile().folder == ""

    def test_global_vars_folder_with_description(self):
        @global_vars(description="IO signals", folder="io")
        class DescFolderGVL:
            motor: BOOL

        compiled = DescFolderGVL.compile()
        assert compiled.folder == "io"
        assert compiled.description == "IO signals"


# ---------------------------------------------------------------------------
# scope= kwarg
# ---------------------------------------------------------------------------

class TestGlobalVarsScopeKwarg:
    def test_scope_controller(self):
        @global_vars(scope="controller")
        class ControllerTags:
            speed: REAL = 0.0

        gvl = ControllerTags.compile()
        assert gvl.scope == "controller"

    def test_scope_program(self):
        @global_vars(scope="program")
        class ProgramTags:
            local_flag: BOOL = False

        gvl = ProgramTags.compile()
        assert gvl.scope == "program"

    def test_scope_default_empty(self):
        @global_vars
        class NoScope:
            x: INT = 0

        assert NoScope.compile().scope == ""

    def test_scope_with_folder_and_description(self):
        @global_vars(description="Motor IO", folder="io/motors", scope="controller")
        class MotorIO:
            run: BOOL

        gvl = MotorIO.compile()
        assert gvl.scope == "controller"
        assert gvl.folder == "io/motors"
        assert gvl.description == "Motor IO"

    def test_scope_json_roundtrip(self):
        @global_vars(scope="controller")
        class ScopeRT:
            v: BOOL = True

        compiled = ScopeRT.compile()
        json_str = compiled.model_dump_json()
        restored = GlobalVariableList.model_validate_json(json_str)
        assert restored.scope == "controller"
        assert restored == compiled

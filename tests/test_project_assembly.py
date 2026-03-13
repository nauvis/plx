"""Tests for project assembly: data types, GVLs, transitive deps, auto-compilation."""

from enum import IntEnum

import pytest

from plx.framework._data_types import enumeration, struct
from plx.framework._decorators import fb, function, program
from plx.framework._descriptors import Input, Output, Static, Field
from plx.framework._errors import ProjectAssemblyError
from plx.framework._global_vars import global_vars
from plx.framework._project import PlxProject, project, _resolve_transitive_deps
from plx.framework._task import _format_interval
from datetime import timedelta
from plx.framework._types import ARRAY, BOOL, DINT, INT, REAL, STRING
from plx.model.pou import POUType
from plx.model.project import Project


# ---------------------------------------------------------------------------
# Fixture POUs and types
# ---------------------------------------------------------------------------

@struct
class _MotorData:
    speed: REAL = 0.0
    running: BOOL = False


@enumeration
class _MachineState:
    STOPPED = 0
    RUNNING = 1
    FAULTED = 2


@global_vars
class _SystemIO:
    sensor_1: BOOL
    sensor_2: BOOL


@global_vars(description="Constants", scope="controller")
class _Constants:
    max_speed: REAL = 100.0
    timeout: INT = 500


@fb
class _InnerFB:
    x: Input[BOOL]
    y: Output[BOOL]

    def logic(self):
        self.y = self.x


@fb
class _OuterFB:
    inner: _InnerFB

    def logic(self):
        self.inner(x=True)


@program
class _MainProg:
    running: Input[BOOL]

    def logic(self):
        pass


@function
class _AddOne:
    a: Input[REAL]

    def logic(self) -> REAL:
        return self.a + 1.0


# ---------------------------------------------------------------------------
# Project with data types
# ---------------------------------------------------------------------------

class TestProjectDataTypes:
    def test_compile_with_struct(self):
        ir = project("P", pous=[_MainProg], data_types=[_MotorData]).compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "_MotorData"

    def test_compile_with_enum(self):
        ir = project("P", pous=[_MainProg], data_types=[_MachineState]).compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "_MachineState"

    def test_compile_with_multiple_data_types(self):
        ir = project(
            "P",
            pous=[_MainProg],
            data_types=[_MotorData, _MachineState],
        ).compile()
        assert len(ir.data_types) == 2
        type_names = {dt.name for dt in ir.data_types}
        assert type_names == {"_MotorData", "_MachineState"}

    def test_data_types_in_serialization(self):
        ir = project("P", data_types=[_MotorData]).compile()
        data = ir.model_dump()
        assert len(data["data_types"]) == 1
        assert data["data_types"][0]["name"] == "_MotorData"

    def test_non_data_type_raises(self):
        class NotAType:
            pass

        proj = project("P", data_types=[NotAType])
        with pytest.raises(ProjectAssemblyError, match="not a data type"):
            proj.compile()


# ---------------------------------------------------------------------------
# Project with global variable lists
# ---------------------------------------------------------------------------

class TestProjectGVLs:
    def test_compile_with_gvl(self):
        ir = project("P", global_var_lists=[_SystemIO]).compile()
        assert len(ir.global_variable_lists) == 1
        assert ir.global_variable_lists[0].name == "_SystemIO"

    def test_compile_with_multiple_gvls(self):
        ir = project(
            "P", global_var_lists=[_SystemIO, _Constants]
        ).compile()
        assert len(ir.global_variable_lists) == 2
        gvl_names = {g.name for g in ir.global_variable_lists}
        assert gvl_names == {"_SystemIO", "_Constants"}

    def test_gvl_scope_preserved(self):
        ir = project("P", global_var_lists=[_Constants]).compile()
        assert ir.global_variable_lists[0].scope == "controller"

    def test_gvl_description_preserved(self):
        ir = project("P", global_var_lists=[_Constants]).compile()
        assert ir.global_variable_lists[0].description == "Constants"

    def test_non_gvl_raises(self):
        class NotAGVL:
            pass

        proj = project("P", global_var_lists=[NotAGVL])
        with pytest.raises(ProjectAssemblyError, match="not a global variable list"):
            proj.compile()

    def test_gvl_in_serialization(self):
        ir = project("P", global_var_lists=[_SystemIO]).compile()
        data = ir.model_dump()
        assert len(data["global_variable_lists"]) == 1
        assert data["global_variable_lists"][0]["name"] == "_SystemIO"


# ---------------------------------------------------------------------------
# Full project with all sections
# ---------------------------------------------------------------------------

class TestFullProject:
    def test_all_sections(self):
        from plx.framework._task import task

        ir = project(
            "FullProject",
            pous=[_MainProg, _InnerFB],
            data_types=[_MotorData, _MachineState],
            global_var_lists=[_SystemIO, _Constants],
            tasks=[task("Main", periodic=timedelta(milliseconds=10), pous=[_MainProg])],
        ).compile()

        assert ir.name == "FullProject"
        assert len(ir.pous) >= 2
        assert len(ir.data_types) == 2
        assert len(ir.global_variable_lists) == 2
        assert len(ir.tasks) == 1

    def test_full_project_serializes(self):
        ir = project(
            "P",
            pous=[_MainProg],
            data_types=[_MotorData],
            global_var_lists=[_SystemIO],
        ).compile()
        data = ir.model_dump()
        assert data["name"] == "P"
        assert len(data["pous"]) >= 1
        assert len(data["data_types"]) == 1
        assert len(data["global_variable_lists"]) == 1

    def test_full_project_roundtrips(self):
        ir = project(
            "P",
            pous=[_MainProg],
            data_types=[_MotorData],
            global_var_lists=[_SystemIO],
        ).compile()
        json_str = ir.model_dump_json()
        restored = Project.model_validate_json(json_str)
        assert restored.name == "P"
        assert len(restored.pous) >= 1
        assert len(restored.data_types) == 1
        assert len(restored.global_variable_lists) == 1


# ---------------------------------------------------------------------------
# Transitive dependency resolution
# ---------------------------------------------------------------------------

class TestTransitiveDeps:
    def test_fb_referencing_fb_auto_included(self):
        """OuterFB uses InnerFB — InnerFB should be auto-included."""
        ir = project("P", pous=[_OuterFB]).compile()
        pou_names = {p.name for p in ir.pous}
        assert "_OuterFB" in pou_names
        assert "_InnerFB" in pou_names

    def test_explicit_and_transitive_no_duplicate(self):
        """If InnerFB is explicit and also a transitive dep, no duplicate."""
        ir = project("P", pous=[_OuterFB, _InnerFB]).compile()
        pou_names = [p.name for p in ir.pous]
        assert pou_names.count("_InnerFB") == 1

    def test_struct_type_auto_included(self):
        """FB referencing a struct type should auto-include it."""
        @fb
        class _FBWithStruct:
            data: _MotorData

            def logic(self):
                self.data.speed = 10.0

        ir = project("P", pous=[_FBWithStruct]).compile()
        type_names = {dt.name for dt in ir.data_types}
        assert "_MotorData" in type_names


# ---------------------------------------------------------------------------
# Auto-compilation of IntEnum and dataclass
# ---------------------------------------------------------------------------

class TestAutoCompilation:
    def test_intenum_auto_compiled(self):
        """IntEnum without @enumeration should be auto-compiled."""
        class Color(IntEnum):
            RED = 0
            GREEN = 1
            BLUE = 2

        ir = project("P", data_types=[Color]).compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "Color"

    def test_already_decorated_not_double_compiled(self):
        """@enumeration classes should compile fine without double-compilation."""
        ir = project("P", data_types=[_MachineState]).compile()
        assert len(ir.data_types) == 1
        assert ir.data_types[0].name == "_MachineState"


# ---------------------------------------------------------------------------
# _format_interval
# ---------------------------------------------------------------------------

class TestFormatInterval:
    def test_time_literal(self):
        assert _format_interval(timedelta(milliseconds=100)) == "T#100ms"

    def test_timedelta(self):
        assert _format_interval(timedelta(milliseconds=500)) == "T#500ms"

    def test_string_passthrough(self):
        assert _format_interval("T#2s") == "T#2s"

    def test_invalid_type_raises(self):
        with pytest.raises(ProjectAssemblyError, match="Expected a duration"):
            _format_interval(42)

    def test_invalid_type_none_raises(self):
        """None should not be passed (but _format_interval is only called
        when watchdog is not None, so this tests the guard)."""
        with pytest.raises(ProjectAssemblyError, match="Expected a duration"):
            _format_interval(None)

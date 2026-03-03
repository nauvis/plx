"""Tests for variable descriptors."""

import pytest

from plx.framework._descriptors import (
    VarDescriptor,
    _collect_descriptors,
    _format_initial,
    input_var,
    output_var,
    static_var,
    inout_var,
    temp_var,
    constant_var,
    external_var,
)
from plx.framework._types import T, LT, TimeLiteral
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
)
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# _format_initial
# ---------------------------------------------------------------------------

class TestFormatInitial:
    def test_none(self):
        assert _format_initial(None) is None

    def test_bool_true(self):
        assert _format_initial(True) == "TRUE"

    def test_bool_false(self):
        assert _format_initial(False) == "FALSE"

    def test_int(self):
        assert _format_initial(42) == "42"

    def test_float(self):
        assert _format_initial(3.14) == "3.14"

    def test_time_literal(self):
        assert _format_initial(T(5)) == "T#5s"

    def test_ltime_literal(self):
        assert _format_initial(LT(ms=100)) == "LTIME#100ms"

    def test_string_passthrough(self):
        assert _format_initial("T#10s") == "T#10s"

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="Cannot convert"):
            _format_initial([1, 2, 3])


# ---------------------------------------------------------------------------
# Constructor functions
# ---------------------------------------------------------------------------

class TestInputVar:
    def test_basic(self):
        v = input_var(PrimitiveType.BOOL)
        assert isinstance(v, VarDescriptor)
        assert v.direction == "input"
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert v.initial_value is None
        assert v.description == ""

    def test_with_initial(self):
        v = input_var(PrimitiveType.REAL, initial=0.0)
        assert v.initial_value == "0.0"

    def test_with_description(self):
        v = input_var(PrimitiveType.INT, description="Sensor count")
        assert v.description == "Sensor count"

    def test_string_type(self):
        v = input_var("MyUDT")
        assert v.data_type == NamedTypeRef(name="MyUDT")

    def test_retain(self):
        v = input_var(PrimitiveType.BOOL, retain=True)
        assert v.retain is True

    def test_address(self):
        v = input_var(PrimitiveType.BOOL, address="%I0.0")
        assert v.address == "%I0.0"


class TestPythonBuiltinTypes:
    def test_input_var_python_bool(self):
        v = input_var(bool)
        assert isinstance(v, VarDescriptor)
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_static_var_python_int(self):
        v = static_var(int, initial=0)
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)
        assert v.initial_value == "0"

    def test_output_var_python_float(self):
        v = output_var(float)
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_static_var_python_str(self):
        v = static_var(str)
        assert v.data_type == StringTypeRef(wide=False, max_length=255)


class TestOutputVar:
    def test_basic(self):
        v = output_var(PrimitiveType.BOOL)
        assert v.direction == "output"

    def test_with_initial_bool(self):
        v = output_var(PrimitiveType.BOOL, initial=False)
        assert v.initial_value == "FALSE"

    def test_retain(self):
        v = output_var(PrimitiveType.REAL, retain=True)
        assert v.retain is True

    def test_address(self):
        v = output_var(PrimitiveType.REAL, address="%Q0.0")
        assert v.address == "%Q0.0"


class TestStaticVar:
    def test_basic(self):
        v = static_var(PrimitiveType.DINT)
        assert v.direction == "static"

    def test_with_time_initial(self):
        v = static_var(PrimitiveType.TIME, initial=T(5))
        assert v.initial_value == "T#5s"

    def test_retain(self):
        v = static_var(PrimitiveType.DINT, retain=True)
        assert v.retain is True

    def test_persistent(self):
        v = static_var(PrimitiveType.DINT, persistent=True)
        assert v.persistent is True

    def test_constant(self):
        v = static_var(PrimitiveType.DINT, constant=True)
        assert v.constant is True

    def test_address(self):
        v = static_var(PrimitiveType.DINT, address="%MW100")
        assert v.address == "%MW100"


class TestInoutVar:
    def test_basic(self):
        v = inout_var(PrimitiveType.REAL)
        assert v.direction == "inout"
        assert v.initial_value is None

    def test_with_description(self):
        v = inout_var(PrimitiveType.INT, description="Shared counter")
        assert v.description == "Shared counter"

    def test_rejects_retain(self):
        with pytest.raises(TypeError):
            inout_var(PrimitiveType.BOOL, retain=True)

    def test_rejects_address(self):
        with pytest.raises(TypeError):
            inout_var(PrimitiveType.BOOL, address="%I0.0")


class TestTempVar:
    def test_basic(self):
        v = temp_var(PrimitiveType.INT)
        assert v.direction == "temp"
        assert v.description == ""

    def test_with_initial(self):
        v = temp_var(PrimitiveType.REAL, initial=0.0)
        assert v.initial_value == "0.0"

    def test_rejects_retain(self):
        with pytest.raises(TypeError):
            temp_var(PrimitiveType.BOOL, retain=True)

    def test_rejects_address(self):
        with pytest.raises(TypeError):
            temp_var(PrimitiveType.BOOL, address="%Q0.0")


# ---------------------------------------------------------------------------
# _collect_descriptors
# ---------------------------------------------------------------------------

class TestCollectDescriptors:
    def test_basic_collection(self):
        class MyFB:
            sensor = input_var(PrimitiveType.BOOL)
            valve = output_var(PrimitiveType.BOOL)
            count = static_var(PrimitiveType.DINT, initial=0)

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert len(groups["output"]) == 1
        assert len(groups["static"]) == 1
        assert len(groups["inout"]) == 0
        assert len(groups["temp"]) == 0

    def test_variable_names(self):
        class MyFB:
            sensor = input_var(PrimitiveType.BOOL)

        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].name == "sensor"

    def test_variable_types(self):
        class MyFB:
            speed = input_var(PrimitiveType.REAL)

        groups = _collect_descriptors(MyFB)
        v = groups["input"][0]
        assert isinstance(v, Variable)
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_initial_value_preserved(self):
        class MyFB:
            count = static_var(PrimitiveType.DINT, initial=10)

        groups = _collect_descriptors(MyFB)
        assert groups["static"][0].initial_value == "10"

    def test_description_preserved(self):
        class MyFB:
            temp = input_var(PrimitiveType.REAL, description="Temperature")

        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].description == "Temperature"

    def test_non_descriptors_ignored(self):
        class MyFB:
            sensor = input_var(PrimitiveType.BOOL)
            some_constant = 42
            some_method = lambda self: None

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        total = sum(len(v) for v in groups.values())
        assert total == 1

    def test_empty_class(self):
        class Empty:
            pass

        groups = _collect_descriptors(Empty)
        total = sum(len(v) for v in groups.values())
        assert total == 0

    def test_all_directions(self):
        class AllDirs:
            a = input_var(PrimitiveType.BOOL)
            b = output_var(PrimitiveType.BOOL)
            c = inout_var(PrimitiveType.BOOL)
            d = static_var(PrimitiveType.BOOL)
            e = temp_var(PrimitiveType.BOOL)

        groups = _collect_descriptors(AllDirs)
        assert len(groups["input"]) == 1
        assert len(groups["output"]) == 1
        assert len(groups["inout"]) == 1
        assert len(groups["static"]) == 1
        assert len(groups["temp"]) == 1

    def test_flags_passed_through_to_variable(self):
        class MyFB:
            a = static_var(PrimitiveType.DINT, retain=True, persistent=True,
                           constant=True, address="%MW100")
            b = input_var(PrimitiveType.BOOL, retain=True, address="%I0.0")
            c = output_var(PrimitiveType.REAL, retain=True, address="%Q0.0")

        groups = _collect_descriptors(MyFB)

        static = groups["static"][0]
        assert static.retain is True
        assert static.persistent is True
        assert static.constant is True
        assert static.address == "%MW100"

        inp = groups["input"][0]
        assert inp.retain is True
        assert inp.address == "%I0.0"
        assert inp.persistent is False
        assert inp.constant is False

        out = groups["output"][0]
        assert out.retain is True
        assert out.address == "%Q0.0"
        assert out.persistent is False
        assert out.constant is False

    def test_constant_group(self):
        class MyFB:
            sensor = input_var(PrimitiveType.BOOL)
            MAX_SPEED = constant_var(PrimitiveType.REAL, initial=100.0)

        groups = _collect_descriptors(MyFB)
        assert len(groups["constant"]) == 1
        assert groups["constant"][0].name == "MAX_SPEED"
        assert groups["constant"][0].constant is True

    def test_flags_default_to_false_none(self):
        class MyFB:
            x = static_var(PrimitiveType.INT)

        groups = _collect_descriptors(MyFB)
        v = groups["static"][0]
        assert v.retain is False
        assert v.persistent is False
        assert v.constant is False
        assert v.address is None


# ---------------------------------------------------------------------------
# constant_var
# ---------------------------------------------------------------------------

class TestConstantVar:
    def test_basic(self):
        v = constant_var(PrimitiveType.REAL, initial=3.14)
        assert isinstance(v, VarDescriptor)
        assert v.direction == "constant"
        assert v.constant is True
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_with_initial(self):
        v = constant_var(PrimitiveType.DINT, initial=42)
        assert v.initial_value == "42"

    def test_initial_required(self):
        with pytest.raises(TypeError):
            constant_var(PrimitiveType.INT)

    def test_with_description(self):
        v = constant_var(PrimitiveType.REAL, initial=9.81, description="Gravity")
        assert v.description == "Gravity"

    def test_rejects_retain(self):
        with pytest.raises(TypeError):
            constant_var(PrimitiveType.BOOL, initial=True, retain=True)

    def test_rejects_address(self):
        with pytest.raises(TypeError):
            constant_var(PrimitiveType.INT, initial=0, address="%MW0")


# ---------------------------------------------------------------------------
# constant_var integration with @fb
# ---------------------------------------------------------------------------

class TestConstantVarIntegration:
    def test_fb_with_constant_var(self):
        from plx.framework import fb, REAL, BOOL

        @fb
        class Motor:
            running = input_var(PrimitiveType.BOOL)
            MAX_RPM = constant_var(PrimitiveType.REAL, initial=3600.0)

            def logic(self):
                pass

        pou = Motor.compile()
        assert len(pou.interface.constant_vars) == 1
        cv = pou.interface.constant_vars[0]
        assert cv.name == "MAX_RPM"
        assert cv.constant is True
        assert cv.initial_value == "3600.0"


# ---------------------------------------------------------------------------
# external_var
# ---------------------------------------------------------------------------

class TestExternalVar:
    def test_basic(self):
        v = external_var(PrimitiveType.REAL)
        assert isinstance(v, VarDescriptor)
        assert v.direction == "external"
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert v.initial_value is None
        assert v.description == ""

    def test_with_description(self):
        v = external_var(PrimitiveType.INT, description="Global counter")
        assert v.description == "Global counter"

    def test_string_type(self):
        v = external_var("SystemConfig")
        assert v.data_type == NamedTypeRef(name="SystemConfig")

    def test_collect_descriptors_includes_external(self):
        class MyProg:
            speed = external_var(PrimitiveType.REAL)
            cmd = input_var(PrimitiveType.BOOL)

        groups = _collect_descriptors(MyProg)
        assert len(groups["external"]) == 1
        assert groups["external"][0].name == "speed"
        assert len(groups["input"]) == 1


# ---------------------------------------------------------------------------
# Annotation-based variable declarations
# ---------------------------------------------------------------------------

class TestAnnotationVars:
    def test_input_annotation(self):
        from plx.framework._descriptors import Input

        class MyFB:
            sensor: Input[bool]

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].name == "sensor"
        assert groups["input"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_output_annotation(self):
        from plx.framework._descriptors import Output

        class MyFB:
            valve: Output[float]

        groups = _collect_descriptors(MyFB)
        assert len(groups["output"]) == 1
        assert groups["output"][0].name == "valve"
        assert groups["output"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_inout_annotation(self):
        from plx.framework._descriptors import InOut

        class MyFB:
            ref_speed: InOut[int]

        groups = _collect_descriptors(MyFB)
        assert len(groups["inout"]) == 1
        assert groups["inout"][0].name == "ref_speed"
        assert groups["inout"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_bare_annotation_is_static(self):
        class MyFB:
            count: int = 0

        groups = _collect_descriptors(MyFB)
        assert len(groups["static"]) == 1
        assert groups["static"][0].name == "count"
        assert groups["static"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)
        assert groups["static"][0].initial_value == "0"

    def test_bare_annotation_no_default(self):
        class MyFB:
            flag: bool

        groups = _collect_descriptors(MyFB)
        assert len(groups["static"]) == 1
        assert groups["static"][0].name == "flag"
        assert groups["static"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert groups["static"][0].initial_value is None

    def test_mixed_descriptor_and_annotation(self):
        from plx.framework._descriptors import Input, Output

        class MyFB:
            sensor: Input[bool]
            valve = output_var(PrimitiveType.REAL, description="Main valve")
            count: int = 0

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].name == "sensor"
        assert len(groups["output"]) == 1
        assert groups["output"][0].name == "valve"
        assert groups["output"][0].description == "Main valve"
        assert len(groups["static"]) == 1
        assert groups["static"][0].name == "count"

    def test_annotation_inheritance(self):
        from plx.framework._descriptors import Input

        class Parent:
            speed: Input[float]

        class Child(Parent):
            accel: Input[float]

        groups = _collect_descriptors(Child)
        assert len(groups["input"]) == 2
        names = [v.name for v in groups["input"]]
        assert "speed" in names
        assert "accel" in names

    def test_annotation_override(self):
        from plx.framework._descriptors import Input, Output

        class Parent:
            x: Input[int]

        class Child(Parent):
            x: Output[float]

        groups = _collect_descriptors(Child)
        # x should be output (child overrides parent)
        assert len(groups["input"]) == 0
        assert len(groups["output"]) == 1
        assert groups["output"][0].name == "x"
        assert groups["output"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_input_with_struct_type(self):
        from plx.framework._descriptors import Input
        from plx.framework._data_types import struct
        from plx.framework._types import REAL

        @struct
        class SensorData:
            value: REAL = 0.0

        class MyFB:
            data: Input[SensorData]

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].data_type == NamedTypeRef(name="SensorData")

    def test_input_with_array_type(self):
        from plx.framework._descriptors import Input
        from plx.framework._types import ARRAY

        class MyFB:
            values: Input[ARRAY(int, 10)]

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].data_type.kind == "array"

    def test_descriptor_takes_precedence_over_annotation(self):
        """If a name is both a descriptor and annotated, descriptor wins."""
        from plx.framework._descriptors import Input

        class MyFB:
            sensor = input_var(PrimitiveType.REAL, description="Temp sensor")
            sensor: Input[bool]  # annotation should be ignored

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        # Descriptor version wins
        assert groups["input"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert groups["input"][0].description == "Temp sensor"

"""Tests for variable descriptors (annotation + Field() syntax)."""

import pytest

from plx.framework._descriptors import (
    Input,
    Output,
    InOut,
    Static,
    Temp,
    Constant,
    External,
    Field,
    FieldDescriptor,
    VarDirection,
    _collect_descriptors,
    _determine_direction,
    _format_initial,
    _resolve_declaration,
)
from plx.framework._errors import DeclarationError
from datetime import timedelta
from plx.framework._types import REAL, BOOL, INT, DINT, timedelta_to_iec
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

    def test_timedelta(self):
        assert _format_initial(timedelta(seconds=5)) == "T#5s"

    def test_timedelta_ms(self):
        assert _format_initial(timedelta(milliseconds=100)) == "T#100ms"

    def test_string_passthrough(self):
        assert _format_initial("T#10s") == "T#10s"

    def test_invalid_type_raises(self):
        with pytest.raises(DeclarationError, match="Cannot convert"):
            _format_initial([1, 2, 3])


# ---------------------------------------------------------------------------
# Field() function
# ---------------------------------------------------------------------------

class TestField:
    def test_basic(self):
        f = Field()
        assert isinstance(f, FieldDescriptor)
        assert f.initial_value is None
        assert f.description == ""
        assert f.retain is False
        assert f.persistent is False
        assert f.constant is False

    def test_with_initial(self):
        f = Field(initial=42)
        assert f.initial_value == "42"

    def test_with_initial_bool(self):
        f = Field(initial=True)
        assert f.initial_value == "TRUE"

    def test_with_initial_time(self):
        f = Field(initial=timedelta(seconds=5))
        assert f.initial_value == "T#5s"

    def test_with_description(self):
        f = Field(description="Sensor input")
        assert f.description == "Sensor input"

    def test_with_retain(self):
        f = Field(retain=True)
        assert f.retain is True

    def test_with_persistent(self):
        f = Field(persistent=True)
        assert f.persistent is True

    def test_with_constant(self):
        f = Field(constant=True)
        assert f.constant is True

    def test_all_kwargs(self):
        f = Field(initial=0.0, description="Speed", retain=True,
                  persistent=True)
        assert f.initial_value == "0.0"
        assert f.description == "Speed"
        assert f.retain is True
        assert f.persistent is True

    def test_hardware_input(self):
        f = Field(hardware="input")
        assert f.hardware == "input"

    def test_hardware_output(self):
        f = Field(hardware="output")
        assert f.hardware == "output"

    def test_hardware_memory(self):
        f = Field(hardware="memory")
        assert f.hardware == "memory"

    def test_hardware_none_by_default(self):
        f = Field()
        assert f.hardware is None

    def test_external_true_normalizes_to_readwrite(self):
        f = Field(external=True)
        assert f.external == "readwrite"

    def test_external_read(self):
        f = Field(external="read")
        assert f.external == "read"

    def test_external_readwrite(self):
        f = Field(external="readwrite")
        assert f.external == "readwrite"

    def test_external_false_normalizes_to_none(self):
        f = Field(external=False)
        assert f.external is None

    def test_external_none_by_default(self):
        f = Field()
        assert f.external is None

    def test_external_invalid_raises(self):
        with pytest.raises(DeclarationError, match="Invalid external"):
            Field(external="write")

    def test_hardware_and_external_together(self):
        f = Field(hardware="output", external=True)
        assert f.hardware == "output"
        assert f.external == "readwrite"


# ---------------------------------------------------------------------------
# Annotation wrappers
# ---------------------------------------------------------------------------

class TestAnnotationWrappers:
    def test_input_annotation(self):
        class MyFB:
            sensor: Input[bool]

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].name == "sensor"
        assert groups["input"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_output_annotation(self):
        class MyFB:
            valve: Output[float]

        groups = _collect_descriptors(MyFB)
        assert len(groups["output"]) == 1
        assert groups["output"][0].name == "valve"
        assert groups["output"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_inout_annotation(self):
        class MyFB:
            ref_speed: InOut[int]

        groups = _collect_descriptors(MyFB)
        assert len(groups["inout"]) == 1
        assert groups["inout"][0].name == "ref_speed"
        assert groups["inout"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_static_wrapper(self):
        class MyFB:
            count: Static[int]

        groups = _collect_descriptors(MyFB)
        assert len(groups["static"]) == 1
        assert groups["static"][0].name == "count"
        assert groups["static"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_temp_wrapper(self):
        class MyFB:
            scratch: Temp[int]

        groups = _collect_descriptors(MyFB)
        assert len(groups["temp"]) == 1
        assert groups["temp"][0].name == "scratch"
        assert groups["temp"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_constant_wrapper(self):
        class MyFB:
            PI: Constant[float] = 3.14

        groups = _collect_descriptors(MyFB)
        assert len(groups["constant"]) == 1
        assert groups["constant"][0].name == "PI"
        assert groups["constant"][0].constant is True
        assert groups["constant"][0].initial_value == "3.14"

    def test_external_wrapper(self):
        class MyFB:
            ext: External[int]

        groups = _collect_descriptors(MyFB)
        assert len(groups["external"]) == 1
        assert groups["external"][0].name == "ext"

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


# ---------------------------------------------------------------------------
# Field() with annotation wrappers
# ---------------------------------------------------------------------------

class TestAnnotationWithField:
    def test_input_with_field(self):
        class MyFB:
            sensor: Input[bool] = Field(description="Proximity")

        groups = _collect_descriptors(MyFB)
        v = groups["input"][0]
        assert v.name == "sensor"
        assert v.description == "Proximity"

    def test_output_with_field(self):
        class MyFB:
            speed: Output[float] = Field(initial=60.0, retain=True)

        groups = _collect_descriptors(MyFB)
        v = groups["output"][0]
        assert v.name == "speed"
        assert v.initial_value == "60.0"
        assert v.retain is True

    def test_static_with_field(self):
        class MyFB:
            state: int = Field(retain=True)

        groups = _collect_descriptors(MyFB)
        v = groups["static"][0]
        assert v.name == "state"
        assert v.retain is True

    def test_static_wrapper_with_field(self):
        class MyFB:
            state: Static[int] = Field(retain=True)

        groups = _collect_descriptors(MyFB)
        v = groups["static"][0]
        assert v.name == "state"
        assert v.retain is True

    def test_constant_with_field(self):
        class MyFB:
            PI: Constant[float] = Field(initial=3.14, description="Pi constant")

        groups = _collect_descriptors(MyFB)
        v = groups["constant"][0]
        assert v.name == "PI"
        assert v.constant is True
        assert v.initial_value == "3.14"
        assert v.description == "Pi constant"

    def test_input_with_initial_default(self):
        class MyFB:
            speed: Input[float] = 0.0

        groups = _collect_descriptors(MyFB)
        v = groups["input"][0]
        assert v.initial_value == "0.0"

    def test_output_with_initial_default(self):
        class MyFB:
            valve: Output[bool] = False

        groups = _collect_descriptors(MyFB)
        v = groups["output"][0]
        assert v.initial_value == "FALSE"


# ---------------------------------------------------------------------------
# Field validation per direction
# ---------------------------------------------------------------------------

class TestFieldValidation:
    def test_temp_rejects_retain(self):
        with pytest.raises(DeclarationError, match="retain"):
            class MyFB:
                x: Temp[bool] = Field(retain=True)
            _collect_descriptors(MyFB)

    def test_temp_rejects_description(self):
        with pytest.raises(DeclarationError, match="description"):
            class MyFB:
                x: Temp[bool] = Field(description="nope")
            _collect_descriptors(MyFB)

    def test_inout_rejects_initial(self):
        with pytest.raises(DeclarationError, match="initial"):
            class MyFB:
                x: InOut[bool] = Field(initial=True)
            _collect_descriptors(MyFB)

    def test_inout_rejects_retain(self):
        with pytest.raises(DeclarationError, match="retain"):
            class MyFB:
                x: InOut[bool] = Field(retain=True)
            _collect_descriptors(MyFB)

    def test_external_rejects_initial(self):
        with pytest.raises(DeclarationError, match="initial"):
            class MyFB:
                x: External[int] = Field(initial=0)
            _collect_descriptors(MyFB)

    def test_external_rejects_retain(self):
        with pytest.raises(DeclarationError, match="retain"):
            class MyFB:
                x: External[int] = Field(retain=True)
            _collect_descriptors(MyFB)

    def test_constant_rejects_retain(self):
        with pytest.raises(DeclarationError, match="retain"):
            class MyFB:
                x: Constant[float] = Field(initial=3.14, retain=True)
            _collect_descriptors(MyFB)

    def test_constant_requires_initial(self):
        with pytest.raises(DeclarationError, match="requires an initial"):
            class MyFB:
                x: Constant[int]
            _collect_descriptors(MyFB)

    def test_temp_rejects_hardware(self):
        with pytest.raises(DeclarationError, match="hardware"):
            class MyFB:
                x: Temp[bool] = Field(hardware="input")
            _collect_descriptors(MyFB)

    def test_temp_rejects_external(self):
        with pytest.raises(DeclarationError, match="external"):
            class MyFB:
                x: Temp[bool] = Field(external=True)
            _collect_descriptors(MyFB)

    def test_constant_rejects_hardware(self):
        with pytest.raises(DeclarationError, match="hardware"):
            class MyFB:
                x: Constant[float] = Field(initial=3.14, hardware="input")
            _collect_descriptors(MyFB)

    def test_constant_rejects_external(self):
        with pytest.raises(DeclarationError, match="external"):
            class MyFB:
                x: Constant[float] = Field(initial=3.14, external=True)
            _collect_descriptors(MyFB)

    def test_invalid_hardware_value(self):
        with pytest.raises(DeclarationError, match="Invalid hardware"):
            class MyFB:
                x: Input[bool] = Field(hardware="analog")
            _collect_descriptors(MyFB)

    def test_hardware_on_input_ok(self):
        class MyFB:
            x: Input[bool] = Field(hardware="input")
        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].metadata.get("hardware") == "input"

    def test_hardware_on_output_ok(self):
        class MyFB:
            x: Output[bool] = Field(hardware="output")
        groups = _collect_descriptors(MyFB)
        assert groups["output"][0].metadata.get("hardware") == "output"

    def test_external_on_input_ok(self):
        class MyFB:
            x: Input[bool] = Field(external=True)
        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].metadata.get("external") == "readwrite"

    def test_external_read_on_static(self):
        class MyFB:
            x: bool = Field(external="read")
        groups = _collect_descriptors(MyFB)
        assert groups["static"][0].metadata.get("external") == "read"

    def test_hardware_and_external_metadata(self):
        class MyFB:
            x: Output[bool] = Field(hardware="output", external=True)
        groups = _collect_descriptors(MyFB)
        var = groups["output"][0]
        assert var.metadata.get("hardware") == "output"
        assert var.metadata.get("external") == "readwrite"

    def test_no_hardware_or_external_no_metadata(self):
        class MyFB:
            x: Input[bool]
        groups = _collect_descriptors(MyFB)
        var = groups["input"][0]
        assert "hardware" not in var.metadata
        assert "external" not in var.metadata


# ---------------------------------------------------------------------------
# Python builtin types
# ---------------------------------------------------------------------------

class TestPythonBuiltinTypes:
    def test_input_bool(self):
        class MyFB:
            sensor: Input[bool]
        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_static_int(self):
        class MyFB:
            count: int = 0
        groups = _collect_descriptors(MyFB)
        assert groups["static"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.DINT)
        assert groups["static"][0].initial_value == "0"

    def test_output_float(self):
        class MyFB:
            valve: Output[float]
        groups = _collect_descriptors(MyFB)
        assert groups["output"][0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_static_str(self):
        class MyFB:
            name: str
        groups = _collect_descriptors(MyFB)
        assert groups["static"][0].data_type == StringTypeRef(wide=False, max_length=255)


# ---------------------------------------------------------------------------
# _collect_descriptors
# ---------------------------------------------------------------------------

class TestCollectDescriptors:
    def test_basic_collection(self):
        class MyFB:
            sensor: Input[BOOL]
            valve: Output[BOOL]
            count: DINT = 0

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert len(groups["output"]) == 1
        assert len(groups["static"]) == 1
        assert len(groups["inout"]) == 0
        assert len(groups["temp"]) == 0

    def test_variable_names(self):
        class MyFB:
            sensor: Input[BOOL]

        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].name == "sensor"

    def test_variable_types(self):
        class MyFB:
            speed: Input[REAL]

        groups = _collect_descriptors(MyFB)
        v = groups["input"][0]
        assert isinstance(v, Variable)
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_initial_value_preserved(self):
        class MyFB:
            count: DINT = 10

        groups = _collect_descriptors(MyFB)
        assert groups["static"][0].initial_value == "10"

    def test_description_preserved(self):
        class MyFB:
            temp: Input[REAL] = Field(description="Temperature")

        groups = _collect_descriptors(MyFB)
        assert groups["input"][0].description == "Temperature"

    def test_non_descriptors_ignored(self):
        class MyFB:
            sensor: Input[BOOL]
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
            a: Input[BOOL]
            b: Output[BOOL]
            c: InOut[BOOL]
            d: BOOL
            e: Temp[BOOL]

        groups = _collect_descriptors(AllDirs)
        assert len(groups["input"]) == 1
        assert len(groups["output"]) == 1
        assert len(groups["inout"]) == 1
        assert len(groups["static"]) == 1
        assert len(groups["temp"]) == 1

    def test_flags_passed_through_to_variable(self):
        class MyFB:
            a: DINT = Field(retain=True, persistent=True, constant=True)
            b: Input[BOOL] = Field(retain=True)
            c: Output[REAL] = Field(retain=True)

        groups = _collect_descriptors(MyFB)

        static = groups["static"][0]
        assert static.retain is True
        assert static.persistent is True
        assert static.constant is True

        inp = groups["input"][0]
        assert inp.retain is True
        assert inp.persistent is False
        assert inp.constant is False

        out = groups["output"][0]
        assert out.retain is True
        assert out.persistent is False
        assert out.constant is False

    def test_constant_group(self):
        class MyFB:
            sensor: Input[BOOL]
            MAX_SPEED: Constant[REAL] = 100.0

        groups = _collect_descriptors(MyFB)
        assert len(groups["constant"]) == 1
        assert groups["constant"][0].name == "MAX_SPEED"
        assert groups["constant"][0].constant is True

    def test_flags_default_to_false_none(self):
        class MyFB:
            x: INT

        groups = _collect_descriptors(MyFB)
        v = groups["static"][0]
        assert v.retain is False
        assert v.persistent is False
        assert v.constant is False


# ---------------------------------------------------------------------------
# Constant wrapper integration with @fb
# ---------------------------------------------------------------------------

class TestConstantIntegration:
    def test_fb_with_constant(self):
        from plx.framework import fb

        @fb
        class Motor:
            running: Input[BOOL]
            MAX_RPM: Constant[REAL] = 3600.0

            def logic(self):
                pass

        pou = Motor.compile()
        assert len(pou.interface.constant_vars) == 1
        cv = pou.interface.constant_vars[0]
        assert cv.name == "MAX_RPM"
        assert cv.constant is True
        assert cv.initial_value == "3600.0"


# ---------------------------------------------------------------------------
# External wrapper
# ---------------------------------------------------------------------------

class TestExternalWrapper:
    def test_basic(self):
        class MyFB:
            ext: External[REAL]

        groups = _collect_descriptors(MyFB)
        assert len(groups["external"]) == 1
        v = groups["external"][0]
        assert v.data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert v.initial_value is None

    def test_with_description(self):
        class MyFB:
            ext: External[INT] = Field(description="Global counter")

        groups = _collect_descriptors(MyFB)
        assert groups["external"][0].description == "Global counter"

    def test_string_type(self):
        class MyFB:
            config: External["SystemConfig"]

        groups = _collect_descriptors(MyFB)
        assert groups["external"][0].data_type == NamedTypeRef(name="SystemConfig")

    def test_collect_descriptors_includes_external(self):
        class MyProg:
            speed: External[REAL]
            cmd: Input[BOOL]

        groups = _collect_descriptors(MyProg)
        assert len(groups["external"]) == 1
        assert groups["external"][0].name == "speed"
        assert len(groups["input"]) == 1


# ---------------------------------------------------------------------------
# Annotation inheritance + override
# ---------------------------------------------------------------------------

class TestAnnotationInheritance:
    def test_annotation_inheritance(self):
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


# ---------------------------------------------------------------------------
# Struct/Array type annotations
# ---------------------------------------------------------------------------

class TestStructArrayAnnotations:
    def test_input_with_struct_type(self):
        from plx.framework._data_types import struct

        @struct
        class SensorData:
            value: REAL = 0.0

        class MyFB:
            data: Input[SensorData]

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].data_type == NamedTypeRef(name="SensorData")

    def test_input_with_array_type(self):
        from plx.framework._types import ARRAY

        class MyFB:
            values: Input[ARRAY(int, 10)]

        groups = _collect_descriptors(MyFB)
        assert len(groups["input"]) == 1
        assert groups["input"][0].data_type.kind == "array"


# ---------------------------------------------------------------------------
# _determine_direction
# ---------------------------------------------------------------------------

class TestDetermineDirection:
    def test_input(self):
        d, inner = _determine_direction(Input[int])
        assert d == VarDirection.INPUT
        assert inner is int

    def test_output(self):
        d, inner = _determine_direction(Output[float])
        assert d == VarDirection.OUTPUT
        assert inner is float

    def test_inout(self):
        d, inner = _determine_direction(InOut[bool])
        assert d == VarDirection.INOUT
        assert inner is bool

    def test_static(self):
        d, inner = _determine_direction(Static[int])
        assert d == VarDirection.STATIC
        assert inner is int

    def test_temp(self):
        d, inner = _determine_direction(Temp[int])
        assert d == VarDirection.TEMP
        assert inner is int

    def test_constant(self):
        d, inner = _determine_direction(Constant[float])
        assert d == VarDirection.CONSTANT
        assert inner is float

    def test_external(self):
        d, inner = _determine_direction(External[int])
        assert d == VarDirection.EXTERNAL
        assert inner is int

    def test_bare_type_returns_static(self):
        d, inner = _determine_direction(int)
        assert d == VarDirection.STATIC
        assert inner is int


# ---------------------------------------------------------------------------
# _resolve_declaration
# ---------------------------------------------------------------------------

class TestResolveDeclaration:
    def test_each_wrapper_direction(self):
        for wrapper, expected in [
            (Input[int], VarDirection.INPUT),
            (Output[float], VarDirection.OUTPUT),
            (InOut[bool], VarDirection.INOUT),
            (Static[int], VarDirection.STATIC),
            (Temp[int], VarDirection.TEMP),
            (External[int], VarDirection.EXTERNAL),
        ]:
            desc = _resolve_declaration("x", wrapper, None, type("Dummy", (), {}))
            assert desc is not None
            assert desc.direction == expected

    def test_constant_wrapper_with_initial(self):
        desc = _resolve_declaration("PI", Constant[float], 3.14, type("D", (), {}))
        assert desc is not None
        assert desc.direction == VarDirection.CONSTANT
        assert desc.constant is True
        assert desc.initial_value == "3.14"

    def test_bare_annotation(self):
        desc = _resolve_declaration("count", int, 0, type("D", (), {}))
        assert desc is not None
        assert desc.direction == VarDirection.STATIC
        assert desc.initial_value == "0"

    def test_field_descriptor_default(self):
        field = Field(initial=42, description="The answer")
        desc = _resolve_declaration("x", Input[int], field, type("D", (), {}))
        assert desc is not None
        assert desc.direction == VarDirection.INPUT
        assert desc.initial_value == "42"
        assert desc.description == "The answer"

    def test_annotated_field(self):
        from typing import Annotated
        hint = Annotated[Input[int], Field(description="Sensor")]
        desc = _resolve_declaration("x", hint, None, type("D", (), {}))
        assert desc is not None
        assert desc.direction == VarDirection.INPUT
        assert desc.description == "Sensor"

    def test_non_value_default_returns_none(self):
        desc = _resolve_declaration("x", int, object(), type("D", (), {}))
        assert desc is None

    def test_unresolvable_type_returns_none(self):
        desc = _resolve_declaration("x", Input[object()], None, type("D", (), {}))
        assert desc is None


# ---------------------------------------------------------------------------
# Bug fix: Constant + Field() without initial raises DeclarationError
# ---------------------------------------------------------------------------

class TestConstantFieldBugFix:
    def test_constant_with_field_no_initial_raises_declaration_error(self):
        with pytest.raises(DeclarationError, match="requires an initial"):
            class MyFB:
                x: Constant[int] = Field()
            _collect_descriptors(MyFB)

    def test_constant_with_annotated_field_no_initial_raises_declaration_error(self):
        from typing import Annotated
        with pytest.raises(DeclarationError, match="requires an initial"):
            class MyFB:
                x: Annotated[Constant[int], Field()] = None
            _collect_descriptors(MyFB)

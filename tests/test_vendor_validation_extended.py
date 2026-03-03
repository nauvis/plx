"""Extended vendor validation tests: nested types, interfaces, properties, deep hierarchies."""

import pytest

from plx.framework._compiler_core import CompileError
from plx.framework._decorators import fb, interface, method, program
from plx.framework._descriptors import Input, Output, Static
from plx.framework._project import project
from plx.framework._properties import fb_property
from plx.framework._types import ARRAY, BOOL, DINT, INT, POINTER_TO, REAL, REFERENCE_TO
from plx.framework._vendor import (
    CompileResult,
    PortabilityWarning,
    Vendor,
    VendorValidationError,
    _type_contains,
    validate_target,
)
from plx.model.pou import (
    POU,
    POUInterface,
    POUType,
    AccessSpecifier,
    Method,
    Property,
)
from plx.model.project import Project
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
)
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# _type_contains — recursive type checking
# ---------------------------------------------------------------------------

class TestTypeContains:
    def test_direct_pointer(self):
        t = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.DINT))
        assert _type_contains(t, "pointer") is True

    def test_direct_reference(self):
        t = ReferenceTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert _type_contains(t, "reference") is True

    def test_pointer_in_array(self):
        t = ArrayTypeRef(
            element_type=PointerTypeRef(
                target_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
            ),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _type_contains(t, "pointer") is True

    def test_reference_in_array(self):
        t = ArrayTypeRef(
            element_type=ReferenceTypeRef(
                target_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
            ),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _type_contains(t, "reference") is True

    def test_plain_array(self):
        t = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _type_contains(t, "pointer") is False
        assert _type_contains(t, "reference") is False

    def test_plain_primitive(self):
        t = PrimitiveTypeRef(type=PrimitiveType.BOOL)
        assert _type_contains(t, "pointer") is False
        assert _type_contains(t, "reference") is False

    def test_named_type(self):
        t = NamedTypeRef(name="MyFB")
        assert _type_contains(t, "pointer") is False

    def test_nested_pointer_in_pointer(self):
        """POINTER_TO(POINTER_TO(DINT))"""
        t = PointerTypeRef(
            target_type=PointerTypeRef(
                target_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
            ),
        )
        assert _type_contains(t, "pointer") is True


# ---------------------------------------------------------------------------
# Nested POINTER_TO / REFERENCE_TO rejection
# ---------------------------------------------------------------------------

class TestNestedTypeRejection:
    def test_ab_rejects_pointer_in_array(self):
        """ARRAY OF POINTER_TO should be rejected on AB."""
        @fb
        class FBWithArrayPointer:
            arr: ARRAY(POINTER_TO(DINT), 10)

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="POINTER_TO"):
            project("P", pous=[FBWithArrayPointer]).compile(target=Vendor.AB)

    def test_ab_rejects_reference_in_array(self):
        """ARRAY OF REFERENCE_TO should be rejected on AB."""
        @fb
        class FBWithArrayRef:
            arr: ARRAY(REFERENCE_TO(REAL), 10)

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="REFERENCE_TO"):
            project("P", pous=[FBWithArrayRef]).compile(target=Vendor.AB)

    def test_beckhoff_allows_pointer_in_array(self):
        """ARRAY OF POINTER_TO should pass on Beckhoff."""
        @fb
        class FBWithArrayPointerBk:
            arr: ARRAY(POINTER_TO(DINT), 10)

            def logic(self):
                pass

        result = project("P", pous=[FBWithArrayPointerBk]).compile(
            target=Vendor.BECKHOFF
        )
        assert isinstance(result, CompileResult)


# ---------------------------------------------------------------------------
# Interface rejection on AB / Siemens
# ---------------------------------------------------------------------------

class TestInterfaceRejection:
    def test_ab_rejects_interface_pou(self):
        @interface
        class IDevice:
            @method
            def start(self): ...

        with pytest.raises(VendorValidationError, match="INTERFACE"):
            project("P", pous=[IDevice]).compile(target=Vendor.AB)

    def test_siemens_rejects_interface_pou(self):
        @interface
        class IController:
            @method
            def run(self): ...

        with pytest.raises(VendorValidationError, match="INTERFACE"):
            project("P", pous=[IController]).compile(target=Vendor.SIEMENS)

    def test_ab_rejects_implements(self):
        @interface
        class IRunnable:
            @method
            def run(self): ...

        @fb(implements=[IRunnable])
        class Runner:
            @method
            def run(self):
                pass

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="interface"):
            project("P", pous=[Runner]).compile(target=Vendor.AB)

    def test_beckhoff_allows_interface(self):
        @interface
        class IStartable:
            @method
            def start(self): ...

        result = project("P", pous=[IStartable]).compile(target=Vendor.BECKHOFF)
        assert isinstance(result, CompileResult)


# ---------------------------------------------------------------------------
# Property rejection on AB / Siemens
# ---------------------------------------------------------------------------

class TestPropertyRejection:
    def test_ab_rejects_properties(self):
        @fb
        class FBWithProp:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="properties"):
            project("P", pous=[FBWithProp]).compile(target=Vendor.AB)

    def test_siemens_rejects_properties(self):
        @fb
        class FBWithPropSiemens:
            _temp: REAL

            @fb_property(REAL)
            def temperature(self):
                return self._temp

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="properties"):
            project("P", pous=[FBWithPropSiemens]).compile(target=Vendor.SIEMENS)

    def test_beckhoff_allows_properties(self):
        @fb
        class FBWithPropBk:
            _val: REAL

            @fb_property(REAL)
            def value(self):
                return self._val

            def logic(self):
                pass

        result = project("P", pous=[FBWithPropBk]).compile(target=Vendor.BECKHOFF)
        assert isinstance(result, CompileResult)


# ---------------------------------------------------------------------------
# Multiple errors collected
# ---------------------------------------------------------------------------

class TestMultipleErrors:
    def test_methods_and_properties_both_reported(self):
        @fb
        class ComplexFB:
            _val: REAL

            @method
            def do_thing(self) -> BOOL:
                return True

            @fb_property(REAL)
            def value(self):
                return self._val

            def logic(self):
                pass

        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[ComplexFB]).compile(target=Vendor.AB)
        err = exc_info.value
        assert len(err.errors) == 2  # methods + properties

    def test_interface_and_pointer_both_reported(self):
        @interface
        class ISomething:
            @method
            def do_it(self): ...

        @fb
        class PointerFB:
            ptr: POINTER_TO(DINT)

            def logic(self):
                pass

        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[ISomething, PointerFB]).compile(target=Vendor.AB)
        err = exc_info.value
        assert len(err.errors) >= 2


# ---------------------------------------------------------------------------
# Deep interface hierarchies
# ---------------------------------------------------------------------------

class TestDeepInterfaceHierarchy:
    def test_three_level_interface(self):
        @interface
        class IBase:
            @method
            def base_op(self): ...

        @interface
        class IMid(IBase):
            @method
            def mid_op(self): ...

        @interface
        class ITop(IMid):
            @method
            def top_op(self): ...

        pou = ITop.compile()
        method_names = [m.name for m in pou.methods]
        assert "base_op" in method_names
        assert "mid_op" in method_names
        assert "top_op" in method_names
        assert pou.extends == "IMid"

    def test_interface_with_property(self):
        @interface
        class IMotor:
            @method
            def start(self): ...

            @fb_property(REAL, abstract=True)
            def speed(self): ...

        pou = IMotor.compile()
        assert len(pou.methods) == 1
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "speed"
        assert pou.properties[0].abstract is True

    def test_fb_implements_with_property(self):
        @interface
        class IReadable:
            @fb_property(REAL, abstract=True)
            def value(self): ...

        @fb(implements=[IReadable])
        class Sensor:
            _val: REAL

            @fb_property(REAL)
            def value(self):
                return self._val

            def logic(self):
                pass

        pou = Sensor.compile()
        assert pou.implements == ["IReadable"]
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "value"
        assert pou.properties[0].getter is not None


# ---------------------------------------------------------------------------
# CompileResult behavior
# ---------------------------------------------------------------------------

class TestCompileResultBehavior:
    def test_delegates_data_types(self):
        from plx.framework._data_types import struct

        @struct
        class Pt:
            x: REAL = 0.0

        result = project("P", data_types=[Pt]).compile(target=Vendor.BECKHOFF)
        assert len(result.data_types) == 1

    def test_delegates_global_variable_lists(self):
        from plx.framework._global_vars import global_vars

        @global_vars
        class IO:
            sensor: BOOL

        result = project("P", global_var_lists=[IO]).compile(target=Vendor.BECKHOFF)
        assert len(result.global_variable_lists) == 1

    def test_warnings_list_type(self):
        @fb
        class SimpleFB:
            x: Input[BOOL]

            def logic(self):
                pass

        result = project("P", pous=[SimpleFB]).compile(target=Vendor.BECKHOFF)
        assert isinstance(result.warnings, list)

    def test_compile_result_has_project(self):
        @program
        class Main:
            def logic(self):
                pass

        result = project("P", pous=[Main]).compile(target=Vendor.BECKHOFF)
        assert isinstance(result.project, Project)


# ---------------------------------------------------------------------------
# PortabilityWarning fields
# ---------------------------------------------------------------------------

class TestPortabilityWarningFields:
    def test_warning_has_all_fields(self):
        w = PortabilityWarning(
            category="test",
            pou_name="MyPOU",
            message="something",
            details={"key": "value"},
        )
        assert w.category == "test"
        assert w.pou_name == "MyPOU"
        assert w.message == "something"
        assert w.details == {"key": "value"}

    def test_warning_default_details(self):
        w = PortabilityWarning(
            category="test",
            pou_name="MyPOU",
            message="something",
        )
        assert w.details == {}

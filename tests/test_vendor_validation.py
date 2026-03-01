"""Tests for vendor target validation."""

import pytest

from plx.framework._compiler import CompileError
from plx.framework._data_types import enumeration, struct
from plx.framework._decorators import fb, method, program
from plx.framework._descriptors import input_var, output_var, static_var
from plx.framework._project import project
from plx.framework._types import BOOL, DINT, INT, POINTER_TO, REAL, REFERENCE_TO
from plx.framework._vendor import Vendor, VendorValidationError, validate_target
from plx.model.project import Project


# ---------------------------------------------------------------------------
# Fixtures — simple POUs for testing
# ---------------------------------------------------------------------------

@fb
class _SimpleFB:
    x = input_var(BOOL)
    y = output_var(BOOL)

    def logic(self):
        self.y = self.x


@program
class _SimpleProgram:
    running = input_var(BOOL)

    def logic(self):
        pass


@fb
class _FBWithMethod:
    speed = static_var(REAL)

    def logic(self):
        pass

    @method
    def start(self, target_speed: REAL) -> BOOL:
        self.speed = target_speed
        return True


@fb
class _FBWithPointer:
    ptr = static_var(POINTER_TO(DINT))

    def logic(self):
        pass


@fb
class _FBWithReference:
    ref = static_var(REFERENCE_TO(REAL))

    def logic(self):
        pass


@enumeration
class _TestEnum:
    STOPPED = 0
    RUNNING = 1
    FAULTED = 2


@struct
class _TestStruct:
    speed: REAL = 0.0
    running: BOOL = False


# ---------------------------------------------------------------------------
# Backward compatibility — no target
# ---------------------------------------------------------------------------

class TestNoTarget:
    """compile() with no target must behave exactly as before."""

    def test_compile_no_target(self):
        ir = project("P", pous=[_SimpleFB, _SimpleProgram]).compile()
        assert ir.name == "P"
        assert len(ir.pous) == 2

    def test_compile_with_methods_no_target(self):
        ir = project("P", pous=[_FBWithMethod]).compile()
        assert ir.pous[0].methods[0].name == "start"

    def test_compile_with_enum_no_target(self):
        ir = project("P", pous=[_SimpleFB], data_types=[_TestEnum]).compile()
        assert len(ir.data_types) == 1


# ---------------------------------------------------------------------------
# Beckhoff target — everything passes
# ---------------------------------------------------------------------------

class TestBeckhoff:
    """Beckhoff supports all current IR features."""

    def test_beckhoff_allows_everything(self):
        ir = project(
            "P",
            pous=[_FBWithMethod, _FBWithPointer, _FBWithReference],
            data_types=[_TestEnum],
        ).compile(target=Vendor.BECKHOFF)
        assert len(ir.pous) == 3
        assert len(ir.data_types) == 1


# ---------------------------------------------------------------------------
# AB target — vendor-specific features rejected
# ---------------------------------------------------------------------------

class TestAB:
    def test_ab_allows_simple_project(self):
        ir = project(
            "P",
            pous=[_SimpleFB, _SimpleProgram],
            data_types=[_TestStruct],
        ).compile(target=Vendor.AB)
        assert len(ir.pous) == 2

    def test_ab_allows_enum(self):
        """Enums are universal — raise pass will lower to DINT constants."""
        ir = project("P", pous=[_SimpleFB], data_types=[_TestEnum]).compile(
            target=Vendor.AB,
        )
        assert len(ir.data_types) == 1

    def test_ab_rejects_methods(self):
        with pytest.raises(VendorValidationError, match="methods"):
            project("P", pous=[_FBWithMethod]).compile(target=Vendor.AB)

    def test_ab_rejects_pointer(self):
        with pytest.raises(VendorValidationError, match="POINTER_TO"):
            project("P", pous=[_FBWithPointer]).compile(target=Vendor.AB)

    def test_ab_rejects_reference(self):
        with pytest.raises(VendorValidationError, match="REFERENCE_TO"):
            project("P", pous=[_FBWithReference]).compile(target=Vendor.AB)

    def test_ab_collects_all_errors(self):
        """Multiple issues are reported in a single error."""
        with pytest.raises(VendorValidationError) as exc_info:
            project(
                "P",
                pous=[_FBWithMethod, _FBWithPointer],
                data_types=[_TestEnum],
            ).compile(target=Vendor.AB)
        err = exc_info.value
        assert len(err.errors) == 2  # method + pointer (enum is now universal)


# ---------------------------------------------------------------------------
# Siemens target — same restrictions for now
# ---------------------------------------------------------------------------

class TestSiemens:
    def test_siemens_allows_simple_project(self):
        ir = project(
            "P",
            pous=[_SimpleFB, _SimpleProgram],
            data_types=[_TestStruct],
        ).compile(target=Vendor.SIEMENS)
        assert len(ir.pous) == 2

    def test_siemens_allows_enum(self):
        """Enums are universal — raise pass will lower to DINT constants."""
        ir = project("P", pous=[_SimpleFB], data_types=[_TestEnum]).compile(
            target=Vendor.SIEMENS,
        )
        assert len(ir.data_types) == 1

    def test_siemens_rejects_methods(self):
        with pytest.raises(VendorValidationError, match="methods"):
            project("P", pous=[_FBWithMethod]).compile(target=Vendor.SIEMENS)


# ---------------------------------------------------------------------------
# Abstract / final / struct extends — Beckhoff-only
# ---------------------------------------------------------------------------

class TestAbstractFinal:
    def test_beckhoff_allows_abstract_pou(self):
        from plx.model.pou import POU, POUType, POUInterface
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="AbstractFB",
            abstract=True,
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        validate_target(ir, Vendor.BECKHOFF)  # should not raise

    def test_ab_rejects_abstract_pou(self):
        from plx.model.pou import POU, POUType, POUInterface
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="AbstractFB",
            abstract=True,
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="ABSTRACT"):
            validate_target(ir, Vendor.AB)

    def test_siemens_rejects_abstract_pou(self):
        from plx.model.pou import POU, POUType, POUInterface
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="AbstractFB",
            abstract=True,
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="ABSTRACT"):
            validate_target(ir, Vendor.SIEMENS)

    def test_ab_rejects_abstract_method(self):
        from plx.model.pou import POU, POUType, POUInterface, Method
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            interface=POUInterface(),
            methods=[Method(name="do_thing", abstract=True)],
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="ABSTRACT"):
            validate_target(ir, Vendor.AB)

    def test_ab_rejects_final_method(self):
        from plx.model.pou import POU, POUType, POUInterface, Method
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            interface=POUInterface(),
            methods=[Method(name="do_thing", final=True)],
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="FINAL"):
            validate_target(ir, Vendor.AB)

    def test_ab_rejects_abstract_property(self):
        from plx.model.pou import POU, POUType, POUInterface, Property
        from plx.model.types import PrimitiveTypeRef, PrimitiveType
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            interface=POUInterface(),
            properties=[Property(
                name="speed",
                data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                abstract=True,
            )],
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="ABSTRACT"):
            validate_target(ir, Vendor.AB)

    def test_ab_rejects_final_property(self):
        from plx.model.pou import POU, POUType, POUInterface, Property
        from plx.model.types import PrimitiveTypeRef, PrimitiveType
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            interface=POUInterface(),
            properties=[Property(
                name="speed",
                data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                final=True,
            )],
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="FINAL"):
            validate_target(ir, Vendor.AB)


class TestStructExtends:
    def test_beckhoff_allows_struct_extends(self):
        from plx.model.types import StructType, PrimitiveTypeRef, PrimitiveType
        from plx.model.types import StructMember
        dt = StructType(
            name="Derived",
            extends="Base",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        validate_target(ir, Vendor.BECKHOFF)  # should not raise

    def test_ab_rejects_struct_extends(self):
        from plx.model.types import StructType, PrimitiveTypeRef, PrimitiveType
        from plx.model.types import StructMember
        dt = StructType(
            name="Derived",
            extends="Base",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        with pytest.raises(VendorValidationError, match="struct inheritance"):
            validate_target(ir, Vendor.AB)

    def test_siemens_rejects_struct_extends(self):
        from plx.model.types import StructType, PrimitiveTypeRef, PrimitiveType
        from plx.model.types import StructMember
        dt = StructType(
            name="Derived",
            extends="Base",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        with pytest.raises(VendorValidationError, match="struct inheritance"):
            validate_target(ir, Vendor.SIEMENS)

    def test_struct_without_extends_passes(self):
        from plx.model.types import StructType, PrimitiveTypeRef, PrimitiveType
        from plx.model.types import StructMember
        dt = StructType(
            name="Simple",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        validate_target(ir, Vendor.AB)  # should not raise


# ---------------------------------------------------------------------------
# VendorValidationError is a CompileError
# ---------------------------------------------------------------------------

class TestErrorType:
    def test_is_compile_error(self):
        assert issubclass(VendorValidationError, CompileError)

    def test_error_has_target_and_errors(self):
        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[_FBWithMethod]).compile(target=Vendor.AB)
        err = exc_info.value
        assert err.target == Vendor.AB
        assert isinstance(err.errors, list)
        assert len(err.errors) == 1


# ---------------------------------------------------------------------------
# Vendor enum
# ---------------------------------------------------------------------------

class TestVendorEnum:
    def test_values(self):
        assert Vendor.BECKHOFF == "beckhoff"
        assert Vendor.AB == "ab"
        assert Vendor.SIEMENS == "siemens"

    def test_from_string(self):
        assert Vendor("beckhoff") is Vendor.BECKHOFF
        assert Vendor("ab") is Vendor.AB
        assert Vendor("siemens") is Vendor.SIEMENS

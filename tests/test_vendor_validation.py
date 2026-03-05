"""Tests for vendor target validation."""

import math

import pytest

from plx.framework._compiler import CompileError
from plx.framework._data_types import enumeration, struct
from plx.framework._decorators import fb, method, program
from plx.framework._descriptors import Input, Field, Output, Static, TON, RTO, SR, RS, CTU, CTD
from plx.framework._project import project
from datetime import timedelta
from plx.framework._types import BOOL, DINT, INT, POINTER_TO, REAL, REFERENCE_TO, TIME
from plx.framework._vendor import (
    CompileResult,
    PortabilityWarning,
    Vendor,
    VendorValidationError,
    validate_target,
)
from plx.model.project import Project


# ---------------------------------------------------------------------------
# Fixtures — simple POUs for testing
# ---------------------------------------------------------------------------

@fb
class _SimpleFB:
    x: Input[BOOL]
    y: Output[BOOL]

    def logic(self):
        self.y = self.x


@program
class _SimpleProgram:
    running: Input[BOOL]

    def logic(self):
        pass


@fb
class _FBWithMethod:
    speed: REAL

    def logic(self):
        pass

    @method
    def start(self, target_speed: REAL) -> BOOL:
        self.speed = target_speed
        return True


@fb
class _FBWithPointer:
    ptr: POINTER_TO(DINT)

    def logic(self):
        pass


@fb
class _FBWithReference:
    ref: REFERENCE_TO(REAL)

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


# ---------------------------------------------------------------------------
# Portability warnings
# ---------------------------------------------------------------------------

@fb
class _BaseFB:
    x: Input[BOOL]

    def logic(self):
        pass


@fb
class _DerivedFB(_BaseFB):
    y: Output[BOOL]

    def logic(self):
        self.y = self.x


@fb
class _FBWithRTO:
    timer: RTO

    def logic(self):
        self.timer(IN=self.timer.Q, PT=timedelta(milliseconds=500))


@fb
class _FBWithSR:
    latch: SR

    def logic(self):
        self.latch(SET1=True, RESET=False)


@fb
class _FBWithRS:
    latch: RS

    def logic(self):
        self.latch(SET=True, RESET1=False)


@fb
class _FBWithCTU:
    counter: CTU

    def logic(self):
        self.counter(CU=True, PV=10)


@fb
class _FBWithCTD:
    counter: CTD

    def logic(self):
        self.counter(CD=True, PV=10)


@fb
class _FBWithTON:
    """Uses TON via delayed() — universal, should produce no warnings."""
    timer: TON

    def logic(self):
        self.timer(IN=True, PT=timedelta(milliseconds=100))


class TestPortabilityWarnings:
    """Tests for the portability warning system."""

    # --- Backward compatibility ---

    def test_compile_no_target_returns_project(self):
        """compile() without target returns plain Project, not CompileResult."""
        ir = project("P", pous=[_SimpleFB]).compile()
        assert isinstance(ir, Project)
        assert not isinstance(ir, CompileResult)

    def test_compile_with_target_returns_compile_result(self):
        """compile(target=...) returns CompileResult."""
        result = project("P", pous=[_SimpleFB]).compile(target=Vendor.BECKHOFF)
        assert isinstance(result, CompileResult)
        assert isinstance(result.project, Project)

    # --- CompileResult delegation ---

    def test_compile_result_delegates_name(self):
        result = project("P", pous=[_SimpleFB]).compile(target=Vendor.AB)
        assert result.name == "P"

    def test_compile_result_delegates_pous(self):
        result = project("P", pous=[_SimpleFB]).compile(target=Vendor.AB)
        assert len(result.pous) == 1
        assert result.pous[0].name == "_SimpleFB"

    def test_compile_result_delegates_model_dump(self):
        result = project("P", pous=[_SimpleFB]).compile(target=Vendor.AB)
        d = result.model_dump()
        assert d["name"] == "P"

    def test_compile_result_repr(self):
        result = project("P", pous=[_SimpleFB]).compile(target=Vendor.AB)
        assert "CompileResult" in repr(result)
        assert "'P'" in repr(result)

    # --- No warnings for universal FBs ---

    def test_ton_no_warnings(self):
        """TON is universal — no warnings for any vendor."""
        for vendor in Vendor:
            result = project("P", pous=[_FBWithTON]).compile(target=vendor)
            assert result.warnings == [], f"Unexpected warnings for {vendor}"

    # --- FB translation warnings ---

    def test_rto_warns_for_beckhoff(self):
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.BECKHOFF)
        assert len(result.warnings) == 1
        w = result.warnings[0]
        assert w.category == "fb_translation"
        assert w.pou_name == "_FBWithRTO"
        assert "RTO" in w.message
        assert w.details["fb_type"] == "RTO"

    def test_rto_no_warning_for_ab(self):
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.AB)
        assert result.warnings == []

    def test_rto_no_warning_for_siemens(self):
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.SIEMENS)
        assert result.warnings == []

    def test_sr_warns_for_ab(self):
        result = project("P", pous=[_FBWithSR]).compile(target=Vendor.AB)
        fb_warnings = [w for w in result.warnings if w.category == "fb_translation"]
        assert len(fb_warnings) == 1
        assert fb_warnings[0].details["fb_type"] == "SR"

    def test_sr_warns_for_siemens(self):
        result = project("P", pous=[_FBWithSR]).compile(target=Vendor.SIEMENS)
        fb_warnings = [w for w in result.warnings if w.category == "fb_translation"]
        assert len(fb_warnings) == 1
        assert fb_warnings[0].details["fb_type"] == "SR"

    def test_sr_no_warning_for_beckhoff(self):
        result = project("P", pous=[_FBWithSR]).compile(target=Vendor.BECKHOFF)
        assert result.warnings == []

    def test_rs_warns_for_ab(self):
        result = project("P", pous=[_FBWithRS]).compile(target=Vendor.AB)
        fb_warnings = [w for w in result.warnings if w.category == "fb_translation"]
        assert len(fb_warnings) == 1
        assert fb_warnings[0].details["fb_type"] == "RS"

    def test_ctu_warns_for_ab(self):
        result = project("P", pous=[_FBWithCTU]).compile(target=Vendor.AB)
        fb_warnings = [w for w in result.warnings if w.category == "fb_translation"]
        assert len(fb_warnings) == 1
        assert fb_warnings[0].details["fb_type"] == "CTU"

    def test_ctd_warns_for_siemens(self):
        result = project("P", pous=[_FBWithCTD]).compile(target=Vendor.SIEMENS)
        fb_warnings = [w for w in result.warnings if w.category == "fb_translation"]
        assert len(fb_warnings) == 1
        assert fb_warnings[0].details["fb_type"] == "CTD"

    # --- OOP flattening warnings ---

    def test_extends_warns_for_ab(self):
        result = project("P", pous=[_DerivedFB]).compile(target=Vendor.AB)
        oop_warnings = [w for w in result.warnings if w.category == "oop_flattening"]
        assert len(oop_warnings) == 1
        assert oop_warnings[0].pou_name == "_DerivedFB"
        assert "flattened" in oop_warnings[0].message

    def test_extends_warns_for_siemens(self):
        result = project("P", pous=[_DerivedFB]).compile(target=Vendor.SIEMENS)
        oop_warnings = [w for w in result.warnings if w.category == "oop_flattening"]
        assert len(oop_warnings) == 1

    def test_extends_no_warning_for_beckhoff(self):
        result = project("P", pous=[_DerivedFB]).compile(target=Vendor.BECKHOFF)
        oop_warnings = [w for w in result.warnings if w.category == "oop_flattening"]
        assert len(oop_warnings) == 0

    # --- Hard errors still raise ---

    def test_hard_error_still_raises(self):
        """Methods are a hard error on AB — should still raise, not return warnings."""
        with pytest.raises(VendorValidationError, match="methods"):
            project("P", pous=[_FBWithMethod]).compile(target=Vendor.AB)

    # --- Warnings don't block compilation ---

    def test_warnings_dont_block(self):
        """Projects with warnings still produce valid IR."""
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.BECKHOFF)
        assert len(result.warnings) > 0
        assert result.project.pous[0].name == "_FBWithRTO"

    # --- validate_target returns warnings directly ---

    def test_validate_target_returns_warnings(self):
        from plx.model.pou import POU, POUType, POUInterface
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Child",
            extends="Parent",
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        warnings = validate_target(ir, Vendor.AB)
        assert len(warnings) == 1
        assert warnings[0].category == "oop_flattening"

    def test_validate_target_returns_empty_for_clean_project(self):
        ir = project("P", pous=[_SimpleFB]).compile()
        warnings = validate_target(ir, Vendor.AB)
        assert warnings == []

    # --- Math function portability warnings ---

    def test_exp_warns_for_ab(self):
        @fb
        class _FBWithExp:
            x: Input[REAL]
            y: Output[REAL]

            def logic(self):
                self.y = math.exp(self.x)

        result = project("P", pous=[_FBWithExp]).compile(target=Vendor.AB)
        math_warnings = [w for w in result.warnings if w.category == "math_translation"]
        assert len(math_warnings) == 1
        assert math_warnings[0].details["function"] == "EXP"
        assert "EXPT" in math_warnings[0].message

    def test_exp_no_warning_for_beckhoff(self):
        @fb
        class _FBWithExp2:
            x: Input[REAL]
            y: Output[REAL]

            def logic(self):
                self.y = math.exp(self.x)

        result = project("P", pous=[_FBWithExp2]).compile(target=Vendor.BECKHOFF)
        math_warnings = [w for w in result.warnings if w.category == "math_translation"]
        assert math_warnings == []

    def test_ceil_warns_for_ab(self):
        @fb
        class _FBWithCeil:
            x: Input[REAL]
            y: Output[REAL]

            def logic(self):
                self.y = math.ceil(self.x)

        result = project("P", pous=[_FBWithCeil]).compile(target=Vendor.AB)
        math_warnings = [w for w in result.warnings if w.category == "math_translation"]
        assert len(math_warnings) == 1
        assert math_warnings[0].details["function"] == "CEIL"

    def test_floor_warns_for_ab(self):
        @fb
        class _FBWithFloor:
            x: Input[REAL]
            y: Output[REAL]

            def logic(self):
                self.y = math.floor(self.x)

        result = project("P", pous=[_FBWithFloor]).compile(target=Vendor.AB)
        math_warnings = [w for w in result.warnings if w.category == "math_translation"]
        assert len(math_warnings) == 1
        assert math_warnings[0].details["function"] == "FLOOR"

    def test_sqrt_no_math_warning(self):
        """SQRT is universal — no math_translation warning for any vendor."""
        @fb
        class _FBWithSqrt:
            x: Input[REAL]
            y: Output[REAL]

            def logic(self):
                self.y = math.sqrt(self.x)

        for vendor in Vendor:
            result = project("P", pous=[_FBWithSqrt]).compile(target=vendor)
            math_warnings = [w for w in result.warnings if w.category == "math_translation"]
            assert math_warnings == [], f"Unexpected warning for {vendor}"

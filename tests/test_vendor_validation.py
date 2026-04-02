"""Tests for vendor target validation."""

import math
from datetime import timedelta

import pytest

from plx.framework._compiler import CompileError
from plx.framework._data_types import enumeration, struct
from plx.framework._decorators import fb, fb_method, program
from plx.framework._descriptors import CTD, CTU, RS, RTO, SR, TON, TP, Input, Output, Static, Temp
from plx.framework._library import LibraryFB, LibraryStruct
from plx.framework._project import project
from plx.framework._types import ARRAY, BOOL, BYTE, CHAR, DATE, DINT, POINTER_TO, REAL, REFERENCE_TO, TIME, TOD
from plx.framework._vendor import (
    CompileResult,
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

    @fb_method
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
        from plx.model.pou import POU, POUInterface, POUType

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="AbstractFB",
            abstract=True,
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        validate_target(ir, Vendor.BECKHOFF)  # should not raise

    def test_ab_rejects_abstract_pou(self):
        from plx.model.pou import POU, POUInterface, POUType

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
        from plx.model.pou import POU, POUInterface, POUType

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
        from plx.model.pou import POU, Method, POUInterface, POUType

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
        from plx.model.pou import POU, Method, POUInterface, POUType

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
        from plx.model.pou import POU, POUInterface, POUType, Property
        from plx.model.types import PrimitiveType, PrimitiveTypeRef

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            interface=POUInterface(),
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    abstract=True,
                )
            ],
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="ABSTRACT"):
            validate_target(ir, Vendor.AB)

    def test_ab_rejects_final_property(self):
        from plx.model.pou import POU, POUInterface, POUType, Property
        from plx.model.types import PrimitiveType, PrimitiveTypeRef

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="FB1",
            interface=POUInterface(),
            properties=[
                Property(
                    name="speed",
                    data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
                    final=True,
                )
            ],
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError, match="FINAL"):
            validate_target(ir, Vendor.AB)


class TestStructExtends:
    def test_beckhoff_allows_struct_extends(self):
        from plx.model.types import PrimitiveType, PrimitiveTypeRef, StructMember, StructType

        dt = StructType(
            name="Derived",
            extends="Base",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        validate_target(ir, Vendor.BECKHOFF)  # should not raise

    def test_ab_rejects_struct_extends(self):
        from plx.model.types import PrimitiveType, PrimitiveTypeRef, StructMember, StructType

        dt = StructType(
            name="Derived",
            extends="Base",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        with pytest.raises(VendorValidationError, match="struct inheritance"):
            validate_target(ir, Vendor.AB)

    def test_siemens_rejects_struct_extends(self):
        from plx.model.types import PrimitiveType, PrimitiveTypeRef, StructMember, StructType

        dt = StructType(
            name="Derived",
            extends="Base",
            members=[StructMember(name="x", data_type=PrimitiveTypeRef(type=PrimitiveType.REAL))],
        )
        ir = Project(name="P", data_types=[dt])
        with pytest.raises(VendorValidationError, match="struct inheritance"):
            validate_target(ir, Vendor.SIEMENS)

    def test_struct_without_extends_passes(self):
        from plx.model.types import PrimitiveType, PrimitiveTypeRef, StructMember, StructType

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
        assert w.round_trippable is False

    def test_rto_no_warning_for_ab(self):
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.AB)
        assert result.warnings == []

    def test_rto_warns_for_siemens(self):
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.SIEMENS)
        fb_warnings = [w for w in result.warnings if w.category == "fb_translation"]
        assert len(fb_warnings) == 1
        assert fb_warnings[0].details["fb_type"] == "RTO"
        assert fb_warnings[0].round_trippable is False

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

    def test_extends_blocked_for_ab(self):
        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[_DerivedFB]).compile(target=Vendor.AB)
        assert "extends" in str(exc_info.value).lower()
        assert "round-trip" in str(exc_info.value).lower()

    def test_extends_blocked_for_siemens(self):
        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[_DerivedFB]).compile(target=Vendor.SIEMENS)
        assert "extends" in str(exc_info.value).lower()
        assert "round-trip" in str(exc_info.value).lower()

    def test_extends_allowed_for_beckhoff(self):
        result = project("P", pous=[_DerivedFB]).compile(target=Vendor.BECKHOFF)
        assert result.project.pous[0].name == "_DerivedFB"

    # --- allow_lossy ---

    def test_allow_lossy_permits_extends_ab(self):
        result = project("P", pous=[_DerivedFB]).compile(
            target=Vendor.AB,
            allow_lossy=True,
        )
        lossy = [w for w in result.warnings if w.category == "lossy_transform"]
        assert len(lossy) == 1
        assert not lossy[0].round_trippable
        assert "extends" in lossy[0].message.lower()

    def test_allow_lossy_permits_extends_siemens(self):
        result = project("P", pous=[_DerivedFB]).compile(
            target=Vendor.SIEMENS,
            allow_lossy=True,
        )
        lossy = [w for w in result.warnings if w.category == "lossy_transform"]
        assert len(lossy) == 1
        assert not lossy[0].round_trippable

    def test_allow_lossy_does_not_suppress_hard_errors(self):
        """allow_lossy only affects lossy checks, not structural impossibilities."""
        with pytest.raises(VendorValidationError, match="methods"):
            project("P", pous=[_FBWithMethod]).compile(
                target=Vendor.AB,
                allow_lossy=True,
            )

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
        """validate_target() returns warnings for translatable features."""
        result = project("P", pous=[_FBWithRTO]).compile(target=Vendor.BECKHOFF)
        assert len(result.warnings) > 0
        assert result.warnings[0].category == "fb_translation"

    def test_validate_target_rejects_extends_ab(self):
        from plx.model.pou import POU, POUInterface, POUType

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Child",
            extends="Parent",
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError) as exc_info:
            validate_target(ir, Vendor.AB)
        assert "round-trip" in str(exc_info.value).lower()

    def test_validate_target_rejects_extends_siemens(self):
        from plx.model.pou import POU, POUInterface, POUType

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Child",
            extends="Parent",
            interface=POUInterface(),
        )
        ir = Project(name="P", pous=[pou])
        with pytest.raises(VendorValidationError) as exc_info:
            validate_target(ir, Vendor.SIEMENS)
        assert "round-trip" in str(exc_info.value).lower()

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


# ---------------------------------------------------------------------------
# Library type vendor validation
# ---------------------------------------------------------------------------

# Local stub definitions for testing — these register at class definition time.
# Using unique names to avoid collisions with real vendor stubs.


class _TestABOnlyFB(LibraryFB, vendor="ab", library="test_lib"):
    Enable: Input[BOOL]
    Done: Output[BOOL]


class _TestBeckhoffOnlyFB(LibraryFB, vendor="beckhoff", library="test_lib"):
    Execute: Input[BOOL]
    Busy: Output[BOOL]


class _TestABOnlyStruct(LibraryStruct, vendor="ab", library="test_lib"):
    Status: DINT


class _TestBeckhoffOnlyStruct(LibraryStruct, vendor="beckhoff", library="test_lib"):
    State: DINT


class TestLibraryTypeValidation:
    """Tests for library type vendor compatibility checks in validate_target()."""

    def test_iec_universal_fb_passes_all_targets(self):
        """IEC standard FBs (TON, etc.) have no vendor — pass everywhere."""

        @fb
        class _UsesTon:
            timer: TON

            def logic(self):
                self.timer(IN=True, PT=timedelta(milliseconds=100))

        for vendor in Vendor:
            result = project("P", pous=[_UsesTon]).compile(target=vendor)
            # Should not raise VendorValidationError
            assert result.project.pous[0].name == "_UsesTon"

    def test_ab_fb_passes_on_ab(self):
        """AB-vendor FB compiles fine when target is AB."""

        @fb
        class _UsesPIDE:
            pid: Static[_TestABOnlyFB]

            def logic(self):
                self.pid(Enable=True)

        result = project("P", pous=[_UsesPIDE]).compile(target=Vendor.AB)
        assert result.project.pous[0].name == "_UsesPIDE"

    def test_ab_fb_fails_on_beckhoff(self):
        """AB-vendor FB should fail when compiling for Beckhoff."""

        @fb
        class _UsesPIDE2:
            pid: Static[_TestABOnlyFB]

            def logic(self):
                self.pid(Enable=True)

        with pytest.raises(VendorValidationError, match="_TestABOnlyFB"):
            project("P", pous=[_UsesPIDE2]).compile(target=Vendor.BECKHOFF)

    def test_ab_fb_fails_on_siemens(self):
        """AB-vendor FB should fail when compiling for Siemens."""

        @fb
        class _UsesPIDE3:
            pid: Static[_TestABOnlyFB]

            def logic(self):
                self.pid(Enable=True)

        with pytest.raises(VendorValidationError, match="_TestABOnlyFB"):
            project("P", pous=[_UsesPIDE3]).compile(target=Vendor.SIEMENS)

    def test_beckhoff_fb_fails_on_ab(self):
        """Beckhoff-vendor FB should fail when compiling for AB."""

        @fb
        class _UsesMCPower:
            mc: Static[_TestBeckhoffOnlyFB]

            def logic(self):
                self.mc(Execute=True)

        with pytest.raises(VendorValidationError, match="_TestBeckhoffOnlyFB"):
            project("P", pous=[_UsesMCPower]).compile(target=Vendor.AB)

    def test_beckhoff_fb_passes_on_beckhoff(self):
        """Beckhoff-vendor FB compiles fine when target is Beckhoff."""

        @fb
        class _UsesMCPower2:
            mc: Static[_TestBeckhoffOnlyFB]

            def logic(self):
                self.mc(Execute=True)

        result = project("P", pous=[_UsesMCPower2]).compile(target=Vendor.BECKHOFF)
        assert result.project.pous[0].name == "_UsesMCPower2"

    def test_ab_variable_type_fails_on_beckhoff(self):
        """AB-vendor struct used as a variable type should fail on Beckhoff."""

        @fb
        class _UsesABStruct:
            axis: Static[_TestABOnlyStruct]

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="_TestABOnlyStruct"):
            project("P", pous=[_UsesABStruct]).compile(target=Vendor.BECKHOFF)

    def test_ab_type_inside_array_fails(self):
        """ARRAY(VendorStruct, N) should catch the vendor mismatch recursively."""

        @fb
        class _UsesABArray:
            axes: Static[ARRAY(_TestABOnlyStruct, 4)]

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="_TestABOnlyStruct"):
            project("P", pous=[_UsesABArray]).compile(target=Vendor.BECKHOFF)

    def test_multiple_vendor_mismatches_collected(self):
        """Multiple vendor-mismatched types should all appear in errors."""

        @fb
        class _UsesBothVendors:
            ab_fb: Static[_TestABOnlyFB]
            bk_fb: Static[_TestBeckhoffOnlyFB]

            def logic(self):
                self.ab_fb(Enable=True)
                self.bk_fb(Execute=True)

        # Target AB: Beckhoff FB should fail
        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[_UsesBothVendors]).compile(target=Vendor.AB)
        err = exc_info.value
        error_text = str(err)
        assert "_TestBeckhoffOnlyFB" in error_text
        # AB type should pass on AB, only Beckhoff should error
        assert "_TestABOnlyFB" not in error_text

    def test_error_message_includes_pou_and_type(self):
        """Error message should include POU name, type name, and vendor."""

        @fb
        class _CheckMsg:
            mc: Static[_TestBeckhoffOnlyFB]

            def logic(self):
                self.mc(Execute=True)

        with pytest.raises(VendorValidationError) as exc_info:
            project("P", pous=[_CheckMsg]).compile(target=Vendor.AB)
        err = exc_info.value
        assert len(err.errors) >= 1
        msg = err.errors[0]
        assert "_CheckMsg" in msg
        assert "_TestBeckhoffOnlyFB" in msg
        assert "beckhoff" in msg
        assert "ab" in msg

    def test_no_target_skips_library_check(self):
        """compile() without target should not run library type checks."""

        @fb
        class _MixedNoTarget:
            ab_fb: Static[_TestABOnlyFB]
            bk_fb: Static[_TestBeckhoffOnlyFB]

            def logic(self):
                self.ab_fb(Enable=True)
                self.bk_fb(Execute=True)

        # Should not raise — no vendor target means no validation
        ir = project("P", pous=[_MixedNoTarget]).compile()
        assert isinstance(ir, Project)


# ---------------------------------------------------------------------------
# AB unsupported primitive types
# ---------------------------------------------------------------------------


class TestABUnsupportedPrimitives:
    """AB rejects CHAR, WCHAR, DATE, LDATE, TOD, LTOD, DT, LDT."""

    def test_ab_rejects_char_var(self):
        @fb
        class _FBWithChar:
            c: Input[CHAR]

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="CHAR"):
            project("P", pous=[_FBWithChar]).compile(target=Vendor.AB)

    def test_ab_rejects_date_var(self):
        @fb
        class _FBWithDate:
            d: Static[DATE]

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="DATE"):
            project("P", pous=[_FBWithDate]).compile(target=Vendor.AB)

    def test_ab_rejects_tod_var(self):
        @fb
        class _FBWithTOD:
            t: Output[TOD]

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="TOD"):
            project("P", pous=[_FBWithTOD]).compile(target=Vendor.AB)

    def test_ab_rejects_char_inside_array(self):
        @fb
        class _FBWithCharArray:
            chars: Static[ARRAY(CHAR, 10)]

            def logic(self):
                pass

        with pytest.raises(VendorValidationError, match="CHAR"):
            project("P", pous=[_FBWithCharArray]).compile(target=Vendor.AB)

    def test_ab_rejects_date_in_struct_member(self):
        @struct
        class _StructWithDate:
            timestamp: DATE

        with pytest.raises(VendorValidationError, match="DATE"):
            project("P", pous=[_SimpleFB], data_types=[_StructWithDate]).compile(
                target=Vendor.AB,
            )

    def test_siemens_allows_char(self):
        @fb
        class _FBWithCharSiemens:
            c: Input[CHAR]

            def logic(self):
                pass

        result = project("P", pous=[_FBWithCharSiemens]).compile(target=Vendor.SIEMENS)
        assert result.project.pous[0].name == "_FBWithCharSiemens"

    def test_beckhoff_allows_char(self):
        @fb
        class _FBWithCharBK:
            c: Input[CHAR]

            def logic(self):
                pass

        result = project("P", pous=[_FBWithCharBK]).compile(target=Vendor.BECKHOFF)
        assert result.project.pous[0].name == "_FBWithCharBK"


# ---------------------------------------------------------------------------
# AB TP timer rejection
# ---------------------------------------------------------------------------


class TestABTPTimer:
    """AB rejects TP (pulse timer) — no native equivalent."""

    def test_ab_rejects_tp(self):
        @fb
        class _FBWithTP:
            timer: TP

            def logic(self):
                self.timer(IN=True, PT=timedelta(milliseconds=100))

        with pytest.raises(VendorValidationError, match="TP"):
            project("P", pous=[_FBWithTP]).compile(target=Vendor.AB)

    def test_siemens_allows_tp(self):
        @fb
        class _FBWithTPSiemens:
            timer: TP

            def logic(self):
                self.timer(IN=True, PT=timedelta(milliseconds=100))

        result = project("P", pous=[_FBWithTPSiemens]).compile(target=Vendor.SIEMENS)
        assert result.project.pous[0].name == "_FBWithTPSiemens"

    def test_beckhoff_allows_tp(self):
        @fb
        class _FBWithTPBK:
            timer: TP

            def logic(self):
                self.timer(IN=True, PT=timedelta(milliseconds=100))

        result = project("P", pous=[_FBWithTPBK]).compile(target=Vendor.BECKHOFF)
        assert result.project.pous[0].name == "_FBWithTPBK"


# ---------------------------------------------------------------------------
# AB lossy type mapping warnings
# ---------------------------------------------------------------------------


class TestABLossyTypeMappings:
    """AB warns for BYTE→SINT, WORD→INT, TIME→DINT, etc."""

    def test_ab_warns_for_byte(self):
        @fb
        class _FBWithByte:
            b: Input[BYTE]

            def logic(self):
                pass

        result = project("P", pous=[_FBWithByte]).compile(target=Vendor.AB)
        type_warnings = [w for w in result.warnings if w.category == "type_mapping"]
        assert len(type_warnings) == 1
        assert type_warnings[0].round_trippable is False
        assert type_warnings[0].details["type"] == "BYTE"
        assert type_warnings[0].details["mapped_to"] == "SINT"

    def test_ab_warns_for_time(self):
        @fb
        class _FBWithTime:
            t: Static[TIME]

            def logic(self):
                pass

        result = project("P", pous=[_FBWithTime]).compile(target=Vendor.AB)
        type_warnings = [w for w in result.warnings if w.category == "type_mapping"]
        assert len(type_warnings) == 1
        assert type_warnings[0].round_trippable is False
        assert type_warnings[0].details["type"] == "TIME"
        assert type_warnings[0].details["mapped_to"] == "DINT"

    def test_beckhoff_no_type_mapping_warning(self):
        @fb
        class _FBWithByteBK:
            b: Input[BYTE]

            def logic(self):
                pass

        result = project("P", pous=[_FBWithByteBK]).compile(target=Vendor.BECKHOFF)
        type_warnings = [w for w in result.warnings if w.category == "type_mapping"]
        assert type_warnings == []


# ---------------------------------------------------------------------------
# AB temp var promotion warnings
# ---------------------------------------------------------------------------


class TestABTempVarPromotion:
    """AB warns when POU has temp vars — promoted to static."""

    def test_ab_warns_for_temp_vars(self):
        @fb
        class _FBWithTemp:
            x: Input[BOOL]
            tmp: Temp[DINT]

            def logic(self):
                self.tmp = 42

        result = project("P", pous=[_FBWithTemp]).compile(target=Vendor.AB)
        temp_warnings = [w for w in result.warnings if w.category == "temp_var_promotion"]
        assert len(temp_warnings) == 1
        assert temp_warnings[0].round_trippable is False
        assert "_FBWithTemp" in temp_warnings[0].message
        assert "tmp" in temp_warnings[0].message

    def test_beckhoff_no_temp_var_warning(self):
        @fb
        class _FBWithTempBK:
            x: Input[BOOL]
            tmp: Temp[DINT]

            def logic(self):
                self.tmp = 42

        result = project("P", pous=[_FBWithTempBK]).compile(target=Vendor.BECKHOFF)
        temp_warnings = [w for w in result.warnings if w.category == "temp_var_promotion"]
        assert temp_warnings == []

    def test_siemens_no_temp_var_warning(self):
        @fb
        class _FBWithTempSiemens:
            x: Input[BOOL]
            tmp: Temp[DINT]

            def logic(self):
                self.tmp = 42

        result = project("P", pous=[_FBWithTempSiemens]).compile(target=Vendor.SIEMENS)
        temp_warnings = [w for w in result.warnings if w.category == "temp_var_promotion"]
        assert temp_warnings == []

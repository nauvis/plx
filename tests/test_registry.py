"""Tests for the POU/type registry and transitive dependency resolution."""

import pytest

from plx.framework import (
    BOOL,
    DINT,
    INT,
    REAL,
    fb,
    function,
    Input,
    Output,
    program,
    project,
    struct,
    enumeration,
    Field,
)
from plx.framework._registry import (
    _clear_registries,
    _pou_registry,
    _type_registry,
    lookup_pou,
    lookup_type,
)


# ---------------------------------------------------------------------------
# Registry basics
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_fb_registered(self):
        @fb
        class RegFB1:
            x: Input[BOOL]
            def logic(self):
                pass

        assert lookup_pou("RegFB1") is RegFB1

    def test_program_registered(self):
        @program
        class RegProg1:
            def logic(self):
                pass

        assert lookup_pou("RegProg1") is RegProg1

    def test_function_registered(self):
        @function
        class RegFunc1:
            x: Input[REAL]
            def logic(self) -> REAL:
                return self.x + 1.0

        assert lookup_pou("RegFunc1") is RegFunc1

    def test_struct_registered(self):
        @struct
        class RegStruct1:
            x: REAL = 0.0
            y: INT = 0

        assert lookup_type("RegStruct1") is RegStruct1

    def test_enum_registered(self):
        @enumeration
        class RegEnum1:
            OFF = 0
            ON = 1

        assert lookup_type("RegEnum1") is RegEnum1

    def test_lookup_missing_returns_none(self):
        assert lookup_pou("NoSuchPOU_XYZ") is None
        assert lookup_type("NoSuchType_XYZ") is None


# ---------------------------------------------------------------------------
# Transitive dependency resolution
# ---------------------------------------------------------------------------

class TestTransitiveDeps:
    def test_fb_dep_auto_included(self):
        """If Program uses FB as a static var, FB is auto-included."""
        @fb
        class InnerFB:
            val: Input[BOOL]
            out: Output[BOOL]
            def logic(self):
                self.out = self.val

        @program
        class OuterProg:
            inst: InnerFB
            cmd: Input[BOOL]
            def logic(self):
                self.inst(val=self.cmd)

        # Only pass OuterProg — InnerFB should be auto-included
        proj = project("Test", pous=[OuterProg]).compile()
        pou_names = {p.name for p in proj.pous}
        assert "OuterProg" in pou_names
        assert "InnerFB" in pou_names

    def test_nested_transitive_deps(self):
        """A -> B -> C: passing only A should include B and C."""
        @fb
        class DepC:
            x: Input[BOOL]
            def logic(self):
                pass

        @fb
        class DepB:
            c: DepC
            def logic(self):
                self.c(x=True)

        @program
        class DepA:
            b: DepB
            def logic(self):
                self.b()

        proj = project("Test", pous=[DepA]).compile()
        pou_names = {p.name for p in proj.pous}
        assert "DepA" in pou_names
        assert "DepB" in pou_names
        assert "DepC" in pou_names

    def test_struct_dep_auto_included(self):
        """If a POU uses a struct as a static var, the struct is auto-included."""
        @struct
        class TransMotorData:
            speed: REAL = 0.0
            running: BOOL = False

        @program
        class TransStructProg:
            data: TransMotorData
            def logic(self):
                pass

        proj = project("Test", pous=[TransStructProg]).compile()
        type_names = {t.name for t in proj.data_types}
        assert "TransMotorData" in type_names

    def test_explicit_deps_not_duplicated(self):
        """If a dep is already explicit, it shouldn't appear twice."""
        @fb
        class ExplicitFB:
            x: Input[BOOL]
            def logic(self):
                pass

        @program
        class ExplicitProg:
            inst: ExplicitFB
            def logic(self):
                self.inst(x=True)

        # Pass both explicitly
        proj = project("Test", pous=[ExplicitProg, ExplicitFB]).compile()
        pou_names = [p.name for p in proj.pous]
        assert pou_names.count("ExplicitFB") == 1

    def test_iec_standard_types_skipped(self):
        """IEC types like TON are not in the registry — resolution skips them."""
        from plx.framework import delayed

        @program
        class TimerProg:
            cmd: Input[BOOL]
            out: Output[BOOL]
            def logic(self):
                self.out = delayed(self.cmd, seconds=5)

        # TON is generated as a NamedTypeRef but shouldn't cause errors
        proj = project("Test", pous=[TimerProg]).compile()
        pou_names = {p.name for p in proj.pous}
        assert "TimerProg" in pou_names
        # TON should NOT appear as a POU
        assert "TON" not in pou_names

    def test_fb_inheritance_parent_included(self):
        """If DerivedFB extends BaseFB, BaseFB should be auto-included."""
        @fb
        class TransBaseFB:
            x: Input[BOOL]
            def logic(self):
                pass

        @fb
        class TransDerivedFB(TransBaseFB):
            y: Output[BOOL]
            def logic(self):
                super().logic()
                self.y = self.x

        proj = project("Test", pous=[TransDerivedFB]).compile()
        pou_names = {p.name for p in proj.pous}
        assert "TransDerivedFB" in pou_names
        assert "TransBaseFB" in pou_names

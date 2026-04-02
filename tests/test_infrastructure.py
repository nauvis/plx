"""Tests for infrastructure changes: registry scoping, iteration guard,
sentinel registry, and vendor extensibility."""

import warnings
from datetime import timedelta

import pytest

from plx.framework import (
    BOOL,
    Input,
    Output,
    Vendor,
    delayed,
    fb,
    program,
    project,
)
from plx.framework._compiler_core import SENTINEL_REGISTRY
from plx.framework._project import (
    _MAX_DEP_ITERATIONS,
    _collect_type_ref_names,
)
from plx.framework._registry import (
    _restore_registries,
    _snapshot_registries,
    lookup_pou,
    register_pou,
    register_type,
)
from plx.framework._vendor import (
    PortabilityWarning,
    _clear_vendor_extensions,
    register_fb_translation_warning,
    register_vendor_check,
    register_vendor_warning,
)
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
)

# ===================================================================
# Change 1: Registry scoping
# ===================================================================


class TestRegistryCollisionWarning:
    def test_pou_collision_warns(self):
        """Registering two different classes with the same name warns."""
        FakeA = type("Collision", (), {})
        FakeB = type("Collision", (), {})

        register_pou(FakeA)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            register_pou(FakeB)

        assert len(w) == 1
        assert "POU registry: 'Collision' already registered" in str(w[0].message)

    def test_type_collision_warns(self):
        """Registering two different type classes with the same name warns."""
        TypeA = type("TypeCollision", (), {})
        TypeB = type("TypeCollision", (), {})

        register_type(TypeA)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            register_type(TypeB)

        assert len(w) == 1
        assert "Type registry: 'TypeCollision' already registered" in str(w[0].message)

    def test_same_class_no_warning(self):
        """Re-registering the same class object does not warn."""
        SameFB = type("SameFB", (), {})

        register_pou(SameFB)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            register_pou(SameFB)

        assert len(w) == 0


class TestRegistrySnapshotRestore:
    def test_roundtrip(self):
        """Snapshot/restore preserves registry state."""
        # Take a snapshot of the current state
        snapshot = _snapshot_registries()

        # Add something new
        class TempFB:
            __name__ = "TempFB"

        register_pou(TempFB)
        assert lookup_pou("TempFB") is TempFB

        # Restore
        _restore_registries(snapshot)
        assert lookup_pou("TempFB") is None

    def test_snapshot_is_independent_copy(self):
        """Modifying the snapshot dict doesn't affect registries."""
        snapshot = _snapshot_registries()
        snapshot[0]["injected"] = object  # mutate the snapshot copy
        assert lookup_pou("injected") is None  # registry untouched


class TestRegistryIsolationFixture:
    """Verify the autouse fixture works — additions in one test don't leak."""

    def test_add_to_registry(self):
        @fb
        class IsolationTestFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert lookup_pou("IsolationTestFB") is IsolationTestFB

    def test_previous_addition_gone(self):
        """IsolationTestFB from test_add_to_registry should be gone."""
        assert lookup_pou("IsolationTestFB") is None


# ===================================================================
# Change 2: Iteration guard + PointerTypeRef/ReferenceTypeRef
# ===================================================================


class TestIterationGuard:
    def test_constant_exists(self):
        assert _MAX_DEP_ITERATIONS == 10_000

    def test_normal_project_resolves(self):
        """Normal projects resolve without hitting the guard."""

        @fb
        class GuardInnerFB:
            x: Input[BOOL]

            def logic(self):
                pass

        @program
        class GuardProg:
            inst: GuardInnerFB

            def logic(self):
                self.inst(x=True)

        proj = project("Test", pous=[GuardProg]).compile()
        pou_names = {p.name for p in proj.pous}
        assert "GuardInnerFB" in pou_names


class TestCollectTypeRefNames:
    def test_named_type_ref(self):
        names: set[str] = set()
        _collect_type_ref_names(NamedTypeRef(name="MyStruct"), names)
        assert names == {"MyStruct"}

    def test_array_of_named(self):
        names: set[str] = set()
        ref = ArrayTypeRef(
            element_type=NamedTypeRef(name="MyStruct"),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        _collect_type_ref_names(ref, names)
        assert names == {"MyStruct"}

    def test_pointer_to_named(self):
        names: set[str] = set()
        ref = PointerTypeRef(target_type=NamedTypeRef(name="PointedStruct"))
        _collect_type_ref_names(ref, names)
        assert names == {"PointedStruct"}

    def test_reference_to_named(self):
        names: set[str] = set()
        ref = ReferenceTypeRef(target_type=NamedTypeRef(name="RefStruct"))
        _collect_type_ref_names(ref, names)
        assert names == {"RefStruct"}

    def test_pointer_to_primitive_no_names(self):
        names: set[str] = set()
        ref = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.DINT))
        _collect_type_ref_names(ref, names)
        assert names == set()

    def test_array_of_pointer_to_named(self):
        """Nested: ARRAY OF POINTER_TO MyStruct."""
        names: set[str] = set()
        ref = ArrayTypeRef(
            element_type=PointerTypeRef(target_type=NamedTypeRef(name="DeepStruct")),
            dimensions=[DimensionRange(lower=0, upper=4)],
        )
        _collect_type_ref_names(ref, names)
        assert names == {"DeepStruct"}


# ===================================================================
# Change 3: Sentinel registry
# ===================================================================


class TestSentinelRegistry:
    def test_all_sentinels_present(self):
        """All 12 sentinel functions are in the registry."""
        expected = {
            "delayed",
            "sustained",
            "pulse",
            "retentive",
            "rising",
            "falling",
            "count_up",
            "count_down",
            "count_up_down",
            "set_dominant",
            "reset_dominant",
            "first_scan",
        }
        assert set(SENTINEL_REGISTRY.keys()) == expected

    def test_sentinel_def_is_frozen(self):
        """SentinelDef instances are immutable."""
        sd = SENTINEL_REGISTRY["delayed"]
        with pytest.raises(AttributeError):
            sd.name = "changed"

    def test_timer_sentinels_match(self):
        for name, (fb_type, in_name, pt_name) in [
            ("delayed", ("TON", "IN", "PT")),
            ("sustained", ("TOF", "IN", "PT")),
            ("pulse", ("TP", "IN", "PT")),
            ("retentive", ("RTO", "IN", "PT")),
        ]:
            sd = SENTINEL_REGISTRY[name]
            assert sd.category == "timer"
            assert sd.fb_type == fb_type
            assert sd.params["signal"] == in_name
            assert sd.params["duration"] == pt_name

    def test_edge_sentinels_match(self):
        for name, fb_type in [("rising", "R_TRIG"), ("falling", "F_TRIG")]:
            sd = SENTINEL_REGISTRY[name]
            assert sd.category == "edge"
            assert sd.fb_type == fb_type
            assert sd.params["signal"] == "CLK"

    def test_counter_sentinels_match(self):
        sd = SENTINEL_REGISTRY["count_up"]
        assert sd.category == "counter"
        assert sd.fb_type == "CTU"
        assert sd.params["signal"] == "CU"
        assert sd.params["preset"] == "PV"
        assert sd.params["control"] == "RESET"

        sd = SENTINEL_REGISTRY["count_down"]
        assert sd.category == "counter"
        assert sd.fb_type == "CTD"
        assert sd.params["signal"] == "CD"
        assert sd.params["preset"] == "PV"
        assert sd.params["control"] == "LOAD"

    def test_bistable_sentinels_match(self):
        sd = SENTINEL_REGISTRY["set_dominant"]
        assert sd.category == "bistable"
        assert sd.fb_type == "SR"
        assert sd.params["set"] == "SET1"
        assert sd.params["reset"] == "RESET"

        sd = SENTINEL_REGISTRY["reset_dominant"]
        assert sd.category == "bistable"
        assert sd.fb_type == "RS"
        assert sd.params["set"] == "SET"
        assert sd.params["reset"] == "RESET1"

    def test_system_flag_sentinels_match(self):
        from plx.model.expressions import SystemFlag

        sd = SENTINEL_REGISTRY["first_scan"]
        assert sd.category == "system_flag"
        assert sd.fb_type == ""
        assert sd.system_flag == SystemFlag.FIRST_SCAN

    def test_sentinel_dispatch_still_works(self):
        """Existing sentinel compilation still works through new dispatch."""

        @program
        class SentinelDispatchProg:
            cmd: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                self.out = delayed(self.cmd, timedelta(seconds=5))

        pou = SentinelDispatchProg.compile()
        # Should have generated a TON static var
        static_names = [v.name for v in pou.interface.static_vars]
        assert any("ton" in n for n in static_names)


# ===================================================================
# Change 4: Vendor check extensibility
# ===================================================================


class TestVendorCheckExtensibility:
    def setup_method(self):
        _clear_vendor_extensions()

    def teardown_method(self):
        _clear_vendor_extensions()

    def test_register_vendor_check(self):
        """A registered check fires during validate_target."""
        fired = []

        def my_check(project, target, errors):
            fired.append(True)
            errors.append("custom check failed")

        register_vendor_check(my_check)

        @program
        class CheckProg:
            def logic(self):
                pass

        with pytest.raises(Exception) as exc_info:
            project("Test", pous=[CheckProg]).compile(target=Vendor.AB)

        assert fired
        assert "custom check failed" in str(exc_info.value)

    def test_register_vendor_warning(self):
        """A registered warning function adds warnings to CompileResult."""

        def my_warning(proj, target, warns):
            warns.append(
                PortabilityWarning(
                    category="custom",
                    pou_name="TestPOU",
                    message="custom warning",
                )
            )

        register_vendor_warning(my_warning)

        @program
        class WarnProg:
            def logic(self):
                pass

        result = project("Test", pous=[WarnProg]).compile(target=Vendor.AB)
        custom = [w for w in result.warnings if w.category == "custom"]
        assert len(custom) == 1
        assert custom[0].message == "custom warning"

    def test_register_fb_translation_warning(self):
        """A registered FB translation warning appears for matching FBs."""
        register_fb_translation_warning("TON", Vendor.AB, "TON needs special handling on AB")

        @program
        class FBWarnProg:
            cmd: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                self.out = delayed(self.cmd, timedelta(seconds=1))

        result = project("Test", pous=[FBWarnProg]).compile(target=Vendor.AB)
        ton_warnings = [
            w for w in result.warnings if w.category == "fb_translation" and w.details.get("fb_type") == "TON"
        ]
        assert len(ton_warnings) == 1
        assert "special handling" in ton_warnings[0].message

    def test_clear_vendor_extensions(self):
        """_clear_vendor_extensions removes registered extensions."""
        register_vendor_check(lambda p, t, e: None)
        register_vendor_warning(lambda p, t, w: None)
        register_fb_translation_warning("FAKE_FB", Vendor.AB, "test")

        _clear_vendor_extensions()

        # After clearing, the custom entries should be gone
        # We verify indirectly by compiling without errors
        @program
        class ClearProg:
            def logic(self):
                pass

        result = project("Test", pous=[ClearProg]).compile(target=Vendor.AB)
        assert not any(w.details.get("fb_type") == "FAKE_FB" for w in result.warnings)

    def test_builtin_checks_survive_clear(self):
        """Built-in checks (methods, properties, etc.) survive _clear_vendor_extensions."""
        from plx.framework._vendor import _BUILTIN_CHECK_COUNT, _CHECKS

        register_vendor_check(lambda p, t, e: None)
        _clear_vendor_extensions()

        assert len(_CHECKS) == _BUILTIN_CHECK_COUNT

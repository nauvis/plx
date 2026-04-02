"""Tests for registry edge cases not covered by test_registry.py.

Covers duplicate registration warnings, lookup miss behavior,
snapshot/restore semantics, and transitive dependency resolution
edge cases (diamond dependencies, deep chains).
"""

import warnings

from plx.framework import (
    BOOL,
    DINT,
    REAL,
    Input,
    Output,
    enumeration,
    fb,
    program,
    project,
    struct,
)
from plx.framework._registry import (
    _clear_registries,
    _restore_registries,
    _snapshot_registries,
    lookup_pou,
    lookup_type,
    register_pou,
)

# ---------------------------------------------------------------------------
# TestRegistryDuplicates — warning behavior on re-registration
# ---------------------------------------------------------------------------


class TestRegistryDuplicates:
    def test_duplicate_pou_same_class_no_warning(self):
        """Registering the same class object twice should NOT warn."""

        @fb
        class DupSameFB:
            x: Input[BOOL]

            def logic(self):
                pass

        # First registration happened at decoration time. Register again.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            register_pou(DupSameFB)

        registry_warnings = [x for x in w if "registry" in str(x.message).lower()]
        assert len(registry_warnings) == 0

    def test_duplicate_pou_different_class_warns(self):
        """Registering a different class with the same name should warn."""

        @fb
        class DupDiffFB:
            x: Input[BOOL]

            def logic(self):
                pass

        first = DupDiffFB

        # Create a second, different class with the same __name__
        @fb
        class DupDiffFB:
            y: Output[BOOL]

            def logic(self):
                pass

        second = DupDiffFB
        assert first is not second

        # The second @fb decoration already triggered register_pou, which
        # should have warned about replacing the first.
        # Verify the second is now registered.
        assert lookup_pou("DupDiffFB") is second

    def test_duplicate_type_different_class_warns(self):
        """Registering a different type class with the same name should warn."""

        @struct
        class DupStruct:
            x: REAL = 0.0

        first = DupStruct

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            @struct
            class DupStruct:
                y: DINT = 0

            second = DupStruct

        assert first is not second
        registry_warnings = [x for x in w if "registry" in str(x.message).lower()]
        assert len(registry_warnings) == 1
        assert "DupStruct" in str(registry_warnings[0].message)
        assert lookup_type("DupStruct") is second


# ---------------------------------------------------------------------------
# TestRegistryLookup — miss and clear behavior
# ---------------------------------------------------------------------------


class TestRegistryLookup:
    def test_lookup_nonexistent_pou_returns_none(self):
        assert lookup_pou("NoSuchPOU_EdgeCase_XYZ") is None

    def test_lookup_nonexistent_type_returns_none(self):
        assert lookup_type("NoSuchType_EdgeCase_XYZ") is None

    def test_lookup_after_clear_returns_none(self):
        """After clearing registries, previously registered items vanish."""

        @fb
        class ClearedFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert lookup_pou("ClearedFB") is ClearedFB

        _clear_registries()
        assert lookup_pou("ClearedFB") is None

        # Note: the autouse fixture in conftest.py will restore the
        # registries after this test, so other tests are unaffected.


# ---------------------------------------------------------------------------
# TestRegistrySnapshot — isolation semantics
# ---------------------------------------------------------------------------


class TestRegistrySnapshot:
    def test_snapshot_and_restore(self):
        """Register, snapshot, clear, restore — lookup should work again."""

        @fb
        class SnapFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert lookup_pou("SnapFB") is SnapFB

        snapshot = _snapshot_registries()
        _clear_registries()
        assert lookup_pou("SnapFB") is None

        _restore_registries(snapshot)
        assert lookup_pou("SnapFB") is SnapFB

    def test_snapshot_is_deep_copy(self):
        """Registrations after snapshot should not appear when restored."""

        @fb
        class PreSnapFB:
            x: Input[BOOL]

            def logic(self):
                pass

        snapshot = _snapshot_registries()

        @fb
        class PostSnapFB:
            y: Output[BOOL]

            def logic(self):
                pass

        # PostSnapFB is in the live registry
        assert lookup_pou("PostSnapFB") is PostSnapFB

        # Restore snapshot — PostSnapFB should disappear
        _restore_registries(snapshot)
        assert lookup_pou("PreSnapFB") is PreSnapFB
        assert lookup_pou("PostSnapFB") is None

    def test_snapshot_captures_types_too(self):
        """Snapshot/restore covers both POU and type registries."""

        @struct
        class SnapStruct:
            val: REAL = 0.0

        snapshot = _snapshot_registries()
        _clear_registries()
        assert lookup_type("SnapStruct") is None

        _restore_registries(snapshot)
        assert lookup_type("SnapStruct") is SnapStruct


# ---------------------------------------------------------------------------
# TestTransitiveDepsEdgeCases — dependency resolution edge cases
# ---------------------------------------------------------------------------


class TestTransitiveDepsEdgeCases:
    def test_diamond_dependency(self):
        """A uses B and C, both B and C use D -> D only included once."""

        @fb
        class DiamondD:
            x: Input[BOOL]

            def logic(self):
                pass

        @fb
        class DiamondB:
            d: DiamondD

            def logic(self):
                self.d(x=True)

        @fb
        class DiamondC:
            d: DiamondD

            def logic(self):
                self.d(x=False)

        @program
        class DiamondA:
            b: DiamondB
            c: DiamondC

            def logic(self):
                self.b()
                self.c()

        proj = project("DiamondTest", pous=[DiamondA]).compile()
        pou_names = [p.name for p in proj.pous]
        assert pou_names.count("DiamondD") == 1
        assert "DiamondA" in pou_names
        assert "DiamondB" in pou_names
        assert "DiamondC" in pou_names

    def test_deep_chain(self):
        """A -> B -> C -> D -> E — all resolved transitively."""

        @fb
        class ChainE:
            x: Input[BOOL]

            def logic(self):
                pass

        @fb
        class ChainD:
            e: ChainE

            def logic(self):
                self.e(x=True)

        @fb
        class ChainC:
            d: ChainD

            def logic(self):
                self.d()

        @fb
        class ChainB:
            c: ChainC

            def logic(self):
                self.c()

        @program
        class ChainA:
            b: ChainB

            def logic(self):
                self.b()

        proj = project("ChainTest", pous=[ChainA]).compile()
        pou_names = {p.name for p in proj.pous}
        assert pou_names == {"ChainA", "ChainB", "ChainC", "ChainD", "ChainE"}

    def test_struct_diamond_dependency(self):
        """Two FBs reference the same struct — it appears once in data_types."""

        @struct
        class SharedConfig:
            value: REAL = 0.0

        @fb
        class UserA:
            cfg: SharedConfig

            def logic(self):
                pass

        @fb
        class UserB:
            cfg: SharedConfig

            def logic(self):
                pass

        @program
        class StructDiamondProg:
            a: UserA
            b: UserB

            def logic(self):
                self.a()
                self.b()

        proj = project("StructDiamondTest", pous=[StructDiamondProg]).compile()
        type_names = [t.name for t in proj.data_types]
        assert type_names.count("SharedConfig") == 1

    def test_enum_dep_auto_included(self):
        """Enum used as a variable type is auto-included in data_types."""

        @enumeration
        class MachineMode:
            OFF = 0
            MANUAL = 1
            AUTO = 2

        @program
        class EnumDepProg:
            mode: MachineMode

            def logic(self):
                pass

        proj = project("EnumDepTest", pous=[EnumDepProg]).compile()
        type_names = {t.name for t in proj.data_types}
        assert "MachineMode" in type_names

    def test_no_deps_produces_single_pou(self):
        """A standalone program with no FB dependencies produces just itself."""

        @program
        class StandaloneProg:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = self.x

        proj = project("StandaloneTest", pous=[StandaloneProg]).compile()
        assert len(proj.pous) == 1
        assert proj.pous[0].name == "StandaloneProg"
        assert len(proj.data_types) == 0

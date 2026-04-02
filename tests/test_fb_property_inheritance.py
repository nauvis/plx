"""Tests for property inheritance across FB hierarchies.

Covers MRO-based property collection via ``_collect_properties``, including
single inheritance, multi-level chains, property overrides, and mixed
property/logic inheritance.
"""

from plx.framework import BOOL, DINT, REAL, fb, fb_property
from plx.model.pou import AccessSpecifier

# ---------------------------------------------------------------------------
# TestPropertyInheritance — basic MRO property propagation
# ---------------------------------------------------------------------------


class TestPropertyInheritance:
    def test_child_inherits_parent_property(self):
        """A child FB with no properties of its own should inherit the parent's."""

        @fb
        class PropParent1:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        @fb
        class PropChild1(PropParent1):
            def logic(self):
                super().logic()

        pou = PropChild1.compile()
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "speed"
        assert prop.data_type.type.value == "REAL"
        assert prop.getter is not None

    def test_child_overrides_parent_property(self):
        """Child replaces parent getter with different logic."""

        @fb
        class PropParent2:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        @fb
        class PropChild2(PropParent2):
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed + 1.0

            def logic(self):
                super().logic()

        pou = PropChild2.compile()
        # Should still be exactly one property (overridden, not duplicated)
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "speed"
        assert prop.getter is not None

    def test_child_adds_setter_to_inherited_property(self):
        """Parent has getter-only property; child redefines with getter + setter."""

        @fb
        class PropParent3:
            _level: REAL

            @fb_property(REAL)
            def level(self):
                return self._level

            def logic(self):
                pass

        @fb
        class PropChild3(PropParent3):
            _level: REAL

            @fb_property(REAL)
            def level(self):
                return self._level

            @level.setter
            def level(self, value: REAL):
                self._level = value

            def logic(self):
                super().logic()

        pou = PropChild3.compile()
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "level"
        assert prop.getter is not None
        assert prop.setter is not None

    def test_multi_level_inheritance(self):
        """Grandparent -> Parent -> Child: property flows through the chain."""

        @fb
        class PropGrandparent:
            _temp: REAL

            @fb_property(REAL)
            def temperature(self):
                return self._temp

            def logic(self):
                pass

        @fb
        class PropMiddle(PropGrandparent):
            def logic(self):
                super().logic()

        @fb
        class PropGrandchild(PropMiddle):
            def logic(self):
                super().logic()

        pou = PropGrandchild.compile()
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "temperature"
        assert prop.getter is not None


# ---------------------------------------------------------------------------
# TestPropertyOnDerivedFB — property + logic interaction
# ---------------------------------------------------------------------------


class TestPropertyOnDerivedFB:
    def test_property_alongside_inherited_logic(self):
        """Child has its own property AND overrides logic() with super()."""

        @fb
        class PropBaseLogic:
            _running: BOOL

            def logic(self):
                self._running = True

        @fb
        class PropDerivedWithProp(PropBaseLogic):
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                super().logic()

        pou = PropDerivedWithProp.compile()
        # Property comes from child
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "speed"
        # Logic body should contain statements (from super() + child)
        assert len(pou.networks) > 0

    def test_multiple_properties_with_inheritance(self):
        """Parent has prop1; child adds prop2. Both should appear."""

        @fb
        class PropParentMulti:
            _pressure: REAL

            @fb_property(REAL)
            def pressure(self):
                return self._pressure

            def logic(self):
                pass

        @fb
        class PropChildMulti(PropParentMulti):
            _flow: REAL

            @fb_property(REAL)
            def flow(self):
                return self._flow

            def logic(self):
                super().logic()

        pou = PropChildMulti.compile()
        names = [p.name for p in pou.properties]
        assert "pressure" in names
        assert "flow" in names
        assert len(pou.properties) == 2

    def test_override_preserves_sibling_properties(self):
        """Parent has prop_a and prop_b. Child overrides prop_a only.

        Both properties should appear, with prop_a from child and prop_b
        from parent.
        """

        @fb
        class PropParentTwo:
            _a: DINT
            _b: REAL

            @fb_property(DINT)
            def prop_a(self):
                return self._a

            @fb_property(REAL)
            def prop_b(self):
                return self._b

            def logic(self):
                pass

        @fb
        class PropChildOverrideOne(PropParentTwo):
            _a: DINT

            @fb_property(DINT)
            def prop_a(self):
                return self._a + 1

            def logic(self):
                super().logic()

        pou = PropChildOverrideOne.compile()
        assert len(pou.properties) == 2
        names = [p.name for p in pou.properties]
        assert "prop_a" in names
        assert "prop_b" in names

    def test_abstract_property_inherited_and_implemented(self):
        """Parent has abstract property; child provides concrete implementation."""

        @fb
        class PropAbstractBase:
            @fb_property(REAL, abstract=True)
            def value(self):
                return 0.0

            def logic(self):
                pass

        @fb
        class PropConcreteChild(PropAbstractBase):
            _val: REAL

            @fb_property(REAL)
            def value(self):
                return self._val

            def logic(self):
                super().logic()

        pou = PropConcreteChild.compile()
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "value"
        # Child's version is concrete — getter should be compiled
        assert prop.abstract is False
        assert prop.getter is not None

    def test_access_specifier_inherited(self):
        """Property access specifier propagates through inheritance."""

        @fb
        class PropProtectedBase:
            _data: DINT

            @fb_property(DINT, access=AccessSpecifier.PROTECTED)
            def data(self):
                return self._data

            def logic(self):
                pass

        @fb
        class PropProtectedChild(PropProtectedBase):
            def logic(self):
                super().logic()

        pou = PropProtectedChild.compile()
        assert len(pou.properties) == 1
        assert pou.properties[0].access == AccessSpecifier.PROTECTED

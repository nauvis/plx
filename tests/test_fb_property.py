"""Tests for @fb_property decorator on function blocks."""

import pytest

from plx.framework._compiler_core import CompileError
from plx.framework._decorators import fb, method
from plx.framework._descriptors import Input, Field, Output
from plx.framework._properties import PropDescriptor, fb_property
from plx.framework._types import BOOL, INT, REAL
from plx.model.pou import AccessSpecifier, POUType


# ---------------------------------------------------------------------------
# Getter-only property
# ---------------------------------------------------------------------------

class TestGetterOnly:
    def test_getter_only_compiles(self):
        @fb
        class Motor:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        pou = Motor.compile()
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "speed"
        assert prop.data_type.type.value == "REAL"
        assert prop.getter is not None
        assert prop.setter is None

    def test_getter_has_network(self):
        @fb
        class Widget:
            _val: INT

            @fb_property(INT)
            def val(self):
                return self._val

            def logic(self):
                pass

        prop = Widget.compile().properties[0]
        assert len(prop.getter.networks) == 1
        assert len(prop.getter.networks[0].statements) > 0


# ---------------------------------------------------------------------------
# Getter + setter
# ---------------------------------------------------------------------------

class TestGetterSetter:
    def test_getter_and_setter(self):
        @fb
        class Tank:
            _level: REAL

            @fb_property(REAL)
            def level(self):
                return self._level

            @level.setter
            def level(self, value: REAL):
                self._level = value

            def logic(self):
                pass

        pou = Tank.compile()
        prop = pou.properties[0]
        assert prop.name == "level"
        assert prop.getter is not None
        assert prop.setter is not None
        assert len(prop.setter.networks) == 1

    def test_setter_chaining_returns_descriptor(self):
        """The .setter decorator should return the same PropDescriptor."""
        @fb_property(REAL)
        def speed(self):
            return self._speed

        assert isinstance(speed, PropDescriptor)

        @speed.setter
        def speed(self, value: REAL):
            self._speed = value

        # After .setter(), it's still a PropDescriptor
        assert isinstance(speed, PropDescriptor)


# ---------------------------------------------------------------------------
# Access specifiers
# ---------------------------------------------------------------------------

class TestAccess:
    def test_default_access_is_public(self):
        @fb
        class Pump:
            _flow: REAL

            @fb_property(REAL)
            def flow(self):
                return self._flow

            def logic(self):
                pass

        prop = Pump.compile().properties[0]
        assert prop.access == AccessSpecifier.PUBLIC

    def test_private_access(self):
        @fb
        class Valve:
            _pos: REAL

            @fb_property(REAL, access=AccessSpecifier.PRIVATE)
            def position(self):
                return self._pos

            def logic(self):
                pass

        prop = Valve.compile().properties[0]
        assert prop.access == AccessSpecifier.PRIVATE

    def test_protected_access(self):
        @fb
        class Sensor:
            _raw: INT

            @fb_property(INT, access=AccessSpecifier.PROTECTED)
            def raw_value(self):
                return self._raw

            def logic(self):
                pass

        prop = Sensor.compile().properties[0]
        assert prop.access == AccessSpecifier.PROTECTED


# ---------------------------------------------------------------------------
# Abstract / final
# ---------------------------------------------------------------------------

class TestAbstractFinal:
    def test_abstract_property(self):
        @fb
        class Base:
            @fb_property(REAL, abstract=True)
            def speed(self):
                return 0.0

            def logic(self):
                pass

        prop = Base.compile().properties[0]
        assert prop.abstract is True
        # Abstract properties should NOT have compiled getter/setter
        assert prop.getter is None

    def test_final_property(self):
        @fb
        class Sealed:
            _val: REAL

            @fb_property(REAL, final=True)
            def value(self):
                return self._val

            def logic(self):
                pass

        prop = Sealed.compile().properties[0]
        assert prop.final is True
        # Final properties should still have a compiled getter
        assert prop.getter is not None


# ---------------------------------------------------------------------------
# Multiple properties on one FB
# ---------------------------------------------------------------------------

class TestMultipleProperties:
    def test_two_properties(self):
        @fb
        class Drive:
            _speed: REAL
            _torque: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            @speed.setter
            def speed(self, value: REAL):
                self._speed = value

            @fb_property(REAL)
            def torque(self):
                return self._torque

            def logic(self):
                pass

        pou = Drive.compile()
        assert len(pou.properties) == 2
        names = [p.name for p in pou.properties]
        assert "speed" in names
        assert "torque" in names


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_fb_property_requires_type(self):
        with pytest.raises(CompileError, match="requires a type argument"):
            @fb_property
            def bad(self):
                pass


# ---------------------------------------------------------------------------
# ST export
# ---------------------------------------------------------------------------

class TestPropertySTExport:
    def test_getter_only_st(self):
        from plx.export.st import to_structured_text

        @fb
        class Motor:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        pou = Motor.compile()
        st = to_structured_text(pou)
        assert "PROPERTY speed : REAL" in st
        assert "GET" in st
        assert "END_GET" in st
        assert "END_PROPERTY" in st

    def test_getter_setter_st(self):
        from plx.export.st import to_structured_text

        @fb
        class Tank:
            _level: REAL

            @fb_property(REAL)
            def level(self):
                return self._level

            @level.setter
            def level(self, value: REAL):
                self._level = value

            def logic(self):
                pass

        pou = Tank.compile()
        st = to_structured_text(pou)
        assert "PROPERTY level : REAL" in st
        assert "GET" in st
        assert "END_GET" in st
        assert "SET" in st
        assert "END_SET" in st
        assert "END_PROPERTY" in st

    def test_private_property_st(self):
        from plx.export.st import to_structured_text

        @fb
        class Valve:
            _pos: REAL

            @fb_property(REAL, access=AccessSpecifier.PRIVATE)
            def position(self):
                return self._pos

            def logic(self):
                pass

        pou = Valve.compile()
        st = to_structured_text(pou)
        assert "PROPERTY PRIVATE position : REAL" in st


# ---------------------------------------------------------------------------
# Native @property support
# ---------------------------------------------------------------------------

class TestNativeProperty:
    def test_getter_only(self):
        @fb
        class Motor:
            _speed: REAL

            @property
            def speed(self) -> REAL:
                return self._speed

            def logic(self):
                pass

        pou = Motor.compile()
        assert len(pou.properties) == 1
        prop = pou.properties[0]
        assert prop.name == "speed"
        assert prop.data_type.type.value == "REAL"
        assert prop.getter is not None
        assert prop.setter is None

    def test_getter_and_setter(self):
        @fb
        class Tank:
            _level: REAL

            @property
            def level(self) -> REAL:
                return self._level

            @level.setter
            def level(self, value: REAL):
                self._level = value

            def logic(self):
                pass

        pou = Tank.compile()
        prop = pou.properties[0]
        assert prop.name == "level"
        assert prop.getter is not None
        assert prop.setter is not None

    def test_default_access_is_public(self):
        @fb
        class Pump:
            _flow: REAL

            @property
            def flow(self) -> REAL:
                return self._flow

            def logic(self):
                pass

        prop = Pump.compile().properties[0]
        assert prop.access == AccessSpecifier.PUBLIC

    def test_int_return_type(self):
        @fb
        class Counter:
            _count: INT

            @property
            def count(self) -> INT:
                return self._count

            def logic(self):
                pass

        prop = Counter.compile().properties[0]
        assert prop.data_type.type.value == "INT"

    def test_bool_return_type(self):
        @fb
        class Sensor:
            _active: BOOL

            @property
            def active(self) -> BOOL:
                return self._active

            def logic(self):
                pass

        prop = Sensor.compile().properties[0]
        assert prop.data_type.type.value == "BOOL"

    def test_no_return_annotation_skipped(self):
        """@property without -> TYPE annotation is not compiled as IEC PROPERTY."""
        @fb
        class Widget:
            _x: REAL

            @property
            def x(self):
                return self._x

            def logic(self):
                pass

        pou = Widget.compile()
        assert len(pou.properties) == 0

    def test_multiple_properties(self):
        @fb
        class Drive:
            _speed: REAL
            _torque: REAL

            @property
            def speed(self) -> REAL:
                return self._speed

            @property
            def torque(self) -> REAL:
                return self._torque

            def logic(self):
                pass

        pou = Drive.compile()
        assert len(pou.properties) == 2
        names = [p.name for p in pou.properties]
        assert "speed" in names
        assert "torque" in names

    def test_st_export(self):
        from plx.export.st import to_structured_text

        @fb
        class Motor:
            _speed: REAL

            @property
            def speed(self) -> REAL:
                return self._speed

            @speed.setter
            def speed(self, value: REAL):
                self._speed = value

            def logic(self):
                pass

        pou = Motor.compile()
        st = to_structured_text(pou)
        assert "PROPERTY speed : REAL" in st
        assert "GET" in st
        assert "SET" in st

    def test_mixed_native_and_fb_property(self):
        """Native @property and @fb_property can coexist on the same FB."""
        @fb
        class Mixed:
            _a: REAL
            _b: INT

            @property
            def a(self) -> REAL:
                return self._a

            @fb_property(INT)
            def b(self):
                return self._b

            def logic(self):
                pass

        pou = Mixed.compile()
        assert len(pou.properties) == 2
        names = [p.name for p in pou.properties]
        assert "a" in names
        assert "b" in names

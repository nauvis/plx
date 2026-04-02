"""Extended tests for @fb_property: inheritance, setter renaming, complex logic."""

from plx.framework._decorators import fb
from plx.framework._properties import (
    PropDescriptor,
    _collect_properties,
    _rename_in_node,
    fb_property,
)
from plx.framework._types import BOOL, DINT, INT, REAL
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    LiteralExpr,
    MemberAccessExpr,
    VariableRef,
)
from plx.model.statements import Assignment

# ---------------------------------------------------------------------------
# Property inheritance
# ---------------------------------------------------------------------------


class TestPropertyInheritance:
    def test_inherited_property(self):
        """Child FB inherits parent property."""

        @fb
        class Base:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        @fb
        class Derived(Base):
            def logic(self):
                pass

        pou = Derived.compile()
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "speed"

    def test_overridden_property(self):
        """Child can override parent property."""

        @fb
        class Base:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        @fb
        class Derived(Base):
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed + 1.0

            def logic(self):
                pass

        pou = Derived.compile()
        # Should have exactly one property (override replaces parent)
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "speed"

    def test_child_adds_new_property(self):
        """Child can add properties beyond what parent has."""

        @fb
        class Base:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            def logic(self):
                pass

        @fb
        class Derived(Base):
            _torque: REAL

            @fb_property(REAL)
            def torque(self):
                return self._torque

            def logic(self):
                pass

        pou = Derived.compile()
        prop_names = [p.name for p in pou.properties]
        assert "speed" in prop_names
        assert "torque" in prop_names


# ---------------------------------------------------------------------------
# Setter parameter renaming
# ---------------------------------------------------------------------------


class TestSetterRenaming:
    def test_setter_param_renamed_to_property_name(self):
        """IEC 61131-3 setters use the property name, not the Python param."""

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
        setter = prop.setter
        assert setter is not None

        # The setter body should contain VariableRef("level"), not "value"
        stmts = setter.networks[0].statements
        assert len(stmts) >= 1

        # Find the assignment: self._level = level (renamed from value)
        assign = stmts[0]
        assert isinstance(assign, Assignment)
        # RHS should reference "level" (property name), not "value" (Python param)
        assert isinstance(assign.value, VariableRef)
        assert assign.value.name == "level"

    def test_setter_param_same_as_property_no_rename(self):
        """If Python param matches property name, no rename needed."""

        @fb
        class Pump:
            _flow: REAL

            @fb_property(REAL)
            def flow(self):
                return self._flow

            @flow.setter
            def flow(self, flow: REAL):
                self._flow = flow

            def logic(self):
                pass

        pou = Pump.compile()
        prop = pou.properties[0]
        setter = prop.setter
        assert setter is not None

        stmts = setter.networks[0].statements
        assign = stmts[0]
        assert isinstance(assign, Assignment)
        assert isinstance(assign.value, VariableRef)
        assert assign.value.name == "flow"


# ---------------------------------------------------------------------------
# _rename_in_node
# ---------------------------------------------------------------------------


class TestRenameInNode:
    def test_rename_variable_ref(self):
        node = VariableRef(name="old")
        result = _rename_in_node(node, "old", "new")
        assert result.name == "new"

    def test_no_rename_different_name(self):
        node = VariableRef(name="other")
        result = _rename_in_node(node, "old", "new")
        assert result is node  # unchanged — same object

    def test_rename_in_binary_expr(self):
        node = BinaryExpr(
            left=VariableRef(name="old"),
            op=BinaryOp.ADD,
            right=LiteralExpr(value="1"),
        )
        result = _rename_in_node(node, "old", "new")
        assert isinstance(result, BinaryExpr)
        assert result.left.name == "new"

    def test_rename_in_nested_binary_expr(self):
        """Deeply nested VariableRef gets renamed."""
        node = BinaryExpr(
            left=BinaryExpr(
                left=VariableRef(name="old"),
                op=BinaryOp.MUL,
                right=LiteralExpr(value="2"),
            ),
            op=BinaryOp.ADD,
            right=VariableRef(name="old"),
        )
        result = _rename_in_node(node, "old", "new")
        assert result.left.left.name == "new"
        assert result.right.name == "new"

    def test_rename_in_assignment(self):
        node = Assignment(
            target=VariableRef(name="x"),
            value=VariableRef(name="old"),
        )
        result = _rename_in_node(node, "old", "new")
        assert result.value.name == "new"
        assert result.target.name == "x"  # unchanged

    def test_rename_in_member_access(self):
        node = MemberAccessExpr(
            struct=VariableRef(name="old"),
            member="field",
        )
        result = _rename_in_node(node, "old", "new")
        assert result.struct.name == "new"


# ---------------------------------------------------------------------------
# Complex getter/setter logic
# ---------------------------------------------------------------------------


class TestComplexPropertyLogic:
    def test_getter_with_arithmetic(self):
        @fb
        class Sensor:
            _raw: INT
            _offset: INT

            @fb_property(INT)
            def calibrated(self):
                return self._raw + self._offset

            def logic(self):
                pass

        pou = Sensor.compile()
        prop = pou.properties[0]
        assert prop.getter is not None
        assert len(prop.getter.networks[0].statements) > 0

    def test_setter_with_clamping(self):
        @fb
        class Drive:
            _speed: REAL

            @fb_property(REAL)
            def speed(self):
                return self._speed

            @speed.setter
            def speed(self, value: REAL):
                if value > 100.0:
                    self._speed = 100.0
                else:
                    self._speed = value

            def logic(self):
                pass

        pou = Drive.compile()
        prop = pou.properties[0]
        assert prop.setter is not None
        stmts = prop.setter.networks[0].statements
        # Should compile the if/else into IR statements
        assert len(stmts) >= 1


# ---------------------------------------------------------------------------
# Various data types on properties
# ---------------------------------------------------------------------------


class TestPropertyTypes:
    def test_bool_property(self):
        @fb
        class Valve:
            _open: BOOL

            @fb_property(BOOL)
            def is_open(self):
                return self._open

            def logic(self):
                pass

        prop = Valve.compile().properties[0]
        assert prop.data_type.type.value == "BOOL"

    def test_int_property(self):
        @fb
        class Counter:
            _count: INT

            @fb_property(INT)
            def count(self):
                return self._count

            def logic(self):
                pass

        prop = Counter.compile().properties[0]
        assert prop.data_type.type.value == "INT"

    def test_dint_property(self):
        @fb
        class Accumulator:
            _total: DINT

            @fb_property(DINT)
            def total(self):
                return self._total

            def logic(self):
                pass

        prop = Accumulator.compile().properties[0]
        assert prop.data_type.type.value == "DINT"


# ---------------------------------------------------------------------------
# _collect_properties
# ---------------------------------------------------------------------------


class TestCollectProperties:
    def test_collect_from_single_class(self):
        class Fake:
            speed = fb_property(REAL)(lambda self: 0.0)

        props = _collect_properties(Fake)
        assert len(props) == 1
        assert props[0][0] == "speed"

    def test_collect_from_mro(self):
        class Base:
            speed = fb_property(REAL)(lambda self: 0.0)

        class Derived(Base):
            torque = fb_property(REAL)(lambda self: 0.0)

        props = _collect_properties(Derived)
        names = [name for name, _ in props]
        assert "speed" in names
        assert "torque" in names

    def test_override_in_mro(self):
        class Base:
            speed = fb_property(REAL)(lambda self: 0.0)

        class Derived(Base):
            speed = fb_property(INT)(lambda self: 0)

        props = _collect_properties(Derived)
        assert len(props) == 1
        assert props[0][0] == "speed"
        # Should be the child's version (INT)
        assert props[0][1].data_type.type.value == "INT"

    def test_empty_class(self):
        class Empty:
            pass

        props = _collect_properties(Empty)
        assert props == []


# ---------------------------------------------------------------------------
# PropDescriptor
# ---------------------------------------------------------------------------


class TestPropDescriptor:
    def test_descriptor_creation(self):
        @fb_property(REAL)
        def speed(self):
            return 0.0

        assert isinstance(speed, PropDescriptor)

    def test_setter_returns_same_descriptor(self):
        @fb_property(REAL)
        def speed(self):
            return 0.0

        result = speed.setter(lambda self, v: None)
        assert result is speed

    def test_setter_registers_function(self):
        @fb_property(REAL)
        def speed(self):
            return 0.0

        def set_speed(self, v: REAL):
            pass

        speed.setter(set_speed)
        assert speed._marker.setter_func is set_speed

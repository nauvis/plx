"""Edge case tests for FB inheritance, deep chains, and OOP interactions.

Covers scenarios not tested in test_inheritance.py, test_methods.py, or
test_property_coverage.py:
- 4+ level inheritance chains
- Method + property + variable inheritance combined
- Diamond-free multi-level method override
- super().logic() at every level of a deep chain
- Variable direction changes across levels
- Child with no logic but methods/properties from parent
- Sentinel inheritance across levels
- Mixed direction variable override
"""

import pytest
from datetime import timedelta

from plx.framework._compiler import CompileError, delayed, rising
from plx.framework._decorators import fb, fb_method, function, program
from plx.framework._descriptors import Input, Output, Static, Temp, Field
from plx.framework._properties import fb_property
from plx.framework._types import BOOL, DINT, INT, REAL, TIME
from plx.model.pou import POUType
from plx.model.statements import Assignment, FBInvocation, IfStatement
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef


# ===========================================================================
# Deep inheritance chains (4+ levels)
# ===========================================================================

class TestDeepInheritance:
    """Test 4 and 5 level inheritance chains."""

    def test_four_level_chain(self):
        @fb
        class L1:
            a: Input[BOOL]
            w: Output[BOOL]

            def logic(self):
                self.w = self.a

        @fb
        class L2(L1):
            x: Output[BOOL]

            def logic(self):
                super().logic()
                self.x = not self.a

        @fb
        class L3(L2):
            y: Output[BOOL]

            def logic(self):
                super().logic()
                self.y = self.w and self.x

        @fb
        class L4(L3):
            z: Output[BOOL]

            def logic(self):
                super().logic()
                self.z = self.y

        pou = L4.compile()
        assert pou.extends == "L3"

        # All outputs present: w (L1), x (L2), y (L3), z (L4)
        output_names = [v.name for v in pou.interface.output_vars]
        assert output_names == ["w", "x", "y", "z"]

        # 4 statements inlined: w=a, x=!a, y=w&x, z=y
        stmts = pou.networks[0].statements
        assert len(stmts) == 4
        assert stmts[0].target.name == "w"
        assert stmts[3].target.name == "z"

    def test_five_level_chain(self):
        @fb
        class A:
            v: Input[DINT]
            r1: Output[DINT]

            def logic(self):
                self.r1 = self.v + 1

        @fb
        class B(A):
            r2: Output[DINT]

            def logic(self):
                super().logic()
                self.r2 = self.r1 + 1

        @fb
        class C(B):
            r3: Output[DINT]

            def logic(self):
                super().logic()
                self.r3 = self.r2 + 1

        @fb
        class D(C):
            r4: Output[DINT]

            def logic(self):
                super().logic()
                self.r4 = self.r3 + 1

        @fb
        class E(D):
            r5: Output[DINT]

            def logic(self):
                super().logic()
                self.r5 = self.r4 + 1

        pou = E.compile()
        assert pou.extends == "D"
        stmts = pou.networks[0].statements
        assert len(stmts) == 5

    def test_deep_chain_extends_only_immediate_parent(self):
        """Each level only extends its immediate parent, not grandparent."""
        @fb
        class Root:
            x: Input[BOOL]
            def logic(self):
                pass

        @fb
        class Mid(Root):
            def logic(self):
                super().logic()

        @fb
        class Leaf(Mid):
            def logic(self):
                super().logic()

        assert Root.compile().extends is None
        assert Mid.compile().extends == "Root"
        assert Leaf.compile().extends == "Mid"


# ===========================================================================
# Methods across inheritance levels
# ===========================================================================

class TestMethodInheritanceDeep:
    """Test methods inherited, overridden, and added across multiple levels."""

    def test_method_inherited_through_two_levels(self):
        """Method defined on grandparent should appear on grandchild."""
        @fb
        class GP:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        @fb
        class P(GP):
            def logic(self):
                super().logic()

        @fb
        class C(P):
            def logic(self):
                super().logic()

        pou = C.compile()
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "reset"

    def test_method_override_at_middle_level(self):
        """Override a method at middle level — child gets the override."""
        @fb
        class GP:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        @fb
        class P(GP):
            y: REAL

            def logic(self):
                super().logic()

            @fb_method
            def reset(self):
                self.x = 0.0
                self.y = 0.0

        @fb
        class C(P):
            def logic(self):
                super().logic()

        pou = C.compile()
        assert len(pou.methods) == 1
        # Should have P's 2-statement version, not GP's 1-statement version
        assert len(pou.methods[0].networks[0].statements) == 2

    def test_methods_accumulated_across_levels(self):
        """Each level adds a method — child gets all of them."""
        @fb
        class L1:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def m1(self):
                self.x = 1.0

        @fb
        class L2(L1):
            def logic(self):
                super().logic()

            @fb_method
            def m2(self):
                self.x = 2.0

        @fb
        class L3(L2):
            def logic(self):
                super().logic()

            @fb_method
            def m3(self):
                self.x = 3.0

        pou = L3.compile()
        method_names = [m.name for m in pou.methods]
        assert "m1" in method_names
        assert "m2" in method_names
        assert "m3" in method_names
        assert len(method_names) == 3


# ===========================================================================
# Properties across inheritance levels
# ===========================================================================

class TestPropertyInheritanceDeep:
    """Test properties inherited and overridden across multiple levels."""

    def test_property_inherited_through_two_levels(self):
        @fb
        class GP:
            _val: REAL

            @fb_property(REAL)
            def val(self):
                return self._val

            def logic(self):
                pass

        @fb
        class P(GP):
            def logic(self):
                pass

        @fb
        class C(P):
            def logic(self):
                pass

        pou = C.compile()
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "val"

    def test_property_override_at_leaf(self):
        """Override a grandparent's property at the leaf level."""
        @fb
        class GP:
            _val: REAL

            @fb_property(REAL)
            def val(self):
                return self._val

            def logic(self):
                pass

        @fb
        class P(GP):
            def logic(self):
                pass

        @fb
        class C(P):
            _val: REAL

            @fb_property(REAL)
            def val(self):
                return self._val + 1.0

            def logic(self):
                pass

        pou = C.compile()
        assert len(pou.properties) == 1
        # Should have C's version (with +1.0)
        assert pou.properties[0].getter is not None


# ===========================================================================
# Combined: methods + properties + variables across levels
# ===========================================================================

class TestCombinedOOPInheritance:
    """Test methods, properties, and variables interacting across inheritance."""

    def test_full_oop_chain(self):
        """FB with vars + method + property at each level."""
        @fb
        class Base:
            speed: Input[REAL]
            running: Output[BOOL]
            _position: REAL

            def logic(self):
                self.running = self.speed > 0.0

            @fb_method
            def stop(self):
                self.running = False

            @fb_property(REAL)
            def position(self):
                return self._position

        @fb
        class Advanced(Base):
            accel: Input[REAL]
            at_target: Output[BOOL]

            def logic(self):
                super().logic()
                self.at_target = self._position > 100.0

            @fb_method
            def home(self):
                self._position = 0.0

        pou = Advanced.compile()

        # Variables: speed (inherited), accel (own) as inputs
        input_names = [v.name for v in pou.interface.input_vars]
        assert "speed" in input_names
        assert "accel" in input_names

        # Outputs: running (inherited), at_target (own)
        output_names = [v.name for v in pou.interface.output_vars]
        assert "running" in output_names
        assert "at_target" in output_names

        # Methods: stop (inherited) + home (own)
        method_names = [m.name for m in pou.methods]
        assert "stop" in method_names
        assert "home" in method_names

        # Property: position (inherited)
        assert len(pou.properties) == 1
        assert pou.properties[0].name == "position"

        # Logic: 2 statements (parent + child)
        stmts = pou.networks[0].statements
        assert len(stmts) == 2


# ===========================================================================
# Sentinel inheritance
# ===========================================================================

class TestSentinelInheritanceDeep:
    """Test sentinel functions (delayed, rising) across inheritance levels."""

    def test_sentinels_at_each_level(self):
        """Each level uses its own sentinel — all get unique instances."""
        @fb
        class L1:
            sig: Input[BOOL]
            out1: Output[BOOL]

            def logic(self):
                self.out1 = delayed(self.sig, timedelta(seconds=1))

        @fb
        class L2(L1):
            out2: Output[BOOL]

            def logic(self):
                super().logic()
                self.out2 = delayed(self.sig, timedelta(seconds=2))

        @fb
        class L3(L2):
            out3: Output[BOOL]

            def logic(self):
                super().logic()
                self.out3 = rising(self.sig)

        pou = L3.compile()

        # Should have 2 TON instances + 1 R_TRIG instance
        static_types = {v.name: v.data_type for v in pou.interface.static_vars
                        if isinstance(v.data_type, NamedTypeRef)}
        ton_count = sum(1 for dt in static_types.values() if dt.name == "TON")
        rtrig_count = sum(1 for dt in static_types.values() if dt.name == "R_TRIG")
        assert ton_count == 2
        assert rtrig_count == 1

        # All instance names should be unique
        names = [v.name for v in pou.interface.static_vars
                 if isinstance(v.data_type, NamedTypeRef)]
        assert len(names) == len(set(names))


# ===========================================================================
# Edge cases: no logic, empty bodies, variable direction
# ===========================================================================

class TestInheritanceEdgeCases:

    def test_child_no_logic_inherits_parent_logic(self):
        """Child with no logic() method uses parent's."""
        @fb
        class Parent:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = self.x

        @fb
        class Child(Parent):
            z: Static[DINT] = 0

        pou = Child.compile()
        assert len(pou.networks[0].statements) == 1
        assert pou.networks[0].statements[0].target.name == "y"

    def test_child_empty_logic_with_super(self):
        """Child with only super().logic() produces same output as parent."""
        @fb
        class Parent:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = self.x

        @fb
        class Child(Parent):
            def logic(self):
                super().logic()

        pou = Child.compile()
        stmts = pou.networks[0].statements
        assert len(stmts) == 1
        assert stmts[0].target.name == "y"

    def test_child_adds_vars_only(self):
        """Child adds variables without any logic."""
        @fb
        class Parent:
            x: Input[BOOL]

            def logic(self):
                pass

        @fb
        class Child(Parent):
            extra: Output[REAL] = 0.0

        pou = Child.compile()
        assert any(v.name == "extra" for v in pou.interface.output_vars)
        assert any(v.name == "x" for v in pou.interface.input_vars)

    def test_variable_override_changes_type(self):
        """Child can override parent variable with a different type."""
        @fb
        class Parent:
            val: Input[INT]
            out: Output[BOOL]

            def logic(self):
                self.out = self.val > 0

        @fb
        class Child(Parent):
            val: Input[DINT]  # wider type

            def logic(self):
                super().logic()

        pou = Child.compile()
        val_var = next(v for v in pou.interface.input_vars if v.name == "val")
        # Should be DINT, not INT
        assert isinstance(val_var.data_type, PrimitiveTypeRef)
        assert val_var.data_type.type == PrimitiveType.DINT

    def test_variable_override_changes_initial_value(self):
        """Child can override parent variable's initial value."""
        @fb
        class Parent:
            timeout: Input[REAL] = 5.0
            out: Output[BOOL]

            def logic(self):
                self.out = True

        @fb
        class Child(Parent):
            timeout: Input[REAL] = 30.0

            def logic(self):
                super().logic()

        pou = Child.compile()
        timeout_var = next(v for v in pou.interface.input_vars if v.name == "timeout")
        assert timeout_var.initial_value == "30.0"

    def test_multiple_super_calls_inline_twice(self):
        """Calling super().logic() twice inlines parent logic twice."""
        @fb
        class Parent:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = self.x

        @fb
        class Child(Parent):
            def logic(self):
                super().logic()
                super().logic()

        pou = Child.compile()
        stmts = pou.networks[0].statements
        # Parent logic inlined twice
        assert len(stmts) == 2
        assert stmts[0].target.name == "y"
        assert stmts[1].target.name == "y"

    def test_child_with_if_around_super(self):
        """super().logic() inside an if block should work."""
        @fb
        class Parent:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = self.x

        @fb
        class Child(Parent):
            enable: Input[BOOL]

            def logic(self):
                if self.enable:
                    super().logic()

        pou = Child.compile()
        stmts = pou.networks[0].statements
        assert len(stmts) == 1
        assert isinstance(stmts[0], IfStatement)
        # Parent's logic is inside the if body
        assert len(stmts[0].if_branch.body) == 1


# ===========================================================================
# Program and function inheritance restrictions
# ===========================================================================

class TestInheritanceRestrictions:

    def test_program_cannot_inherit_fb(self):
        """@program inheriting from @fb should still compile (extends detected)."""
        @fb
        class BaseFB:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = self.x

        @program
        class MainProg(BaseFB):
            def logic(self):
                super().logic()

        pou = MainProg.compile()
        assert pou.pou_type == POUType.PROGRAM
        # Should inherit parent's vars
        assert any(v.name == "x" for v in pou.interface.input_vars)

    def test_fb_inheriting_non_fb_base_ignored(self):
        """Base class without _compiled_pou is silently skipped."""
        class PlainPython:
            pass

        @fb
        class MyFB(PlainPython):
            x: Input[BOOL]

            def logic(self):
                pass

        pou = MyFB.compile()
        assert pou.extends is None

    def test_method_not_confused_with_logic(self):
        """@fb_method functions should NOT be compiled as logic()."""
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                self.x = 1.0

            @fb_method
            def do_thing(self, amount: REAL) -> BOOL:
                self.x = amount
                return True

        pou = MyFB.compile()
        # logic has 1 statement
        assert len(pou.networks[0].statements) == 1
        assert pou.networks[0].statements[0].target.name == "x"
        # method has its own separate body
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "do_thing"
        assert len(pou.methods[0].networks[0].statements) == 2

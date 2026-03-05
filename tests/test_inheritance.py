"""Tests for FB inheritance and super().logic()."""

import pytest

from plx.framework._compiler import CompileError
from plx.framework._decorators import fb
from plx.framework._descriptors import Input, Field, Output
from datetime import timedelta
from plx.framework._types import BOOL, DINT, REAL, TIME
from plx.model.pou import POU, POUType
from plx.model.statements import Assignment, FBInvocation, IfStatement
from plx.model.types import NamedTypeRef


# -- Fixtures: define base and derived FBs --------------------------------

@fb
class _Base:
    x: Input[BOOL]
    y: Output[BOOL]

    def logic(self):
        self.y = self.x


@fb
class _Derived(_Base):
    z: Output[BOOL]

    def logic(self):
        super().logic()
        self.z = not self.x


# ---------------------------------------------------------------------------
# extends field
# ---------------------------------------------------------------------------

class TestExtends:
    def test_base_has_no_extends(self):
        assert _Base.compile().extends is None

    def test_derived_has_extends(self):
        assert _Derived.compile().extends == "_Base"

    def test_pou_type_preserved(self):
        assert _Derived.compile().pou_type == POUType.FUNCTION_BLOCK


# ---------------------------------------------------------------------------
# Variable inheritance
# ---------------------------------------------------------------------------

class TestVariableInheritance:
    def test_derived_inherits_inputs(self):
        pou = _Derived.compile()
        input_names = [v.name for v in pou.interface.input_vars]
        assert "x" in input_names

    def test_derived_has_own_outputs(self):
        pou = _Derived.compile()
        output_names = [v.name for v in pou.interface.output_vars]
        assert "y" in output_names  # inherited
        assert "z" in output_names  # own

    def test_parent_vars_come_first(self):
        pou = _Derived.compile()
        output_names = [v.name for v in pou.interface.output_vars]
        assert output_names.index("y") < output_names.index("z")


class TestVariableOverride:
    def test_child_overrides_parent_default(self):
        @fb
        class Parent:
            timeout: Input[TIME] = timedelta(seconds=3)
            out: Output[BOOL]

            def logic(self):
                self.out = True

        @fb
        class Child(Parent):
            timeout: Input[TIME] = timedelta(seconds=10)

            def logic(self):
                super().logic()

        pou = Child.compile()
        timeout_var = next(v for v in pou.interface.input_vars if v.name == "timeout")
        assert timeout_var.initial_value == "T#10s"

    def test_override_does_not_duplicate(self):
        @fb
        class Parent:
            x: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                self.out = True

        @fb
        class Child(Parent):
            x: Input[REAL]  # override type
            extra: Output[BOOL]

            def logic(self):
                super().logic()

        pou = Child.compile()
        input_names = [v.name for v in pou.interface.input_vars]
        assert input_names.count("x") == 1


# ---------------------------------------------------------------------------
# super().logic() inlining
# ---------------------------------------------------------------------------

class TestSuperLogic:
    def test_inlines_parent_statements(self):
        pou = _Derived.compile()
        stmts = pou.networks[0].statements
        # Parent: 1 assignment (y = x)
        # Child: 1 assignment (z = not x)
        assert len(stmts) == 2

    def test_parent_statement_first(self):
        pou = _Derived.compile()
        stmts = pou.networks[0].statements
        # First statement should be parent's y = x
        assert isinstance(stmts[0], Assignment)
        assert stmts[0].target.name == "y"
        # Second is child's z = not x
        assert isinstance(stmts[1], Assignment)
        assert stmts[1].target.name == "z"

    def test_super_in_middle(self):
        @fb
        class Parent:
            a: Input[BOOL]
            b: Output[BOOL]

            def logic(self):
                self.b = self.a

        @fb
        class Child(Parent):
            c: Output[BOOL]

            def logic(self):
                self.c = False
                super().logic()
                self.c = self.b

        pou = Child.compile()
        stmts = pou.networks[0].statements
        assert len(stmts) == 3
        assert stmts[0].target.name == "c"
        assert stmts[1].target.name == "b"  # from parent
        assert stmts[2].target.name == "c"

    def test_super_with_sentinels(self):
        """Parent uses delayed() — child should inherit the generated TON instance."""
        from plx.framework._compiler import delayed

        @fb
        class TimedBase:
            sig: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                self.out = delayed(self.sig, timedelta(seconds=5))

        @fb
        class TimedChild(TimedBase):
            extra: Output[BOOL]

            def logic(self):
                super().logic()
                self.extra = delayed(self.sig, timedelta(seconds=10))

        pou = TimedChild.compile()
        # Should have 2 TON static vars with unique names
        ton_vars = [v for v in pou.interface.static_vars
                     if isinstance(v.data_type, NamedTypeRef) and v.data_type.name == "TON"]
        assert len(ton_vars) == 2
        assert ton_vars[0].name != ton_vars[1].name

        # Should have 4 statements: FBInvocation, Assignment, FBInvocation, Assignment
        stmts = pou.networks[0].statements
        assert len(stmts) == 4
        assert isinstance(stmts[0], FBInvocation)
        assert isinstance(stmts[2], FBInvocation)


# ---------------------------------------------------------------------------
# Three-level inheritance
# ---------------------------------------------------------------------------

class TestThreeLevel:
    def test_three_level_chain(self):
        @fb
        class GrandParent:
            a: Input[BOOL]
            x: Output[BOOL]

            def logic(self):
                self.x = self.a

        @fb
        class Parent(GrandParent):
            y: Output[BOOL]

            def logic(self):
                super().logic()
                self.y = not self.a

        @fb
        class Child(Parent):
            z: Output[BOOL]

            def logic(self):
                super().logic()
                self.z = self.x and self.y

        pou = Child.compile()
        assert pou.extends == "Parent"

        output_names = [v.name for v in pou.interface.output_vars]
        assert output_names == ["x", "y", "z"]

        stmts = pou.networks[0].statements
        # GrandParent: x = a (1)
        # Parent: y = not a (1)
        # Child: z = x and y (1)
        assert len(stmts) == 3

    def test_extends_points_to_immediate_parent(self):
        @fb
        class L1:
            a: Input[BOOL]
            def logic(self):
                pass

        @fb
        class L2(L1):
            def logic(self):
                super().logic()

        @fb
        class L3(L2):
            def logic(self):
                super().logic()

        assert L3.compile().extends == "L2"
        assert L2.compile().extends == "L1"
        assert L1.compile().extends is None


# ---------------------------------------------------------------------------
# Inheriting logic without override
# ---------------------------------------------------------------------------

class TestInheritedLogic:
    def test_child_inherits_logic_without_override(self):
        """Child without its own logic() uses parent's."""
        @fb
        class Parent:
            a: Input[BOOL]
            b: Output[BOOL]

            def logic(self):
                self.b = self.a

        @fb
        class Child(Parent):
            c: Output[BOOL] = False

        pou = Child.compile()
        assert pou.extends == "Parent"
        stmts = pou.networks[0].statements
        # Uses parent's logic: b = a
        assert len(stmts) == 1
        assert stmts[0].target.name == "b"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestSuperErrors:
    def test_super_logic_on_base_class(self):
        """Calling super().logic() on a class with no parent logic raises."""
        with pytest.raises(CompileError, match="no parent class"):
            @fb
            class Orphan:
                x: Input[BOOL]

                def logic(self):
                    super().logic()
                    self.x = True

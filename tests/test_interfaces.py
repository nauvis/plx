"""Tests for @interface decorator and implements= on @fb."""

import pytest

from plx.framework._compiler_core import CompileError
from plx.framework._decorators import fb, interface, method
from plx.framework._descriptors import input_var, output_var, static_var
from plx.framework._types import BOOL, REAL
from plx.model.pou import POUType


# ---------------------------------------------------------------------------
# Basic @interface
# ---------------------------------------------------------------------------

class TestInterface:
    def test_basic_interface(self):
        @interface
        class IMoveable:
            @method
            def move_to(self, target: REAL) -> BOOL: ...

        pou = IMoveable.compile()
        assert pou.pou_type == POUType.INTERFACE
        assert pou.name == "IMoveable"
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "move_to"
        assert pou.methods[0].return_type is not None

    def test_interface_method_params(self):
        @interface
        class IMotor:
            @method
            def set_speed(self, speed: REAL, enable: BOOL) -> BOOL: ...

        pou = IMotor.compile()
        m = pou.methods[0]
        assert m.name == "set_speed"
        assert len(m.interface.input_vars) == 2
        assert m.interface.input_vars[0].name == "speed"
        assert m.interface.input_vars[1].name == "enable"

    def test_interface_no_body_compiled(self):
        """Interface methods should have no networks/body."""
        @interface
        class ISimple:
            @method
            def do_thing(self): ...

        pou = ISimple.compile()
        assert pou.methods[0].networks == []

    def test_interface_marker(self):
        @interface
        class IFoo:
            @method
            def bar(self): ...

        assert getattr(IFoo, "__plx_interface__", False) is True


# ---------------------------------------------------------------------------
# Interface extends (inheritance)
# ---------------------------------------------------------------------------

class TestInterfaceExtends:
    def test_extends(self):
        @interface
        class IBase:
            @method
            def base_method(self): ...

        @interface
        class IDerived(IBase):
            @method
            def derived_method(self): ...

        pou = IDerived.compile()
        assert pou.extends == "IBase"
        # Should have both inherited and own methods
        method_names = [m.name for m in pou.methods]
        assert "base_method" in method_names
        assert "derived_method" in method_names

    def test_no_extends_without_parent(self):
        @interface
        class IStandalone:
            @method
            def foo(self): ...

        pou = IStandalone.compile()
        assert pou.extends is None


# ---------------------------------------------------------------------------
# implements= on @fb
# ---------------------------------------------------------------------------

class TestImplements:
    def test_fb_implements(self):
        @interface
        class IRunnable:
            @method
            def run(self, speed: REAL) -> BOOL: ...

        @fb(implements=[IRunnable])
        class Motor:
            speed = static_var(REAL)

            @method
            def run(self, speed: REAL) -> BOOL:
                self.speed = speed
                return True

            def logic(self):
                pass

        pou = Motor.compile()
        assert pou.implements == ["IRunnable"]

    def test_fb_implements_multiple(self):
        @interface
        class IA:
            @method
            def a(self): ...

        @interface
        class IB:
            @method
            def b(self): ...

        @fb(implements=[IA, IB])
        class Combined:
            @method
            def a(self):
                pass

            @method
            def b(self):
                pass

            def logic(self):
                pass

        pou = Combined.compile()
        assert pou.implements == ["IA", "IB"]

    def test_implements_rejects_non_interface(self):
        @fb
        class NotAnInterface:
            def logic(self):
                pass

        with pytest.raises(CompileError, match="not an @interface"):
            @fb(implements=[NotAnInterface])
            class Bad:
                def logic(self):
                    pass


# ---------------------------------------------------------------------------
# ST export of interfaces
# ---------------------------------------------------------------------------

class TestInterfaceSTExport:
    def test_interface_st(self):
        from plx.export.st import to_structured_text

        @interface
        class IMotor:
            @method
            def start(self, speed: REAL) -> BOOL: ...

        pou = IMotor.compile()
        st = to_structured_text(pou)
        assert "INTERFACE IMotor" in st
        assert "METHOD start : BOOL" in st
        assert "END_INTERFACE" in st

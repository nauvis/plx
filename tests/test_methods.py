"""Tests for @fb_method decorator on function blocks."""

import pytest

from datetime import timedelta

from plx.framework import (
    BOOL,
    DINT,
    REAL,
    TIME,
    fb,
    fb_method,
    Input,
    Output,
    delayed,
    CompileError,
    Field,
)
from plx.model.pou import AccessSpecifier, Method, POU, POUType
from plx.model.expressions import BinaryExpr, FunctionCallExpr, LiteralExpr, VariableRef
from plx.model.statements import Assignment, FunctionCallStatement, ReturnStatement
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# Basic method compilation
# ---------------------------------------------------------------------------

class TestMethodBasic:
    def test_method_appears_on_pou(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        pou = MyFB.compile()
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "reset"

    def test_method_body_compiled(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        m = MyFB.compile().methods[0]
        assert len(m.networks) == 1
        assert len(m.networks[0].statements) == 1
        stmt = m.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert stmt.target.name == "x"

    def test_multiple_methods(self):
        @fb
        class Motor:
            speed: REAL
            running: Output[BOOL]

            def logic(self):
                pass

            @fb_method
            def start(self, target: REAL):
                self.speed = target
                self.running = True

            @fb_method
            def stop(self):
                self.speed = 0.0
                self.running = False

        pou = Motor.compile()
        assert len(pou.methods) == 2
        names = [m.name for m in pou.methods]
        assert "start" in names
        assert "stop" in names

    def test_non_decorated_methods_excluded(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

            def _python_helper(self):
                """This should NOT be compiled."""
                pass

        pou = MyFB.compile()
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "reset"


# ---------------------------------------------------------------------------
# Method parameters → input_vars
# ---------------------------------------------------------------------------

class TestMethodParameters:
    def test_typed_parameter(self):
        @fb
        class MyFB:
            speed: REAL

            def logic(self):
                pass

            @fb_method
            def set_speed(self, target: REAL):
                self.speed = target

        m = MyFB.compile().methods[0]
        assert len(m.interface.input_vars) == 1
        assert m.interface.input_vars[0].name == "target"
        assert m.interface.input_vars[0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_multiple_parameters(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def configure(self, low: REAL, high: REAL, enable: BOOL):
                pass

        m = MyFB.compile().methods[0]
        assert len(m.interface.input_vars) == 3
        names = [v.name for v in m.interface.input_vars]
        assert names == ["low", "high", "enable"]

    def test_self_not_included(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        m = MyFB.compile().methods[0]
        assert len(m.interface.input_vars) == 0

    def test_parameter_used_in_body(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def set_value(self, val: REAL):
                self.x = val

        m = MyFB.compile().methods[0]
        stmt = m.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, VariableRef)
        assert stmt.value.name == "val"

    def test_untyped_parameter_raises(self):
        with pytest.raises(CompileError, match="type annotation"):
            @fb
            class BadFB:
                x: REAL

                def logic(self):
                    pass

                @fb_method
                def bad_method(self, val):
                    self.x = val


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class TestMethodReturnType:
    def test_return_type(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def get_value(self) -> REAL:
                return self.x

        m = MyFB.compile().methods[0]
        assert m.return_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_no_return_type(self):
        @fb
        class MyFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        m = MyFB.compile().methods[0]
        assert m.return_type is None

    def test_bool_return(self):
        @fb
        class MyFB:
            running: BOOL

            def logic(self):
                pass

            @fb_method
            def is_running(self) -> BOOL:
                return self.running

        m = MyFB.compile().methods[0]
        assert m.return_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)
        stmts = m.networks[0].statements
        assert isinstance(stmts[0], ReturnStatement)


# ---------------------------------------------------------------------------
# Access specifiers
# ---------------------------------------------------------------------------

class TestMethodAccess:
    def test_default_public(self):
        @fb
        class MyFB:
            def logic(self):
                pass

            @fb_method
            def reset(self):
                pass

        assert MyFB.compile().methods[0].access == AccessSpecifier.PUBLIC

    def test_explicit_public(self):
        @fb
        class MyFB:
            def logic(self):
                pass

            @fb_method(access=AccessSpecifier.PUBLIC)
            def reset(self):
                pass

        assert MyFB.compile().methods[0].access == AccessSpecifier.PUBLIC

    def test_private(self):
        @fb
        class MyFB:
            def logic(self):
                pass

            @fb_method(access=AccessSpecifier.PRIVATE)
            def _internal(self):
                pass

        assert MyFB.compile().methods[0].access == AccessSpecifier.PRIVATE

    def test_protected(self):
        @fb
        class MyFB:
            def logic(self):
                pass

            @fb_method(access=AccessSpecifier.PROTECTED)
            def _helper(self):
                pass

        assert MyFB.compile().methods[0].access == AccessSpecifier.PROTECTED


# ---------------------------------------------------------------------------
# Methods access FB instance vars
# ---------------------------------------------------------------------------

class TestMethodAccessFBVars:
    def test_reads_input(self):
        @fb
        class MyFB:
            sensor: Input[BOOL]
            result: Output[BOOL]

            def logic(self):
                pass

            @fb_method
            def check(self) -> BOOL:
                return self.sensor

        m = MyFB.compile().methods[0]
        stmt = m.networks[0].statements[0]
        assert isinstance(stmt, ReturnStatement)
        assert isinstance(stmt.value, VariableRef)
        assert stmt.value.name == "sensor"

    def test_writes_output(self):
        @fb
        class MyFB:
            out: Output[REAL]

            def logic(self):
                pass

            @fb_method
            def set_output(self, val: REAL):
                self.out = val

        m = MyFB.compile().methods[0]
        stmt = m.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert stmt.target.name == "out"

    def test_reads_static(self):
        @fb
        class MyFB:
            count: DINT = 0

            def logic(self):
                pass

            @fb_method
            def get_count(self) -> DINT:
                return self.count

        m = MyFB.compile().methods[0]
        stmt = m.networks[0].statements[0]
        assert stmt.value.name == "count"


# ---------------------------------------------------------------------------
# Methods called from logic()
# ---------------------------------------------------------------------------

class TestMethodCalledFromLogic:
    def test_method_call_as_expression(self):
        """self.method() in expression context should not prepend self as arg."""
        @fb
        class Valve:
            pressure: REAL
            limit: REAL = 100.0

            def logic(self):
                self.pressure = self.check_limits()

            @fb_method
            def check_limits(self) -> REAL:
                return self.limit

        pou = Valve.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "check_limits"
        # No 'self' argument should be present
        assert len(stmt.value.args) == 0

    def test_method_call_with_args_as_expression(self):
        """self.method(arg) in expression context compiles args correctly."""
        @fb
        class Limiter:
            val: REAL

            def logic(self):
                self.val = self.clamp(self.val)

            @fb_method
            def clamp(self, x: REAL) -> REAL:
                return x

        pou = Limiter.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "clamp"
        assert len(stmt.value.args) == 1
        assert isinstance(stmt.value.args[0].value, VariableRef)
        assert stmt.value.args[0].value.name == "val"

    def test_method_call_as_statement(self):
        """self.method() as a statement should also work correctly."""
        @fb
        class Motor:
            speed: REAL

            def logic(self):
                self.reset()

            @fb_method
            def reset(self):
                self.speed = 0.0

        pou = Motor.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, FunctionCallStatement)
        assert stmt.function_name == "reset"
        assert len(stmt.args) == 0


# ---------------------------------------------------------------------------
# Methods with sentinels
# ---------------------------------------------------------------------------

class TestMethodWithSentinels:
    def test_method_with_delayed(self):
        @fb
        class MyFB:
            sig: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                pass

            @fb_method
            def timed_check(self) -> BOOL:
                return delayed(self.sig, timedelta(seconds=5))

        m = MyFB.compile().methods[0]
        # Should have generated a TON static var on the method
        assert len(m.interface.static_vars) == 1
        assert m.interface.static_vars[0].data_type == NamedTypeRef(name="TON")


# ---------------------------------------------------------------------------
# Method inheritance
# ---------------------------------------------------------------------------

class TestMethodInheritance:
    def test_child_inherits_methods(self):
        @fb
        class Parent:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        @fb
        class Child(Parent):
            y: REAL

            def logic(self):
                super().logic()

        pou = Child.compile()
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "reset"

    def test_child_overrides_method(self):
        @fb
        class Parent:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        @fb
        class Child(Parent):
            y: REAL

            def logic(self):
                super().logic()

            @fb_method
            def reset(self):
                self.x = 0.0
                self.y = 0.0

        pou = Child.compile()
        assert len(pou.methods) == 1
        # Child's reset has 2 statements, parent's had 1
        assert len(pou.methods[0].networks[0].statements) == 2

    def test_child_adds_method(self):
        @fb
        class Parent:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def reset(self):
                self.x = 0.0

        @fb
        class Child(Parent):
            def logic(self):
                super().logic()

            @fb_method
            def extra(self) -> BOOL:
                return True

        pou = Child.compile()
        assert len(pou.methods) == 2
        names = [m.name for m in pou.methods]
        assert "reset" in names
        assert "extra" in names


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestMethodSerialization:
    def test_pou_with_methods_serializes(self):
        @fb
        class SerFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def set_x(self, val: REAL):
                self.x = val

        pou = SerFB.compile()
        data = pou.model_dump()
        assert len(data["methods"]) == 1
        m = data["methods"][0]
        assert m["name"] == "set_x"
        assert m["access"] == "PUBLIC"
        assert len(m["interface"]["input_vars"]) == 1
        assert m["interface"]["input_vars"][0]["name"] == "val"

    def test_pou_with_methods_roundtrips(self):
        @fb
        class RoundFB:
            x: REAL

            def logic(self):
                pass

            @fb_method
            def get_x(self) -> REAL:
                return self.x

        pou = RoundFB.compile()
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert len(restored.methods) == 1
        assert restored.methods[0].name == "get_x"
        assert restored.methods[0].return_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

"""Tests for Pythonic API improvements.

Covers:
  1. Simulation context manager (with statement)
  2. Re-exports (dataclass, IntEnum, Annotated)
  3. Optional logic() for data-only FBs
  4. Annotated metadata support
  5. Python builtins in examples
"""

import pytest

from plx.framework import (
    # Re-exports we're testing
    dataclass,
    IntEnum,
    Annotated,
    # Errors
    DeclarationError,
    # Core API
    fb,
    program,
    function,
    method,
    Input,
    Output,
    Static,
    Temp,
    Constant,
    Field,
    project,
    struct,
    enumeration,
    REAL,
    DINT,
    BOOL,
    CompileError,
)
from plx.framework._descriptors import _collect_descriptors
from plx.model.types import PrimitiveType, PrimitiveTypeRef, NamedTypeRef
from plx.simulate import simulate


# ===========================================================================
# 1. Simulation context manager
# ===========================================================================

class TestSimulationContextManager:
    def test_with_statement(self):
        @fb
        class Motor:
            cmd: Input[bool]
            running: Output[bool]

            def logic(self):
                self.running = self.cmd

        with simulate(Motor) as ctx:
            ctx.cmd = True
            ctx.scan()
            assert ctx.running is True

    def test_variables_accessible_inside_with(self):
        @fb
        class Simple:
            x: Input[int]
            y: Output[int]

            def logic(self):
                self.y = self.x + 1

        with simulate(Simple) as ctx:
            ctx.x = 10
            ctx.scan()
            assert ctx.y == 11

    def test_tick_works_inside_with(self):
        @fb
        class Counter:
            count: Output[int]

            def logic(self):
                self.count += 1

        with simulate(Counter) as ctx:
            ctx.tick(ms=50)
            assert ctx.count == 5  # 50ms / 10ms per scan = 5

    def test_exception_propagates(self):
        @fb
        class Dummy:
            x: Output[bool]

            def logic(self):
                self.x = True

        with pytest.raises(ValueError, match="test error"):
            with simulate(Dummy) as ctx:
                ctx.scan()
                raise ValueError("test error")

    def test_enter_returns_self(self):
        @fb
        class Dummy:
            x: Output[bool]

            def logic(self):
                self.x = True

        ctx = simulate(Dummy)
        assert ctx.__enter__() is ctx
        ctx.__exit__(None, None, None)


# ===========================================================================
# 2. Re-exports
# ===========================================================================

class TestReExports:
    def test_dataclass_import(self):
        from plx.framework import dataclass as dc
        assert dc is dataclass
        from dataclasses import dataclass as std_dc
        assert dc is std_dc

    def test_intenum_import(self):
        from plx.framework import IntEnum as ie
        assert ie is IntEnum
        from enum import IntEnum as std_ie
        assert ie is std_ie

    def test_annotated_import(self):
        from plx.framework import Annotated as ann
        from typing import Annotated as std_ann
        assert ann is std_ann

    def test_intenum_works_as_enumeration(self):
        """IntEnum classes should work as data_types in project()."""
        class Color(IntEnum):
            RED = 0
            GREEN = 1
            BLUE = 2

        @fb
        class Painter:
            color: int = 0

            def logic(self):
                self.color = 1

        proj = project("Test", pous=[Painter], data_types=[Color])
        ir = proj.compile()
        type_names = [dt.name for dt in ir.data_types]
        assert "Color" in type_names


# ===========================================================================
# 3. Optional logic() for data-only FBs
# ===========================================================================

class TestOptionalLogic:
    def test_data_only_fb(self):
        """@fb without logic() should compile with empty networks."""
        @fb
        class Config:
            max_speed: Input[float]
            timeout: Input[int]
            enabled: Output[bool]

        pou = Config.compile()
        assert pou.name == "Config"
        assert pou.networks == []
        assert len(pou.interface.input_vars) == 2
        assert len(pou.interface.output_vars) == 1

    def test_data_only_fb_with_methods(self):
        """Methods should still compile on data-only FBs."""
        @fb
        class DataBlock:
            value: float = 0.0

            @method
            def reset(self):
                self.value = 0.0

        pou = DataBlock.compile()
        assert pou.networks == []
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "reset"

    def test_function_without_logic_raises(self):
        """@function must always have logic() for the return type."""
        with pytest.raises(CompileError, match="must have a logic"):
            @function
            class BadFunc:
                x: Input[float]

    def test_program_without_logic(self):
        """@program without logic() should compile with empty body."""
        @program
        class EmptyMain:
            running: Output[bool]

        pou = EmptyMain.compile()
        assert pou.networks == []
        assert len(pou.interface.output_vars) == 1

    def test_data_only_fb_as_static_var(self):
        """A data-only FB should be usable as a static var type."""
        @fb
        class Params:
            max_speed: float = 100.0
            accel: float = 10.0

        @fb
        class Motor:
            params: Params

            def logic(self):
                pass

        pou = Motor.compile()
        static_names = [v.name for v in pou.interface.static_vars]
        assert "params" in static_names

    def test_data_only_fb_simulation(self):
        """Simulating a data-only FB should be a no-op scan."""
        @fb
        class Config:
            speed: float = 50.0
            enabled: bool = True

        ctx = simulate(Config)
        # Can read defaults
        assert ctx.speed == 50.0
        assert ctx.enabled is True
        # Scan is a no-op
        ctx.scan()
        assert ctx.speed == 50.0
        # Can set and read back
        ctx.speed = 75.0
        ctx.scan()
        assert ctx.speed == 75.0


# ===========================================================================
# 4. Annotated metadata support
# ===========================================================================

class TestAnnotatedMetadata:
    def test_annotated_input_with_default(self):
        """Annotated[Input[bool], Field(description=...)] = True"""
        @fb
        class Sensor:
            prox: Annotated[Input[bool], Field(description="Proximity sensor")] = True

            def logic(self):
                pass

        pou = Sensor.compile()
        var = pou.interface.input_vars[0]
        assert var.name == "prox"
        assert var.description == "Proximity sensor"
        assert var.initial_value == "TRUE"

    def test_annotated_output_with_retain_and_default(self):
        """Annotated[Output[float], Field(retain=True)] = 60.0"""
        @fb
        class Heater:
            setpoint: Annotated[Output[float], Field(retain=True)] = 60.0

            def logic(self):
                pass

        pou = Heater.compile()
        var = pou.interface.output_vars[0]
        assert var.name == "setpoint"
        assert var.retain is True
        assert var.initial_value == "60.0"

    def test_field_initial_overrides_default(self):
        """Field(initial=X) should win over class default."""
        @fb
        class Override:
            val: Annotated[Input[bool], Field(initial=False)] = True

            def logic(self):
                pass

        pou = Override.compile()
        var = pou.interface.input_vars[0]
        assert var.initial_value == "FALSE"  # Field(initial=) wins

    def test_annotated_bare_type_is_static(self):
        """Annotated[bool, Field(retain=True)] → static var with metadata."""
        @fb
        class Latch:
            saved: Annotated[bool, Field(retain=True)]

            def logic(self):
                pass

        pou = Latch.compile()
        var = pou.interface.static_vars[0]
        assert var.name == "saved"
        assert var.retain is True

    def test_multiple_fields_raises(self):
        """Multiple Field() in Annotated should raise TypeError."""
        with pytest.raises(DeclarationError, match="multiple Field"):
            @fb
            class Bad:
                x: Annotated[Input[bool], Field(retain=True), Field(description="dup")]

                def logic(self):
                    pass

    def test_annotated_temp_with_retain_raises(self):
        """Temp variables cannot use retain."""
        with pytest.raises(DeclarationError, match="cannot use retain"):
            @fb
            class Bad:
                x: Annotated[Temp[int], Field(retain=True)]

                def logic(self):
                    pass

    def test_non_field_metadata_ignored(self):
        """Non-Field metadata in Annotated should be silently ignored."""
        @fb
        class WithMeta:
            x: Annotated[Input[bool], "some doc string", 42] = True

            def logic(self):
                pass

        pou = WithMeta.compile()
        var = pou.interface.input_vars[0]
        assert var.name == "x"
        assert var.initial_value == "TRUE"

    def test_plain_input_still_works(self):
        """Plain Input[bool] without Annotated should still work."""
        @fb
        class Plain:
            x: Input[bool]

            def logic(self):
                pass

        pou = Plain.compile()
        assert len(pou.interface.input_vars) == 1

    def test_annotated_global_vars(self):
        """Annotated should work in @global_vars."""
        from plx.framework import global_vars

        @global_vars
        class IO:
            motor_run: Annotated[bool, Field(description="Motor run output")] = False
            speed: Annotated[float, Field(retain=True)] = 50.0

        gvl = IO.compile()
        motor = next(v for v in gvl.variables if v.name == "motor_run")
        assert motor.description == "Motor run output"
        assert motor.initial_value == "FALSE"

        speed = next(v for v in gvl.variables if v.name == "speed")
        assert speed.retain is True
        assert speed.initial_value == "50.0"

    def test_annotated_no_default(self):
        """Annotated with Field but no class default."""
        @fb
        class NoDef:
            sensor: Annotated[Input[bool], Field(description="No default sensor")]

            def logic(self):
                pass

        pou = NoDef.compile()
        var = pou.interface.input_vars[0]
        assert var.description == "No default sensor"
        assert var.initial_value is None

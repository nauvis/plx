"""End-to-end integration tests: framework-compiled POUs + simulator."""

import pytest

from datetime import timedelta

from plx.framework import (
    ARRAY,
    BOOL,
    DINT,
    INT,
    REAL,
    count_down,
    count_up,
    delayed,
    enumeration,
    fb,
    fb_property,
    falling,
    first_scan,
    function,
    Input,
    Output,
    program,
    pulse,
    reset_dominant,
    rising,
    set_dominant,
    Static,
    struct,
    sustained,
    Temp,
    Field,
)
from plx.simulate import simulate


# ---------------------------------------------------------------------------
# Canonical example: motor starts after delay
# ---------------------------------------------------------------------------

class TestMotorStartsAfterDelay:
    def test_canonical(self):
        @fb
        class Motor:
            cmd: Input[BOOL]
            running: Output[BOOL]

            def logic(self):
                self.running = delayed(self.cmd, timedelta(seconds=5))

        ctrl = simulate(Motor)
        ctrl.cmd = True
        ctrl.scan()
        assert not ctrl.running
        ctrl.tick(seconds=5)
        assert ctrl.running

    def test_reset_on_cmd_false(self):
        @fb
        class Motor2:
            cmd: Input[BOOL]
            running: Output[BOOL]

            def logic(self):
                self.running = delayed(self.cmd, timedelta(seconds=2))

        ctrl = simulate(Motor2)
        ctrl.cmd = True
        ctrl.tick(seconds=1)
        assert not ctrl.running
        ctrl.cmd = False
        ctrl.scan()
        assert not ctrl.running


# ---------------------------------------------------------------------------
# Edge detection
# ---------------------------------------------------------------------------

class TestEdgeDetection:
    def test_rising_edge(self):
        @fb
        class RisingTest:
            signal: Input[BOOL]
            detected: Output[BOOL]

            def logic(self):
                self.detected = rising(self.signal)

        ctx = simulate(RisingTest)
        ctx.signal = True
        ctx.scan()
        assert ctx.detected is True
        ctx.scan()
        assert ctx.detected is False

    def test_falling_edge(self):
        @fb
        class FallingTest:
            signal: Input[BOOL]
            detected: Output[BOOL]

            def logic(self):
                self.detected = falling(self.signal)

        ctx = simulate(FallingTest)
        ctx.signal = True
        ctx.scan()
        assert ctx.detected is False
        ctx.signal = False
        ctx.scan()
        assert ctx.detected is True
        ctx.scan()
        assert ctx.detected is False


# ---------------------------------------------------------------------------
# Counter: static var persistence
# ---------------------------------------------------------------------------

class TestCounter:
    def test_counter_increments(self):
        @fb
        class Counter:
            count: Output[INT]

            def logic(self):
                self.count = self.count + 1

        ctx = simulate(Counter)
        ctx.scan()
        assert ctx.count == 1
        ctx.scan()
        assert ctx.count == 2
        ctx.scan(n=8)
        assert ctx.count == 10


# ---------------------------------------------------------------------------
# Nested user-defined FB
# ---------------------------------------------------------------------------

class TestNestedUserFB:
    def test_nested_fb(self):
        @fb
        class Doubler:
            x: Input[INT]
            result: Output[INT]

            def logic(self):
                self.result = self.x * 2

        @fb
        class Outer:
            val: Input[INT]
            doubled: Output[INT]
            dbl: Doubler

            def logic(self):
                self.dbl(x=self.val)
                self.doubled = self.dbl.result

        ctx = simulate(Outer, pous=[Doubler])
        ctx.val = 7
        ctx.scan()
        assert ctx.doubled == 14


# ---------------------------------------------------------------------------
# For loop
# ---------------------------------------------------------------------------

class TestForLoop:
    def test_for_loop_sum(self):
        @fb
        class Summer:
            n: Input[INT]
            total: Output[INT]

            def logic(self):
                self.total = 0
                for i in range(1, self.n + 1):
                    self.total = self.total + i

        ctx = simulate(Summer)
        ctx.n = 5
        ctx.scan()
        assert ctx.total == 15  # 1+2+3+4+5


# ---------------------------------------------------------------------------
# Case (match) statement
# ---------------------------------------------------------------------------

class TestCaseStatement:
    def test_case_dispatch(self):
        @fb
        class Dispatcher:
            mode: Input[INT]
            result: Output[INT]

            def logic(self):
                match self.mode:
                    case 1:
                        self.result = 10
                    case 2:
                        self.result = 20
                    case 3:
                        self.result = 30
                    case _:
                        self.result = -1

        ctx = simulate(Dispatcher)
        ctx.mode = 2
        ctx.scan()
        assert ctx.result == 20

        ctx.mode = 99
        ctx.scan()
        assert ctx.result == -1


# ---------------------------------------------------------------------------
# If/elsif/else
# ---------------------------------------------------------------------------

class TestIfElsifElse:
    def test_branches(self):
        @fb
        class Classifier:
            value: Input[INT]
            category: Output[INT]

            def logic(self):
                if self.value < 0:
                    self.category = -1
                elif self.value == 0:
                    self.category = 0
                else:
                    self.category = 1

        ctx = simulate(Classifier)

        ctx.value = -5
        ctx.scan()
        assert ctx.category == -1

        ctx.value = 0
        ctx.scan()
        assert ctx.category == 0

        ctx.value = 10
        ctx.scan()
        assert ctx.category == 1


# ---------------------------------------------------------------------------
# While loop
# ---------------------------------------------------------------------------

class TestWhileLoop:
    def test_while(self):
        @fb
        class WhileTest:
            result: Output[INT]

            def logic(self):
                self.result = 1
                while self.result < 100:
                    self.result = self.result * 2

        ctx = simulate(WhileTest)
        ctx.scan()
        assert ctx.result == 128  # 1->2->4->8->16->32->64->128


# ---------------------------------------------------------------------------
# Array access
# ---------------------------------------------------------------------------

class TestArrayAccess:
    def test_array_read_write(self):
        @fb
        class ArrayTest:
            data: ARRAY(INT, 5)
            result: Output[INT]

            def logic(self):
                self.data[0] = 10
                self.data[1] = 20
                self.data[2] = 30
                self.result = self.data[0] + self.data[1] + self.data[2]

        ctx = simulate(ArrayTest)
        ctx.scan()
        assert ctx.result == 60


# ---------------------------------------------------------------------------
# Struct member access
# ---------------------------------------------------------------------------

class TestStructMemberAccess:
    def test_struct_read_write(self):
        @struct
        class MotorData:
            speed: REAL = 0.0
            running: BOOL = False

        @fb
        class StructTest:
            data: MotorData
            out_speed: Output[REAL]

            def logic(self):
                self.data.speed = 75.5
                self.data.running = True
                self.out_speed = self.data.speed

        ctx = simulate(StructTest, data_types=[MotorData])
        ctx.scan()
        assert ctx.out_speed == pytest.approx(75.5)


# ---------------------------------------------------------------------------
# Sustained timer (TOF)
# ---------------------------------------------------------------------------

class TestSustainedTimer:
    def test_sustained(self):
        @fb
        class SustainedTest:
            trigger: Input[BOOL]
            output: Output[BOOL]

            def logic(self):
                self.output = sustained(self.trigger, timedelta(seconds=1))

        ctx = simulate(SustainedTest)
        ctx.trigger = True
        ctx.scan()
        assert ctx.output is True
        ctx.trigger = False
        ctx.scan()
        assert ctx.output is True  # sustained for 1s
        ctx.tick(seconds=1)
        assert ctx.output is False


# ---------------------------------------------------------------------------
# Pulse timer (TP)
# ---------------------------------------------------------------------------

class TestPulseTimer:
    def test_pulse(self):
        @fb
        class PulseTest:
            trigger: Input[BOOL]
            output: Output[BOOL]

            def logic(self):
                self.output = pulse(self.trigger, timedelta(milliseconds=500))

        ctx = simulate(PulseTest)
        ctx.trigger = True
        ctx.scan()
        assert ctx.output is True
        ctx.tick(ms=500)
        assert ctx.output is False


# ---------------------------------------------------------------------------
# Arithmetic expressions
# ---------------------------------------------------------------------------

class TestArithmeticExpressions:
    def test_arithmetic(self):
        @fb
        class MathTest:
            a: Input[INT]
            b: Input[INT]
            sum_val: Output[INT]
            diff: Output[INT]
            prod: Output[INT]
            quot: Output[INT]
            neg: Output[INT]

            def logic(self):
                self.sum_val = self.a + self.b
                self.diff = self.a - self.b
                self.prod = self.a * self.b
                self.quot = self.a / self.b
                self.neg = -self.a

        ctx = simulate(MathTest)
        ctx.a = 10
        ctx.b = 3
        ctx.scan()
        assert ctx.sum_val == 13
        assert ctx.diff == 7
        assert ctx.prod == 30
        assert ctx.quot == 3
        assert ctx.neg == -10


# ---------------------------------------------------------------------------
# Type conversion
# ---------------------------------------------------------------------------

class TestTypeConversion:
    def test_int_to_real(self):
        @fb
        class ConvertTest:
            x: Input[INT]
            y: Output[REAL]

            def logic(self):
                self.y = INT_TO_REAL(self.x)

        ctx = simulate(ConvertTest)
        ctx.x = 42
        ctx.scan()
        assert ctx.y == pytest.approx(42.0)
        assert isinstance(ctx.y, float)


# ---------------------------------------------------------------------------
# Function calls
# ---------------------------------------------------------------------------

class TestFunctionCalls:
    def test_abs_min_max(self):
        @fb
        class FuncTest:
            a: Input[INT]
            b: Input[INT]
            abs_a: Output[INT]
            min_ab: Output[INT]
            max_ab: Output[INT]

            def logic(self):
                self.abs_a = abs(self.a)
                self.min_ab = min(self.a, self.b)
                self.max_ab = max(self.a, self.b)

        ctx = simulate(FuncTest)
        ctx.a = -5
        ctx.b = 3
        ctx.scan()
        assert ctx.abs_a == 5
        assert ctx.min_ab == -5
        assert ctx.max_ab == 3


# ---------------------------------------------------------------------------
# Program POU
# ---------------------------------------------------------------------------

class TestProgramPOU:
    def test_program(self):
        @program
        class Main:
            running: Input[BOOL]
            status: Output[INT]

            def logic(self):
                if self.running:
                    self.status = 1
                else:
                    self.status = 0

        ctx = simulate(Main)
        ctx.running = True
        ctx.scan()
        assert ctx.status == 1


# ---------------------------------------------------------------------------
# first_scan() system flag
# ---------------------------------------------------------------------------

class TestFirstScanIntegration:
    def test_first_scan_sets_init_flag(self):
        @program
        class InitProgram:
            initialized: Output[BOOL]

            def logic(self):
                if first_scan():
                    self.initialized = True

        ctx = simulate(InitProgram)
        assert not ctx.initialized

        # First scan: first_scan() is True → sets initialized
        ctx.scan()
        assert ctx.initialized

        # Reset and scan again: first_scan() is False
        ctx.initialized = False
        ctx.scan()
        assert not ctx.initialized

    def test_first_scan_counter(self):
        @fb
        class ScanCounter:
            count: Output[INT]

            def logic(self):
                if first_scan():
                    self.count = 100
                self.count = self.count + 1

        ctx = simulate(ScanCounter)
        # First scan: first_scan() is True → count = 100, then +1 = 101
        ctx.scan()
        assert ctx.count == 101

        # Second scan: first_scan() is False → count = 101 + 1 = 102
        ctx.scan()
        assert ctx.count == 102


# ---------------------------------------------------------------------------
# Count up (CTU)
# ---------------------------------------------------------------------------

class TestCountUp:
    def test_count_up_basic(self):
        @fb
        class CountTest:
            trigger: Input[BOOL]
            done: Output[BOOL]

            def logic(self):
                self.done = count_up(self.trigger, preset=3)

        ctx = simulate(CountTest)
        # 3 rising edges
        for _ in range(3):
            ctx.trigger = True
            ctx.scan()
            ctx.trigger = False
            ctx.scan()
        assert ctx.done is True


# ---------------------------------------------------------------------------
# Count down (CTD)
# ---------------------------------------------------------------------------

class TestCountDown:
    def test_count_down_basic(self):
        @fb
        class CountDownTest:
            trigger: Input[BOOL]
            done: Output[BOOL]

            def logic(self):
                self.done = count_down(self.trigger, preset=2)

        ctx = simulate(CountDownTest)
        # First edge: CV goes from 0 to -1, Q = CV <= 0 → True
        ctx.trigger = True
        ctx.scan()
        assert ctx.done is True


# ---------------------------------------------------------------------------
# Set dominant (SR)
# ---------------------------------------------------------------------------

class TestSetDominant:
    def test_set_dominant_basic(self):
        @fb
        class SRTest:
            s: Input[BOOL]
            r: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                self.out = set_dominant(self.s, self.r)

        ctx = simulate(SRTest)
        ctx.s = True
        ctx.r = True
        ctx.scan()
        assert ctx.out is True  # set-dominant

        ctx.s = False
        ctx.scan()
        assert ctx.out is False  # reset wins when no set


# ---------------------------------------------------------------------------
# Reset dominant (RS)
# ---------------------------------------------------------------------------

class TestResetDominant:
    def test_reset_dominant_basic(self):
        @fb
        class RSTest:
            s: Input[BOOL]
            r: Input[BOOL]
            out: Output[BOOL]

            def logic(self):
                self.out = reset_dominant(self.s, self.r)

        ctx = simulate(RSTest)
        ctx.s = True
        ctx.r = True
        ctx.scan()
        assert ctx.out is False  # reset-dominant

        ctx.r = False
        ctx.scan()
        assert ctx.out is True  # set wins when no reset


# ---------------------------------------------------------------------------
# Property getter/setter (integration)
# ---------------------------------------------------------------------------

class TestPropertyIntegration:
    def test_property_getter_setter(self):
        @fb
        class MotorProp:
            _speed: Static[REAL]

            @fb_property(REAL)
            def speed(self):
                return self._speed

            @speed.setter
            def speed(self, value: REAL):
                self._speed = value

            def logic(self):
                pass

        @fb
        class Controller:
            m: MotorProp
            out: Output[REAL]

            def logic(self):
                self.m.speed = 75.5
                self.out = self.m.speed

        ctx = simulate(Controller, pous=[MotorProp])
        ctx.scan()
        assert ctx.out == pytest.approx(75.5)


# ---------------------------------------------------------------------------
# Enum values return IntEnum members
# ---------------------------------------------------------------------------

class TestEnumIntEnumReturns:
    def test_enum_literal_returns_intenum(self):
        """Enum literals in POU logic resolve to IntEnum members."""
        from enum import IntEnum

        @enumeration
        class Color:
            RED = 0
            GREEN = 1
            BLUE = 2

        @fb
        class ColorPicker:
            out: Output[DINT]

            def logic(self):
                self.out = Color.GREEN

        ctx = simulate(ColorPicker, data_types=[Color])
        ctx.scan()
        assert ctx.out == 1
        assert isinstance(ctx.out, IntEnum)
        assert ctx.out.name == "GREEN"

    def test_enum_default_is_intenum(self):
        """Enum-typed variable defaults are IntEnum members."""
        from enum import IntEnum

        @enumeration
        class MachineState:
            IDLE = 0
            RUNNING = 1
            FAULTED = 2

        @fb
        class Machine:
            state: Static[MachineState]

            def logic(self):
                pass

        ctx = simulate(Machine, data_types=[MachineState])
        # Before any scan, the default should be first member as IntEnum
        assert ctx.state == 0
        assert isinstance(ctx.state, IntEnum)
        assert ctx.state.name == "IDLE"

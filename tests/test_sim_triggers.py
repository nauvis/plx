"""Tests for ScanTrigger — compositional scan-loop builder."""

import pytest

from plx.model.expressions import BinaryExpr, BinaryOp, LiteralExpr, VariableRef
from plx.model.pou import POU, Network, POUInterface, POUType
from plx.model.statements import Assignment
from plx.model.types import PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable
from plx.simulate import SimulationTimeout, simulate


def _int_type():
    return PrimitiveTypeRef(type=PrimitiveType.DINT)


def _bool_type():
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _real_type():
    return PrimitiveTypeRef(type=PrimitiveType.REAL)


def make_counter_pou():
    """A simple POU: count := count + 1 every scan."""
    return POU(
        name="Counter",
        pou_type=POUType.FUNCTION_BLOCK,
        interface=POUInterface(
            output_vars=[Variable(name="count", data_type=_int_type())],
        ),
        networks=[
            Network(
                statements=[
                    Assignment(
                        target=VariableRef(name="count"),
                        value=BinaryExpr(
                            op=BinaryOp.ADD,
                            left=VariableRef(name="count"),
                            right=LiteralExpr(value="1", data_type=_int_type()),
                        ),
                    ),
                ]
            ),
        ],
    )


def make_threshold_pou():
    """A POU: count increments each scan; done := (count >= 5)."""
    return POU(
        name="Threshold",
        pou_type=POUType.FUNCTION_BLOCK,
        interface=POUInterface(
            output_vars=[
                Variable(name="count", data_type=_int_type()),
                Variable(name="done", data_type=_bool_type()),
            ],
        ),
        networks=[
            Network(
                statements=[
                    Assignment(
                        target=VariableRef(name="count"),
                        value=BinaryExpr(
                            op=BinaryOp.ADD,
                            left=VariableRef(name="count"),
                            right=LiteralExpr(value="1", data_type=_int_type()),
                        ),
                    ),
                    Assignment(
                        target=VariableRef(name="done"),
                        value=BinaryExpr(
                            op=BinaryOp.GE,
                            left=VariableRef(name="count"),
                            right=LiteralExpr(value="5", data_type=_int_type()),
                        ),
                    ),
                ]
            ),
        ],
    )


class TestScanTriggerRepeat:
    def test_repeat_n(self):
        ctx = simulate(make_counter_pou())
        trace = ctx.scans().repeat(10).run()
        assert ctx.count == 10
        # Without sampling, trace is empty
        assert len(trace) == 0

    def test_repeat_with_sample(self):
        ctx = simulate(make_counter_pou())
        trace = ctx.scans().repeat(5).sample("count").run()
        assert trace.values_of("count") == [1, 2, 3, 4, 5]

    def test_repeat_with_sample_all(self):
        ctx = simulate(make_counter_pou())
        trace = ctx.scans().repeat(3).sample_all().run()
        assert len(trace) == 3
        assert trace.values_of("count") == [1, 2, 3]


class TestScanTriggerUntil:
    def test_until_condition(self):
        ctx = simulate(make_threshold_pou())
        ctx.scans().until(lambda c: c.done).timeout(seconds=1).run()
        assert ctx.done
        assert ctx.count == 5

    def test_until_with_sample(self):
        ctx = simulate(make_threshold_pou())
        trace = ctx.scans().until(lambda c: c.done).timeout(seconds=1).sample("count").run()
        counts = trace.values_of("count")
        assert counts[-1] == 5
        assert len(counts) == 5


class TestScanTriggerChanged:
    def test_changed_detects_change(self):
        """changed() should stop when a variable's value changes."""
        pou = make_counter_pou()
        ctx = simulate(pou)
        # count starts at 0, first scan changes it to 1
        trace = ctx.scans().changed("count").timeout(seconds=1).sample("count").run()
        assert ctx.count == 1
        assert len(trace) == 1


class TestScanTriggerTimeout:
    def test_timeout_only(self):
        """timeout-only trigger runs for the specified simulated time."""
        ctx = simulate(make_counter_pou(), scan_period_ms=10)
        trace = ctx.scans().timeout(ms=50).sample("count").run()
        assert len(trace) == 5
        assert ctx.count == 5

    def test_timeout_raises_on_unmet_condition(self):
        """until() + timeout raises SimulationTimeout if condition never met."""
        ctx = simulate(make_counter_pou())
        with pytest.raises(SimulationTimeout):
            ctx.scans().until(lambda c: c.count > 9999).timeout(ms=100).run()

    def test_timeout_positive_required(self):
        ctx = simulate(make_counter_pou())
        with pytest.raises(ValueError):
            ctx.scans().timeout(ms=0)


class TestScanTriggerNoTermination:
    def test_no_termination_raises(self):
        ctx = simulate(make_counter_pou())
        with pytest.raises(ValueError, match="no termination condition"):
            ctx.scans().run()

    def test_sample_alone_raises(self):
        ctx = simulate(make_counter_pou())
        with pytest.raises(ValueError, match="no termination condition"):
            ctx.scans().sample("count").run()


class TestScanUntilConvenience:
    def test_scan_until(self):
        ctx = simulate(make_threshold_pou())
        ctx.scan_until(lambda c: c.done, timeout_seconds=1)
        assert ctx.done
        assert ctx.count == 5

    def test_scan_until_timeout_raises(self):
        ctx = simulate(make_counter_pou(), scan_period_ms=10)
        with pytest.raises(SimulationTimeout):
            ctx.scan_until(lambda c: c.count > 9999, timeout_seconds=0.1)


class TestScanTriggerImmutability:
    def test_builder_returns_new_instance(self):
        ctx = simulate(make_counter_pou())
        t1 = ctx.scans()
        t2 = t1.repeat(10)
        t3 = t1.until(lambda c: c.count > 5)
        assert t1 is not t2
        assert t1 is not t3
        assert t2 is not t3


class TestTickWithTrace:
    def test_tick_trace_false(self):
        ctx = simulate(make_counter_pou(), scan_period_ms=10)
        result = ctx.tick(ms=50)
        assert result is None
        assert ctx.count == 5

    def test_tick_trace_true(self):
        ctx = simulate(make_counter_pou(), scan_period_ms=10)
        trace = ctx.tick(ms=50, trace=True)
        assert trace is not None
        assert len(trace) == 5
        assert trace.values_of("count") == [1, 2, 3, 4, 5]

    def test_tick_trace_zero_time(self):
        ctx = simulate(make_counter_pou())
        result = ctx.tick(seconds=0, trace=True)
        assert result is not None
        assert len(result) == 0

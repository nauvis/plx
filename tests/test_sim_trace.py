"""Tests for ScanTrace and ScanSnapshot — waveform capture."""

import pytest

from plx.simulate._trace import ScanSnapshot, ScanTrace


class TestScanSnapshot:
    def test_immutable(self):
        snap = ScanSnapshot(clock_ms=100, values={"x": 1})
        with pytest.raises(AttributeError):
            snap.clock_ms = 200

    def test_active_steps_default(self):
        snap = ScanSnapshot(clock_ms=0, values={})
        assert snap.active_steps == frozenset()

    def test_active_steps(self):
        snap = ScanSnapshot(
            clock_ms=0,
            values={},
            active_steps=frozenset({"s1", "s2"}),
        )
        assert snap.active_steps == frozenset({"s1", "s2"})


class TestScanTrace:
    def test_empty(self):
        trace = ScanTrace()
        assert len(trace) == 0
        assert trace.values_of("x") == []
        assert trace.to_dict() == {"__clock_ms": []}

    def test_values_of(self):
        trace = ScanTrace()
        trace._snapshots.append(ScanSnapshot(clock_ms=0, values={"x": 1, "y": 10}))
        trace._snapshots.append(ScanSnapshot(clock_ms=10, values={"x": 2, "y": 20}))
        trace._snapshots.append(ScanSnapshot(clock_ms=20, values={"x": 3, "y": 30}))

        assert trace.values_of("x") == [1, 2, 3]
        assert trace.values_of("y") == [10, 20, 30]
        assert trace.values_of("missing") == [None, None, None]

    def test_to_dict(self):
        trace = ScanTrace()
        trace._snapshots.append(ScanSnapshot(clock_ms=0, values={"a": 1}))
        trace._snapshots.append(ScanSnapshot(clock_ms=10, values={"a": 2}))

        d = trace.to_dict()
        assert d["__clock_ms"] == [0, 10]
        assert d["a"] == [1, 2]

    def test_snapshots_returns_copy(self):
        trace = ScanTrace()
        trace._snapshots.append(ScanSnapshot(clock_ms=0, values={}))
        snaps = trace.snapshots
        snaps.clear()
        assert len(trace) == 1

    def test_indexing(self):
        trace = ScanTrace()
        trace._snapshots.append(ScanSnapshot(clock_ms=0, values={"x": 1}))
        trace._snapshots.append(ScanSnapshot(clock_ms=10, values={"x": 2}))
        assert trace[0].values["x"] == 1
        assert trace[1].values["x"] == 2

    def test_repr(self):
        trace = ScanTrace()
        assert "0 snapshots" in repr(trace)
        trace._snapshots.append(ScanSnapshot(clock_ms=0, values={}))
        assert "1 snapshots" in repr(trace)

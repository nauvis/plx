"""Tests for timedelta_to_iec() and timedelta_to_ir() helpers."""

from datetime import timedelta

from plx.framework import TIME, LTIME, timedelta_to_iec, timedelta_to_ir
from plx.model.expressions import LiteralExpr
from plx.model.types import PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# timedelta_to_iec() — TIME (default)
# ---------------------------------------------------------------------------

class TestTimedeltaToIec:
    def test_seconds(self):
        assert timedelta_to_iec(timedelta(seconds=5)) == "T#5s"

    def test_milliseconds(self):
        assert timedelta_to_iec(timedelta(milliseconds=500)) == "T#500ms"

    def test_microseconds(self):
        assert timedelta_to_iec(timedelta(microseconds=250)) == "T#250us"

    def test_minutes(self):
        assert timedelta_to_iec(timedelta(minutes=2)) == "T#2m"

    def test_hours(self):
        assert timedelta_to_iec(timedelta(hours=1)) == "T#1h"

    def test_composite(self):
        assert timedelta_to_iec(timedelta(hours=1, minutes=30, seconds=15, milliseconds=500)) == "T#1h30m15s500ms"

    def test_minutes_and_seconds(self):
        assert timedelta_to_iec(timedelta(minutes=1, seconds=30)) == "T#1m30s"

    def test_zero(self):
        assert timedelta_to_iec(timedelta()) == "T#0s"
        assert timedelta_to_iec(timedelta(0)) == "T#0s"

    def test_fractional_seconds(self):
        assert timedelta_to_iec(timedelta(seconds=0.5)) == "T#500ms"

    def test_fractional_seconds_with_ms(self):
        assert timedelta_to_iec(timedelta(seconds=1.5)) == "T#1s500ms"

    def test_large_values(self):
        td = timedelta(hours=24, minutes=59, seconds=59, milliseconds=999)
        assert timedelta_to_iec(td) == "T#24h59m59s999ms"

    def test_days_decompose_to_hours(self):
        assert timedelta_to_iec(timedelta(days=1)) == "T#24h"

    def test_weeks_decompose_to_hours(self):
        assert timedelta_to_iec(timedelta(weeks=1)) == "T#168h"


# ---------------------------------------------------------------------------
# timedelta_to_iec() — LTIME
# ---------------------------------------------------------------------------

class TestTimedeltaToIecLtime:
    def test_seconds(self):
        assert timedelta_to_iec(timedelta(seconds=5), ltime=True) == "LTIME#5s"

    def test_milliseconds(self):
        assert timedelta_to_iec(timedelta(milliseconds=100), ltime=True) == "LTIME#100ms"

    def test_microseconds(self):
        assert timedelta_to_iec(timedelta(microseconds=250), ltime=True) == "LTIME#250us"

    def test_composite(self):
        td = timedelta(seconds=5, milliseconds=100, microseconds=42)
        assert timedelta_to_iec(td, ltime=True) == "LTIME#5s100ms42us"

    def test_zero(self):
        assert timedelta_to_iec(timedelta(0), ltime=True) == "LTIME#0s"


# ---------------------------------------------------------------------------
# timedelta_to_ir()
# ---------------------------------------------------------------------------

class TestTimedeltaToIr:
    def test_produces_literal_expr(self):
        ir = timedelta_to_ir(timedelta(seconds=5))
        assert isinstance(ir, LiteralExpr)

    def test_value_is_iec_string(self):
        ir = timedelta_to_ir(timedelta(seconds=5))
        assert ir.value == "T#5s"

    def test_data_type_is_time(self):
        ir = timedelta_to_ir(timedelta(seconds=5))
        assert ir.data_type == PrimitiveTypeRef(type=PrimitiveType.TIME)

    def test_ltime_data_type(self):
        ir = timedelta_to_ir(timedelta(seconds=5), ltime=True)
        assert ir.data_type == PrimitiveTypeRef(type=PrimitiveType.LTIME)
        assert ir.value == "LTIME#5s"

    def test_composite_ir(self):
        ir = timedelta_to_ir(timedelta(minutes=1, seconds=30))
        assert ir.value == "T#1m30s"
        assert ir.data_type == PrimitiveTypeRef(type=PrimitiveType.TIME)

    def test_ir_serializes(self):
        ir = timedelta_to_ir(timedelta(seconds=5))
        d = ir.model_dump()
        assert d["kind"] == "literal"
        assert d["value"] == "T#5s"


# ---------------------------------------------------------------------------
# Primitive type constants
# ---------------------------------------------------------------------------

class TestPrimitiveTypeConstants:
    def test_time_is_primitive_type(self):
        assert TIME == PrimitiveType.TIME

    def test_ltime_is_primitive_type(self):
        assert LTIME == PrimitiveType.LTIME

    def test_all_primitive_types_exported(self):
        from plx.framework import (
            BOOL, BYTE, WORD, DWORD, LWORD,
            SINT, INT, DINT, LINT,
            USINT, UINT, UDINT, ULINT,
            REAL, LREAL,
            TIME, LTIME,
            DATE, LDATE, TOD, LTOD, DT, LDT,
            CHAR, WCHAR,
        )
        assert BOOL == PrimitiveType.BOOL
        assert INT == PrimitiveType.INT
        assert REAL == PrimitiveType.REAL
        assert DINT == PrimitiveType.DINT


# ---------------------------------------------------------------------------
# timedelta re-export from framework
# ---------------------------------------------------------------------------

class TestTimedeltaReexport:
    def test_timedelta_available_from_framework(self):
        from plx.framework import timedelta as td
        assert td is timedelta

    def test_timedelta_in_all(self):
        import plx.framework
        assert "timedelta" in plx.framework.__all__

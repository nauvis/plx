"""Tests for simulator value system."""

import pytest

from plx.model.types import PrimitiveType, PrimitiveTypeRef, StringTypeRef, NamedTypeRef
from plx.simulate._values import (
    SimulationError,
    coerce_type,
    parse_literal,
    type_default,
)


# ---------------------------------------------------------------------------
# parse_literal
# ---------------------------------------------------------------------------

class TestParseLiteral:
    def test_true(self):
        assert parse_literal("TRUE") is True

    def test_false(self):
        assert parse_literal("FALSE") is False

    def test_true_lowercase(self):
        assert parse_literal("true") is True

    def test_integer(self):
        assert parse_literal("42") == 42
        assert isinstance(parse_literal("42"), int)

    def test_negative_integer(self):
        assert parse_literal("-7") == -7

    def test_zero(self):
        assert parse_literal("0") == 0

    def test_float(self):
        assert parse_literal("3.14") == pytest.approx(3.14)
        assert isinstance(parse_literal("3.14"), float)

    def test_negative_float(self):
        assert parse_literal("-1.5") == pytest.approx(-1.5)

    def test_time_seconds(self):
        assert parse_literal("T#5s") == 5000

    def test_time_milliseconds(self):
        assert parse_literal("T#100ms") == 100

    def test_time_compound(self):
        assert parse_literal("T#1h30m15s500ms") == (1 * 3600000 + 30 * 60000 + 15000 + 500)

    def test_time_prefix_variants(self):
        assert parse_literal("TIME#1s") == 1000
        assert parse_literal("LTIME#1s") == 1000
        assert parse_literal("LT#1s") == 1000

    def test_time_zero(self):
        assert parse_literal("T#0s") == 0

    def test_time_minutes(self):
        assert parse_literal("T#2m") == 120000

    def test_time_hours(self):
        assert parse_literal("T#1h") == 3600000

    def test_quoted_string(self):
        assert parse_literal("'hello'") == "hello"

    def test_empty_string(self):
        assert parse_literal("''") == ""

    def test_enum_literal(self):
        from enum import IntEnum
        MachineState = IntEnum("MachineState", {"RUNNING": 1, "STOPPED": 0})
        registry = {"MachineState": MachineState}
        result = parse_literal("MachineState#RUNNING", enum_registry=registry)
        assert result == 1
        assert isinstance(result, IntEnum)
        assert result.name == "RUNNING"

    def test_enum_unknown_raises(self):
        with pytest.raises(SimulationError, match="Cannot resolve enum"):
            parse_literal("Unknown#VALUE")

    def test_with_float_type_hint(self):
        dtype = PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert isinstance(parse_literal("0", data_type=dtype), float)

    def test_with_int_type_hint(self):
        dtype = PrimitiveTypeRef(type=PrimitiveType.INT)
        assert isinstance(parse_literal("42", data_type=dtype), int)

    # --- DATE/TOD/DT literals ---

    def test_date_literal(self):
        result = parse_literal("DATE#2024-01-15")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_date_d_prefix(self):
        result = parse_literal("D#2024-06-01")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_ldate_literal(self):
        result = parse_literal("LDATE#2024-01-15")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_tod_literal(self):
        result = parse_literal("TOD#14:30:00")
        assert result == 14 * 3_600_000 + 30 * 60_000

    def test_tod_with_fraction(self):
        result = parse_literal("TOD#14:30:00.500")
        assert result == 14 * 3_600_000 + 30 * 60_000 + 500

    def test_ltod_literal(self):
        result = parse_literal("LTOD#01:00:00")
        assert result == 3_600_000

    def test_time_of_day_prefix(self):
        result = parse_literal("TIME_OF_DAY#12:00:00")
        assert result == 12 * 3_600_000

    def test_dt_literal(self):
        result = parse_literal("DT#2024-01-15-14:30:00")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_ldt_literal(self):
        result = parse_literal("LDT#2024-01-15-14:30:00")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_date_and_time_prefix(self):
        result = parse_literal("DATE_AND_TIME#2024-06-01-00:00:00")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_dt_with_fraction(self):
        result = parse_literal("DT#2024-01-15-14:30:00.250")
        from datetime import datetime, timezone
        expected = int(datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000) + 250
        assert result == expected


# ---------------------------------------------------------------------------
# type_default
# ---------------------------------------------------------------------------

class TestTypeDefault:
    def test_bool(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.BOOL)) is False

    def test_int(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.INT)) == 0
        assert isinstance(type_default(PrimitiveTypeRef(type=PrimitiveType.INT)), int)

    def test_dint(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.DINT)) == 0

    def test_real(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.REAL)) == 0.0
        assert isinstance(type_default(PrimitiveTypeRef(type=PrimitiveType.REAL)), float)

    def test_lreal(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.LREAL)) == 0.0

    def test_time(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.TIME)) == 0

    def test_string(self):
        assert type_default(StringTypeRef()) == ""

    def test_date(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.DATE)) == 0

    def test_tod(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.TOD)) == 0

    def test_dt(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.DT)) == 0

    def test_ldt(self):
        assert type_default(PrimitiveTypeRef(type=PrimitiveType.LDT)) == 0

    def test_named_returns_none(self):
        assert type_default(NamedTypeRef(name="SomeFB")) is None


# ---------------------------------------------------------------------------
# coerce_type
# ---------------------------------------------------------------------------

class TestCoerceType:
    def test_int_to_float(self):
        result = coerce_type(42, PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert result == 42.0
        assert isinstance(result, float)

    def test_float_to_int_truncates(self):
        result = coerce_type(3.7, PrimitiveTypeRef(type=PrimitiveType.INT))
        assert result == 3
        assert isinstance(result, int)

    def test_negative_float_to_int_truncates_toward_zero(self):
        result = coerce_type(-3.7, PrimitiveTypeRef(type=PrimitiveType.INT))
        assert result == -3

    def test_bool_to_int(self):
        assert coerce_type(True, PrimitiveTypeRef(type=PrimitiveType.INT)) == 1
        assert coerce_type(False, PrimitiveTypeRef(type=PrimitiveType.INT)) == 0

    def test_int_to_bool(self):
        assert coerce_type(1, PrimitiveTypeRef(type=PrimitiveType.BOOL)) is True
        assert coerce_type(0, PrimitiveTypeRef(type=PrimitiveType.BOOL)) is False

    def test_passthrough_for_named_type(self):
        assert coerce_type(42, NamedTypeRef(name="MyType")) == 42

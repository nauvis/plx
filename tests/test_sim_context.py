"""Tests for the simulation context."""

import pytest

from conftest import make_pou, ptype
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    LiteralExpr,
    VariableRef,
)
from plx.model.pou import POU, POUInterface, POUType
from plx.model.statements import Assignment
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PrimitiveType,
    StringTypeRef,
    StructMember,
    StructType,
)
from plx.model.variables import Variable
from plx.simulate._context import SimulationContext

# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


class TestAllocation:
    def test_bool_default(self):
        pou = make_pou(
            input_vars=[
                Variable(name="flag", data_type=ptype(PrimitiveType.BOOL)),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.flag is False

    def test_int_default(self):
        pou = make_pou(
            input_vars=[
                Variable(name="count", data_type=ptype(PrimitiveType.INT)),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.count == 0

    def test_real_default(self):
        pou = make_pou(
            output_vars=[
                Variable(name="speed", data_type=ptype(PrimitiveType.REAL)),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.speed == 0.0

    def test_initial_value(self):
        pou = make_pou(
            static_vars=[
                Variable(name="x", data_type=ptype(PrimitiveType.INT), initial_value="42"),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.x == 42

    def test_string_default(self):
        pou = make_pou(
            input_vars=[
                Variable(name="msg", data_type=StringTypeRef()),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.msg == ""

    def test_array_allocation(self):
        pou = make_pou(
            static_vars=[
                Variable(
                    name="arr",
                    data_type=ArrayTypeRef(
                        element_type=ptype(PrimitiveType.INT),
                        dimensions=[DimensionRange(lower=0, upper=4)],
                    ),
                ),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.arr == [0, 0, 0, 0, 0]

    def test_builtin_fb_allocation(self):
        pou = make_pou(
            static_vars=[
                Variable(name="timer", data_type=NamedTypeRef(name="TON")),
            ]
        )
        ctx = SimulationContext(pou)
        assert isinstance(ctx.timer, dict)
        assert "Q" in ctx.timer
        assert "ET" in ctx.timer

    def test_struct_allocation(self):
        struct_def = StructType(
            name="MotorData",
            members=[
                StructMember(name="speed", data_type=ptype(PrimitiveType.REAL)),
                StructMember(name="running", data_type=ptype(PrimitiveType.BOOL)),
            ],
        )
        pou = make_pou(
            static_vars=[
                Variable(name="data", data_type=NamedTypeRef(name="MotorData")),
            ]
        )
        ctx = SimulationContext(pou, data_type_registry={"MotorData": struct_def})
        assert ctx.data == {"speed": 0.0, "running": False}

    def test_user_fb_allocation(self):
        inner_pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Inner",
            interface=POUInterface(
                input_vars=[Variable(name="x", data_type=ptype(PrimitiveType.INT))],
                output_vars=[Variable(name="y", data_type=ptype(PrimitiveType.INT))],
            ),
            networks=[],
        )
        pou = make_pou(
            static_vars=[
                Variable(name="inner", data_type=NamedTypeRef(name="Inner")),
            ]
        )
        ctx = SimulationContext(pou, pou_registry={"Inner": inner_pou})
        assert isinstance(ctx.inner, dict)
        assert ctx.inner["x"] == 0
        assert ctx.inner["y"] == 0


# ---------------------------------------------------------------------------
# Attribute access
# ---------------------------------------------------------------------------


class TestAttributeAccess:
    def test_read_input(self):
        pou = make_pou(
            input_vars=[
                Variable(name="cmd", data_type=ptype(PrimitiveType.BOOL)),
            ]
        )
        ctx = SimulationContext(pou)
        assert ctx.cmd is False

    def test_write_input(self):
        pou = make_pou(
            input_vars=[
                Variable(name="cmd", data_type=ptype(PrimitiveType.BOOL)),
            ]
        )
        ctx = SimulationContext(pou)
        ctx.cmd = True
        assert ctx.cmd is True

    def test_unknown_var_raises(self):
        pou = make_pou(
            input_vars=[
                Variable(name="x", data_type=ptype(PrimitiveType.INT)),
            ]
        )
        ctx = SimulationContext(pou)
        with pytest.raises(AttributeError, match="no variable 'nonexistent'"):
            _ = ctx.nonexistent


# ---------------------------------------------------------------------------
# Scan / tick
# ---------------------------------------------------------------------------


class TestScan:
    def test_scan_advances_clock(self):
        pou = make_pou()
        ctx = SimulationContext(pou, scan_period_ms=10)
        assert ctx.clock_ms == 0
        ctx.scan()
        assert ctx.clock_ms == 10
        ctx.scan()
        assert ctx.clock_ms == 20

    def test_scan_multiple(self):
        pou = make_pou()
        ctx = SimulationContext(pou, scan_period_ms=5)
        ctx.scan(n=10)
        assert ctx.clock_ms == 50

    def test_tick_computes_scans(self):
        pou = make_pou()
        ctx = SimulationContext(pou, scan_period_ms=10)
        ctx.tick(seconds=1)
        assert ctx.clock_ms == 1000

    def test_tick_rounds_up(self):
        pou = make_pou()
        ctx = SimulationContext(pou, scan_period_ms=10)
        ctx.tick(ms=15)
        assert ctx.clock_ms == 20  # ceil(15/10) = 2 scans

    def test_tick_ms_param(self):
        pou = make_pou()
        ctx = SimulationContext(pou, scan_period_ms=10)
        ctx.tick(ms=100)
        assert ctx.clock_ms == 100

    def test_static_vars_persist(self):
        pou = make_pou(
            stmts=[
                Assignment(
                    target=VariableRef(name="count"),
                    value=BinaryExpr(
                        op=BinaryOp.ADD,
                        left=VariableRef(name="count"),
                        right=LiteralExpr(value="1"),
                    ),
                ),
            ],
            static_vars=[
                Variable(name="count", data_type=ptype(PrimitiveType.INT)),
            ],
        )
        ctx = SimulationContext(pou)
        ctx.scan()
        assert ctx.count == 1
        ctx.scan()
        assert ctx.count == 2
        ctx.scan()
        assert ctx.count == 3

    def test_temp_vars_reset(self):
        pou = make_pou(
            stmts=[
                # temp_val should be 0 each scan, then we assign it
                Assignment(
                    target=VariableRef(name="result"),
                    value=VariableRef(name="temp_val"),
                ),
                Assignment(
                    target=VariableRef(name="temp_val"),
                    value=LiteralExpr(value="42"),
                ),
            ],
            output_vars=[
                Variable(name="result", data_type=ptype(PrimitiveType.INT)),
            ],
            temp_vars=[
                Variable(name="temp_val", data_type=ptype(PrimitiveType.INT)),
            ],
        )
        ctx = SimulationContext(pou)
        ctx.scan()
        assert ctx.result == 0  # temp_val was reset to 0 before scan
        ctx.scan()
        assert ctx.result == 0  # temp_val reset again

    def test_logic_executes(self):
        pou = make_pou(
            stmts=[
                Assignment(
                    target=VariableRef(name="out"),
                    value=VariableRef(name="inp"),
                ),
            ],
            input_vars=[
                Variable(name="inp", data_type=ptype(PrimitiveType.BOOL)),
            ],
            output_vars=[
                Variable(name="out", data_type=ptype(PrimitiveType.BOOL)),
            ],
        )
        ctx = SimulationContext(pou)
        ctx.inp = True
        ctx.scan()
        assert ctx.out is True


# ---------------------------------------------------------------------------
# Timedelta coercion
# ---------------------------------------------------------------------------


class TestTimedeltaCoercion:
    def test_setattr_coerces_timedelta(self):
        """Setting a TIME variable via timedelta stores int milliseconds."""
        from datetime import timedelta

        pou = make_pou(
            input_vars=[
                Variable(name="delay", data_type=ptype(PrimitiveType.TIME)),
            ]
        )
        ctx = SimulationContext(pou)
        ctx.delay = timedelta(seconds=10)
        assert ctx.delay == 10000

    def test_set_method_coerces_timedelta(self):
        from datetime import timedelta

        pou = make_pou(
            input_vars=[
                Variable(name="timeout", data_type=ptype(PrimitiveType.TIME)),
            ]
        )
        ctx = SimulationContext(pou)
        ctx.set(timeout=timedelta(milliseconds=500))
        assert ctx.timeout == 500

    def test_set_external_coerces_timedelta(self):
        from datetime import timedelta

        pou = make_pou(
            static_vars=[
                Variable(name="ext_time", data_type=ptype(PrimitiveType.TIME)),
            ]
        )
        ctx = SimulationContext(pou)
        ctx.set_external("ext_time", timedelta(seconds=2))
        assert ctx.ext_time == 2000

    def test_struct_proxy_setattr_coerces_timedelta(self):
        from datetime import timedelta

        from plx.simulate._proxy import StructProxy

        d = {"pt": 0}
        proxy = StructProxy(d)
        proxy.pt = timedelta(seconds=5)
        assert d["pt"] == 5000

    def test_struct_proxy_setitem_coerces_timedelta(self):
        from datetime import timedelta

        from plx.simulate._proxy import StructProxy

        d = {"pt": 0}
        proxy = StructProxy(d)
        proxy["pt"] = timedelta(seconds=3)
        assert d["pt"] == 3000

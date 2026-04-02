"""Tests for the simulate() entry point."""

import pytest

from conftest import ptype
from plx.model.pou import POU, POUInterface, POUType
from plx.model.types import (
    EnumMember,
    EnumType,
    PrimitiveType,
    StructMember,
    StructType,
)
from plx.model.variables import Variable
from plx.simulate import SimulationContext, simulate


def _simple_pou(name="TestFB"):
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name=name,
        interface=POUInterface(
            input_vars=[Variable(name="x", data_type=ptype(PrimitiveType.BOOL))],
            output_vars=[Variable(name="y", data_type=ptype(PrimitiveType.BOOL))],
        ),
        networks=[],
    )


class TestSimulateAPI:
    def test_accepts_pou_ir(self):
        pou = _simple_pou()
        ctx = simulate(pou)
        assert isinstance(ctx, SimulationContext)

    def test_accepts_decorated_class(self):
        # Simulate a @fb class by attaching _compiled_pou + compile()
        class FakeFB:
            _compiled_pou = _simple_pou()

            @classmethod
            def compile(cls):
                return cls._compiled_pou

        ctx = simulate(FakeFB)
        assert isinstance(ctx, SimulationContext)

    def test_rejects_invalid(self):
        with pytest.raises(TypeError, match="simulate\\(\\) expects"):
            simulate(42)

    def test_pous_registry(self):
        inner = _simple_pou(name="InnerFB")
        outer = _simple_pou(name="OuterFB")
        ctx = simulate(outer, pous=[inner])
        # InnerFB should be resolvable
        assert "InnerFB" in ctx._pou_registry

    def test_data_types_registry(self):
        struct_def = StructType(
            name="MyStruct",
            members=[StructMember(name="val", data_type=ptype(PrimitiveType.INT))],
        )
        pou = _simple_pou()
        ctx = simulate(pou, data_types=[struct_def])
        assert "MyStruct" in ctx._data_type_registry

    def test_enum_registry(self):
        from enum import IntEnum

        enum_def = EnumType(
            name="Color",
            members=[
                EnumMember(name="RED", value=0),
                EnumMember(name="GREEN", value=1),
            ],
        )
        pou = _simple_pou()
        ctx = simulate(pou, data_types=[enum_def])
        enum_cls = ctx._enum_registry["Color"]
        assert issubclass(enum_cls, IntEnum)
        assert enum_cls["RED"] == 0
        assert enum_cls["GREEN"] == 1

    def test_scan_period(self):
        pou = _simple_pou()
        ctx = simulate(pou, scan_period_ms=5)
        ctx.scan()
        assert ctx.clock_ms == 5

    def test_data_types_rejects_invalid(self):
        pou = _simple_pou()
        with pytest.raises(TypeError, match="data_types entries"):
            simulate(pou, data_types=[42])

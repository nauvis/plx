"""Tests for pointer/reference simulation support."""

import pytest

from plx.model.expressions import (
    CallArg,
    DerefExpr,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    VariableRef,
)
from plx.model.pou import POU, Network, POUInterface, POUType
from plx.model.statements import Assignment, FunctionCallStatement
from plx.model.types import (
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StructMember,
    StructType,
)
from plx.model.variables import Variable
from plx.simulate._executor import ExecutionEngine
from plx.simulate._pointers import NULL_PTR, PointerTable, _RefBinding
from plx.simulate._values import SimulationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dint() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.DINT)


def _bool() -> PrimitiveTypeRef:
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _ptr(target: str) -> PointerTypeRef:
    return PointerTypeRef(target_type=NamedTypeRef(name=target))


def _ptr_dint() -> PointerTypeRef:
    return PointerTypeRef(target_type=_dint())


def _make_engine(state, pointer_table=None, pou=None):
    if pou is None:
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestPOU",
            interface=POUInterface(),
            networks=[],
        )
    return ExecutionEngine(
        pou=pou,
        state=state,
        clock_ms=0,
        pointer_table=pointer_table,
    )


# ---------------------------------------------------------------------------
# PointerTable unit tests
# ---------------------------------------------------------------------------


class TestPointerTable:
    def test_get_or_assign_returns_stable_address(self):
        pt = PointerTable()
        state = {"x": 42}
        addr1 = pt.get_or_assign("x", state, "x")
        addr2 = pt.get_or_assign("x", state, "x")
        assert addr1 == addr2
        assert isinstance(addr1, int)
        assert addr1 != 0

    def test_read_write(self):
        pt = PointerTable()
        state = {"x": 10}
        addr = pt.get_or_assign("x", state, "x")
        assert pt.read(addr) == 10
        pt.write(addr, 99)
        assert state["x"] == 99
        assert pt.read(addr) == 99

    def test_null_deref_raises(self):
        pt = PointerTable()
        with pytest.raises(SimulationError, match="Null pointer"):
            pt.read(NULL_PTR)

    def test_invalid_addr_raises(self):
        pt = PointerTable()
        with pytest.raises(SimulationError, match="Invalid pointer"):
            pt.read(0xDEAD)

    def test_heap_alloc_and_read(self):
        pt = PointerTable()
        addr = pt.heap_alloc({"field": 0})
        assert addr != 0
        val = pt.read(addr)
        assert val == {"field": 0}

    def test_heap_free(self):
        pt = PointerTable()
        addr = pt.heap_alloc(42)
        pt.heap_free(addr)
        with pytest.raises(SimulationError, match="Use after free"):
            pt.read(addr)

    def test_double_free_raises(self):
        pt = PointerTable()
        addr = pt.heap_alloc(0)
        pt.heap_free(addr)
        with pytest.raises(SimulationError, match="Double free"):
            pt.heap_free(addr)

    def test_free_non_heap_raises(self):
        pt = PointerTable()
        state = {"x": 0}
        addr = pt.get_or_assign("x", state, "x")
        with pytest.raises(SimulationError, match="not allocated by __NEW"):
            pt.heap_free(addr)

    def test_is_valid(self):
        pt = PointerTable()
        state = {"x": 0}
        addr = pt.get_or_assign("x", state, "x")
        assert pt.is_valid(addr)
        assert not pt.is_valid(NULL_PTR)
        assert not pt.is_valid(0xDEAD)

    def test_is_valid_after_free(self):
        pt = PointerTable()
        addr = pt.heap_alloc(0)
        assert pt.is_valid(addr)
        pt.heap_free(addr)
        assert not pt.is_valid(addr)


# ---------------------------------------------------------------------------
# ADR and basic dereference
# ---------------------------------------------------------------------------


class TestAdrAndDeref:
    def test_adr_returns_address(self):
        pt = PointerTable()
        state = {"x": 42, "ptr": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="x", data_type=_dint()),
                    Variable(name="ptr", data_type=_ptr_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        # ptr := ADR(x)
                        Assignment(
                            target=VariableRef(name="ptr"),
                            value=FunctionCallExpr(
                                function_name="ADR",
                                args=[CallArg(value=VariableRef(name="x"))],
                            ),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert isinstance(state["ptr"], int)
        assert state["ptr"] != 0

    def test_deref_reads_value(self):
        """ptr := ADR(x); result := ptr^  →  result == x"""
        pt = PointerTable()
        state = {"x": 42, "ptr": 0, "result": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="x", data_type=_dint()),
                    Variable(name="ptr", data_type=_ptr_dint()),
                    Variable(name="result", data_type=_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ptr"),
                            value=FunctionCallExpr(
                                function_name="ADR",
                                args=[CallArg(value=VariableRef(name="x"))],
                            ),
                        ),
                        Assignment(
                            target=VariableRef(name="result"),
                            value=DerefExpr(pointer=VariableRef(name="ptr")),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["result"] == 42

    def test_deref_writes_value(self):
        """ptr := ADR(x); ptr^ := 99  →  x == 99"""
        pt = PointerTable()
        state = {"x": 0, "ptr": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="x", data_type=_dint()),
                    Variable(name="ptr", data_type=_ptr_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ptr"),
                            value=FunctionCallExpr(
                                function_name="ADR",
                                args=[CallArg(value=VariableRef(name="x"))],
                            ),
                        ),
                        Assignment(
                            target=DerefExpr(pointer=VariableRef(name="ptr")),
                            value=LiteralExpr(value="99"),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["x"] == 99

    def test_deref_struct_member(self):
        """ptr := ADR(s); result := ptr^.field"""
        pt = PointerTable()
        state = {"s": {"field": 42}, "ptr": 0, "result": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="s", data_type=NamedTypeRef(name="MyStruct")),
                    Variable(name="ptr", data_type=_ptr("MyStruct")),
                    Variable(name="result", data_type=_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ptr"),
                            value=FunctionCallExpr(
                                function_name="ADR",
                                args=[CallArg(value=VariableRef(name="s"))],
                            ),
                        ),
                        Assignment(
                            target=VariableRef(name="result"),
                            value=MemberAccessExpr(
                                struct=DerefExpr(pointer=VariableRef(name="ptr")),
                                member="field",
                            ),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["result"] == 42

    def test_null_deref_raises(self):
        pt = PointerTable()
        state = {"ptr": 0}
        engine = _make_engine(state, pt)
        with pytest.raises(SimulationError, match="Null pointer"):
            engine._eval_deref(DerefExpr(pointer=VariableRef(name="ptr")))


# ---------------------------------------------------------------------------
# Pointer arithmetic rejection
# ---------------------------------------------------------------------------


class TestPointerArithmeticRejection:
    def test_arithmetic_deref_raises(self):
        """ptr := ADR(x) + 1; ptr^  → raises"""
        pt = PointerTable()
        state = {"x": 42, "ptr": 0}
        addr = pt.get_or_assign("x", state, "x")
        state["ptr"] = addr + 1  # offset by 1 — not in table
        engine = _make_engine(state, pt)
        with pytest.raises(SimulationError, match="pointer arithmetic"):
            engine._eval_deref(DerefExpr(pointer=VariableRef(name="ptr")))


# ---------------------------------------------------------------------------
# __NEW and __DELETE
# ---------------------------------------------------------------------------


class TestNewDelete:
    def test_new_allocates(self):
        pt = PointerTable()
        state = {"ptr": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[Variable(name="ptr", data_type=_ptr_dint())],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ptr"),
                            value=FunctionCallExpr(
                                function_name="__NEW",
                                args=[CallArg(value=LiteralExpr(value="DINT"))],
                            ),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["ptr"] != 0
        # Should be able to read the allocated value
        assert pt.read(state["ptr"]) == 0  # default for DINT

    def test_new_struct(self):
        my_struct = StructType(
            name="MyNode",
            members=[
                StructMember(name="data", data_type=_dint()),
                StructMember(name="next", data_type=_ptr_dint()),
            ],
        )
        pt = PointerTable()
        state = {"ptr": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[Variable(name="ptr", data_type=_ptr("MyNode"))],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ptr"),
                            value=FunctionCallExpr(
                                function_name="__NEW",
                                args=[CallArg(value=LiteralExpr(value="MyNode"))],
                            ),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.data_type_registry = {"MyNode": my_struct}
        engine.execute()
        val = pt.read(state["ptr"])
        assert isinstance(val, dict)
        assert val["data"] == 0
        assert val["next"] == 0

    def test_delete_frees(self):
        pt = PointerTable()
        addr = pt.heap_alloc(42)
        state = {"ptr": addr}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[Variable(name="ptr", data_type=_ptr_dint())],
            ),
            networks=[
                Network(
                    statements=[
                        FunctionCallStatement(
                            function_name="__DELETE",
                            args=[CallArg(value=VariableRef(name="ptr"))],
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        # Pointer should be set to null after delete
        assert state["ptr"] == 0
        # Dereferencing freed memory should raise
        with pytest.raises(SimulationError, match="Use after free"):
            pt.read(addr)

    def test_delete_null_raises(self):
        pt = PointerTable()
        state = {"ptr": 0}
        engine = _make_engine(state, pt)
        with pytest.raises(SimulationError, match="null pointer"):
            engine._exec_function_call_stmt(
                FunctionCallStatement(
                    function_name="__DELETE",
                    args=[CallArg(value=VariableRef(name="ptr"))],
                )
            )


# ---------------------------------------------------------------------------
# REF= and __ISVALIDREF
# ---------------------------------------------------------------------------


class TestRefAssign:
    def test_ref_assign_read_through(self):
        """ref REF= x; result := ref  →  result == x"""
        pt = PointerTable()
        state = {"x": 42, "ref": 0, "result": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="x", data_type=_dint()),
                    Variable(name="ref", data_type=_dint()),
                    Variable(name="result", data_type=_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ref"),
                            value=VariableRef(name="x"),
                            ref_assign=True,
                        ),
                        Assignment(
                            target=VariableRef(name="result"),
                            value=VariableRef(name="ref"),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["result"] == 42

    def test_ref_assign_write_through(self):
        """ref REF= x; ref := 99  →  x == 99"""
        pt = PointerTable()
        state = {"x": 0, "ref": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="x", data_type=_dint()),
                    Variable(name="ref", data_type=_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ref"),
                            value=VariableRef(name="x"),
                            ref_assign=True,
                        ),
                        Assignment(
                            target=VariableRef(name="ref"),
                            value=LiteralExpr(value="99"),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["x"] == 99

    def test_isvalidref_bound(self):
        pt = PointerTable()
        state = {"x": 42, "ref": 0}
        # Bind ref to x
        addr = pt.get_or_assign("x", state, "x")
        state["ref"] = _RefBinding(addr)
        engine = _make_engine(state, pt)
        result = engine._eval_isvalidref(VariableRef(name="ref"))
        assert result is True

    def test_isvalidref_unbound(self):
        pt = PointerTable()
        state = {"ref": 0}
        engine = _make_engine(state, pt)
        result = engine._eval_isvalidref(VariableRef(name="ref"))
        assert result is False


# ---------------------------------------------------------------------------
# SIZEOF
# ---------------------------------------------------------------------------


class TestSizeof:
    def test_sizeof_dint(self):
        pt = PointerTable()
        state = {"x": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[Variable(name="x", data_type=_dint())],
            ),
            networks=[],
        )
        engine = _make_engine(state, pt, pou)
        result = engine._eval_sizeof(VariableRef(name="x"))
        assert result == 4

    def test_sizeof_bool(self):
        pt = PointerTable()
        state = {"x": False}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[Variable(name="x", data_type=_bool())],
            ),
            networks=[],
        )
        engine = _make_engine(state, pt, pou)
        result = engine._eval_sizeof(VariableRef(name="x"))
        assert result == 1


# ---------------------------------------------------------------------------
# Integration: linked list
# ---------------------------------------------------------------------------


class TestLinkedListIntegration:
    def test_linked_list_create_and_traverse(self):
        """Simulate creating two linked-list nodes and reading through pointers."""
        node_type = StructType(
            name="Node",
            members=[
                StructMember(name="data", data_type=_dint()),
                StructMember(name="next", data_type=_ptr("Node")),
            ],
        )
        pt = PointerTable()
        state = {"head": 0, "tmp": 0, "result": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="head", data_type=_ptr("Node")),
                    Variable(name="tmp", data_type=_ptr("Node")),
                    Variable(name="result", data_type=_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        # head := __NEW(Node)
                        Assignment(
                            target=VariableRef(name="head"),
                            value=FunctionCallExpr(
                                function_name="__NEW",
                                args=[CallArg(value=LiteralExpr(value="Node"))],
                            ),
                        ),
                        # head^.data := 10
                        Assignment(
                            target=MemberAccessExpr(
                                struct=DerefExpr(pointer=VariableRef(name="head")),
                                member="data",
                            ),
                            value=LiteralExpr(value="10"),
                        ),
                        # tmp := __NEW(Node)
                        Assignment(
                            target=VariableRef(name="tmp"),
                            value=FunctionCallExpr(
                                function_name="__NEW",
                                args=[CallArg(value=LiteralExpr(value="Node"))],
                            ),
                        ),
                        # tmp^.data := 20
                        Assignment(
                            target=MemberAccessExpr(
                                struct=DerefExpr(pointer=VariableRef(name="tmp")),
                                member="data",
                            ),
                            value=LiteralExpr(value="20"),
                        ),
                        # head^.next := tmp
                        Assignment(
                            target=MemberAccessExpr(
                                struct=DerefExpr(pointer=VariableRef(name="head")),
                                member="next",
                            ),
                            value=VariableRef(name="tmp"),
                        ),
                        # result := head^.next^.data  (should be 20)
                        # First: tmp2 = head^.next
                        # Then: result = tmp2^.data
                        # As a single expr: MemberAccess(DerefExpr(MemberAccess(DerefExpr(head), "next")), "data")
                        Assignment(
                            target=VariableRef(name="result"),
                            value=MemberAccessExpr(
                                struct=DerefExpr(
                                    pointer=MemberAccessExpr(
                                        struct=DerefExpr(pointer=VariableRef(name="head")),
                                        member="next",
                                    ),
                                ),
                                member="data",
                            ),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.data_type_registry = {"Node": node_type}
        engine.execute()
        assert state["result"] == 20


class TestSwapViaPointers:
    def test_swap(self):
        """Swap two variables using pointer indirection."""
        pt = PointerTable()
        state = {"a": 10, "b": 20, "pa": 0, "pb": 0, "tmp": 0}
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="Test",
            interface=POUInterface(
                static_vars=[
                    Variable(name="a", data_type=_dint()),
                    Variable(name="b", data_type=_dint()),
                    Variable(name="pa", data_type=_ptr_dint()),
                    Variable(name="pb", data_type=_ptr_dint()),
                    Variable(name="tmp", data_type=_dint()),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        # pa := ADR(a); pb := ADR(b)
                        Assignment(
                            target=VariableRef(name="pa"),
                            value=FunctionCallExpr(function_name="ADR", args=[CallArg(value=VariableRef(name="a"))]),
                        ),
                        Assignment(
                            target=VariableRef(name="pb"),
                            value=FunctionCallExpr(function_name="ADR", args=[CallArg(value=VariableRef(name="b"))]),
                        ),
                        # tmp := pa^
                        Assignment(
                            target=VariableRef(name="tmp"),
                            value=DerefExpr(pointer=VariableRef(name="pa")),
                        ),
                        # pa^ := pb^
                        Assignment(
                            target=DerefExpr(pointer=VariableRef(name="pa")),
                            value=DerefExpr(pointer=VariableRef(name="pb")),
                        ),
                        # pb^ := tmp
                        Assignment(
                            target=DerefExpr(pointer=VariableRef(name="pb")),
                            value=VariableRef(name="tmp"),
                        ),
                    ]
                )
            ],
        )
        engine = _make_engine(state, pt, pou)
        engine.execute()
        assert state["a"] == 20
        assert state["b"] == 10

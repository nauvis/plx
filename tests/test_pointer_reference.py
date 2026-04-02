"""Tests for pointer/reference operations (DerefExpr, ADR, REF=)."""

import pytest

from conftest import compile_expr, compile_stmts
from plx.framework._compiler import CompileContext
from plx.framework._descriptors import VarDirection
from plx.model.expressions import (
    DerefExpr,
    FunctionCallExpr,
    MemberAccessExpr,
    VariableRef,
)
from plx.model.statements import Assignment

# ---------------------------------------------------------------------------
# DerefExpr — IR model
# ---------------------------------------------------------------------------


class TestDerefExprModel:
    def test_create(self):
        d = DerefExpr(pointer=VariableRef(name="ptr"))
        assert d.kind == "deref"
        assert isinstance(d.pointer, VariableRef)
        assert d.pointer.name == "ptr"

    def test_nested_deref(self):
        """ptr^^ — double dereference."""
        inner = DerefExpr(pointer=VariableRef(name="ptr"))
        outer = DerefExpr(pointer=inner)
        assert isinstance(outer.pointer, DerefExpr)

    def test_deref_with_member(self):
        """ptr^.member — dereference then member access."""
        d = DerefExpr(pointer=VariableRef(name="ptr"))
        m = MemberAccessExpr(struct=d, member="field")
        assert isinstance(m.struct, DerefExpr)


# ---------------------------------------------------------------------------
# Compiler — .deref syntax
# ---------------------------------------------------------------------------


class TestCompilerDeref:
    def test_self_deref(self):
        """self.ptr.deref → DerefExpr(pointer=VariableRef('ptr'))"""
        ctx = CompileContext(declared_vars={"ptr": VarDirection.STATIC})
        result = compile_expr("self.ptr.deref", ctx)
        assert isinstance(result, DerefExpr)
        assert isinstance(result.pointer, VariableRef)
        assert result.pointer.name == "ptr"

    def test_deref_member(self):
        """self.ptr.deref.field → MemberAccessExpr(struct=DerefExpr(...), member='field')"""
        ctx = CompileContext(declared_vars={"ptr": VarDirection.STATIC})
        result = compile_expr("self.ptr.deref.field", ctx)
        assert isinstance(result, MemberAccessExpr)
        assert result.member == "field"
        assert isinstance(result.struct, DerefExpr)
        assert result.struct.pointer.name == "ptr"

    def test_deref_assignment(self):
        """self.ptr.deref = 42 → Assignment(target=DerefExpr, value=Literal)"""
        ctx = CompileContext(declared_vars={"ptr": VarDirection.STATIC})
        stmts = compile_stmts("self.ptr.deref = 42", ctx)
        assert len(stmts) == 1
        assert isinstance(stmts[0], Assignment)
        assert isinstance(stmts[0].target, DerefExpr)
        assert stmts[0].target.pointer.name == "ptr"


# ---------------------------------------------------------------------------
# Compiler — ADR / SIZEOF
# ---------------------------------------------------------------------------


class TestCompilerADR:
    def test_adr_call(self):
        """ADR(self.x) → FunctionCallExpr('ADR', ...)"""
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        result = compile_expr("ADR(self.x)", ctx)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "ADR"
        assert len(result.args) == 1
        assert isinstance(result.args[0].value, VariableRef)
        assert result.args[0].value.name == "x"

    def test_sizeof_call(self):
        """SIZEOF(self.x) → FunctionCallExpr('SIZEOF', ...)"""
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        result = compile_expr("SIZEOF(self.x)", ctx)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "SIZEOF"


# ---------------------------------------------------------------------------
# Compiler — @= (REF= assignment)
# ---------------------------------------------------------------------------


class TestCompilerRefAssign:
    def test_ref_assign(self):
        """self.ref @= self.x → Assignment(ref_assign=True)"""
        ctx = CompileContext(
            declared_vars={
                "ref": VarDirection.STATIC,
                "x": VarDirection.STATIC,
            }
        )
        stmts = compile_stmts("self.ref @= self.x", ctx)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, Assignment)
        assert stmt.ref_assign is True
        assert isinstance(stmt.target, VariableRef)
        assert stmt.target.name == "ref"
        assert isinstance(stmt.value, VariableRef)
        assert stmt.value.name == "x"


# ---------------------------------------------------------------------------
# ST exporter
# ---------------------------------------------------------------------------


class TestSTExport:
    def test_deref(self):
        from plx.export.st import format_expression

        d = DerefExpr(pointer=VariableRef(name="ptr"))
        assert format_expression(d) == "ptr^"

    def test_deref_member(self):
        from plx.export.st import format_expression

        d = DerefExpr(pointer=VariableRef(name="ptr"))
        m = MemberAccessExpr(struct=d, member="field")
        assert format_expression(m) == "ptr^.field"

    def test_ref_assign(self):
        from plx.export.st import format_statement

        stmt = Assignment(
            target=VariableRef(name="ref"),
            value=VariableRef(name="x"),
            ref_assign=True,
        )
        assert "REF=" in format_statement(stmt)


# ---------------------------------------------------------------------------
# Python exporter
# ---------------------------------------------------------------------------


class TestPyExport:
    def _expr(self, expr):
        # Import via framework to avoid circular import
        from plx.export.py import PyWriter

        w = PyWriter()
        return w._expr(expr)

    def _stmt(self, stmt):
        from plx.export.py import PyWriter

        w = PyWriter()
        w._write_assignment(stmt)
        return w.getvalue().strip()

    def test_deref(self):
        d = DerefExpr(pointer=VariableRef(name="self.ptr"))
        assert self._expr(d) == "self.ptr.deref"

    def test_deref_member(self):
        d = DerefExpr(pointer=VariableRef(name="ptr"))
        m = MemberAccessExpr(struct=d, member="field")
        assert self._expr(m) == "ptr.deref.field"

    def test_ref_assign(self):
        stmt = Assignment(
            target=VariableRef(name="self.ref"),
            value=VariableRef(name="self.x"),
            ref_assign=True,
        )
        result = self._stmt(stmt)
        assert "@=" in result


# ---------------------------------------------------------------------------
# Vendor validation
# ---------------------------------------------------------------------------


class TestVendorValidation:
    def test_deref_rejected_for_ab(self):
        from plx.framework._vendor import Vendor, VendorValidationError, validate_target
        from plx.model.pou import POU, Network, POUInterface, POUType

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=DerefExpr(pointer=VariableRef(name="ptr")),
                            value=VariableRef(name="x"),
                        ),
                    ]
                )
            ],
        )
        from plx.model.project import Project

        proj = Project(name="Test", pous=[pou])
        with pytest.raises(VendorValidationError, match="pointer dereference"):
            validate_target(proj, Vendor.AB)

    def test_ref_assign_rejected_for_siemens(self):
        from plx.framework._vendor import Vendor, VendorValidationError, validate_target
        from plx.model.pou import POU, Network, POUInterface, POUType

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=VariableRef(name="ref"),
                            value=VariableRef(name="x"),
                            ref_assign=True,
                        ),
                    ]
                )
            ],
        )
        from plx.model.project import Project

        proj = Project(name="Test", pous=[pou])
        with pytest.raises(VendorValidationError, match="REF="):
            validate_target(proj, Vendor.SIEMENS)

    def test_adr_rejected_for_ab(self):
        from plx.framework._vendor import Vendor, VendorValidationError, validate_target
        from plx.model.expressions import CallArg
        from plx.model.pou import POU, Network, POUInterface, POUType
        from plx.model.statements import FunctionCallStatement

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(),
            networks=[
                Network(
                    statements=[
                        FunctionCallStatement(
                            function_name="ADR",
                            args=[CallArg(value=VariableRef(name="x"))],
                        ),
                    ]
                )
            ],
        )
        from plx.model.project import Project

        proj = Project(name="Test", pous=[pou])
        with pytest.raises(VendorValidationError, match="ADR"):
            validate_target(proj, Vendor.AB)

    def test_beckhoff_allows_all(self):
        from plx.framework._vendor import Vendor, validate_target
        from plx.model.pou import POU, Network, POUInterface, POUType

        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(),
            networks=[
                Network(
                    statements=[
                        Assignment(
                            target=DerefExpr(pointer=VariableRef(name="ptr")),
                            value=VariableRef(name="x"),
                        ),
                        Assignment(
                            target=VariableRef(name="ref"),
                            value=VariableRef(name="x"),
                            ref_assign=True,
                        ),
                    ]
                )
            ],
        )
        from plx.model.project import Project

        proj = Project(name="Test", pous=[pou])
        # Should not raise — Beckhoff supports all pointer operations
        validate_target(proj, Vendor.BECKHOFF)


# ---------------------------------------------------------------------------
# Simulation — pointer ops raise SimulationError
# ---------------------------------------------------------------------------


class TestSimulationDeref:
    def test_deref_raises_without_pointer_table(self):
        from plx.simulate._executor import ExecutionEngine
        from plx.simulate._values import SimulationError

        engine = ExecutionEngine.__new__(ExecutionEngine)
        engine.state = {}
        engine.pointer_table = None
        with pytest.raises(SimulationError, match="Pointer dereference"):
            engine._eval_deref(DerefExpr(pointer=VariableRef(name="ptr")))

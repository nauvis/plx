"""Shared test helpers for the plx test suite."""

import ast
import textwrap

import pytest

from plx.framework._compiler import ASTCompiler, CompileContext
from plx.framework._registry import _snapshot_registries, _restore_registries
from plx.model.pou import Network, POU, POUInterface, POUType
from plx.model.types import PrimitiveTypeRef
from plx.model.variables import Variable


@pytest.fixture(autouse=True)
def _registry_isolation():
    """Snapshot registries before each test and restore after.

    Prevents cross-test pollution from @fb/@struct decorations while
    preserving module-level registrations that exist at import time.
    """
    snapshot = _snapshot_registries()
    yield
    _restore_registries(snapshot)


def compile_stmts(source: str, ctx: CompileContext | None = None) -> list:
    """Compile Python source (as if inside a logic() body) into IR statements."""
    if ctx is None:
        ctx = CompileContext()
    source = textwrap.dedent(source)
    wrapped = f"def logic(self):\n" + textwrap.indent(source, "    ")
    tree = ast.parse(wrapped)
    func_def = tree.body[0]
    compiler = ASTCompiler(ctx)
    return compiler.compile_body(func_def)


def compile_expr(source: str, ctx: CompileContext | None = None):
    """Compile a single Python expression string to an IR expression."""
    if ctx is None:
        ctx = CompileContext()
    tree = ast.parse(source, mode="eval")
    compiler = ASTCompiler(ctx)
    return compiler.compile_expression(tree.body)


def make_pou(stmts=None, **iface_kwargs):
    """Build a POU with given statements and interface kwargs."""
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name="TestPOU",
        interface=POUInterface(**iface_kwargs),
        networks=[Network(statements=stmts or [])],
    )


def ptype(p):
    """Shorthand for PrimitiveTypeRef(type=p)."""
    return PrimitiveTypeRef(type=p)

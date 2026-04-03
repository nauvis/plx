"""Shared test helpers for the plx test suite."""

import ast
import textwrap

import pytest
from hypothesis import HealthCheck, settings

# ---------------------------------------------------------------------------
# Hypothesis profiles — selected via HYPOTHESIS_PROFILE env var
# ---------------------------------------------------------------------------
# default: fast local dev (what's in each test's @settings)
# ci: moderate bump for push-to-main fuzz job (~5x default)
# nightly: aggressive exploration for overnight runs (~10x default)
settings.register_profile("default", max_examples=100)
settings.register_profile(
    "ci",
    max_examples=500,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=2000,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
import os

_profile = os.environ.get("HYPOTHESIS_PROFILE", "default")
settings.load_profile(_profile)

from plx.framework._compiler import ASTCompiler
from plx.framework._compiler_core import CompileContext
from plx.framework._registry import _restore_registries, _snapshot_registries
from plx.model.pou import POU, Network, POUInterface, POUType
from plx.model.types import PrimitiveTypeRef


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
    wrapped = "def logic(self):\n" + textwrap.indent(source, "    ")
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

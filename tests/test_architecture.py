"""Architectural health tests.

These tests characterize known architectural issues in the codebase.
When an issue is fixed, the corresponding test will fail — update it
to assert the corrected behavior.
"""

import ast
import inspect

import pytest

from plx.framework import (
    BOOL,
    DINT,
    INT,
    T,
    count_down,
    count_up,
    fb,
    Input,
    Output,
    reset_dominant,
    set_dominant,
    Field,
)
from plx.simulate import simulate
from plx.simulate._builtins import BUILTIN_FBS
from plx.simulate._values import SimulationError


# ---------------------------------------------------------------------------
# Class 1: Missing builtins — sentinels generate FB types the simulator
# doesn't know about (CTU, CTD, SR, RS).
# ---------------------------------------------------------------------------


class TestMissingBuiltins:
    """Sentinel-generated FB types that are absent from BUILTIN_FBS."""

    def test_ctu_not_in_builtin_fbs(self):
        assert "CTU" not in BUILTIN_FBS

    def test_ctd_not_in_builtin_fbs(self):
        assert "CTD" not in BUILTIN_FBS

    def test_sr_not_in_builtin_fbs(self):
        assert "SR" not in BUILTIN_FBS

    def test_rs_not_in_builtin_fbs(self):
        assert "RS" not in BUILTIN_FBS

    def test_existing_builtins_present(self):
        for name in ("TON", "TOF", "TP", "R_TRIG", "F_TRIG"):
            assert name in BUILTIN_FBS, f"{name} should be in BUILTIN_FBS"

    # -- End-to-end: compiles fine, crashes at scan time --

    def test_count_up_compiles_but_crashes_simulator(self):
        @fb
        class CountUpFB:
            trigger: Input[BOOL]
            done: Output[BOOL]
            _inst: DINT

            def logic(self):
                self.done = count_up(self.trigger, preset=5)

        ctx = simulate(CountUpFB)
        ctx.trigger = True
        with pytest.raises(SimulationError, match="CTU"):
            ctx.scan()

    def test_count_down_compiles_but_crashes_simulator(self):
        @fb
        class CountDownFB:
            trigger: Input[BOOL]
            done: Output[BOOL]
            _inst: DINT

            def logic(self):
                self.done = count_down(self.trigger, preset=5)

        ctx = simulate(CountDownFB)
        ctx.trigger = True
        with pytest.raises(SimulationError, match="CTD"):
            ctx.scan()

    def test_set_dominant_compiles_but_crashes_simulator(self):
        @fb
        class SetDomFB:
            s: Input[BOOL]
            r: Input[BOOL]
            q: Output[BOOL]

            def logic(self):
                self.q = set_dominant(self.s, self.r)

        ctx = simulate(SetDomFB)
        ctx.s = True
        ctx.r = False
        with pytest.raises(SimulationError, match="SR"):
            ctx.scan()

    def test_reset_dominant_compiles_but_crashes_simulator(self):
        @fb
        class ResetDomFB:
            s: Input[BOOL]
            r: Input[BOOL]
            q: Output[BOOL]

            def logic(self):
                self.q = reset_dominant(self.s, self.r)

        ctx = simulate(ResetDomFB)
        ctx.s = True
        ctx.r = False
        with pytest.raises(SimulationError, match="RS"):
            ctx.scan()

    def test_sentinel_fb_types_vs_builtin_registry(self):
        """Programmatically compute all sentinel FB types and diff against BUILTIN_FBS."""
        from plx.framework._compiler_core import (
            _BISTABLE_SENTINELS,
            _COUNTER_SENTINELS,
            _EDGE_SENTINELS,
            _TIMER_SENTINELS,
        )

        # Collect every FB type name from sentinel dicts
        sentinel_fb_types: set[str] = set()

        # Timer/counter/bistable: value is (fb_type, ...)
        for _name, val in _TIMER_SENTINELS.items():
            sentinel_fb_types.add(val[0])
        for _name, val in _COUNTER_SENTINELS.items():
            sentinel_fb_types.add(val[0])
        for _name, val in _BISTABLE_SENTINELS.items():
            sentinel_fb_types.add(val[0])

        # Edge: value is fb_type string directly
        for _name, fb_type in _EDGE_SENTINELS.items():
            sentinel_fb_types.add(fb_type)

        missing = sentinel_fb_types - BUILTIN_FBS.keys()
        assert missing == {"CTU", "CTD", "SR", "RS"}


# ---------------------------------------------------------------------------
# Class 2: Layer violations — imports that cross architectural boundaries.
# ---------------------------------------------------------------------------


class TestLayerViolations:
    """Import violations between framework, export, and simulate layers."""

    def test_framework_reexports_generate_from_export(self):
        import plx.export.py as export_py
        import plx.framework as fw

        assert fw.generate is export_py.generate

    def test_framework_reexports_generate_files_from_export(self):
        import plx.export.py as export_py
        import plx.framework as fw

        assert fw.generate_files is export_py.generate_files

    def test_framework_init_has_export_import_in_source(self):
        """AST-parse framework/__init__.py and find ImportFrom with plx.export.py."""
        import plx.framework as fw

        source = inspect.getsource(fw)
        tree = ast.parse(source)
        export_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "plx.export.py"
        ]
        assert len(export_imports) >= 1

    def test_simulate_imports_from_framework_protocols(self):
        """AST-parse simulate/__init__.py and find ImportFrom with plx.framework._protocols."""
        import plx.simulate

        init_file = inspect.getfile(plx.simulate)
        with open(init_file) as f:
            source = f.read()
        tree = ast.parse(source)
        protocol_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "plx.framework._protocols"
        ]
        assert len(protocol_imports) >= 1

    def test_simulate_uses_framework_protocol_in_resolve_pou(self):
        """_resolve_pou references CompiledPOU from the framework."""
        from plx.simulate import _resolve_pou

        source = inspect.getsource(_resolve_pou)
        assert "CompiledPOU" in source


# ---------------------------------------------------------------------------
# Class 3: Module complexity — _decorators.py has too many responsibilities.
# ---------------------------------------------------------------------------


class TestModuleComplexity:
    """_decorators.py is a 697-line module with 6+ distinct sections."""

    def _get_decorators_source(self) -> str:
        import plx.framework._decorators as mod

        return inspect.getsource(mod)

    def test_decorators_line_count_exceeds_threshold(self):
        source = self._get_decorators_source()
        assert len(source.splitlines()) > 500

    def test_decorators_public_function_count(self):
        """At least 5 top-level public function defs."""
        source = self._get_decorators_source()
        tree = ast.parse(source)
        public_defs = [
            node
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        ]
        assert len(public_defs) >= 5

    def test_decorators_has_many_section_separators(self):
        """Count '# ---...' separator lines (>= 20 chars), expect >= 10."""
        source = self._get_decorators_source()
        separators = [
            line
            for line in source.splitlines()
            if line.strip().startswith("# ---") and len(line.strip()) > 20
        ]
        assert len(separators) >= 10

    def test_comment_extraction_has_zero_framework_deps(self):
        """_extract_comments works on pure string input with no framework imports."""
        from plx.framework._decorators import _extract_comments

        source = '''\
def logic(self):
    # Start motor
    self.running = True
    # Stop motor
    self.running = False
'''
        comments = _extract_comments(source)
        assert isinstance(comments, dict)
        assert len(comments) > 0

    def test_split_body_by_comments_is_pure_ast(self):
        """_split_body_by_comments works with stdlib-only AST inputs."""
        from plx.framework._decorators import (
            _extract_comments,
            _split_body_by_comments,
        )

        source = '''\
def logic(self):
    # Network 1
    x = 1
    # Network 2
    y = 2
'''
        comments = _extract_comments(source)
        tree = ast.parse(source)
        func_def = tree.body[0]
        networks = _split_body_by_comments(func_def, comments)
        assert isinstance(networks, list)
        assert len(networks) >= 2

    def test_all_five_capabilities_in_one_module(self):
        """method, interface, fb, _extract_comments, _compile_pou_class all on one module."""
        import plx.framework._decorators as mod

        for name in ("method", "interface", "fb", "_extract_comments", "_compile_pou_class"):
            assert hasattr(mod, name), f"{name} not found on _decorators module"

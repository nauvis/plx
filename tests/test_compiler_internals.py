"""Tests for compiler core internals: CompileError, CompileContext, resolve_annotation,
enum discovery, parent POU detection, source parsing, var context building."""

import ast

import pytest

from plx.framework._compiler_core import (
    CompileContext,
    CompileError,
    _BIT_ACCESS_RE,
    _TYPE_CONV_RE,
    resolve_annotation,
)
from plx.framework._compilation_helpers import (
    _build_compile_context,
    _build_var_context,
    _detect_parent_pou,
    _discover_enums,
    _parse_function_source,
)
from plx.framework._data_types import enumeration
from plx.framework._decorators import fb
from plx.framework._descriptors import Input, Output, Static, VarDirection
from plx.framework._types import BOOL, DINT, INT, REAL
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# CompileError
# ---------------------------------------------------------------------------

class TestCompileError:
    def test_basic_message(self):
        err = CompileError("something failed")
        assert str(err) == "something failed"
        assert err.source_file == "<unknown>"
        assert err.source_line is None

    def test_with_node_and_context(self):
        """CompileError with node and context includes source location."""
        node = ast.parse("x = 1").body[0]
        node.lineno = 5
        ctx = CompileContext(
            source_file="test.py",
            source_line_offset=10,
        )
        err = CompileError("bad thing", node=node, ctx=ctx)
        assert "test.py:15" in str(err)
        assert err.source_file == "test.py"
        assert err.source_line == 15

    def test_with_node_no_context(self):
        """Node without context doesn't add location."""
        node = ast.parse("x = 1").body[0]
        err = CompileError("bad thing", node=node)
        assert err.source_line is None
        assert "bad thing" in str(err)

    def test_with_context_no_node(self):
        """Context without node doesn't add location."""
        ctx = CompileContext(source_file="test.py", source_line_offset=10)
        err = CompileError("bad thing", ctx=ctx)
        assert err.source_line is None

    def test_node_without_lineno(self):
        """Node without lineno attribute doesn't crash."""
        node = ast.AST()
        ctx = CompileContext(source_file="test.py", source_line_offset=0)
        err = CompileError("bad thing", node=node, ctx=ctx)
        assert err.source_line is None

    def test_is_exception(self):
        assert issubclass(CompileError, Exception)


# ---------------------------------------------------------------------------
# CompileContext
# ---------------------------------------------------------------------------

class TestCompileContext:
    def test_next_auto_name_sequential(self):
        ctx = CompileContext()
        assert ctx.next_auto_name("ton") == "_plx_ton_0"
        assert ctx.next_auto_name("ton") == "_plx_ton_1"
        assert ctx.next_auto_name("ton") == "_plx_ton_2"

    def test_next_auto_name_different_prefixes(self):
        ctx = CompileContext()
        assert ctx.next_auto_name("ton") == "_plx_ton_0"
        assert ctx.next_auto_name("rtrig") == "_plx_rtrig_1"
        assert ctx.next_auto_name("ton") == "_plx_ton_2"

    def test_defaults(self):
        ctx = CompileContext()
        assert ctx.declared_vars == {}
        assert ctx.static_var_types == {}
        assert ctx.generated_static_vars == []
        assert ctx.generated_temp_vars == []
        assert ctx.pending_fb_invocations == []
        assert ctx.pou_class is None
        assert ctx.known_enums == {}
        assert ctx.source_line_offset == 0
        assert ctx.source_file == "<unknown>"

    def test_declared_vars_mutable(self):
        ctx = CompileContext()
        ctx.declared_vars["x"] = VarDirection.INPUT
        assert ctx.declared_vars["x"] == VarDirection.INPUT

    def test_known_enums_lookup(self):
        ctx = CompileContext(
            known_enums={"Color": {"RED": 0, "GREEN": 1, "BLUE": 2}}
        )
        assert ctx.known_enums["Color"]["RED"] == 0
        assert ctx.known_enums["Color"]["BLUE"] == 2


# ---------------------------------------------------------------------------
# resolve_annotation
# ---------------------------------------------------------------------------

class TestResolveAnnotation:
    def test_primitive_type(self):
        ann = ast.Name(id="REAL")
        result = resolve_annotation(ann)
        assert isinstance(result, PrimitiveTypeRef)
        assert result.type == PrimitiveType.REAL

    def test_python_builtin_bool(self):
        ann = ast.Name(id="bool")
        result = resolve_annotation(ann)
        assert isinstance(result, PrimitiveTypeRef)
        assert result.type == PrimitiveType.BOOL

    def test_python_builtin_int(self):
        ann = ast.Name(id="int")
        result = resolve_annotation(ann)
        assert isinstance(result, PrimitiveTypeRef)
        assert result.type == PrimitiveType.INT

    def test_python_builtin_float(self):
        ann = ast.Name(id="float")
        result = resolve_annotation(ann)
        assert isinstance(result, PrimitiveTypeRef)
        assert result.type == PrimitiveType.REAL

    def test_named_type(self):
        ann = ast.Name(id="MyCustomType")
        result = resolve_annotation(ann)
        assert isinstance(result, NamedTypeRef)
        assert result.name == "MyCustomType"

    def test_attribute_annotation(self):
        ann = ast.Attribute(
            value=ast.Name(id="module"),
            attr="SomeType",
        )
        result = resolve_annotation(ann)
        assert isinstance(result, NamedTypeRef)
        assert result.name == "SomeType"

    def test_none_constant(self):
        ann = ast.Constant(value=None)
        result = resolve_annotation(ann)
        assert result is None

    def test_unsupported_raises(self):
        ann = ast.Tuple(elts=[])
        with pytest.raises(CompileError, match="Unsupported type annotation"):
            resolve_annotation(ann)

    def test_unsupported_with_location_hint(self):
        ann = ast.Tuple(elts=[])
        with pytest.raises(CompileError, match="my hint"):
            resolve_annotation(ann, location_hint="my hint")


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

class TestRegexPatterns:
    def test_type_conv_matches(self):
        assert _TYPE_CONV_RE.match("INT_TO_REAL")
        assert _TYPE_CONV_RE.match("DINT_TO_LREAL")
        assert _TYPE_CONV_RE.match("BOOL_TO_INT")

    def test_type_conv_rejects(self):
        assert _TYPE_CONV_RE.match("lower_to_upper") is None
        assert _TYPE_CONV_RE.match("123_TO_456") is None

    def test_bit_access_matches(self):
        assert _BIT_ACCESS_RE.match("bit0")
        assert _BIT_ACCESS_RE.match("bit31")

    def test_bit_access_rejects(self):
        assert _BIT_ACCESS_RE.match("bitX") is None
        assert _BIT_ACCESS_RE.match("bits") is None
        assert _BIT_ACCESS_RE.match("Bit0") is None


# ---------------------------------------------------------------------------
# _discover_enums
# ---------------------------------------------------------------------------

class TestDiscoverEnums:
    def test_discovers_enumeration_from_globals(self):
        """Enums in the module globals should be discovered."""
        @enumeration
        class Direction:
            LEFT = 0
            RIGHT = 1

        # _discover_enums walks func.__globals__
        def logic(self):
            pass

        # Inject the enum into the function's globals
        logic.__globals__["Direction"] = Direction
        try:
            result = _discover_enums(logic)
            assert "Direction" in result
            assert result["Direction"] == {"LEFT": 0, "RIGHT": 1}
        finally:
            del logic.__globals__["Direction"]

    def test_discovers_intenum_from_globals(self):
        """IntEnum in module globals should be discovered."""
        from enum import IntEnum

        class Priority(IntEnum):
            LOW = 0
            HIGH = 1

        def logic(self):
            pass

        logic.__globals__["Priority"] = Priority
        try:
            result = _discover_enums(logic)
            assert "Priority" in result
            assert result["Priority"]["LOW"] == 0
            assert result["Priority"]["HIGH"] == 1
        finally:
            del logic.__globals__["Priority"]

    def test_no_globals_attribute(self):
        """Object without __globals__ returns empty dict."""
        result = _discover_enums(42)
        assert result == {}

    def test_empty_globals(self):
        """Function with no enums in globals returns empty."""
        def bare_func():
            pass

        result = _discover_enums(bare_func)
        # May find module-level enums, but at minimum should not crash
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _detect_parent_pou
# ---------------------------------------------------------------------------

class TestDetectParentPOU:
    def test_no_parent(self):
        class Standalone:
            pass

        assert _detect_parent_pou(Standalone) is None

    def test_with_fb_parent(self):
        @fb
        class BaseFB:
            x: Input[BOOL]

            def logic(self):
                pass

        class ChildFB(BaseFB):
            pass

        assert _detect_parent_pou(ChildFB) == "BaseFB"

    def test_skips_object(self):
        """object in MRO should be skipped."""
        class Simple:
            pass

        assert _detect_parent_pou(Simple) is None

    def test_non_pou_parent_skipped(self):
        """Non-POU parent classes are skipped."""
        class Mixin:
            pass

        class Child(Mixin):
            pass

        assert _detect_parent_pou(Child) is None


# ---------------------------------------------------------------------------
# _parse_function_source
# ---------------------------------------------------------------------------

class TestParseFunctionSource:
    def test_basic_parse(self):
        def logic(self):
            pass

        func_def, source, start = _parse_function_source(logic, "test.logic()")
        assert isinstance(func_def, ast.FunctionDef)
        assert func_def.name == "logic"

    def test_validate_self_only_rejects_extra_params(self):
        def logic(self, x):
            pass

        with pytest.raises(CompileError, match="exactly one parameter"):
            _parse_function_source(logic, "test", validate_self_only=True)

    def test_validate_self_only_rejects_vararg(self):
        def logic(self, *args):
            pass

        with pytest.raises(CompileError, match="only 'self'"):
            _parse_function_source(logic, "test", validate_self_only=True)

    def test_validate_self_only_rejects_kwarg(self):
        def logic(self, **kwargs):
            pass

        with pytest.raises(CompileError, match="only 'self'"):
            _parse_function_source(logic, "test", validate_self_only=True)

    def test_validate_single_return(self):
        def cond(self):
            return self.x

        func_def, _, _ = _parse_function_source(
            cond, "test", validate_self_only=True, validate_single_return=True,
        )
        assert isinstance(func_def.body[0], ast.Return)

    def test_validate_single_return_rejects_multiple(self):
        def cond(self):
            x = 1
            return x

        with pytest.raises(CompileError, match="exactly one statement"):
            _parse_function_source(
                cond, "test",
                validate_self_only=True,
                validate_single_return=True,
            )

    def test_validate_single_return_rejects_bare_return(self):
        def cond(self):
            return

        with pytest.raises(CompileError, match="must return an expression"):
            _parse_function_source(
                cond, "test",
                validate_self_only=True,
                validate_single_return=True,
            )

    def test_no_validation(self):
        """With all validation off, extra params are allowed."""
        def method(self, x, y):
            return x + y

        func_def, _, _ = _parse_function_source(
            method, "test",
            validate_self_only=False,
            validate_single_return=False,
        )
        assert len(func_def.args.args) == 3


# ---------------------------------------------------------------------------
# _build_var_context
# ---------------------------------------------------------------------------

class TestBuildVarContext:
    def test_basic_var_context(self):
        @fb
        class Simple:
            x: Input[BOOL]
            y: Output[REAL]
            count: INT

            def logic(self):
                pass

        var_groups, declared_vars, static_var_types = _build_var_context(Simple)
        assert "x" in declared_vars
        assert declared_vars["x"] == VarDirection.INPUT
        assert "y" in declared_vars
        assert declared_vars["y"] == VarDirection.OUTPUT
        assert "count" in declared_vars

    def test_static_var_types_populated(self):
        """Static vars with FB types should appear in static_var_types."""
        from plx.framework._descriptors import TON

        @fb
        class WithTimer:
            timer: TON

            def logic(self):
                self.timer(IN=True, PT=True)

        _, _, static_var_types = _build_var_context(WithTimer)
        assert "timer" in static_var_types

    def test_var_groups_keys(self):
        @fb
        class Multi:
            a: Input[BOOL]
            b: Output[BOOL]
            c: REAL

            def logic(self):
                pass

        var_groups, _, _ = _build_var_context(Multi)
        assert "input" in var_groups
        assert "output" in var_groups
        assert "static" in var_groups


# ---------------------------------------------------------------------------
# _build_compile_context
# ---------------------------------------------------------------------------

class TestBuildCompileContext:
    def test_basic_context(self):
        @fb
        class Dummy:
            x: Input[BOOL]

            def logic(self):
                pass

        ctx = _build_compile_context(
            Dummy.logic,
            Dummy,
            {"x": VarDirection.INPUT},
            {},
            10,
            "test.py",
        )
        assert ctx.source_file == "test.py"
        assert ctx.source_line_offset == 9  # start_lineno - 1
        assert ctx.pou_class is Dummy
        assert "x" in ctx.declared_vars
        assert isinstance(ctx.known_enums, dict)

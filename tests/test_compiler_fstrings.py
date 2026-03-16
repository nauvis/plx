"""Tests for f-string compilation to CONCAT() with automatic type conversions."""

import pytest

from conftest import compile_expr, compile_stmts

from plx.framework._compiler import CompileContext, CompileError
from plx.model.expressions import (
    CallArg,
    FunctionCallExpr,
    LiteralExpr,
    TypeConversionExpr,
    VariableRef,
)
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
)


def _ctx_with_vars(**var_types):
    """Build a CompileContext with static var types for testing."""
    ctx = CompileContext()
    for name, type_ref in var_types.items():
        ctx.static_var_types[name] = type_ref
    return ctx


# ---------------------------------------------------------------------------
# Basic f-string compilation
# ---------------------------------------------------------------------------

class TestFStringBasic:
    def test_literal_only(self):
        """f"hello" → LiteralExpr('hello')"""
        result = compile_expr('f"hello"')
        assert isinstance(result, LiteralExpr)
        assert result.value == "'hello'"

    def test_empty(self):
        """f"" → LiteralExpr('')"""
        result = compile_expr('f""')
        assert isinstance(result, LiteralExpr)
        assert result.value == "''"

    def test_single_string_var(self):
        """f"{self.name}" with STRING var → VariableRef (no CONCAT, no conversion)"""
        ctx = _ctx_with_vars(name=StringTypeRef())
        result = compile_expr('f"{self.name}"', ctx=ctx)
        assert isinstance(result, VariableRef)
        assert result.name == "name"

    def test_single_int_var(self):
        """f"{self.x}" with DINT var → TypeConversionExpr (no CONCAT)"""
        ctx = _ctx_with_vars(x=PrimitiveTypeRef(type=PrimitiveType.DINT))
        result = compile_expr('f"{self.x}"', ctx=ctx)
        assert isinstance(result, TypeConversionExpr)
        assert result.target_type == StringTypeRef()
        assert result.source == VariableRef(name="x")
        assert result.source_type == PrimitiveTypeRef(type=PrimitiveType.DINT)


# ---------------------------------------------------------------------------
# CONCAT generation
# ---------------------------------------------------------------------------

class TestFStringConcat:
    def test_text_and_int(self):
        """f"axis {self.id}" → CONCAT('axis ', DINT_TO_STRING(id))"""
        ctx = _ctx_with_vars(id=PrimitiveTypeRef(type=PrimitiveType.DINT))
        result = compile_expr('f"axis {self.id}"', ctx=ctx)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "CONCAT"
        assert len(result.args) == 2
        assert result.args[0].value == LiteralExpr(value="'axis '")
        arg1 = result.args[1].value
        assert isinstance(arg1, TypeConversionExpr)
        assert arg1.source_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_multiple_interpolations(self):
        """f"Fault on axis {self.axis_id}: error {self.error_code}" → CONCAT with 4 parts"""
        ctx = _ctx_with_vars(
            axis_id=PrimitiveTypeRef(type=PrimitiveType.DINT),
            error_code=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        result = compile_expr(
            'f"Fault on axis {self.axis_id}: error {self.error_code}"',
            ctx=ctx,
        )
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "CONCAT"
        assert len(result.args) == 4
        assert result.args[0].value == LiteralExpr(value="'Fault on axis '")
        assert isinstance(result.args[1].value, TypeConversionExpr)
        assert result.args[2].value == LiteralExpr(value="': error '")
        assert isinstance(result.args[3].value, TypeConversionExpr)

    def test_adjacent_interpolations(self):
        """f"{self.x}{self.y}" → CONCAT(to_string(x), to_string(y))"""
        ctx = _ctx_with_vars(
            x=PrimitiveTypeRef(type=PrimitiveType.DINT),
            y=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        result = compile_expr('f"{self.x}{self.y}"', ctx=ctx)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "CONCAT"
        assert len(result.args) == 2

    def test_string_var_no_conversion(self):
        """f"hello {self.name}" with STRING var → CONCAT without type conversion"""
        ctx = _ctx_with_vars(name=StringTypeRef())
        result = compile_expr('f"hello {self.name}"', ctx=ctx)
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "CONCAT"
        assert len(result.args) == 2
        assert result.args[0].value == LiteralExpr(value="'hello '")
        # STRING var passed through directly, no TypeConversionExpr
        assert result.args[1].value == VariableRef(name="name")

    def test_mixed_types(self):
        """f"Device {self.name} at {self.temp} degrees" with STRING + REAL"""
        ctx = _ctx_with_vars(
            name=StringTypeRef(),
            temp=PrimitiveTypeRef(type=PrimitiveType.REAL),
        )
        result = compile_expr(
            'f"Device {self.name} at {self.temp} degrees"',
            ctx=ctx,
        )
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "CONCAT"
        # 5 parts: 'Device ', name, ' at ', REAL_TO_STRING(temp), ' degrees'
        assert len(result.args) == 5
        assert result.args[0].value == LiteralExpr(value="'Device '")
        assert result.args[1].value == VariableRef(name="name")
        assert result.args[2].value == LiteralExpr(value="' at '")
        assert isinstance(result.args[3].value, TypeConversionExpr)
        assert result.args[3].value.source_type == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert result.args[4].value == LiteralExpr(value="' degrees'")


# ---------------------------------------------------------------------------
# Type conversions for various primitive types
# ---------------------------------------------------------------------------

class TestFStringTypeConversions:
    @pytest.mark.parametrize("ptype,expected_source_type", [
        (PrimitiveType.BOOL, PrimitiveType.BOOL),
        (PrimitiveType.INT, PrimitiveType.INT),
        (PrimitiveType.DINT, PrimitiveType.DINT),
        (PrimitiveType.SINT, PrimitiveType.SINT),
        (PrimitiveType.LINT, PrimitiveType.LINT),
        (PrimitiveType.UINT, PrimitiveType.UINT),
        (PrimitiveType.UDINT, PrimitiveType.UDINT),
        (PrimitiveType.USINT, PrimitiveType.USINT),
        (PrimitiveType.ULINT, PrimitiveType.ULINT),
        (PrimitiveType.REAL, PrimitiveType.REAL),
        (PrimitiveType.LREAL, PrimitiveType.LREAL),
        (PrimitiveType.BYTE, PrimitiveType.BYTE),
        (PrimitiveType.WORD, PrimitiveType.WORD),
        (PrimitiveType.DWORD, PrimitiveType.DWORD),
        (PrimitiveType.LWORD, PrimitiveType.LWORD),
        (PrimitiveType.TIME, PrimitiveType.TIME),
    ])
    def test_primitive_to_string(self, ptype, expected_source_type):
        """Each primitive type gets wrapped in TypeConversionExpr(target=STRING)."""
        ctx = _ctx_with_vars(val=PrimitiveTypeRef(type=ptype))
        result = compile_expr('f"v={self.val}"', ctx=ctx)
        assert isinstance(result, FunctionCallExpr)
        conv = result.args[1].value
        assert isinstance(conv, TypeConversionExpr)
        assert conv.target_type == StringTypeRef()
        assert conv.source_type == PrimitiveTypeRef(type=expected_source_type)


# ---------------------------------------------------------------------------
# Expressions inside f-strings
# ---------------------------------------------------------------------------

class TestFStringExpressions:
    def test_arithmetic_expression(self):
        """f"total: {self.count * 2}" → infers type from arithmetic"""
        ctx = _ctx_with_vars(count=PrimitiveTypeRef(type=PrimitiveType.DINT))
        result = compile_expr('f"total: {self.count * 2}"', ctx=ctx)
        assert isinstance(result, FunctionCallExpr)
        conv = result.args[1].value
        assert isinstance(conv, TypeConversionExpr)
        assert conv.source_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_int_literal(self):
        """f"code: {42}" → CONCAT('code: ', INT_TO_STRING(42))"""
        result = compile_expr('f"code: {42}"')
        assert isinstance(result, FunctionCallExpr)
        conv = result.args[1].value
        assert isinstance(conv, TypeConversionExpr)
        assert conv.source_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_float_literal(self):
        """f"val: {3.14}" → CONCAT('val: ', REAL_TO_STRING(3.14))"""
        result = compile_expr('f"val: {3.14}"')
        assert isinstance(result, FunctionCallExpr)
        conv = result.args[1].value
        assert isinstance(conv, TypeConversionExpr)
        assert conv.source_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_bool_literal(self):
        """f"flag: {True}" → CONCAT('flag: ', BOOL_TO_STRING(TRUE))"""
        result = compile_expr('f"flag: {True}"')
        assert isinstance(result, FunctionCallExpr)
        conv = result.args[1].value
        assert isinstance(conv, TypeConversionExpr)
        assert conv.source_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_string_literal_passthrough(self):
        """f"prefix: {'hello'}" → CONCAT('prefix: ', 'hello') — no conversion"""
        result = compile_expr("""f"prefix: {'hello'}" """)
        assert isinstance(result, FunctionCallExpr)
        assert result.args[1].value == LiteralExpr(value="'hello'")

    def test_comparison_expr(self):
        """f"ok: {self.x > 0}" → infers BOOL from comparison"""
        ctx = _ctx_with_vars(x=PrimitiveTypeRef(type=PrimitiveType.DINT))
        result = compile_expr('f"ok: {self.x > 0}"', ctx=ctx)
        assert isinstance(result, FunctionCallExpr)
        conv = result.args[1].value
        assert isinstance(conv, TypeConversionExpr)
        assert conv.source_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestFStringErrors:
    def test_format_spec_rejected(self):
        """f"{self.x:.2f}" → CompileError"""
        ctx = _ctx_with_vars(x=PrimitiveTypeRef(type=PrimitiveType.REAL))
        with pytest.raises(CompileError, match="Format specifiers"):
            compile_expr('f"{self.x:.2f}"', ctx=ctx)

    def test_conversion_flag_r_rejected(self):
        """f"{self.x!r}" → CompileError"""
        ctx = _ctx_with_vars(x=PrimitiveTypeRef(type=PrimitiveType.DINT))
        with pytest.raises(CompileError, match="Conversion flag !r"):
            compile_expr('f"{self.x!r}"', ctx=ctx)

    def test_conversion_flag_s_rejected(self):
        """f"{self.x!s}" → CompileError"""
        ctx = _ctx_with_vars(x=PrimitiveTypeRef(type=PrimitiveType.DINT))
        with pytest.raises(CompileError, match="Conversion flag !s"):
            compile_expr('f"{self.x!s}"', ctx=ctx)

    def test_conversion_flag_a_rejected(self):
        """f"{self.x!a}" → CompileError"""
        ctx = _ctx_with_vars(x=PrimitiveTypeRef(type=PrimitiveType.DINT))
        with pytest.raises(CompileError, match="Conversion flag !a"):
            compile_expr('f"{self.x!a}"', ctx=ctx)

    def test_unknown_type_rejected(self):
        """f"{some_call()}" where type can't be inferred → CompileError"""
        with pytest.raises(CompileError, match="Cannot determine the type"):
            compile_expr('f"val: {UNKNOWN_FUNC()}"')

    def test_named_type_rejected(self):
        """f"{self.my_struct}" where type is a named type → CompileError"""
        ctx = _ctx_with_vars(my_struct=NamedTypeRef(name="MyStruct"))
        with pytest.raises(CompileError, match="Cannot automatically convert 'MyStruct'"):
            compile_expr('f"{self.my_struct}"', ctx=ctx)


# ---------------------------------------------------------------------------
# String + operator rejected
# ---------------------------------------------------------------------------

class TestStringPlusRejected:
    def test_string_literal_plus_string_literal(self):
        """'a' + 'b' → CompileError pointing to f-strings"""
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("'hello' + ' world'")

    def test_string_var_plus_string_literal(self):
        """self.name + ' suffix' → CompileError"""
        ctx = _ctx_with_vars(name=StringTypeRef())
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("self.name + ' suffix'", ctx=ctx)

    def test_string_literal_plus_string_var(self):
        """'prefix ' + self.name → CompileError"""
        ctx = _ctx_with_vars(name=StringTypeRef())
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("'prefix ' + self.name", ctx=ctx)

    def test_string_var_plus_string_var(self):
        """self.a + self.b where both STRING → CompileError"""
        ctx = _ctx_with_vars(a=StringTypeRef(), b=StringTypeRef())
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("self.a + self.b", ctx=ctx)

    def test_int_plus_int_still_works(self):
        """self.x + self.y where both DINT → BinaryExpr(ADD) as usual"""
        from plx.model.expressions import BinaryExpr, BinaryOp
        ctx = _ctx_with_vars(
            x=PrimitiveTypeRef(type=PrimitiveType.DINT),
            y=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        result = compile_expr("self.x + self.y", ctx=ctx)
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.ADD

    def test_unknown_plus_unknown_still_works(self):
        """a + b where types unknown → ADD (no false positive)"""
        from plx.model.expressions import BinaryExpr, BinaryOp
        result = compile_expr("a + b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.ADD

    def test_string_augassign_rejected(self):
        """self.msg += ' suffix' → CompileError"""
        ctx = _ctx_with_vars(msg=StringTypeRef())
        with pytest.raises(CompileError, match="f-string"):
            compile_stmts("self.msg += ' suffix'", ctx=ctx)

    def test_int_augassign_still_works(self):
        """self.count += 1 → normal augmented assignment"""
        ctx = _ctx_with_vars(count=PrimitiveTypeRef(type=PrimitiveType.DINT))
        stmts = compile_stmts("self.count += 1", ctx=ctx)
        assert len(stmts) == 1


# ---------------------------------------------------------------------------
# In assignment context (full statement compilation)
# ---------------------------------------------------------------------------

class TestFStringInStatements:
    def test_assign_fstring_to_output(self):
        """self.msg = f"axis {self.id}" compiles to AssignmentStatement"""
        ctx = _ctx_with_vars(
            msg=StringTypeRef(),
            id=PrimitiveTypeRef(type=PrimitiveType.DINT),
        )
        stmts = compile_stmts('self.msg = f"axis {self.id}"', ctx=ctx)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.target == VariableRef(name="msg")
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "CONCAT"


# ---------------------------------------------------------------------------
# ST export integration
# ---------------------------------------------------------------------------

class TestFStringSTExport:
    def test_concat_renders_correctly(self):
        """Verify the IR from f-string renders to expected ST."""
        from plx.export.st import to_structured_text
        from plx.model.pou import Network, POU, POUInterface, POUType
        from plx.model.statements import Assignment
        from plx.model.variables import Variable

        # Build the IR that f-string compilation would produce
        stmt = Assignment(
            target=VariableRef(name="message"),
            value=FunctionCallExpr(
                function_name="CONCAT",
                args=[
                    CallArg(value=LiteralExpr(value="'Fault: '")),
                    CallArg(value=TypeConversionExpr(
                        target_type=StringTypeRef(),
                        source=VariableRef(name="error_code"),
                        source_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
                    )),
                ],
            ),
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="message", data_type=StringTypeRef())],
                input_vars=[Variable(name="error_code", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))],
            ),
            networks=[Network(statements=[stmt])],
        )
        st = to_structured_text(pou)
        assert "CONCAT('Fault: ', DINT_TO_STRING(error_code))" in st


# ---------------------------------------------------------------------------
# CONCAT rejected in framework Python
# ---------------------------------------------------------------------------

class TestConcatRejected:
    def test_concat_call_rejected(self):
        """CONCAT() is not available directly — use f-strings."""
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("CONCAT('a', 'b')")


# ---------------------------------------------------------------------------
# Python export reconstructs f-strings from CONCAT IR
# ---------------------------------------------------------------------------

class TestFStringPyExport:
    def _generate(self, value_expr):
        """Build a POU with a single assignment and generate Python."""
        from plx.export.py import generate
        from plx.model.pou import Network, POU, POUInterface, POUType
        from plx.model.project import Project
        from plx.model.statements import Assignment
        from plx.model.variables import Variable

        stmt = Assignment(
            target=VariableRef(name="message"),
            value=value_expr,
        )
        pou = POU(
            pou_type=POUType.FUNCTION_BLOCK,
            name="TestFB",
            interface=POUInterface(
                output_vars=[Variable(name="message", data_type=StringTypeRef())],
                input_vars=[Variable(name="error_code", data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))],
                static_vars=[Variable(name="name", data_type=StringTypeRef())],
            ),
            networks=[Network(statements=[stmt])],
        )
        proj = Project(name="test", pous=[pou])
        return generate(proj)

    def test_simple_concat_to_fstring(self):
        """CONCAT('prefix ', DINT_TO_STRING(x)) → f"prefix {self.error_code}" """
        py = self._generate(FunctionCallExpr(
            function_name="CONCAT",
            args=[
                CallArg(value=LiteralExpr(value="'prefix '")),
                CallArg(value=TypeConversionExpr(
                    target_type=StringTypeRef(),
                    source=VariableRef(name="error_code"),
                    source_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
                )),
            ],
        ))
        assert 'f"prefix {self.error_code}"' in py

    def test_multiple_interpolations(self):
        """Multiple parts reconstruct correctly."""
        py = self._generate(FunctionCallExpr(
            function_name="CONCAT",
            args=[
                CallArg(value=LiteralExpr(value="'Fault: '")),
                CallArg(value=TypeConversionExpr(
                    target_type=StringTypeRef(),
                    source=VariableRef(name="error_code"),
                    source_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
                )),
                CallArg(value=LiteralExpr(value="' on '")),
                CallArg(value=VariableRef(name="name")),
            ],
        ))
        assert 'f"Fault: {self.error_code} on {self.name}"' in py

    def test_string_only_concat(self):
        """CONCAT of pure string literals → plain string (no f-string)."""
        py = self._generate(FunctionCallExpr(
            function_name="CONCAT",
            args=[
                CallArg(value=LiteralExpr(value="'hello '")),
                CallArg(value=LiteralExpr(value="'world'")),
            ],
        ))
        assert "'hello world'" in py
        assert "f\"" not in py

    def test_curly_braces_escaped(self):
        """Literal curly braces in string segments are escaped."""
        py = self._generate(FunctionCallExpr(
            function_name="CONCAT",
            args=[
                CallArg(value=LiteralExpr(value="'val={'")),
                CallArg(value=TypeConversionExpr(
                    target_type=StringTypeRef(),
                    source=VariableRef(name="error_code"),
                    source_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
                )),
                CallArg(value=LiteralExpr(value="'}'")),
            ],
        ))
        assert 'f"val={{{self.error_code}}}"' in py

    def test_double_quote_fallback(self):
        """Literal containing double quote falls back to CONCAT()."""
        py = self._generate(FunctionCallExpr(
            function_name="CONCAT",
            args=[
                CallArg(value=LiteralExpr(value="""'say "hi"'""")),
                CallArg(value=TypeConversionExpr(
                    target_type=StringTypeRef(),
                    source=VariableRef(name="error_code"),
                    source_type=PrimitiveTypeRef(type=PrimitiveType.DINT),
                )),
            ],
        ))
        assert "CONCAT(" in py

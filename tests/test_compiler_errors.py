"""Tests for AST compiler — error handling and rejected nodes."""

import ast
import textwrap

import pytest

from conftest import compile_expr, compile_stmts
from plx.framework._compiler import ASTCompiler, CompileContext, CompileError
from plx.framework._descriptors import VarDirection

# ---------------------------------------------------------------------------
# Rejected statement nodes
# ---------------------------------------------------------------------------


class TestRejectedStatements:
    def test_function_def(self):
        with pytest.raises(CompileError, match="Function definitions"):
            compile_stmts("def foo(): pass")

    def test_class_def(self):
        with pytest.raises(CompileError, match="Class definitions"):
            compile_stmts("class Foo: pass")

    def test_delete(self):
        with pytest.raises(CompileError, match="del statements"):
            compile_stmts("del x")

    def test_with(self):
        with pytest.raises(CompileError, match="with statements"):
            compile_stmts("with open('f') as f: pass")

    def test_raise(self):
        with pytest.raises(CompileError, match="raise statements"):
            compile_stmts("raise ValueError()")

    def test_try(self):
        with pytest.raises(CompileError, match="try/except"):
            compile_stmts("""\
try:
    pass
except:
    pass
""")

    def test_assert(self):
        with pytest.raises(CompileError, match="assert statements"):
            compile_stmts("assert True")

    def test_import(self):
        with pytest.raises(CompileError, match="import statements"):
            compile_stmts("import os")

    def test_import_from(self):
        with pytest.raises(CompileError, match="import statements"):
            compile_stmts("from os import path")

    def test_global(self):
        with pytest.raises(CompileError, match="global statements"):
            compile_stmts("global x")

    def test_nonlocal(self):
        # nonlocal requires an enclosing scope, so wrap it
        with pytest.raises(CompileError):
            source = textwrap.dedent("""\
def outer():
    x = 1
    def logic(self):
        nonlocal x
""")
            tree = ast.parse(source)
            # Extract the inner function
            inner = tree.body[0].body[1]
            ctx = CompileContext()
            compiler = ASTCompiler(ctx)
            compiler.compile_body(inner)


# ---------------------------------------------------------------------------
# Rejected expression nodes
# ---------------------------------------------------------------------------


class TestRejectedExpressions:
    def test_lambda(self):
        with pytest.raises(CompileError, match="Lambda"):
            compile_expr("lambda x: x")

    def test_dict(self):
        with pytest.raises(CompileError, match="Dict"):
            compile_expr("{'a': 1}")

    def test_set(self):
        with pytest.raises(CompileError, match="Set"):
            compile_expr("{1, 2, 3}")

    def test_list(self):
        with pytest.raises(CompileError, match="List"):
            compile_expr("[1, 2, 3]")

    def test_tuple(self):
        with pytest.raises(CompileError, match="Tuple"):
            compile_expr("(1, 2)")

    def test_list_comp(self):
        with pytest.raises(CompileError, match="List comprehension"):
            compile_expr("[x for x in range(10)]")

    def test_dict_comp(self):
        with pytest.raises(CompileError, match="Dict comprehension"):
            compile_expr("{k: v for k, v in items}")

    def test_set_comp(self):
        with pytest.raises(CompileError, match="Set comprehension"):
            compile_expr("{x for x in items}")

    def test_generator_exp(self):
        with pytest.raises(CompileError, match="Generator"):
            compile_expr("ABS(x for x in items)")

    def test_fstring(self):
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("f'hello {x}'")

    def test_walrus(self):
        with pytest.raises(CompileError, match="Walrus"):
            compile_expr("(x := 5)")


# ---------------------------------------------------------------------------
# Specific error cases
# ---------------------------------------------------------------------------


class TestSpecificErrors:
    def test_range_outside_for(self):
        with pytest.raises(CompileError, match=r"range.*for loop"):
            compile_expr("range(10)")

    def test_for_non_range(self):
        with pytest.raises(CompileError, match="range"):
            compile_stmts("""\
for x in items:
    self.y = x
""")

    def test_for_non_name_target(self):
        with pytest.raises(CompileError, match="simple name"):
            compile_stmts("""\
for a, b in range(10):
    pass
""")

    def test_type_conv_wrong_arg_count(self):
        with pytest.raises(CompileError, match="exactly 1 argument"):
            compile_expr("INT_TO_REAL(a, b)")

    def test_sentinel_as_statement(self):
        with pytest.raises(CompileError, match="must be used in an expression"):
            compile_stmts("delayed(self.input, timedelta(seconds=5))")

    def test_sentinel_no_signal(self):
        with pytest.raises(CompileError, match="requires a signal"):
            compile_expr("delayed()")

    def test_sentinel_no_duration(self):
        with pytest.raises(CompileError, match="requires a duration"):
            ctx = CompileContext()
            compile_stmts("self.x = delayed(self.input)", ctx)

    def test_rising_no_signal(self):
        with pytest.raises(CompileError, match="requires a signal"):
            compile_expr("rising()")

    def test_compile_error_has_location(self):
        ctx = CompileContext(source_file="test.py", source_line_offset=10)
        with pytest.raises(CompileError, match=r"test\.py"):
            compile_stmts("def foo(): pass", ctx)

    def test_fb_positional_args_rejected(self):
        ctx = CompileContext(
            declared_vars={"timer": VarDirection.STATIC},
            static_var_types={"timer": NamedTypeRef(name="TON")},
        )
        with pytest.raises(CompileError, match="keyword arguments"):
            compile_stmts("self.timer(self.input, self.preset)", ctx)


from plx.model.types import NamedTypeRef

# ---------------------------------------------------------------------------
# MatMult operator rejection (#6)
# ---------------------------------------------------------------------------


class TestMatMultRejected:
    def test_matmult_raises(self):
        """@ operator (MatMult) must be rejected in logic()."""
        ctx = CompileContext(declared_vars={"a": VarDirection.STATIC, "b": VarDirection.STATIC})
        with pytest.raises(CompileError, match="Unsupported binary operator"):
            compile_stmts("self.a = self.a @ self.b", ctx)


# ---------------------------------------------------------------------------
# Multiple assignment targets (silent bug fix)
# ---------------------------------------------------------------------------


class TestMultipleAssignment:
    def test_chained_assignment_rejected(self):
        """a = b = 5 must be rejected (was silently dropping second target)."""
        ctx = CompileContext(declared_vars={"a": VarDirection.STATIC, "b": VarDirection.STATIC})
        with pytest.raises(CompileError, match="Multiple assignment targets"):
            compile_stmts("self.a = self.b = 5", ctx)

    def test_triple_assignment_rejected(self):
        ctx = CompileContext(
            declared_vars={"a": VarDirection.STATIC, "b": VarDirection.STATIC, "c": VarDirection.STATIC}
        )
        with pytest.raises(CompileError, match="Multiple assignment targets"):
            compile_stmts("self.a = self.b = self.c = 5", ctx)

    def test_single_assignment_still_works(self):
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        stmts = compile_stmts("self.x = 5", ctx)
        assert len(stmts) == 1


# ---------------------------------------------------------------------------
# Tuple unpacking
# ---------------------------------------------------------------------------


class TestTupleUnpacking:
    def test_tuple_unpacking_rejected(self):
        ctx = CompileContext(declared_vars={"a": VarDirection.TEMP, "b": VarDirection.TEMP})
        with pytest.raises(CompileError, match="Tuple unpacking"):
            compile_stmts("a, b = 1, 2", ctx)

    def test_tuple_unpacking_guidance(self):
        ctx = CompileContext(declared_vars={"a": VarDirection.TEMP, "b": VarDirection.TEMP})
        with pytest.raises(CompileError, match="separate line"):
            compile_stmts("a, b = 1, 2", ctx)


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------


class TestComparisonOperators:
    def test_in_requires_tuple(self):
        with pytest.raises(CompileError, match="requires a tuple, list, or set of values"):
            compile_expr("x in items")

    def test_not_in_requires_tuple(self):
        with pytest.raises(CompileError, match="requires a tuple, list, or set of values"):
            compile_expr("x not in items")

    def test_in_chaining_after_rejected(self):
        with pytest.raises(CompileError, match="must be the last operator"):
            compile_expr("x in (1, 2) < y")

    def test_not_in_chaining_after_rejected(self):
        with pytest.raises(CompileError, match="must be the last operator"):
            compile_expr("x not in (1, 2) < y")

    def test_is_rejected(self):
        with pytest.raises(CompileError, match="'is' is not supported"):
            compile_expr("x is y")

    def test_is_not_rejected(self):
        with pytest.raises(CompileError, match="'is not' is not supported"):
            compile_expr("x is not y")


# ---------------------------------------------------------------------------
# Rejected Python builtins
# ---------------------------------------------------------------------------


class TestRejectedBuiltins:
    def test_print_rejected_as_expr(self):
        with pytest.raises(CompileError, match=r"print.*does not exist"):
            compile_expr("print('hello')")

    def test_print_rejected_as_stmt(self):
        with pytest.raises(CompileError, match=r"print.*does not exist"):
            compile_stmts("print('hello')")

    def test_str_rejected(self):
        with pytest.raises(CompileError, match=r"str.*not supported"):
            compile_expr("str(42)")

    def test_isinstance_rejected(self):
        with pytest.raises(CompileError, match=r"isinstance.*statically typed"):
            compile_expr("isinstance(x, int)")

    def test_type_rejected(self):
        with pytest.raises(CompileError, match=r"type.*statically typed"):
            compile_expr("type(x)")

    def test_sum_rejected(self):
        with pytest.raises(CompileError, match=r"sum.*for loop"):
            compile_expr("sum(values)")

    def test_enumerate_rejected(self):
        with pytest.raises(CompileError, match=r"enumerate.*for loop"):
            compile_expr("enumerate(items)")


# ---------------------------------------------------------------------------
# None constant
# ---------------------------------------------------------------------------


class TestNoneConstant:
    def test_none_assignment_rejected(self):
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        with pytest.raises(CompileError, match="None does not exist"):
            compile_stmts("self.x = None", ctx)

    def test_none_guidance(self):
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        with pytest.raises(CompileError, match=r"0.*FALSE"):
            compile_stmts("self.x = None", ctx)


# ---------------------------------------------------------------------------
# Augmented assignment errors
# ---------------------------------------------------------------------------


class TestAugAssignErrors:
    def test_floordiv_augassign_compiles(self):
        """//= now compiles to TRUNC(x / y) — no longer rejected."""
        from plx.model.types import PrimitiveType, PrimitiveTypeRef

        ctx = CompileContext(
            declared_vars={"x": VarDirection.STATIC},
            static_var_types={"x": PrimitiveTypeRef(type=PrimitiveType.DINT)},
        )
        stmts = compile_stmts("self.x //= 2", ctx)
        assert len(stmts) == 1


# ---------------------------------------------------------------------------
# Improved guidance in rejected nodes
# ---------------------------------------------------------------------------


class TestImprovedGuidance:
    def test_function_def_guidance(self):
        with pytest.raises(CompileError, match=r"@fb.*@function"):
            compile_stmts("def foo(): pass")

    def test_try_guidance(self):
        with pytest.raises(CompileError, match=r"if/else.*error flags"):
            compile_stmts("try:\n    pass\nexcept:\n    pass")

    def test_raise_guidance(self):
        with pytest.raises(CompileError, match=r"if/else.*error flags"):
            compile_stmts("raise ValueError()")

    def test_assert_guidance(self):
        with pytest.raises(CompileError, match=r"if/else.*fault flags"):
            compile_stmts("assert True")

    def test_with_guidance(self):
        with pytest.raises(CompileError, match="Context managers"):
            compile_stmts("with open('f') as f: pass")

    def test_walrus_guidance(self):
        with pytest.raises(CompileError, match=r"temp variable.*separate line"):
            compile_expr("(x := 5)")

    def test_lambda_guidance(self):
        with pytest.raises(CompileError, match=r"@fb.*@function"):
            compile_expr("lambda x: x")

    def test_list_guidance(self):
        with pytest.raises(CompileError, match=r"ARRAY.*@struct"):
            compile_expr("[1, 2, 3]")

    def test_dict_guidance(self):
        with pytest.raises(CompileError, match="@struct"):
            compile_expr("{'a': 1}")

    def test_fstring_unknown_type_guidance(self):
        with pytest.raises(CompileError, match="Cannot determine the type"):
            compile_expr("f'val: {UNKNOWN_FUNC()}'")

    def test_slice_guidance(self):
        with pytest.raises(CompileError, match="Cannot determine"):
            compile_expr("arr[1:3]")

    def test_list_comp_guidance(self):
        with pytest.raises(CompileError, match="for loop"):
            compile_expr("[x for x in range(10)]")

    def test_global_guidance(self):
        with pytest.raises(CompileError, match="global_var"):
            compile_stmts("global x")

    def test_import_guidance(self):
        with pytest.raises(CompileError, match="module level"):
            compile_stmts("import os")

    def test_delete_guidance(self):
        with pytest.raises(CompileError, match="persist"):
            compile_stmts("del x")

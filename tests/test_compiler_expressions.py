"""Tests for AST compiler — expression handlers."""

import pytest

from conftest import compile_expr, compile_stmts

from plx.framework._compiler import CompileContext, CompileError
from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.types import PrimitiveType, PrimitiveTypeRef, NamedTypeRef, StringTypeRef


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstant:
    def test_int(self):
        result = compile_expr("42")
        assert isinstance(result, LiteralExpr)
        assert result.value == "42"

    def test_float(self):
        result = compile_expr("3.14")
        assert isinstance(result, LiteralExpr)
        assert result.value == "3.14"

    def test_bool_true(self):
        result = compile_expr("True")
        assert isinstance(result, LiteralExpr)
        assert result.value == "TRUE"
        assert result.data_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_bool_false(self):
        result = compile_expr("False")
        assert isinstance(result, LiteralExpr)
        assert result.value == "FALSE"

    def test_string(self):
        result = compile_expr("'hello'")
        assert isinstance(result, LiteralExpr)
        assert result.value == "'hello'"

    def test_negative_int(self):
        result = compile_expr("-5")
        assert isinstance(result, UnaryExpr)
        assert result.op == UnaryOp.NEG
        assert isinstance(result.operand, LiteralExpr)
        assert result.operand.value == "5"

    def test_zero(self):
        result = compile_expr("0")
        assert isinstance(result, LiteralExpr)
        assert result.value == "0"

    def test_large_int(self):
        result = compile_expr("1000000")
        assert isinstance(result, LiteralExpr)
        assert result.value == "1000000"


# ---------------------------------------------------------------------------
# Variable references
# ---------------------------------------------------------------------------

class TestVariableRef:
    def test_simple_name(self):
        result = compile_expr("x")
        assert isinstance(result, VariableRef)
        assert result.name == "x"

    def test_self_attr(self):
        result = compile_expr("self.sensor")
        assert isinstance(result, VariableRef)
        assert result.name == "sensor"

    def test_member_access(self):
        result = compile_expr("self.fb.Q")
        assert isinstance(result, MemberAccessExpr)
        assert result.member == "Q"
        assert isinstance(result.struct, VariableRef)
        assert result.struct.name == "fb"

    def test_nested_member_access(self):
        result = compile_expr("self.a.b.c")
        assert isinstance(result, MemberAccessExpr)
        assert result.member == "c"
        assert isinstance(result.struct, MemberAccessExpr)
        assert result.struct.member == "b"


# ---------------------------------------------------------------------------
# Binary operators
# ---------------------------------------------------------------------------

class TestBinaryOp:
    def test_add(self):
        result = compile_expr("a + b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.ADD

    def test_sub(self):
        result = compile_expr("a - b")
        assert result.op == BinaryOp.SUB

    def test_mul(self):
        result = compile_expr("a * b")
        assert result.op == BinaryOp.MUL

    def test_div(self):
        result = compile_expr("a / b")
        assert result.op == BinaryOp.DIV

    def test_mod(self):
        result = compile_expr("a % b")
        assert result.op == BinaryOp.MOD

    def test_bitand(self):
        result = compile_expr("a & b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.BAND

    def test_bitor(self):
        result = compile_expr("a | b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.BOR

    def test_bitxor(self):
        result = compile_expr("a ^ b")
        assert result.op == BinaryOp.XOR

    def test_lshift(self):
        result = compile_expr("a << b")
        assert result.op == BinaryOp.SHL

    def test_rshift(self):
        result = compile_expr("a >> b")
        assert result.op == BinaryOp.SHR

    def test_pow(self):
        result = compile_expr("a ** b")
        assert result.op == BinaryOp.EXPT

    def test_floordiv(self):
        """a // b → TRUNC(a / b)"""
        result = compile_expr("a // b")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "TRUNC"
        assert len(result.args) == 1
        inner = result.args[0].value
        assert isinstance(inner, BinaryExpr)
        assert inner.op == BinaryOp.DIV

    def test_nested(self):
        result = compile_expr("a + b * c")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.ADD
        assert isinstance(result.right, BinaryExpr)
        assert result.right.op == BinaryOp.MUL

    def test_floordiv_augassign(self):
        """a //= b → a := TRUNC(a / b)"""
        from plx.model.statements import Assignment
        from plx.framework._descriptors import VarDirection
        ctx = CompileContext(declared_vars={"a": VarDirection.TEMP})
        stmts = compile_stmts("a //= b", ctx)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, FunctionCallExpr)
        assert stmt.value.function_name == "TRUNC"

    def test_bitand_augassign(self):
        from plx.model.statements import Assignment
        from plx.framework._descriptors import VarDirection
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        stmts = compile_stmts("self.x &= b", ctx)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == BinaryOp.BAND

    def test_bitor_augassign(self):
        from plx.model.statements import Assignment
        from plx.framework._descriptors import VarDirection
        ctx = CompileContext(declared_vars={"x": VarDirection.STATIC})
        stmts = compile_stmts("self.x |= b", ctx)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == BinaryOp.BOR


# ---------------------------------------------------------------------------
# Boolean operators
# ---------------------------------------------------------------------------

class TestBoolOp:
    def test_and(self):
        result = compile_expr("a and b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.AND

    def test_or(self):
        result = compile_expr("a or b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR

    def test_chain_and(self):
        result = compile_expr("a and b and c")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.AND
        assert isinstance(result.left, BinaryExpr)
        assert result.left.op == BinaryOp.AND

    def test_chain_or(self):
        result = compile_expr("a or b or c")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR
        assert isinstance(result.left, BinaryExpr)


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

class TestCompare:
    def test_eq(self):
        result = compile_expr("a == b")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.EQ

    def test_ne(self):
        result = compile_expr("a != b")
        assert result.op == BinaryOp.NE

    def test_gt(self):
        result = compile_expr("a > b")
        assert result.op == BinaryOp.GT

    def test_ge(self):
        result = compile_expr("a >= b")
        assert result.op == BinaryOp.GE

    def test_lt(self):
        result = compile_expr("a < b")
        assert result.op == BinaryOp.LT

    def test_le(self):
        result = compile_expr("a <= b")
        assert result.op == BinaryOp.LE

    def test_chained(self):
        result = compile_expr("a < b < c")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.AND
        assert isinstance(result.left, BinaryExpr)
        assert result.left.op == BinaryOp.LT
        assert isinstance(result.right, BinaryExpr)
        assert result.right.op == BinaryOp.LT


# ---------------------------------------------------------------------------
# Unary operators
# ---------------------------------------------------------------------------

class TestUnaryOp:
    def test_not(self):
        result = compile_expr("not a")
        assert isinstance(result, UnaryExpr)
        assert result.op == UnaryOp.NOT

    def test_neg(self):
        result = compile_expr("-a")
        assert isinstance(result, UnaryExpr)
        assert result.op == UnaryOp.NEG

    def test_invert(self):
        result = compile_expr("~a")
        assert isinstance(result, UnaryExpr)
        assert result.op == UnaryOp.BNOT

    def test_uadd(self):
        result = compile_expr("+a")
        assert isinstance(result, VariableRef)
        assert result.name == "a"


# ---------------------------------------------------------------------------
# Function calls
# ---------------------------------------------------------------------------

class TestFunctionCall:
    def test_simple_call(self):
        result = compile_expr("SQRT(x)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "SQRT"
        assert len(result.args) == 1

    def test_call_with_kwargs(self):
        result = compile_expr("LIMIT(MN=0, IN=x, MX=100)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "LIMIT"
        assert len(result.args) == 3
        assert result.args[0].name == "MN"

    def test_abs_builtin(self):
        result = compile_expr("abs(x)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "ABS"

    def test_min_builtin(self):
        result = compile_expr("min(a, b)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "MIN"

    def test_max_builtin(self):
        result = compile_expr("max(a, b)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "MAX"

    def test_round_builtin(self):
        result = compile_expr("round(x)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "ROUND"

    def test_pow_builtin(self):
        result = compile_expr("pow(a, b)")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.EXPT

    def test_pow_wrong_arg_count(self):
        with pytest.raises(CompileError, match="exactly 2 arguments"):
            compile_expr("pow(a, b, c)")

    def test_pow_single_arg_rejected(self):
        with pytest.raises(CompileError, match="exactly 2 arguments"):
            compile_expr("pow(a)")

    def test_generic_function(self):
        result = compile_expr("MyFunc(a, b)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "MyFunc"


# ---------------------------------------------------------------------------
# Type conversion
# ---------------------------------------------------------------------------

class TestTypeConversion:
    def test_int_to_real(self):
        result = compile_expr("INT_TO_REAL(x)")
        assert isinstance(result, TypeConversionExpr)
        assert result.target_type == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert isinstance(result.source, VariableRef)

    def test_real_to_dint(self):
        result = compile_expr("REAL_TO_DINT(x)")
        assert isinstance(result, TypeConversionExpr)
        assert result.target_type == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_unknown_target_type(self):
        result = compile_expr("INT_TO_MyType(x)")
        assert isinstance(result, TypeConversionExpr)
        assert result.target_type == NamedTypeRef(name="MyType")


# ---------------------------------------------------------------------------
# Array access
# ---------------------------------------------------------------------------

class TestArrayAccess:
    def test_single_dim(self):
        result = compile_expr("a[0]")
        assert isinstance(result, ArrayAccessExpr)
        assert len(result.indices) == 1
        assert isinstance(result.indices[0], LiteralExpr)
        assert result.indices[0].value == "0"

    def test_multi_dim(self):
        result = compile_expr("a[i, j]")
        assert isinstance(result, ArrayAccessExpr)
        assert len(result.indices) == 2

    def test_expression_index(self):
        result = compile_expr("a[i + 1]")
        assert isinstance(result, ArrayAccessExpr)
        assert isinstance(result.indices[0], BinaryExpr)


# ---------------------------------------------------------------------------
# Ternary (if expression)
# ---------------------------------------------------------------------------

class TestIfExp:
    def test_basic(self):
        result = compile_expr("a if cond else b")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "SEL"
        assert len(result.args) == 3
        # SEL(cond, false_val, true_val)
        assert isinstance(result.args[0].value, VariableRef)
        assert result.args[0].value.name == "cond"
        assert isinstance(result.args[1].value, VariableRef)
        assert result.args[1].value.name == "b"  # false value
        assert isinstance(result.args[2].value, VariableRef)
        assert result.args[2].value.name == "a"  # true value


# ---------------------------------------------------------------------------
# Bit access
# ---------------------------------------------------------------------------

class TestBitAccess:
    def test_self_attr_bit5(self):
        result = compile_expr("self.status.bit5")
        assert isinstance(result, BitAccessExpr)
        assert isinstance(result.target, VariableRef)
        assert result.target.name == "status"
        assert result.bit_index == 5

    def test_bit0(self):
        result = compile_expr("self.word.bit0")
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 0

    def test_bit31(self):
        result = compile_expr("self.dword.bit31")
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 31

    def test_nested_member_bit_access(self):
        result = compile_expr("self.data.status.bit3")
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 3
        assert isinstance(result.target, MemberAccessExpr)
        assert result.target.member == "status"

    def test_array_element_bit_access(self):
        result = compile_expr("self.arr[0].bit7")
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 7
        assert isinstance(result.target, ArrayAccessExpr)

    def test_regular_member_no_false_positive(self):
        result = compile_expr("self.data.status")
        assert isinstance(result, MemberAccessExpr)
        assert result.member == "status"

    def test_partial_match_no_false_positive(self):
        result = compile_expr("self.data.bitmap")
        assert isinstance(result, MemberAccessExpr)
        assert result.member == "bitmap"

    # --- Type validation: valid types ---

    def test_dint_bit5(self):
        ctx = CompileContext(static_var_types={"status": PrimitiveTypeRef(type=PrimitiveType.DINT)})
        result = compile_expr("self.status.bit5", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 5

    def test_word_bit15(self):
        ctx = CompileContext(static_var_types={"flags": PrimitiveTypeRef(type=PrimitiveType.WORD)})
        result = compile_expr("self.flags.bit15", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 15

    def test_byte_bit7(self):
        ctx = CompileContext(static_var_types={"b": PrimitiveTypeRef(type=PrimitiveType.BYTE)})
        result = compile_expr("self.b.bit7", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 7

    def test_lword_bit63(self):
        ctx = CompileContext(static_var_types={"w": PrimitiveTypeRef(type=PrimitiveType.LWORD)})
        result = compile_expr("self.w.bit63", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 63

    def test_sint_bit0(self):
        ctx = CompileContext(static_var_types={"s": PrimitiveTypeRef(type=PrimitiveType.SINT)})
        result = compile_expr("self.s.bit0", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 0

    def test_uint_bit10(self):
        ctx = CompileContext(static_var_types={"u": PrimitiveTypeRef(type=PrimitiveType.UINT)})
        result = compile_expr("self.u.bit10", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 10

    # --- Type validation: invalid types ---

    def test_real_rejects_bit_access(self):
        ctx = CompileContext(static_var_types={"val": PrimitiveTypeRef(type=PrimitiveType.REAL)})
        with pytest.raises(CompileError, match="not supported on REAL"):
            compile_expr("self.val.bit0", ctx)

    def test_lreal_rejects_bit_access(self):
        ctx = CompileContext(static_var_types={"val": PrimitiveTypeRef(type=PrimitiveType.LREAL)})
        with pytest.raises(CompileError, match="not supported on LREAL"):
            compile_expr("self.val.bit0", ctx)

    def test_bool_rejects_bit_access(self):
        ctx = CompileContext(static_var_types={"flag": PrimitiveTypeRef(type=PrimitiveType.BOOL)})
        with pytest.raises(CompileError, match="not supported on BOOL"):
            compile_expr("self.flag.bit0", ctx)

    def test_time_rejects_bit_access(self):
        ctx = CompileContext(static_var_types={"t": PrimitiveTypeRef(type=PrimitiveType.TIME)})
        with pytest.raises(CompileError, match="not supported on TIME"):
            compile_expr("self.t.bit0", ctx)

    def test_string_rejects_bit_access(self):
        from plx.model.types import StringTypeRef
        ctx = CompileContext(static_var_types={"s": StringTypeRef()})
        with pytest.raises(CompileError, match="not supported on STRING"):
            compile_expr("self.s.bit0", ctx)

    def test_wstring_rejects_bit_access(self):
        from plx.model.types import StringTypeRef
        ctx = CompileContext(static_var_types={"s": StringTypeRef(wide=True)})
        with pytest.raises(CompileError, match="not supported on WSTRING"):
            compile_expr("self.s.bit0", ctx)

    def test_named_type_rejects_bit_access(self):
        ctx = CompileContext(static_var_types={"data": NamedTypeRef(name="MyStruct")})
        with pytest.raises(CompileError, match="not supported on 'MyStruct'"):
            compile_expr("self.data.bit0", ctx)

    # --- Type validation: out of range ---

    def test_byte_bit8_out_of_range(self):
        ctx = CompileContext(static_var_types={"b": PrimitiveTypeRef(type=PrimitiveType.BYTE)})
        with pytest.raises(CompileError, match="bit8 is out of range for BYTE.*bit0..bit7"):
            compile_expr("self.b.bit8", ctx)

    def test_word_bit16_out_of_range(self):
        ctx = CompileContext(static_var_types={"w": PrimitiveTypeRef(type=PrimitiveType.WORD)})
        with pytest.raises(CompileError, match="bit16 is out of range for WORD.*bit0..bit15"):
            compile_expr("self.w.bit16", ctx)

    def test_dint_bit32_out_of_range(self):
        ctx = CompileContext(static_var_types={"d": PrimitiveTypeRef(type=PrimitiveType.DINT)})
        with pytest.raises(CompileError, match="bit32 is out of range for DINT.*bit0..bit31"):
            compile_expr("self.d.bit32", ctx)

    def test_sint_bit8_out_of_range(self):
        ctx = CompileContext(static_var_types={"s": PrimitiveTypeRef(type=PrimitiveType.SINT)})
        with pytest.raises(CompileError, match="bit8 is out of range for SINT.*bit0..bit7"):
            compile_expr("self.s.bit8", ctx)

    # --- Nested access (unknown type) passes through ---

    def test_nested_member_bit_access_no_type_info(self):
        """Nested member access can't be type-inferred — passes through without validation."""
        ctx = CompileContext(static_var_types={"data": NamedTypeRef(name="MyStruct")})
        result = compile_expr("self.data.status.bit3", ctx)
        assert isinstance(result, BitAccessExpr)
        assert result.bit_index == 3

    # --- Dynamic bit access: self.status.bit[idx] ---

    def test_dynamic_bit_access_variable(self):
        """self.status.bit[idx] → BitAccessExpr with Expression index."""
        result = compile_expr("self.status.bit[idx]")
        assert isinstance(result, BitAccessExpr)
        assert isinstance(result.target, VariableRef)
        assert result.target.name == "status"
        assert isinstance(result.bit_index, VariableRef)
        assert result.bit_index.name == "idx"

    def test_dynamic_bit_access_expression(self):
        """self.flags.bit[i + 1] → BitAccessExpr with BinaryExpr index."""
        result = compile_expr("self.flags.bit[i + 1]")
        assert isinstance(result, BitAccessExpr)
        assert isinstance(result.target, VariableRef)
        assert result.target.name == "flags"
        assert isinstance(result.bit_index, BinaryExpr)

    def test_dynamic_bit_access_nested_member(self):
        """self.data.word.bit[idx] → BitAccessExpr on MemberAccessExpr."""
        result = compile_expr("self.data.word.bit[idx]")
        assert isinstance(result, BitAccessExpr)
        assert isinstance(result.target, MemberAccessExpr)
        assert result.target.member == "word"
        assert isinstance(result.bit_index, VariableRef)


# ---------------------------------------------------------------------------
# IEC type name as type conversion
# ---------------------------------------------------------------------------

class TestIECTypeNameConversion:
    def test_iec_type_name_conversion(self):
        """INT(x), SINT(x), LREAL(x) → TypeConversionExpr."""
        for type_name in ("INT", "SINT", "LREAL", "DINT", "UINT", "UDINT"):
            result = compile_expr(f"{type_name}(x)")
            assert isinstance(result, TypeConversionExpr), f"{type_name}(x) should be TypeConversionExpr"
            assert isinstance(result.target_type, PrimitiveTypeRef)
            assert result.target_type.type == PrimitiveType(type_name)
            assert isinstance(result.source, VariableRef)
            assert result.source.name == "x"

    def test_iec_type_name_multi_arg_falls_through(self):
        """INT(x, y) should NOT be a type conversion — falls through to FunctionCallExpr."""
        result = compile_expr("INT(x, y)")
        assert isinstance(result, FunctionCallExpr)
        assert result.function_name == "INT"


# ---------------------------------------------------------------------------
# Membership operators (in / not in)
# ---------------------------------------------------------------------------

class TestMembershipOperators:
    def test_in_basic(self):
        """x in (1, 2, 3) → (x == 1) OR (x == 2) OR (x == 3)."""
        result = compile_expr("x in (1, 2, 3)")
        # Structure: OR(OR(EQ(x, 1), EQ(x, 2)), EQ(x, 3))
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR
        assert isinstance(result.right, BinaryExpr)
        assert result.right.op == BinaryOp.EQ
        assert result.right.right == LiteralExpr(value="3")
        assert isinstance(result.left, BinaryExpr)
        assert result.left.op == BinaryOp.OR
        assert result.left.left == BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="1"))
        assert result.left.right == BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="2"))

    def test_not_in_basic(self):
        """x not in (1, 2) → (x != 1) AND (x != 2)."""
        result = compile_expr("x not in (1, 2)")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.AND
        assert result.left == BinaryExpr(op=BinaryOp.NE, left=VariableRef(name="x"), right=LiteralExpr(value="1"))
        assert result.right == BinaryExpr(op=BinaryOp.NE, left=VariableRef(name="x"), right=LiteralExpr(value="2"))

    def test_in_single_element(self):
        """x in (5,) → x == 5."""
        result = compile_expr("x in (5,)")
        assert result == BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=LiteralExpr(value="5"))

    def test_not_in_single_element(self):
        """x not in (5,) → x != 5."""
        result = compile_expr("x not in (5,)")
        assert result == BinaryExpr(op=BinaryOp.NE, left=VariableRef(name="x"), right=LiteralExpr(value="5"))

    def test_in_empty_tuple(self):
        """x in () → FALSE."""
        result = compile_expr("x in ()")
        assert result == LiteralExpr(value="FALSE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))

    def test_not_in_empty_tuple(self):
        """x not in () → TRUE."""
        result = compile_expr("x not in ()")
        assert result == LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))

    def test_in_with_variables(self):
        """x in (a, b) → (x == a) OR (x == b)."""
        result = compile_expr("x in (a, b)")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR
        assert result.left == BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=VariableRef(name="a"))
        assert result.right == BinaryExpr(op=BinaryOp.EQ, left=VariableRef(name="x"), right=VariableRef(name="b"))

    def test_in_with_self_attribute(self):
        """self.state in (1, 2) → (state == 1) OR (state == 2)."""
        result = compile_expr("self.state in (1, 2)")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR
        assert result.left.left == VariableRef(name="state")
        assert result.right.left == VariableRef(name="state")

    def test_in_with_enum_members(self):
        """self.state in (Mode.IDLE, Mode.RUN) → enum literal comparisons."""
        ctx = CompileContext(known_enums={"Mode": {"IDLE": 0, "RUN": 1, "FAULT": 99}})
        result = compile_expr("self.state in (Mode.IDLE, Mode.RUN)", ctx=ctx)
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR
        assert result.left.right == LiteralExpr(value="Mode#IDLE", data_type=NamedTypeRef(name="Mode"))
        assert result.right.right == LiteralExpr(value="Mode#RUN", data_type=NamedTypeRef(name="Mode"))

    def test_in_list_literal(self):
        """x in [1, 2] → same as tuple."""
        result = compile_expr("x in [1, 2]")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR

    def test_in_set_literal(self):
        """x in {1, 2} → same as tuple."""
        result = compile_expr("x in {1, 2}")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.OR

    def test_chained_comparison_before_in(self):
        """a < x in (1, 2) → (a < x) AND ((x == 1) OR (x == 2))."""
        result = compile_expr("a < x in (1, 2)")
        assert isinstance(result, BinaryExpr)
        assert result.op == BinaryOp.AND
        # Left part: a < x
        assert result.left == BinaryExpr(op=BinaryOp.LT, left=VariableRef(name="a"), right=VariableRef(name="x"))
        # Right part: (x == 1) OR (x == 2)
        membership = result.right
        assert isinstance(membership, BinaryExpr)
        assert membership.op == BinaryOp.OR


# ---------------------------------------------------------------------------
# String slicing
# ---------------------------------------------------------------------------

class TestStringSlicing:
    """String slicing: s[:n] → LEFT, s[n:] → RIGHT, s[i:j] → MID, s[i] → MID."""

    def _ctx(self, var_name: str = "s") -> CompileContext:
        return CompileContext(static_var_types={var_name: StringTypeRef()})

    # --- s[:n] ---

    def test_left_literal(self):
        """self.s[:3] → SubstringExpr(end=3)."""
        result = compile_expr("self.s[:3]", self._ctx())
        assert isinstance(result, SubstringExpr)
        assert result.start is None
        assert result.end == LiteralExpr(value="3")
        assert result.single_char is False

    def test_left_variable(self):
        """self.s[:n] → SubstringExpr(end=VariableRef('n'))."""
        result = compile_expr("self.s[:n]", self._ctx())
        assert isinstance(result, SubstringExpr)
        assert result.start is None
        assert result.end == VariableRef(name="n")

    # --- s[n:] ---

    def test_right_literal(self):
        """self.s[3:] → SubstringExpr(start=3)."""
        result = compile_expr("self.s[3:]", self._ctx())
        assert isinstance(result, SubstringExpr)
        assert result.start == LiteralExpr(value="3")
        assert result.end is None

    # --- s[i:j] ---

    def test_mid_literals(self):
        """self.s[2:5] → SubstringExpr(start=2, end=5)."""
        result = compile_expr("self.s[2:5]", self._ctx())
        assert isinstance(result, SubstringExpr)
        assert result.start == LiteralExpr(value="2")
        assert result.end == LiteralExpr(value="5")
        assert result.single_char is False

    # --- s[i] (single char) ---

    def test_single_index(self):
        """self.s[0] → SubstringExpr(start=0, single_char=True)."""
        result = compile_expr("self.s[0]", self._ctx())
        assert isinstance(result, SubstringExpr)
        assert result.start == LiteralExpr(value="0")
        assert result.single_char is True

    def test_single_index_variable(self):
        """self.s[i] → SubstringExpr(start=VariableRef('i'), single_char=True)."""
        result = compile_expr("self.s[i]", self._ctx())
        assert isinstance(result, SubstringExpr)
        assert result.start == VariableRef(name="i")
        assert result.single_char is True

    # --- s[:] ---

    def test_full_slice_identity(self):
        """self.s[:] → VariableRef('s') (identity, no SubstringExpr)."""
        result = compile_expr("self.s[:]", self._ctx())
        assert isinstance(result, VariableRef)
        assert result.name == "s"

    # --- Error cases ---

    def test_negative_start_rejected(self):
        with pytest.raises(CompileError, match="Negative start"):
            compile_expr("self.s[-1:]", self._ctx())

    def test_negative_stop_rejected(self):
        with pytest.raises(CompileError, match="Negative stop"):
            compile_expr("self.s[:-1]", self._ctx())

    def test_negative_single_index_rejected(self):
        with pytest.raises(CompileError, match="Negative index"):
            compile_expr("self.s[-1]", self._ctx())

    def test_step_slice_rejected(self):
        with pytest.raises(CompileError, match="Step slicing"):
            compile_expr("self.s[::2]", self._ctx())

    def test_unknown_type_slice_rejected(self):
        """Slicing a variable with unknown type raises a clear error."""
        with pytest.raises(CompileError, match="Cannot determine"):
            compile_expr("x[1:3]")

    def test_array_single_index_unaffected(self):
        """Single index on untyped variables still produces ArrayAccessExpr."""
        result = compile_expr("arr[0]")
        assert isinstance(result, ArrayAccessExpr)

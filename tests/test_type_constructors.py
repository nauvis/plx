"""Tests for type constructors and _resolve_type_ref."""

import pytest

from plx.framework._types import (
    ARRAY,
    POINTER_TO,
    REFERENCE_TO,
    STRING,
    WSTRING,
    _resolve_type_ref,
)
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
)

# ---------------------------------------------------------------------------
# _resolve_type_ref
# ---------------------------------------------------------------------------


class TestResolveTypeRef:
    def test_primitive_type_enum(self):
        result = _resolve_type_ref(PrimitiveType.BOOL)
        assert result == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_primitive_type_ref_passthrough(self):
        ref = PrimitiveTypeRef(type=PrimitiveType.INT)
        assert _resolve_type_ref(ref) is ref

    def test_string_type_ref_passthrough(self):
        ref = StringTypeRef(wide=False, max_length=80)
        assert _resolve_type_ref(ref) is ref

    def test_named_type_ref_passthrough(self):
        ref = NamedTypeRef(name="MyUDT")
        assert _resolve_type_ref(ref) is ref

    def test_array_type_ref_passthrough(self):
        ref = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _resolve_type_ref(ref) is ref

    def test_pointer_type_ref_passthrough(self):
        ref = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.DINT))
        assert _resolve_type_ref(ref) is ref

    def test_reference_type_ref_passthrough(self):
        ref = ReferenceTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert _resolve_type_ref(ref) is ref

    def test_string_to_named_type_ref(self):
        result = _resolve_type_ref("MyFB")
        assert result == NamedTypeRef(name="MyFB")

    def test_python_bool(self):
        result = _resolve_type_ref(bool)
        assert result == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_python_int(self):
        result = _resolve_type_ref(int)
        assert result == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_python_float_rejected(self):
        """float is ambiguous — must use real or lreal."""
        from plx.framework._errors import DeclarationError

        with pytest.raises(DeclarationError, match="float is ambiguous"):
            _resolve_type_ref(float)

    def test_python_str(self):
        result = _resolve_type_ref(str)
        assert result == StringTypeRef(wide=False, max_length=255)

    def test_python_int_in_array(self):
        result = ARRAY(int, 10)
        assert isinstance(result, ArrayTypeRef)
        assert result.element_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_python_float_in_pointer_rejected(self):
        """float is ambiguous — must use real or lreal."""
        from plx.framework._errors import DeclarationError

        with pytest.raises(DeclarationError, match="float is ambiguous"):
            POINTER_TO(float)

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="Expected a type"):
            _resolve_type_ref(42)

    def test_invalid_type_none_raises(self):
        with pytest.raises(TypeError, match="Expected a type"):
            _resolve_type_ref(None)


# ---------------------------------------------------------------------------
# ARRAY
# ---------------------------------------------------------------------------


class TestARRAY:
    def test_single_int_dim(self):
        result = ARRAY(PrimitiveType.INT, 10)
        assert isinstance(result, ArrayTypeRef)
        assert result.element_type == PrimitiveTypeRef(type=PrimitiveType.INT)
        assert len(result.dimensions) == 1
        assert result.dimensions[0].lower == 0
        assert result.dimensions[0].upper == 9

    def test_single_tuple_dim(self):
        result = ARRAY(PrimitiveType.REAL, (1, 10))
        assert result.dimensions[0].lower == 1
        assert result.dimensions[0].upper == 10

    def test_multi_dim(self):
        result = ARRAY(PrimitiveType.BOOL, 3, 4)
        assert len(result.dimensions) == 2
        assert result.dimensions[0] == DimensionRange(lower=0, upper=2)
        assert result.dimensions[1] == DimensionRange(lower=0, upper=3)

    def test_mixed_dims(self):
        result = ARRAY(PrimitiveType.DINT, 5, (1, 10))
        assert result.dimensions[0] == DimensionRange(lower=0, upper=4)
        assert result.dimensions[1] == DimensionRange(lower=1, upper=10)

    def test_string_element_type(self):
        result = ARRAY("MyStruct", 5)
        assert result.element_type == NamedTypeRef(name="MyStruct")

    def test_no_dims_raises(self):
        with pytest.raises(ValueError, match="at least one dimension"):
            ARRAY(PrimitiveType.INT)

    def test_zero_size_raises(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            ARRAY(PrimitiveType.INT, 0)

    def test_negative_size_raises(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            ARRAY(PrimitiveType.INT, -1)

    def test_invalid_dim_type_raises(self):
        with pytest.raises(TypeError, match="Dimension must be"):
            ARRAY(PrimitiveType.INT, "bad")

    def test_nested_array(self):
        inner = ARRAY(PrimitiveType.INT, 5)
        outer = ARRAY(inner, 3)
        assert isinstance(outer.element_type, ArrayTypeRef)


# ---------------------------------------------------------------------------
# DimensionRange with expression bounds
# ---------------------------------------------------------------------------


class TestDimensionRangeExpressionBounds:
    def test_expression_upper_bound(self):
        from plx.model.expressions import MemberAccessExpr, VariableRef

        dr = DimensionRange(
            lower=1,
            upper=MemberAccessExpr(
                struct=VariableRef(name="Params"),
                member="MAX_SIZE",
            ),
        )
        assert dr.lower == 1
        assert isinstance(dr.upper, MemberAccessExpr)
        assert dr.upper.member == "MAX_SIZE"

    def test_expression_both_bounds(self):
        from plx.model.expressions import VariableRef

        dr = DimensionRange(
            lower=VariableRef(name="MIN_IDX"),
            upper=VariableRef(name="MAX_IDX"),
        )
        assert isinstance(dr.lower, VariableRef)
        assert isinstance(dr.upper, VariableRef)

    def test_expression_bound_skips_validation(self):
        """Expression bounds should not trigger numeric validation."""
        from plx.model.expressions import VariableRef

        # This would fail with int bounds (lower=10 > upper=1) but
        # expression bounds skip numeric validation
        dr = DimensionRange(
            lower=10,
            upper=VariableRef(name="SOME_CONST"),
        )
        assert dr.lower == 10

    def test_int_bounds_still_validated(self):
        """Pure integer bounds should still be validated."""
        with pytest.raises(ValueError, match=r"lower.*must be <= upper"):
            DimensionRange(lower=10, upper=5)

    def test_array_type_ref_with_expression_bounds(self):
        from plx.model.expressions import MemberAccessExpr, VariableRef

        arr = ArrayTypeRef(
            element_type=NamedTypeRef(name="I_PackML_BaseModule"),
            dimensions=[
                DimensionRange(
                    lower=1,
                    upper=MemberAccessExpr(
                        struct=VariableRef(name="Parameters_PackML_Base"),
                        member="MAX_NO_OF_SUBMODULES",
                    ),
                )
            ],
        )
        assert len(arr.dimensions) == 1
        assert isinstance(arr.dimensions[0].upper, MemberAccessExpr)

    def test_json_round_trip(self):
        from plx.model.expressions import MemberAccessExpr, VariableRef

        arr = ArrayTypeRef(
            element_type=NamedTypeRef(name="MyType"),
            dimensions=[
                DimensionRange(
                    lower=1,
                    upper=MemberAccessExpr(
                        struct=VariableRef(name="GVL"),
                        member="MAX",
                    ),
                )
            ],
        )
        json_str = arr.model_dump_json()
        arr2 = ArrayTypeRef.model_validate_json(json_str)
        assert isinstance(arr2.dimensions[0].upper, MemberAccessExpr)
        assert arr2.dimensions[0].upper.member == "MAX"
        assert arr2.dimensions[0].lower == 1


# ---------------------------------------------------------------------------
# STRING / WSTRING
# ---------------------------------------------------------------------------


class TestSTRING:
    def test_default_length(self):
        result = STRING()
        assert isinstance(result, StringTypeRef)
        assert result.wide is False
        assert result.max_length == 255

    def test_custom_length(self):
        result = STRING(80)
        assert result.max_length == 80

    def test_wstring_default(self):
        result = WSTRING()
        assert result.wide is True
        assert result.max_length == 255

    def test_wstring_custom(self):
        result = WSTRING(100)
        assert result.wide is True
        assert result.max_length == 100


# ---------------------------------------------------------------------------
# POINTER_TO / REFERENCE_TO
# ---------------------------------------------------------------------------


class TestPOINTER_TO:
    def test_primitive(self):
        result = POINTER_TO(PrimitiveType.INT)
        assert isinstance(result, PointerTypeRef)
        assert result.target_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_named(self):
        result = POINTER_TO("MyStruct")
        assert result.target_type == NamedTypeRef(name="MyStruct")


class TestREFERENCE_TO:
    def test_primitive(self):
        result = REFERENCE_TO(PrimitiveType.REAL)
        assert isinstance(result, ReferenceTypeRef)
        assert result.target_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_named(self):
        result = REFERENCE_TO("MyFB")
        assert result.target_type == NamedTypeRef(name="MyFB")


# ---------------------------------------------------------------------------
# Python annotation resolution (resolve_annotation)
# ---------------------------------------------------------------------------


class TestPythonAnnotationResolution:
    """Test that Python builtin types in annotations resolve correctly."""

    def test_function_return_float_rejected(self):
        """float is ambiguous — must use real or lreal as return type."""
        from plx.framework._compiler_core import CompileError
        from plx.framework._decorators import function

        with pytest.raises(CompileError, match="float is ambiguous"):

            @function
            class FloatFunc:
                def logic(self) -> float:
                    return 1.0

    def test_function_return_real(self):
        from plx.framework._decorators import function
        from plx.framework._plc_types import real

        @function
        class RealFunc:
            def logic(self) -> real:
                return 1.0

        pou = RealFunc.compile()
        assert pou.return_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_function_return_int(self):
        from plx.framework._decorators import function

        @function
        class IntFunc:
            def logic(self) -> int:
                return 42

        pou = IntFunc.compile()
        assert pou.return_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_function_return_bool(self):
        from plx.framework._decorators import function

        @function
        class BoolFunc:
            def logic(self) -> bool:
                return True

        pou = BoolFunc.compile()
        assert pou.return_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_method_param_int(self):
        from plx.framework._decorators import fb, fb_method

        @fb
        class ParamFB:
            def logic(self):
                pass

            @fb_method
            def set_speed(self, value: int):
                pass

        pou = ParamFB.compile()
        m = pou.methods[0]
        assert m.interface.input_vars[0].data_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_method_param_float_rejected(self):
        """float is ambiguous — must use real or lreal as method param."""
        from plx.framework._compiler_core import CompileError
        from plx.framework._decorators import fb, fb_method

        with pytest.raises(CompileError, match="float is ambiguous"):

            @fb
            class ParamFB2:
                def logic(self):
                    pass

                @fb_method
                def set_value(self, value: float):
                    pass

    def test_method_param_real(self):
        from plx.framework._decorators import fb, fb_method
        from plx.framework._plc_types import real

        @fb
        class ParamFB2r:
            def logic(self):
                pass

            @fb_method
            def set_value(self, value: real):
                pass

        pou = ParamFB2r.compile()
        m = pou.methods[0]
        assert m.interface.input_vars[0].data_type == PrimitiveTypeRef(type=PrimitiveType.REAL)


# ---------------------------------------------------------------------------
# Python type conversions: int(), bool()
# ---------------------------------------------------------------------------


class TestPythonTypeConversions:
    """Test that int(x), bool(x) compile to TypeConversionExpr, float(x) is rejected."""

    def test_float_conversion_rejected(self):
        """float() is ambiguous — must use REAL() or LREAL()."""
        from plx.framework._compiler_core import CompileError
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import DINT, REAL

        with pytest.raises(CompileError, match=r"float.*ambiguous"):

            @fb
            class FloatConv:
                x: Input[DINT]
                y: Output[REAL]

                def logic(self):
                    self.y = float(self.x)

    def test_int_conversion(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import DINT, REAL
        from plx.model.expressions import TypeConversionExpr
        from plx.model.statements import Assignment

        @fb
        class IntConv:
            x: Input[REAL]
            y: Output[DINT]

            def logic(self):
                self.y = int(self.x)

        pou = IntConv.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, TypeConversionExpr)
        assert stmt.value.target_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_bool_conversion(self):
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import BOOL, DINT
        from plx.model.expressions import TypeConversionExpr
        from plx.model.statements import Assignment

        @fb
        class BoolConv:
            x: Input[DINT]
            y: Output[BOOL]

            def logic(self):
                self.y = bool(self.x)

        pou = BoolConv.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, TypeConversionExpr)
        assert stmt.value.target_type == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_float_too_many_args_still_rejected(self):
        """float() with multiple args is also rejected (ambiguous)."""
        from plx.framework._compiler_core import CompileError
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import DINT, REAL

        with pytest.raises(CompileError, match=r"float.*ambiguous"):

            @fb
            class BadConv:
                x: Input[DINT]
                y: Output[REAL]

                def logic(self):
                    self.y = float(self.x, self.x)

    def test_str_still_rejected(self):
        from plx.framework._compiler_core import CompileError
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import DINT

        with pytest.raises(CompileError, match=r"str.*not supported"):

            @fb
            class StrConv:
                x: Input[DINT]
                y: Output[DINT]

                def logic(self):
                    self.y = str(self.x)


# ---------------------------------------------------------------------------
# R1: int() applied to an enum literal must raise CompileError
# ---------------------------------------------------------------------------


class TestIntEnumCast:
    """int(EnumClass.MEMBER) must be rejected at compile time (R1).

    INT(EnumName#MEMBER) is not valid TwinCAT XAE structured-text syntax.
    """

    def test_int_of_enum_member_raises_error(self):
        """int(BoxType.METAL) should raise CompileError, not compile silently."""
        from plx.framework._compiler_core import CompileError
        from plx.framework._data_types import enumeration
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import BOOL, INT

        @enumeration
        class BoxType:
            METAL = 1
            BLUE = 2
            OTHER = 3

        with pytest.raises(CompileError, match="invalid structured-text syntax"):

            @fb
            class Sorter:
                inp_type: Input[INT]
                p1_trigger: Output[BOOL]

                def logic(self):
                    self.p1_trigger = self.inp_type == int(BoxType.METAL)

    def test_error_message_guides_user(self):
        """The error message should name the enum and member and give remediation."""
        from plx.framework._compiler_core import CompileError
        from plx.framework._data_types import enumeration
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import BOOL, INT

        @enumeration
        class Color:
            RED = 0
            GREEN = 1

        with pytest.raises(CompileError) as exc_info:

            @fb
            class UseColor:
                x: Input[INT]
                y: Output[BOOL]

                def logic(self):
                    self.y = self.x == int(Color.GREEN)

        msg = str(exc_info.value)
        assert "Color.GREEN" in msg
        assert "Color#GREEN" in msg

    def test_int_of_plain_variable_still_works(self):
        """int(self.x) on a non-enum variable must continue to compile."""
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input, Output
        from plx.framework._types import DINT, INT
        from plx.model.expressions import TypeConversionExpr
        from plx.model.statements import Assignment

        @fb
        class IntCast:
            x: Input[DINT]
            y: Output[INT]

            def logic(self):
                self.y = int(self.x)

        pou = IntCast.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, Assignment)
        assert isinstance(stmt.value, TypeConversionExpr)

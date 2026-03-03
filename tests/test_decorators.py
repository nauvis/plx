"""Tests for POU decorators — end-to-end compilation."""

import pytest

from plx.framework._compiler import CompileError
from plx.framework._decorators import fb, function, program
from plx.framework._descriptors import Input, Field, Output, InOut
from plx.framework._types import BOOL, DINT, INT, REAL, TIME, T
from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    LiteralExpr,
    MemberAccessExpr,
    VariableRef,
)
from plx.model.pou import POU, Language, POUType
from plx.model.statements import Assignment, FBInvocation, IfStatement
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# @fb
# ---------------------------------------------------------------------------

class TestFBDecorator:
    def test_basic_fb(self):
        @fb
        class SimpleFB:
            sensor: Input[BOOL]
            valve: Output[BOOL]

            def logic(self):
                self.valve = self.sensor

        pou = SimpleFB.compile()
        assert isinstance(pou, POU)
        assert pou.pou_type == POUType.FUNCTION_BLOCK
        assert pou.name == "SimpleFB"
        assert len(pou.interface.input_vars) == 1
        assert len(pou.interface.output_vars) == 1
        assert pou.interface.input_vars[0].name == "sensor"
        assert len(pou.networks) == 1
        assert len(pou.networks[0].statements) == 1

    def test_fb_with_static(self):
        @fb
        class CounterFB:
            enable: Input[BOOL]
            count: Output[DINT]
            internal: DINT = 0

            def logic(self):
                if self.enable:
                    self.internal += 1
                self.count = self.internal

        pou = CounterFB.compile()
        assert len(pou.interface.static_vars) == 1
        assert pou.interface.static_vars[0].name == "internal"
        assert pou.interface.static_vars[0].initial_value == "0"

    def test_fb_with_sentinel(self):
        from plx.framework._compiler import delayed

        @fb
        class DelayedFB:
            input_signal: Input[BOOL]
            output_signal: Output[BOOL]

            def logic(self):
                self.output_signal = delayed(self.input_signal, seconds=5)

        pou = DelayedFB.compile()
        # Should have generated a TON static var
        ton_vars = [v for v in pou.interface.static_vars if v.data_type == NamedTypeRef(name="TON")]
        assert len(ton_vars) == 1

        stmts = pou.networks[0].statements
        assert len(stmts) == 2
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].fb_type == "TON"

    def test_fb_multiple_variables(self):
        @fb
        class MultiFB:
            a: Input[REAL]
            b: Input[REAL]
            c: Input[REAL]
            result: Output[REAL]

            def logic(self):
                self.result = self.a + self.b + self.c

        pou = MultiFB.compile()
        assert len(pou.interface.input_vars) == 3
        assert len(pou.interface.output_vars) == 1


# ---------------------------------------------------------------------------
# @program
# ---------------------------------------------------------------------------

class TestProgramDecorator:
    def test_basic_program(self):
        @program
        class MainProgram:
            running: Input[BOOL]

            def logic(self):
                pass

        pou = MainProgram.compile()
        assert pou.pou_type == POUType.PROGRAM
        assert pou.name == "MainProgram"

    def test_program_with_logic(self):
        @program
        class ControlLoop:
            setpoint: Input[REAL]
            actual: Input[REAL]
            output: Output[REAL]

            def logic(self):
                self.output = self.setpoint - self.actual

        pou = ControlLoop.compile()
        assert len(pou.networks[0].statements) == 1


# ---------------------------------------------------------------------------
# @function
# ---------------------------------------------------------------------------

class TestFunctionDecorator:
    def test_basic_function(self):
        @function
        class AddOne:
            x: Input[REAL]

            def logic(self) -> REAL:
                return self.x + 1.0

        pou = AddOne.compile()
        assert pou.pou_type == POUType.FUNCTION
        assert pou.name == "AddOne"
        assert pou.return_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_function_return_type(self):
        @function
        class Square:
            x: Input[DINT]

            def logic(self) -> DINT:
                return self.x * self.x

        pou = Square.compile()
        assert pou.return_type == PrimitiveTypeRef(type=PrimitiveType.DINT)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestDecoratorErrors:
    def test_missing_logic_on_fb_is_data_only(self):
        """@fb without logic() now produces a data-only FB with empty networks."""
        @fb
        class NoLogic:
            x: Input[BOOL]

        pou = NoLogic.compile()
        assert pou.networks == []

    def test_missing_logic_on_function_raises(self):
        with pytest.raises(CompileError, match="must have a logic"):
            @function
            class NoLogicFunc:
                x: Input[BOOL]

    def test_invalid_syntax_in_logic(self):
        with pytest.raises(CompileError):
            @fb
            class BadLogic:
                x: Input[BOOL]

                def logic(self):
                    import os

    def test_logic_extra_param_rejected(self):
        with pytest.raises(CompileError, match="must take exactly one parameter"):
            @fb
            class ExtraParam:
                def logic(self, x):
                    pass

    def test_logic_varargs_rejected(self):
        with pytest.raises(CompileError, match="must take only 'self'"):
            @fb
            class VarArgs:
                def logic(self, *args):
                    pass

    def test_logic_kwargs_rejected(self):
        with pytest.raises(CompileError, match="must take only 'self'"):
            @fb
            class KwArgs:
                def logic(self, **kwargs):
                    pass

    def test_function_missing_return_annotation(self):
        with pytest.raises(CompileError, match="requires a return type"):
            @function
            class NoReturn:
                x: Input[REAL]

                def logic(self):
                    return self.x + 1.0


# ---------------------------------------------------------------------------
# End-to-end: serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_pou_serializes_to_json(self):
        @fb
        class SerFB:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.y = not self.x

        pou = SerFB.compile()
        data = pou.model_dump()
        assert data["pou_type"] == "FUNCTION_BLOCK"
        assert data["name"] == "SerFB"
        assert len(data["interface"]["input_vars"]) == 1
        assert len(data["interface"]["output_vars"]) == 1

    def test_pou_roundtrips_json(self):
        @fb
        class RoundTrip:
            a: Input[REAL]
            b: Output[REAL]

            def logic(self):
                self.b = self.a + 1.0

        pou = RoundTrip.compile()
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored.name == "RoundTrip"
        assert restored.pou_type == POUType.FUNCTION_BLOCK


# ---------------------------------------------------------------------------
# @fb language parameter
# ---------------------------------------------------------------------------

class TestFBLanguage:
    def test_bare_fb_language_is_none(self):
        @fb
        class BareLanguageFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert BareLanguageFB.compile().language is None

    def test_fb_empty_parens_language_is_none(self):
        @fb()
        class EmptyParensFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert EmptyParensFB.compile().language is None

    def test_fb_language_st(self):
        @fb(language="ST")
        class StFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert StFB.compile().language == Language.ST

    def test_fb_language_ld(self):
        @fb(language="LD")
        class LdFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert LdFB.compile().language == Language.LD

    def test_fb_language_fbd(self):
        @fb(language="FBD")
        class FbdFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert FbdFB.compile().language == Language.FBD


# ---------------------------------------------------------------------------
# @program language parameter
# ---------------------------------------------------------------------------

class TestProgramLanguage:
    def test_bare_program_language_is_none(self):
        @program
        class BareLangProg:
            x: Input[BOOL]

            def logic(self):
                pass

        assert BareLangProg.compile().language is None

    def test_program_empty_parens_language_is_none(self):
        @program()
        class EmptyParensProg:
            x: Input[BOOL]

            def logic(self):
                pass

        assert EmptyParensProg.compile().language is None

    def test_program_language_st(self):
        @program(language="ST")
        class StProg:
            x: Input[BOOL]

            def logic(self):
                pass

        assert StProg.compile().language == Language.ST


# ---------------------------------------------------------------------------
# @function language parameter
# ---------------------------------------------------------------------------

class TestFunctionLanguage:
    def test_function_default_language_is_none(self):
        @function
        class DefaultLangFunc:
            x: Input[REAL]

            def logic(self) -> REAL:
                return self.x

        assert DefaultLangFunc.compile().language is None

    def test_function_language_fbd(self):
        @function(language="FBD")
        class FbdFunc:
            x: Input[REAL]

            def logic(self) -> REAL:
                return self.x

        assert FbdFunc.compile().language == Language.FBD


# ---------------------------------------------------------------------------
# Language error cases
# ---------------------------------------------------------------------------

class TestLanguageErrors:
    def test_sfc_rejected_on_fb(self):
        with pytest.raises(CompileError, match="Use @sfc instead"):
            @fb(language="SFC")
            class SfcFB:
                def logic(self):
                    pass

    def test_sfc_rejected_on_program(self):
        with pytest.raises(CompileError, match="Use @sfc instead"):
            @program(language="SFC")
            class SfcProg:
                def logic(self):
                    pass

    def test_sfc_rejected_on_function(self):
        with pytest.raises(CompileError, match="Use @sfc instead"):
            @function(language="SFC")
            class SfcFunc:
                def logic(self) -> BOOL:
                    pass

    def test_invalid_language_string(self):
        with pytest.raises(CompileError, match="Invalid language 'IL'"):
            @fb(language="IL")
            class IlFB:
                def logic(self):
                    pass

    def test_language_is_case_sensitive(self):
        with pytest.raises(CompileError, match="Invalid language 'st'"):
            @fb(language="st")
            class LowercaseFB:
                def logic(self):
                    pass


# ---------------------------------------------------------------------------
# Language serialization
# ---------------------------------------------------------------------------

class TestLanguageSerialization:
    def test_language_in_model_dump(self):
        @fb(language="LD")
        class DumpFB:
            x: Input[BOOL]

            def logic(self):
                pass

        data = DumpFB.compile().model_dump()
        assert data["language"] == "LD"

    def test_none_language_in_model_dump(self):
        @fb
        class NullDumpFB:
            x: Input[BOOL]

            def logic(self):
                pass

        data = NullDumpFB.compile().model_dump()
        assert data["language"] is None

    def test_language_json_roundtrip(self):
        @fb(language="FBD")
        class RoundTripLangFB:
            x: Input[BOOL]

            def logic(self):
                pass

        pou = RoundTripLangFB.compile()
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored.language == Language.FBD


# ---------------------------------------------------------------------------
# Language with inheritance
# ---------------------------------------------------------------------------

class TestLanguageWithInheritance:
    def test_parent_and_child_different_languages(self):
        @fb(language="ST")
        class ParentLangFB:
            x: Input[BOOL]

            def logic(self):
                pass

        @fb(language="LD")
        class ChildLangFB(ParentLangFB):
            def logic(self):
                pass

        assert ParentLangFB.compile().language == Language.ST
        assert ChildLangFB.compile().language == Language.LD

    def test_child_inherits_none_independently(self):
        @fb(language="FBD")
        class ParentFbdFB:
            x: Input[BOOL]

            def logic(self):
                pass

        @fb
        class ChildNoLangFB(ParentFbdFB):
            def logic(self):
                pass

        assert ParentFbdFB.compile().language == Language.FBD
        assert ChildNoLangFB.compile().language is None


# ---------------------------------------------------------------------------
# folder= kwarg
# ---------------------------------------------------------------------------

class TestFolderKwarg:
    def test_fb_folder(self):
        @fb(folder="actuators")
        class FolderFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert FolderFB.compile().folder == "actuators"

    def test_fb_bare_default_folder(self):
        @fb
        class NoFolderFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert NoFolderFB.compile().folder == ""

    def test_program_folder(self):
        @program(folder="programs/main")
        class FolderProgram:
            x: Input[BOOL]

            def logic(self):
                pass

        assert FolderProgram.compile().folder == "programs/main"

    def test_function_folder(self):
        @function(folder="utils")
        class FolderFunc:
            x: Input[REAL]

            def logic(self) -> REAL:
                return self.x + 1.0

        assert FolderFunc.compile().folder == "utils"

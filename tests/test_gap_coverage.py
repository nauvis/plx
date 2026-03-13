"""Tests filling identified coverage gaps in the universal framework.

Covers:
- Field() validation per variable direction (10 error paths)
- ARRAY() constructor error paths (3)
- match/case negative literal patterns (1)
- Sentinel direct-call RuntimeError guards (12)
- SFC resets= parameter in compiled IR (1)
- _resolve_type_ref with CompiledPOU (1)
"""

import pytest

from plx.framework import (
    ARRAY,
    BOOL,
    DINT,
    INT,
    REAL,
    CompileError,
    DeclarationError,
    Field,
    Input,
    Output,
    Static,
    fb,
    program,
    sfc,
    step,
    transition,
)
from plx.framework._descriptors import (
    Constant,
    External,
    InOut,
    Temp,
)
from plx.framework._types import _resolve_type_ref, first_scan
from plx.framework._compiler import (
    count_down,
    count_up,
    count_up_down,
    delayed,
    falling,
    pulse,
    reset_dominant,
    retentive,
    rising,
    set_dominant,
    sustained,
)
from plx.model.statements import CaseStatement
from plx.model.types import NamedTypeRef

from typing import Annotated


# ---------------------------------------------------------------------------
# Field() validation per direction — 10 untested error paths
# ---------------------------------------------------------------------------

class TestFieldValidationPerDirection:
    """Each variable direction rejects certain Field() kwargs."""

    def test_temp_with_persistent_raises(self):
        with pytest.raises(DeclarationError, match="cannot use persistent"):
            @fb
            class Bad:
                x: Annotated[Temp[int], Field(persistent=True)]

                def logic(self):
                    pass

    def test_temp_with_description_raises(self):
        with pytest.raises(DeclarationError, match="cannot use description"):
            @fb
            class Bad:
                x: Annotated[Temp[int], Field(description="nope")]

                def logic(self):
                    pass

    def test_inout_with_initial_raises(self):
        with pytest.raises(DeclarationError, match="cannot use initial"):
            @fb
            class Bad:
                x: Annotated[InOut[int], Field(initial=42)]

                def logic(self):
                    pass

    def test_inout_with_retain_raises(self):
        with pytest.raises(DeclarationError, match="cannot use retain"):
            @fb
            class Bad:
                x: Annotated[InOut[int], Field(retain=True)]

                def logic(self):
                    pass

    def test_inout_with_persistent_raises(self):
        with pytest.raises(DeclarationError, match="cannot use persistent"):
            @fb
            class Bad:
                x: Annotated[InOut[int], Field(persistent=True)]

                def logic(self):
                    pass

    def test_external_with_initial_raises(self):
        with pytest.raises(DeclarationError, match="cannot use initial"):
            @fb
            class Bad:
                x: Annotated[External[int], Field(initial=42)]

                def logic(self):
                    pass

    def test_external_with_retain_raises(self):
        with pytest.raises(DeclarationError, match="cannot use retain"):
            @fb
            class Bad:
                x: Annotated[External[int], Field(retain=True)]

                def logic(self):
                    pass

    def test_external_with_persistent_raises(self):
        with pytest.raises(DeclarationError, match="cannot use persistent"):
            @fb
            class Bad:
                x: Annotated[External[int], Field(persistent=True)]

                def logic(self):
                    pass

    def test_constant_with_retain_raises(self):
        with pytest.raises(DeclarationError, match="cannot use retain"):
            @fb
            class Bad:
                x: Annotated[Constant[int], Field(retain=True)]

                def logic(self):
                    pass

    def test_constant_with_persistent_raises(self):
        with pytest.raises(DeclarationError, match="cannot use persistent"):
            @fb
            class Bad:
                x: Annotated[Constant[int], Field(persistent=True)]

                def logic(self):
                    pass


# ---------------------------------------------------------------------------
# ARRAY() constructor error paths
# ---------------------------------------------------------------------------

class TestArrayConstructorErrors:
    """ARRAY() raises on bad dimensions."""

    def test_no_dimensions(self):
        with pytest.raises(ValueError, match="at least one dimension"):
            ARRAY(INT)

    def test_zero_size(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            ARRAY(INT, 0)

    def test_negative_size(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            ARRAY(INT, -3)

    def test_bad_dimension_type(self):
        with pytest.raises(TypeError, match="Dimension must be int or"):
            ARRAY(INT, "five")


# ---------------------------------------------------------------------------
# match/case with negative literal
# ---------------------------------------------------------------------------

class TestMatchCaseNegativeLiteral:
    """match/case should support negative integer patterns like case -5."""

    def test_negative_constant_pattern(self):
        @fb
        class NegMatch:
            val: Input[INT]
            out: Output[INT]

            def logic(self):
                match self.val:
                    case -5:
                        self.out = 1
                    case 0:
                        self.out = 2
                    case 10:
                        self.out = 3

        pou = NegMatch.compile()
        stmt = pou.networks[0].statements[0]
        assert isinstance(stmt, CaseStatement)
        assert stmt.branches[0].values == [-5]
        assert stmt.branches[1].values == [0]
        assert stmt.branches[2].values == [10]


# ---------------------------------------------------------------------------
# Sentinel direct-call guards
# ---------------------------------------------------------------------------

class TestSentinelDirectCallGuards:
    """All sentinel functions raise RuntimeError when called directly."""

    def test_first_scan(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            first_scan()

    def test_delayed(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            delayed(True)

    def test_sustained(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            sustained(True)

    def test_pulse(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            pulse(True)

    def test_retentive(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            retentive(True)

    def test_rising(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            rising(True)

    def test_falling(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            falling(True)

    def test_count_up(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            count_up(True)

    def test_count_down(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            count_down(True)

    def test_count_up_down(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            count_up_down(True, False)

    def test_set_dominant(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            set_dominant(True, False)

    def test_reset_dominant(self):
        with pytest.raises(RuntimeError, match="do not call directly"):
            reset_dominant(True, False)


# ---------------------------------------------------------------------------
# SFC resets= parameter in compiled IR
# ---------------------------------------------------------------------------

class TestSfcResetsParameter:
    """The resets= kwarg on @STEP.action should set action_name in IR."""

    def test_resets_produces_action_name(self):
        @sfc
        class ResetTest:
            S0 = step(initial=True)
            S1 = step()

            @S0.action("L")
            def stored_act(self):
                pass

            @S1.action("R", resets="stored_act")
            def do_reset(self):
                pass

            @transition(S0 >> S1)
            def go(self):
                return True

        pou = ResetTest.compile()
        # Find the S1 step and its action with qualifier R
        s1_step = next(s for s in pou.sfc_body.steps if s.name == "S1")
        r_action = next(a for a in s1_step.actions if a.qualifier.value == "R")
        assert r_action.action_name == "stored_act"


# ---------------------------------------------------------------------------
# _resolve_type_ref with CompiledPOU (FB class as type argument)
# ---------------------------------------------------------------------------

class TestResolveTypeRefCompiledPOU:
    """_resolve_type_ref should accept @fb-decorated classes as type args."""

    def test_fb_class_resolves_to_named_ref(self):
        @fb
        class InnerFB:
            x: Input[BOOL]

            def logic(self):
                pass

        result = _resolve_type_ref(InnerFB)
        assert isinstance(result, NamedTypeRef)
        assert result.name == "InnerFB"

    def test_fb_as_static_var_type(self):
        """An @fb class used as a Static variable type compiles correctly."""
        @fb
        class HelperFB:
            val: Input[INT]

            def logic(self):
                pass

        @fb
        class OuterFB:
            helper: Static[HelperFB]

            def logic(self):
                pass

        pou = OuterFB.compile()
        static_var = next(v for v in pou.interface.static_vars if v.name == "helper")
        assert isinstance(static_var.data_type, NamedTypeRef)
        assert static_var.data_type.name == "HelperFB"

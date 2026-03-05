"""Tests for @sfc decorator — SFC framework compilation."""

import pytest

from datetime import timedelta

from plx.framework import (
    BOOL,
    DINT,
    INT,
    REAL,
    CompileError,
    Input,
    method,
    Output,
    project,
    sfc,
    step,
    transition,
    Field,
)
from plx.framework._protocols import CompiledPOU
from plx.model.pou import POU, POUType
from plx.model.sfc import ActionQualifier


# ---------------------------------------------------------------------------
# Basic step/transition declarations
# ---------------------------------------------------------------------------

class TestBasicSFC:
    def test_basic_sfc_compiles(self):
        @sfc
        class Simple:
            cmd: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            RUNNING = step()

            @IDLE.action
            def idle_act(self):
                self.out = False

            @RUNNING.action
            def running_act(self):
                self.out = True

            @transition(IDLE >> RUNNING)
            def start(self):
                return self.cmd

            @transition(RUNNING >> IDLE)
            def stop(self):
                return not self.cmd

        pou = Simple.compile()
        assert isinstance(pou, POU)
        assert pou.sfc_body is not None
        assert pou.networks == []

    def test_default_pou_type_is_program(self):
        @sfc
        class Prog:
            S0 = step(initial=True)

        pou = Prog.compile()
        assert pou.pou_type == POUType.PROGRAM

    def test_explicit_fb_pou_type(self):
        @sfc(pou_type="FB")
        class FbSfc:
            S0 = step(initial=True)

        pou = FbSfc.compile()
        assert pou.pou_type == POUType.FUNCTION_BLOCK

    def test_function_pou_type_rejected(self):
        with pytest.raises(CompileError, match="FUNCTION.*SFC requires state"):
            @sfc(pou_type="FUNCTION")
            class BadSfc:
                S0 = step(initial=True)

    def test_step_is_initial_flag(self):
        @sfc
        class Seq:
            A = step(initial=True)
            B = step()
            C = step()

            @transition(A >> B)
            def t1(self):
                return True

            @transition(B >> C)
            def t2(self):
                return True

            @transition(C >> A)
            def t3(self):
                return True

        pou = Seq.compile()
        steps = {s.name: s for s in pou.sfc_body.steps}
        assert steps["A"].is_initial is True
        assert steps["B"].is_initial is False
        assert steps["C"].is_initial is False

    def test_transition_source_target(self):
        @sfc
        class Seq:
            A = step(initial=True)
            B = step()

            @transition(A >> B)
            def go(self):
                return True

            @transition(B >> A)
            def back(self):
                return True

        pou = Seq.compile()
        trans = pou.sfc_body.transitions
        assert len(trans) == 2
        assert trans[0].source_steps == ["A"]
        assert trans[0].target_steps == ["B"]
        assert trans[1].source_steps == ["B"]
        assert trans[1].target_steps == ["A"]

    def test_variable_descriptors(self):
        @sfc
        class VarTest:
            x: Input[REAL]
            y: Output[INT]
            z: DINT = 42

            S0 = step(initial=True)

        pou = VarTest.compile()
        assert len(pou.interface.input_vars) == 1
        assert pou.interface.input_vars[0].name == "x"
        assert len(pou.interface.output_vars) == 1
        assert pou.interface.output_vars[0].name == "y"
        assert len(pou.interface.static_vars) == 1
        assert pou.interface.static_vars[0].name == "z"


# ---------------------------------------------------------------------------
# Action compilation
# ---------------------------------------------------------------------------

class TestActions:
    def test_n_qualified_action(self):
        @sfc
        class Act:
            out: Output[BOOL]
            S0 = step(initial=True)

            @S0.action
            def during(self):
                self.out = True

        pou = Act.compile()
        step_ir = pou.sfc_body.steps[0]
        assert len(step_ir.actions) == 1
        assert step_ir.actions[0].qualifier == ActionQualifier.N
        assert len(step_ir.actions[0].body) == 1

    def test_entry_action(self):
        @sfc
        class EntryAct:
            count: INT = 0
            S0 = step(initial=True)

            @S0.entry
            def on_enter(self):
                self.count = self.count + 1

        pou = EntryAct.compile()
        step_ir = pou.sfc_body.steps[0]
        assert len(step_ir.entry_actions) == 1
        assert step_ir.entry_actions[0].qualifier == ActionQualifier.P1

    def test_exit_action(self):
        @sfc
        class ExitAct:
            out: Output[BOOL]
            S0 = step(initial=True)

            @S0.exit
            def on_exit(self):
                self.out = False

        pou = ExitAct.compile()
        step_ir = pou.sfc_body.steps[0]
        assert len(step_ir.exit_actions) == 1
        assert step_ir.exit_actions[0].qualifier == ActionQualifier.P0

    def test_explicit_qualifier(self):
        @sfc
        class QualAct:
            out: Output[BOOL]
            S0 = step(initial=True)

            @S0.action(qualifier="L", duration=timedelta(seconds=10))
            def limited(self):
                self.out = True

        pou = QualAct.compile()
        action = pou.sfc_body.steps[0].actions[0]
        assert action.qualifier == ActionQualifier.L
        assert action.duration == "T#10s"

    def test_multiple_actions_per_step(self):
        @sfc
        class Multi:
            a: Output[BOOL]
            b: Output[BOOL]
            S0 = step(initial=True)

            @S0.action
            def act1(self):
                self.a = True

            @S0.action
            def act2(self):
                self.b = True

        pou = Multi.compile()
        assert len(pou.sfc_body.steps[0].actions) == 2

    def test_sentinel_in_action(self):
        """Sentinel functions (delayed/rising/falling) work in actions."""
        from plx.framework import delayed

        @sfc
        class Sentinel:
            cmd: Input[BOOL]
            out: Output[BOOL]
            S0 = step(initial=True)

            @S0.action
            def act(self):
                self.out = delayed(self.cmd, timedelta(seconds=3))

        pou = Sentinel.compile()
        # Should generate static vars for the timer FB
        assert any(v.name.startswith("_plx_ton_") for v in pou.interface.static_vars)


# ---------------------------------------------------------------------------
# Divergence / Convergence
# ---------------------------------------------------------------------------

class TestDivergenceConvergence:
    def test_and_fork(self):
        """A >> (B & C) → simultaneous divergence."""
        @sfc
        class Fork:
            cmd: Input[BOOL]
            A = step(initial=True)
            B = step()
            C = step()

            @transition(A >> (B & C))
            def split(self):
                return self.cmd

            @transition((B & C) >> A)
            def join(self):
                return True

        pou = Fork.compile()
        t0 = pou.sfc_body.transitions[0]
        assert t0.source_steps == ["A"]
        assert set(t0.target_steps) == {"B", "C"}

    def test_and_join(self):
        """A & B >> C → simultaneous convergence."""
        @sfc
        class Join:
            cmd: Input[BOOL]
            A = step(initial=True)
            B = step()
            C = step()

            @transition(A >> B)
            def t1(self):
                return True

            @transition((A & B) >> C)
            def join(self):
                return self.cmd

            @transition(C >> A)
            def back(self):
                return True

        pou = Join.compile()
        t_join = pou.sfc_body.transitions[1]
        assert set(t_join.source_steps) == {"A", "B"}
        assert t_join.target_steps == ["C"]

    def test_selection_divergence(self):
        """Multiple transitions from same source → declaration order preserved."""
        @sfc
        class Sel:
            go: Input[BOOL]
            err: Input[BOOL]
            IDLE = step(initial=True)
            RUNNING = step()
            FAULT = step()

            @transition(IDLE >> RUNNING)
            def start(self):
                return self.go

            @transition(IDLE >> FAULT)
            def fault(self):
                return self.err

            @transition(RUNNING >> IDLE)
            def stop(self):
                return True

            @transition(FAULT >> IDLE)
            def reset(self):
                return True

        pou = Sel.compile()
        # Both transitions from IDLE preserved in declaration order
        idle_trans = [t for t in pou.sfc_body.transitions if "IDLE" in t.source_steps]
        assert len(idle_trans) == 2
        assert idle_trans[0].target_steps == ["RUNNING"]
        assert idle_trans[1].target_steps == ["FAULT"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_no_steps(self):
        with pytest.raises(CompileError, match="must define at least one step"):
            @sfc
            class NoSteps:
                out: Output[BOOL]

    def test_no_initial_step(self):
        with pytest.raises(CompileError, match="must have exactly one initial step"):
            @sfc
            class NoInitial:
                A = step()
                B = step()

    def test_multiple_initial_steps(self):
        with pytest.raises(CompileError, match="multiple initial steps"):
            @sfc
            class MultiInit:
                A = step(initial=True)
                B = step(initial=True)

    def test_action_references_undefined_step(self):
        """Action referencing a step not in this class raises CompileError."""
        from plx.framework._sfc import StepDescriptor
        foreign_step = StepDescriptor(initial=False)
        foreign_step.name = "NONEXISTENT"  # simulate __set_name__

        with pytest.raises(CompileError, match="could not be resolved"):
            @sfc
            class BadAction:
                out: Output[BOOL]
                A = step(initial=True)

                # Manually stamp an action referencing a foreign step descriptor
                def bad_action(self):
                    self.out = True
                from plx.framework._sfc import _ActionMarker
                bad_action._plx_marker = _ActionMarker(
                    step_desc=foreign_step,
                    qualifier=ActionQualifier.N,
                    slot="action",
                )

    def test_transition_body_not_single_return(self):
        with pytest.raises(CompileError, match="must have exactly one statement.*return"):
            @sfc
            class BadTransition:
                cmd: Input[BOOL]
                A = step(initial=True)
                B = step()

                @transition(A >> B)
                def bad(self):
                    x = self.cmd
                    return x

                @transition(B >> A)
                def t2(self):
                    return True

    def test_logic_method_rejected(self):
        with pytest.raises(CompileError, match="must not define a logic"):
            @sfc
            class HasLogic:
                S0 = step(initial=True)

                def logic(self):
                    pass


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_satisfies_compiled_pou(self):
        @sfc
        class Proto:
            S0 = step(initial=True)

        assert isinstance(Proto, CompiledPOU)

    def test_compile_returns_pou(self):
        @sfc
        class Proto2:
            S0 = step(initial=True)

        pou = Proto2.compile()
        assert isinstance(pou, POU)

    def test_project_integration(self):
        @sfc
        class SfcProg:
            S0 = step(initial=True)

        proj = project("Test", pous=[SfcProg]).compile()
        assert len(proj.pous) == 1
        assert proj.pous[0].sfc_body is not None


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_json_roundtrip(self):
        @sfc
        class Roundtrip:
            cmd: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            ACTIVE = step()

            @IDLE.action
            def idle_act(self):
                self.out = False

            @ACTIVE.action
            def active_act(self):
                self.out = True

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.cmd

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return not self.cmd

        pou = Roundtrip.compile()
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored.sfc_body is not None
        assert len(restored.sfc_body.steps) == 2
        assert len(restored.sfc_body.transitions) == 2


# ---------------------------------------------------------------------------
# @method on @sfc class
# ---------------------------------------------------------------------------

class TestMethodOnSfc:
    def test_method_compiles_on_sfc(self):
        @sfc
        class SfcWithMethod:
            val: INT = 0
            S0 = step(initial=True)

            @method
            def reset(self, target: INT) -> BOOL:
                self.val = target
                return True

        pou = SfcWithMethod.compile()
        assert len(pou.methods) == 1
        assert pou.methods[0].name == "reset"


# ---------------------------------------------------------------------------
# folder= kwarg
# ---------------------------------------------------------------------------

class TestSfcFolderKwarg:
    def test_sfc_folder(self):
        @sfc(folder="sequences")
        class FolderSfc:
            S0 = step(initial=True)

        assert FolderSfc.compile().folder == "sequences"

    def test_sfc_bare_default_folder(self):
        @sfc
        class NoFolderSfc:
            S0 = step(initial=True)

        assert NoFolderSfc.compile().folder == ""


# ---------------------------------------------------------------------------
# Operator precedence / chaining guards on TransitionPath
# ---------------------------------------------------------------------------

class TestTransitionPathOperatorGuards:
    """TransitionPath should reject & and chained >> with clear errors."""

    def test_transition_path_and_step(self):
        """(A >> B) & C must raise TypeError."""
        A = step(initial=True)
        B = step()
        C = step()
        path = A >> B
        with pytest.raises(TypeError, match="precedence"):
            path & C

    def test_transition_path_and_step_group(self):
        """(A >> B) & (C & D) must raise TypeError."""
        A = step(initial=True)
        B = step()
        C = step()
        D = step()
        path = A >> B
        group = C & D
        with pytest.raises(TypeError, match="precedence"):
            path & group

    def test_step_and_transition_path(self):
        """C & (A >> B) must raise TypeError (rand)."""
        A = step(initial=True)
        B = step()
        C = step()
        path = A >> B
        with pytest.raises(TypeError, match="precedence"):
            C & path

    def test_step_group_and_transition_path(self):
        """(C & D) & (A >> B) must raise TypeError (rand)."""
        A = step(initial=True)
        B = step()
        C = step()
        D = step()
        path = A >> B
        group = C & D
        with pytest.raises(TypeError, match="precedence"):
            group & path

    def test_chain_rshift(self):
        """(A >> B) >> C must raise TypeError."""
        A = step(initial=True)
        B = step()
        C = step()
        path = A >> B
        with pytest.raises(TypeError, match="Cannot chain"):
            path >> C

    def test_chain_rrshift(self):
        """A >> (B >> C) must raise TypeError."""
        A = step(initial=True)
        B = step()
        C = step()
        path = B >> C
        with pytest.raises(TypeError, match="Cannot chain"):
            A >> path

    def test_correct_parenthesized_divergence_still_works(self):
        """A >> (B & C) should still produce a valid TransitionPath."""
        from plx.framework._sfc import TransitionPath
        A = step(initial=True)
        B = step()
        C = step()
        result = A >> (B & C)
        assert isinstance(result, TransitionPath)
        assert result.source_descs == [A]
        assert set(result.target_descs) == {B, C}

    def test_correct_parenthesized_convergence_still_works(self):
        """(A & B) >> C should still produce a valid TransitionPath."""
        from plx.framework._sfc import TransitionPath
        A = step(initial=True)
        B = step()
        C = step()
        result = (A & B) >> C
        assert isinstance(result, TransitionPath)
        assert set(result.source_descs) == {A, B}
        assert result.target_descs == [C]

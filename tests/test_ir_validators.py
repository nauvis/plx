"""Tests for Pydantic model validators on IR models."""

import pytest
from pydantic import ValidationError

from plx.model.expressions import LiteralExpr
from plx.model.pou import (
    Method,
    Network,
    POU,
    POUType,
    _check_body_exclusivity,
)
from plx.model.sfc import (
    Action,
    ActionQualifier,
    SFCBody,
    Step,
    Transition,
)
from plx.model.statements import Assignment, CaseRange
from plx.model.task import ContinuousTask, EventTask, PeriodicTask, StartupTask


# ---------------------------------------------------------------------------
# Helper: a minimal Expression for building test objects
# ---------------------------------------------------------------------------
TRUE_EXPR = LiteralExpr(value="TRUE")
ASSIGN_STMT = Assignment(
    target=LiteralExpr(value="x"),
    value=TRUE_EXPR,
)


# ===========================================================================
# CaseRange validators
# ===========================================================================


class TestCaseRange:
    def test_valid_equal(self):
        """start == end is valid (single-value range)."""
        cr = CaseRange(start=5, end=5)
        assert cr.start == 5
        assert cr.end == 5

    def test_valid_ascending(self):
        """start < end is valid."""
        cr = CaseRange(start=10, end=20)
        assert cr.start == 10
        assert cr.end == 20

    def test_invalid_descending(self):
        """start > end raises ValidationError."""
        with pytest.raises(ValidationError, match=r"start \(30\) must be <= end \(10\)"):
            CaseRange(start=30, end=10)


# ===========================================================================
# Task validators
# ===========================================================================


class TestTask:
    def test_periodic_with_interval(self):
        """PERIODIC task with interval is valid."""
        t = PeriodicTask(name="Main", interval="T#10ms")
        assert t.interval == "T#10ms"
        assert t.kind == "periodic"

    def test_periodic_without_interval(self):
        """PERIODIC task without interval raises ValidationError."""
        with pytest.raises(ValidationError):
            PeriodicTask(name="Main")

    def test_event_with_trigger(self):
        """EVENT task with trigger_variable is valid."""
        t = EventTask(name="EventTask", trigger_variable="StartSignal")
        assert t.trigger_variable == "StartSignal"
        assert t.kind == "event"

    def test_event_without_trigger(self):
        """EVENT task without trigger_variable raises ValidationError."""
        with pytest.raises(ValidationError):
            EventTask(name="EventTask")

    def test_continuous_valid(self):
        """CONTINUOUS task with no interval and no trigger is valid."""
        t = ContinuousTask(name="Free")
        assert t.kind == "continuous"

    def test_continuous_rejects_extra_fields(self):
        """CONTINUOUS task rejects unknown fields (extra='forbid')."""
        with pytest.raises(ValidationError):
            ContinuousTask(name="Free", interval="T#10ms")

    def test_startup_rejects_extra_fields(self):
        """STARTUP task rejects unknown fields (extra='forbid')."""
        with pytest.raises(ValidationError):
            StartupTask(name="Init", trigger_variable="Trig")


# ===========================================================================
# Transition validators
# ===========================================================================


class TestTransition:
    def test_valid_transition(self):
        """Normal transition with one source and one target."""
        t = Transition(
            source_steps=["S1"],
            target_steps=["S2"],
            condition=TRUE_EXPR,
        )
        assert t.source_steps == ["S1"]
        assert t.target_steps == ["S2"]

    def test_empty_source_steps(self):
        """Empty source_steps raises ValidationError."""
        with pytest.raises(ValidationError, match="source_steps must not be empty"):
            Transition(
                source_steps=[],
                target_steps=["S2"],
                condition=TRUE_EXPR,
            )

    def test_empty_target_steps(self):
        """Empty target_steps raises ValidationError."""
        with pytest.raises(ValidationError, match="target_steps must not be empty"):
            Transition(
                source_steps=["S1"],
                target_steps=[],
                condition=TRUE_EXPR,
            )

    def test_duplicate_source_steps(self):
        """Duplicate source_steps raises ValidationError."""
        with pytest.raises(ValidationError, match="source_steps contains duplicates"):
            Transition(
                source_steps=["S1", "S1"],
                target_steps=["S2"],
                condition=TRUE_EXPR,
            )

    def test_duplicate_target_steps(self):
        """Duplicate target_steps raises ValidationError."""
        with pytest.raises(ValidationError, match="target_steps contains duplicates"):
            Transition(
                source_steps=["S1"],
                target_steps=["S2", "S2"],
                condition=TRUE_EXPR,
            )


# ===========================================================================
# SFCBody validators
# ===========================================================================


class TestSFCBody:
    def test_empty_steps_ok(self):
        """SFCBody with no steps is valid (empty body)."""
        body = SFCBody(steps=[], transitions=[])
        assert body.steps == []

    def test_one_initial_step(self):
        """SFCBody with exactly one initial step is valid."""
        body = SFCBody(
            steps=[
                Step(name="Init", is_initial=True),
                Step(name="Run"),
            ]
        )
        assert len(body.steps) == 2

    def test_zero_initial_steps(self):
        """SFCBody with steps but no initial step raises ValidationError."""
        with pytest.raises(
            ValidationError,
            match="SFCBody must have exactly one initial step.*found 0",
        ):
            SFCBody(
                steps=[
                    Step(name="Run"),
                    Step(name="Stop"),
                ]
            )

    def test_two_initial_steps(self):
        """SFCBody with two initial steps raises ValidationError."""
        with pytest.raises(
            ValidationError,
            match="SFCBody must have exactly one initial step.*found 2",
        ):
            SFCBody(
                steps=[
                    Step(name="Init1", is_initial=True),
                    Step(name="Init2", is_initial=True),
                ]
            )


# ===========================================================================
# Action validators
# ===========================================================================


class TestAction:
    def test_body_only(self):
        """Action with inline body only is valid."""
        a = Action(name="Act1", body=[ASSIGN_STMT])
        assert len(a.body) == 1
        assert a.action_name is None

    def test_action_name_only(self):
        """Action with action_name reference only is valid."""
        a = Action(name="Act1", action_name="MyAction")
        assert a.body == []
        assert a.action_name == "MyAction"

    def test_neither(self):
        """Action with neither body nor action_name is valid (empty action)."""
        a = Action(name="Act1")
        assert a.body == []
        assert a.action_name is None

    def test_both_body_and_action_name(self):
        """Action with both body and action_name raises ValidationError."""
        with pytest.raises(
            ValidationError,
            match="Action must have either inline 'body' or 'action_name' reference, not both",
        ):
            Action(name="Act1", body=[ASSIGN_STMT], action_name="MyAction")


# ===========================================================================
# POU / Method body exclusivity (shared helper)
# ===========================================================================


class TestBodyExclusivity:
    def test_shared_helper_raises(self):
        """_check_body_exclusivity raises ValueError when both are present."""
        with pytest.raises(
            ValueError, match="TestCtx must have at most one body type"
        ):
            _check_body_exclusivity(
                networks=[Network(statements=[])],
                sfc_body=SFCBody(steps=[Step(name="S", is_initial=True)]),
                context="TestCtx",
            )

    def test_shared_helper_ok_networks_only(self):
        """_check_body_exclusivity passes with networks only."""
        _check_body_exclusivity(
            networks=[Network(statements=[])],
            sfc_body=None,
            context="Test",
        )

    def test_shared_helper_ok_neither(self):
        """_check_body_exclusivity passes with neither body type."""
        _check_body_exclusivity(
            networks=[],
            sfc_body=None,
            context="Test",
        )

    def test_pou_both_bodies(self):
        """POU with both networks and sfc_body raises ValidationError."""
        with pytest.raises(
            ValidationError, match="POU must have at most one body type"
        ):
            POU(
                pou_type=POUType.PROGRAM,
                name="Main",
                networks=[Network(statements=[])],
                sfc_body=SFCBody(steps=[Step(name="S", is_initial=True)]),
            )

    def test_method_both_bodies(self):
        """Method with both networks and sfc_body raises ValidationError."""
        with pytest.raises(
            ValidationError, match="Method must have at most one body type"
        ):
            Method(
                name="DoWork",
                networks=[Network(statements=[])],
                sfc_body=SFCBody(steps=[Step(name="S", is_initial=True)]),
            )

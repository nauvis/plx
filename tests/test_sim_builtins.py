"""Tests for builtin FBs and stdlib functions."""

import math

import pytest

from plx.simulate._builtins import (
    BUILTIN_FBS,
    F_TRIG,
    R_TRIG,
    RTO,
    STDLIB_FUNCTIONS,
    TOF,
    TON,
    TP,
)


# ---------------------------------------------------------------------------
# TON
# ---------------------------------------------------------------------------

class TestTON:
    def test_delays_output(self):
        s = TON.initial_state()
        s["IN"] = True
        s["PT"] = 5000
        TON.execute(s, 0)
        assert s["Q"] is False

    def test_fires_after_pt(self):
        s = TON.initial_state()
        s["IN"] = True
        s["PT"] = 5000
        TON.execute(s, 0)
        TON.execute(s, 5000)
        assert s["Q"] is True

    def test_et_clamps_at_pt(self):
        s = TON.initial_state()
        s["IN"] = True
        s["PT"] = 100
        TON.execute(s, 0)
        TON.execute(s, 200)
        assert s["ET"] == 100

    def test_resets_on_false(self):
        s = TON.initial_state()
        s["IN"] = True
        s["PT"] = 100
        TON.execute(s, 0)
        TON.execute(s, 100)
        assert s["Q"] is True
        s["IN"] = False
        TON.execute(s, 200)
        assert s["Q"] is False
        assert s["ET"] == 0

    def test_elapsed_time_tracking(self):
        s = TON.initial_state()
        s["IN"] = True
        s["PT"] = 1000
        TON.execute(s, 0)
        TON.execute(s, 500)
        assert s["ET"] == 500


# ---------------------------------------------------------------------------
# TOF
# ---------------------------------------------------------------------------

class TestTOF:
    def test_stays_true_after_falling(self):
        s = TOF.initial_state()
        s["IN"] = True
        s["PT"] = 1000
        TOF.execute(s, 0)
        assert s["Q"] is True
        s["IN"] = False
        TOF.execute(s, 100)
        assert s["Q"] is True

    def test_goes_false_after_pt(self):
        s = TOF.initial_state()
        s["IN"] = True
        s["PT"] = 1000
        TOF.execute(s, 0)
        s["IN"] = False
        TOF.execute(s, 100)
        TOF.execute(s, 1100)
        assert s["Q"] is False

    def test_resets_when_in_goes_true_again(self):
        s = TOF.initial_state()
        s["IN"] = True
        s["PT"] = 1000
        TOF.execute(s, 0)
        s["IN"] = False
        TOF.execute(s, 100)
        s["IN"] = True
        TOF.execute(s, 500)
        assert s["Q"] is True
        assert s["ET"] == 0


# ---------------------------------------------------------------------------
# TP
# ---------------------------------------------------------------------------

class TestTP:
    def test_pulse_on_rising_edge(self):
        s = TP.initial_state()
        s["IN"] = True
        s["PT"] = 500
        TP.execute(s, 0)
        assert s["Q"] is True

    def test_pulse_ends_after_pt(self):
        s = TP.initial_state()
        s["IN"] = True
        s["PT"] = 500
        TP.execute(s, 0)
        TP.execute(s, 500)
        assert s["Q"] is False

    def test_no_retrigger_during_pulse(self):
        s = TP.initial_state()
        s["IN"] = True
        s["PT"] = 500
        TP.execute(s, 0)
        s["IN"] = False
        TP.execute(s, 100)
        s["IN"] = True
        TP.execute(s, 200)
        # Still in original pulse
        assert s["Q"] is True

    def test_elapsed_time(self):
        s = TP.initial_state()
        s["IN"] = True
        s["PT"] = 1000
        TP.execute(s, 0)
        TP.execute(s, 300)
        assert s["ET"] == 300


# ---------------------------------------------------------------------------
# RTO
# ---------------------------------------------------------------------------

class TestRTO:
    def test_delays_output(self):
        s = RTO.initial_state()
        s["IN"] = True
        s["PT"] = 5000
        RTO.execute(s, 0)
        assert s["Q"] is False

    def test_fires_after_pt(self):
        s = RTO.initial_state()
        s["IN"] = True
        s["PT"] = 5000
        RTO.execute(s, 0)
        RTO.execute(s, 5000)
        assert s["Q"] is True

    def test_retains_time_on_false(self):
        """Key RTO behavior: accumulated time is NOT reset when IN goes FALSE."""
        s = RTO.initial_state()
        s["IN"] = True
        s["PT"] = 1000
        RTO.execute(s, 0)
        RTO.execute(s, 400)
        assert s["ET"] == 400
        assert s["Q"] is False
        # IN goes FALSE — ET must be retained
        s["IN"] = False
        RTO.execute(s, 500)
        assert s["ET"] == 400  # retained, not reset
        assert s["Q"] is False

    def test_accumulates_across_on_off_cycles(self):
        """RTO accumulates total ON time across multiple cycles."""
        s = RTO.initial_state()
        s["PT"] = 1000

        # First ON period: 0ms to 400ms (400ms accumulated)
        s["IN"] = True
        RTO.execute(s, 0)
        RTO.execute(s, 400)
        assert s["ET"] == 400

        # OFF period
        s["IN"] = False
        RTO.execute(s, 500)
        assert s["ET"] == 400  # retained

        # Second ON period: 600ms to 1200ms (600ms more = 1000ms total)
        s["IN"] = True
        RTO.execute(s, 600)
        RTO.execute(s, 1200)
        assert s["ET"] == 1000
        assert s["Q"] is True

    def test_et_clamps_at_pt(self):
        s = RTO.initial_state()
        s["IN"] = True
        s["PT"] = 100
        RTO.execute(s, 0)
        RTO.execute(s, 200)
        assert s["ET"] == 100

    def test_q_stays_true_after_done(self):
        """Once Q goes TRUE it stays TRUE (even if IN goes FALSE)."""
        s = RTO.initial_state()
        s["IN"] = True
        s["PT"] = 100
        RTO.execute(s, 0)
        RTO.execute(s, 100)
        assert s["Q"] is True
        s["IN"] = False
        RTO.execute(s, 200)
        assert s["Q"] is True  # retentive — stays done

    def test_registered_in_builtins(self):
        assert "RTO" in BUILTIN_FBS


# ---------------------------------------------------------------------------
# R_TRIG
# ---------------------------------------------------------------------------

class TestRTRIG:
    def test_rising_edge(self):
        s = R_TRIG.initial_state()
        s["CLK"] = True
        R_TRIG.execute(s, 0)
        assert s["Q"] is True

    def test_no_output_when_held(self):
        s = R_TRIG.initial_state()
        s["CLK"] = True
        R_TRIG.execute(s, 0)
        R_TRIG.execute(s, 10)
        assert s["Q"] is False

    def test_no_output_on_falling(self):
        s = R_TRIG.initial_state()
        s["CLK"] = True
        R_TRIG.execute(s, 0)
        s["CLK"] = False
        R_TRIG.execute(s, 10)
        assert s["Q"] is False


# ---------------------------------------------------------------------------
# F_TRIG
# ---------------------------------------------------------------------------

class TestFTRIG:
    def test_falling_edge(self):
        s = F_TRIG.initial_state()
        s["CLK"] = True
        s["_prev_clk"] = True
        s["CLK"] = False
        F_TRIG.execute(s, 0)
        assert s["Q"] is True

    def test_no_output_when_held_false(self):
        s = F_TRIG.initial_state()
        F_TRIG.execute(s, 0)
        assert s["Q"] is False

    def test_no_output_on_rising(self):
        s = F_TRIG.initial_state()
        s["CLK"] = True
        F_TRIG.execute(s, 0)
        assert s["Q"] is False


# ---------------------------------------------------------------------------
# STDLIB_FUNCTIONS
# ---------------------------------------------------------------------------

class TestStdlib:
    def test_abs(self):
        assert STDLIB_FUNCTIONS["ABS"](-5) == 5

    def test_sqrt(self):
        assert STDLIB_FUNCTIONS["SQRT"](4.0) == pytest.approx(2.0)

    def test_min(self):
        assert STDLIB_FUNCTIONS["MIN"](3, 1, 2) == 1

    def test_max(self):
        assert STDLIB_FUNCTIONS["MAX"](3, 1, 2) == 3

    def test_limit(self):
        assert STDLIB_FUNCTIONS["LIMIT"](0, 5, 10) == 5
        assert STDLIB_FUNCTIONS["LIMIT"](0, -1, 10) == 0
        assert STDLIB_FUNCTIONS["LIMIT"](0, 15, 10) == 10

    def test_sel(self):
        assert STDLIB_FUNCTIONS["SEL"](False, 10, 20) == 10
        assert STDLIB_FUNCTIONS["SEL"](True, 10, 20) == 20

    def test_mux(self):
        assert STDLIB_FUNCTIONS["MUX"](0, "a", "b", "c") == "a"
        assert STDLIB_FUNCTIONS["MUX"](2, "a", "b", "c") == "c"

    def test_trunc(self):
        assert STDLIB_FUNCTIONS["TRUNC"](3.7) == 3

    def test_round(self):
        assert STDLIB_FUNCTIONS["ROUND"](3.5) == 4

    def test_sin(self):
        assert STDLIB_FUNCTIONS["SIN"](0.0) == pytest.approx(0.0)

    def test_cos(self):
        assert STDLIB_FUNCTIONS["COS"](0.0) == pytest.approx(1.0)

    def test_exp(self):
        assert STDLIB_FUNCTIONS["EXP"](0.0) == pytest.approx(1.0)

    def test_expt(self):
        assert STDLIB_FUNCTIONS["EXPT"](2, 3) == 8

    def test_shl(self):
        assert STDLIB_FUNCTIONS["SHL"](1, 3) == 8

    def test_shr(self):
        assert STDLIB_FUNCTIONS["SHR"](8, 2) == 2

    def test_ln(self):
        assert STDLIB_FUNCTIONS["LN"](math.e) == pytest.approx(1.0)

    def test_log(self):
        assert STDLIB_FUNCTIONS["LOG"](100) == pytest.approx(2.0)

    def test_atan2(self):
        assert STDLIB_FUNCTIONS["ATAN2"](1.0, 1.0) == pytest.approx(math.pi / 4)

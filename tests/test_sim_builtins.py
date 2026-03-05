"""Tests for builtin FBs and stdlib functions."""

import math

import pytest

from plx.simulate._builtins import (
    BUILTIN_FBS,
    CTD,
    CTU,
    F_TRIG,
    R_TRIG,
    RS,
    RTO,
    SR,
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

    def test_ceil(self):
        assert STDLIB_FUNCTIONS["CEIL"](2.3) == 3
        assert STDLIB_FUNCTIONS["CEIL"](-2.3) == -2
        assert STDLIB_FUNCTIONS["CEIL"](5.0) == 5

    def test_floor(self):
        assert STDLIB_FUNCTIONS["FLOOR"](2.7) == 2
        assert STDLIB_FUNCTIONS["FLOOR"](-2.7) == -3
        assert STDLIB_FUNCTIONS["FLOOR"](5.0) == 5

    # --- String functions ---

    def test_len(self):
        assert STDLIB_FUNCTIONS["LEN"]("hello") == 5

    def test_len_empty(self):
        assert STDLIB_FUNCTIONS["LEN"]("") == 0

    def test_left(self):
        assert STDLIB_FUNCTIONS["LEFT"]("hello", 3) == "hel"

    def test_right(self):
        assert STDLIB_FUNCTIONS["RIGHT"]("hello", 3) == "llo"

    def test_mid(self):
        assert STDLIB_FUNCTIONS["MID"]("hello world", 7, 5) == "world"

    def test_mid_1_based(self):
        assert STDLIB_FUNCTIONS["MID"]("ABCDE", 1, 3) == "ABC"

    def test_concat(self):
        assert STDLIB_FUNCTIONS["CONCAT"]("foo", "bar") == "foobar"

    def test_concat_multiple(self):
        assert STDLIB_FUNCTIONS["CONCAT"]("a", "b", "c") == "abc"

    def test_find_found(self):
        assert STDLIB_FUNCTIONS["FIND"]("hello world", "world") == 7

    def test_find_not_found(self):
        assert STDLIB_FUNCTIONS["FIND"]("hello", "xyz") == 0

    def test_replace(self):
        # IEC order: REPLACE(source, replacement, num_chars, position)
        assert STDLIB_FUNCTIONS["REPLACE"]("hello world", "earth", 5, 7) == "hello earth"

    def test_insert(self):
        assert STDLIB_FUNCTIONS["INSERT"]("helo", "l", 4) == "hello"

    def test_delete(self):
        assert STDLIB_FUNCTIONS["DELETE"]("hello", 1, 4) == "helo"

    # --- Bitwise function-call forms ---

    def test_rol(self):
        assert STDLIB_FUNCTIONS["ROL"](0x80000001, 1) == 0x00000003

    def test_ror(self):
        assert STDLIB_FUNCTIONS["ROR"](0x00000003, 1) == 0x80000001

    def test_and_bool(self):
        assert STDLIB_FUNCTIONS["AND"](True, False) is False
        assert STDLIB_FUNCTIONS["AND"](True, True) is True

    def test_and_int(self):
        assert STDLIB_FUNCTIONS["AND"](0xFF, 0x0F) == 0x0F

    def test_or_bool(self):
        assert STDLIB_FUNCTIONS["OR"](False, True) is True

    def test_or_int(self):
        assert STDLIB_FUNCTIONS["OR"](0xF0, 0x0F) == 0xFF

    def test_xor_bool(self):
        assert STDLIB_FUNCTIONS["XOR"](True, True) is False
        assert STDLIB_FUNCTIONS["XOR"](True, False) is True

    def test_not_bool(self):
        assert STDLIB_FUNCTIONS["NOT"](True) is False
        assert STDLIB_FUNCTIONS["NOT"](False) is True


# ---------------------------------------------------------------------------
# CTU
# ---------------------------------------------------------------------------

class TestCTU:
    def test_counts_on_rising_edge(self):
        s = CTU.initial_state()
        s["PV"] = 3
        s["CU"] = True
        CTU.execute(s, 0)
        assert s["CV"] == 1
        assert s["Q"] is False

    def test_q_true_when_cv_reaches_pv(self):
        s = CTU.initial_state()
        s["PV"] = 2
        # Edge 1
        s["CU"] = True
        CTU.execute(s, 0)
        assert s["CV"] == 1
        # Reset edge detection
        s["CU"] = False
        CTU.execute(s, 10)
        # Edge 2
        s["CU"] = True
        CTU.execute(s, 20)
        assert s["CV"] == 2
        assert s["Q"] is True

    def test_no_count_without_edge(self):
        s = CTU.initial_state()
        s["PV"] = 5
        s["CU"] = True
        CTU.execute(s, 0)
        CTU.execute(s, 10)  # held high, no new edge
        assert s["CV"] == 1

    def test_reset_clears_cv(self):
        s = CTU.initial_state()
        s["PV"] = 5
        s["CU"] = True
        CTU.execute(s, 0)
        assert s["CV"] == 1
        s["RESET"] = True
        CTU.execute(s, 10)
        assert s["CV"] == 0
        assert s["Q"] is False

    def test_registered(self):
        assert "CTU" in BUILTIN_FBS


# ---------------------------------------------------------------------------
# CTD
# ---------------------------------------------------------------------------

class TestCTD:
    def test_counts_down_on_rising_edge(self):
        s = CTD.initial_state()
        s["PV"] = 5
        s["CV"] = 3
        s["CD"] = True
        CTD.execute(s, 0)
        assert s["CV"] == 2

    def test_q_true_when_cv_le_zero(self):
        s = CTD.initial_state()
        s["PV"] = 1
        s["CV"] = 1
        s["CD"] = True
        CTD.execute(s, 0)
        assert s["CV"] == 0
        assert s["Q"] is True

    def test_load_sets_cv_to_pv(self):
        s = CTD.initial_state()
        s["PV"] = 10
        s["LOAD"] = True
        CTD.execute(s, 0)
        assert s["CV"] == 10

    def test_no_count_without_edge(self):
        s = CTD.initial_state()
        s["CV"] = 5
        s["CD"] = True
        CTD.execute(s, 0)
        CTD.execute(s, 10)  # held high
        assert s["CV"] == 4

    def test_registered(self):
        assert "CTD" in BUILTIN_FBS


# ---------------------------------------------------------------------------
# SR
# ---------------------------------------------------------------------------

class TestSR:
    def test_set_dominant(self):
        s = SR.initial_state()
        s["SET1"] = True
        s["RESET"] = True
        SR.execute(s, 0)
        assert s["Q1"] is True  # set-dominant

    def test_reset_when_no_set(self):
        s = SR.initial_state()
        s["Q1"] = True
        s["SET1"] = False
        s["RESET"] = True
        SR.execute(s, 0)
        assert s["Q1"] is False

    def test_latch(self):
        s = SR.initial_state()
        s["SET1"] = True
        SR.execute(s, 0)
        assert s["Q1"] is True
        s["SET1"] = False
        SR.execute(s, 10)
        assert s["Q1"] is True  # latched

    def test_registered(self):
        assert "SR" in BUILTIN_FBS


# ---------------------------------------------------------------------------
# RS
# ---------------------------------------------------------------------------

class TestRS:
    def test_reset_dominant(self):
        s = RS.initial_state()
        s["SET"] = True
        s["RESET1"] = True
        RS.execute(s, 0)
        assert s["Q1"] is False  # reset-dominant

    def test_set_when_no_reset(self):
        s = RS.initial_state()
        s["SET"] = True
        s["RESET1"] = False
        RS.execute(s, 0)
        assert s["Q1"] is True

    def test_latch(self):
        s = RS.initial_state()
        s["SET"] = True
        RS.execute(s, 0)
        assert s["Q1"] is True
        s["SET"] = False
        RS.execute(s, 10)
        assert s["Q1"] is True  # latched

    def test_registered(self):
        assert "RS" in BUILTIN_FBS

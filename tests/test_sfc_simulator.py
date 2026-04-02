"""Tests for SFC execution in the simulator."""

from datetime import timedelta

from plx.framework import (
    BOOL,
    INT,
    REAL,
    Input,
    Output,
    delayed,
    sfc,
    step,
    transition,
)
from plx.simulate import simulate

# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


class TestBasicExecution:
    def test_initial_step_active_on_first_scan(self):
        @sfc
        class Seq:
            IDLE = step(initial=True)
            RUN = step()

            @transition(IDLE >> RUN)
            def t1(self):
                return False

            @transition(RUN >> IDLE)
            def t2(self):
                return True

        ctx = simulate(Seq)
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}

    def test_n_action_runs_every_scan(self):
        @sfc
        class NAction:
            count: INT = 0
            S0 = step(initial=True)

            @S0.action
            def inc(self):
                self.count = self.count + 1

        ctx = simulate(NAction)
        ctx.scan(3)
        assert ctx.count == 3

    def test_transition_fires(self):
        @sfc
        class Trans:
            go: Input[BOOL]
            IDLE = step(initial=True)
            RUN = step()

            @transition(IDLE >> RUN)
            def start(self):
                return self.go

            @transition(RUN >> IDLE)
            def stop(self):
                return not self.go

        ctx = simulate(Trans)
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}
        ctx.go = True
        ctx.scan()
        assert ctx.active_steps == {"RUN"}

    def test_transition_deactivates_old_step(self):
        @sfc
        class Trans2:
            go: Input[BOOL]
            A = step(initial=True)
            B = step()

            @transition(A >> B)
            def t1(self):
                return self.go

            @transition(B >> A)
            def t2(self):
                return not self.go

        ctx = simulate(Trans2)
        ctx.scan()
        assert "A" in ctx.active_steps
        assert "B" not in ctx.active_steps
        ctx.go = True
        ctx.scan()
        assert "B" in ctx.active_steps
        assert "A" not in ctx.active_steps


# ---------------------------------------------------------------------------
# Entry / exit actions
# ---------------------------------------------------------------------------


class TestEntryExitActions:
    def test_entry_action_runs_once(self):
        @sfc
        class EntryOnce:
            go: Input[BOOL]
            entry_count: INT = 0

            IDLE = step(initial=True)
            RUN = step()

            @RUN.entry
            def on_enter(self):
                self.entry_count = self.entry_count + 1

            @transition(IDLE >> RUN)
            def start(self):
                return self.go

            @transition(RUN >> IDLE)
            def stop(self):
                return False

        ctx = simulate(EntryOnce)
        ctx.scan()  # first scan — initializes IDLE
        ctx.go = True
        ctx.scan()  # transitions to RUN
        ctx.scan()  # entry action should have run once on previous scan transition
        ctx.scan()  # still in RUN, entry should NOT run again
        assert ctx.entry_count == 1

    def test_exit_action_runs_once(self):
        @sfc
        class ExitOnce:
            go: Input[BOOL]
            exit_count: INT = 0

            IDLE = step(initial=True)
            RUN = step()

            @IDLE.exit
            def on_exit(self):
                self.exit_count = self.exit_count + 1

            @transition(IDLE >> RUN)
            def start(self):
                return self.go

            @transition(RUN >> IDLE)
            def stop(self):
                return False

        ctx = simulate(ExitOnce)
        ctx.scan()  # init IDLE
        ctx.go = True
        ctx.scan()  # transition IDLE→RUN (marks IDLE as just_deactivated)
        ctx.scan()  # exit action runs for IDLE (from just_deactivated)
        assert ctx.exit_count == 1
        ctx.scan()  # no more exits
        assert ctx.exit_count == 1

    def test_initial_step_entry_action(self):
        """Entry action on the initial step runs on first scan."""

        @sfc
        class InitEntry:
            entry_count: INT = 0
            S0 = step(initial=True)

            @S0.entry
            def on_enter(self):
                self.entry_count = self.entry_count + 1

        ctx = simulate(InitEntry)
        ctx.scan()  # first scan — S0 is just_activated
        assert ctx.entry_count == 1
        ctx.scan()  # second scan — not just_activated
        assert ctx.entry_count == 1


# ---------------------------------------------------------------------------
# Selection divergence
# ---------------------------------------------------------------------------


class TestSelectionDivergence:
    def test_first_true_wins(self):
        """Two transitions from same step: first-true wins (declaration order)."""

        @sfc
        class Sel:
            IDLE = step(initial=True)
            A = step()
            B = step()

            @transition(IDLE >> A)
            def go_a(self):
                return True  # always true

            @transition(IDLE >> B)
            def go_b(self):
                return True  # also true, but second

            @transition(A >> IDLE)
            def back_a(self):
                return False  # stay in A

            @transition(B >> IDLE)
            def back_b(self):
                return False  # stay in B

        ctx = simulate(Sel)
        ctx.scan()  # init + both conditions true from IDLE, first wins → A
        assert ctx.active_steps == {"A"}


# ---------------------------------------------------------------------------
# Simultaneous divergence (AND-fork)
# ---------------------------------------------------------------------------


class TestSimultaneousDivergence:
    def test_and_fork(self):
        @sfc
        class Fork:
            go: Input[BOOL]
            IDLE = step(initial=True)
            FILL = step()
            HEAT = step()

            @transition(IDLE >> (FILL & HEAT))
            def start(self):
                return self.go

            @transition((FILL & HEAT) >> IDLE)
            def done(self):
                return True

        ctx = simulate(Fork)
        ctx.scan()  # init
        ctx.go = True
        ctx.scan()  # fork
        assert ctx.active_steps == {"FILL", "HEAT"}


# ---------------------------------------------------------------------------
# Simultaneous convergence (AND-join)
# ---------------------------------------------------------------------------


class TestSimultaneousConvergence:
    def test_and_join(self):
        """Transition only fires when ALL source steps are active."""

        @sfc
        class Join:
            go: Input[BOOL]
            done_flag: Input[BOOL]
            IDLE = step(initial=True)
            A = step()
            B = step()
            DONE = step()

            @transition(IDLE >> (A & B))
            def start(self):
                return self.go

            @transition((A & B) >> DONE)
            def join(self):
                return self.done_flag

            @transition(DONE >> IDLE)
            def reset(self):
                return True

        ctx = simulate(Join)
        ctx.scan()
        ctx.go = True
        ctx.scan()  # fork to A & B
        assert ctx.active_steps == {"A", "B"}
        ctx.done_flag = True
        ctx.scan()  # join — both active, condition true
        assert ctx.active_steps == {"DONE"}


# ---------------------------------------------------------------------------
# Multi-step sequence
# ---------------------------------------------------------------------------


class TestMultiStepSequence:
    def test_full_cycle(self):
        @sfc
        class Fill:
            start_cmd: Input[BOOL]
            level: Input[REAL]
            inlet_valve: Output[BOOL]
            drain_valve: Output[BOOL]

            IDLE = step(initial=True)
            FILLING = step()
            DRAINING = step()

            @IDLE.action
            def idle_act(self):
                self.inlet_valve = False
                self.drain_valve = False

            @FILLING.action
            def fill_act(self):
                self.inlet_valve = True

            @DRAINING.action
            def drain_act(self):
                self.drain_valve = True

            @transition(IDLE >> FILLING)
            def start(self):
                return self.start_cmd

            @transition(FILLING >> DRAINING)
            def full(self):
                return self.level > 90.0

            @transition(DRAINING >> IDLE)
            def empty(self):
                return self.level < 10.0

        ctx = simulate(Fill)

        # IDLE
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}
        assert ctx.inlet_valve is False
        assert ctx.drain_valve is False

        # Start filling
        ctx.start_cmd = True
        ctx.scan()
        assert ctx.active_steps == {"FILLING"}
        ctx.scan()  # N action runs
        assert ctx.inlet_valve is True

        # Tank full
        ctx.level = 95.0
        ctx.scan()
        assert ctx.active_steps == {"DRAINING"}
        ctx.scan()
        assert ctx.drain_valve is True

        # Tank empty
        ctx.level = 5.0
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}
        ctx.scan()
        assert ctx.inlet_valve is False
        assert ctx.drain_valve is False


# ---------------------------------------------------------------------------
# Time-based qualifiers
# ---------------------------------------------------------------------------


class TestTimeQualifiers:
    def test_l_time_limited(self):
        """L qualifier: action runs while step active AND elapsed < duration."""

        @sfc
        class LTest:
            go: Input[BOOL]
            out: Output[BOOL]
            IDLE = step(initial=True)
            RUN = step()

            @RUN.action(qualifier="L", duration=timedelta(milliseconds=100))
            def limited(self):
                self.out = True

            @transition(IDLE >> RUN)
            def start(self):
                return self.go

            @transition(RUN >> IDLE)
            def stop(self):
                return False

        ctx = simulate(LTest, scan_period_ms=10)
        ctx.scan()  # init IDLE
        ctx.go = True
        ctx.scan()  # transition to RUN (entry_time = 10ms, just_activated)

        # L action should run while elapsed < 100ms
        ctx.scan()  # clock=20ms, elapsed=10ms < 100ms
        assert ctx.out is True

        # Reset and scan past duration
        ctx.out = False
        ctx.scan(8)  # clock=100ms, elapsed=90ms → still running at clock 90ms
        # Actually let's check more carefully. step entry at clock 10ms.
        # After 8 more scans: clock = 20+80 = 100ms. elapsed = 100-10 = 90ms < 100. still runs.
        assert ctx.out is True

        ctx.out = False
        ctx.scan(2)  # clock = 120ms, elapsed = 110ms >= 100ms → stops
        assert ctx.out is False

    def test_d_time_delayed(self):
        """D qualifier: action starts after duration while step still active."""

        @sfc
        class DTest:
            go: Input[BOOL]
            out: Output[BOOL]
            IDLE = step(initial=True)
            RUN = step()

            @RUN.action(qualifier="D", duration=timedelta(milliseconds=50))
            def delayed_act(self):
                self.out = True

            @transition(IDLE >> RUN)
            def start(self):
                return self.go

            @transition(RUN >> IDLE)
            def stop(self):
                return False

        ctx = simulate(DTest, scan_period_ms=10)
        ctx.scan()  # init
        ctx.go = True
        ctx.scan()  # transition to RUN at clock=10ms

        # Before delay
        ctx.out = False
        ctx.scan()  # clock=20, elapsed=10 < 50
        assert ctx.out is False

        # After delay
        ctx.scan(4)  # clock=60, elapsed=50 >= 50
        assert ctx.out is True

    def test_s_stored_and_r_reset(self):
        """S qualifier: action persists after step deactivation. R stops it."""

        @sfc
        class SRTest:
            go: Input[BOOL]
            reset_flag: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            ACTIVE = step()
            RESET_STEP = step()

            @ACTIVE.action(qualifier="S")
            def stored_act(self):
                self.out = True

            @RESET_STEP.action(qualifier="R", resets="stored_act")
            def reset_act(self):
                pass  # R doesn't need a body — it resets the stored action

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.go

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return not self.go

            @transition(IDLE >> RESET_STEP)
            def do_reset(self):
                return self.reset_flag

            @transition(RESET_STEP >> IDLE)
            def back(self):
                return True

        ctx = simulate(SRTest, scan_period_ms=10)
        ctx.scan()  # init

        # Activate stored action
        ctx.go = True
        ctx.scan()  # → ACTIVE (just_activated, S action starts stored)
        ctx.scan()  # stored action runs
        assert ctx.out is True

        # Deactivate step — stored action should persist
        ctx.go = False
        ctx.scan()  # → IDLE
        ctx.scan()  # stored action still runs
        assert ctx.out is True

        # Reset
        ctx.reset_flag = True
        ctx.scan()  # → RESET_STEP (R qualifier resets stored_act)
        ctx.out = False
        ctx.scan()  # stored action no longer running
        assert ctx.out is False

    def test_sd_stored_delayed(self):
        """SD qualifier: becomes stored after delay, even if step deactivates."""

        @sfc
        class SDTest:
            go: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            ACTIVE = step()

            @ACTIVE.action(qualifier="SD", duration=timedelta(milliseconds=50))
            def sd_act(self):
                self.out = True

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.go

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return not self.go

        ctx = simulate(SDTest, scan_period_ms=10)
        ctx.scan()  # init IDLE

        # Activate step — SD timer starts
        ctx.go = True
        ctx.scan()  # → ACTIVE (just_activated, SD timer starts at clock=10)
        ctx.scan()  # clock=20, SD elapsed=10 < 50 → not stored yet
        assert ctx.out is False

        # Deactivate step BEFORE delay expires
        ctx.go = False
        ctx.scan()  # clock=30, transition ACTIVE→IDLE, SD timer still pending
        ctx.scan()  # clock=40, SD elapsed=30 < 50 → still not stored

        # Wait for delay to expire (SD should fire even though step is inactive)
        ctx.scan()  # clock=50, SD elapsed=40 < 50
        ctx.scan()  # clock=60, SD elapsed=50 >= 50 → becomes stored!
        ctx.scan()  # clock=70, stored action runs
        assert ctx.out is True

    def test_ds_delayed_stored_cancelled_on_deactivation(self):
        """DS qualifier: cancelled if step deactivates before delay expires."""

        @sfc
        class DSTest:
            go: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            ACTIVE = step()

            @ACTIVE.action(qualifier="DS", duration=timedelta(milliseconds=50))
            def ds_act(self):
                self.out = True

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.go

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return not self.go

        ctx = simulate(DSTest, scan_period_ms=10)
        ctx.scan()  # init IDLE

        # Activate step — DS timer starts
        ctx.go = True
        ctx.scan()  # → ACTIVE (just_activated, DS timer starts)
        ctx.scan()  # clock=20, DS elapsed=10 < 50

        # Deactivate step BEFORE delay — DS should be cancelled
        ctx.go = False
        ctx.scan()  # clock=30, transition ACTIVE→IDLE, DS timer cancelled
        ctx.scan(5)  # wait well past the delay
        assert ctx.out is False  # DS never became stored

    def test_ds_delayed_stored_fires_when_step_active(self):
        """DS qualifier: becomes stored after delay if step stays active."""

        @sfc
        class DSTest2:
            go: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            ACTIVE = step()

            @ACTIVE.action(qualifier="DS", duration=timedelta(milliseconds=50))
            def ds_act(self):
                self.out = True

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.go

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return not self.go

        ctx = simulate(DSTest2, scan_period_ms=10)
        ctx.scan()  # init IDLE

        ctx.go = True
        ctx.scan()  # → ACTIVE (DS timer starts at clock=10)
        ctx.scan(5)  # clock=20..60, wait for delay (elapsed=50 at clock=60)
        ctx.scan()  # clock=70, stored action runs
        assert ctx.out is True

        # Deactivate — stored action should persist
        ctx.go = False
        ctx.out = False
        ctx.scan()  # transition ACTIVE→IDLE
        ctx.scan()  # stored action still runs
        assert ctx.out is True

    def test_sl_stored_time_limited(self):
        """SL qualifier: stored action expires after duration."""

        @sfc
        class SLTest:
            go: Input[BOOL]
            out: Output[BOOL]

            IDLE = step(initial=True)
            ACTIVE = step()

            @ACTIVE.action(qualifier="SL", duration=timedelta(milliseconds=50))
            def sl_act(self):
                self.out = True

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.go

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return not self.go

        ctx = simulate(SLTest, scan_period_ms=10)
        ctx.scan()  # init IDLE

        # Activate step — SL stored action starts
        ctx.go = True
        ctx.scan()  # → ACTIVE (just_activated, SL starts stored at clock=10)
        ctx.scan()  # clock=20, stored action runs (elapsed=10 < 50)
        assert ctx.out is True

        # Deactivate step — SL should persist but with time limit
        ctx.go = False
        ctx.out = False
        ctx.scan()  # clock=30, transition ACTIVE→IDLE, stored action runs
        ctx.scan()  # clock=40, elapsed=30 < 50, stored runs
        assert ctx.out is True

        # Wait for SL to expire
        ctx.out = False
        ctx.scan()  # clock=50, elapsed=40 < 50, runs
        ctx.scan()  # clock=60, elapsed=50 >= 50, expires!
        ctx.out = False
        ctx.scan()  # clock=70, no longer stored
        assert ctx.out is False

    def test_sl_does_not_restart_while_step_active(self):
        """SL qualifier must not restart after expiring while step is still active."""

        @sfc
        class SLRestart:
            go: Input[BOOL]
            count: INT = 0

            IDLE = step(initial=True)
            ACTIVE = step()

            @ACTIVE.action(qualifier="SL", duration=timedelta(milliseconds=30))
            def sl_act(self):
                self.count = self.count + 1

            @transition(IDLE >> ACTIVE)
            def activate(self):
                return self.go

            @transition(ACTIVE >> IDLE)
            def deactivate(self):
                return False  # stay in ACTIVE

        ctx = simulate(SLRestart, scan_period_ms=10)
        ctx.scan()  # init

        ctx.go = True
        ctx.scan()  # → ACTIVE (just_activated set, SL starts next scan)
        ctx.scan()  # clock=20, SL registered (start_time=20), elapsed=0 < 30, runs (count=1)
        ctx.scan()  # clock=30, elapsed=10 < 30, runs (count=2)
        ctx.scan()  # clock=40, elapsed=20 < 30, runs (count=3)
        ctx.scan()  # clock=50, elapsed=30 >= 30, expires (count stays 3)

        # Keep scanning — SL must NOT restart
        ctx.scan(5)  # clock=60..100
        assert ctx.count == 3  # no additional runs after expiration


# ---------------------------------------------------------------------------
# Sentinel functions in actions
# ---------------------------------------------------------------------------


class TestSentinelsInActions:
    def test_delayed_in_action(self):
        @sfc
        class SentinelSfc:
            cmd: Input[BOOL]
            out: Output[BOOL]
            S0 = step(initial=True)

            @S0.action
            def act(self):
                self.out = delayed(self.cmd, timedelta(seconds=1))

        ctx = simulate(SentinelSfc, scan_period_ms=10)
        ctx.cmd = True
        ctx.scan()
        assert ctx.out is False  # timer not elapsed
        ctx.tick(seconds=1)
        assert ctx.out is True


# ---------------------------------------------------------------------------
# active_steps property
# ---------------------------------------------------------------------------


class TestActiveSteps:
    def test_active_steps_returns_correct_set(self):
        @sfc
        class Steps:
            go: Input[BOOL]
            IDLE = step(initial=True)
            RUN = step()

            @transition(IDLE >> RUN)
            def start(self):
                return self.go

            @transition(RUN >> IDLE)
            def stop(self):
                return not self.go

        ctx = simulate(Steps)
        assert ctx.active_steps == set()  # before first scan
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}
        ctx.go = True
        ctx.scan()
        assert ctx.active_steps == {"RUN"}
        ctx.go = False
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}

    def test_active_steps_non_sfc_empty(self):
        """Non-SFC POUs return empty set."""
        from plx.framework import fb

        @fb
        class Plain:
            x: Input[BOOL]

            def logic(self):
                pass

        ctx = simulate(Plain)
        ctx.scan()
        assert ctx.active_steps == set()


# ---------------------------------------------------------------------------
# Integration: end-to-end
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_end_to_end_fill_sequence(self):
        @sfc
        class FillSeq:
            start: Input[BOOL]
            level: Input[REAL]
            valve: Output[BOOL]
            fill_count: INT = 0

            IDLE = step(initial=True)
            FILLING = step()

            @IDLE.action
            def idle_act(self):
                self.valve = False

            @FILLING.entry
            def filling_entry(self):
                self.fill_count = self.fill_count + 1

            @FILLING.action
            def filling_act(self):
                self.valve = True

            @transition(IDLE >> FILLING)
            def begin(self):
                return self.start

            @transition(FILLING >> IDLE)
            def done(self):
                return self.level > 100.0

        ctx = simulate(FillSeq)

        # Start idle
        ctx.scan()
        assert ctx.valve is False
        assert ctx.fill_count == 0

        # Start fill cycle
        ctx.start = True
        ctx.scan()
        assert ctx.active_steps == {"FILLING"}
        ctx.scan()
        assert ctx.valve is True
        assert ctx.fill_count == 1

        # Complete fill
        ctx.level = 110.0
        ctx.scan()
        assert ctx.active_steps == {"IDLE"}
        ctx.scan()
        assert ctx.valve is False

        # Second fill cycle
        ctx.level = 0.0
        ctx.scan()  # still IDLE, transition fires
        assert ctx.active_steps == {"FILLING"}
        ctx.scan()
        assert ctx.fill_count == 2

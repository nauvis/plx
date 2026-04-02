"""ScanTrigger: compositional scan-loop builder (Amaranth-inspired).

Synchronous (not async) — PLC scans are sequential, and AI writes
better sync Python.  Every builder method returns a new ``ScanTrigger``
(immutable builder pattern).  ``.run()`` executes the trigger loop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ._trace import ScanTrace

if TYPE_CHECKING:
    from ._context import SimulationContext


class SimulationTimeout(Exception):
    """Raised when a trigger's timeout expires before the condition is met."""


class ScanTrigger:
    """Immutable builder for declarative scan loops.

    Created via ``ctx.scans()``.  Chain builder methods, then call
    ``.run()`` to execute.

    Parameters
    ----------
    ctx : SimulationContext
        The simulation context that executes scans.
    max_scans : int or None
        Maximum number of scans to execute, or ``None`` for unlimited.
    condition : callable or None
        A callable ``(SimulationContext) -> object`` that terminates the loop
        when it returns a truthy value.
    changed_vars : tuple of str or None
        Variable names to monitor; the loop terminates when any value changes.
    sample_vars : tuple of str or None
        Variable names to capture into the trace each scan.
    sample_all : bool
        If ``True``, capture all known variables each scan.
    timeout_ms : int or None
        Simulated-time deadline in milliseconds, or ``None`` for no timeout.

    Examples
    --------
    ::

        # Scan 100 times, capture speed each scan
        trace = ctx.scans().repeat(100).sample("speed").run()
        speeds = trace.values_of("speed")

        # Scan until output goes True, with 10s timeout
        ctx.scans().until(lambda c: c.running).timeout(seconds=10).run()
        assert ctx.running

        # Scan until a variable changes
        ctx.scans().changed("state").timeout(seconds=5).run()
    """

    __slots__ = (
        "_ctx",
        "_max_scans",
        "_condition",
        "_changed_vars",
        "_sample_vars",
        "_sample_all",
        "_timeout_ms",
    )

    def __init__(
        self,
        ctx: SimulationContext,
        *,
        max_scans: int | None = None,
        condition: Callable[[SimulationContext], object] | None = None,
        changed_vars: tuple[str, ...] | None = None,
        sample_vars: tuple[str, ...] | None = None,
        sample_all: bool = False,
        timeout_ms: int | None = None,
    ) -> None:
        self._ctx = ctx
        self._max_scans = max_scans
        self._condition = condition
        self._changed_vars = changed_vars
        self._sample_vars = sample_vars
        self._sample_all = sample_all
        self._timeout_ms = timeout_ms

    # -- builder methods (each returns a NEW trigger) ----------------------

    def repeat(self, n: int) -> ScanTrigger:
        """Scan exactly *n* times.

        Parameters
        ----------
        n : int
            Number of scans to execute.

        Returns
        -------
        ScanTrigger
            New trigger with the repeat count set.
        """
        return ScanTrigger(
            self._ctx,
            max_scans=n,
            condition=self._condition,
            changed_vars=self._changed_vars,
            sample_vars=self._sample_vars,
            sample_all=self._sample_all,
            timeout_ms=self._timeout_ms,
        )

    def until(self, condition: Callable[[SimulationContext], object]) -> ScanTrigger:
        """Scan until ``condition(ctx)`` is truthy.

        Parameters
        ----------
        condition : callable
            A callable ``(SimulationContext) -> object`` evaluated after each
            scan.  The loop terminates when the return value is truthy.

        Returns
        -------
        ScanTrigger
            New trigger with the until-condition set.
        """
        return ScanTrigger(
            self._ctx,
            max_scans=self._max_scans,
            condition=condition,
            changed_vars=self._changed_vars,
            sample_vars=self._sample_vars,
            sample_all=self._sample_all,
            timeout_ms=self._timeout_ms,
        )

    def changed(self, *var_names: str) -> ScanTrigger:
        """Scan until any of *var_names* changes value.

        Parameters
        ----------
        *var_names : str
            One or more variable names to monitor for changes.

        Returns
        -------
        ScanTrigger
            New trigger with change-detection enabled for the given variables.
        """
        return ScanTrigger(
            self._ctx,
            max_scans=self._max_scans,
            condition=self._condition,
            changed_vars=var_names,
            sample_vars=self._sample_vars,
            sample_all=self._sample_all,
            timeout_ms=self._timeout_ms,
        )

    def sample(self, *var_names: str) -> ScanTrigger:
        """Capture the listed variables per scan into the returned trace.

        Parameters
        ----------
        *var_names : str
            Variable names to record in each snapshot.

        Returns
        -------
        ScanTrigger
            New trigger with the sample list set.
        """
        return ScanTrigger(
            self._ctx,
            max_scans=self._max_scans,
            condition=self._condition,
            changed_vars=self._changed_vars,
            sample_vars=var_names,
            sample_all=self._sample_all,
            timeout_ms=self._timeout_ms,
        )

    def sample_all(self) -> ScanTrigger:
        """Capture all variables per scan into the returned trace.

        Returns
        -------
        ScanTrigger
            New trigger with full-state sampling enabled.
        """
        return ScanTrigger(
            self._ctx,
            max_scans=self._max_scans,
            condition=self._condition,
            changed_vars=self._changed_vars,
            sample_vars=self._sample_vars,
            sample_all=True,
            timeout_ms=self._timeout_ms,
        )

    def timeout(self, *, seconds: float = 0, ms: float = 0) -> ScanTrigger:
        """Set a maximum wall-clock-equivalent timeout.

        Measured in simulated time.  Raises ``SimulationTimeout`` if the
        termination condition isn't met before the timeout elapses.

        Parameters
        ----------
        seconds : float
            Timeout duration in seconds (added to *ms*).
        ms : float
            Timeout duration in milliseconds (added to *seconds*).

        Returns
        -------
        ScanTrigger
            New trigger with the timeout set.

        Raises
        ------
        ValueError
            If the total timeout is not positive.
        """
        total = int(seconds * 1000 + ms)
        if total <= 0:
            raise ValueError("timeout must be positive")
        return ScanTrigger(
            self._ctx,
            max_scans=self._max_scans,
            condition=self._condition,
            changed_vars=self._changed_vars,
            sample_vars=self._sample_vars,
            sample_all=self._sample_all,
            timeout_ms=total,
        )

    # -- execution ---------------------------------------------------------

    def run(self) -> ScanTrace:
        """Execute the trigger loop and return the captured trace.

        Loops calling ``ctx.scan(n=1)`` until the termination condition
        is met (repeat count, until-condition, changed-variable, or
        timeout).  If no termination condition is set, raises ValueError.

        Returns
        -------
        ScanTrace
            Trace containing snapshots captured during the run.  Empty if
            no sampling was configured.

        Raises
        ------
        SimulationTimeout
            If a timeout was set alongside an until-condition or
            changed-variable monitor and the deadline elapsed first.
        ValueError
            If no termination condition was configured.
        """
        ctx = self._ctx
        trace = ScanTrace()

        has_termination = self._max_scans is not None or self._condition is not None or self._changed_vars is not None
        if not has_termination and self._timeout_ms is None:
            raise ValueError(
                "ScanTrigger has no termination condition. "
                "Use .repeat(n), .until(fn), .changed('var'), or .timeout(seconds=N)."
            )

        # Snapshot "before" values for .changed() detection
        state = object.__getattribute__(ctx, "_state")
        if self._changed_vars:
            prev_values = {v: state.get(v) for v in self._changed_vars}

        # Compute timeout deadline
        start_clock = object.__getattribute__(ctx, "_clock_ms")
        deadline_ms = (start_clock + self._timeout_ms) if self._timeout_ms else None

        scans_done = 0
        do_sample = self._sample_vars is not None or self._sample_all

        while True:
            # Check repeat limit
            if self._max_scans is not None and scans_done >= self._max_scans:
                break

            # Execute one scan
            ctx.scan(n=1)
            scans_done += 1

            # Capture trace if sampling
            if do_sample:
                if self._sample_all:
                    trace.capture(ctx)
                elif self._sample_vars:
                    trace.capture_vars(ctx, self._sample_vars)

            # Check until-condition
            if self._condition is not None and self._condition(ctx):
                break

            # Check changed-vars
            if self._changed_vars:
                state = object.__getattribute__(ctx, "_state")
                for v in self._changed_vars:
                    curr = state.get(v)
                    if curr != prev_values.get(v):
                        # Return — at least one var changed
                        return trace
                # Update prev for next iteration
                prev_values = {v: state.get(v) for v in self._changed_vars}

            # Check timeout
            if deadline_ms is not None:
                current_clock = object.__getattribute__(ctx, "_clock_ms")
                if current_clock >= deadline_ms:
                    # If there's no other termination condition, this is an error
                    if self._condition is not None or self._changed_vars is not None:
                        raise SimulationTimeout(
                            f"Trigger timed out after {self._timeout_ms}ms simulated time ({scans_done} scans)"
                        )
                    # timeout-only trigger: just stop
                    break

        return trace

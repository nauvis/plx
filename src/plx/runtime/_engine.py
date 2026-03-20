"""Real-time scan loop wrapping ProjectSimulationContext.

The RuntimeEngine drives the existing simulation infrastructure with
wall-clock timing instead of manual scan() calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from plx.model.project import Project
from plx.simulate._project_context import ProjectSimulationContext

logger = logging.getLogger("plx.runtime")


@dataclass
class ScanStats:
    """Accumulated scan timing statistics."""

    total_scans: int = 0
    total_duration_us: float = 0.0
    max_duration_us: float = 0.0
    overrun_count: int = 0

    @property
    def avg_duration_us(self) -> float:
        if self.total_scans == 0:
            return 0.0
        return self.total_duration_us / self.total_scans


class RuntimeEngine:
    """Wall-clock-driven scan loop wrapping ProjectSimulationContext.

    Runs on an asyncio event loop. Each tick executes one base-period
    scan synchronously, then sleeps until the next scan is due.
    """

    def __init__(self, project_ir: Project, *, scan_period_ms: int = 10) -> None:
        self._project_ir = project_ir
        self._scan_period_ms = scan_period_ms
        self._sim = ProjectSimulationContext(
            project_ir, scan_period_ms=scan_period_ms,
        )
        self._stats = ScanStats()
        self._running = False
        self._scan_task: asyncio.Task | None = None

    @property
    def project_name(self) -> str:
        return self._project_ir.name

    @property
    def scan_period_ms(self) -> int:
        return self._sim._base_period_ms

    @property
    def stats(self) -> ScanStats:
        return self._stats

    @property
    def running(self) -> bool:
        return self._running

    @property
    def program_names(self) -> list[str]:
        return list(self._sim._programs.keys())

    def read_variable(self, path: str) -> object:
        """Read a variable by dotted path.

        Supports:
        - "ProgramName.var_name" — program variable
        - "ProgramName.fb_instance.member" — nested FB member
        - "GVL.var_name" — global variable
        """
        parts = path.split(".", 1)
        if len(parts) < 2:
            raise KeyError(f"Variable path must be 'scope.name', got '{path}'")

        scope, rest = parts

        # Try program first
        if scope in self._sim._programs:
            return self._resolve_nested(self._sim._programs[scope]._state, rest)

        # Try GVL
        if scope in self._sim._global_state:
            return self._resolve_nested(self._sim._global_state[scope], rest)

        raise KeyError(
            f"Unknown scope '{scope}'. "
            f"Available programs: {list(self._sim._programs.keys())}, "
            f"GVLs: {list(self._sim._global_state.keys())}"
        )

    def write_variable(self, path: str, value: object) -> None:
        """Write a variable by dotted path (same format as read_variable)."""
        parts = path.split(".", 1)
        if len(parts) < 2:
            raise KeyError(f"Variable path must be 'scope.name', got '{path}'")

        scope, rest = parts

        # Try program first
        if scope in self._sim._programs:
            self._set_nested(self._sim._programs[scope]._state, rest, value)
            return

        # Try GVL
        if scope in self._sim._global_state:
            self._set_nested(self._sim._global_state[scope], rest, value)
            return

        raise KeyError(
            f"Unknown scope '{scope}'. "
            f"Available programs: {list(self._sim._programs.keys())}, "
            f"GVLs: {list(self._sim._global_state.keys())}"
        )

    def _resolve_nested(self, state: dict, path: str) -> object:
        """Walk a dotted path through nested dicts."""
        parts = path.split(".")
        current: object = state
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    raise KeyError(f"Key '{part}' not found in {path}")
                current = current[part]
            else:
                raise KeyError(f"Cannot traverse into non-dict at '{part}' in {path}")
        return current

    def _set_nested(self, state: dict, path: str, value: object) -> None:
        """Set a value at a dotted path through nested dicts."""
        parts = path.split(".")
        current = state
        for part in parts[:-1]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise KeyError(f"Key '{part}' not found in path")
        if not isinstance(current, dict):
            raise KeyError(f"Cannot set value on non-dict at '{parts[-2]}'")
        current[parts[-1]] = value

    def _execute_one_scan(self) -> None:
        """Execute a single scan and record timing."""
        t0 = time.perf_counter_ns()
        self._sim._execute_one_scan()
        elapsed_us = (time.perf_counter_ns() - t0) / 1000.0

        self._stats.total_scans += 1
        self._stats.total_duration_us += elapsed_us
        if elapsed_us > self._stats.max_duration_us:
            self._stats.max_duration_us = elapsed_us

        if elapsed_us > self._sim._base_period_ms * 1000:
            self._stats.overrun_count += 1

    async def _scan_loop(self) -> None:
        """Main scan loop — runs until stopped."""
        period_s = self._sim._base_period_ms / 1000.0
        next_scan = time.monotonic()

        while self._running:
            self._execute_one_scan()

            next_scan += period_s
            now = time.monotonic()
            delay = next_scan - now
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                # Overrun — reset next_scan to avoid cascading drift
                next_scan = now

    async def start(self) -> None:
        """Start the scan loop as an async task."""
        if self._running:
            return
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(
            "Scan loop started: %dms period, programs: %s",
            self.scan_period_ms,
            ", ".join(self.program_names),
        )

    async def stop(self) -> None:
        """Stop the scan loop."""
        self._running = False
        if self._scan_task is not None:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        logger.info("Scan loop stopped after %d scans", self._stats.total_scans)

    def reload(self, new_ir: Project) -> None:
        """Swap to a new Project IR, preserving compatible state.

        Variables that exist in both old and new IR with compatible types
        keep their values. Everything else re-initializes.
        """
        old_programs = self._sim._programs
        old_global_state = dict(self._sim._global_state)

        # Create new simulation context
        self._project_ir = new_ir
        self._sim = ProjectSimulationContext(
            new_ir, scan_period_ms=self._scan_period_ms,
        )

        # Restore compatible program state
        for name, new_ctx in self._sim._programs.items():
            if name in old_programs:
                old_state = old_programs[name]._state
                for var_name in new_ctx._known_vars:
                    if var_name in old_state:
                        old_val = old_state[var_name]
                        new_val = new_ctx._state.get(var_name)
                        # Only restore if same type
                        if type(old_val) is type(new_val):
                            new_ctx._state[var_name] = old_val

        # Restore compatible GVL state
        for gvl_name, new_gvl in self._sim._global_state.items():
            if gvl_name in old_global_state:
                old_gvl = old_global_state[gvl_name]
                for var_name, new_val in new_gvl.items():
                    if var_name in old_gvl:
                        old_val = old_gvl[var_name]
                        if type(old_val) is type(new_val):
                            new_gvl[var_name] = old_val

        logger.info("Reloaded project '%s'", new_ir.name)

    def get_all_variables(self) -> dict[str, dict[str, object]]:
        """Return all variable values organized by scope.

        Returns a dict like:
        {
            "Programs.MainProgram": {"var1": value, ...},
            "GVLs.IO": {"sensor1": value, ...},
        }
        """
        result: dict[str, dict[str, object]] = {}

        for name, ctx in self._sim._programs.items():
            prog_vars: dict[str, object] = {}
            for var_name in ctx._known_vars:
                if var_name in ctx._state:
                    prog_vars[var_name] = ctx._state[var_name]
            result[f"Programs.{name}"] = prog_vars

        for gvl_name, gvl_state in self._sim._global_state.items():
            result[f"GVLs.{gvl_name}"] = dict(gvl_state)

        return result

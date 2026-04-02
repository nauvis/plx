"""Terminal status display for the plx runtime."""

from __future__ import annotations

import asyncio
import logging
import sys

from ._engine import RuntimeEngine

logger = logging.getLogger("plx.runtime")


def _format_duration(us: float) -> str:
    """Format a duration in microseconds to a human-readable string."""
    if us < 1000:
        return f"{us:.0f}us"
    elif us < 1_000_000:
        return f"{us / 1000:.1f}ms"
    else:
        return f"{us / 1_000_000:.2f}s"


class ConsoleDisplay:
    """Periodic status output to the terminal."""

    def __init__(
        self,
        engine: RuntimeEngine,
        *,
        interval: float = 2.0,
        opcua_info: str = "",
    ) -> None:
        self._engine = engine
        self._interval = interval
        self._opcua_info = opcua_info
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._display_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _display_loop(self) -> None:
        try:
            while True:
                self._print_status()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    def _print_status(self) -> None:
        engine = self._engine
        stats = engine.stats

        lines = [
            f"\nplx runtime | {engine.project_name}",
            f"  Scan: {engine.scan_period_ms}ms period | {stats.total_scans} scans | {stats.overrun_count} overruns",
            f"  Timing: avg {_format_duration(stats.avg_duration_us)} | max {_format_duration(stats.max_duration_us)}",
            f"  Programs: {', '.join(engine.program_names)}",
        ]

        if self._opcua_info:
            lines.append(f"  OPC-UA: {self._opcua_info}")

        sys.stderr.write("\n".join(lines) + "\n")
        sys.stderr.flush()

    def print_startup(self) -> None:
        """Print one-time startup banner."""
        engine = self._engine
        lines = [
            f"plx runtime starting | {engine.project_name}",
            f"  Scan period: {engine.scan_period_ms}ms",
            f"  Programs: {', '.join(engine.program_names)}",
        ]
        if self._opcua_info:
            lines.append(f"  OPC-UA: {self._opcua_info}")
        lines.append("")
        sys.stderr.write("\n".join(lines) + "\n")
        sys.stderr.flush()

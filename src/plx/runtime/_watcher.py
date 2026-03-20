"""File watching for hot reload.

Uses watchfiles (Rust-backed) for efficient filesystem monitoring.
Gracefully degrades if watchfiles is not installed.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Awaitable

logger = logging.getLogger("plx.runtime")

try:
    from watchfiles import awatch, Change

    _HAS_WATCHFILES = True
except ImportError:
    _HAS_WATCHFILES = False


class FileWatcher:
    """Watch project source files and trigger reload on changes.

    Parameters
    ----------
    source_path : Path
        File or directory to watch for ``.py`` changes.
    project_path : str
        Dotted import path passed to the reload callback.
    on_reload : Callable[[str], Awaitable[None]]
        Async callback invoked with *project_path* when changes are detected.
    debounce_ms : int, optional
        Minimum interval between reload triggers in milliseconds, by default 250.
    """

    def __init__(
        self,
        source_path: Path,
        project_path: str,
        on_reload: Callable[[str], Awaitable[None]],
        *,
        debounce_ms: int = 250,
    ) -> None:
        if not _HAS_WATCHFILES:
            raise RuntimeError(
                "watchfiles is not installed. "
                "Install with: pip install plx-controls[runtime]"
            )

        self._source_path = source_path
        self._project_path = project_path
        self._on_reload = on_reload
        self._debounce_ms = debounce_ms
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the file-watching background task."""
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("File watcher started for %s", self._source_path)

    async def stop(self) -> None:
        """Cancel the file-watching background task."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch_loop(self) -> None:
        try:
            watch_path = self._source_path
            if watch_path.is_file():
                watch_path = watch_path.parent

            async for changes in awatch(
                watch_path,
                debounce=self._debounce_ms,
                step=100,
            ):
                # Filter for .py changes only
                py_changes = [
                    (change, path) for change, path in changes
                    if path.endswith(".py")
                ]
                if not py_changes:
                    continue

                changed_files = [path for _, path in py_changes]
                logger.info(
                    "Detected changes in: %s",
                    ", ".join(Path(f).name for f in changed_files),
                )

                await self._on_reload(self._project_path)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("File watcher error: %s", exc)

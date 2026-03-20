"""plx runtime — soft PLC with OPC-UA and plant co-simulation.

Start a runtime from the CLI::

    plx run my_machine/
    plx run examples/batch_mix.py --port 4840
    plx run project.plx.json --plant tank_model.py

Or programmatically::

    from plx.runtime import run
    run("my_machine/", port=4840)
"""

from __future__ import annotations

import asyncio

from ._engine import RuntimeEngine, ScanStats
from ._plant import PlantModel, PlantIO, plant


def run(
    project_path: str,
    *,
    port: int = 4840,
    enable_opcua: bool = True,
    enable_watch: bool = True,
    plant_files: list[str] | None = None,
    scan_period_ms: int = 10,
    quiet: bool = False,
) -> None:
    """Run a plx project as a soft PLC runtime.

    Blocks until interrupted (Ctrl+C or SIGTERM).

    Parameters
    ----------
    project_path : str
        Path to project directory, .py file, or .plx.json file.
    port : int
        OPC-UA server port (default 4840).
    enable_opcua : bool
        Enable OPC-UA server (default True).
    enable_watch : bool
        Enable file watching for hot reload (default True).
    plant_files : list[str] | None
        Paths to plant model scripts.
    scan_period_ms : int
        Override scan period in milliseconds (default 10).
    quiet : bool
        Minimal output.
    """
    from ._cli import _run

    asyncio.run(_run(
        project_path=project_path,
        port=port,
        enable_opcua=enable_opcua,
        enable_watch=enable_watch,
        plant_files=plant_files or [],
        scan_period_ms=scan_period_ms,
        quiet=quiet,
    ))


__all__ = [
    "run",
    "RuntimeEngine",
    "ScanStats",
    "PlantModel",
    "PlantIO",
    "plant",
]

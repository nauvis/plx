"""CLI entry point for ``plx run``.

Examples
--------
::

    plx run <project_path> [options]

    Options:
      --port PORT          OPC-UA port (default: 4840)
      --no-opcua           Disable OPC-UA server
      --no-watch           Disable hot reload
      --plant FILE         Plant model script (repeatable)
      --scan-rate RATE     Override scan period (e.g. "10ms")
      --quiet              Minimal output
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys


def _parse_scan_rate(rate_str: str) -> int:
    """Parse a scan rate string like '10ms' or '100us' to milliseconds."""
    rate_str = rate_str.strip().lower()
    if rate_str.endswith("ms"):
        return int(rate_str[:-2])
    elif rate_str.endswith("us"):
        return max(1, int(rate_str[:-2]) // 1000)
    elif rate_str.endswith("s"):
        return int(float(rate_str[:-1]) * 1000)
    else:
        return int(rate_str)


def main(argv: list[str] | None = None) -> None:
    """Main entry point for ``plx run``."""
    parser = argparse.ArgumentParser(
        prog="plx run",
        description="Run a plx project as a soft PLC runtime",
    )
    parser.add_argument(
        "project_path",
        help="Path to project directory, .py file, or .plx.json file",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4840,
        help="OPC-UA server port (default: 4840)",
    )
    parser.add_argument(
        "--no-opcua",
        action="store_true",
        help="Disable OPC-UA server",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Disable file watching / hot reload",
    )
    parser.add_argument(
        "--plant",
        action="append",
        default=[],
        metavar="FILE",
        help="Plant model script (can be specified multiple times)",
    )
    parser.add_argument(
        "--scan-rate",
        default=None,
        metavar="RATE",
        help="Override scan period (e.g. '10ms', '100ms', '1s')",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output",
    )

    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    scan_period_ms = _parse_scan_rate(args.scan_rate) if args.scan_rate else 10

    try:
        asyncio.run(_run(
            project_path=args.project_path,
            port=args.port,
            enable_opcua=not args.no_opcua,
            enable_watch=not args.no_watch,
            plant_files=args.plant,
            scan_period_ms=scan_period_ms,
            quiet=args.quiet,
        ))
    except KeyboardInterrupt:
        pass


async def _run(
    *,
    project_path: str,
    port: int,
    enable_opcua: bool,
    enable_watch: bool,
    plant_files: list[str],
    scan_period_ms: int,
    quiet: bool,
) -> None:
    """Main async runtime loop."""
    from ._loader import load_project, reload_project
    from ._engine import RuntimeEngine
    from ._console import ConsoleDisplay
    from ._plant import PlantRunner, load_plant_models

    logger = logging.getLogger("plx.runtime")

    # Load project
    try:
        project_ir, source_path = load_project(project_path)
    except Exception as exc:
        logger.error("Failed to load project: %s", exc)
        sys.exit(1)

    # Create engine
    engine = RuntimeEngine(project_ir, scan_period_ms=scan_period_ms)

    # OPC-UA server (optional)
    opcua_server = None
    opcua_info = ""
    if enable_opcua:
        try:
            from ._opcua import OPCUAServer
            opcua_server = OPCUAServer(engine, port=port)
            opcua_info = opcua_server.endpoint
        except RuntimeError as exc:
            logger.warning("%s", exc)
            logger.warning("Continuing without OPC-UA server")

    # Console display
    console = ConsoleDisplay(engine, opcua_info=opcua_info)
    if not quiet:
        console.print_startup()

    # Plant models
    plant_runner = PlantRunner(engine)
    for plant_file in plant_files:
        try:
            models = load_plant_models(plant_file)
            for model in models:
                plant_runner.add(model)
        except Exception as exc:
            logger.error("Failed to load plant model '%s': %s", plant_file, exc)

    # Reload callback for file watcher
    async def on_reload(path: str) -> None:
        try:
            new_ir = reload_project(path)
            engine.reload(new_ir)
            if opcua_server is not None:
                await opcua_server.rebuild_address_space()
            logger.info("Hot reload successful")
        except Exception as exc:
            logger.error("Hot reload failed: %s", exc)
            logger.info("Continuing with previous project state")

    # File watcher (optional)
    watcher = None
    if enable_watch:
        try:
            from ._watcher import FileWatcher
            watcher = FileWatcher(source_path, project_path, on_reload)
        except RuntimeError as exc:
            logger.warning("%s", exc)
            logger.warning("Continuing without hot reload")

    # Start all components
    await engine.start()

    if opcua_server is not None:
        await opcua_server.start()

    await plant_runner.start()

    if watcher is not None:
        await watcher.start()

    if not quiet:
        await console.start()

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Wait for shutdown signal
    await stop_event.wait()

    # Graceful shutdown
    logger.info("Shutting down...")
    if not quiet:
        await console.stop()
    if watcher is not None:
        await watcher.stop()
    await plant_runner.stop()
    if opcua_server is not None:
        await opcua_server.stop()
    await engine.stop()
    logger.info("Shutdown complete")

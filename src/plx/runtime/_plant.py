"""Plant model co-simulation for simulated I/O.

Plant models are Python functions decorated with @plant that model
physical processes. They run as async tasks alongside the scan loop,
reading PLC outputs and writing simulated sensor inputs.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._engine import RuntimeEngine

logger = logging.getLogger("plx.runtime")


class PlantIO:
    """Interface passed to plant model functions for reading/writing PLC variables.

    Attributes
    ----------
    state : dict[str, Any]
        Persistent state dictionary for the plant model. Plant functions
        store intermediate values (e.g. simulated tank level) here between
        scan cycles.
    """

    def __init__(self, engine: RuntimeEngine) -> None:
        self._engine = engine
        self.state: dict[str, Any] = {}

    def read(self, path: str) -> object:
        """Read a PLC variable by dotted path (e.g. 'MainProgram.valve_out').

        Parameters
        ----------
        path : str
            Dotted variable path relative to the project scope.

        Returns
        -------
        object
            The current variable value, or ``None`` if the path does not exist.
        """
        try:
            return self._engine.read_variable(path)
        except KeyError:
            return None

    def write(self, path: str, value: object) -> None:
        """Write a PLC variable by dotted path.

        Parameters
        ----------
        path : str
            Dotted variable path relative to the project scope.
        value : object
            The value to write into the PLC variable.
        """
        try:
            self._engine.write_variable(path, value)
        except KeyError:
            logger.warning("Plant model: variable '%s' not found", path)


@dataclass
class PlantModel:
    """A registered plant model.

    Attributes
    ----------
    name : str
        Display name of the plant model (derived from the function name).
    func : Callable[[PlantIO], None]
        The plant simulation function invoked each scan cycle.
    scan_period_ms : int
        Execution period in milliseconds (default 100).
    """

    name: str
    func: Callable[[PlantIO], None]
    scan_period_ms: int = 100


def plant(
    func: Callable[[PlantIO], None] | None = None,
    *,
    scan_period_ms: int = 100,
) -> Any:
    """Decorator to register a function as a plant model.

    Parameters
    ----------
    func : Callable[[PlantIO], None] or None
        The plant function when used as ``@plant`` without arguments.
        ``None`` when used as ``@plant(scan_period_ms=...)``.
    scan_period_ms : int
        Execution period in milliseconds (default 100).

    Returns
    -------
    PlantModel or Callable
        A ``PlantModel`` when decorating directly, or a decorator callable
        when invoked with keyword arguments.

    Examples
    --------
    ::

        @plant(scan_period_ms=100)
        def tank_model(io):
            level = io.state.get("level", 0.0)
            if io.read("MainProgram.fill_valve"):
                level += 0.5
            level = max(0.0, min(level, 100.0))
            io.write("MainProgram.level_raw", int(level * 327.67))
            io.state["level"] = level
    """

    def decorator(fn: Callable[[PlantIO], None]) -> PlantModel:
        return PlantModel(
            name=fn.__name__,
            func=fn,
            scan_period_ms=scan_period_ms,
        )

    if func is not None:
        # Called as @plant without arguments
        return decorator(func)
    return decorator


class PlantRunner:
    """Manages plant model execution as async tasks."""

    def __init__(self, engine: RuntimeEngine) -> None:
        self._engine = engine
        self._models: list[PlantModel] = []
        self._tasks: list[asyncio.Task] = []
        self._ios: dict[str, PlantIO] = {}

    def add(self, model: PlantModel) -> None:
        """Register a plant model for execution.

        Parameters
        ----------
        model : PlantModel
            The plant model to add.
        """
        self._models.append(model)

    async def start(self) -> None:
        """Start all registered plant models as concurrent async tasks."""
        for model in self._models:
            io = PlantIO(self._engine)
            self._ios[model.name] = io
            task = asyncio.create_task(
                self._run_plant(model, io),
                name=f"plant:{model.name}",
            )
            self._tasks.append(task)
            logger.info(
                "Plant model '%s' started (period: %dms)",
                model.name,
                model.scan_period_ms,
            )

    async def stop(self) -> None:
        """Cancel all running plant model tasks and wait for completion."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _run_plant(self, model: PlantModel, io: PlantIO) -> None:
        period_s = model.scan_period_ms / 1000.0
        try:
            while True:
                try:
                    model.func(io)
                except Exception as exc:
                    logger.error(
                        "Plant model '%s' error: %s",
                        model.name,
                        exc,
                    )
                await asyncio.sleep(period_s)
        except asyncio.CancelledError:
            pass


def load_plant_models(filepath: str) -> list[PlantModel]:
    """Load plant models from a Python file.

    The file should contain functions decorated with ``@plant``.

    Parameters
    ----------
    filepath : str
        Path to a ``.py`` file containing ``@plant``-decorated functions.

    Returns
    -------
    list[PlantModel]
        Discovered plant models. Empty list (with a warning) if none found.
    """
    path = Path(filepath).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Plant model file not found: {filepath}")

    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    module_name = f"_plx_plant_{path.stem}"
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import plant model file: {filepath}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    models: list[PlantModel] = []
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, PlantModel):
            models.append(obj)

    if not models:
        logger.warning("No @plant models found in '%s'", filepath)

    return models

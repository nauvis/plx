"""ScanTrace: per-scan waveform capture for simulation.

Provides ``ScanSnapshot`` (one scan's state) and ``ScanTrace``
(a sequence of snapshots with convenience accessors).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScanSnapshot:
    """Immutable snapshot of simulation state at one scan instant."""

    clock_ms: int
    values: dict[str, object]
    active_steps: frozenset[str] = field(default_factory=frozenset)


class ScanTrace:
    """Ordered sequence of ``ScanSnapshot`` instances.

    Built up by ``ScanTrigger.run()`` or ``ctx.tick(trace=True)``.
    """

    __slots__ = ("_snapshots",)

    def __init__(self) -> None:
        self._snapshots: list[ScanSnapshot] = []

    # -- building ----------------------------------------------------------

    def capture(self, ctx: object) -> None:
        """Take a snapshot of *ctx*'s current state.

        Parameters
        ----------
        ctx : SimulationContext
            The simulation context to snapshot.  Uses private attributes
            to read state without going through StructProxy.
        """
        state = object.__getattribute__(ctx, "_state")
        known = object.__getattribute__(ctx, "_known_vars")
        clock = object.__getattribute__(ctx, "_clock_ms")

        values = {k: state[k] for k in known if k in state}
        active = frozenset(state.get("__sfc_active_steps", set()))
        self._snapshots.append(ScanSnapshot(clock_ms=clock, values=values, active_steps=active))

    def capture_vars(self, ctx: object, var_names: tuple[str, ...]) -> None:
        """Snapshot only the named variables (faster for large states).

        Parameters
        ----------
        ctx : SimulationContext
        var_names : tuple[str, ...]
            Variable names to capture.
        """
        state = object.__getattribute__(ctx, "_state")
        clock = object.__getattribute__(ctx, "_clock_ms")

        values = {}
        for name in var_names:
            if name in state:
                values[name] = state[name]
        active = frozenset(state.get("__sfc_active_steps", set()))
        self._snapshots.append(ScanSnapshot(clock_ms=clock, values=values, active_steps=active))

    # -- querying ----------------------------------------------------------

    def values_of(self, var: str) -> list:
        """Return the time-series of a single variable across all snapshots."""
        return [s.values.get(var) for s in self._snapshots]

    def to_dict(self) -> dict[str, list]:
        """Flatten to ``{"__clock_ms": [...], "var1": [...], ...}``."""
        if not self._snapshots:
            return {"__clock_ms": []}

        all_keys: set[str] = set()
        for s in self._snapshots:
            all_keys.update(s.values.keys())

        result: dict[str, list] = {"__clock_ms": []}
        for key in sorted(all_keys):
            result[key] = []

        for s in self._snapshots:
            result["__clock_ms"].append(s.clock_ms)
            for key in sorted(all_keys):
                result[key].append(s.values.get(key))

        return result

    @property
    def snapshots(self) -> list[ScanSnapshot]:
        """All captured snapshots (read-only copy)."""
        return list(self._snapshots)

    def __len__(self) -> int:
        return len(self._snapshots)

    def __getitem__(self, index: int) -> ScanSnapshot:
        return self._snapshots[index]

    def __repr__(self) -> str:
        return f"ScanTrace({len(self._snapshots)} snapshots)"

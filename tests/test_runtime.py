"""Tests for the plx runtime module."""

import asyncio
import json
import sys
import textwrap
from datetime import timedelta
from pathlib import Path
from typing import Optional

import pytest

from plx.framework import (
    BOOL,
    REAL,
    INT,
    Input,
    Output,
    Field,
    fb,
    program,
    project,
    task,
    delayed,
    rising,
)
from plx.model.project import Project
from plx.runtime._engine import RuntimeEngine, ScanStats
from plx.runtime._loader import load_project
from plx.runtime._plant import PlantIO, PlantModel, PlantRunner, plant


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@program
class SimpleProgram:
    cmd: Input[bool]
    running: Output[bool]
    count: int = 0

    def logic(self):
        if self.cmd:
            self.running = True
            self.count += 1
        else:
            self.running = False


@program
class CounterProgram:
    enable: Input[bool]
    value: Output[int] = 0

    def logic(self):
        if self.enable:
            self.value += 1


def _make_simple_project() -> Project:
    return project("TestProject", pous=[SimpleProgram]).compile()


def _make_counter_project() -> Project:
    return project("CounterProject", pous=[CounterProgram]).compile()


# ---------------------------------------------------------------------------
# ScanStats
# ---------------------------------------------------------------------------

class TestScanStats:
    def test_initial_state(self):
        stats = ScanStats()
        assert stats.total_scans == 0
        assert stats.avg_duration_us == 0.0
        assert stats.max_duration_us == 0.0
        assert stats.overrun_count == 0

    def test_avg_calculation(self):
        stats = ScanStats(total_scans=10, total_duration_us=1000.0)
        assert stats.avg_duration_us == 100.0


# ---------------------------------------------------------------------------
# RuntimeEngine — synchronous tests
# ---------------------------------------------------------------------------

class TestRuntimeEngine:
    def test_create(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        assert engine.project_name == "TestProject"
        assert engine.running is False
        assert "SimpleProgram" in engine.program_names

    def test_execute_one_scan(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        engine._execute_one_scan()
        assert engine.stats.total_scans == 1
        assert engine.stats.max_duration_us > 0

    def test_read_write_variable(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)

        # Initial state
        assert engine.read_variable("SimpleProgram.cmd") is False
        assert engine.read_variable("SimpleProgram.running") is False

        # Write and read back
        engine.write_variable("SimpleProgram.cmd", True)
        assert engine.read_variable("SimpleProgram.cmd") is True

        # Execute a scan — running should become True
        engine._execute_one_scan()
        assert engine.read_variable("SimpleProgram.running") is True

    def test_read_unknown_scope(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        with pytest.raises(KeyError, match="Unknown scope"):
            engine.read_variable("NonExistent.var")

    def test_read_invalid_path(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        with pytest.raises(KeyError, match="must be 'scope.name'"):
            engine.read_variable("no_dot")

    def test_multiple_scans(self):
        ir = _make_counter_project()
        engine = RuntimeEngine(ir)
        engine.write_variable("CounterProgram.enable", True)

        for _ in range(5):
            engine._execute_one_scan()

        assert engine.read_variable("CounterProgram.value") == 5
        assert engine.stats.total_scans == 5

    def test_get_all_variables(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        all_vars = engine.get_all_variables()
        assert "Programs.SimpleProgram" in all_vars
        prog_vars = all_vars["Programs.SimpleProgram"]
        assert "cmd" in prog_vars
        assert "running" in prog_vars

    def test_reload_preserves_state(self):
        ir = _make_counter_project()
        engine = RuntimeEngine(ir)
        engine.write_variable("CounterProgram.enable", True)

        # Run some scans
        for _ in range(10):
            engine._execute_one_scan()

        count_before = engine.read_variable("CounterProgram.value")
        assert count_before == 10

        # Reload with same IR
        engine.reload(ir)

        # value should be preserved (same name, same type)
        count_after = engine.read_variable("CounterProgram.value")
        assert count_after == count_before


# ---------------------------------------------------------------------------
# RuntimeEngine — async tests
# ---------------------------------------------------------------------------

class TestRuntimeEngineAsync:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir, scan_period_ms=50)
        await engine.start()
        assert engine.running is True

        # Let it run a few scans
        await asyncio.sleep(0.2)
        assert engine.stats.total_scans > 0

        await engine.stop()
        assert engine.running is False

    @pytest.mark.asyncio
    async def test_scan_loop_executes(self):
        ir = _make_counter_project()
        engine = RuntimeEngine(ir, scan_period_ms=10)
        engine.write_variable("CounterProgram.enable", True)

        await engine.start()
        await asyncio.sleep(0.1)  # ~10 scans
        await engine.stop()

        assert engine.read_variable("CounterProgram.value") > 0


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestLoader:
    def test_load_python_file(self, tmp_path):
        # Write a simple project file
        py_file = tmp_path / "test_project.py"
        py_file.write_text(textwrap.dedent("""\
            from plx.framework import program, project, Input, Output

            @program
            class MyProg:
                x: Input[bool]
                y: Output[bool]
                def logic(self):
                    self.y = self.x

            proj = project("TestFromFile", pous=[MyProg])
        """))

        ir, source = load_project(str(py_file))
        assert ir.name == "TestFromFile"
        assert len(ir.pous) == 1
        assert ir.pous[0].name == "MyProg"

    def test_load_json_file(self, tmp_path):
        # Create a minimal project IR and save as JSON
        ir = _make_simple_project()
        json_file = tmp_path / "test.plx.json"
        json_file.write_text(ir.model_dump_json(indent=2))

        loaded, source = load_project(str(json_file))
        assert loaded.name == ir.name
        assert len(loaded.pous) == len(ir.pous)

    def test_load_nonexistent_raises(self):
        with pytest.raises(RuntimeError):
            load_project("/nonexistent/path")

    def test_load_directory(self, tmp_path):
        # Create a package directory
        pkg_dir = tmp_path / "my_machine"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "main.py").write_text(textwrap.dedent("""\
            from plx.framework import program, Input, Output

            @program
            class MainProg:
                x: Input[bool]
                y: Output[bool]
                def logic(self):
                    self.y = self.x
        """))

        ir, source = load_project(str(pkg_dir))
        assert ir.name == "my_machine"
        assert len(ir.pous) >= 1


# ---------------------------------------------------------------------------
# Plant model tests
# ---------------------------------------------------------------------------

class TestPlantModel:
    def test_plant_decorator(self):
        @plant(scan_period_ms=50)
        def my_plant(io):
            pass

        assert isinstance(my_plant, PlantModel)
        assert my_plant.name == "my_plant"
        assert my_plant.scan_period_ms == 50

    def test_plant_decorator_no_args(self):
        @plant
        def my_plant(io):
            pass

        assert isinstance(my_plant, PlantModel)
        assert my_plant.scan_period_ms == 100  # default

    def test_plant_io_read_write(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        io = PlantIO(engine)

        # Write via plant IO
        io.write("SimpleProgram.cmd", True)
        assert engine.read_variable("SimpleProgram.cmd") is True

        # Read via plant IO
        val = io.read("SimpleProgram.cmd")
        assert val is True

    def test_plant_io_state(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        io = PlantIO(engine)

        # State is per-plant persistent dict
        io.state["level"] = 50.0
        assert io.state["level"] == 50.0

    def test_plant_io_read_nonexistent(self):
        ir = _make_simple_project()
        engine = RuntimeEngine(ir)
        io = PlantIO(engine)

        # Returns None for nonexistent variables
        assert io.read("NonExistent.var") is None

    @pytest.mark.asyncio
    async def test_plant_runner(self):
        ir = _make_counter_project()
        engine = RuntimeEngine(ir, scan_period_ms=10)

        call_count = 0

        @plant(scan_period_ms=20)
        def counter_plant(io):
            nonlocal call_count
            call_count += 1
            io.write("CounterProgram.enable", True)

        runner = PlantRunner(engine)
        runner.add(counter_plant)

        await engine.start()
        await runner.start()
        await asyncio.sleep(0.1)
        await runner.stop()
        await engine.stop()

        assert call_count > 0


# ---------------------------------------------------------------------------
# Console display test
# ---------------------------------------------------------------------------

class TestConsoleDisplay:
    def test_format_duration(self):
        from plx.runtime._console import _format_duration

        assert _format_duration(42.0) == "42us"
        assert _format_duration(1500.0) == "1.5ms"
        assert _format_duration(1_500_000.0) == "1.50s"

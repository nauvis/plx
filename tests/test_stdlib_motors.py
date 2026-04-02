"""Tests for stdlib motor building blocks."""

from plx.framework import (
    BOOL,
    Input,
    program,
    project,
)
from plx.model.pou import POUType
from plx.simulate import simulate
from plx.stdlib.motors import DOLStarter


class TestDOLStarterCompilation:
    def test_compiles(self):
        pou = DOLStarter.compile()
        assert pou.pou_type == POUType.FUNCTION_BLOCK
        assert pou.name == "DOLStarter"
        assert pou.folder == "stdlib/motors"

    def test_interface(self):
        pou = DOLStarter.compile()
        input_names = {v.name for v in pou.interface.input_vars}
        output_names = {v.name for v in pou.interface.output_vars}
        assert "run_cmd" in input_names
        assert "stop_cmd" in input_names
        assert "e_stop" in input_names
        assert "motor_on" in output_names
        assert "running" in output_names
        assert "faulted" in output_names

    def test_auto_included_in_project(self):
        """DOLStarter is auto-included when used as a static var."""

        @program
        class MotorMain:
            motor: DOLStarter
            start: Input[BOOL]

            def logic(self):
                self.motor(run_cmd=self.start, e_stop=True)

        proj = project("Test", pous=[MotorMain]).compile()
        pou_names = {p.name for p in proj.pous}
        assert "MotorMain" in pou_names
        assert "DOLStarter" in pou_names


class TestDOLStarterSimulation:
    def test_start_stop(self):
        ctrl = simulate(DOLStarter)
        # Start motor
        ctrl.run_cmd = True
        ctrl.e_stop = True
        ctrl.feedback = True
        ctrl.scan()
        assert ctrl.motor_on is True
        assert ctrl.running is True

        # Stop motor
        ctrl.stop_cmd = True
        ctrl.scan()
        assert ctrl.motor_on is False

    def test_e_stop_blocks_start(self):
        ctrl = simulate(DOLStarter)
        ctrl.run_cmd = True
        ctrl.e_stop = False  # E-stop tripped
        ctrl.scan()
        assert ctrl.motor_on is False
        assert ctrl.faulted is True

    def test_overload_faults(self):
        ctrl = simulate(DOLStarter)
        ctrl.run_cmd = True
        ctrl.e_stop = True
        ctrl.feedback = True
        ctrl.scan()
        assert ctrl.motor_on is True

        # Overload trips
        ctrl.overload = True
        ctrl.scan()
        assert ctrl.faulted is True
        assert ctrl.motor_on is False

    def test_running_requires_feedback(self):
        ctrl = simulate(DOLStarter)
        ctrl.run_cmd = True
        ctrl.e_stop = True
        ctrl.feedback = False
        ctrl.scan()
        assert ctrl.motor_on is True
        assert ctrl.running is False  # No feedback yet

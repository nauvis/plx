"""Smoke test: end-to-end pneumatic actuator example."""

import json

from plx.framework import (
    BOOL,
    DINT,
    REAL,
    TIME,
    T,
    ARRAY,
    STRING,
    CompileError,
    delayed,
    falling,
    fb,
    function,
    Input,
    Output,
    program,
    project,
    pulse,
    rising,
    sustained,
    Temp,
    Field,
)
from plx.model.pou import POU, POUType
from plx.model.project import Project
from plx.model.statements import Assignment, FBInvocation, IfStatement


@fb
class PneumaticActuator:
    extend_cmd: Input[BOOL] = Field(description="Command to extend")
    retract_cmd: Input[BOOL] = Field(description="Command to retract")
    extend_fb: Input[BOOL] = Field(description="Extended feedback")
    retract_fb: Input[BOOL] = Field(description="Retracted feedback")
    fault_time: TIME = T(5)
    extend_sol: Output[BOOL]
    retract_sol: Output[BOOL]
    fault: Output[BOOL]

    def logic(self):
        if self.extend_cmd and not self.retract_cmd:
            self.extend_sol = True
            self.retract_sol = False
        elif self.retract_cmd and not self.extend_cmd:
            self.extend_sol = False
            self.retract_sol = True

        if self.extend_sol and delayed(not self.extend_fb, seconds=5):
            self.fault = True
        elif self.retract_sol and delayed(not self.retract_fb, seconds=5):
            self.fault = True


@program
class MainProgram:
    speed: Input[REAL]
    running: Input[BOOL]
    output: Output[REAL]

    def logic(self):
        if self.running:
            self.output = self.speed * 0.5
        else:
            self.output = 0.0


@function
class Clamp:
    value: Input[REAL]
    low: Input[REAL]
    high: Input[REAL]

    def logic(self) -> REAL:
        if self.value < self.low:
            return self.low
        elif self.value > self.high:
            return self.high
        return self.value


class TestSmokeEndToEnd:
    def test_pneumatic_actuator_compiles(self):
        pou = PneumaticActuator.compile()
        assert isinstance(pou, POU)
        assert pou.pou_type == POUType.FUNCTION_BLOCK
        assert pou.name == "PneumaticActuator"
        assert len(pou.interface.input_vars) == 4
        assert len(pou.interface.output_vars) == 3
        assert len(pou.interface.static_vars) >= 1  # fault_time + generated TONs
        assert len(pou.networks) == 1
        assert len(pou.networks[0].statements) > 0

    def test_pneumatic_actuator_has_ton_instances(self):
        pou = PneumaticActuator.compile()
        ton_vars = [v for v in pou.interface.static_vars if hasattr(v.data_type, 'name') and v.data_type.name == "TON"]
        assert len(ton_vars) == 2  # Two delayed() calls

    def test_project_compiles(self):
        proj = project("TestPlant", pous=[PneumaticActuator, MainProgram, Clamp])
        ir = proj.compile()
        assert isinstance(ir, Project)
        assert ir.name == "TestPlant"
        assert len(ir.pous) == 3

    def test_project_serializes_to_json(self):
        proj = project("TestPlant", pous=[PneumaticActuator, MainProgram, Clamp])
        ir = proj.compile()
        data = ir.model_dump()
        assert data["name"] == "TestPlant"
        json_str = json.dumps(data)
        assert len(json_str) > 100

    def test_pou_roundtrips_json(self):
        pou = PneumaticActuator.compile()
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert restored.name == "PneumaticActuator"
        assert restored.pou_type == POUType.FUNCTION_BLOCK
        assert len(restored.interface.input_vars) == 4

    def test_function_has_return_type(self):
        pou = Clamp.compile()
        assert pou.return_type is not None
        assert pou.pou_type == POUType.FUNCTION

    def test_imports_from_flat_namespace(self):
        """Verify all public symbols are importable."""
        from plx.framework import (
            BOOL,
            INT,
            DINT,
            REAL,
            TIME,
            LTIME,
            T,
            LT,
            ARRAY,
            STRING,
            WSTRING,
            POINTER_TO,
            REFERENCE_TO,
            fb,
            program,
            function,
            Input,
            Output,
            InOut,
            Temp,
            delayed,
            rising,
            falling,
            sustained,
            pulse,
            CompileError,
            project,
            Field,
        )

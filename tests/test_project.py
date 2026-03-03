"""Tests for project assembly."""

import pytest

from plx.framework._decorators import fb, function, program
from plx.framework._descriptors import Input, Field, Output
from plx.framework._errors import ProjectAssemblyError
from plx.framework._project import PlxProject, project
from plx.framework._types import BOOL, DINT, REAL
from plx.model.pou import POUType
from plx.model.project import Project


@fb
class _TestFB:
    x: Input[BOOL]
    y: Output[BOOL]

    def logic(self):
        self.y = self.x


@program
class _TestProgram:
    running: Input[BOOL]

    def logic(self):
        pass


@function
class _TestFunc:
    a: Input[REAL]

    def logic(self) -> REAL:
        return self.a + 1.0


class TestProject:
    def test_create_project(self):
        proj = project("TestProject")
        assert isinstance(proj, PlxProject)
        assert proj.name == "TestProject"

    def test_compile_empty(self):
        proj = project("Empty")
        ir = proj.compile()
        assert isinstance(ir, Project)
        assert ir.name == "Empty"
        assert len(ir.pous) == 0

    def test_compile_with_pous(self):
        proj = project("MyProject", pous=[_TestFB, _TestProgram, _TestFunc])
        ir = proj.compile()
        assert len(ir.pous) == 3
        assert ir.pous[0].name == "_TestFB"
        assert ir.pous[0].pou_type == POUType.FUNCTION_BLOCK
        assert ir.pous[1].pou_type == POUType.PROGRAM
        assert ir.pous[2].pou_type == POUType.FUNCTION

    def test_compile_serializes(self):
        proj = project("SerProject", pous=[_TestFB])
        ir = proj.compile()
        data = ir.model_dump()
        assert data["name"] == "SerProject"
        assert len(data["pous"]) == 1
        assert data["pous"][0]["pou_type"] == "FUNCTION_BLOCK"

    def test_non_pou_class_raises(self):
        class NotAPOU:
            pass

        proj = project("Bad", pous=[NotAPOU])
        with pytest.raises(ProjectAssemblyError, match="not a compiled POU"):
            proj.compile()

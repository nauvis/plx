"""Tests for vendor library type stubs (LibraryFB, LibraryStruct, LibraryEnum).

Covers:
- Registration and metadata
- Interface parsing (FB params, struct fields, enum values)
- Type resolution via _resolve_type_ref
- Variable collection via _collect_descriptors (annotation + bare assignment)
- Simulation integration (initial_state, execute, allocation)
- Compilation integration (FB invocation in logic)
"""

import pytest

from plx.framework._descriptors import (
    InOut,
    Input,
    Output,
    VarDirection,
    _collect_descriptors,
)
from plx.framework._library import (
    FBParam,
    LibraryEnum,
    LibraryFB,
    LibraryStruct,
    LibraryType,
    _clear_library_registry,
    _LIBRARY_TYPE_REGISTRY,
    get_library_fb,
    get_library_type,
)
from plx.framework._types import (
    BOOL,
    DINT,
    INT,
    LREAL,
    REAL,
    UDINT,
    WORD,
    _resolve_type_ref,
)
from plx.model.types import NamedTypeRef, PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# Test fixtures — local stub definitions (avoid polluting global registry)
# ---------------------------------------------------------------------------

# Note: these are defined at module level because __init_subclass__ runs
# at class definition time.  Tests that need isolation use _clear_library_registry.

class _TestFB(LibraryFB, vendor="test_vendor", library="TestLib"):
    Enable: Input[BOOL]
    Speed: Input[REAL]
    Running: Output[BOOL]
    ErrorCode: Output[DINT]


class _TestFBWithExecute(LibraryFB, vendor="test_vendor", library="TestLib"):
    Start: Input[BOOL]
    Done: Output[BOOL]
    Count: Output[DINT]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        if state["Start"]:
            state["Done"] = True
            state["Count"] = state.get("Count", 0) + 1
        else:
            state["Done"] = False


class _TestStruct(LibraryStruct, vendor="test_vendor", library="TestLib"):
    x: REAL
    y: REAL
    active: BOOL


class _TestEmptyStruct(LibraryStruct, vendor="test_vendor", library="TestLib"):
    """Empty stub — fields populated on demand."""
    pass


class _TestEnum(LibraryEnum, vendor="test_vendor", library="TestLib"):
    idle = 0
    running = 1
    error = 2
    complete = 3


class _TestEnumEmpty(LibraryEnum, vendor="test_vendor", library="TestLib"):
    """Enum with no values."""
    pass


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_library_fb_registered(self):
        assert "_TestFB" in _LIBRARY_TYPE_REGISTRY
        assert _LIBRARY_TYPE_REGISTRY["_TestFB"] is _TestFB

    def test_library_struct_registered(self):
        assert "_TestStruct" in _LIBRARY_TYPE_REGISTRY
        assert _LIBRARY_TYPE_REGISTRY["_TestStruct"] is _TestStruct

    def test_library_enum_registered(self):
        assert "_TestEnum" in _LIBRARY_TYPE_REGISTRY
        assert _LIBRARY_TYPE_REGISTRY["_TestEnum"] is _TestEnum

    def test_get_library_type(self):
        assert get_library_type("_TestFB") is _TestFB
        assert get_library_type("_TestStruct") is _TestStruct
        assert get_library_type("_TestEnum") is _TestEnum
        assert get_library_type("NonExistent") is None

    def test_get_library_fb(self):
        assert get_library_fb("_TestFB") is _TestFB
        # Struct and enum should NOT match get_library_fb
        assert get_library_fb("_TestStruct") is None
        assert get_library_fb("_TestEnum") is None
        assert get_library_fb("NonExistent") is None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_fb_vendor(self):
        assert _TestFB._vendor == "test_vendor"

    def test_fb_library(self):
        assert _TestFB._library == "TestLib"

    def test_fb_type_name_defaults_to_class_name(self):
        assert _TestFB._type_name == "_TestFB"

    def test_struct_metadata(self):
        assert _TestStruct._vendor == "test_vendor"
        assert _TestStruct._library == "TestLib"
        assert _TestStruct._type_name == "_TestStruct"

    def test_enum_metadata(self):
        assert _TestEnum._vendor == "test_vendor"
        assert _TestEnum._library == "TestLib"
        assert _TestEnum._type_name == "_TestEnum"

    def test_empty_library_is_valid(self):
        """Vendor kwarg is required, library is optional (AB/Siemens)."""

        class _NoLib(LibraryFB, vendor="ab"):
            Enable: Input[BOOL]

        assert _NoLib._vendor == "ab"
        assert _NoLib._library == ""


# ---------------------------------------------------------------------------
# Interface parsing
# ---------------------------------------------------------------------------

class TestFBInterfaceParsing:
    def test_input_params(self):
        iface = _TestFB._interface
        assert "Enable" in iface
        assert iface["Enable"].direction == "input"
        assert iface["Enable"].type_ref == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_output_params(self):
        iface = _TestFB._interface
        assert "Running" in iface
        assert iface["Running"].direction == "output"
        assert iface["Running"].type_ref == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_all_params_present(self):
        assert set(_TestFB._interface.keys()) == {"Enable", "Speed", "Running", "ErrorCode"}

    def test_param_types(self):
        iface = _TestFB._interface
        assert iface["Speed"].type_ref == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert iface["ErrorCode"].type_ref == PrimitiveTypeRef(type=PrimitiveType.DINT)

    def test_inout_param(self):
        class _WithInOut(LibraryFB, vendor="test_vendor", library="TestLib"):
            Axis: InOut[DINT]

        assert _WithInOut._interface["Axis"].direction == "inout"

    def test_named_type_in_param(self):
        """Params with NamedTypeRef types (e.g. InOut[AXIS_REF])."""

        class _Ref(LibraryStruct, vendor="test_vendor", library="TestLib"):
            pass

        class _WithNamedParam(LibraryFB, vendor="test_vendor", library="TestLib"):
            Axis: InOut[_Ref]

        param = _WithNamedParam._interface["Axis"]
        assert param.direction == "inout"
        assert isinstance(param.type_ref, NamedTypeRef)
        assert param.type_ref.name == "_Ref"


class TestStructFieldParsing:
    def test_fields(self):
        assert set(_TestStruct._fields.keys()) == {"x", "y", "active"}
        assert _TestStruct._fields["x"] == PrimitiveTypeRef(type=PrimitiveType.REAL)
        assert _TestStruct._fields["active"] == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_empty_struct(self):
        assert _TestEmptyStruct._fields == {}


class TestEnumValueParsing:
    def test_values(self):
        assert _TestEnum._values == {
            "idle": 0,
            "running": 1,
            "error": 2,
            "complete": 3,
        }

    def test_empty_enum(self):
        assert _TestEnumEmpty._values == {}

    def test_default_value(self):
        assert _TestEnum.default_value() == 0  # first member

    def test_default_value_empty(self):
        assert _TestEnumEmpty.default_value() == 0


# ---------------------------------------------------------------------------
# Type resolution
# ---------------------------------------------------------------------------

class TestTypeResolution:
    def test_resolve_library_fb(self):
        result = _resolve_type_ref(_TestFB)
        assert result == NamedTypeRef(name="_TestFB")

    def test_resolve_library_struct(self):
        result = _resolve_type_ref(_TestStruct)
        assert result == NamedTypeRef(name="_TestStruct")

    def test_resolve_library_enum(self):
        result = _resolve_type_ref(_TestEnum)
        assert result == NamedTypeRef(name="_TestEnum")

    def test_resolve_by_string_still_works(self):
        result = _resolve_type_ref("_TestFB")
        assert result == NamedTypeRef(name="_TestFB")

    def test_base_classes_not_resolvable(self):
        """LibraryType/LibraryFB/etc. base classes should not resolve."""
        with pytest.raises(TypeError):
            _resolve_type_ref(LibraryType)
        with pytest.raises(TypeError):
            _resolve_type_ref(LibraryFB)


# ---------------------------------------------------------------------------
# Variable collection (_collect_descriptors)
# ---------------------------------------------------------------------------

class TestVariableCollection:
    def test_annotation_style(self):
        """power: MC_Power → static var with NamedTypeRef."""

        class _MyFB:
            power: _TestFB

        groups = _collect_descriptors(_MyFB)
        statics = groups["static"]
        assert len(statics) == 1
        assert statics[0].name == "power"
        assert statics[0].data_type == NamedTypeRef(name="_TestFB")

    def test_bare_assignment_style(self):
        """power = MC_Power → static var with NamedTypeRef."""

        class _MyFB:
            power = _TestFB

        groups = _collect_descriptors(_MyFB)
        statics = groups["static"]
        assert len(statics) == 1
        assert statics[0].name == "power"
        assert statics[0].data_type == NamedTypeRef(name="_TestFB")

    def test_mixed_with_regular_vars(self):
        """Library stubs alongside regular annotations."""

        class _MyFB:
            enable: Input[BOOL]
            power = _TestFB
            speed: Output[REAL]

        groups = _collect_descriptors(_MyFB)
        assert len(groups["input"]) == 1
        assert len(groups["output"]) == 1
        assert len(groups["static"]) == 1
        assert groups["static"][0].name == "power"


# ---------------------------------------------------------------------------
# initial_state / execute
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_fb_initial_state(self):
        state = _TestFB.initial_state()
        assert state == {
            "Enable": False,
            "Speed": 0.0,
            "Running": False,
            "ErrorCode": 0,
        }

    def test_struct_initial_state(self):
        state = _TestStruct.initial_state()
        assert state == {"x": 0.0, "y": 0.0, "active": False}

    def test_empty_struct_initial_state(self):
        assert _TestEmptyStruct.initial_state() == {}

    def test_execute_default_noop(self):
        """Default execute() does nothing — outputs unchanged."""
        state = _TestFB.initial_state()
        state["Enable"] = True
        _TestFB.execute(state, 0)
        # Outputs should be unchanged from initial (no-op)
        assert state["Running"] is False
        assert state["ErrorCode"] == 0

    def test_execute_override(self):
        """Custom execute() modifies state."""
        state = _TestFBWithExecute.initial_state()
        state["Start"] = True
        _TestFBWithExecute.execute(state, 0)
        assert state["Done"] is True
        assert state["Count"] == 1

        _TestFBWithExecute.execute(state, 10)
        assert state["Count"] == 2


# ---------------------------------------------------------------------------
# Simulation integration
# ---------------------------------------------------------------------------

class TestSimulationIntegration:
    def _make_pou_with_library_fb(self):
        """Build a POU IR that uses a library FB instance."""
        from plx.model.expressions import LiteralExpr, MemberAccessExpr, VariableRef
        from plx.model.pou import POU, POUInterface, POUType, Network
        from plx.model.statements import Assignment, FBInvocation
        from plx.model.variables import Variable

        pou = POU(
            name="TestPOU",
            pou_type=POUType.PROGRAM,
            interface=POUInterface(
                input_vars=[
                    Variable(name="start", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
                ],
                output_vars=[
                    Variable(name="done", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL)),
                ],
                static_vars=[
                    Variable(
                        name="my_fb",
                        data_type=NamedTypeRef(name="_TestFBWithExecute"),
                    ),
                ],
            ),
            networks=[
                Network(
                    statements=[
                        FBInvocation(
                            instance_name="my_fb",
                            fb_type=NamedTypeRef(name="_TestFBWithExecute"),
                            inputs={"Start": VariableRef(name="start")},
                        ),
                        Assignment(
                            target=VariableRef(name="done"),
                            value=MemberAccessExpr(
                                struct=VariableRef(name="my_fb"),
                                member="Done",
                            ),
                        ),
                    ],
                ),
            ],
        )
        return pou

    def test_allocate_library_fb_instance(self):
        """Simulator allocates library FB instance via initial_state()."""
        from plx.simulate import SimulationContext

        pou = self._make_pou_with_library_fb()
        ctx = SimulationContext(pou)
        assert isinstance(ctx.my_fb, dict)
        assert "Start" in ctx.my_fb
        assert "Done" in ctx.my_fb
        assert "Count" in ctx.my_fb

    def test_execute_library_fb_in_simulation(self):
        """Simulator dispatches to library FB execute()."""
        from plx.simulate import SimulationContext

        pou = self._make_pou_with_library_fb()
        ctx = SimulationContext(pou)

        ctx.start = True
        ctx.scan()
        assert ctx.done is True
        assert ctx.my_fb["Count"] == 1

        ctx.scan()
        assert ctx.my_fb["Count"] == 2

        ctx.start = False
        ctx.scan()
        assert ctx.done is False

    def test_allocate_library_struct(self):
        """Simulator allocates library struct as dict."""
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.simulate import SimulationContext

        pou = POU(
            name="TestPOU",
            pou_type=POUType.PROGRAM,
            interface=POUInterface(
                static_vars=[
                    Variable(
                        name="pos",
                        data_type=NamedTypeRef(name="_TestStruct"),
                    ),
                ],
            ),
        )
        ctx = SimulationContext(pou)
        assert isinstance(ctx.pos, dict)
        assert ctx.pos == {"x": 0.0, "y": 0.0, "active": False}

    def test_allocate_library_enum(self):
        """Simulator allocates library enum as default int value."""
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.simulate import SimulationContext

        pou = POU(
            name="TestPOU",
            pou_type=POUType.PROGRAM,
            interface=POUInterface(
                static_vars=[
                    Variable(
                        name="state",
                        data_type=NamedTypeRef(name="_TestEnum"),
                    ),
                ],
            ),
        )
        ctx = SimulationContext(pou)
        assert ctx.state == 0  # first enum value


# ---------------------------------------------------------------------------
# Beckhoff vendor stubs (integration test)
# ---------------------------------------------------------------------------

class TestBeckhoffStubs:
    def test_mc_power_registered(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_Power
        assert get_library_type("MC_Power") is MC_Power
        assert get_library_fb("MC_Power") is MC_Power

    def test_mc_power_metadata(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_Power
        assert MC_Power._vendor == "beckhoff"
        assert MC_Power._library == "Tc2_MC2"

    def test_mc_power_interface(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_Power
        iface = MC_Power._interface
        assert iface["Enable"].direction == "input"
        assert iface["Status"].direction == "output"
        assert iface["Override"].type_ref == PrimitiveTypeRef(type=PrimitiveType.LREAL)

    def test_mc_power_execute(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_Power
        state = MC_Power.initial_state()
        state["Enable"] = True
        MC_Power.execute(state, 0)
        assert state["Status"] is True
        assert state["Active"] is True
        assert state["Error"] is False

    def test_axis_ref_registered(self):
        from plx.framework.vendor.beckhoff.mc2 import AXIS_REF
        assert get_library_type("AXIS_REF") is AXIS_REF
        assert AXIS_REF._vendor == "beckhoff"

    def test_mc_direction_registered(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_Direction
        assert get_library_type("MC_Direction") is MC_Direction
        assert MC_Direction._values["MC_Positive_Direction"] == 1
        assert MC_Direction.default_value() == 1

    def test_resolve_mc_power_type(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_Power
        result = _resolve_type_ref(MC_Power)
        assert result == NamedTypeRef(name="MC_Power")

    def test_mc_move_absolute_initial_state(self):
        from plx.framework.vendor.beckhoff.mc2 import MC_MoveAbsolute
        state = MC_MoveAbsolute.initial_state()
        assert state["Execute"] is False
        assert state["Done"] is False
        assert state["Velocity"] == 0.0
        # MC_MoveAbsolute uses default no-op execute (no sim logic)
        state["Execute"] = True
        MC_MoveAbsolute.execute(state, 0)
        # outputs retain initial values (no-op execute)
        assert state["Done"] is False


# ---------------------------------------------------------------------------
# Compilation integration
# ---------------------------------------------------------------------------

class TestCompilationIntegration:
    def test_fb_with_library_instance_compiles(self):
        """@fb class with a library FB instance compiles to correct IR."""
        from plx.framework import fb, BOOL, REAL
        from plx.model.types import NamedTypeRef

        @fb
        class MotorCtrl:
            enable: Input[BOOL]
            speed: Input[REAL]
            power = _TestFB

        pou = MotorCtrl.compile()
        statics = pou.interface.static_vars
        power_var = next(v for v in statics if v.name == "power")
        assert power_var.data_type == NamedTypeRef(name="_TestFB")

    def test_fb_with_library_annotation_compiles(self):
        """@fb class with library type annotation compiles correctly."""
        from plx.framework import fb, BOOL

        @fb
        class AxisCtrl:
            enable: Input[BOOL]
            power: _TestFB

        pou = AxisCtrl.compile()
        statics = pou.interface.static_vars
        power_var = next(v for v in statics if v.name == "power")
        assert power_var.data_type == NamedTypeRef(name="_TestFB")

    def test_fb_invocation_in_logic(self):
        """Library FB call in logic() compiles to FBInvocation IR."""
        from plx.framework import fb, BOOL
        from plx.model.statements import FBInvocation

        @fb
        class AxisCtrl:
            enable: Input[BOOL]
            power: _TestFB
            running: Output[BOOL]

            def logic(self):
                self.power(Enable=self.enable, Speed=0.0)
                self.running = self.power.Running

        pou = AxisCtrl.compile()
        stmts = pou.networks[0].statements
        # First statement: FBInvocation
        assert isinstance(stmts[0], FBInvocation)
        assert stmts[0].instance_name == "power"
        assert isinstance(stmts[0].fb_type, NamedTypeRef)
        assert stmts[0].fb_type.name == "_TestFB"
        assert "Enable" in stmts[0].inputs


# ---------------------------------------------------------------------------
# Python export — library imports
# ---------------------------------------------------------------------------

class TestPythonExportLibraryImports:
    def test_collect_library_imports_from_interface(self):
        """_collect_library_imports finds library types in POU interface."""
        from plx.export.py._helpers import _collect_library_imports
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.model.project import Project

        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="axis", data_type=NamedTypeRef(name="AXIS_REF")),
                    Variable(name="power", data_type=NamedTypeRef(name="MC_Power")),
                ]
            ),
        )
        project = Project(name="test", pous=[pou])

        imports = _collect_library_imports(pou, project)
        assert any("from plx.framework.vendor.beckhoff import" in line for line in imports)
        assert any("AXIS_REF" in line for line in imports)
        assert any("MC_Power" in line for line in imports)

    def test_collect_library_imports_excludes_project_local(self):
        """Project-local types are not treated as library imports."""
        from plx.export.py._helpers import _collect_library_imports
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.model.project import Project
        from plx.model.types import StructType

        local_struct = StructType(name="MyStruct", members=[])
        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="s", data_type=NamedTypeRef(name="MyStruct")),
                ]
            ),
        )
        project = Project(name="test", pous=[pou], data_types=[local_struct])

        imports = _collect_library_imports(pou, project)
        assert not any("MyStruct" in line for line in imports)

    def test_collect_library_imports_from_fb_invocation(self):
        """_collect_library_imports finds library types in FBInvocation fb_type."""
        from plx.export.py._helpers import _collect_library_imports
        from plx.model.pou import POU, POUInterface, POUType, Network
        from plx.model.variables import Variable
        from plx.model.statements import FBInvocation
        from plx.model.project import Project

        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="power", data_type=NamedTypeRef(name="MC_Power")),
                ]
            ),
            networks=[
                Network(statements=[
                    FBInvocation(
                        instance_name="power",
                        fb_type=NamedTypeRef(name="MC_Power"),
                        inputs={},
                    ),
                ]),
            ],
        )
        project = Project(name="test", pous=[pou])

        imports = _collect_library_imports(pou, project)
        assert any("MC_Power" in line for line in imports)

    def test_generate_files_includes_library_imports(self):
        """generate_files() emits vendor-qualified imports for library types."""
        from plx.export.py import generate_files
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.model.project import Project

        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="axis", data_type=NamedTypeRef(name="AXIS_REF")),
                    Variable(name="power", data_type=NamedTypeRef(name="MC_Power")),
                ]
            ),
        )
        project = Project(name="test", pous=[pou])

        files = generate_files(project)
        pou_file = files.get("TestPOU.py", "")
        assert "from plx.framework.vendor.beckhoff import" in pou_file
        assert "AXIS_REF" in pou_file
        assert "MC_Power" in pou_file
        # Should NOT be quoted as string
        assert '"AXIS_REF"' not in pou_file
        assert "'AXIS_REF'" not in pou_file
        assert '"MC_Power"' not in pou_file
        assert "'MC_Power'" not in pou_file

    def test_library_types_not_quoted_in_writer(self):
        """PyWriter emits library types unquoted (not as string literals)."""
        from plx.export.py._writer import PyWriter
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.model.project import Project

        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="power", data_type=NamedTypeRef(name="MC_Power")),
                ]
            ),
        )
        project = Project(name="test", pous=[pou])

        w = PyWriter(project)
        w._write_pou(pou)
        output = w.getvalue()
        # MC_Power should appear unquoted as a type annotation
        assert "MC_Power" in output
        assert "'MC_Power'" not in output

    def test_collect_library_imports_groups_by_vendor(self):
        """Imports from different vendors produce separate import lines."""
        from plx.export.py._helpers import _collect_library_imports
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.model.project import Project

        # Explicitly import vendor stubs to register them
        import plx.framework.vendor.beckhoff  # noqa: F401
        import plx.framework.vendor.siemens  # noqa: F401

        # Use types unique to each vendor to avoid registry name collisions
        # (MC_Power exists for both beckhoff and siemens — last import wins)
        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    # LTON is Beckhoff-only (Tc2_Standard)
                    Variable(name="timer", data_type=NamedTypeRef(name="LTON")),
                    # PID_Compact is Siemens-only
                    Variable(name="pid", data_type=NamedTypeRef(name="PID_Compact")),
                ]
            ),
        )
        project = Project(name="test", pous=[pou])

        imports = _collect_library_imports(pou, project)
        # Should have separate import lines for beckhoff and siemens
        beckhoff_lines = [l for l in imports if "beckhoff" in l]
        siemens_lines = [l for l in imports if "siemens" in l]
        assert len(beckhoff_lines) >= 1
        assert len(siemens_lines) >= 1


# ---------------------------------------------------------------------------
# Beckhoff raise pass — library auto-detection
# ---------------------------------------------------------------------------

class TestBeckhoffRaiseLibraryAutoDetection:
    def test_auto_adds_library_refs(self):
        """Beckhoff raise pass auto-detects library references from type usage."""
        from plx.model.pou import POU, POUInterface, POUType, Network
        from plx.model.variables import Variable
        from plx.model.statements import FBInvocation
        from plx.model.project import Project

        pou = POU(
            name="MotionTest",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="axis", data_type=NamedTypeRef(name="AXIS_REF")),
                    Variable(name="power", data_type=NamedTypeRef(name="MC_Power")),
                ]
            ),
            networks=[
                Network(statements=[
                    FBInvocation(
                        instance_name="power",
                        fb_type=NamedTypeRef(name="MC_Power"),
                        inputs={},
                    ),
                ]),
            ],
        )
        project = Project(name="test", pous=[pou])

        try:
            from plx.beckhoff.raise_._project import raise_
        except ImportError:
            pytest.skip("Beckhoff raise pass not available")

        result, _ = raise_(project)
        lib_names = {lib.name for lib in result.libraries}
        assert "Tc2_MC2" in lib_names, f"Expected Tc2_MC2 in {lib_names}"
        # Default libs should still be present
        assert "Tc2_Standard" in lib_names
        assert "Tc2_System" in lib_names

    def test_no_duplicate_default_libraries(self):
        """Auto-detection does not duplicate default libraries."""
        from plx.model.pou import POU, POUInterface, POUType
        from plx.model.variables import Variable
        from plx.model.project import Project

        pou = POU(
            name="TestPOU",
            pou_type=POUType.FUNCTION_BLOCK,
            interface=POUInterface(
                static_vars=[
                    Variable(name="timer", data_type=NamedTypeRef(name="LTON")),
                ]
            ),
        )
        project = Project(name="test", pous=[pou])

        try:
            from plx.beckhoff.raise_._project import raise_
        except ImportError:
            pytest.skip("Beckhoff raise pass not available")

        result, _ = raise_(project)
        lib_names = [lib.name for lib in result.libraries]
        # Tc2_Standard is a default lib AND the library for LTON —
        # should appear exactly once
        assert lib_names.count("Tc2_Standard") == 1

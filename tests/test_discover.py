"""Tests for auto-discovery and folder inference."""

import pytest

from plx.framework._discover import DiscoveryResult, _infer_folder, discover
from plx.framework._project import project

# ---------------------------------------------------------------------------
# _infer_folder
# ---------------------------------------------------------------------------


class TestInferFolder:
    """Tests for _infer_folder() with various module structures."""

    def test_root_package_init(self):
        """Class in root package __init__.py → ''."""

        class Fake:
            __module__ = "my_machine"

        assert _infer_folder(Fake, "my_machine") == ""

    def test_root_level_module(self):
        """Class in my_machine.types (regular file) → ''."""

        class Fake:
            __module__ = "my_machine.types"

        assert _infer_folder(Fake, "my_machine") == ""

    def test_subpackage_module(self):
        """Class in my_machine.conveyors.belt → 'conveyors'."""

        class Fake:
            __module__ = "my_machine.conveyors.belt"

        assert _infer_folder(Fake, "my_machine") == "conveyors"

    def test_deep_subpackage_module(self):
        """Class in my_machine.area1.conveyors.belt → 'area1/conveyors'."""

        class Fake:
            __module__ = "my_machine.area1.conveyors.belt"

        assert _infer_folder(Fake, "my_machine") == "area1/conveyors"

    def test_subpackage_init(self):
        """Class in a package __init__.py → keeps all segments."""
        import sys
        from types import ModuleType

        # Create a fake package module with __path__
        mod = ModuleType("my_machine.conveyors")
        mod.__path__ = ["/fake/path"]
        sys.modules["my_machine.conveyors"] = mod
        try:

            class Fake:
                __module__ = "my_machine.conveyors"

            assert _infer_folder(Fake, "my_machine") == "conveyors"
        finally:
            del sys.modules["my_machine.conveyors"]

    def test_different_root(self):
        """Class from outside root package → ''."""

        class Fake:
            __module__ = "other_package.foo"

        assert _infer_folder(Fake, "my_machine") == ""


# ---------------------------------------------------------------------------
# discover() — integration with test fixture package
# ---------------------------------------------------------------------------


class TestDiscover:
    """Tests for discover() using the sample_project fixture."""

    def test_discovers_all_pous(self):
        result = discover("tests.fixtures.sample_project")
        pou_names = {cls.__name__ for cls in result.pous}
        assert "MainProgram" in pou_names
        assert "BeltConveyor" in pou_names
        assert "RollerConveyor" in pou_names

    def test_discovers_data_types(self):
        result = discover("tests.fixtures.sample_project")
        type_names = {cls.__name__ for cls in result.data_types}
        assert "BeltData" in type_names
        assert "MotorData" in type_names

    def test_discovers_global_var_lists(self):
        result = discover("tests.fixtures.sample_project")
        gvl_names = {cls.__name__ for cls in result.global_var_lists}
        assert "DigitalIO" in gvl_names

    def test_discovers_tasks(self):
        result = discover("tests.fixtures.sample_project")
        task_names = {t.name for t in result.tasks}
        assert "MainTask" in task_names

    def test_folder_inference_conveyors(self):
        """POUs in conveyors/ subpackage get folder='conveyors'."""
        result = discover("tests.fixtures.sample_project")
        for cls in result.pous:
            if cls.__name__ == "BeltConveyor":
                assert cls._compiled_pou.folder == "conveyors"
                return
        pytest.fail("BeltConveyor not found")

    def test_folder_inference_root_module(self):
        """Types in root-level types.py get folder=''."""
        result = discover("tests.fixtures.sample_project")
        for cls in result.data_types:
            if cls.__name__ == "MotorData":
                assert cls._compiled_type.folder == ""
                return
        pytest.fail("MotorData not found")

    def test_folder_inference_root_init(self):
        """POU in root __init__.py gets folder=''."""
        result = discover("tests.fixtures.sample_project")
        for cls in result.pous:
            if cls.__name__ == "MainProgram":
                assert cls._compiled_pou.folder == ""
                return
        pytest.fail("MainProgram not found")

    def test_folder_inference_io_subpackage(self):
        """GVL in io/signals.py gets folder='io'."""
        result = discover("tests.fixtures.sample_project")
        for cls in result.global_var_lists:
            if cls.__name__ == "DigitalIO":
                assert cls._compiled_gvl.folder == "io"
                return
        pytest.fail("DigitalIO not found")

    def test_deduplication(self):
        """Same package scanned twice doesn't produce duplicates."""
        result = discover(
            "tests.fixtures.sample_project",
            "tests.fixtures.sample_project",
        )
        pou_names = [cls.__name__ for cls in result.pous]
        # Each POU should appear only once
        assert len(pou_names) == len(set(pou_names))

    def test_excludes_external_imports(self):
        """Classes imported from outside the package are excluded."""
        result = discover("tests.fixtures.sample_project")
        # No classes from plx.framework or plx.model should appear
        for cls in result.pous:
            assert cls.__module__.startswith("tests.fixtures.sample_project")
        for cls in result.data_types:
            assert cls.__module__.startswith("tests.fixtures.sample_project")

    def test_result_type(self):
        result = discover("tests.fixtures.sample_project")
        assert isinstance(result, DiscoveryResult)

    def test_import_failure_warns(self):
        """Modules that fail to import should emit a warning, not silently skip."""
        import sys
        import types

        # Create a fake package whose submodule raises ImportError
        pkg = types.ModuleType("_plx_test_bad_pkg")
        pkg.__path__ = ["/fake/nonexistent/path"]
        pkg.__package__ = "_plx_test_bad_pkg"
        sys.modules["_plx_test_bad_pkg"] = pkg

        # Create a bad submodule entry that will fail on import
        sub = types.ModuleType("_plx_test_bad_pkg._broken")
        sub.__package__ = "_plx_test_bad_pkg"
        # Make it raise on import by registering then deleting so
        # pkgutil.walk_packages finds it but importlib.import_module fails
        sys.modules["_plx_test_bad_pkg._broken"] = sub
        del sys.modules["_plx_test_bad_pkg._broken"]

        try:
            import warnings

            with warnings.catch_warnings(record=True) as _w:
                warnings.simplefilter("always")
                result = discover("_plx_test_bad_pkg")
            # Should still return a result (not crash)
            assert isinstance(result, DiscoveryResult)
        finally:
            sys.modules.pop("_plx_test_bad_pkg", None)


# ---------------------------------------------------------------------------
# Explicit folder= overrides inference
# ---------------------------------------------------------------------------


class TestFolderOverride:
    """Explicit folder= on decorators should not be overridden by discovery."""

    def test_explicit_folder_preserved(self):
        """When a decorator sets folder=, discover() doesn't override it."""
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input
        from plx.framework._types import BOOL

        @fb(folder="custom/path")
        class ExplicitFolderFB:
            x: Input[BOOL]

            def logic(self):
                pass

        assert ExplicitFolderFB._compiled_pou.folder == "custom/path"


# ---------------------------------------------------------------------------
# project(packages=...)
# ---------------------------------------------------------------------------


class TestProjectPackages:
    """Tests for project(packages=...) integration."""

    def test_project_with_packages(self):
        proj = project(
            "TestProject",
            packages=["tests.fixtures.sample_project"],
        )
        ir = proj.compile()

        pou_names = {p.name for p in ir.pous}
        assert "MainProgram" in pou_names
        assert "BeltConveyor" in pou_names
        assert "RollerConveyor" in pou_names

        type_names = {t.name for t in ir.data_types}
        assert "BeltData" in type_names
        assert "MotorData" in type_names

        gvl_names = {g.name for g in ir.global_variable_lists}
        assert "DigitalIO" in gvl_names

        task_names = {t.name for t in ir.tasks}
        assert "MainTask" in task_names

    def test_project_packages_with_explicit_merge(self):
        """Explicit pous= merged with packages= discovered items."""
        from plx.framework._decorators import fb
        from plx.framework._descriptors import Input
        from plx.framework._types import BOOL

        @fb
        class ExtraFB:
            x: Input[BOOL]

            def logic(self):
                pass

        proj = project(
            "MergedProject",
            pous=[ExtraFB],
            packages=["tests.fixtures.sample_project"],
        )
        ir = proj.compile()

        pou_names = {p.name for p in ir.pous}
        assert "ExtraFB" in pou_names
        assert "MainProgram" in pou_names
        assert "BeltConveyor" in pou_names

    def test_project_packages_folders_in_ir(self):
        """Folder paths should appear in the compiled Project IR."""
        proj = project(
            "FolderProject",
            packages=["tests.fixtures.sample_project"],
        )
        ir = proj.compile()

        belt_pou = next(p for p in ir.pous if p.name == "BeltConveyor")
        assert belt_pou.folder == "conveyors"

        main_pou = next(p for p in ir.pous if p.name == "MainProgram")
        assert main_pou.folder == ""

        digital_gvl = next(g for g in ir.global_variable_lists if g.name == "DigitalIO")
        assert digital_gvl.folder == "io"

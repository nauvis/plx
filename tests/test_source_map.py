"""Tests for the ST source map module."""

from plx.export.st._source_map import _build_source_map, _collect_variable_names
from plx.model.pou import POU, POUInterface, POUType
from plx.model.project import Project
from plx.model.types import PrimitiveType, PrimitiveTypeRef
from plx.model.variables import Variable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOOL = PrimitiveTypeRef(type=PrimitiveType.BOOL)
_INT = PrimitiveTypeRef(type=PrimitiveType.INT)
_REAL = PrimitiveTypeRef(type=PrimitiveType.REAL)
_DINT = PrimitiveTypeRef(type=PrimitiveType.DINT)


def _var(name: str, dt=None) -> Variable:
    return Variable(name=name, data_type=dt or _BOOL)


def _make_pou(name: str, **var_lists) -> POU:
    iface = POUInterface(**var_lists)
    return POU(pou_type=POUType.FUNCTION_BLOCK, name=name, interface=iface, networks=[])


# ===========================================================================
# Tests: _collect_variable_names
# ===========================================================================


class TestCollectVariableNames:
    def test_single_pou_input_output_static(self):
        """Single POU with input/output/static vars returns all names."""
        pou = _make_pou(
            "MyFB",
            input_vars=[_var("sensor")],
            output_vars=[_var("valve")],
            static_vars=[_var("counter", _INT)],
        )
        names = _collect_variable_names(pou)
        assert names == {"sensor", "valve", "counter"}

    def test_project_with_multiple_pous(self):
        """Project with multiple POUs returns union of all var names."""
        pou1 = _make_pou("FB1", input_vars=[_var("a")], output_vars=[_var("b")])
        pou2 = _make_pou("FB2", static_vars=[_var("c")], temp_vars=[_var("d")])
        proj = Project(name="TestProject", pous=[pou1, pou2])
        names = _collect_variable_names(proj)
        assert names == {"a", "b", "c", "d"}

    def test_pou_with_no_vars(self):
        """POU with no variables returns empty set."""
        pou = _make_pou("EmptyFB")
        names = _collect_variable_names(pou)
        assert names == set()

    def test_all_seven_var_categories(self):
        """Variables from all 7 categories are collected."""
        pou = _make_pou(
            "FullFB",
            input_vars=[_var("v_input")],
            output_vars=[_var("v_output")],
            inout_vars=[_var("v_inout")],
            static_vars=[_var("v_static")],
            temp_vars=[_var("v_temp")],
            constant_vars=[_var("v_constant")],
            external_vars=[_var("v_external")],
        )
        names = _collect_variable_names(pou)
        assert names == {
            "v_input",
            "v_output",
            "v_inout",
            "v_static",
            "v_temp",
            "v_constant",
            "v_external",
        }

    def test_project_overlapping_var_names(self):
        """When multiple POUs share a variable name, it appears once in the set."""
        pou1 = _make_pou("FB1", input_vars=[_var("shared")])
        pou2 = _make_pou("FB2", output_vars=[_var("shared")])
        proj = Project(name="TestProject", pous=[pou1, pou2])
        names = _collect_variable_names(proj)
        assert names == {"shared"}

    def test_project_with_no_pous(self):
        """Project with no POUs returns empty set."""
        proj = Project(name="EmptyProject", pous=[])
        names = _collect_variable_names(proj)
        assert names == set()


# ===========================================================================
# Tests: _build_source_map
# ===========================================================================


class TestBuildSourceMap:
    def test_simple_variable_references(self):
        """Simple ST text with variable references produces correct line/column."""
        st = "valve := sensor AND enable;"
        names = {"valve", "sensor", "enable"}
        entries = _build_source_map(st, names)
        assert len(entries) == 3
        # Check each variable is found with correct 1-indexed positions
        by_name = {e["name"]: e for e in entries}
        assert by_name["valve"]["line"] == 1
        assert by_name["valve"]["column"] == 1
        assert by_name["sensor"]["line"] == 1
        assert by_name["sensor"]["column"] == st.index("sensor") + 1
        assert by_name["enable"]["line"] == 1
        assert by_name["enable"]["column"] == st.index("enable") + 1

    def test_var_block_lines_skipped(self):
        """Lines inside VAR blocks are not mapped."""
        st = "VAR_INPUT\n    sensor : BOOL;\nEND_VAR\nvalve := sensor;"
        names = {"sensor", "valve"}
        entries = _build_source_map(st, names)
        # Only line 4 should be present (the logic line), not VAR block lines
        by_name = {e["name"]: e for e in entries}
        assert "valve" in by_name
        assert by_name["valve"]["line"] == 4
        assert "sensor" in by_name
        assert by_name["sensor"]["line"] == 4

    def test_var_block_keyword_variants(self):
        """All VAR block keyword variants are correctly skipped."""
        keywords = [
            "VAR_INPUT",
            "VAR_OUTPUT",
            "VAR_IN_OUT",
            "VAR",
            "VAR_TEMP",
            "VAR CONSTANT",
            "VAR_GLOBAL",
            "VAR_EXTERNAL",
        ]
        for kw in keywords:
            st = f"{kw}\n    x : BOOL;\nEND_VAR\ny := x;"
            names = {"x", "y"}
            entries = _build_source_map(st, names)
            lines = [e["line"] for e in entries]
            # x and y should only appear on line 4 (after END_VAR)
            assert all(ln == 4 for ln in lines), f"VAR keyword '{kw}' did not skip block: lines={lines}"

    def test_line_comment_stripped(self):
        """// comments are stripped before matching."""
        st = "valve := TRUE; // sensor is disabled"
        names = {"valve", "sensor"}
        entries = _build_source_map(st, names)
        by_name = {e["name"]: e for e in entries}
        assert "valve" in by_name
        # "sensor" only appears in the comment, so it should not be found
        assert "sensor" not in by_name

    def test_multiple_refs_same_line_deduped(self):
        """Multiple occurrences of the same variable on one line produce one entry."""
        st = "x := x + x;"
        names = {"x"}
        entries = _build_source_map(st, names)
        assert len(entries) == 1
        assert entries[0]["name"] == "x"
        assert entries[0]["line"] == 1
        # First occurrence is at column 1
        assert entries[0]["column"] == 1

    def test_longest_first_prevents_partial_match(self):
        """Variable names sorted longest-first prevents partial matches."""
        st = "motor_speed := motor;"
        names = {"motor", "motor_speed"}
        entries = _build_source_map(st, names)
        by_name = {e["name"]: e for e in entries}
        # "motor_speed" should be matched as a whole, not "motor" + partial
        assert "motor_speed" in by_name
        assert "motor" in by_name
        # motor_speed starts at column 1
        assert by_name["motor_speed"]["column"] == 1
        # motor starts after ":= "
        assert by_name["motor"]["column"] == st.index(":= motor;") + 4

    def test_empty_text(self):
        """Empty ST text returns empty list."""
        entries = _build_source_map("", {"x", "y"})
        assert entries == []

    def test_no_matching_variables(self):
        """Text with no matching variable names returns empty list."""
        st = "result := 42 + 8;"
        names = {"x", "y", "z"}
        entries = _build_source_map(st, names)
        assert entries == []

    def test_empty_variable_names(self):
        """Empty variable names set returns empty list (fast path)."""
        st = "valve := sensor;"
        entries = _build_source_map(st, set())
        assert entries == []

    def test_variable_at_start_of_line(self):
        """Variable at the very start of a line has column 1."""
        st = "valve := TRUE;"
        names = {"valve"}
        entries = _build_source_map(st, names)
        assert len(entries) == 1
        assert entries[0]["column"] == 1

    def test_variable_in_middle_of_line(self):
        """Variable in the middle of a line has correct column offset."""
        st = "    result := speed * 2;"
        names = {"result", "speed"}
        entries = _build_source_map(st, names)
        by_name = {e["name"]: e for e in entries}
        assert by_name["result"]["column"] == st.index("result") + 1
        assert by_name["speed"]["column"] == st.index("speed") + 1

    def test_multiline_text(self):
        """Variables on different lines have correct line numbers."""
        st = "IF sensor THEN\n    valve := TRUE;\nEND_IF;"
        names = {"sensor", "valve"}
        entries = _build_source_map(st, names)
        by_name = {e["name"]: e for e in entries}
        assert by_name["sensor"]["line"] == 1
        assert by_name["valve"]["line"] == 2

    def test_var_block_then_logic(self):
        """Full POU structure with VAR blocks followed by logic."""
        st = (
            "VAR_INPUT\n    sensor : BOOL;\nEND_VAR\n"
            "VAR_OUTPUT\n    valve : BOOL;\nEND_VAR\n"
            "VAR\n    temp : INT;\nEND_VAR\n"
            "valve := sensor AND NOT temp;"
        )
        names = {"sensor", "valve", "temp"}
        entries = _build_source_map(st, names)
        # All entries should come from line 10 only
        assert all(e["line"] == 10 for e in entries)
        assert len(entries) == 3

    def test_nested_var_blocks(self):
        """Multiple VAR blocks are all correctly skipped."""
        st = "VAR_INPUT\n    a : BOOL;\nEND_VAR\nVAR_OUTPUT\n    b : BOOL;\nEND_VAR\nb := a;"
        names = {"a", "b"}
        entries = _build_source_map(st, names)
        # Only line 7 should have entries
        assert all(e["line"] == 7 for e in entries)

    def test_word_boundary_matching(self):
        """Variable names match on word boundaries only (no substring matches)."""
        st = "my_valve := TRUE;"
        # "valve" should NOT match inside "my_valve" due to word boundary
        names = {"valve"}
        entries = _build_source_map(st, names)
        assert entries == []

    def test_word_boundary_exact_match(self):
        """Exact variable name matches correctly at word boundaries."""
        st = "valve := TRUE; my_valve := FALSE;"
        names = {"valve"}
        entries = _build_source_map(st, names)
        assert len(entries) == 1
        assert entries[0]["name"] == "valve"
        assert entries[0]["column"] == 1

    def test_multiple_variables_on_multiple_lines(self):
        """Multiple variables across multiple lines produce correct entries."""
        st = "x := 1;\ny := x + 2;\nz := x + y;"
        names = {"x", "y", "z"}
        entries = _build_source_map(st, names)
        # Line 1: x
        # Line 2: y, x
        # Line 3: z, x, y
        line1 = [e for e in entries if e["line"] == 1]
        line2 = [e for e in entries if e["line"] == 2]
        line3 = [e for e in entries if e["line"] == 3]
        assert {e["name"] for e in line1} == {"x"}
        assert {e["name"] for e in line2} == {"y", "x"}
        assert {e["name"] for e in line3} == {"z", "x", "y"}

    def test_comment_in_middle_of_line(self):
        """Variable reference before // comment is found; reference after is not."""
        st = "valve := sensor; // reset motor"
        names = {"valve", "sensor", "motor"}
        entries = _build_source_map(st, names)
        found_names = {e["name"] for e in entries}
        assert "valve" in found_names
        assert "sensor" in found_names
        assert "motor" not in found_names

    def test_end_var_exits_block(self):
        """END_VAR correctly ends the skip region."""
        st = "VAR\n    x : BOOL;\nEND_VAR\nx := TRUE;"
        names = {"x"}
        entries = _build_source_map(st, names)
        assert len(entries) == 1
        assert entries[0]["line"] == 4

    def test_entry_dict_structure(self):
        """Each entry has exactly name, line, column keys."""
        st = "x := 1;"
        names = {"x"}
        entries = _build_source_map(st, names)
        assert len(entries) == 1
        entry = entries[0]
        assert set(entry.keys()) == {"name", "line", "column"}
        assert isinstance(entry["name"], str)
        assert isinstance(entry["line"], int)
        assert isinstance(entry["column"], int)

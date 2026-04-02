"""Tests for Python comments → Network comments feature."""

import ast
import textwrap
from datetime import timedelta

from plx.framework import (
    BOOL,
    REAL,
    Input,
    Output,
    delayed,
    fb,
    function,
    program,
)
from plx.framework._decorators import _extract_comments, _split_body_by_comments
from plx.model.pou import POU
from plx.model.statements import FBInvocation, IfStatement

# ---------------------------------------------------------------------------
# Unit tests: _extract_comments
# ---------------------------------------------------------------------------


class TestExtractComments:
    def test_standalone_comment_extracted(self):
        source = textwrap.dedent("""\
            def logic(self):
                # This is a comment
                self.x = 1
        """)
        result = _extract_comments(source)
        assert 2 in result
        assert result[2] == "This is a comment"

    def test_inline_comment_excluded(self):
        source = textwrap.dedent("""\
            def logic(self):
                self.x = 1  # inline
        """)
        result = _extract_comments(source)
        assert result == {}

    def test_empty_hash_excluded(self):
        source = textwrap.dedent("""\
            def logic(self):
                #
                self.x = 1
        """)
        result = _extract_comments(source)
        assert result == {}

    def test_double_hash_handling(self):
        source = textwrap.dedent("""\
            def logic(self):
                ## Header
                self.x = 1
        """)
        result = _extract_comments(source)
        assert 2 in result
        assert result[2] == "# Header"

    def test_no_comments_returns_empty(self):
        source = textwrap.dedent("""\
            def logic(self):
                self.x = 1
        """)
        result = _extract_comments(source)
        assert result == {}

    def test_multiple_comments(self):
        source = textwrap.dedent("""\
            def logic(self):
                # First
                self.x = 1
                # Second
                self.y = 2
        """)
        result = _extract_comments(source)
        assert result[2] == "First"
        assert result[4] == "Second"


# ---------------------------------------------------------------------------
# Unit tests: _split_body_by_comments
# ---------------------------------------------------------------------------


class TestSplitBodyByComments:
    def _parse_func(self, source: str) -> ast.FunctionDef:
        tree = ast.parse(textwrap.dedent(source))
        return tree.body[0]

    def test_no_comments_single_group(self):
        func_def = self._parse_func("""\
            def logic(self):
                x = 1
                y = 2
        """)
        groups = _split_body_by_comments(func_def, {})
        assert len(groups) == 1
        assert groups[0][0] is None
        assert len(groups[0][1]) == 2

    def test_comment_splits_body(self):
        source = textwrap.dedent("""\
            def logic(self):
                x = 1
                # Split here
                y = 2
        """)
        func_def = ast.parse(source).body[0]
        comments = _extract_comments(source)
        groups = _split_body_by_comments(func_def, comments)
        assert len(groups) == 2
        assert groups[0][0] is None
        assert len(groups[0][1]) == 1  # x = 1
        assert groups[1][0] == "Split here"
        assert len(groups[1][1]) == 1  # y = 2

    def test_consecutive_comments_merge(self):
        source = textwrap.dedent("""\
            def logic(self):
                # Line 1
                # Line 2
                x = 1
        """)
        func_def = ast.parse(source).body[0]
        comments = _extract_comments(source)
        groups = _split_body_by_comments(func_def, comments)
        assert len(groups) == 1
        assert groups[0][0] == "Line 1\nLine 2"

    def test_nested_comment_ignored(self):
        source = textwrap.dedent("""\
            def logic(self):
                if True:
                    # Inside if
                    x = 1
                y = 2
        """)
        func_def = ast.parse(source).body[0]
        comments = _extract_comments(source)
        groups = _split_body_by_comments(func_def, comments)
        assert len(groups) == 1
        assert groups[0][0] is None

    def test_trailing_comment_discarded(self):
        source = textwrap.dedent("""\
            def logic(self):
                x = 1
                # Trailing
        """)
        func_def = ast.parse(source).body[0]
        comments = _extract_comments(source)
        groups = _split_body_by_comments(func_def, comments)
        assert len(groups) == 1
        assert groups[0][0] is None
        assert len(groups[0][1]) == 1

    def test_statements_before_first_comment(self):
        source = textwrap.dedent("""\
            def logic(self):
                x = 1
                # Section
                y = 2
        """)
        func_def = ast.parse(source).body[0]
        comments = _extract_comments(source)
        groups = _split_body_by_comments(func_def, comments)
        assert len(groups) == 2
        assert groups[0][0] is None
        assert groups[1][0] == "Section"

    def test_comment_before_first_statement(self):
        source = textwrap.dedent("""\
            def logic(self):
                # Preamble
                x = 1
        """)
        func_def = ast.parse(source).body[0]
        comments = _extract_comments(source)
        groups = _split_body_by_comments(func_def, comments)
        assert len(groups) == 1
        assert groups[0][0] == "Preamble"
        assert len(groups[0][1]) == 1


# ---------------------------------------------------------------------------
# End-to-end tests via decorators
# ---------------------------------------------------------------------------


class TestNetworkComments:
    def test_no_comments_single_network(self):
        @fb
        class Simple:
            x: Output[BOOL]

            def logic(self):
                self.x = True

        pou = Simple.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment is None

    def test_single_comment_one_network(self):
        @fb
        class OneComment:
            x: Output[BOOL]

            def logic(self):
                # Set output
                self.x = True

        pou = OneComment.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment == "Set output"
        assert len(pou.networks[0].statements) == 1

    def test_two_comments_two_networks(self):
        @fb
        class TwoComments:
            x: Output[BOOL]
            y: Output[BOOL]

            def logic(self):
                # First section
                self.x = True
                # Second section
                self.y = False

        pou = TwoComments.compile()
        assert len(pou.networks) == 2
        assert pou.networks[0].comment == "First section"
        assert pou.networks[1].comment == "Second section"

    def test_statements_before_first_comment(self):
        @fb
        class Preamble:
            x: Output[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.x = True
                # Then this
                self.y = False

        pou = Preamble.compile()
        assert len(pou.networks) == 2
        assert pou.networks[0].comment is None
        assert pou.networks[1].comment == "Then this"

    def test_consecutive_comments_merge(self):
        @fb
        class Merged:
            x: Output[BOOL]

            def logic(self):
                # Line 1
                # Line 2
                self.x = True

        pou = Merged.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment == "Line 1\nLine 2"

    def test_inline_comment_no_split(self):
        @fb
        class Inline:
            x: Output[BOOL]
            y: Output[BOOL]

            def logic(self):
                self.x = True  # inline comment
                self.y = False

        pou = Inline.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment is None

    def test_comment_inside_if_no_split(self):
        @fb
        class Nested:
            x: Input[BOOL]
            y: Output[BOOL]

            def logic(self):
                if self.x:
                    # Inside if
                    self.y = True

        pou = Nested.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment is None

    def test_sentinel_across_groups(self):
        @fb
        class SentinelGroups:
            a: Input[BOOL]
            b: Input[BOOL]
            x: Output[BOOL]
            y: Output[BOOL]

            def logic(self):
                # First timer
                if delayed(self.a, timedelta(seconds=1)):
                    self.x = True
                # Second timer
                if delayed(self.b, timedelta(seconds=2)):
                    self.y = True

        pou = SentinelGroups.compile()
        assert len(pou.networks) == 2
        # Both networks should have FBInvocation + IfStatement
        net0 = pou.networks[0]
        net1 = pou.networks[1]
        assert any(isinstance(s, FBInvocation) for s in net0.statements)
        assert any(isinstance(s, IfStatement) for s in net0.statements)
        assert any(isinstance(s, FBInvocation) for s in net1.statements)
        assert any(isinstance(s, IfStatement) for s in net1.statements)

        # Auto-counter should produce different instance names
        fb_names = []
        for net in pou.networks:
            for s in net.statements:
                if isinstance(s, FBInvocation):
                    fb_names.append(s.instance_name)
        assert len(fb_names) == 2
        assert fb_names[0] != fb_names[1]

    def test_super_logic_with_comments(self):
        @fb
        class Base:
            x: Output[BOOL]

            def logic(self):
                self.x = True

        @fb
        class Derived(Base):
            y: Output[BOOL]

            def logic(self):
                super().logic()
                # After parent
                self.y = False

        pou = Derived.compile()
        assert len(pou.networks) == 2
        # First network: inlined parent statements (no comment)
        assert pou.networks[0].comment is None
        # Second network: comment + child statements
        assert pou.networks[1].comment == "After parent"

    def test_works_with_program(self):
        @program
        class Main:
            x: Output[BOOL]

            def logic(self):
                # Initialize
                self.x = True

        pou = Main.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment == "Initialize"

    def test_works_with_function(self):
        @function
        class AddOne:
            x: Input[REAL]

            def logic(self) -> REAL:
                # Compute result
                return self.x + 1.0

        pou = AddOne.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment == "Compute result"

    def test_serialization_roundtrip(self):
        @fb
        class Serializable:
            x: Output[BOOL]
            y: Output[BOOL]

            def logic(self):
                # First rung
                self.x = True
                # Second rung
                self.y = False

        pou = Serializable.compile()
        json_str = pou.model_dump_json()
        restored = POU.model_validate_json(json_str)
        assert len(restored.networks) == 2
        assert restored.networks[0].comment == "First rung"
        assert restored.networks[1].comment == "Second rung"

    def test_multiple_statements_per_network(self):
        @fb
        class Multi:
            a: Output[BOOL]
            b: Output[BOOL]
            c: Output[BOOL]

            def logic(self):
                # Set outputs
                self.a = True
                self.b = True
                # Clear
                self.c = False

        pou = Multi.compile()
        assert len(pou.networks) == 2
        assert len(pou.networks[0].statements) == 2
        assert len(pou.networks[1].statements) == 1

    def test_comment_between_control_structures(self):
        @fb
        class ControlSplit:
            x: Input[BOOL]
            y: Output[BOOL]
            z: Output[BOOL]

            def logic(self):
                # Check input
                if self.x:
                    self.y = True
                # Always run
                self.z = False

        pou = ControlSplit.compile()
        assert len(pou.networks) == 2
        assert pou.networks[0].comment == "Check input"
        assert pou.networks[1].comment == "Always run"

    def test_empty_logic_with_pass(self):
        @fb
        class Empty:
            def logic(self):
                pass

        pou = Empty.compile()
        assert len(pou.networks) == 1
        assert pou.networks[0].comment is None

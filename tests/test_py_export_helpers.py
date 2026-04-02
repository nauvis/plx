"""Tests for plx.export.py._helpers — standalone helper functions."""

from plx.export.py._helpers import (
    _build_self_vars,
    _case_branch_condition,
    _collect_named_refs,
    _collect_pou_deps,
    _fix_embedded_iec,
    _iec_string_to_python,
    _is_dict_literal,
    _quote_string,
    _safe_name,
    _sanitize_folder,
    _sanitize_identifier,
    _split_init_params,
    _step_group_expr,
    _topo_sort_data_types,
    _topo_sort_fbs,
)
from plx.model.pou import (
    POU,
    Method,
    POUInterface,
    POUType,
    Property,
    PropertyAccessor,
)
from plx.model.project import GlobalVariableList, Project
from plx.model.statements import CaseBranch, CaseRange
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    EnumMember,
    EnumType,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
    StructMember,
    StructType,
)
from plx.model.variables import Variable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bool_type():
    return PrimitiveTypeRef(type=PrimitiveType.BOOL)


def _int_type():
    return PrimitiveTypeRef(type=PrimitiveType.INT)


def _real_type():
    return PrimitiveTypeRef(type=PrimitiveType.REAL)


def _named(name: str):
    return NamedTypeRef(name=name)


def _var(name: str, data_type=None):
    return Variable(name=name, data_type=data_type or _bool_type())


def _fb(name: str, *, extends=None, interface=None, folder="", methods=None, properties=None, implements=None):
    return POU(
        pou_type=POUType.FUNCTION_BLOCK,
        name=name,
        folder=folder,
        extends=extends,
        interface=interface or POUInterface(),
        methods=methods or [],
        properties=properties or [],
        implements=implements or [],
    )


# ===========================================================================
# _safe_name
# ===========================================================================


class TestSafeName:
    def test_normal_name_unchanged(self):
        assert _safe_name("speed") == "speed"

    def test_uppercase_name_unchanged(self):
        assert _safe_name("Speed") == "Speed"

    def test_underscore_prefix_unchanged(self):
        assert _safe_name("_internal") == "_internal"

    def test_keyword_for(self):
        assert _safe_name("for") == "for_"

    def test_keyword_if(self):
        assert _safe_name("if") == "if_"

    def test_keyword_class(self):
        assert _safe_name("class") == "class_"

    def test_keyword_return(self):
        assert _safe_name("return") == "return_"

    def test_keyword_in(self):
        assert _safe_name("in") == "in_"

    def test_keyword_is(self):
        assert _safe_name("is") == "is_"

    def test_keyword_not(self):
        assert _safe_name("not") == "not_"

    def test_keyword_and(self):
        assert _safe_name("and") == "and_"

    def test_keyword_or(self):
        assert _safe_name("or") == "or_"

    def test_keyword_while(self):
        assert _safe_name("while") == "while_"

    def test_keyword_with(self):
        assert _safe_name("with") == "with_"

    def test_keyword_yield(self):
        assert _safe_name("yield") == "yield_"

    def test_keyword_None(self):
        """None is in the keyword set AND in the explicit ('None',) check."""
        assert _safe_name("None") == "None_"

    def test_keyword_True(self):
        assert _safe_name("True") == "True_"

    def test_keyword_False(self):
        assert _safe_name("False") == "False_"

    def test_non_keyword_similar(self):
        """Names that look like keywords but aren't should pass through."""
        assert _safe_name("For") == "For"
        assert _safe_name("IF") == "IF"
        assert _safe_name("CLASS") == "CLASS"

    def test_numeric_name(self):
        assert _safe_name("x123") == "x123"

    def test_already_suffixed(self):
        """A name that is already escaped should not be double-escaped."""
        assert _safe_name("for_") == "for_"

    def test_keyword_pass(self):
        assert _safe_name("pass") == "pass_"

    def test_keyword_raise(self):
        assert _safe_name("raise") == "raise_"

    def test_keyword_lambda(self):
        assert _safe_name("lambda") == "lambda_"

    def test_keyword_try(self):
        assert _safe_name("try") == "try_"

    def test_keyword_del(self):
        assert _safe_name("del") == "del_"

    def test_keyword_global(self):
        assert _safe_name("global") == "global_"

    def test_keyword_import(self):
        assert _safe_name("import") == "import_"

    def test_keyword_from(self):
        assert _safe_name("from") == "from_"

    def test_keyword_as(self):
        assert _safe_name("as") == "as_"


# ===========================================================================
# _sanitize_identifier
# ===========================================================================


class TestSanitizeIdentifier:
    def test_clean_name_unchanged(self):
        assert _sanitize_identifier("speed") == "speed"

    def test_dotted_name(self):
        assert _sanitize_identifier("Module.Name") == "Module_Name"

    def test_hyphenated_name(self):
        assert _sanitize_identifier("my-name") == "my_name"

    def test_spaces(self):
        assert _sanitize_identifier("my name") == "my_name"

    def test_multiple_special_chars(self):
        assert _sanitize_identifier("a.b-c d") == "a_b_c_d"

    def test_leading_digit(self):
        assert _sanitize_identifier("1abc") == "_1abc"

    def test_underscore_preserved(self):
        assert _sanitize_identifier("_private") == "_private"

    def test_all_underscores(self):
        assert _sanitize_identifier("___") == "___"

    def test_special_chars_only(self):
        assert _sanitize_identifier("@#!") == "___"

    def test_backslash(self):
        assert _sanitize_identifier("path\\to") == "path_to"

    def test_colon(self):
        assert _sanitize_identifier("a:b") == "a_b"

    def test_keyword_gets_suffix(self):
        """_sanitize_identifier also applies keyword escaping."""
        assert _sanitize_identifier("for") == "for_"
        assert _sanitize_identifier("class") == "class_"

    def test_unicode_chars_replaced(self):
        assert _sanitize_identifier("moteur_entree") == "moteur_entree"

    def test_parentheses_replaced(self):
        assert _sanitize_identifier("func(x)") == "func_x_"

    def test_equals_replaced(self):
        assert _sanitize_identifier("a=b") == "a_b"


# ===========================================================================
# _sanitize_folder
# ===========================================================================


class TestSanitizeFolder:
    def test_empty_string(self):
        assert _sanitize_folder("") == ""

    def test_simple_path(self):
        assert _sanitize_folder("Motors") == "Motors"

    def test_nested_path(self):
        assert _sanitize_folder("Utilities/Motors") == "Utilities/Motors"

    def test_spaces_in_segment(self):
        assert _sanitize_folder("HMI Connections") == "HMI_Connections"

    def test_nested_spaces(self):
        assert _sanitize_folder("Machine/HMI Connections") == "Machine/HMI_Connections"

    def test_hyphens_in_segment(self):
        assert _sanitize_folder("my-folder/sub-dir") == "my_folder/sub_dir"

    def test_dots_in_segment(self):
        assert _sanitize_folder("a.b/c.d") == "a_b/c_d"

    def test_leading_digit_segment(self):
        # "def" is a Python keyword, so it gets "_" suffix from _sanitize_identifier
        assert _sanitize_folder("1abc/def") == "_1abc/def_"

    def test_special_chars_in_segment(self):
        assert _sanitize_folder("a@b/c#d") == "a_b/c_d"

    def test_deeply_nested(self):
        result = _sanitize_folder("A/B/C/D")
        assert result == "A/B/C/D"

    def test_keyword_segment(self):
        """Segments that are Python keywords should get escaped."""
        assert _sanitize_folder("for/class") == "for_/class_"


# ===========================================================================
# _topo_sort_fbs
# ===========================================================================


class TestTopoSortFbs:
    def test_no_inheritance(self):
        a = _fb("A")
        b = _fb("B")
        result = _topo_sort_fbs([a, b])
        assert result == [a, b]

    def test_simple_inheritance(self):
        """B extends A -> A should come first."""
        a = _fb("A")
        b = _fb("B", extends="A")
        result = _topo_sort_fbs([b, a])
        assert result == [a, b]

    def test_chain_inheritance(self):
        """C extends B extends A -> A, B, C."""
        a = _fb("A")
        b = _fb("B", extends="A")
        c = _fb("C", extends="B")
        result = _topo_sort_fbs([c, b, a])
        assert result == [a, b, c]

    def test_independent_mixed_with_inheritance(self):
        """X is independent, B extends A."""
        a = _fb("A")
        b = _fb("B", extends="A")
        x = _fb("X")
        result = _topo_sort_fbs([b, x, a])
        names = [p.name for p in result]
        assert names.index("A") < names.index("B")
        assert "X" in names

    def test_external_base_not_in_list(self):
        """B extends ExternalFB (not in list) -> B still appears."""
        b = _fb("B", extends="ExternalFB")
        result = _topo_sort_fbs([b])
        assert result == [b]

    def test_already_sorted(self):
        a = _fb("A")
        b = _fb("B", extends="A")
        result = _topo_sort_fbs([a, b])
        assert result == [a, b]

    def test_empty_list(self):
        assert _topo_sort_fbs([]) == []

    def test_single_fb(self):
        a = _fb("A")
        assert _topo_sort_fbs([a]) == [a]

    def test_diamond_inheritance(self):
        """D extends B and C, both extend A. All should come after their base."""
        a = _fb("A")
        b = _fb("B", extends="A")
        c = _fb("C", extends="A")
        d = _fb("D", extends="B")
        result = _topo_sort_fbs([d, c, b, a])
        names = [p.name for p in result]
        assert names.index("A") < names.index("B")
        assert names.index("A") < names.index("C")
        assert names.index("B") < names.index("D")


# ===========================================================================
# _topo_sort_data_types
# ===========================================================================


class TestTopoSortDataTypes:
    def test_independent_structs(self):
        a = StructType(
            name="A",
            members=[
                StructMember(name="x", data_type=_int_type()),
            ],
        )
        b = StructType(
            name="B",
            members=[
                StructMember(name="y", data_type=_bool_type()),
            ],
        )
        result = _topo_sort_data_types([a, b])
        assert result == [a, b]

    def test_struct_depends_on_struct(self):
        """B uses A as member type -> A before B."""
        a = StructType(
            name="A",
            members=[
                StructMember(name="x", data_type=_int_type()),
            ],
        )
        b = StructType(
            name="B",
            members=[
                StructMember(name="inner", data_type=_named("A")),
            ],
        )
        result = _topo_sort_data_types([b, a])
        assert result == [a, b]

    def test_chain_dependency(self):
        a = StructType(
            name="A",
            members=[
                StructMember(name="x", data_type=_int_type()),
            ],
        )
        b = StructType(
            name="B",
            members=[
                StructMember(name="inner", data_type=_named("A")),
            ],
        )
        c = StructType(
            name="C",
            members=[
                StructMember(name="inner", data_type=_named("B")),
            ],
        )
        result = _topo_sort_data_types([c, b, a])
        assert result == [a, b, c]

    def test_enum_no_dependencies(self):
        e = EnumType(
            name="MyEnum",
            members=[
                EnumMember(name="A", value=0),
                EnumMember(name="B", value=1),
            ],
        )
        s = StructType(
            name="S",
            members=[
                StructMember(name="mode", data_type=_named("MyEnum")),
            ],
        )
        result = _topo_sort_data_types([s, e])
        names = [dt.name for dt in result]
        assert names.index("MyEnum") < names.index("S")

    def test_empty_list(self):
        assert _topo_sort_data_types([]) == []

    def test_array_member_dependency(self):
        """Struct with ARRAY OF OtherStruct should sort correctly."""
        inner = StructType(
            name="Inner",
            members=[
                StructMember(name="val", data_type=_int_type()),
            ],
        )
        outer = StructType(
            name="Outer",
            members=[
                StructMember(
                    name="items",
                    data_type=ArrayTypeRef(
                        element_type=_named("Inner"),
                        dimensions=[DimensionRange(lower=0, upper=9)],
                    ),
                ),
            ],
        )
        result = _topo_sort_data_types([outer, inner])
        assert result == [inner, outer]

    def test_external_ref_not_in_list(self):
        """Struct referencing a type not in the list -> still appears."""
        s = StructType(
            name="S",
            members=[
                StructMember(name="ext", data_type=_named("ExternalType")),
            ],
        )
        result = _topo_sort_data_types([s])
        assert result == [s]

    def test_no_named_refs(self):
        """All primitive members -> order preserved."""
        a = StructType(
            name="A",
            members=[
                StructMember(name="x", data_type=_int_type()),
            ],
        )
        b = StructType(
            name="B",
            members=[
                StructMember(name="y", data_type=_real_type()),
            ],
        )
        result = _topo_sort_data_types([a, b])
        assert result == [a, b]


# ===========================================================================
# _collect_named_refs
# ===========================================================================


class TestCollectNamedRefs:
    def test_primitive_returns_empty(self):
        assert _collect_named_refs(_bool_type()) == set()

    def test_string_returns_empty(self):
        assert _collect_named_refs(StringTypeRef()) == set()

    def test_named_type(self):
        assert _collect_named_refs(_named("MyStruct")) == {"MyStruct"}

    def test_array_of_named(self):
        tr = ArrayTypeRef(
            element_type=_named("Inner"),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _collect_named_refs(tr) == {"Inner"}

    def test_array_of_primitive(self):
        tr = ArrayTypeRef(
            element_type=_int_type(),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _collect_named_refs(tr) == set()

    def test_pointer_to_named(self):
        tr = PointerTypeRef(target_type=_named("Target"))
        assert _collect_named_refs(tr) == {"Target"}

    def test_reference_to_named(self):
        tr = ReferenceTypeRef(target_type=_named("Target"))
        assert _collect_named_refs(tr) == {"Target"}

    def test_pointer_to_primitive(self):
        tr = PointerTypeRef(target_type=_int_type())
        assert _collect_named_refs(tr) == set()

    def test_reference_to_primitive(self):
        tr = ReferenceTypeRef(target_type=_int_type())
        assert _collect_named_refs(tr) == set()

    def test_nested_array_of_pointer_to_named(self):
        tr = ArrayTypeRef(
            element_type=PointerTypeRef(target_type=_named("Deep")),
            dimensions=[DimensionRange(lower=0, upper=4)],
        )
        assert _collect_named_refs(tr) == {"Deep"}

    def test_nested_pointer_to_reference_to_named(self):
        tr = PointerTypeRef(
            target_type=ReferenceTypeRef(target_type=_named("X")),
        )
        assert _collect_named_refs(tr) == {"X"}


# ===========================================================================
# _collect_pou_deps
# ===========================================================================


class TestCollectPouDeps:
    def _make_project(self, pous=None, data_types=None, gvls=None):
        return Project(
            name="TestProject",
            pous=pous or [],
            data_types=data_types or [],
            global_variable_lists=gvls or [],
        )

    def test_no_deps(self):
        pou = _fb(
            "MyFB",
            interface=POUInterface(
                input_vars=[_var("x", _bool_type())],
            ),
        )
        project = self._make_project(pous=[pou])
        deps = _collect_pou_deps(pou, project)
        assert deps == {}

    def test_fb_instance_dependency(self):
        """POU with a static var of another FB type -> depends on that FB."""
        other_fb = _fb("OtherFB")
        pou = _fb(
            "MyFB",
            interface=POUInterface(
                static_vars=[_var("inst", _named("OtherFB"))],
            ),
        )
        project = self._make_project(pous=[pou, other_fb])
        deps = _collect_pou_deps(pou, project)
        assert "OtherFB" in deps
        assert "OtherFB" in deps["OtherFB"]

    def test_struct_dependency(self):
        """POU with input var of struct type -> depends on that struct."""
        st = StructType(
            name="MyStruct",
            members=[
                StructMember(name="x", data_type=_int_type()),
            ],
        )
        pou = _fb(
            "MyFB",
            interface=POUInterface(
                input_vars=[_var("data", _named("MyStruct"))],
            ),
        )
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "MyStruct" in deps
        assert "MyStruct" in deps["MyStruct"]

    def test_gvl_dependency(self):
        """POU with external var matching a GVL -> depends on that GVL."""
        gvl = GlobalVariableList(
            name="GVL_Main",
            variables=[
                _var("speed", _real_type()),
            ],
        )
        pou = _fb(
            "MyFB",
            interface=POUInterface(
                external_vars=[_var("speed", _named("GVL_Main"))],
            ),
        )
        project = self._make_project(pous=[pou], gvls=[gvl])
        deps = _collect_pou_deps(pou, project)
        assert "GVL_Main" in deps

    def test_extends_dependency(self):
        """POU extending another FB -> depends on the base."""
        base = _fb("BaseFB")
        derived = _fb("DerivedFB", extends="BaseFB")
        project = self._make_project(pous=[base, derived])
        deps = _collect_pou_deps(derived, project)
        assert "BaseFB" in deps

    def test_implements_dependency(self):
        """POU implementing an interface -> depends on that interface."""
        iface = POU(
            pou_type=POUType.INTERFACE,
            name="IRunnable",
        )
        pou = _fb("MyFB", implements=["IRunnable"])
        project = self._make_project(pous=[pou, iface])
        deps = _collect_pou_deps(pou, project)
        assert "IRunnable" in deps

    def test_method_interface_dependency(self):
        """POU with a method that uses a named type -> picks it up."""
        st = StructType(
            name="Config",
            members=[
                StructMember(name="val", data_type=_int_type()),
            ],
        )
        method = Method(
            name="Setup",
            interface=POUInterface(
                input_vars=[_var("cfg", _named("Config"))],
            ),
        )
        pou = _fb("MyFB", methods=[method])
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "Config" in deps

    def test_method_return_type_dependency(self):
        st = StructType(
            name="Result",
            members=[
                StructMember(name="ok", data_type=_bool_type()),
            ],
        )
        method = Method(
            name="GetResult",
            return_type=_named("Result"),
        )
        pou = _fb("MyFB", methods=[method])
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "Result" in deps

    def test_property_dependency(self):
        st = StructType(
            name="Status",
            members=[
                StructMember(name="code", data_type=_int_type()),
            ],
        )
        prop = Property(
            name="CurrentStatus",
            data_type=_named("Status"),
        )
        pou = _fb("MyFB", properties=[prop])
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "Status" in deps

    def test_property_getter_local_var_dependency(self):
        st = StructType(
            name="Helper",
            members=[
                StructMember(name="val", data_type=_int_type()),
            ],
        )
        prop = Property(
            name="Prop",
            data_type=_int_type(),
            getter=PropertyAccessor(
                local_vars=[_var("h", _named("Helper"))],
            ),
        )
        pou = _fb("MyFB", properties=[prop])
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "Helper" in deps

    def test_property_setter_local_var_dependency(self):
        st = StructType(
            name="Converter",
            members=[
                StructMember(name="factor", data_type=_real_type()),
            ],
        )
        prop = Property(
            name="Value",
            data_type=_int_type(),
            setter=PropertyAccessor(
                local_vars=[_var("conv", _named("Converter"))],
            ),
        )
        pou = _fb("MyFB", properties=[prop])
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "Converter" in deps

    def test_self_not_in_deps(self):
        """POU should not list itself as a dependency."""
        pou = _fb("MyFB")
        project = self._make_project(pous=[pou])
        deps = _collect_pou_deps(pou, project)
        assert "MyFB" not in deps

    def test_standard_fb_types_excluded(self):
        """Standard FB types like TON should not appear in deps."""
        pou = _fb(
            "MyFB",
            interface=POUInterface(
                static_vars=[_var("timer", _named("TON"))],
            ),
        )
        project = self._make_project(pous=[pou])
        deps = _collect_pou_deps(pou, project)
        assert "TON" not in deps

    def test_folder_in_module_path(self):
        """POU deps referencing types in folders should have dotted module paths."""
        st = StructType(
            name="Config",
            folder="Utils/Types",
            members=[
                StructMember(name="val", data_type=_int_type()),
            ],
        )
        pou = _fb(
            "MyFB",
            interface=POUInterface(
                input_vars=[_var("cfg", _named("Config"))],
            ),
        )
        project = self._make_project(pous=[pou], data_types=[st])
        deps = _collect_pou_deps(pou, project)
        assert "Utils.Types.Config" in deps
        assert "Config" in deps["Utils.Types.Config"]


# ===========================================================================
# _quote_string
# ===========================================================================


class TestQuoteString:
    def test_simple_string(self):
        assert _quote_string("hello") == '"hello"'

    def test_empty_string(self):
        assert _quote_string("") == '""'

    def test_string_with_double_quotes(self):
        result = _quote_string('say "hi"')
        assert result == repr('say "hi"')

    def test_string_with_newline(self):
        result = _quote_string("line1\nline2")
        assert result == repr("line1\nline2")

    def test_string_with_carriage_return(self):
        result = _quote_string("line1\rline2")
        assert result == repr("line1\rline2")

    def test_string_with_backslash(self):
        result = _quote_string("path\\to")
        assert result == repr("path\\to")

    def test_simple_no_special_chars(self):
        """Simple strings use double-quote wrapping, not repr."""
        assert _quote_string("abc123") == '"abc123"'

    def test_single_quotes_pass_through(self):
        """Single quotes in the string do not trigger repr -- simple double-quote wrap."""
        assert _quote_string("it's") == '"it\'s"'


# ===========================================================================
# _iec_string_to_python
# ===========================================================================


class TestIecStringToPython:
    def test_simple_single_quoted(self):
        result = _iec_string_to_python("'hello'")
        assert result == repr("hello")

    def test_simple_double_quoted(self):
        result = _iec_string_to_python('"hello"')
        assert result == repr("hello")

    def test_dollar_single_quote_escape(self):
        result = _iec_string_to_python("'it$'s'")
        assert result == repr("it's")

    def test_dollar_double_quote_escape(self):
        result = _iec_string_to_python("'say $\"hi$\"'")
        assert result == repr('say "hi"')

    def test_dollar_dollar_escape(self):
        result = _iec_string_to_python("'cost $$5'")
        assert result == repr("cost $5")

    def test_newline_escape_N(self):
        result = _iec_string_to_python("'line1$Nline2'")
        assert result == repr("line1\nline2")

    def test_newline_escape_L(self):
        result = _iec_string_to_python("'line1$Lline2'")
        assert result == repr("line1\nline2")

    def test_newline_escape_lowercase_n(self):
        result = _iec_string_to_python("'line1$nline2'")
        assert result == repr("line1\nline2")

    def test_carriage_return_escape(self):
        result = _iec_string_to_python("'line1$Rline2'")
        assert result == repr("line1\rline2")

    def test_carriage_return_lowercase(self):
        result = _iec_string_to_python("'line1$rline2'")
        assert result == repr("line1\rline2")

    def test_tab_escape(self):
        result = _iec_string_to_python("'col1$Tcol2'")
        assert result == repr("col1\tcol2")

    def test_tab_lowercase(self):
        result = _iec_string_to_python("'col1$tcol2'")
        assert result == repr("col1\tcol2")

    def test_formfeed_escape(self):
        result = _iec_string_to_python("'page1$Ppage2'")
        assert result == repr("page1\fpage2")

    def test_unknown_escape_preserved(self):
        result = _iec_string_to_python("'test$Xval'")
        assert result == repr("test$Xval")

    def test_empty_string(self):
        result = _iec_string_to_python("''")
        assert result == repr("")

    def test_not_quoted_returns_as_is(self):
        """Non-quoted strings are returned unchanged."""
        assert _iec_string_to_python("hello") == "hello"

    def test_mismatched_quotes_returns_as_is(self):
        assert _iec_string_to_python("'hello\"") == "'hello\""

    def test_mixed_escapes(self):
        result = _iec_string_to_python("'A$$B$NC$TD'")
        assert result == repr("A$B\nC\tD")

    def test_single_char(self):
        result = _iec_string_to_python("'x'")
        assert result == repr("x")


# ===========================================================================
# _fix_embedded_iec
# ===========================================================================


class TestFixEmbeddedIec:
    def test_simple_name_no_parens(self):
        """Names without parens are returned unchanged."""
        assert _fix_embedded_iec("MyFunction") == "MyFunction"

    def test_dotted_name_no_parens(self):
        assert _fix_embedded_iec("Module.Method") == "Module.Method"

    def test_and_operator(self):
        result = _fix_embedded_iec("Func(x AND y)")
        assert result == "Func(x and y)"

    def test_or_operator(self):
        result = _fix_embedded_iec("Func(x OR y)")
        assert result == "Func(x or y)"

    def test_not_operator(self):
        result = _fix_embedded_iec("Func(NOT x)")
        assert result == "Func(not x)"

    def test_xor_operator(self):
        # XOR -> ^ but then ^ is replaced by .deref (dereference handling),
        # so the final result uses .deref for the XOR operator
        result = _fix_embedded_iec("Func(x XOR y)")
        assert result == "Func(x .deref y)"

    def test_mod_operator(self):
        result = _fix_embedded_iec("Func(x MOD y)")
        assert result == "Func(x % y)"

    def test_and_then_operator(self):
        result = _fix_embedded_iec("Func(x AND_THEN y)")
        assert result == "Func(x and y)"

    def test_or_else_operator(self):
        result = _fix_embedded_iec("Func(x OR_ELSE y)")
        assert result == "Func(x or y)"

    def test_combined_operators(self):
        result = _fix_embedded_iec("Func(x AND NOT y)")
        assert result == "Func(x and not y)"

    def test_dereference_dot_member(self):
        result = _fix_embedded_iec("Func(ptr^.member)")
        assert result == "Func(ptr.deref.member)"

    def test_dereference_no_dot(self):
        result = _fix_embedded_iec("Func(ptr^)")
        assert result == "Func(ptr.deref)"

    def test_this_pointer(self):
        result = _fix_embedded_iec("Func(THIS^.value)")
        assert result == "Func(self.value)"

    def test_this_pointer_lowercase(self):
        result = _fix_embedded_iec("Func(this^.value)")
        assert result == "Func(self.value)"

    def test_this_pointer_no_dot(self):
        result = _fix_embedded_iec("Func(THIS^)")
        assert result == "Func(self)"

    def test_iec_not_equal(self):
        result = _fix_embedded_iec("Func(x <> y)")
        assert result == "Func(x != y)"

    def test_iec_equality_to_python(self):
        result = _fix_embedded_iec("Func(x = y)")
        assert result == "Func(x == y)"

    def test_does_not_modify_assignment(self):
        """IEC := should not be turned into :==."""
        result = _fix_embedded_iec("Func(x := 5)")
        assert ":=" in result
        assert "==" not in result or ":==" not in result

    def test_iec_string_in_call(self):
        result = _fix_embedded_iec("Func('hello')")
        assert result == "Func('hello')"

    def test_operator_not_in_identifier(self):
        """AND inside a longer identifier should not be replaced."""
        result = _fix_embedded_iec("Func(SANDBLAST)")
        assert result == "Func(SANDBLAST)"

    def test_operator_not_in_identifier_or(self):
        result = _fix_embedded_iec("Func(ORPORATE)")
        assert result == "Func(ORPORATE)"


# ===========================================================================
# _step_group_expr
# ===========================================================================


class TestStepGroupExpr:
    def test_single_step(self):
        assert _step_group_expr(["Init"]) == "Init"

    def test_two_steps(self):
        result = _step_group_expr(["StepA", "StepB"])
        assert result == "(StepA & StepB)"

    def test_three_steps(self):
        result = _step_group_expr(["S1", "S2", "S3"])
        assert result == "(S1 & S2 & S3)"

    def test_step_names_preserved(self):
        result = _step_group_expr(["Step_One", "Step_Two"])
        assert "Step_One" in result
        assert "Step_Two" in result


# ===========================================================================
# _case_branch_condition
# ===========================================================================


class TestCaseBranchCondition:
    def test_single_int_value(self):
        branch = CaseBranch(values=[1], body=[])
        result = _case_branch_condition("state", branch)
        assert result == "state == 1"

    def test_single_string_value(self):
        branch = CaseBranch(values=["MyEnum.IDLE"], body=[])
        result = _case_branch_condition("state", branch)
        assert result == "state == MyEnum.IDLE"

    def test_multiple_int_values(self):
        branch = CaseBranch(values=[1, 2, 3], body=[])
        result = _case_branch_condition("sel", branch)
        assert result == "sel == 1 or sel == 2 or sel == 3"

    def test_single_range(self):
        branch = CaseBranch(ranges=[CaseRange(start=10, end=20)], body=[])
        result = _case_branch_condition("val", branch)
        assert result == "10 <= val <= 20"

    def test_value_and_range(self):
        branch = CaseBranch(
            values=[5],
            ranges=[CaseRange(start=10, end=20)],
            body=[],
        )
        result = _case_branch_condition("x", branch)
        assert result == "x == 5 or 10 <= x <= 20"

    def test_multiple_ranges(self):
        branch = CaseBranch(
            ranges=[
                CaseRange(start=1, end=5),
                CaseRange(start=10, end=15),
            ],
            body=[],
        )
        result = _case_branch_condition("n", branch)
        assert "1 <= n <= 5" in result
        assert "10 <= n <= 15" in result
        assert " or " in result

    def test_enum_dotted_value_with_keyword_member(self):
        """Enum member that is a Python keyword should be escaped."""
        branch = CaseBranch(values=["State.None"], body=[])
        result = _case_branch_condition("s", branch)
        assert result == "s == State.None_"

    def test_mixed_values_and_ranges(self):
        branch = CaseBranch(
            values=[0, 99],
            ranges=[CaseRange(start=10, end=20)],
            body=[],
        )
        result = _case_branch_condition("x", branch)
        parts = result.split(" or ")
        assert len(parts) == 3

    def test_string_value_with_dotted_name(self):
        """Dotted enum values should sanitize the member part."""
        branch = CaseBranch(values=["MyEnum.for"], body=[])
        result = _case_branch_condition("s", branch)
        assert result == "s == MyEnum.for_"


# ===========================================================================
# _build_self_vars
# ===========================================================================


class TestBuildSelfVars:
    def test_empty_interface(self):
        iface = POUInterface()
        result = _build_self_vars(iface)
        assert result == set()

    def test_input_vars(self):
        iface = POUInterface(input_vars=[_var("x"), _var("y")])
        result = _build_self_vars(iface)
        assert result == {"x", "y"}

    def test_output_vars(self):
        iface = POUInterface(output_vars=[_var("out1")])
        result = _build_self_vars(iface)
        assert result == {"out1"}

    def test_inout_vars(self):
        iface = POUInterface(inout_vars=[_var("ref")])
        result = _build_self_vars(iface)
        assert result == {"ref"}

    def test_static_vars(self):
        iface = POUInterface(static_vars=[_var("counter")])
        result = _build_self_vars(iface)
        assert result == {"counter"}

    def test_constant_vars(self):
        iface = POUInterface(constant_vars=[_var("MAX_VAL")])
        result = _build_self_vars(iface)
        assert result == {"MAX_VAL"}

    def test_external_vars(self):
        iface = POUInterface(external_vars=[_var("global_speed")])
        result = _build_self_vars(iface)
        assert result == {"global_speed"}

    def test_temp_vars_excluded(self):
        """Temp vars should NOT appear in self vars."""
        iface = POUInterface(
            input_vars=[_var("x")],
            temp_vars=[_var("tmp")],
        )
        result = _build_self_vars(iface)
        assert "tmp" not in result
        assert "x" in result

    def test_all_sections_combined(self):
        iface = POUInterface(
            input_vars=[_var("a")],
            output_vars=[_var("b")],
            inout_vars=[_var("c")],
            static_vars=[_var("d")],
            constant_vars=[_var("e")],
            external_vars=[_var("f")],
            temp_vars=[_var("tmp")],
        )
        result = _build_self_vars(iface)
        assert result == {"a", "b", "c", "d", "e", "f"}
        assert "tmp" not in result


# ===========================================================================
# _split_init_params
# ===========================================================================


class TestSplitInitParams:
    def test_simple_params(self):
        result = _split_init_params("A := 1, B := 2")
        assert result == ["A := 1", " B := 2"]

    def test_single_param(self):
        result = _split_init_params("A := 1")
        assert result == ["A := 1"]

    def test_nested_parens(self):
        result = _split_init_params("A := 1, B := foo(1, 2)")
        assert len(result) == 2
        assert result[0] == "A := 1"
        assert result[1] == " B := foo(1, 2)"

    def test_deeply_nested_parens(self):
        result = _split_init_params("X := f(g(1, 2), 3), Y := 4")
        assert len(result) == 2
        assert "f(g(1, 2), 3)" in result[0]
        assert "Y := 4" in result[1].strip()

    def test_string_with_comma(self):
        result = _split_init_params("Name := 'Hello, World', B := 1")
        assert len(result) == 2
        assert "'Hello, World'" in result[0]

    def test_empty_string(self):
        # Empty string has no chars, so current stays empty -> result is []
        result = _split_init_params("")
        assert result == []

    def test_no_commas(self):
        result = _split_init_params("X := TRUE")
        assert result == ["X := TRUE"]

    def test_multiple_commas(self):
        result = _split_init_params("A := 1, B := 2, C := 3")
        assert len(result) == 3


# ===========================================================================
# _is_dict_literal
# ===========================================================================


class TestIsDictLiteral:
    def test_dict_literal(self):
        assert _is_dict_literal('{"Name": "Axis"}') is True

    def test_empty_dict(self):
        assert _is_dict_literal("{}") is True

    def test_not_dict_number(self):
        assert _is_dict_literal("42") is False

    def test_not_dict_string(self):
        assert _is_dict_literal('"hello"') is False

    def test_not_dict_list(self):
        assert _is_dict_literal("[1, 2]") is False

    def test_not_dict_bool(self):
        assert _is_dict_literal("True") is False

    def test_dict_with_nested_content(self):
        assert _is_dict_literal('{"a": {"b": 1}}') is True

    def test_single_open_brace(self):
        assert _is_dict_literal("{") is True  # starts with { is enough

    def test_empty_string(self):
        assert _is_dict_literal("") is False

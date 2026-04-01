"""Shared Hypothesis strategies for generating valid IR trees.

These strategies produce structurally valid plx Universal IR models.
They are the foundation for all fuzz tests — public (IR, export,
simulate) and private (vendor roundtrip).

Usage::

    from tests.fuzz.strategies import expressions, statements, pous, projects

    @given(expr=expressions())
    def test_st_export_never_crashes(expr):
        to_structured_text(make_pou_from_expr(expr))
"""

from __future__ import annotations

from hypothesis import strategies as st

from plx.model import (
    # Types
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
    NamedTypeRef,
    ArrayTypeRef,
    DimensionRange,
    PointerTypeRef,
    ReferenceTypeRef,
    # Type definitions
    StructMember,
    StructType,
    EnumMember,
    EnumType,
    SubrangeType,
    AliasType,
    # Variables
    Variable,
    # Expressions
    BinaryOp,
    UnaryOp,
    LiteralExpr,
    VariableRef,
    BinaryExpr,
    UnaryExpr,
    CallArg,
    FunctionCallExpr,
    ArrayAccessExpr,
    MemberAccessExpr,
    BitAccessExpr,
    TypeConversionExpr,
    DerefExpr,
    SubstringExpr,
    SystemFlag,
    SystemFlagExpr,
    # Statements
    Assignment,
    IfBranch,
    IfStatement,
    CaseRange,
    CaseBranch,
    CaseStatement,
    ForStatement,
    WhileStatement,
    RepeatStatement,
    ExitStatement,
    ContinueStatement,
    ReturnStatement,
    FunctionCallStatement,
    FBInvocation,
    EmptyStatement,
    PragmaStatement,
    TryCatchStatement,
    JumpStatement,
    LabelStatement,
    # SFC
    ActionQualifier,
    Action,
    Step,
    SFCTransition,
    SFCBody,
    # POU
    POUType,
    AccessSpecifier,
    Network,
    POUInterface,
    POUAction,
    Method,
    Property,
    PropertyAccessor,
    POU,
    # Task
    PeriodicTask,
    ContinuousTask,
    EventTask,
    StartupTask,
    # Project
    GlobalVariableList,
    Project,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# IEC 61131-3 identifier: letters, digits, underscores, starts with letter
_IDENT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_IDENT_CONT = _IDENT_ALPHABET + "0123456789"

# IEC 61131-3 + vendor reserved keywords — identifiers must not match these
_RESERVED_KEYWORDS = frozenset({
    # IEC 61131-3 keywords
    "IF", "THEN", "ELSIF", "ELSE", "END_IF",
    "CASE", "OF", "END_CASE",
    "FOR", "TO", "BY", "DO", "END_FOR",
    "WHILE", "END_WHILE",
    "REPEAT", "UNTIL", "END_REPEAT",
    "RETURN", "EXIT", "CONTINUE",
    "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP",
    "VAR_GLOBAL", "VAR_EXTERNAL", "END_VAR", "VAR_STAT", "VAR_INST",
    "CONSTANT", "RETAIN", "PERSISTENT",
    "FUNCTION", "FUNCTION_BLOCK", "PROGRAM", "END_FUNCTION",
    "END_FUNCTION_BLOCK", "END_PROGRAM",
    "TYPE", "END_TYPE", "STRUCT", "END_STRUCT",
    "ARRAY", "STRING", "WSTRING",
    "TRUE", "FALSE",
    "AND", "OR", "XOR", "NOT", "MOD",
    "AT", "WITH", "POINTER", "REFERENCE", "REF",
    "METHOD", "END_METHOD", "PROPERTY", "END_PROPERTY",
    "INTERFACE", "END_INTERFACE", "IMPLEMENTS", "EXTENDS",
    "PUBLIC", "PRIVATE", "PROTECTED", "INTERNAL", "FINAL", "ABSTRACT",
    "ACTION", "END_ACTION",
    "STEP", "END_STEP", "TRANSITION", "END_TRANSITION",
    "INITIAL_STEP",
    # Type names
    "BOOL", "BYTE", "WORD", "DWORD", "LWORD",
    "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "REAL", "LREAL",
    "TIME", "LTIME", "DATE", "LDATE", "TOD", "LTOD", "DT", "LDT",
    "CHAR", "WCHAR",
    # Vendor-specific keywords
    "THIS", "SUPER", "NULL",
    # TwinCAT extra reserved (cause compile errors as variable names)
    "S", "R", "PARAMS", "SIZEOF", "INDEXOF", "ADR", "BITADR",
    "READ_ONLY", "READ_WRITE", "REM",
    "AND_THEN", "OR_ELSE", "SHL", "SHR", "ROL", "ROR",
    "JMP", "__TRY", "__CATCH", "__FINALLY", "__ENDTRY",
    "UNION", "END_UNION",
    # Standard FB types
    "TON", "TOF", "TP", "RTO", "CTU", "CTD", "CTUD",
    "R_TRIG", "F_TRIG", "SR", "RS",
})

# Subset of primitive types useful for variables (excludes TIME/DATE variants
# which need special initial value formatting)
_COMMON_PRIMITIVES = [
    PrimitiveType.BOOL,
    PrimitiveType.SINT,
    PrimitiveType.INT,
    PrimitiveType.DINT,
    PrimitiveType.LINT,
    PrimitiveType.USINT,
    PrimitiveType.UINT,
    PrimitiveType.UDINT,
    PrimitiveType.REAL,
    PrimitiveType.LREAL,
    PrimitiveType.BYTE,
    PrimitiveType.WORD,
    PrimitiveType.DWORD,
]

# Binary operators safe for fuzzing (exclude short-circuit Beckhoff extensions)
_SAFE_BINARY_OPS = [
    BinaryOp.ADD, BinaryOp.SUB, BinaryOp.MUL, BinaryOp.DIV, BinaryOp.MOD,
    BinaryOp.AND, BinaryOp.OR, BinaryOp.XOR,
    BinaryOp.EQ, BinaryOp.NE, BinaryOp.GT, BinaryOp.GE, BinaryOp.LT, BinaryOp.LE,
    BinaryOp.BAND, BinaryOp.BOR,
]

# Standard FB types for invocations
_FB_TYPES = ["TON", "TOF", "TP", "CTU", "CTD", "R_TRIG", "F_TRIG", "SR", "RS"]


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

def identifiers(min_size: int = 1, max_size: int = 12) -> st.SearchStrategy[str]:
    """IEC 61131-3 compatible identifier strings (not reserved keywords).

    Avoids trailing/leading underscores, double underscores (vendor path
    issues), and single-character names (collision-prone).
    """
    return st.from_regex(r"[a-zA-Z][a-zA-Z0-9]{0,10}[a-zA-Z0-9]", fullmatch=True).filter(
        lambda s: len(s) >= max(min_size, 2) and s.upper() not in _RESERVED_KEYWORDS
    )


def _unique_identifiers(n: int) -> st.SearchStrategy[list[str]]:
    """Draw n unique identifiers."""
    return st.lists(
        identifiers(min_size=2, max_size=10),
        min_size=n,
        max_size=n,
        unique=True,
    )


# ---------------------------------------------------------------------------
# Type References
# ---------------------------------------------------------------------------

def primitive_type_refs() -> st.SearchStrategy[PrimitiveTypeRef]:
    return st.sampled_from(_COMMON_PRIMITIVES).map(
        lambda p: PrimitiveTypeRef(type=p)
    )


def all_primitive_type_refs() -> st.SearchStrategy[PrimitiveTypeRef]:
    """All IEC 61131-3 primitive types including TIME/DATE variants."""
    return st.sampled_from(list(PrimitiveType)).map(
        lambda p: PrimitiveTypeRef(type=p)
    )


def string_type_refs() -> st.SearchStrategy[StringTypeRef]:
    return st.builds(
        StringTypeRef,
        wide=st.booleans(),
        max_length=st.one_of(st.none(), st.integers(min_value=1, max_value=255)),
    )


def named_type_refs() -> st.SearchStrategy[NamedTypeRef]:
    return identifiers().map(lambda n: NamedTypeRef(name=n))


@st.composite
def type_refs(draw: st.DrawFn, max_depth: int = 2) -> PrimitiveTypeRef | StringTypeRef | NamedTypeRef | ArrayTypeRef | PointerTypeRef | ReferenceTypeRef:
    """Generate a random TypeRef, with bounded nesting for arrays/pointers."""
    if max_depth <= 0:
        return draw(st.one_of(primitive_type_refs(), string_type_refs()))

    leaf = st.one_of(primitive_type_refs(), string_type_refs(), named_type_refs())
    inner = type_refs(max_depth=max_depth - 1)

    choice = draw(st.sampled_from(["primitive", "string", "named", "array", "pointer", "reference"]))

    if choice == "primitive":
        return draw(primitive_type_refs())
    elif choice == "string":
        return draw(string_type_refs())
    elif choice == "named":
        return draw(named_type_refs())
    elif choice == "array":
        elem = draw(inner)
        ndims = draw(st.integers(min_value=1, max_value=3))
        dims = [
            DimensionRange(
                lower=draw(st.integers(min_value=0, max_value=5)),
                upper=draw(st.integers(min_value=5, max_value=100)),
            )
            for _ in range(ndims)
        ]
        return ArrayTypeRef(element_type=elem, dimensions=dims)
    elif choice == "pointer":
        return PointerTypeRef(target_type=draw(inner))
    else:
        return ReferenceTypeRef(target_type=draw(inner))


# ---------------------------------------------------------------------------
# Type Definitions
# ---------------------------------------------------------------------------

@st.composite
def struct_types(draw: st.DrawFn) -> StructType:
    n_members = draw(st.integers(min_value=1, max_value=6))
    names = draw(_unique_identifiers(n_members + 1))
    struct_name = names[0]
    member_names = names[1:]
    members = [
        StructMember(
            name=mname,
            data_type=draw(st.one_of(primitive_type_refs(), string_type_refs())),
        )
        for mname in member_names
    ]
    return StructType(name=struct_name, members=members)


@st.composite
def enum_types(draw: st.DrawFn) -> EnumType:
    n_members = draw(st.integers(min_value=1, max_value=8))
    names = draw(_unique_identifiers(n_members + 1))
    enum_name = names[0]
    member_names = names[1:]
    members = [
        EnumMember(name=mname, value=i)
        for i, mname in enumerate(member_names)
    ]
    return EnumType(name=enum_name, members=members)


def type_definitions() -> st.SearchStrategy:
    return st.one_of(struct_types(), enum_types())


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

@st.composite
def variables(draw: st.DrawFn, name: str | None = None) -> Variable:
    """Generate a Variable with a random primitive type."""
    vname = name or draw(identifiers(min_size=2))
    dtype = draw(primitive_type_refs())
    return Variable(name=vname, data_type=dtype)


@st.composite
def rich_variables(draw: st.DrawFn, name: str | None = None) -> Variable:
    """Generate a Variable with full field coverage."""
    vname = name or draw(identifiers(min_size=2))
    dtype = draw(type_refs(max_depth=1))
    initial_value = draw(st.one_of(
        st.none(),
        st.sampled_from(["0", "1", "TRUE", "FALSE", "0.0"]),
    ))
    description = draw(st.one_of(st.just(""), st.text(min_size=1, max_size=30)))
    constant = draw(st.just(False))  # constant + retain is unusual, keep simple
    retain = draw(st.booleans())
    persistent = draw(st.booleans())
    edge = draw(st.sampled_from(["", "rising", "falling"]))
    return Variable(
        name=vname, data_type=dtype, initial_value=initial_value,
        description=description, constant=constant, retain=retain,
        persistent=persistent, edge=edge,
    )


@st.composite
def variable_lists(draw: st.DrawFn, min_size: int = 0, max_size: int = 5) -> list[Variable]:
    """Generate a list of Variables with unique names."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    if n == 0:
        return []
    names = draw(_unique_identifiers(n))
    return [
        Variable(name=name, data_type=draw(primitive_type_refs()))
        for name in names
    ]


# ---------------------------------------------------------------------------
# Expressions (recursive, depth-bounded)
# ---------------------------------------------------------------------------

def literal_exprs() -> st.SearchStrategy[LiteralExpr]:
    return st.one_of(
        st.integers(min_value=-2**31, max_value=2**31 - 1).map(
            lambda i: LiteralExpr(value=str(i))
        ),
        st.floats(
            min_value=-1e6, max_value=1e6,
            allow_nan=False, allow_infinity=False,
        ).map(lambda f: LiteralExpr(value=str(f))),
        st.sampled_from(["TRUE", "FALSE"]).map(
            lambda b: LiteralExpr(value=b)
        ),
    )


def variable_ref_exprs(
    var_pool: list[str] | None = None,
) -> st.SearchStrategy[VariableRef]:
    """Variable references drawn from a pool (or random identifiers)."""
    if var_pool:
        return st.sampled_from(var_pool).map(lambda n: VariableRef(name=n))
    return identifiers().map(lambda n: VariableRef(name=n))


def system_flag_exprs() -> st.SearchStrategy[SystemFlagExpr]:
    return st.just(SystemFlagExpr(flag=SystemFlag.FIRST_SCAN))


@st.composite
def expressions(
    draw: st.DrawFn,
    max_depth: int = 3,
    var_pool: list[str] | None = None,
) -> LiteralExpr | VariableRef | BinaryExpr | UnaryExpr | FunctionCallExpr | MemberAccessExpr | ArrayAccessExpr | BitAccessExpr | TypeConversionExpr | DerefExpr | SubstringExpr | SystemFlagExpr:
    """Generate a random Expression tree with bounded depth.

    Covers all 12 Expression union members. When *var_pool* is provided,
    VariableRef nodes draw from it (semantically coherent programs).
    """
    leaves = st.one_of(
        literal_exprs(),
        variable_ref_exprs(var_pool),
        system_flag_exprs(),
    )

    if max_depth <= 0:
        return draw(leaves)

    child = expressions(max_depth=max_depth - 1, var_pool=var_pool)

    choice = draw(st.integers(min_value=0, max_value=11))

    if choice <= 2:
        # Leaf (weighted higher to keep trees small)
        return draw(leaves)
    elif choice == 3:
        # Binary
        return BinaryExpr(
            op=draw(st.sampled_from(_SAFE_BINARY_OPS)),
            left=draw(child),
            right=draw(child),
        )
    elif choice == 4:
        # Unary
        return UnaryExpr(
            op=draw(st.sampled_from(list(UnaryOp))),
            operand=draw(child),
        )
    elif choice == 5:
        # Function call
        n_args = draw(st.integers(min_value=0, max_value=3))
        args = [CallArg(value=draw(child)) for _ in range(n_args)]
        return FunctionCallExpr(
            function_name=draw(st.sampled_from(["ABS", "SQRT", "MIN", "MAX", "LIMIT", "SEL"])),
            args=args,
        )
    elif choice == 6:
        # Member access
        return MemberAccessExpr(
            struct=draw(child),
            member=draw(identifiers()),
        )
    elif choice == 7:
        # Type conversion
        return TypeConversionExpr(
            target_type=draw(primitive_type_refs()),
            source=draw(child),
        )
    elif choice == 8:
        # Bit access
        return BitAccessExpr(
            target=draw(child),
            bit_index=draw(st.integers(min_value=0, max_value=31)),
        )
    elif choice == 9:
        # Array access
        n_indices = draw(st.integers(min_value=1, max_value=3))
        return ArrayAccessExpr(
            array=draw(child),
            indices=[draw(child) for _ in range(n_indices)],
        )
    elif choice == 10:
        # Deref
        return DerefExpr(pointer=draw(child))
    else:
        # Substring
        string_expr = draw(child)
        single_char = draw(st.booleans())
        if single_char:
            return SubstringExpr(
                string=string_expr,
                start=draw(child),
                single_char=True,
            )
        else:
            start = draw(st.one_of(st.none(), child))
            end = draw(st.one_of(st.none(), child))
            return SubstringExpr(string=string_expr, start=start, end=end)


# ---------------------------------------------------------------------------
# Statements (recursive, depth-bounded)
# ---------------------------------------------------------------------------

def _optional_comment(draw: st.DrawFn) -> str:
    """Draw an optional comment string (empty most of the time)."""
    return draw(st.one_of(
        st.just(""),
        st.just(""),
        st.just(""),
        st.text(min_size=1, max_size=40, alphabet="abcdefghijklmnopqrstuvwxyz 0123456789"),
    ))


@st.composite
def assignments(
    draw: st.DrawFn,
    max_depth: int = 2,
    var_pool: list[str] | None = None,
) -> Assignment:
    target = draw(variable_ref_exprs(var_pool))
    value = draw(expressions(max_depth=max_depth, var_pool=var_pool))
    return Assignment(target=target, value=value, comment=_optional_comment(draw))


@st.composite
def case_ranges(draw: st.DrawFn) -> CaseRange:
    """Generate a valid CaseRange with start <= end."""
    start = draw(st.integers(min_value=0, max_value=50))
    end = draw(st.integers(min_value=start, max_value=start + 50))
    return CaseRange(start=start, end=end)


@st.composite
def statements(
    draw: st.DrawFn,
    max_depth: int = 2,
    var_pool: list[str] | None = None,
) -> Assignment | IfStatement | CaseStatement | ForStatement | WhileStatement | RepeatStatement | ExitStatement | ContinueStatement | ReturnStatement | FunctionCallStatement | FBInvocation | EmptyStatement | PragmaStatement | TryCatchStatement | JumpStatement | LabelStatement:
    """Generate a random Statement tree with bounded depth.

    Covers all 16 Statement union members. Compound statements (IF, FOR,
    WHILE, CASE, TRY) recurse into their bodies with decremented depth.
    """
    expr = expressions(max_depth=min(max_depth, 2), var_pool=var_pool)
    child_stmts = st.lists(
        statements(max_depth=max_depth - 1, var_pool=var_pool),
        min_size=1,
        max_size=3,
    ) if max_depth > 0 else st.just([EmptyStatement()])

    if max_depth <= 0:
        # Only leaf statements at depth 0
        choice = draw(st.integers(min_value=0, max_value=6))
    else:
        choice = draw(st.integers(min_value=0, max_value=14))

    # Leaf statements
    if choice <= 1:
        return draw(assignments(max_depth=max_depth, var_pool=var_pool))
    elif choice == 2:
        return EmptyStatement(comment=_optional_comment(draw))
    elif choice == 3:
        return ReturnStatement()
    elif choice == 4:
        return JumpStatement(label=draw(identifiers()))
    elif choice == 5:
        return LabelStatement(name=draw(identifiers()))
    elif choice == 6:
        return PragmaStatement(text=draw(st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_0123456789 ")))

    # Compound statements
    elif choice == 7:
        # IF with optional ELSIF branches
        body = draw(child_stmts)
        n_elsif = draw(st.integers(min_value=0, max_value=2))
        elsif_branches = [
            IfBranch(condition=draw(expr), body=draw(child_stmts))
            for _ in range(n_elsif)
        ]
        else_body = draw(st.one_of(st.just([]), child_stmts))
        return IfStatement(
            if_branch=IfBranch(condition=draw(expr), body=body),
            elsif_branches=elsif_branches,
            else_body=else_body,
            comment=_optional_comment(draw),
        )
    elif choice == 8:
        # FOR
        loop_var = draw(identifiers())
        return ForStatement(
            loop_var=loop_var,
            from_expr=LiteralExpr(value=str(draw(st.integers(min_value=0, max_value=5)))),
            to_expr=LiteralExpr(value=str(draw(st.integers(min_value=5, max_value=20)))),
            body=draw(child_stmts),
            comment=_optional_comment(draw),
        )
    elif choice == 9:
        # WHILE
        return WhileStatement(
            condition=draw(expr),
            body=draw(child_stmts),
            comment=_optional_comment(draw),
        )
    elif choice == 10:
        # REPEAT
        return RepeatStatement(
            body=draw(child_stmts),
            until=draw(expr),
            comment=_optional_comment(draw),
        )
    elif choice == 11:
        # CASE with optional ranges
        selector = draw(expr)
        n_branches = draw(st.integers(min_value=1, max_value=4))
        branches = []
        used_values: set[int] = set()
        for _ in range(n_branches):
            val = draw(st.integers(min_value=0, max_value=100).filter(
                lambda v: v not in used_values
            ))
            used_values.add(val)
            ranges = draw(st.lists(case_ranges(), min_size=0, max_size=1))
            branches.append(
                CaseBranch(
                    values=[val],
                    ranges=ranges,
                    body=draw(child_stmts),
                )
            )
        else_body = draw(st.one_of(st.just([]), child_stmts))
        return CaseStatement(
            selector=selector, branches=branches, else_body=else_body,
            comment=_optional_comment(draw),
        )
    elif choice == 12:
        # Function call statement
        n_args = draw(st.integers(min_value=0, max_value=3))
        args = [CallArg(value=draw(expr)) for _ in range(n_args)]
        return FunctionCallStatement(
            function_name=draw(st.sampled_from(["ABS", "SQRT", "CONCAT"])),
            args=args,
        )
    elif choice == 13:
        # FB invocation
        fb_type = draw(st.sampled_from(_FB_TYPES))
        inst_name = draw(identifiers(min_size=2))
        return FBInvocation(
            instance_name=inst_name,
            fb_type=NamedTypeRef(name=fb_type),
            inputs={"IN": draw(expr)},
            comment=_optional_comment(draw),
        )
    else:
        # TryCatch
        try_body = draw(child_stmts)
        catch_var = draw(st.one_of(st.none(), identifiers()))
        catch_body = draw(st.one_of(st.just([]), child_stmts))
        finally_body = draw(st.one_of(st.just([]), child_stmts))
        return TryCatchStatement(
            try_body=try_body,
            catch_var=catch_var,
            catch_body=catch_body,
            finally_body=finally_body,
        )


def statement_lists(
    min_size: int = 1,
    max_size: int = 5,
    max_depth: int = 2,
    var_pool: list[str] | None = None,
) -> st.SearchStrategy[list]:
    return st.lists(
        statements(max_depth=max_depth, var_pool=var_pool),
        min_size=min_size,
        max_size=max_size,
    )


# ---------------------------------------------------------------------------
# SFC (Sequential Function Chart)
# ---------------------------------------------------------------------------

@st.composite
def sfc_actions(draw: st.DrawFn, name: str | None = None, max_depth: int = 1, var_pool: list[str] | None = None) -> Action:
    """Generate an SFC Action with inline body."""
    action_name = name or draw(identifiers(min_size=2))
    qualifier = draw(st.sampled_from(list(ActionQualifier)))
    duration = None
    if qualifier in (ActionQualifier.L, ActionQualifier.D, ActionQualifier.SD, ActionQualifier.DS, ActionQualifier.SL):
        duration = draw(st.sampled_from(["T#1s", "T#5s", "T#100ms"]))
    body = draw(statement_lists(min_size=0, max_size=2, max_depth=max_depth, var_pool=var_pool))
    return Action(name=action_name, qualifier=qualifier, duration=duration, body=body)


@st.composite
def sfc_bodies(draw: st.DrawFn, max_depth: int = 1, var_pool: list[str] | None = None) -> SFCBody:
    """Generate a valid SFCBody with 2-5 steps in a linear chain."""
    n_steps = draw(st.integers(min_value=2, max_value=5))
    # Need unique names for steps + all actions across all steps
    n_action_names = n_steps * 3  # up to 3 actions per step (body, entry, exit)
    all_names = draw(_unique_identifiers(n_steps + n_action_names))
    step_names = all_names[:n_steps]
    action_name_pool = all_names[n_steps:]
    action_idx = 0

    steps = []
    for i, sname in enumerate(step_names):
        step_actions = []
        if draw(st.booleans()):
            step_actions = [draw(sfc_actions(
                name=action_name_pool[action_idx],
                max_depth=max_depth, var_pool=var_pool,
            ))]
            action_idx += 1

        entry = []
        if draw(st.booleans()):
            entry = [draw(sfc_actions(
                name=action_name_pool[action_idx],
                max_depth=max_depth, var_pool=var_pool,
            ))]
            action_idx += 1

        exit_ = []
        if draw(st.booleans()):
            exit_ = [draw(sfc_actions(
                name=action_name_pool[action_idx],
                max_depth=max_depth, var_pool=var_pool,
            ))]
            action_idx += 1

        steps.append(Step(
            name=sname,
            is_initial=(i == 0),
            actions=step_actions,
            entry_actions=entry,
            exit_actions=exit_,
        ))

    # Linear chain: S0 → S1 → S2 → ... → S0
    transitions = []
    for i in range(n_steps):
        src = step_names[i]
        tgt = step_names[(i + 1) % n_steps]
        cond = draw(expressions(max_depth=1, var_pool=var_pool))
        transitions.append(SFCTransition(
            source_steps=[src], target_steps=[tgt], condition=cond,
        ))

    return SFCBody(steps=steps, transitions=transitions)


# ---------------------------------------------------------------------------
# Networks, POUInterface, POU
# ---------------------------------------------------------------------------

@st.composite
def networks(
    draw: st.DrawFn,
    max_stmts: int = 5,
    max_depth: int = 2,
    var_pool: list[str] | None = None,
) -> Network:
    stmts = draw(statement_lists(min_size=1, max_size=max_stmts, max_depth=max_depth, var_pool=var_pool))
    label = draw(st.one_of(st.none(), identifiers()))
    comment = draw(st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=40, alphabet="abcdefghijklmnopqrstuvwxyz 0123456789")))
    return Network(statements=stmts, label=label, comment=comment)


@st.composite
def pou_interfaces(draw: st.DrawFn) -> POUInterface:
    """Generate a POUInterface with unique variable names across all sections."""
    total = draw(st.integers(min_value=2, max_value=12))
    names = draw(_unique_identifiers(total))

    # Split names across input/output/static (the most common sections)
    n_in = draw(st.integers(min_value=1, max_value=max(1, total // 3)))
    n_out = draw(st.integers(min_value=1, max_value=max(1, (total - n_in) // 2)))
    n_static = total - n_in - n_out

    def make_vars(name_list: list[str]) -> list[Variable]:
        return [Variable(name=n, data_type=draw(primitive_type_refs())) for n in name_list]

    return POUInterface(
        input_vars=make_vars(names[:n_in]),
        output_vars=make_vars(names[n_in:n_in + n_out]),
        static_vars=make_vars(names[n_in + n_out:]) if n_static > 0 else [],
    )


@st.composite
def pous(draw: st.DrawFn, max_networks: int = 3, max_depth: int = 2) -> POU:
    """Generate a complete POU with interface and networks.

    The generated networks reference variables from the interface,
    making the POU somewhat semantically coherent.
    """
    pou_type = draw(st.sampled_from([POUType.FUNCTION_BLOCK, POUType.PROGRAM]))
    name = draw(identifiers(min_size=3, max_size=15))
    iface = draw(pou_interfaces())

    # Build a variable pool from the interface for coherent references
    var_pool = (
        [v.name for v in iface.input_vars]
        + [v.name for v in iface.output_vars]
        + [v.name for v in iface.static_vars]
    )

    n_nets = draw(st.integers(min_value=1, max_value=max_networks))
    nets = [
        draw(networks(max_stmts=4, max_depth=max_depth, var_pool=var_pool))
        for _ in range(n_nets)
    ]

    return POU(
        pou_type=pou_type,
        name=name,
        interface=iface,
        networks=nets,
    )


@st.composite
def methods(draw: st.DrawFn, max_depth: int = 1, var_pool: list[str] | None = None) -> Method:
    """Generate a Method with its own interface and body."""
    name = draw(identifiers(min_size=2))
    access = draw(st.sampled_from(list(AccessSpecifier)))
    return_type = draw(st.one_of(st.none(), primitive_type_refs()))
    iface = draw(pou_interfaces())
    method_vars = (
        [v.name for v in iface.input_vars]
        + [v.name for v in iface.output_vars]
        + [v.name for v in iface.static_vars]
    )
    nets = [draw(networks(max_stmts=3, max_depth=max_depth, var_pool=method_vars or var_pool))]
    return Method(
        name=name, access=access, return_type=return_type,
        interface=iface, networks=nets,
    )


@st.composite
def properties(draw: st.DrawFn, max_depth: int = 1, var_pool: list[str] | None = None) -> Property:
    """Generate a Property with optional getter/setter."""
    name = draw(identifiers(min_size=2))
    data_type = draw(primitive_type_refs())
    access = draw(st.sampled_from(list(AccessSpecifier)))
    getter = None
    setter = None
    if draw(st.booleans()):
        getter = PropertyAccessor(
            networks=[draw(networks(max_stmts=2, max_depth=max_depth, var_pool=var_pool))],
        )
    if draw(st.booleans()):
        setter = PropertyAccessor(
            networks=[draw(networks(max_stmts=2, max_depth=max_depth, var_pool=var_pool))],
        )
    return Property(name=name, data_type=data_type, access=access, getter=getter, setter=setter)


@st.composite
def pou_actions(draw: st.DrawFn, max_depth: int = 1, var_pool: list[str] | None = None) -> POUAction:
    """Generate a named POU action."""
    name = draw(identifiers(min_size=2))
    body = [draw(networks(max_stmts=3, max_depth=max_depth, var_pool=var_pool))]
    return POUAction(name=name, body=body)


@st.composite
def rich_pous(draw: st.DrawFn, max_networks: int = 3, max_depth: int = 2) -> POU:
    """Generate POUs with methods, properties, actions, and optionally SFC body."""
    pou_type = draw(st.sampled_from([POUType.FUNCTION_BLOCK, POUType.PROGRAM]))
    name = draw(identifiers(min_size=3, max_size=15))
    iface = draw(pou_interfaces())
    var_pool = (
        [v.name for v in iface.input_vars]
        + [v.name for v in iface.output_vars]
        + [v.name for v in iface.static_vars]
    )

    use_sfc = draw(st.booleans())

    if use_sfc:
        sfc = draw(sfc_bodies(max_depth=1, var_pool=var_pool))
        nets = []
    else:
        sfc = None
        n_nets = draw(st.integers(min_value=1, max_value=max_networks))
        nets = [draw(networks(max_stmts=4, max_depth=max_depth, var_pool=var_pool)) for _ in range(n_nets)]

    # OOP: methods, properties, actions — all names must be unique
    n_methods = draw(st.integers(min_value=0, max_value=2)) if pou_type == POUType.FUNCTION_BLOCK else 0
    n_props = draw(st.integers(min_value=0, max_value=2)) if pou_type == POUType.FUNCTION_BLOCK else 0
    n_actions = draw(st.integers(min_value=0, max_value=2))
    total_oop = n_methods + n_props + n_actions
    oop_names = draw(_unique_identifiers(total_oop)) if total_oop > 0 else []

    method_list = [
        draw(methods(max_depth=1, var_pool=var_pool)).model_copy(update={"name": oop_names[i]})
        for i in range(n_methods)
    ]
    prop_list = [
        draw(properties(max_depth=1, var_pool=var_pool)).model_copy(update={"name": oop_names[n_methods + i]})
        for i in range(n_props)
    ]
    action_list = [
        draw(pou_actions(max_depth=1, var_pool=var_pool)).model_copy(update={"name": oop_names[n_methods + n_props + i]})
        for i in range(n_actions)
    ]

    return POU(
        pou_type=pou_type, name=name, interface=iface,
        networks=nets, sfc_body=sfc,
        methods=method_list, properties=prop_list, actions=action_list,
    )


# ---------------------------------------------------------------------------
# GlobalVariableList
# ---------------------------------------------------------------------------

@st.composite
def global_variable_lists(draw: st.DrawFn) -> GlobalVariableList:
    name = draw(identifiers(min_size=3))
    vars_ = draw(variable_lists(min_size=1, max_size=6))
    return GlobalVariableList(name=name, variables=vars_)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def tasks() -> st.SearchStrategy:
    return st.one_of(
        st.builds(
            PeriodicTask,
            name=identifiers(min_size=3),
            interval=st.sampled_from(["T#10ms", "T#20ms", "T#100ms", "T#1s"]),
        ),
        st.builds(
            ContinuousTask,
            name=identifiers(min_size=3),
        ),
        st.builds(
            EventTask,
            name=identifiers(min_size=3),
            trigger_variable=identifiers(min_size=2),
        ),
        st.builds(
            StartupTask,
            name=identifiers(min_size=3),
        ),
    )


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

@st.composite
def projects(draw: st.DrawFn, max_pous: int = 4, max_depth: int = 2) -> Project:
    """Generate a complete Project with POUs, types, GVLs, and tasks.

    Ensures all names are unique across the project.
    """
    n_pous = draw(st.integers(min_value=1, max_value=max_pous))
    n_types = draw(st.integers(min_value=0, max_value=2))
    n_gvls = draw(st.integers(min_value=0, max_value=2))

    # Generate unique names for everything
    total_names = 1 + n_pous + n_types + n_gvls + 1  # project + pous + types + gvls + task
    all_names = draw(_unique_identifiers(total_names))
    idx = 0

    proj_name = all_names[idx]; idx += 1

    pou_list = []
    for i in range(n_pous):
        p = draw(pous(max_networks=2, max_depth=max_depth))
        # Override name to ensure uniqueness
        pou_list.append(p.model_copy(update={"name": all_names[idx]}))
        idx += 1

    type_list = []
    for i in range(n_types):
        td = draw(type_definitions())
        type_list.append(td.model_copy(update={"name": all_names[idx]}))
        idx += 1

    gvl_list = []
    for i in range(n_gvls):
        gvl = draw(global_variable_lists())
        gvl_list.append(gvl.model_copy(update={"name": all_names[idx]}))
        idx += 1

    task_name = all_names[idx]
    task = PeriodicTask(
        name=task_name,
        interval="T#10ms",
        assigned_pous=[pou_list[0].name] if pou_list else [],
    )

    return Project(
        name=proj_name,
        pous=pou_list,
        data_types=type_list,
        global_variable_lists=gvl_list,
        tasks=[task],
    )


@st.composite
def rich_projects(draw: st.DrawFn, max_pous: int = 3, max_depth: int = 2) -> Project:
    """Generate a Project using rich_pous (with methods, properties, SFC)."""
    n_pous = draw(st.integers(min_value=1, max_value=max_pous))
    n_types = draw(st.integers(min_value=0, max_value=2))
    n_gvls = draw(st.integers(min_value=0, max_value=2))

    total_names = 1 + n_pous + n_types + n_gvls + 1
    all_names = draw(_unique_identifiers(total_names))
    idx = 0

    proj_name = all_names[idx]; idx += 1

    pou_list = []
    for i in range(n_pous):
        p = draw(rich_pous(max_networks=2, max_depth=max_depth))
        pou_list.append(p.model_copy(update={"name": all_names[idx]}))
        idx += 1

    type_list = []
    for i in range(n_types):
        td = draw(type_definitions())
        type_list.append(td.model_copy(update={"name": all_names[idx]}))
        idx += 1

    gvl_list = []
    for i in range(n_gvls):
        gvl = draw(global_variable_lists())
        gvl_list.append(gvl.model_copy(update={"name": all_names[idx]}))
        idx += 1

    task_name = all_names[idx]
    task = draw(tasks()).model_copy(update={"name": task_name})

    return Project(
        name=proj_name,
        pous=pou_list,
        data_types=type_list,
        global_variable_lists=gvl_list,
        tasks=[task],
    )

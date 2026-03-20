"""Universal PLC Data Model — public API.

Vendor-agnostic Pydantic v2 models representing PLC programs, types,
variables, expressions, and statements.  This is the compilation target
for the Python framework and the interchange format between vendor layers.

Usage example::

    from plx.model import (
        POU, POUType, POUInterface, Network, Variable,
        Assignment, VariableRef, LiteralExpr,
        PrimitiveTypeRef, PrimitiveType, Project,
    )

    # Create a variable
    speed = Variable(
        name="speed",
        data_type=PrimitiveTypeRef(type=PrimitiveType.REAL),
        initial_value="0.0",
    )

    # Create a simple POU with one assignment
    pou = POU(
        pou_type=POUType.PROGRAM,
        name="Main",
        interface=POUInterface(output_vars=[speed]),
        networks=[
            Network(statements=[
                Assignment(
                    target=VariableRef(name="speed"),
                    value=LiteralExpr(value="100.0"),
                ),
            ]),
        ],
    )

    # Assemble into a project
    project = Project(name="MyProject", pous=[pou])
"""

from ._base import IRModel
from .expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from .pou import (
    POU,
    AccessSpecifier,
    Language,
    Method,
    Network,
    POUAction,
    POUInterface,
    POUType,
    Property,
    PropertyAccessor,
)
from .project import (
    GlobalVariableList,
    Project,
)
from .sfc import (
    Action,
    ActionQualifier,
    SFCBody,
    Step,
    Transition as SFCTransition,
)
from .statements import (
    Assignment,
    CaseBranch,
    CaseRange,
    CaseStatement,
    ContinueStatement,
    EmptyStatement,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfBranch,
    IfStatement,
    JumpStatement,
    LabelStatement,
    PragmaStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    TryCatchStatement,
    WhileStatement,
)
from .task import (
    ContinuousTask,
    EventTask,
    PeriodicTask,
    StartupTask,
    Task,
)
from .types import (
    AliasType,
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
    SubrangeType,
    TypeDefinition,
    TypeRef,
    UnionType,
)
from .variables import Variable
from .walk import (
    walk_expressions,
    walk_statements,
    walk_pou,
    walk_project,
)

__all__ = [
    # base
    "IRModel",
    # types — references
    "PrimitiveType",
    "PrimitiveTypeRef",
    "StringTypeRef",
    "NamedTypeRef",
    "DimensionRange",
    "ArrayTypeRef",
    "PointerTypeRef",
    "ReferenceTypeRef",
    "TypeRef",
    # types — definitions
    "StructMember",
    "StructType",
    "EnumMember",
    "EnumType",
    "UnionType",
    "AliasType",
    "SubrangeType",
    "TypeDefinition",
    # variables
    "Variable",
    # expressions
    "BinaryOp",
    "UnaryOp",
    "LiteralExpr",
    "VariableRef",
    "BinaryExpr",
    "UnaryExpr",
    "CallArg",
    "FunctionCallExpr",
    "ArrayAccessExpr",
    "MemberAccessExpr",
    "BitAccessExpr",
    "TypeConversionExpr",
    "DerefExpr",
    "SubstringExpr",
    "SystemFlag",
    "SystemFlagExpr",
    "Expression",
    # statements
    "Assignment",
    "IfBranch",
    "IfStatement",
    "CaseRange",
    "CaseBranch",
    "CaseStatement",
    "ForStatement",
    "WhileStatement",
    "RepeatStatement",
    "ExitStatement",
    "ContinueStatement",
    "ReturnStatement",
    "FunctionCallStatement",
    "FBInvocation",
    "EmptyStatement",
    "PragmaStatement",
    "TryCatchStatement",
    "JumpStatement",
    "LabelStatement",
    "Statement",
    # sfc
    "ActionQualifier",
    "Action",
    "Step",
    "SFCTransition",
    "SFCBody",
    # pou
    "POUType",
    "AccessSpecifier",
    "Language",
    "Network",
    "POUInterface",
    "PropertyAccessor",
    "Property",
    "Method",
    "POUAction",
    "POU",
    # task
    "PeriodicTask",
    "ContinuousTask",
    "EventTask",
    "StartupTask",
    "Task",
    # project
    "GlobalVariableList",
    "Project",
    # walk
    "walk_expressions",
    "walk_statements",
    "walk_pou",
    "walk_project",
]

"""Shared compiler constants, classes, and utilities.

This module holds everything that mixin modules (_compiler_expressions,
_compiler_sentinels, _compiler_statements) and other framework modules
need from the compiler layer.  By centralising these here, mixin modules
can import at the top level — eliminating the late-import pattern that
previously existed in _compiler.py.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from plx.model.expressions import (
    BinaryOp,
    SystemFlag,
)
from plx.model.statements import (
    Statement,
)
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    TypeRef,
)
from plx.model.variables import Variable

from ._descriptors import VarDirection


# ---------------------------------------------------------------------------
# CompileError
# ---------------------------------------------------------------------------

class CompileError(Exception):
    """Error during AST compilation with source location."""

    def __init__(self, message: str, node: ast.AST | None = None, ctx: CompileContext | None = None):
        self.source_file = "<unknown>"
        self.source_line: int | None = None
        if node is not None and ctx is not None:
            self.source_file = ctx.source_file
            lineno = getattr(node, "lineno", None)
            if lineno is not None:
                self.source_line = lineno + ctx.source_line_offset
        loc = ""
        if self.source_line is not None:
            loc = f" ({self.source_file}:{self.source_line})"
        super().__init__(f"{message}{loc}")


# ---------------------------------------------------------------------------
# CompileContext
# ---------------------------------------------------------------------------

@dataclass
class CompileContext:
    """Mutable state carried through compilation."""

    declared_vars: dict[str, VarDirection] = field(default_factory=dict)
    """name -> direction (input/output/static/inout/temp)"""

    static_var_types: dict[str, TypeRef] = field(default_factory=dict)
    """name -> TypeRef for static vars (used for FB call resolution)"""

    generated_static_vars: list[Variable] = field(default_factory=list)
    """Auto-created FB instances (TON, R_TRIG, etc.)"""

    generated_temp_vars: list[Variable] = field(default_factory=list)
    """Discovered temp vars from type annotations"""

    pending_fb_invocations: list[Statement] = field(default_factory=list)
    """FBInvocations to flush before the next statement"""

    pou_class: type | None = None
    """The class being compiled (needed for super().logic() resolution)"""

    known_enums: dict[str, dict[str, int]] = field(default_factory=dict)
    """enum_name -> {member_name: int_value} for enum literal resolution"""

    source_line_offset: int = 0
    source_file: str = "<unknown>"
    _auto_counter: int = 0

    def next_auto_name(self, prefix: str) -> str:
        """Generate a unique instance name like ``_plx_ton_0``."""
        name = f"_plx_{prefix}_{self._auto_counter}"
        self._auto_counter += 1
        return name


# ---------------------------------------------------------------------------
# AST operator maps
# ---------------------------------------------------------------------------

_BINOP_MAP: dict[type, BinaryOp] = {
    ast.Add: BinaryOp.ADD,
    ast.Sub: BinaryOp.SUB,
    ast.Mult: BinaryOp.MUL,
    ast.Div: BinaryOp.DIV,
    ast.Mod: BinaryOp.MOD,
    ast.BitXor: BinaryOp.XOR,
    ast.LShift: BinaryOp.SHL,
    ast.RShift: BinaryOp.SHR,
    ast.Pow: BinaryOp.EXPT,
}

_REJECTED_BINOP_MESSAGES: dict[type, str] = {
    ast.FloorDiv: "Floor division (//) is not supported — PLC division has no floor variant. Use / instead.",
    ast.BitAnd: "Bitwise & is not supported in logic(). Use 'and' for logical AND.",
    ast.BitOr: "Bitwise | is not supported in logic(). Use 'or' for logical OR.",
}

_REJECTED_AUGOP_MESSAGES: dict[type, str] = {
    ast.FloorDiv: "Floor division (//=) is not supported — PLC division has no floor variant. Use /= instead.",
    ast.BitAnd: "Bitwise &= is not supported in logic(). Use 'and' for logical AND.",
    ast.BitOr: "Bitwise |= is not supported in logic(). Use 'or' for logical OR.",
}

_CMPOP_MAP: dict[type, BinaryOp] = {
    ast.Eq: BinaryOp.EQ,
    ast.NotEq: BinaryOp.NE,
    ast.Gt: BinaryOp.GT,
    ast.GtE: BinaryOp.GE,
    ast.Lt: BinaryOp.LT,
    ast.LtE: BinaryOp.LE,
}

_REJECTED_CMPOP_MESSAGES: dict[type, str] = {
    ast.In: "'in' is not supported in PLC logic. Use: if x == 1 or x == 2 or x == 3",
    ast.NotIn: "'not in' is not supported in PLC logic. Use: if x != 1 and x != 2 and x != 3",
    ast.Is: "'is' is not supported in PLC logic. Use == for equality.",
    ast.IsNot: "'is not' is not supported in PLC logic. Use != for inequality.",
}

_TYPE_CONV_RE = re.compile(r"^([A-Z_][A-Za-z0-9_]*)_TO_([A-Z_][A-Za-z0-9_]*)$")
_BIT_ACCESS_RE = re.compile(r"^bit(\d+)$")

_BUILTIN_FUNCS = frozenset({
    "ABS", "SQRT", "LN", "LOG", "EXP", "SIN", "COS", "TAN",
    "ASIN", "ACOS", "ATAN", "ATAN2",
    "MIN", "MAX", "LIMIT", "SEL", "MUX",
    "SHL", "SHR", "ROL", "ROR",
    "TRUNC", "ROUND",
    "LEN", "LEFT", "RIGHT", "MID", "CONCAT", "FIND", "REPLACE", "INSERT", "DELETE",
    "AND", "OR", "XOR", "NOT",
})

_PYTHON_BUILTIN_MAP: dict[str, str] = {
    "abs": "ABS",
    "min": "MIN",
    "max": "MAX",
    "len": "LEN",
}

_REJECTED_BUILTINS: dict[str, str] = {
    "print": "print() does not exist in PLC logic.",
    "input": "input() does not exist in PLC logic.",
    "open": "open() does not exist in PLC logic.",
    "str": "str() is not supported. Use type conversion functions like INT_TO_STRING().",
    "int": "int() is not supported. Use type conversion functions like REAL_TO_INT().",
    "float": "float() is not supported. Use type conversion functions like INT_TO_REAL().",
    "bool": "bool() is not supported. Use type conversion functions like INT_TO_BOOL().",
    "type": "type() is not supported. PLCs are statically typed.",
    "isinstance": "isinstance() is not supported. PLCs are statically typed.",
    "list": "list() is not supported. Use ARRAY or @struct.",
    "dict": "dict() is not supported. Use @struct.",
    "set": "set() is not supported. Use ARRAY or @struct.",
    "tuple": "tuple() is not supported. Use ARRAY or @struct.",
    "enumerate": "enumerate() is not supported. Use a for loop with range().",
    "zip": "zip() is not supported. Use a for loop with range().",
    "map": "map() is not supported. Use a for loop with range().",
    "filter": "filter() is not supported. Use a for loop with range().",
    "sorted": "sorted() is not supported. Use a for loop with range().",
    "reversed": "reversed() is not supported. Use a for loop with range().",
    "sum": "sum() is not supported. Use a for loop with range().",
    "any": "any() is not supported. Use a for loop with range().",
    "all": "all() is not supported. Use a for loop with range().",
    "round": "round() is not supported. Use IEC ROUND() (uppercase).",
    "repr": "repr() does not exist in PLC logic.",
    "format": "format() does not exist in PLC logic.",
}

# Sentinel function names
_TIMER_SENTINELS = {
    "delayed": ("TON", "IN", "PT"),
    "sustained": ("TOF", "IN", "PT"),
    "pulse": ("TP", "IN", "PT"),
}

_EDGE_SENTINELS = {
    "rising": "R_TRIG",
    "falling": "F_TRIG",
}

_COUNTER_SENTINELS = {
    "count_up": ("CTU", "CU", "PV", "RESET"),
    "count_down": ("CTD", "CD", "PV", "LOAD"),
}

_BISTABLE_SENTINELS = {
    "set_dominant": ("SR", "SET1", "RESET"),
    "reset_dominant": ("RS", "SET", "RESET1"),
}

_SYSTEM_FLAG_SENTINELS = {
    "first_scan": SystemFlag.FIRST_SCAN,
}

# Complete set of rejected AST node types
_REJECTED_NODES: dict[type, str] = {
    ast.FunctionDef: "Function definitions are not allowed in PLC logic. Define reusable logic as a separate @fb or @function class.",
    ast.AsyncFunctionDef: "Async functions are not allowed in PLC logic. PLCs execute synchronously in scan cycles.",
    ast.ClassDef: "Class definitions are not allowed in PLC logic. Define types at module level with @struct or @fb.",
    ast.Delete: "del statements are not allowed in PLC logic. PLC variables persist for the life of the program.",
    ast.With: "with statements are not allowed in PLC logic. Context managers don't exist in PLC.",
    ast.AsyncWith: "async with statements are not allowed in PLC logic. PLCs execute synchronously in scan cycles.",
    ast.AsyncFor: "async for statements are not allowed in PLC logic. PLCs execute synchronously in scan cycles.",
    ast.Raise: "raise statements are not allowed in PLC logic. PLCs don't have exceptions — use if/else and error flags.",
    ast.Try: "try/except statements are not allowed in PLC logic. PLCs don't have exceptions — use if/else and error flags.",
    ast.Assert: "assert statements are not allowed in PLC logic. Use if/else to validate conditions and set fault flags.",
    ast.Import: "import statements are not allowed in PLC logic. Imports belong at module level, outside logic().",
    ast.ImportFrom: "import statements are not allowed in PLC logic. Imports belong at module level, outside logic().",
    ast.Global: "global statements are not allowed in PLC logic. Use global_var() to define global variables.",
    ast.Nonlocal: "nonlocal statements are not allowed in PLC logic.",
    ast.NamedExpr: "Walrus operator (:=) is not allowed in PLC logic. Assign to a temp variable on a separate line.",
    ast.Lambda: "Lambda expressions are not allowed in PLC logic. Define reusable logic as a separate @fb or @function class.",
    ast.Dict: "Dict literals are not allowed in PLC logic. Use @struct to define structured data.",
    ast.Set: "Set literals are not allowed in PLC logic. Use ARRAY or @struct.",
    ast.List: "List literals are not allowed in PLC logic. Use ARRAY or @struct.",
    ast.Tuple: "Tuple literals are not allowed in PLC logic. Use ARRAY or @struct.",
    ast.ListComp: "List comprehensions are not allowed in PLC logic. Use a for loop with range().",
    ast.SetComp: "Set comprehensions are not allowed in PLC logic. Use a for loop with range().",
    ast.DictComp: "Dict comprehensions are not allowed in PLC logic. Use a for loop with range().",
    ast.GeneratorExp: "Generator expressions are not allowed in PLC logic. Use a for loop with range().",
    ast.Await: "await expressions are not allowed in PLC logic. PLCs execute synchronously in scan cycles.",
    ast.Yield: "yield expressions are not allowed in PLC logic. PLCs execute synchronously in scan cycles.",
    ast.YieldFrom: "yield from expressions are not allowed in PLC logic. PLCs execute synchronously in scan cycles.",
    ast.FormattedValue: "f-string expressions are not allowed in PLC logic. Use CONCAT() for string assembly.",
    ast.JoinedStr: "f-strings are not allowed in PLC logic. Use CONCAT() for string assembly.",
    ast.Starred: "Star unpacking is not allowed in PLC logic. Assign each variable on a separate line.",
    ast.Slice: "Slice operations are not allowed in PLC logic. Access array elements individually with a single index: arr[i].",
}

# Also reject TryStar if available (Python 3.11+)
if hasattr(ast, "TryStar"):
    _REJECTED_NODES[ast.TryStar] = "try/except* statements are not allowed in PLC logic. PLCs don't have exceptions — use if/else and error flags."


# ---------------------------------------------------------------------------
# Annotation resolution (shared by compiler + decorators)
# ---------------------------------------------------------------------------

def resolve_annotation(
    ann: ast.expr,
    *,
    node: ast.AST | None = None,
    ctx: CompileContext | None = None,
    location_hint: str = "",
) -> TypeRef | None:
    """Resolve a type annotation AST node to a TypeRef.

    Handles ``ast.Name``, ``ast.Attribute``, and ``ast.Constant(None)`` → None.
    Used by both the ASTCompiler and ``_decorators.py``.
    """
    if isinstance(ann, ast.Name):
        try:
            return PrimitiveTypeRef(type=PrimitiveType(ann.id))
        except ValueError:
            return NamedTypeRef(name=ann.id)
    if isinstance(ann, ast.Attribute):
        return NamedTypeRef(name=ann.attr)
    if isinstance(ann, ast.Constant) and ann.value is None:
        return None
    msg = f"Unsupported type annotation: {ast.dump(ann)}"
    if location_hint:
        msg = f"{msg} ({location_hint})"
    raise CompileError(msg, node, ctx)

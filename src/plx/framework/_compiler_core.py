"""Shared compiler constants, classes, and utilities.

This module holds everything that mixin modules (_compiler_expressions,
_compiler_sentinels, _compiler_statements) and other framework modules
need from the compiler layer.  By centralising these here, mixin modules
can import at the top level — eliminating the late-import pattern that
previously existed in _compiler.py.
"""

from __future__ import annotations

import ast
import dataclasses
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
    StringTypeRef,
    TypeRef,
)
from plx.model.variables import Variable

from ._descriptors import VarDirection
from ._errors import PlxError


# ---------------------------------------------------------------------------
# CompileError
# ---------------------------------------------------------------------------

class CompileError(PlxError):
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

    known_methods: set[str] = field(default_factory=set)
    """Names of @method-decorated functions on the POU being compiled"""

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
    ast.BitAnd: BinaryOp.BAND,
    ast.BitOr: BinaryOp.BOR,
    ast.LShift: BinaryOp.SHL,
    ast.RShift: BinaryOp.SHR,
    ast.Pow: BinaryOp.EXPT,
}

_REJECTED_BINOP_MESSAGES: dict[type, str] = {
}

_REJECTED_AUGOP_MESSAGES: dict[type, str] = {
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
    ast.Is: "'is' is not supported in PLC logic. Use == for equality.",
    ast.IsNot: "'is not' is not supported in PLC logic. Use != for inequality.",
}

_TYPE_CONV_RE = re.compile(r"^([A-Z_][A-Za-z0-9_]*)_TO_([A-Z_][A-Za-z0-9_]*)$")
_BIT_ACCESS_RE = re.compile(r"^bit(\d+)$")

# Maps PrimitiveType → bit width for types that support bit access.
# Types not in this map (BOOL, REAL, LREAL, TIME, STRING, etc.) reject bit access.
_BIT_ACCESSIBLE_WIDTHS: dict[PrimitiveType, int] = {
    # 8-bit
    PrimitiveType.BYTE: 8,
    PrimitiveType.SINT: 8,
    PrimitiveType.USINT: 8,
    # 16-bit
    PrimitiveType.WORD: 16,
    PrimitiveType.INT: 16,
    PrimitiveType.UINT: 16,
    # 32-bit
    PrimitiveType.DWORD: 32,
    PrimitiveType.DINT: 32,
    PrimitiveType.UDINT: 32,
    # 64-bit
    PrimitiveType.LWORD: 64,
    PrimitiveType.LINT: 64,
    PrimitiveType.ULINT: 64,
}

_BUILTIN_FUNCS = frozenset({
    "ABS", "SQRT", "LN", "LOG", "EXP", "SIN", "COS", "TAN",
    "ASIN", "ACOS", "ATAN",
    "CEIL", "FLOOR",
    "MIN", "MAX", "LIMIT", "SEL", "MUX",
    "SHL", "SHR", "ROL", "ROR",
    "TRUNC", "ROUND",
    "LEN", "LEFT", "RIGHT", "MID", "FIND", "REPLACE", "INSERT", "DELETE",
    "AND", "OR", "XOR", "NOT",
})

_PYTHON_BUILTIN_MAP: dict[str, str] = {
    "abs": "ABS",
    "min": "MIN",
    "max": "MAX",
    "len": "LEN",
    "round": "ROUND",
}

# math module function mapping: math.func() → IEC function
_MATH_FUNC_MAP: dict[str, str] = {
    "sqrt": "SQRT",
    "log": "LN",
    "log10": "LOG",
    "exp": "EXP",
    "sin": "SIN",
    "cos": "COS",
    "tan": "TAN",
    "asin": "ASIN",
    "acos": "ACOS",
    "atan": "ATAN",
    "fabs": "ABS",
    "trunc": "TRUNC",
    "ceil": "CEIL",
    "floor": "FLOOR",
}

# math module constants: math.pi, math.e → IEC LREAL literals
_MATH_CONSTANTS: dict[str, str] = {
    "pi": "3.141592653589793",
    "e": "2.718281828459045",
    "tau": "6.283185307179586",
    "inf": "1.0E+308",
}

_PYTHON_ANNOTATION_MAP: dict[str, TypeRef] = {
    "bool": PrimitiveTypeRef(type=PrimitiveType.BOOL),
    "int": PrimitiveTypeRef(type=PrimitiveType.INT),
    "float": PrimitiveTypeRef(type=PrimitiveType.REAL),
    "str": StringTypeRef(wide=False, max_length=255),
    # Lowercase PLC types — integer
    "sint": PrimitiveTypeRef(type=PrimitiveType.SINT),
    "dint": PrimitiveTypeRef(type=PrimitiveType.DINT),
    "lint": PrimitiveTypeRef(type=PrimitiveType.LINT),
    "usint": PrimitiveTypeRef(type=PrimitiveType.USINT),
    "uint": PrimitiveTypeRef(type=PrimitiveType.UINT),
    "udint": PrimitiveTypeRef(type=PrimitiveType.UDINT),
    "ulint": PrimitiveTypeRef(type=PrimitiveType.ULINT),
    "real": PrimitiveTypeRef(type=PrimitiveType.REAL),
    "lreal": PrimitiveTypeRef(type=PrimitiveType.LREAL),
    # Lowercase PLC types — bit-string
    "byte": PrimitiveTypeRef(type=PrimitiveType.BYTE),
    "word": PrimitiveTypeRef(type=PrimitiveType.WORD),
    "dword": PrimitiveTypeRef(type=PrimitiveType.DWORD),
    "lword": PrimitiveTypeRef(type=PrimitiveType.LWORD),
    # Lowercase PLC types — time
    "time": PrimitiveTypeRef(type=PrimitiveType.TIME),
    "ltime": PrimitiveTypeRef(type=PrimitiveType.LTIME),
    # Lowercase PLC types — date
    "date": PrimitiveTypeRef(type=PrimitiveType.DATE),
    "ldate": PrimitiveTypeRef(type=PrimitiveType.LDATE),
    "tod": PrimitiveTypeRef(type=PrimitiveType.TOD),
    "ltod": PrimitiveTypeRef(type=PrimitiveType.LTOD),
    "dt": PrimitiveTypeRef(type=PrimitiveType.DT),
    "ldt": PrimitiveTypeRef(type=PrimitiveType.LDT),
    # Lowercase PLC types — character
    "char": PrimitiveTypeRef(type=PrimitiveType.CHAR),
    "wchar": PrimitiveTypeRef(type=PrimitiveType.WCHAR),
    # Lowercase FB type names
    "ton": NamedTypeRef(name="TON"),
    "tof": NamedTypeRef(name="TOF"),
    "tp": NamedTypeRef(name="TP"),
    "rto": NamedTypeRef(name="RTO"),
    "r_trig": NamedTypeRef(name="R_TRIG"),
    "f_trig": NamedTypeRef(name="F_TRIG"),
    "ctu": NamedTypeRef(name="CTU"),
    "ctd": NamedTypeRef(name="CTD"),
    "ctud": NamedTypeRef(name="CTUD"),
    "sr": NamedTypeRef(name="SR"),
    "rs": NamedTypeRef(name="RS"),
}

_PYTHON_TYPE_CONV_MAP: dict[str, TypeRef] = {
    "int": PrimitiveTypeRef(type=PrimitiveType.INT),
    "float": PrimitiveTypeRef(type=PrimitiveType.REAL),
    "bool": PrimitiveTypeRef(type=PrimitiveType.BOOL),
}

_REJECTED_BUILTINS: dict[str, str] = {
    "print": "print() does not exist in PLC logic.",
    "input": "input() does not exist in PLC logic.",
    "open": "open() does not exist in PLC logic.",
    "str": "str() is not supported in PLC logic. Use INT_TO_STRING(), REAL_TO_STRING(), etc.",
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
    "repr": "repr() does not exist in PLC logic.",
    "format": "format() does not exist in PLC logic.",
    "CONCAT": "CONCAT() is not available directly. Use an f-string instead: f\"prefix {self.var}\"",
}

# ---------------------------------------------------------------------------
# Unified sentinel registry
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class SentinelDef:
    """Metadata for a single sentinel function."""

    name: str                   # Python function name (e.g. "delayed")
    category: str               # "timer" | "edge" | "counter" | "bistable" | "system_flag"
    fb_type: str                # IEC FB type (e.g. "TON", "R_TRIG")
    params: dict[str, str] = dataclasses.field(default_factory=dict)
    system_flag: SystemFlag | None = None


SENTINEL_REGISTRY: dict[str, SentinelDef] = {
    "delayed": SentinelDef(
        name="delayed", category="timer", fb_type="TON",
        params={"signal": "IN", "duration": "PT"},
    ),
    "sustained": SentinelDef(
        name="sustained", category="timer", fb_type="TOF",
        params={"signal": "IN", "duration": "PT"},
    ),
    "pulse": SentinelDef(
        name="pulse", category="timer", fb_type="TP",
        params={"signal": "IN", "duration": "PT"},
    ),
    "retentive": SentinelDef(
        name="retentive", category="timer", fb_type="RTO",
        params={"signal": "IN", "duration": "PT"},
    ),
    "rising": SentinelDef(
        name="rising", category="edge", fb_type="R_TRIG",
        params={"signal": "CLK"},
    ),
    "falling": SentinelDef(
        name="falling", category="edge", fb_type="F_TRIG",
        params={"signal": "CLK"},
    ),
    "count_up": SentinelDef(
        name="count_up", category="counter", fb_type="CTU",
        params={"signal": "CU", "preset": "PV", "control": "RESET"},
    ),
    "count_down": SentinelDef(
        name="count_down", category="counter", fb_type="CTD",
        params={"signal": "CD", "preset": "PV", "control": "LOAD"},
    ),
    "count_up_down": SentinelDef(
        name="count_up_down", category="ctud", fb_type="CTUD",
        params={"up": "CU", "down": "CD", "preset": "PV", "reset": "RESET", "load": "LOAD"},
    ),
    "set_dominant": SentinelDef(
        name="set_dominant", category="bistable", fb_type="SR",
        params={"set": "SET1", "reset": "RESET"},
    ),
    "reset_dominant": SentinelDef(
        name="reset_dominant", category="bistable", fb_type="RS",
        params={"set": "SET", "reset": "RESET1"},
    ),
    "first_scan": SentinelDef(
        name="first_scan", category="system_flag", fb_type="",
        system_flag=SystemFlag.FIRST_SCAN,
    ),
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
    ast.Global: "global statements are not allowed in PLC logic. Use @global_vars to define global variables.",
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
    ast.Starred: "Star unpacking is not allowed in PLC logic. Assign each variable on a separate line.",
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
        if ann.id in _PYTHON_ANNOTATION_MAP:
            return _PYTHON_ANNOTATION_MAP[ann.id]
        try:
            return PrimitiveTypeRef(type=PrimitiveType(ann.id.upper()))
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


# ---------------------------------------------------------------------------
# Type inference for bare assignments
# ---------------------------------------------------------------------------

def _infer_type(node: ast.expr, ctx: CompileContext) -> TypeRef | None:
    """Try to infer a PLC type from an AST expression node.

    Returns a TypeRef if the type can be determined unambiguously,
    None otherwise (caller should fall back to requiring annotation).
    """
    # Boolean literals
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return PrimitiveTypeRef(type=PrimitiveType.BOOL)
        if isinstance(node.value, int):
            return PrimitiveTypeRef(type=PrimitiveType.DINT)
        if isinstance(node.value, float):
            return PrimitiveTypeRef(type=PrimitiveType.REAL)
        if isinstance(node.value, str):
            return StringTypeRef()

    # True/False name references
    if isinstance(node, ast.Name) and node.id in ("True", "False", "TRUE", "FALSE"):
        return PrimitiveTypeRef(type=PrimitiveType.BOOL)

    # not x → BOOL
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return PrimitiveTypeRef(type=PrimitiveType.BOOL)

    # x and y, x or y → BOOL
    if isinstance(node, ast.BoolOp):
        return PrimitiveTypeRef(type=PrimitiveType.BOOL)

    # x > y, x == y, etc. → BOOL
    if isinstance(node, ast.Compare):
        return PrimitiveTypeRef(type=PrimitiveType.BOOL)

    # self.var_name → look up the declared type
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        var_type = ctx.static_var_types.get(node.attr)
        if var_type is not None:
            return var_type

    # Local variable reference → look up from generated temps
    if isinstance(node, ast.Name):
        name = node.id
        # Check generated temp vars
        for var in ctx.generated_temp_vars:
            if var.name == name:
                return var.data_type
        # Check static var types (covers input/output/static/inout)
        var_type = ctx.static_var_types.get(name)
        if var_type is not None:
            return var_type

    # Unary minus: -x → infer from operand
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _infer_type(node.operand, ctx)

    # Binary ops (arithmetic + bitwise): infer from operands
    if isinstance(node, ast.BinOp):
        left = _infer_type(node.left, ctx)
        right = _infer_type(node.right, ctx)
        if left is not None and right is not None:
            # REAL wins over integer types
            if _is_real(left) or _is_real(right):
                return PrimitiveTypeRef(type=PrimitiveType.REAL)
            return left
        return left or right

    return None


def _is_real(t: TypeRef) -> bool:
    return isinstance(t, PrimitiveTypeRef) and t.type in (PrimitiveType.REAL, PrimitiveType.LREAL)

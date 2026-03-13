"""Structured Text pretty-printer for Universal IR.

Walks Pydantic IR models and emits IEC 61131-3 Structured Text.
"""

from __future__ import annotations

import re
from io import StringIO
from typing import Union, overload

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
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
from plx.model.pou import (
    POU,
    AccessSpecifier,
    Method,
    Network,
    POUAction,
    POUInterface,
    POUType,
    Property,
    PropertyAccessor,
)
from plx.model.project import GlobalVariableList, Project
from plx.model.sfc import Action, ActionQualifier, SFCBody, Step
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    ContinueStatement,
    EmptyStatement,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
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
from plx.model.types import (
    AliasType,
    ArrayTypeRef,
    DimensionRange,
    EnumType,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
    StructType,
    SubrangeType,
    TypeDefinition,
    TypeRef,
    UnionType,
)
from plx.model.variables import Variable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@overload
def to_structured_text(target: Union[Project, POU], *, source_map: bool = False) -> str: ...
@overload
def to_structured_text(target: Union[Project, POU], *, source_map: bool = True) -> tuple[str, list[dict]]: ...

def to_structured_text(target: Union[Project, POU], *, source_map: bool = False) -> str | tuple[str, list[dict]]:
    """Emit IEC 61131-3 Structured Text for a Project or single POU.

    When *source_map* is True, returns ``(st_text, var_source_map)`` where
    ``var_source_map`` is a list of ``{"name", "line", "column"}`` dicts
    mapping each variable reference to its 1-indexed position in the ST output.
    """
    w = STWriter()
    if isinstance(target, Project):
        w.write_project(target)
    elif isinstance(target, POU):
        w.write_pou(target)
    else:
        raise TypeError(
            f"to_structured_text() expects Project or POU, got {type(target).__name__}"
        )
    st_text = w.getvalue()

    if not source_map:
        return st_text

    var_names = _collect_variable_names(target)
    smap = _build_source_map(st_text, var_names)
    return st_text, smap


def format_statement(stmt: Statement) -> str:
    """Format a single IR statement as Structured Text."""
    w = STWriter()
    w._write_stmt(stmt)
    return w.getvalue().rstrip("\n")


def format_expression(expr: Expression) -> str:
    """Format a single IR expression as Structured Text."""
    w = STWriter()
    return w._expr(expr)


# ---------------------------------------------------------------------------
# Operator maps
# ---------------------------------------------------------------------------

_BINOP_SYMBOL: dict[BinaryOp, str] = {
    BinaryOp.ADD: "+",
    BinaryOp.SUB: "-",
    BinaryOp.MUL: "*",
    BinaryOp.DIV: "/",
    BinaryOp.MOD: "MOD",
    BinaryOp.AND: "AND",
    BinaryOp.OR: "OR",
    BinaryOp.XOR: "XOR",
    BinaryOp.BAND: "AND",
    BinaryOp.BOR: "OR",
    BinaryOp.EQ: "=",
    BinaryOp.NE: "<>",
    BinaryOp.GT: ">",
    BinaryOp.GE: ">=",
    BinaryOp.LT: "<",
    BinaryOp.LE: "<=",
    BinaryOp.EXPT: "**",
    BinaryOp.AND_THEN: "AND_THEN",
    BinaryOp.OR_ELSE: "OR_ELSE",
}

# IEC 61131-3 precedence (higher = binds tighter)
_BINOP_PRECEDENCE: dict[BinaryOp, int] = {
    BinaryOp.OR_ELSE: 1,
    BinaryOp.AND_THEN: 2,
    BinaryOp.OR: 3,
    BinaryOp.BOR: 3,
    BinaryOp.XOR: 4,
    BinaryOp.AND: 5,
    BinaryOp.BAND: 5,
    BinaryOp.EQ: 6,
    BinaryOp.NE: 6,
    BinaryOp.LT: 7,
    BinaryOp.GT: 7,
    BinaryOp.LE: 7,
    BinaryOp.GE: 7,
    BinaryOp.ADD: 8,
    BinaryOp.SUB: 8,
    BinaryOp.MUL: 9,
    BinaryOp.DIV: 9,
    BinaryOp.MOD: 9,
    BinaryOp.EXPT: 10,
    # Shifts emitted as function calls, not infix
    BinaryOp.SHL: 0,
    BinaryOp.SHR: 0,
    BinaryOp.ROL: 0,
    BinaryOp.ROR: 0,
}

# Shift/rotate ops are emitted as SHL(IN, N) function calls
_SHIFT_OPS = {BinaryOp.SHL, BinaryOp.SHR, BinaryOp.ROL, BinaryOp.ROR}


# ---------------------------------------------------------------------------
# STWriter
# ---------------------------------------------------------------------------

class STWriter:
    """Walks IR models and emits Structured Text into an internal buffer."""

    def __init__(self) -> None:
        self._buf = StringIO()
        self._indent = 0
        self._indent_str = "    "

    def getvalue(self) -> str:
        return self._buf.getvalue().rstrip("\n") + "\n"

    # -- Low-level output helpers -------------------------------------------

    def _write(self, text: str) -> None:
        self._buf.write(text)

    def _line(self, text: str = "") -> None:
        if text:
            self._buf.write(self._indent_str * self._indent + text + "\n")
        else:
            self._buf.write("\n")

    def _indent_inc(self) -> None:
        self._indent += 1

    def _indent_dec(self) -> None:
        self._indent = max(0, self._indent - 1)

    # ======================================================================
    # Project
    # ======================================================================

    def write_project(self, proj: Project) -> None:
        first = True

        # Type definitions
        for td in proj.data_types:
            if not first:
                self._line()
            self.write_type_definition(td)
            first = False

        # Global variable lists
        for gvl in proj.global_variable_lists:
            if not first:
                self._line()
            self.write_global_variable_list(gvl)
            first = False

        # POUs
        for pou in proj.pous:
            if not first:
                self._line()
            self.write_pou(pou)
            first = False

    # ======================================================================
    # Type definitions
    # ======================================================================

    def write_type_definition(self, td: TypeDefinition) -> None:
        if isinstance(td, StructType):
            self._write_struct_type(td)
        elif isinstance(td, EnumType):
            self._write_enum_type(td)
        elif isinstance(td, UnionType):
            self._write_union_type(td)
        elif isinstance(td, AliasType):
            self._write_alias_type(td)
        elif isinstance(td, SubrangeType):
            self._write_subrange_type(td)

    def _write_struct_type(self, td: StructType) -> None:
        if td.extends:
            self._line(f"TYPE {td.name} EXTENDS {td.extends} :")
        else:
            self._line(f"TYPE {td.name} :")
        self._line("STRUCT")
        self._indent_inc()
        for m in td.members:
            decl = f"{m.name} : {self._type_ref(m.data_type)}"
            if m.initial_value is not None:
                decl += f" := {m.initial_value}"
            decl += ";"
            self._line(decl)
        self._indent_dec()
        self._line("END_STRUCT")
        self._line("END_TYPE")

    def _write_enum_type(self, td: EnumType) -> None:
        members = []
        for m in td.members:
            if m.value is not None:
                members.append(f"{m.name} := {m.value}")
            else:
                members.append(m.name)
        member_str = ", ".join(members)
        if td.base_type is not None:
            self._line(f"TYPE {td.name} : {td.base_type.value} (")
        else:
            self._line(f"TYPE {td.name} : (")
        self._indent_inc()
        self._line(f"{member_str}")
        self._indent_dec()
        self._line(");")
        self._line("END_TYPE")

    def _write_union_type(self, td: UnionType) -> None:
        self._line(f"TYPE {td.name} :")
        self._line("UNION")
        self._indent_inc()
        for m in td.members:
            decl = f"{m.name} : {self._type_ref(m.data_type)}"
            if m.initial_value is not None:
                decl += f" := {m.initial_value}"
            decl += ";"
            self._line(decl)
        self._indent_dec()
        self._line("END_UNION")
        self._line("END_TYPE")

    def _write_alias_type(self, td: AliasType) -> None:
        self._line(f"TYPE {td.name} : {self._type_ref(td.base_type)};")
        self._line("END_TYPE")

    def _write_subrange_type(self, td: SubrangeType) -> None:
        self._line(f"TYPE {td.name} : {td.base_type.value}({td.lower_bound}..{td.upper_bound});")
        self._line("END_TYPE")

    # ======================================================================
    # Global variable lists
    # ======================================================================

    def write_global_variable_list(self, gvl: GlobalVariableList) -> None:
        if gvl.description:
            self._line(f"// {gvl.description}")
        if gvl.qualified_only:
            self._line("{attribute 'qualified_only'}")
        self._line("VAR_GLOBAL")
        self._indent_inc()
        for v in gvl.variables:
            self._write_var_decl(v)
        self._indent_dec()
        self._line("END_VAR")

    # ======================================================================
    # POU
    # ======================================================================

    def write_pou(self, pou: POU) -> None:
        if pou.pou_type == POUType.INTERFACE:
            self._write_interface_pou(pou)
            return

        # Header
        keyword = pou.pou_type.value
        if pou.abstract:
            keyword = f"{keyword} ABSTRACT"
        header = f"{keyword} {pou.name}"
        if pou.extends:
            header += f" EXTENDS {pou.extends}"
        if pou.implements:
            header += f" IMPLEMENTS {', '.join(pou.implements)}"
        if pou.return_type is not None:
            header += f" : {self._type_ref(pou.return_type)}"
        self._line(header)

        # Variable blocks
        self._write_var_blocks(pou.interface)

        # Body
        if pou.sfc_body is not None:
            self._write_sfc_body(pou.sfc_body)
        else:
            self._write_networks(pou.networks)

        # End
        self._line(f"END_{keyword}")

        # Actions (after POU body, before methods)
        for action in pou.actions:
            self._line()
            self._write_pou_action(pou.name, action)

        # Methods
        for method in pou.methods:
            self._line()
            self._write_method(method)

        # Properties
        for prop in pou.properties:
            self._line()
            self._write_property(prop)

    def _write_interface_pou(self, pou: POU) -> None:
        self._line(f"INTERFACE {pou.name}")
        if pou.extends:
            self._line(f"EXTENDS {pou.extends}")
        for method in pou.methods:
            self._line()
            self._write_method(method, interface_only=True)
        for prop in pou.properties:
            self._line()
            self._write_property(prop, interface_only=True)
        self._line("END_INTERFACE")

    # ======================================================================
    # Variable declarations
    # ======================================================================

    def _write_var_blocks(self, iface: POUInterface) -> None:
        self._write_var_block("VAR_INPUT", iface.input_vars)
        self._write_var_block("VAR_OUTPUT", iface.output_vars)
        self._write_var_block("VAR_IN_OUT", iface.inout_vars)
        self._write_var_block("VAR", iface.static_vars)
        self._write_var_block("VAR_TEMP", iface.temp_vars)
        self._write_var_block("VAR CONSTANT", iface.constant_vars)
        self._write_var_block("VAR_EXTERNAL", iface.external_vars)

    def _write_var_block(self, keyword: str, variables: list[Variable]) -> None:
        if not variables:
            return
        self._line(keyword)
        self._indent_inc()
        for v in variables:
            self._write_var_decl(v)
        self._indent_dec()
        self._line("END_VAR")

    def _write_var_decl(self, v: Variable) -> None:
        parts = []
        if v.retain:
            parts.append("RETAIN")
        if v.persistent:
            parts.append("PERSISTENT")

        decl = f"{v.name} : {self._type_ref(v.data_type)}"
        if v.initial_value is not None:
            decl += f" := {v.initial_value}"
        decl += ";"
        if v.description:
            decl += f" // {v.description}"

        if parts:
            self._line(f"{' '.join(parts)} {decl}")
        else:
            self._line(decl)

    # ======================================================================
    # Type references
    # ======================================================================

    def _type_ref(self, tr: TypeRef) -> str:
        if isinstance(tr, PrimitiveTypeRef):
            return tr.type.value
        if isinstance(tr, StringTypeRef):
            base = "WSTRING" if tr.wide else "STRING"
            if tr.max_length is not None:
                return f"{base}[{tr.max_length}]"
            return base
        if isinstance(tr, NamedTypeRef):
            return tr.name
        if isinstance(tr, ArrayTypeRef):
            dims = ", ".join(self._dim_range(d) for d in tr.dimensions)
            return f"ARRAY[{dims}] OF {self._type_ref(tr.element_type)}"
        if isinstance(tr, PointerTypeRef):
            return f"POINTER TO {self._type_ref(tr.target_type)}"
        if isinstance(tr, ReferenceTypeRef):
            return f"REFERENCE TO {self._type_ref(tr.target_type)}"
        return "???"

    def _dim_range(self, d: DimensionRange) -> str:
        def _bound(b: int | Expression) -> str:
            if isinstance(b, int):
                return str(b)
            return format_expression(b)
        return f"{_bound(d.lower)}..{_bound(d.upper)}"

    # ======================================================================
    # Networks / statements
    # ======================================================================

    def _write_networks(self, networks: list[Network]) -> None:
        for i, net in enumerate(networks):
            if net.comment:
                if i > 0:
                    self._line()
                for comment_line in net.comment.split("\n"):
                    self._line(f"// {comment_line}")
            for stmt in net.statements:
                self._write_stmt(stmt)

    def _write_stmt(self, stmt: Statement) -> None:
        if stmt.comment:
            for cline in stmt.comment.split("\n"):
                self._line(f"// {cline}" if cline else "//")
        kind = stmt.kind
        handler = _STMT_WRITERS.get(kind)
        if handler is not None:
            handler(self, stmt)
        else:
            self._line(f"// Unsupported statement: {kind}")

    def _write_assignment(self, stmt: Assignment) -> None:
        if stmt.ref_assign:
            op = "REF="
        elif stmt.latch:
            op = f"{stmt.latch}="
        else:
            op = ":="
        self._line(f"{self._expr(stmt.target)} {op} {self._expr(stmt.value)};")

    def _write_if(self, stmt: IfStatement) -> None:
        self._line(f"IF {self._expr(stmt.if_branch.condition)} THEN")
        self._indent_inc()
        for s in stmt.if_branch.body:
            self._write_stmt(s)
        self._indent_dec()

        for branch in stmt.elsif_branches:
            self._line(f"ELSIF {self._expr(branch.condition)} THEN")
            self._indent_inc()
            for s in branch.body:
                self._write_stmt(s)
            self._indent_dec()

        if stmt.else_body:
            self._line("ELSE")
            self._indent_inc()
            for s in stmt.else_body:
                self._write_stmt(s)
            self._indent_dec()

        self._line("END_IF;")

    def _write_case(self, stmt: CaseStatement) -> None:
        self._line(f"CASE {self._expr(stmt.selector)} OF")
        self._indent_inc()
        for branch in stmt.branches:
            labels = self._case_labels(branch)
            self._line(f"{labels}:")
            self._indent_inc()
            for s in branch.body:
                self._write_stmt(s)
            self._indent_dec()
        self._indent_dec()

        if stmt.else_body:
            self._line("ELSE")
            self._indent_inc()
            for s in stmt.else_body:
                self._write_stmt(s)
            self._indent_dec()

        self._line("END_CASE;")

    @staticmethod
    def _case_labels(branch: CaseBranch) -> str:
        parts: list[str] = []
        for v in branch.values:
            parts.append(str(v))
        for r in branch.ranges:
            parts.append(f"{r.start}..{r.end}")
        return ", ".join(parts)

    def _write_for(self, stmt: ForStatement) -> None:
        header = f"FOR {stmt.loop_var} := {self._expr(stmt.from_expr)} TO {self._expr(stmt.to_expr)}"
        if stmt.by_expr is not None:
            header += f" BY {self._expr(stmt.by_expr)}"
        header += " DO"
        self._line(header)
        self._indent_inc()
        for s in stmt.body:
            self._write_stmt(s)
        self._indent_dec()
        self._line("END_FOR;")

    def _write_while(self, stmt: WhileStatement) -> None:
        self._line(f"WHILE {self._expr(stmt.condition)} DO")
        self._indent_inc()
        for s in stmt.body:
            self._write_stmt(s)
        self._indent_dec()
        self._line("END_WHILE;")

    def _write_repeat(self, stmt: RepeatStatement) -> None:
        self._line("REPEAT")
        self._indent_inc()
        for s in stmt.body:
            self._write_stmt(s)
        self._indent_dec()
        self._line(f"UNTIL {self._expr(stmt.until)}")
        self._line("END_REPEAT;")

    def _write_exit(self, _stmt: ExitStatement) -> None:
        self._line("EXIT;")

    def _write_continue(self, _stmt: ContinueStatement) -> None:
        self._line("CONTINUE;")

    def _write_return(self, stmt: ReturnStatement) -> None:
        if stmt.value is not None:
            self._line(f"RETURN {self._expr(stmt.value)};")
        else:
            self._line("RETURN;")

    def _write_function_call_stmt(self, stmt: FunctionCallStatement) -> None:
        args = ", ".join(self._call_arg(a) for a in stmt.args)
        self._line(f"{stmt.function_name}({args});")

    def _write_fb_invocation(self, stmt: FBInvocation) -> None:
        parts: list[str] = []
        for name, expr in stmt.inputs.items():
            parts.append(f"{name} := {self._expr(expr)}")
        for name, expr in stmt.outputs.items():
            parts.append(f"{name} => {self._expr(expr)}")
        args = ", ".join(parts)
        instance_text = stmt.instance_name if isinstance(stmt.instance_name, str) else self._expr(stmt.instance_name)
        self._line(f"{instance_text}({args});")

    def _write_empty(self, stmt: EmptyStatement) -> None:
        if not stmt.comment:
            self._line(";")

    def _write_pragma(self, stmt: PragmaStatement) -> None:
        self._line(stmt.text)

    def _write_try_catch(self, stmt: TryCatchStatement) -> None:
        self._line("__TRY")
        self._indent_inc()
        for s in stmt.try_body:
            self._write_stmt(s)
        self._indent_dec()
        if stmt.catch_body or stmt.catch_var is not None:
            catch_header = "__CATCH"
            if stmt.catch_var is not None:
                catch_header += f"({stmt.catch_var})"
            self._line(catch_header)
            self._indent_inc()
            for s in stmt.catch_body:
                self._write_stmt(s)
            self._indent_dec()
        if stmt.finally_body:
            self._line("__FINALLY")
            self._indent_inc()
            for s in stmt.finally_body:
                self._write_stmt(s)
            self._indent_dec()
        self._line("__ENDTRY")

    def _write_jump(self, stmt: JumpStatement) -> None:
        self._line(f"JMP {stmt.label};")

    def _write_label(self, stmt: LabelStatement) -> None:
        self._line(f"{stmt.name}:")

    # ======================================================================
    # Expressions
    # ======================================================================

    def _expr(self, expr: Expression, parent_prec: int = 0) -> str:
        kind = expr.kind
        handler = _EXPR_WRITERS.get(kind)
        if handler is not None:
            return handler(self, expr, parent_prec)
        return f"/* unsupported: {kind} */"

    def _expr_literal(self, expr: LiteralExpr, _prec: int) -> str:
        return expr.value

    def _expr_variable_ref(self, expr: VariableRef, _prec: int) -> str:
        return expr.name

    def _expr_binary(self, expr: BinaryExpr, parent_prec: int) -> str:
        # Shift/rotate → function call syntax
        if expr.op in _SHIFT_OPS:
            return f"{expr.op.value}({self._expr(expr.left)}, {self._expr(expr.right)})"

        my_prec = _BINOP_PRECEDENCE.get(expr.op, 0)
        symbol = _BINOP_SYMBOL.get(expr.op, expr.op.value)
        left = self._expr(expr.left, my_prec)
        right = self._expr(expr.right, my_prec + 1)
        result = f"{left} {symbol} {right}"
        if my_prec < parent_prec:
            return f"({result})"
        return result

    def _expr_unary(self, expr: UnaryExpr, _prec: int) -> str:
        operand = self._expr(expr.operand, 10)  # high precedence for unary
        if expr.op == UnaryOp.NEG:
            return f"-{operand}"
        if expr.op == UnaryOp.NOT:
            return f"NOT {operand}"
        if expr.op == UnaryOp.BNOT:
            return f"NOT {operand}"
        return f"{expr.op.value}({operand})"

    def _expr_function_call(self, expr: FunctionCallExpr, _prec: int) -> str:
        args = ", ".join(self._call_arg(a) for a in expr.args)
        return f"{expr.function_name}({args})"

    def _expr_array_access(self, expr: ArrayAccessExpr, _prec: int) -> str:
        indices = ", ".join(self._expr(i) for i in expr.indices)
        return f"{self._expr(expr.array, 10)}[{indices}]"

    def _expr_member_access(self, expr: MemberAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.struct, 10)}.{expr.member}"

    def _expr_bit_access(self, expr: BitAccessExpr, _prec: int) -> str:
        return f"{self._expr(expr.target, 10)}.{expr.bit_index}"

    def _expr_type_conversion(self, expr: TypeConversionExpr, _prec: int) -> str:
        target = self._type_ref(expr.target_type)
        if expr.source_type is not None:
            source = self._type_ref(expr.source_type)
            return f"{source}_TO_{target}({self._expr(expr.source)})"
        return f"{target}({self._expr(expr.source)})"

    def _expr_substring(self, expr: SubstringExpr, _prec: int) -> str:
        s = self._expr(expr.string)
        parts = [s]
        if expr.start is not None:
            parts.append(self._expr(expr.start))
        if expr.end is not None:
            parts.append(self._expr(expr.end))
        return f"MID({', '.join(parts)})"

    def _expr_system_flag(self, expr: SystemFlagExpr, _prec: int) -> str:
        if expr.flag == SystemFlag.FIRST_SCAN:
            return "FirstScan"
        return f"/* unknown flag: {expr.flag} */"

    def _call_arg(self, arg) -> str:
        if arg.name is not None:
            return f"{arg.name} := {self._expr(arg.value)}"
        return self._expr(arg.value)

    # ======================================================================
    # SFC body
    # ======================================================================

    def _write_sfc_body(self, sfc: SFCBody) -> None:
        for step_obj in sfc.steps:
            self._write_sfc_step(step_obj)
            self._line()

        for trans in sfc.transitions:
            src = ", ".join(trans.source_steps)
            tgt = ", ".join(trans.target_steps)
            self._line(f"TRANSITION FROM {src} TO {tgt}")
            self._indent_inc()
            self._line(f":= {self._expr(trans.condition)};")
            self._indent_dec()
            self._line("END_TRANSITION")
            self._line()

    def _write_sfc_step(self, step_obj: Step) -> None:
        keyword = "INITIAL_STEP" if step_obj.is_initial else "STEP"
        self._line(f"{keyword} {step_obj.name}:")

        self._indent_inc()
        # Entry actions
        for action in step_obj.entry_actions:
            self._write_sfc_action_association(action, "entry")
        # Main actions
        for action in step_obj.actions:
            self._write_sfc_action_association(action)
        # Exit actions
        for action in step_obj.exit_actions:
            self._write_sfc_action_association(action, "exit")
        self._indent_dec()

        self._line("END_STEP")

    def _write_sfc_action_association(self, action: Action, phase: str | None = None) -> None:
        qualifier = action.qualifier.value
        if action.duration:
            qualifier += f", {action.duration}"
        name = action.action_name or action.name
        if phase:
            self._line(f"{name}({qualifier}); // {phase}")
        else:
            self._line(f"{name}({qualifier});")

    # ======================================================================
    # POU actions
    # ======================================================================

    def _write_pou_action(self, pou_name: str, action: POUAction) -> None:
        self._line(f"ACTION {pou_name}.{action.name}:")
        self._indent_inc()
        self._write_networks(action.body)
        self._indent_dec()
        self._line("END_ACTION")

    # ======================================================================
    # Methods and properties
    # ======================================================================

    def _write_method(self, method: Method, interface_only: bool = False) -> None:
        header = f"METHOD"
        if method.access != AccessSpecifier.PUBLIC:
            header += f" {method.access.value}"
        if method.abstract:
            header += " ABSTRACT"
        if method.final:
            header += " FINAL"
        header += f" {method.name}"
        if method.return_type is not None:
            header += f" : {self._type_ref(method.return_type)}"
        self._line(header)

        if interface_only:
            self._write_var_blocks(method.interface)
            self._line("END_METHOD")
            return

        self._write_var_blocks(method.interface)

        if method.sfc_body is not None:
            self._write_sfc_body(method.sfc_body)
        else:
            self._write_networks(method.networks)

        self._line("END_METHOD")

    def _write_property(self, prop: Property, interface_only: bool = False) -> None:
        header = f"PROPERTY"
        if prop.access != AccessSpecifier.PUBLIC:
            header += f" {prop.access.value}"
        if prop.abstract:
            header += " ABSTRACT"
        if prop.final:
            header += " FINAL"
        header += f" {prop.name} : {self._type_ref(prop.data_type)}"
        self._line(header)

        if interface_only:
            self._line("END_PROPERTY")
            return

        if prop.getter is not None:
            self._line("GET")
            self._indent_inc()
            self._write_networks(prop.getter.networks)
            self._indent_dec()
            self._line("END_GET")

        if prop.setter is not None:
            self._line("SET")
            self._indent_inc()
            self._write_networks(prop.setter.networks)
            self._indent_dec()
            self._line("END_SET")

        self._line("END_PROPERTY")


# ---------------------------------------------------------------------------
# Source-map helpers
# ---------------------------------------------------------------------------

def _collect_variable_names(target: Union[Project, POU]) -> set[str]:
    """Collect all variable names from POU interfaces."""
    names: set[str] = set()
    pous = target.pous if isinstance(target, Project) else [target]
    for pou in pous:
        iface = pou.interface
        for var_list in (
            iface.input_vars, iface.output_vars, iface.inout_vars,
            iface.static_vars, iface.temp_vars, iface.constant_vars,
            iface.external_vars,
        ):
            for v in var_list:
                names.add(v.name)
    return names


_VAR_BLOCK_KEYWORDS = frozenset({
    "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR", "VAR_TEMP",
    "VAR CONSTANT", "VAR_GLOBAL", "VAR_EXTERNAL",
})


def _build_source_map(st_text: str, variable_names: set[str]) -> list[dict]:
    """Scan ST text for variable references, return [{name, line, column}].

    Lines and columns are 1-indexed (matching Monaco editor conventions).
    Skips VAR declaration blocks, comment text, and de-duplicates per variable
    per line (first occurrence only).
    """
    if not variable_names:
        return []

    # Sort longest-first so the alternation doesn't short-circuit on prefixes
    sorted_names = sorted(variable_names, key=len, reverse=True)
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(n) for n in sorted_names) + r')\b'
    )

    entries: list[dict] = []
    in_var_block = False

    for line_num, line_text in enumerate(st_text.splitlines(), start=1):
        stripped = line_text.strip()

        # Track VAR declaration blocks — skip them entirely
        if stripped in _VAR_BLOCK_KEYWORDS:
            in_var_block = True
            continue
        if stripped == "END_VAR":
            in_var_block = False
            continue
        if in_var_block:
            continue

        # Strip comment portion before matching
        comment_pos = line_text.find("//")
        searchable = line_text[:comment_pos] if comment_pos >= 0 else line_text

        # First occurrence of each variable name per line only
        seen_on_line: set[str] = set()
        for match in pattern.finditer(searchable):
            name = match.group(1)
            if name in seen_on_line:
                continue
            seen_on_line.add(name)
            entries.append({
                "name": name,
                "line": line_num,
                "column": match.start() + 1,
            })
    return entries


# ---------------------------------------------------------------------------
# Dispatch tables (outside class to avoid method resolution overhead)
# ---------------------------------------------------------------------------

_STMT_WRITERS = {
    "assignment": STWriter._write_assignment,
    "if": STWriter._write_if,
    "case": STWriter._write_case,
    "for": STWriter._write_for,
    "while": STWriter._write_while,
    "repeat": STWriter._write_repeat,
    "exit": STWriter._write_exit,
    "continue": STWriter._write_continue,
    "return": STWriter._write_return,
    "function_call_stmt": STWriter._write_function_call_stmt,
    "fb_invocation": STWriter._write_fb_invocation,
    "empty": STWriter._write_empty,
    "pragma": STWriter._write_pragma,
    "try_catch": STWriter._write_try_catch,
    "jump": STWriter._write_jump,
    "label": STWriter._write_label,
}

_EXPR_WRITERS = {
    "literal": STWriter._expr_literal,
    "variable_ref": STWriter._expr_variable_ref,
    "binary": STWriter._expr_binary,
    "unary": STWriter._expr_unary,
    "function_call": STWriter._expr_function_call,
    "array_access": STWriter._expr_array_access,
    "member_access": STWriter._expr_member_access,
    "bit_access": STWriter._expr_bit_access,
    "type_conversion": STWriter._expr_type_conversion,
    "substring": STWriter._expr_substring,
    "system_flag": STWriter._expr_system_flag,
}

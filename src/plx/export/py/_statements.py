"""Statement writer mixin for the Python exporter."""

from __future__ import annotations

from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    LiteralExpr,
    VariableRef,
)
from plx.model.statements import (
    Assignment,
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
    RepeatStatement,
    ReturnStatement,
    Statement,
    TryCatchStatement,
    WhileStatement,
)

from ._helpers import _FUNC_REMAP, _case_branch_condition, _fix_embedded_iec, _safe_name


class _StatementWriterMixin:
    """Mixin providing statement-writing methods for PyWriter."""

    def _write_stmt(self, stmt: Statement) -> None:
        if stmt.comment:
            for cline in stmt.comment.split("\n"):
                self._line(f"# {cline}" if cline else "#")
        handler = _STMT_WRITERS.get(stmt.kind)
        if handler is not None:
            handler(self, stmt)
        else:
            self._line(f"# Unsupported statement: {stmt.kind}")

    # BinaryOp -> Python augmented-assignment operator for ``x = x + y`` -> ``x += y``
    _AUGOP: dict[BinaryOp, str] = {
        BinaryOp.ADD: "+=",
        BinaryOp.SUB: "-=",
        BinaryOp.MUL: "*=",
        BinaryOp.DIV: "/=",
        BinaryOp.MOD: "%=",
        BinaryOp.XOR: "^=",
        BinaryOp.BAND: "&=",
        BinaryOp.BOR: "|=",
        BinaryOp.SHL: "<<=",
        BinaryOp.SHR: ">>=",
        BinaryOp.EXPT: "**=",
    }

    def _write_assignment(self, stmt: Assignment) -> None:
        # Property/function return: ``PropName = expr`` -> ``return expr``
        if (
            self._return_var is not None
            and isinstance(stmt.target, VariableRef)
            and stmt.target.name == self._return_var
        ):
            self._line(f"return {self._expr(stmt.value)}")
            return
        # S=/R= latch assignments have no Python framework equivalent
        if stmt.latch:
            self._line(f"# {self._expr(stmt.target)} {stmt.latch}= {self._expr(stmt.value)}")
            self._line("pass  # latch assignment (S=/R=) not yet supported in framework")
            return
        # REF= reference assignment: ``ref @= expr``
        if stmt.ref_assign:
            self._line(f"{self._expr(stmt.target)} @= {self._expr(stmt.value)}")
            return
        # Recover augmented assignment: ``x = x + y`` -> ``x += y``
        if isinstance(stmt.value, BinaryExpr):
            aug = self._AUGOP.get(stmt.value.op)
            if aug is not None and stmt.value.left == stmt.target:
                self._line(f"{self._expr(stmt.target)} {aug} {self._expr(stmt.value.right)}")
                return
        self._line(f"{self._expr(stmt.target)} = {self._expr(stmt.value)}")

    def _write_if(self, stmt: IfStatement) -> None:
        self._line(f"if {self._expr(stmt.if_branch.condition)}:")
        self._indent_inc()
        self._write_body(stmt.if_branch.body)
        self._indent_dec()

        for branch in stmt.elsif_branches:
            self._line(f"elif {self._expr(branch.condition)}:")
            self._indent_inc()
            self._write_body(branch.body)
            self._indent_dec()

        if stmt.else_body:
            self._line("else:")
            self._indent_inc()
            self._write_body(stmt.else_body)
            self._indent_dec()

    def _write_case(self, stmt: CaseStatement) -> None:
        # Check if any branch has ranges -- if so, use if/elif
        has_ranges = any(b.ranges for b in stmt.branches)

        if has_ranges:
            self._write_case_as_if(stmt)
        else:
            self._write_case_as_match(stmt)

    def _write_case_as_match(self, stmt: CaseStatement) -> None:
        # Check if any branch has bare identifier labels (no dot) —
        # Python match/case treats these as capture patterns, not comparisons.
        # Fall back to if/elif when this happens.
        has_bare_names = False
        for branch in stmt.branches:
            for v in branch.values:
                if isinstance(v, str) and "." not in v:
                    try:
                        int(v)
                    except ValueError:
                        has_bare_names = True
        if has_bare_names:
            self._write_case_as_if(stmt)
            return

        self._line(f"match {self._expr(stmt.selector)}:")
        self._indent_inc()
        for branch in stmt.branches:
            labels: list[str] = []
            for v in branch.values:
                if isinstance(v, str):
                    # Enum reference: E_State.Idle — sanitize member part
                    if "." in v:
                        parts = v.rsplit(".", 1)
                        labels.append(f"{parts[0]}.{_safe_name(parts[1])}")
                    else:
                        labels.append(v)
                else:
                    labels.append(str(v))
            pattern = " | ".join(labels) if labels else "_"
            self._line(f"case {pattern}:")
            self._indent_inc()
            self._write_body(branch.body)
            self._indent_dec()

        if stmt.else_body:
            self._line("case _:")
            self._indent_inc()
            self._write_body(stmt.else_body)
            self._indent_dec()

        self._indent_dec()

    def _write_case_as_if(self, stmt: CaseStatement) -> None:
        sel = self._expr(stmt.selector)
        first = True
        for branch in stmt.branches:
            cond = _case_branch_condition(sel, branch)
            keyword = "if" if first else "elif"
            self._line(f"{keyword} {cond}:")
            self._indent_inc()
            self._write_body(branch.body)
            self._indent_dec()
            first = False

        if stmt.else_body:
            self._line("else:")
            self._indent_inc()
            self._write_body(stmt.else_body)
            self._indent_dec()

    def _write_for(self, stmt: ForStatement) -> None:
        from_str = self._expr(stmt.from_expr)

        # IEC FOR is inclusive; Python range() is exclusive. Pre-compute
        # the +1 when the upper bound is an integer literal so we emit
        # clean ``range(1, 6)`` instead of ``range(1, 5 + 1)``.
        if isinstance(stmt.to_expr, LiteralExpr) and stmt.to_expr.data_type is None:
            try:
                to_val = int(stmt.to_expr.value)
                to_str = str(to_val + 1)
            except ValueError:
                to_str = f"{self._expr(stmt.to_expr)} + 1"
        else:
            to_str = f"{self._expr(stmt.to_expr)} + 1"

        loop_var = _safe_name(stmt.loop_var)
        if stmt.by_expr is not None:
            by_str = self._expr(stmt.by_expr)
            self._line(f"for {loop_var} in range({from_str}, {to_str}, {by_str}):")
        else:
            self._line(f"for {loop_var} in range({from_str}, {to_str}):")

        self._indent_inc()
        self._write_body(stmt.body)
        self._indent_dec()

    def _write_while(self, stmt: WhileStatement) -> None:
        self._line(f"while {self._expr(stmt.condition)}:")
        self._indent_inc()
        self._write_body(stmt.body)
        self._indent_dec()

    def _write_repeat(self, stmt: RepeatStatement) -> None:
        self._line("while True:")
        self._indent_inc()
        for s in stmt.body:
            self._write_stmt(s)
        self._line(f"if {self._expr(stmt.until)}:")
        self._indent_inc()
        self._line("break")
        self._indent_dec()
        self._indent_dec()

    def _write_exit(self, _stmt: ExitStatement) -> None:
        self._line("break")

    def _write_continue(self, _stmt: ContinueStatement) -> None:
        self._line("continue")

    def _write_return(self, stmt: ReturnStatement) -> None:
        if stmt.value is not None:
            self._line(f"return {self._expr(stmt.value)}")
        else:
            self._line("return")

    def _write_function_call_stmt(self, stmt: FunctionCallStatement) -> None:
        name = stmt.function_name
        upper = name.upper()
        # Beckhoff OOP: SUPER^() -> super().logic(), SUPER^.Method() -> super().Method()
        if upper == "SUPER^":
            name = "super().logic"
        elif upper.startswith("SUPER^."):
            name = f"super().{name[7:]}"
        elif upper.startswith("THIS^."):
            name = f"self.{name[6:]}"
        else:
            name = _FUNC_REMAP.get(name, name)
            name = self._qualify_function_name(name)
        # Convert remaining ptr^.member to ptr.deref.member (always, not just else)
        if "^." in name:
            name = name.replace("^.", ".deref.")
        if "^" in name:
            name = name.replace("^", ".deref")
        # Convert IEC operators in embedded chained calls
        name = _fix_embedded_iec(name)
        args = self._call_args_str(stmt.args)
        self._line(f"{name}({args})")

    def _qualify_function_name(self, name: str) -> str:
        """Add self. prefix to function/method names that need it."""
        # Dotted name: Instance.Method() -- qualify the first part
        if "." in name:
            first, _rest = name.split(".", 1)
            if first in self._self_vars:
                return f"self.{name}"
            if self._has_unresolved_parent and first not in self._non_self_names:
                return f"self.{name}"
            return name
        # Simple name: own/inherited method
        if name in self._self_methods:
            return f"self.{name}"
        if self._has_unresolved_parent and name not in self._non_self_names:
            return f"self.{name}"
        return name

    def _write_fb_invocation(self, stmt: FBInvocation) -> None:
        # Emit: self.instance(IN=val, PT=val)
        if isinstance(stmt.instance_name, str):
            inst_name = stmt.instance_name
            # Beckhoff OOP: THIS^.fb.Method -> self.fb.Method (case-insensitive)
            upper = inst_name.upper()
            if upper.startswith("THIS^."):
                instance = f"self.{inst_name[6:]}"
            elif upper.startswith("SUPER^."):
                instance = f"super().{inst_name[7:]}"
            elif inst_name in self._self_vars:
                instance = f"self.{inst_name}"
            else:
                instance = inst_name
                # Convert remaining ptr^.member to ptr.deref.member
                if "^." in instance:
                    instance = instance.replace("^.", ".deref.")
                if "^" in instance:
                    instance = instance.replace("^", ".deref")
        else:
            instance = self._expr(stmt.instance_name)
        parts: list[str] = []
        for name, expr in stmt.inputs.items():
            parts.append(f"{_safe_name(name)}={self._expr(expr)}")
        args = ", ".join(parts)
        self._line(f"{instance}({args})")

        # Output assignments on separate lines
        for name, expr in stmt.outputs.items():
            self._line(f"{self._expr(expr)} = {instance}.{_safe_name(name)}")

    def _write_empty(self, stmt: EmptyStatement) -> None:
        if not stmt.comment:
            self._line("pass")

    def _write_try_catch(self, stmt: TryCatchStatement) -> None:
        # No Python framework equivalent -- emit as ST-style comment block
        self._line("# __TRY")
        self._indent_inc()
        for s in stmt.try_body:
            self._write_stmt(s)
        self._indent_dec()
        if stmt.catch_body or stmt.catch_var is not None:
            catch_header = "# __CATCH"
            if stmt.catch_var is not None:
                catch_header += f"({stmt.catch_var})"
            self._line(catch_header)
            self._indent_inc()
            for s in stmt.catch_body:
                self._write_stmt(s)
            self._indent_dec()
        if stmt.finally_body:
            self._line("# __FINALLY")
            self._indent_inc()
            for s in stmt.finally_body:
                self._write_stmt(s)
            self._indent_dec()
        self._line("# __ENDTRY")

    def _write_jump(self, stmt: JumpStatement) -> None:
        self._line(f"# JMP {stmt.label}")

    def _write_label(self, stmt: LabelStatement) -> None:
        self._line(f"# {stmt.name}:")

    def _write_body(self, body: list[Statement]) -> None:
        """Write a statement list, emitting 'pass' if empty or comment-only."""
        if not body:
            self._line("pass")
        else:
            # Check if body has any statements that produce executable Python.
            # EmptyStatement (with comment), TryCatchStatement, JumpStatement,
            # and LabelStatement only emit comments.
            _COMMENT_ONLY_KINDS = {"empty", "try_catch", "jump", "label"}
            has_executable = any(
                s.kind not in _COMMENT_ONLY_KINDS or (s.kind == "empty" and not s.comment) for s in body
            )
            for s in body:
                self._write_stmt(s)
            if not has_executable:
                self._line("pass")


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_STMT_WRITERS = {
    "assignment": _StatementWriterMixin._write_assignment,
    "if": _StatementWriterMixin._write_if,
    "case": _StatementWriterMixin._write_case,
    "for": _StatementWriterMixin._write_for,
    "while": _StatementWriterMixin._write_while,
    "repeat": _StatementWriterMixin._write_repeat,
    "exit": _StatementWriterMixin._write_exit,
    "continue": _StatementWriterMixin._write_continue,
    "return": _StatementWriterMixin._write_return,
    "function_call_stmt": _StatementWriterMixin._write_function_call_stmt,
    "fb_invocation": _StatementWriterMixin._write_fb_invocation,
    "empty": _StatementWriterMixin._write_empty,
    "try_catch": _StatementWriterMixin._write_try_catch,
    "jump": _StatementWriterMixin._write_jump,
    "label": _StatementWriterMixin._write_label,
}

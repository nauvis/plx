"""Statement writer mixin for the ST exporter."""

from __future__ import annotations

from plx.model.pou import Network
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


class _StatementWriterMixin:
    """Mixin providing statement-writing methods for STWriter."""

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
        if handler is None:
            raise TypeError(f"Unhandled statement kind: {kind!r}")
        handler(self, stmt)

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
    "pragma": _StatementWriterMixin._write_pragma,
    "try_catch": _StatementWriterMixin._write_try_catch,
    "jump": _StatementWriterMixin._write_jump,
    "label": _StatementWriterMixin._write_label,
}

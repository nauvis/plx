"""Statement compilation methods for the AST compiler.

Handles all statement AST nodes: assignments, if/elif/else, for, while,
match/case, return, break, continue, pass, and expression statements
(including super().logic() inlining and FB invocations).
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import TYPE_CHECKING

from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    Expression,
    LiteralExpr,
    VariableRef,
)
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    ContinueStatement,
    ExitStatement,
    ForStatement,
    FunctionCallStatement,
    IfBranch,
    IfStatement,
    ReturnStatement,
    Statement,
    WhileStatement,
)
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    TypeRef,
)
from plx.model.variables import Variable

from ._compiler_core import (
    CompileError,
    _COUNTER_SENTINELS,
    _EDGE_SENTINELS,
    _PYTHON_BUILTIN_MAP,
    _REJECTED_AUGOP_MESSAGES,
    _REJECTED_BINOP_MESSAGES,
    _REJECTED_BUILTINS,
    _BINOP_MAP,
    _SYSTEM_FLAG_SENTINELS,
    _TIMER_SENTINELS,
    resolve_annotation,
)
from ._descriptors import VarDirection

if TYPE_CHECKING:
    from ._compiler import ASTCompiler


# ---------------------------------------------------------------------------
# Statement mixin
# ---------------------------------------------------------------------------

class _StatementMixin:
    """Mixin providing statement compilation methods for ASTCompiler."""

    def _compile_assign(self, node: ast.Assign) -> list[Statement]:
        if len(node.targets) > 1:
            raise CompileError(
                "Multiple assignment targets (a = b = value) are not supported. "
                "Assign each variable on a separate line.",
                node, self.ctx,
            )
        target_node = node.targets[0]
        target = self._compile_target(target_node, node)
        value, pending = self._compile_expr_and_flush(node.value)
        pending.append(Assignment(target=target, value=value))
        return pending

    def _compile_target(self, target_node: ast.expr, stmt_node: ast.stmt) -> Expression:
        """Compile an assignment target (LHS)."""
        if isinstance(target_node, ast.Attribute):
            if isinstance(target_node.value, ast.Name) and target_node.value.id == "self":
                return VariableRef(name=target_node.attr)
            return self.compile_expression(target_node)
        if isinstance(target_node, ast.Name):
            name = target_node.id
            if name not in self.ctx.declared_vars:
                raise CompileError(
                    f"Undeclared variable '{name}'. Use a type annotation "
                    f"(e.g. '{name}: INT = 0') to declare temp variables.",
                    stmt_node, self.ctx,
                )
            return VariableRef(name=name)
        if isinstance(target_node, ast.Subscript):
            return self.compile_expression(target_node)
        if isinstance(target_node, ast.Tuple):
            raise CompileError(
                "Tuple unpacking (a, b = ...) is not supported in PLC logic. "
                "Assign each variable on a separate line.",
                stmt_node, self.ctx,
            )
        raise CompileError(
            f"Unsupported assignment target: {type(target_node).__name__}",
            stmt_node, self.ctx,
        )

    def _compile_augassign(self, node: ast.AugAssign) -> list[Statement]:
        rejected_msg = _REJECTED_AUGOP_MESSAGES.get(type(node.op))
        if rejected_msg is not None:
            raise CompileError(rejected_msg, node, self.ctx)
        target = self._compile_target(node.target, node)
        op = _BINOP_MAP.get(type(node.op))
        if op is None:
            raise CompileError(
                f"Unsupported augmented assignment operator: {type(node.op).__name__}",
                node, self.ctx,
            )
        rhs, pending = self._compile_expr_and_flush(node.value)
        pending.append(Assignment(
            target=target,
            value=BinaryExpr(op=op, left=target, right=rhs),
        ))
        return pending

    def _compile_annassign(self, node: ast.AnnAssign) -> list[Statement]:
        """Handle type-annotated assignment: ``x: REAL = 0.0``."""
        if not isinstance(node.target, ast.Name):
            raise CompileError(
                "Type annotations are only supported on simple names",
                node, self.ctx,
            )
        name = node.target.id
        type_ref = self._resolve_annotation(node.annotation, node)

        # Register as temp var
        self.ctx.declared_vars[name] = VarDirection.TEMP
        var = Variable(name=name, data_type=type_ref)
        self.ctx.generated_temp_vars.append(var)

        if node.value is not None:
            value, pending = self._compile_expr_and_flush(node.value)
            pending.append(Assignment(
                target=VariableRef(name=name),
                value=value,
            ))
            return pending
        return []

    def _resolve_annotation(self, ann: ast.expr, node: ast.stmt) -> TypeRef:
        """Resolve a type annotation AST node to a TypeRef."""
        result = resolve_annotation(ann, node=node, ctx=self.ctx)
        if result is None:
            raise CompileError("None is not a valid type annotation", node, self.ctx)
        return result

    def _compile_if(self, node: ast.If) -> list[Statement]:
        cond, pending = self._compile_expr_and_flush(node.test)

        if_body = self._compile_body_list(node.body)

        # Extract elif chain
        elsif_branches: list[IfBranch] = []
        else_body: list[Statement] = []
        orelse = node.orelse

        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                elif_node = orelse[0]
                elif_cond, elif_pending = self._compile_expr_and_flush(elif_node.test)
                # Prepend any pending FB invocations to the elsif body
                elif_body = elif_pending + self._compile_body_list(elif_node.body)
                elsif_branches.append(IfBranch(condition=elif_cond, body=elif_body))
                orelse = elif_node.orelse
            else:
                else_body = self._compile_body_list(orelse)
                break

        pending.append(IfStatement(
            if_branch=IfBranch(condition=cond, body=if_body),
            elsif_branches=elsif_branches,
            else_body=else_body,
        ))
        return pending

    def _compile_for(self, node: ast.For) -> list[Statement]:
        if not isinstance(node.target, ast.Name):
            raise CompileError(
                "For loop variable must be a simple name",
                node, self.ctx,
            )
        loop_var = node.target.id

        # Only range() is supported
        if not (isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"):
            raise CompileError(
                "For loops only support range() iteration",
                node, self.ctx,
            )

        args = node.iter.args
        if len(args) == 1:
            from_expr = LiteralExpr(value="0")
            to_expr = BinaryExpr(
                op=BinaryOp.SUB,
                left=self.compile_expression(args[0]),
                right=LiteralExpr(value="1"),
            )
            by_expr = None
        elif len(args) == 2:
            from_expr = self.compile_expression(args[0])
            to_expr = BinaryExpr(
                op=BinaryOp.SUB,
                left=self.compile_expression(args[1]),
                right=LiteralExpr(value="1"),
            )
            by_expr = None
        elif len(args) == 3:
            from_expr = self.compile_expression(args[0])
            to_expr = BinaryExpr(
                op=BinaryOp.SUB,
                left=self.compile_expression(args[1]),
                right=LiteralExpr(value="1"),
            )
            by_expr = self.compile_expression(args[2])
        else:
            raise CompileError("range() takes 1-3 arguments", node, self.ctx)

        # Register loop var as temp
        if loop_var not in self.ctx.declared_vars:
            self.ctx.declared_vars[loop_var] = VarDirection.TEMP
            self.ctx.generated_temp_vars.append(
                Variable(name=loop_var, data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))
            )

        body = self._compile_body_list(node.body)

        return [ForStatement(
            loop_var=loop_var,
            from_expr=from_expr,
            to_expr=to_expr,
            by_expr=by_expr,
            body=body,
        )]

    def _compile_while(self, node: ast.While) -> list[Statement]:
        cond, pending = self._compile_expr_and_flush(node.test)
        body = self._compile_body_list(node.body)
        pending.append(WhileStatement(condition=cond, body=body))
        return pending

    def _compile_match(self, node: ast.Match) -> list[Statement]:
        selector, pending = self._compile_expr_and_flush(node.subject)

        branches: list[CaseBranch] = []
        else_body: list[Statement] = []

        for case in node.cases:
            pattern = case.pattern

            if isinstance(pattern, ast.MatchAs) and pattern.name is None:
                # Wildcard _ → else
                else_body = self._compile_body_list(case.body)
                continue

            values = self._extract_case_values(pattern, node)
            body = self._compile_body_list(case.body)
            branches.append(CaseBranch(values=values, body=body))

        pending.append(CaseStatement(
            selector=selector,
            branches=branches,
            else_body=else_body,
        ))
        return pending

    def _extract_case_values(self, pattern: ast.pattern, node: ast.stmt) -> list[int]:
        """Extract integer values from a match case pattern."""
        if isinstance(pattern, ast.MatchValue):
            return [self._pattern_to_int(pattern.value, node)]
        if isinstance(pattern, ast.MatchOr):
            values: list[int] = []
            for p in pattern.patterns:
                values.extend(self._extract_case_values(p, node))
            return values
        raise CompileError(
            f"Unsupported match pattern: {type(pattern).__name__}. "
            f"Only integer/enum values and | alternatives are supported.",
            node, self.ctx,
        )

    def _pattern_to_int(self, value_node: ast.expr, node: ast.stmt) -> int:
        """Convert a pattern value node to an integer."""
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, int):
            return value_node.value
        # Negative constants: UnaryOp(USub, Constant)
        if (isinstance(value_node, ast.UnaryOp)
                and isinstance(value_node.op, ast.USub)
                and isinstance(value_node.operand, ast.Constant)
                and isinstance(value_node.operand.value, int)):
            return -value_node.operand.value
        # Enum-style: SomeEnum.MEMBER → resolve to integer value
        if isinstance(value_node, ast.Attribute) and isinstance(value_node.value, ast.Name):
            enum_name = value_node.value.id
            if enum_name in self.ctx.known_enums:
                member_name = value_node.attr
                members = self.ctx.known_enums[enum_name]
                if member_name not in members:
                    raise CompileError(
                        f"'{member_name}' is not a member of enum '{enum_name}'",
                        node, self.ctx,
                    )
                return members[member_name]
            raise CompileError(
                f"Unknown enum type '{enum_name}'",
                node, self.ctx,
            )
        raise CompileError(
            f"Case pattern must be an integer literal or enum member, "
            f"got {type(value_node).__name__}",
            node, self.ctx,
        )

    def _compile_return(self, node: ast.Return) -> list[Statement]:
        if node.value is not None:
            value, pending = self._compile_expr_and_flush(node.value)
        else:
            value, pending = None, []
        pending.append(ReturnStatement(value=value))
        return pending

    def _compile_break(self, node: ast.Break) -> list[Statement]:
        return [ExitStatement()]

    def _compile_continue(self, node: ast.Continue) -> list[Statement]:
        return [ContinueStatement()]

    def _compile_pass(self, node: ast.Pass) -> list[Statement]:
        return []

    def _compile_expr_stmt(self, node: ast.Expr) -> list[Statement]:
        """Compile an expression used as a statement (e.g. function call)."""
        expr_node = node.value

        # super().logic() — inline parent's compiled logic
        if self._is_super_logic_call(expr_node):
            return self._compile_super_logic(node)

        # Function/FB call as statement
        if isinstance(expr_node, ast.Call):
            result = self._compile_call_as_statement(expr_node)
            if result is not None:
                pending = self._flush_pending()
                pending.append(result)
                return pending

        # If the expression generated pending FB invocations, flush them
        _, pending = self._compile_expr_and_flush(expr_node)
        return pending

    def _compile_call_as_statement(self, call_node: ast.Call) -> Statement | None:
        """Try to compile a call expression as a statement."""
        func = call_node.func

        # self.fb_instance(...) → FBInvocation
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
            inv = self._build_fb_invocation(func.attr, call_node)
            if inv is not None:
                return inv

        # Bare function call as statement
        if isinstance(func, ast.Name):
            name = func.id
            # Check if it's a sentinel (should be used as expression, not statement)
            if name in _TIMER_SENTINELS or name in _EDGE_SENTINELS or name in _COUNTER_SENTINELS or name in _SYSTEM_FLAG_SENTINELS:
                raise CompileError(
                    f"{name}() must be used in an expression (e.g. in an assignment or if condition), "
                    f"not as a standalone statement",
                    call_node, self.ctx,
                )
            # Rejected Python builtins
            if name in _REJECTED_BUILTINS:
                raise CompileError(_REJECTED_BUILTINS[name], call_node, self.ctx)
            mapped = _PYTHON_BUILTIN_MAP.get(name, name)
            args = self._compile_call_args(call_node)
            return FunctionCallStatement(function_name=mapped, args=args)

        if isinstance(func, ast.Attribute):
            # member function call as statement — compile as MemberAccess call
            name = func.attr
            args = self._compile_call_args(call_node)
            return FunctionCallStatement(function_name=name, args=args)

        return None

    @staticmethod
    def _is_super_logic_call(node: ast.expr) -> bool:
        """Check if node is ``super().logic()``."""
        return (
            isinstance(node, ast.Call)
            and not node.args
            and not node.keywords
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "logic"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
            and not node.func.value.args
            and not node.func.value.keywords
        )

    def _compile_super_logic(self, node: ast.stmt) -> list[Statement]:
        """Inline the parent class's logic() body.

        Re-compiles the parent's source in the *same* CompileContext so
        that auto-generated instance names (``__ton_0``, etc.) continue
        from where the child left off — no renaming needed.
        """
        import inspect as _inspect
        import textwrap as _textwrap

        if self.ctx.pou_class is None:
            raise CompileError(
                "super().logic() used but no class context available",
                node, self.ctx,
            )

        # Walk MRO to find the first parent with its own logic()
        parent_class = None
        for base in self.ctx.pou_class.__mro__[1:]:
            if base is object:
                continue
            if "logic" in base.__dict__:
                parent_class = base
                break

        if parent_class is None:
            raise CompileError(
                f"super().logic(): no parent class with a logic() method "
                f"found in MRO of {self.ctx.pou_class.__name__}",
                node, self.ctx,
            )

        # Get parent's logic source
        logic_method = parent_class.__dict__["logic"]
        source_lines, start_lineno = _inspect.getsourcelines(logic_method)
        source = _textwrap.dedent("".join(source_lines))
        tree = ast.parse(source)

        if not tree.body or not isinstance(tree.body[0], ast.FunctionDef):
            raise CompileError(
                f"Could not parse {parent_class.__name__}.logic()",
                node, self.ctx,
            )

        # Temporarily set pou_class to the parent so nested
        # super().logic() calls resolve to the grandparent
        saved_class = self.ctx.pou_class
        saved_offset = self.ctx.source_line_offset
        self.ctx.pou_class = parent_class
        self.ctx.source_line_offset = start_lineno - 1

        try:
            stmts = self.compile_body(tree.body[0])
        finally:
            self.ctx.pou_class = saved_class
            self.ctx.source_line_offset = saved_offset

        return stmts

    def _compile_body_list(self, stmts: list[ast.stmt]) -> list[Statement]:
        """Compile a list of AST statements."""
        result: list[Statement] = []
        for s in stmts:
            result.extend(self._compile_statement(s))
        return result

    # Statement handler dispatch table
    _STATEMENT_HANDLERS: dict[type[ast.stmt], Callable[[ASTCompiler, ast.stmt], list[Statement]]] = {
        ast.Assign: _compile_assign,
        ast.AugAssign: _compile_augassign,
        ast.AnnAssign: _compile_annassign,
        ast.If: _compile_if,
        ast.For: _compile_for,
        ast.While: _compile_while,
        ast.Match: _compile_match,
        ast.Return: _compile_return,
        ast.Break: _compile_break,
        ast.Continue: _compile_continue,
        ast.Pass: _compile_pass,
        ast.Expr: _compile_expr_stmt,
    }

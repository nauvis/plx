"""Base IR visitor for static analysis.

Walks compiled IR using a dispatch-table pattern (matching the simulator
and ST exporter) and calls hook methods that rule subclasses override.
"""

from __future__ import annotations

from typing import Callable

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    BitAccessExpr,
    SubstringExpr,
    TypeConversionExpr,
    UnaryExpr,
    VariableRef,
    SystemFlagExpr,
)
from plx.model.pou import POU, Method, Network, Property
from plx.model.project import Project
from plx.model.sfc import SFCBody, Step, Transition
from plx.model.statements import (
    Assignment,
    CaseStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    TryCatchStatement,
    WhileStatement,
)

from ._context import AnalysisContext, ReadInfo, WriteInfo
from ._results import AnalysisResult, Finding


class AnalysisVisitor:
    """Base class for analysis rules.

    Subclasses override ``on_*`` hook methods (all default to no-op).
    The base class manages context push/pop and records all writes
    automatically — rules inspect ``ctx.writes`` in ``on_pou_exit``.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_project(self, project: Project) -> AnalysisResult:
        """Run this rule against every POU in a project.

        Parameters
        ----------
        project : Project
            Compiled project IR to analyze.

        Returns
        -------
        AnalysisResult
            Aggregated findings from all POUs.
        """
        all_findings: list[Finding] = []
        for pou in project.pous:
            all_findings.extend(self.analyze_pou(pou))
        return AnalysisResult(
            findings=all_findings,
            pou_count=len(project.pous),
            rule_count=1,
        )

    def analyze_pou(self, pou: POU) -> list[Finding]:
        """Run this rule against a single POU, returning any findings.

        Visits the POU's main body, actions, methods, and properties.

        Parameters
        ----------
        pou : POU
            The POU to analyze.

        Returns
        -------
        list[Finding]
            All findings produced by this rule for the POU.
        """
        ctx = self._make_context(pou)
        self.on_pou_enter(ctx)

        # Main body
        self._visit_body(ctx, pou.networks, pou.sfc_body)

        # Actions — share the parent POU's context (execute in parent scope)
        for action in pou.actions:
            ctx.current_stmt_path.append(f"action:{action.name}")
            for i, network in enumerate(action.body):
                ctx.current_network_idx = i
                self._visit_network(ctx, network)
            ctx.current_stmt_path.pop()

        self.on_pou_exit(ctx)

        # Methods — each gets its own context (independent scope)
        for method in pou.methods:
            method_ctx = self._make_method_context(pou, method)
            self.on_pou_enter(method_ctx)
            self._visit_body(method_ctx, method.networks, method.sfc_body)
            self.on_pou_exit(method_ctx)
            ctx.findings.extend(method_ctx.findings)

        # Properties — getter/setter each get own context
        for prop in pou.properties:
            for accessor_name, accessor in [
                ("getter", prop.getter),
                ("setter", prop.setter),
            ]:
                if accessor is None:
                    continue
                prop_ctx = self._make_property_context(pou, prop, accessor_name)
                self.on_pou_enter(prop_ctx)
                self._visit_body(prop_ctx, accessor.networks, sfc_body=None)
                self.on_pou_exit(prop_ctx)
                ctx.findings.extend(prop_ctx.findings)

        return ctx.findings

    # ------------------------------------------------------------------
    # Hook methods (subclasses override these)
    # ------------------------------------------------------------------

    def on_pou_enter(self, ctx: AnalysisContext) -> None:
        """Called once before traversal of a POU, method, or property accessor.

        Parameters
        ----------
        ctx : AnalysisContext
            Fresh context for the POU being entered. Inspect ``ctx.pou_name``,
            ``ctx.output_names``, etc.
        """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        """Called after all statements in a POU have been visited.

        Parameters
        ----------
        ctx : AnalysisContext
            Fully populated context with ``ctx.writes``, ``ctx.reads``, and
            any ``ctx.findings`` accumulated during traversal.
        """

    def on_assignment(self, ctx: AnalysisContext, stmt: Assignment) -> None:
        """Called for each assignment statement after the write is recorded.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : Assignment
            The assignment node (``stmt.target`` and ``stmt.value``).
        """

    def on_if_enter(self, ctx: AnalysisContext, stmt: IfStatement) -> None:
        """Called before descending into if/elsif/else branches.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context (nesting depth not yet incremented).
        stmt : IfStatement
            The if statement node.
        """

    def on_if_exit(self, ctx: AnalysisContext, stmt: IfStatement) -> None:
        """Called after all if/elsif/else branches have been visited.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context (nesting depth restored).
        stmt : IfStatement
            The if statement node.
        """

    def on_case(self, ctx: AnalysisContext, stmt: CaseStatement) -> None:
        """Called before descending into case branches.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : CaseStatement
            The case statement node.
        """

    def on_for(self, ctx: AnalysisContext, stmt: ForStatement) -> None:
        """Called before descending into the for loop body.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : ForStatement
            The for statement node.
        """

    def on_for_exit(self, ctx: AnalysisContext, stmt: ForStatement) -> None:
        """Called after the for loop body has been visited.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context (nesting depth restored).
        stmt : ForStatement
            The for statement node.
        """

    def on_while(self, ctx: AnalysisContext, stmt: WhileStatement) -> None:
        """Called before descending into the while loop body.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : WhileStatement
            The while statement node.
        """

    def on_repeat(self, ctx: AnalysisContext, stmt: RepeatStatement) -> None:
        """Called before descending into the repeat loop body.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : RepeatStatement
            The repeat statement node.
        """

    def on_return(self, ctx: AnalysisContext, stmt: ReturnStatement) -> None:
        """Called when a return statement is encountered.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : ReturnStatement
            The return statement node (``stmt.value`` may be ``None``).
        """

    def on_fb_invocation(self, ctx: AnalysisContext, stmt: FBInvocation) -> None:
        """Called for each function block invocation after output writes are recorded.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : FBInvocation
            The FB invocation node (``stmt.instance_name``, ``stmt.fb_type``,
            ``stmt.inputs``, ``stmt.outputs``).
        """

    def on_try_catch(self, ctx: AnalysisContext, stmt: TryCatchStatement) -> None:
        """Called after try/catch/finally bodies have been visited.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        stmt : TryCatchStatement
            The try-catch statement node.
        """

    def on_expression(self, ctx: AnalysisContext, expr: Expression) -> None:
        """Called for every expression node encountered during read collection.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        expr : Expression
            The expression node being visited.
        """

    def on_sfc_enter(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        """Called before traversing SFC steps and transitions.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        sfc : SFCBody
            The SFC body containing steps and transitions.
        """

    def on_sfc_exit(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        """Called after all SFC steps and transitions have been visited.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        sfc : SFCBody
            The SFC body that was traversed.
        """

    def on_sfc_step(self, ctx: AnalysisContext, step: Step) -> None:
        """Called for each SFC step before visiting its action bodies.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        step : Step
            The SFC step node.
        """

    def on_sfc_transition(self, ctx: AnalysisContext, trans: Transition) -> None:
        """Called for each SFC transition after its condition is read-collected.

        Parameters
        ----------
        ctx : AnalysisContext
            Current analysis context.
        trans : Transition
            The SFC transition node (``trans.condition`` is the guard expression).
        """

    # ------------------------------------------------------------------
    # Context construction
    # ------------------------------------------------------------------

    @staticmethod
    def _make_context(pou: POU) -> AnalysisContext:
        from ._types import TypeEnvironment

        iface = pou.interface
        return AnalysisContext(
            pou=pou,
            pou_name=pou.name,
            output_names={v.name for v in iface.output_vars},
            input_names={v.name for v in iface.input_vars},
            type_env=TypeEnvironment(iface),
        )

    @staticmethod
    def _make_method_context(pou: POU, method: Method) -> AnalysisContext:
        from ._types import TypeEnvironment

        iface = method.interface
        return AnalysisContext(
            pou=pou,
            pou_name=f"{pou.name}.{method.name}",
            output_names={v.name for v in iface.output_vars},
            input_names={v.name for v in iface.input_vars},
            type_env=TypeEnvironment(iface),
        )

    @staticmethod
    def _make_property_context(
        pou: POU, prop: Property, accessor_name: str,
    ) -> AnalysisContext:
        from ._types import TypeEnvironment
        from plx.model.pou import POUInterface
        from plx.model.variables import Variable

        # Build a minimal interface for type resolution
        accessor = prop.getter if accessor_name == "getter" else prop.setter
        type_env = None
        if accessor is not None:
            iface = POUInterface(temp_vars=list(accessor.local_vars))
            # Setter has an implicit VAR_INPUT with the property's type
            if accessor_name == "setter":
                iface = POUInterface(
                    input_vars=[Variable(name=prop.name, data_type=prop.data_type)],
                    temp_vars=list(accessor.local_vars),
                )
            type_env = TypeEnvironment(iface)

        return AnalysisContext(
            pou=pou,
            pou_name=f"{pou.name}.{prop.name}.{accessor_name}",
            output_names=set(),
            input_names=set(),
            type_env=type_env,
        )

    # ------------------------------------------------------------------
    # Body traversal
    # ------------------------------------------------------------------

    def _visit_body(
        self,
        ctx: AnalysisContext,
        networks: list[Network],
        sfc_body: SFCBody | None,
    ) -> None:
        """Walk a POU/method body (either networks or SFC)."""
        if sfc_body is not None:
            self._visit_sfc(ctx, sfc_body)
        else:
            for i, network in enumerate(networks):
                ctx.current_network_idx = i
                self._visit_network(ctx, network)

    # ------------------------------------------------------------------
    # Statement traversal
    # ------------------------------------------------------------------

    def _visit_network(self, ctx: AnalysisContext, network: Network) -> None:
        ctx.current_stmt_path.append(f"network {ctx.current_network_idx}")
        for stmt in network.statements:
            self._visit_stmt(ctx, stmt)
        ctx.current_stmt_path.pop()

    def _visit_stmt(self, ctx: AnalysisContext, stmt: Statement) -> None:
        handler = self._STMT_VISITORS.get(stmt.kind)  # type: ignore[union-attr]
        if handler is not None:
            handler(self, ctx, stmt)

    def _visit_assignment(self, ctx: AnalysisContext, stmt: Assignment) -> None:
        # Record the write
        target_name = self._extract_target_name(stmt.target)
        if target_name is not None:
            info = WriteInfo(
                guarded=ctx.nesting_depth > 0,
                nesting_depth=ctx.nesting_depth,
                guard_conditions=list(ctx.guard_conditions),
                value_is_true=self._is_bool_literal(stmt.value),
                location=self._location(ctx),
            )
            ctx.writes.setdefault(target_name, []).append(info)

        # Collect reads from the value expression
        self._collect_reads(ctx, stmt.value)

        self.on_assignment(ctx, stmt)

    def _visit_if(self, ctx: AnalysisContext, stmt: IfStatement) -> None:
        self.on_if_enter(ctx, stmt)

        # if branch
        ctx.nesting_depth += 1
        ctx.guard_conditions.append(stmt.if_branch.condition)
        ctx.current_stmt_path.append("if_branch")
        self._collect_reads(ctx, stmt.if_branch.condition)
        for s in stmt.if_branch.body:
            self._visit_stmt(ctx, s)
        ctx.current_stmt_path.pop()
        ctx.guard_conditions.pop()
        ctx.nesting_depth -= 1

        # elsif branches
        for i, branch in enumerate(stmt.elsif_branches):
            ctx.nesting_depth += 1
            ctx.guard_conditions.append(branch.condition)
            ctx.current_stmt_path.append(f"elsif_{i}")
            self._collect_reads(ctx, branch.condition)
            for s in branch.body:
                self._visit_stmt(ctx, s)
            ctx.current_stmt_path.pop()
            ctx.guard_conditions.pop()
            ctx.nesting_depth -= 1

        # else body
        if stmt.else_body:
            ctx.nesting_depth += 1
            ctx.current_stmt_path.append("else")
            for s in stmt.else_body:
                self._visit_stmt(ctx, s)
            ctx.current_stmt_path.pop()
            ctx.nesting_depth -= 1

        self.on_if_exit(ctx, stmt)

    def _visit_case(self, ctx: AnalysisContext, stmt: CaseStatement) -> None:
        self.on_case(ctx, stmt)
        self._collect_reads(ctx, stmt.selector)
        for i, branch in enumerate(stmt.branches):
            ctx.nesting_depth += 1
            ctx.guard_conditions.append(stmt.selector)
            ctx.current_stmt_path.append(f"case_{i}")
            for s in branch.body:
                self._visit_stmt(ctx, s)
            ctx.current_stmt_path.pop()
            ctx.guard_conditions.pop()
            ctx.nesting_depth -= 1

        if stmt.else_body:
            ctx.nesting_depth += 1
            ctx.guard_conditions.append(stmt.selector)
            ctx.current_stmt_path.append("case_else")
            for s in stmt.else_body:
                self._visit_stmt(ctx, s)
            ctx.current_stmt_path.pop()
            ctx.guard_conditions.pop()
            ctx.nesting_depth -= 1

    def _visit_for(self, ctx: AnalysisContext, stmt: ForStatement) -> None:
        self.on_for(ctx, stmt)
        self._collect_reads(ctx, stmt.from_expr)
        self._collect_reads(ctx, stmt.to_expr)
        if stmt.by_expr:
            self._collect_reads(ctx, stmt.by_expr)
        ctx.nesting_depth += 1
        ctx.current_stmt_path.append("for")
        for s in stmt.body:
            self._visit_stmt(ctx, s)
        ctx.current_stmt_path.pop()
        ctx.nesting_depth -= 1
        self.on_for_exit(ctx, stmt)

    def _visit_while(self, ctx: AnalysisContext, stmt: WhileStatement) -> None:
        self.on_while(ctx, stmt)
        self._collect_reads(ctx, stmt.condition)
        ctx.nesting_depth += 1
        ctx.current_stmt_path.append("while")
        for s in stmt.body:
            self._visit_stmt(ctx, s)
        ctx.current_stmt_path.pop()
        ctx.nesting_depth -= 1

    def _visit_repeat(self, ctx: AnalysisContext, stmt: RepeatStatement) -> None:
        self.on_repeat(ctx, stmt)
        ctx.nesting_depth += 1
        ctx.current_stmt_path.append("repeat")
        for s in stmt.body:
            self._visit_stmt(ctx, s)
        ctx.current_stmt_path.pop()
        ctx.nesting_depth -= 1
        self._collect_reads(ctx, stmt.until)

    def _visit_return(self, ctx: AnalysisContext, stmt: ReturnStatement) -> None:
        if stmt.value:
            self._collect_reads(ctx, stmt.value)
        self.on_return(ctx, stmt)

    def _visit_fb_invocation(self, ctx: AnalysisContext, stmt: FBInvocation) -> None:
        for expr in stmt.inputs.values():
            self._collect_reads(ctx, expr)

        # Record output targets as writes
        for _param_name, target_expr in stmt.outputs.items():
            target_name = self._extract_target_name(target_expr)
            if target_name is not None:
                info = WriteInfo(
                    guarded=ctx.nesting_depth > 0,
                    nesting_depth=ctx.nesting_depth,
                    guard_conditions=list(ctx.guard_conditions),
                    value_is_true=None,
                    location=self._location(ctx),
                )
                ctx.writes.setdefault(target_name, []).append(info)

        self.on_fb_invocation(ctx, stmt)

    def _visit_function_call_stmt(
        self, ctx: AnalysisContext, stmt: FunctionCallStatement
    ) -> None:
        for arg in stmt.args:
            self._collect_reads(ctx, arg.value)

    def _visit_try_catch(self, ctx: AnalysisContext, stmt: TryCatchStatement) -> None:
        # try body — treated as normal execution path (not guarded)
        ctx.current_stmt_path.append("try")
        for s in stmt.try_body:
            self._visit_stmt(ctx, s)
        ctx.current_stmt_path.pop()

        # catch body — conditional on exception, treat as guarded
        if stmt.catch_body:
            ctx.nesting_depth += 1
            ctx.current_stmt_path.append("catch")
            for s in stmt.catch_body:
                self._visit_stmt(ctx, s)
            ctx.current_stmt_path.pop()
            ctx.nesting_depth -= 1

        # finally body — always runs, treat as normal execution path
        if stmt.finally_body:
            ctx.current_stmt_path.append("finally")
            for s in stmt.finally_body:
                self._visit_stmt(ctx, s)
            ctx.current_stmt_path.pop()

        self.on_try_catch(ctx, stmt)

    def _visit_noop(self, ctx: AnalysisContext, stmt: Statement) -> None:
        pass

    _STMT_VISITORS: dict[
        str, Callable[[AnalysisVisitor, AnalysisContext, Statement], None]
    ] = {
        "assignment": _visit_assignment,
        "if": _visit_if,
        "case": _visit_case,
        "for": _visit_for,
        "while": _visit_while,
        "repeat": _visit_repeat,
        "return": _visit_return,
        "fb_invocation": _visit_fb_invocation,
        "function_call_stmt": _visit_function_call_stmt,
        "try_catch": _visit_try_catch,
        "exit": _visit_noop,
        "continue": _visit_noop,
        "empty": _visit_noop,
        "pragma": _visit_noop,
        "jump": _visit_noop,
        "label": _visit_noop,
    }

    # ------------------------------------------------------------------
    # SFC traversal
    # ------------------------------------------------------------------

    def _visit_sfc(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        self.on_sfc_enter(ctx, sfc)

        for step in sfc.steps:
            self.on_sfc_step(ctx, step)
            # Visit action bodies
            for action in step.actions:
                ctx.current_stmt_path.append(f"step:{step.name}/{action.name}")
                for s in action.body:
                    self._visit_stmt(ctx, s)
                ctx.current_stmt_path.pop()
            for action in step.entry_actions:
                ctx.current_stmt_path.append(f"step:{step.name}/entry:{action.name}")
                for s in action.body:
                    self._visit_stmt(ctx, s)
                ctx.current_stmt_path.pop()
            for action in step.exit_actions:
                ctx.current_stmt_path.append(f"step:{step.name}/exit:{action.name}")
                for s in action.body:
                    self._visit_stmt(ctx, s)
                ctx.current_stmt_path.pop()

        for trans in sfc.transitions:
            self.on_sfc_transition(ctx, trans)
            self._collect_reads(ctx, trans.condition)

        self.on_sfc_exit(ctx, sfc)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_target_name(expr: Expression) -> str | None:
        """Extract the root variable name from an assignment target.

        Recursively descends through MemberAccessExpr, ArrayAccessExpr,
        BitAccessExpr, and DerefExpr to find the underlying VariableRef.
        Examples: a[0].b -> 'a', a.b[0] -> 'a', a[0][1] -> 'a', ptr^.x -> 'ptr'
        """
        current: Expression = expr
        while True:
            if isinstance(current, VariableRef):
                return current.name
            if isinstance(current, MemberAccessExpr):
                current = current.struct
            elif isinstance(current, ArrayAccessExpr):
                current = current.array
            elif isinstance(current, BitAccessExpr):
                current = current.target
            elif isinstance(current, DerefExpr):
                current = current.pointer
            else:
                return None

    @staticmethod
    def _is_bool_literal(expr: Expression) -> bool | None:
        """Return True/False if expression is a boolean literal, else None."""
        if isinstance(expr, LiteralExpr):
            if expr.value == "TRUE":
                return True
            if expr.value == "FALSE":
                return False
        return None

    def _collect_reads(self, ctx: AnalysisContext, expr: Expression) -> None:
        """Recursively collect all variable references in an expression."""
        self.on_expression(ctx, expr)
        if isinstance(expr, VariableRef):
            info = ReadInfo(
                location=self._location(ctx),
                guarded=ctx.nesting_depth > 0,
            )
            ctx.reads.setdefault(expr.name, []).append(info)
        elif isinstance(expr, BinaryExpr):
            self._collect_reads(ctx, expr.left)
            self._collect_reads(ctx, expr.right)
        elif isinstance(expr, UnaryExpr):
            self._collect_reads(ctx, expr.operand)
        elif isinstance(expr, FunctionCallExpr):
            for arg in expr.args:
                self._collect_reads(ctx, arg.value)
        elif isinstance(expr, ArrayAccessExpr):
            self._collect_reads(ctx, expr.array)
            for idx in expr.indices:
                self._collect_reads(ctx, idx)
        elif isinstance(expr, MemberAccessExpr):
            self._collect_reads(ctx, expr.struct)
        elif isinstance(expr, DerefExpr):
            self._collect_reads(ctx, expr.pointer)
        elif isinstance(expr, BitAccessExpr):
            self._collect_reads(ctx, expr.target)
        elif isinstance(expr, TypeConversionExpr):
            self._collect_reads(ctx, expr.source)
        elif isinstance(expr, SubstringExpr):
            self._collect_reads(ctx, expr.string)
            if expr.start is not None:
                self._collect_reads(ctx, expr.start)
            if expr.end is not None:
                self._collect_reads(ctx, expr.end)
        # LiteralExpr, SystemFlagExpr — no reads

    @staticmethod
    def _location(ctx: AnalysisContext) -> str:
        """Build a human-readable location string from the context path."""
        if ctx.current_stmt_path:
            return " -> ".join(ctx.current_stmt_path)
        return ""

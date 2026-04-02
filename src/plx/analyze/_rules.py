"""Built-in analysis rules."""

from __future__ import annotations

from collections import defaultdict

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    Expression,
    FunctionCallExpr,
    MemberAccessExpr,
    TypeConversionExpr,
    UnaryExpr,
    VariableRef,
)
from plx.model.pou import POU, POUType
from plx.model.project import Project
from plx.model.sfc import SFCBody
from plx.model.statements import (
    Assignment,
    CaseStatement,
    ExitStatement,
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
from plx.model.types import (
    EnumType,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
)

from ._context import AnalysisContext
from ._results import AnalysisResult, Finding, Severity
from ._types import (
    _INTEGER_RANGE,
    is_narrowing,
    parse_integer_literal,
)
from ._visitor import AnalysisVisitor

# ---------------------------------------------------------------------------
# Safety rules
# ---------------------------------------------------------------------------


class UnguardedOutputRule(AnalysisVisitor):
    """Flag output variables written unconditionally.

    rule_id: ``"unguarded-output"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        for var_name, writes in ctx.writes.items():
            if var_name not in ctx.output_names:
                continue
            for w in writes:
                if not w.guarded:
                    ctx.findings.append(
                        Finding(
                            rule_id="unguarded-output",
                            severity=Severity.WARNING,
                            pou_name=ctx.pou_name,
                            message=f"Output '{var_name}' is written unconditionally",
                            location=w.location,
                            details={"variable": var_name},
                        )
                    )


class MultipleOutputWriteRule(AnalysisVisitor):
    """Flag output variables written in more than one location per scan.

    rule_id: ``"multiple-output-write"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        for var_name, writes in ctx.writes.items():
            if var_name not in ctx.output_names:
                continue
            if len(writes) > 1:
                locations = [w.location for w in writes]
                ctx.findings.append(
                    Finding(
                        rule_id="multiple-output-write",
                        severity=Severity.ERROR,
                        pou_name=ctx.pou_name,
                        message=(f"Output '{var_name}' is written in {len(writes)} locations — last write wins"),
                        location=locations[0],
                        details={
                            "variable": var_name,
                            "write_count": len(writes),
                            "locations": locations,
                        },
                    )
                )


class WriteToInputRule(AnalysisVisitor):
    """Flag writes to VAR_INPUT variables inside the POU body.

    rule_id: ``"write-to-input"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        for var_name, writes in ctx.writes.items():
            if var_name not in ctx.input_names:
                continue
            ctx.findings.append(
                Finding(
                    rule_id="write-to-input",
                    severity=Severity.ERROR,
                    pou_name=ctx.pou_name,
                    message=f"Input '{var_name}' is written inside the POU body",
                    location=writes[0].location,
                    details={"variable": var_name},
                )
            )


# ---------------------------------------------------------------------------
# Correctness rules
# ---------------------------------------------------------------------------


class RealEqualityRule(AnalysisVisitor):
    """Flag equality/inequality comparisons on REAL or LREAL operands.

    Uses ``on_expression`` to catch comparisons everywhere — IF conditions,
    WHILE conditions, CASE selectors, assignment values, etc.

    rule_id: ``"real-equality"``
    """

    _FLOAT_TYPES = frozenset({PrimitiveType.REAL, PrimitiveType.LREAL})

    def on_expression(self, ctx: AnalysisContext, expr: Expression) -> None:
        if not isinstance(expr, BinaryExpr):
            return
        if expr.op not in (BinaryOp.EQ, BinaryOp.NE):
            return
        if ctx.type_env is None:
            return
        left_type = ctx.type_env.resolve_expr_type(expr.left)
        right_type = ctx.type_env.resolve_expr_type(expr.right)
        if self._is_float(left_type) or self._is_float(right_type):
            op_str = "==" if expr.op == BinaryOp.EQ else "!="
            ctx.findings.append(
                Finding(
                    rule_id="real-equality",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"Floating-point comparison using '{op_str}' — use range-based comparison instead"),
                    location=self._location(ctx),
                )
            )

    @classmethod
    def _is_float(cls, t: object) -> bool:
        return isinstance(t, PrimitiveTypeRef) and t.type in cls._FLOAT_TYPES


class MissingCaseElseRule(AnalysisVisitor):
    """Flag CASE statements with no ELSE branch.

    rule_id: ``"missing-case-else"``
    """

    def on_case(self, ctx: AnalysisContext, stmt: CaseStatement) -> None:
        if not stmt.else_body:
            ctx.findings.append(
                Finding(
                    rule_id="missing-case-else",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message="CASE statement has no ELSE branch",
                    location=self._location(ctx),
                )
            )


class ForCounterWriteRule(AnalysisVisitor):
    """Flag writes to the FOR loop counter variable inside the loop body.

    rule_id: ``"for-counter-write"``
    """

    def __init__(self) -> None:
        super().__init__()
        self._loop_vars: list[str] = []

    def on_for(self, ctx: AnalysisContext, stmt: ForStatement) -> None:
        self._loop_vars.append(stmt.loop_var)

    def on_for_exit(self, ctx: AnalysisContext, stmt: ForStatement) -> None:
        self._loop_vars.pop()

    def on_assignment(self, ctx: AnalysisContext, stmt: Assignment) -> None:
        if not self._loop_vars:
            return
        target_name = self._extract_target_name(stmt.target)
        if target_name is not None and target_name in self._loop_vars:
            ctx.findings.append(
                Finding(
                    rule_id="for-counter-write",
                    severity=Severity.ERROR,
                    pou_name=ctx.pou_name,
                    message=(f"FOR loop counter '{target_name}' is modified inside the loop body"),
                    location=self._location(ctx),
                    details={"variable": target_name},
                )
            )


# ---------------------------------------------------------------------------
# Style / Unused rules
# ---------------------------------------------------------------------------


class UnusedVariableRule(AnalysisVisitor):
    """Flag variables that are declared but never read or written.

    rule_id: ``"unused-variable"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        # Skip method/property contexts — ctx.pou points to the parent POU,
        # not the method, so the interface vars would be wrong.
        if "." in ctx.pou_name:
            return

        all_vars: set[str] = set()
        for var_list in (
            ctx.pou.interface.input_vars,
            ctx.pou.interface.output_vars,
            ctx.pou.interface.inout_vars,
            ctx.pou.interface.static_vars,
            ctx.pou.interface.temp_vars,
        ):
            for v in var_list:
                all_vars.add(v.name)

        for var_name in sorted(all_vars):
            if var_name not in ctx.reads and var_name not in ctx.writes:
                ctx.findings.append(
                    Finding(
                        rule_id="unused-variable",
                        severity=Severity.WARNING,
                        pou_name=ctx.pou_name,
                        message=f"Variable '{var_name}' is declared but never used",
                        details={"variable": var_name},
                    )
                )


class UnusedInputRule(AnalysisVisitor):
    """Flag VAR_INPUT variables that are never read in the POU body.

    rule_id: ``"unused-input"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        for var_name in sorted(ctx.input_names):
            if var_name not in ctx.reads:
                ctx.findings.append(
                    Finding(
                        rule_id="unused-input",
                        severity=Severity.WARNING,
                        pou_name=ctx.pou_name,
                        message=f"Input '{var_name}' is declared but never read",
                        details={"variable": var_name},
                    )
                )


class UnusedOutputRule(AnalysisVisitor):
    """Flag VAR_OUTPUT variables that are never written in the POU body.

    rule_id: ``"unused-output"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        for var_name in sorted(ctx.output_names):
            if var_name not in ctx.writes:
                ctx.findings.append(
                    Finding(
                        rule_id="unused-output",
                        severity=Severity.WARNING,
                        pou_name=ctx.pou_name,
                        message=f"Output '{var_name}' is declared but never written",
                        details={"variable": var_name},
                    )
                )


class TempFBInstanceRule(AnalysisVisitor):
    """Flag function block instances declared as VAR_TEMP.

    Only flags ``NamedTypeRef`` types that are known POU types (FBs),
    not structs, enums, or other named data types.

    rule_id: ``"temp-fb-instance"``
    """

    def __init__(self) -> None:
        super().__init__()
        self._data_type_names: set[str] = set()

    def analyze_project(self, project: Project) -> AnalysisResult:
        self._data_type_names = {dt.name for dt in project.data_types}
        return super().analyze_project(project)

    def on_pou_enter(self, ctx: AnalysisContext) -> None:
        if "." in ctx.pou_name:
            return
        for var in ctx.pou.interface.temp_vars:
            if isinstance(var.data_type, NamedTypeRef):
                # Skip structs, enums, and other non-FB named types
                if var.data_type.name in self._data_type_names:
                    continue
                ctx.findings.append(
                    Finding(
                        rule_id="temp-fb-instance",
                        severity=Severity.WARNING,
                        pou_name=ctx.pou_name,
                        message=(
                            f"'{var.name}' of type '{var.data_type.name}' is "
                            f"declared as VAR_TEMP — FB state will be lost each scan"
                        ),
                        details={"variable": var.name, "fb_type": var.data_type.name},
                    )
                )


class EmptyBodyRule(AnalysisVisitor):
    """Flag POUs with no statements in their body.

    rule_id: ``"empty-body"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        pou = ctx.pou
        if "." in ctx.pou_name:
            return
        has_body = False
        if pou.sfc_body is not None and pou.sfc_body.steps:
            has_body = True
        else:
            for network in pou.networks:
                if network.statements:
                    has_body = True
                    break
        if not has_body and pou.pou_type != POUType.INTERFACE:
            ctx.findings.append(
                Finding(
                    rule_id="empty-body",
                    severity=Severity.INFO,
                    pou_name=ctx.pou_name,
                    message=f"POU '{pou.name}' has an empty body",
                )
            )


# ---------------------------------------------------------------------------
# SFC rules
# ---------------------------------------------------------------------------


class DeadSfcStepRule(AnalysisVisitor):
    """Flag SFC steps not targeted by any transition.

    rule_id: ``"sfc-dead-step"``
    """

    def on_sfc_exit(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        targeted: set[str] = set()
        for trans in sfc.transitions:
            targeted.update(trans.target_steps)
        for step in sfc.steps:
            if step.is_initial:
                continue
            if step.name not in targeted:
                ctx.findings.append(
                    Finding(
                        rule_id="sfc-dead-step",
                        severity=Severity.WARNING,
                        pou_name=ctx.pou_name,
                        message=(
                            f"Step '{step.name}' is unreachable — "
                            f"no transition targets it and it is not the initial step"
                        ),
                        details={"step": step.name},
                    )
                )


class SfcNoInitialStepRule(AnalysisVisitor):
    """Flag SFC bodies with no initial step.

    rule_id: ``"sfc-no-initial"``
    """

    def on_sfc_exit(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        if not sfc.steps:
            return
        if not any(s.is_initial for s in sfc.steps):
            ctx.findings.append(
                Finding(
                    rule_id="sfc-no-initial",
                    severity=Severity.ERROR,
                    pou_name=ctx.pou_name,
                    message="SFC has no initial step",
                )
            )


class SfcMultipleInitialStepsRule(AnalysisVisitor):
    """Flag SFC bodies with more than one initial step.

    rule_id: ``"sfc-multiple-initial"``
    """

    def on_sfc_exit(self, ctx: AnalysisContext, sfc: SFCBody) -> None:
        initial_steps = [s.name for s in sfc.steps if s.is_initial]
        if len(initial_steps) > 1:
            ctx.findings.append(
                Finding(
                    rule_id="sfc-multiple-initial",
                    severity=Severity.ERROR,
                    pou_name=ctx.pou_name,
                    message=(f"SFC has {len(initial_steps)} initial steps: {', '.join(initial_steps)}"),
                    details={"steps": initial_steps},
                )
            )


# ---------------------------------------------------------------------------
# Wave 2: Type-based rules
# ---------------------------------------------------------------------------


class NarrowingConversionRule(AnalysisVisitor):
    """Flag implicit narrowing type conversions in assignments.

    Detects DINT → INT, LREAL → REAL, signed → unsigned, etc.

    rule_id: ``"narrowing-conversion"``
    """

    def on_assignment(self, ctx: AnalysisContext, stmt: Assignment) -> None:
        if ctx.type_env is None:
            return
        target_type = ctx.type_env.resolve_expr_type(stmt.target)
        value_type = ctx.type_env.resolve_expr_type(stmt.value)
        if (
            isinstance(target_type, PrimitiveTypeRef)
            and isinstance(value_type, PrimitiveTypeRef)
            and is_narrowing(value_type.type, target_type.type)
        ):
            ctx.findings.append(
                Finding(
                    rule_id="narrowing-conversion",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"Implicit narrowing conversion from {value_type.type.value} to {target_type.type.value}"),
                    location=self._location(ctx),
                )
            )


class ConstantOutOfRangeRule(AnalysisVisitor):
    """Flag integer literal assignments that exceed the target type's range.

    rule_id: ``"constant-out-of-range"``
    """

    def on_assignment(self, ctx: AnalysisContext, stmt: Assignment) -> None:
        if ctx.type_env is None:
            return
        from plx.model.expressions import LiteralExpr

        if not isinstance(stmt.value, LiteralExpr):
            return
        target_type = ctx.type_env.resolve_expr_type(stmt.target)
        if not isinstance(target_type, PrimitiveTypeRef):
            return
        bounds = _INTEGER_RANGE.get(target_type.type)
        if bounds is None:
            return
        val = parse_integer_literal(stmt.value.value)
        if val is None:
            return
        lo, hi = bounds
        if val < lo or val > hi:
            ctx.findings.append(
                Finding(
                    rule_id="constant-out-of-range",
                    severity=Severity.ERROR,
                    pou_name=ctx.pou_name,
                    message=(f"Constant {val} exceeds {target_type.type.value} range [{lo}..{hi}]"),
                    location=self._location(ctx),
                )
            )


class EnumCastRule(AnalysisVisitor):
    """Flag explicit type-conversion of an enum literal to a primitive type.

    ``INT(BoxType#METAL)`` is not valid structured-text syntax in TwinCAT XAE
    and other IEC 61131-3 IDEs.  Declare the variable as the enum type and
    compare directly, or use a raw integer value.

    rule_id: ``"enum-cast-to-int"``
    """

    def on_expression(self, ctx: AnalysisContext, expr: Expression) -> None:
        if not isinstance(expr, TypeConversionExpr):
            return
        from plx.model.expressions import LiteralExpr

        if not isinstance(expr.source, LiteralExpr):
            return
        if not isinstance(expr.source.data_type, NamedTypeRef):
            return
        # Enum literals use the "EnumName#MEMBER" format
        if "#" not in expr.source.value:
            return
        ctx.findings.append(
            Finding(
                rule_id="enum-cast-to-int",
                severity=Severity.ERROR,
                pou_name=ctx.pou_name,
                message=(
                    f"Type cast of enum literal {expr.source.value!r} generates invalid "
                    f"structured-text syntax. Declare the variable as the enum type and "
                    f"compare directly, or use a raw integer value."
                ),
                location=self._location(ctx),
            )
        )


class DivisionByZeroRule(AnalysisVisitor):
    """Flag division or modulo where the divisor is a literal zero.

    rule_id: ``"division-by-zero"``
    """

    def on_expression(self, ctx: AnalysisContext, expr: Expression) -> None:
        if not isinstance(expr, BinaryExpr):
            return
        if expr.op not in (BinaryOp.DIV, BinaryOp.MOD):
            return
        from plx.model.expressions import LiteralExpr

        if isinstance(expr.right, LiteralExpr):
            is_zero = False
            val = parse_integer_literal(expr.right.value)
            if val == 0:
                is_zero = True
            else:
                # Check float zero (e.g. "0.0", "REAL#0.0")
                raw = expr.right.value
                if "#" in raw:
                    raw = raw.split("#", 1)[1]
                try:
                    if float(raw) == 0.0:
                        is_zero = True
                except ValueError:
                    pass
            if is_zero:
                op_name = "Division" if expr.op == BinaryOp.DIV else "Modulo"
                ctx.findings.append(
                    Finding(
                        rule_id="division-by-zero",
                        severity=Severity.ERROR,
                        pou_name=ctx.pou_name,
                        message=f"{op_name} by zero",
                        location=self._location(ctx),
                    )
                )


class IncompleteCaseEnumRule(AnalysisVisitor):
    """Flag CASE on an enum type that doesn't cover all members.

    Requires project-level analysis to resolve enum definitions.

    rule_id: ``"incomplete-enum-case"``
    """

    def __init__(self) -> None:
        super().__init__()
        self._enum_defs: dict[str, EnumType] = {}

    def analyze_project(self, project: Project) -> AnalysisResult:
        self._enum_defs = {td.name: td for td in project.data_types if isinstance(td, EnumType)}
        return super().analyze_project(project)

    def on_case(self, ctx: AnalysisContext, stmt: CaseStatement) -> None:
        if ctx.type_env is None or not self._enum_defs:
            return
        selector_type = ctx.type_env.resolve_expr_type(stmt.selector)
        if not isinstance(selector_type, NamedTypeRef):
            return
        enum_def = self._enum_defs.get(selector_type.name)
        if enum_def is None:
            return

        # Collect all covered values from branches
        covered: set[int | str] = set()
        for branch in stmt.branches:
            for v in branch.values:
                covered.add(v)
        # Check which enum members are missing
        missing = []
        for member in enum_def.members:
            key = member.value if member.value is not None else member.name
            if key not in covered and member.name not in covered:
                missing.append(member.name)

        if missing and not stmt.else_body:
            ctx.findings.append(
                Finding(
                    rule_id="incomplete-enum-case",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"CASE on '{selector_type.name}' is missing members: {', '.join(missing)}"),
                    location=self._location(ctx),
                    details={"enum": selector_type.name, "missing": missing},
                )
            )


# ---------------------------------------------------------------------------
# Wave 2: Complexity metrics
# ---------------------------------------------------------------------------


class CyclomaticComplexityRule(AnalysisVisitor):
    """Flag POUs whose cyclomatic complexity exceeds a threshold.

    CC = 1 + (number of decision points). Decision points: IF, ELSIF,
    CASE branches, FOR, WHILE, REPEAT, AND_THEN, OR_ELSE.

    rule_id: ``"cyclomatic-complexity"``
    """

    def __init__(self, max_complexity: int = 15) -> None:
        super().__init__()
        self._max = max_complexity
        self._cc = 0

    def on_pou_enter(self, ctx: AnalysisContext) -> None:
        self._cc = 1  # base path

    def on_if_enter(self, ctx: AnalysisContext, stmt: IfStatement) -> None:
        self._cc += 1 + len(stmt.elsif_branches)

    def on_case(self, ctx: AnalysisContext, stmt: CaseStatement) -> None:
        self._cc += len(stmt.branches)

    def on_for(self, ctx: AnalysisContext, stmt: ForStatement) -> None:
        self._cc += 1

    def on_while(self, ctx: AnalysisContext, stmt: WhileStatement) -> None:
        self._cc += 1

    def on_repeat(self, ctx: AnalysisContext, stmt: RepeatStatement) -> None:
        self._cc += 1

    def on_expression(self, ctx: AnalysisContext, expr: Expression) -> None:
        if isinstance(expr, BinaryExpr) and expr.op in (
            BinaryOp.AND_THEN,
            BinaryOp.OR_ELSE,
        ):
            self._cc += 1

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        if self._cc > self._max:
            ctx.findings.append(
                Finding(
                    rule_id="cyclomatic-complexity",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"Cyclomatic complexity is {self._cc} (threshold: {self._max})"),
                    details={"complexity": self._cc, "threshold": self._max},
                )
            )


class MaxNestingDepthRule(AnalysisVisitor):
    """Flag POUs where control-flow nesting exceeds a threshold.

    rule_id: ``"max-nesting-depth"``
    """

    def __init__(self, max_depth: int = 5) -> None:
        super().__init__()
        self._max = max_depth
        self._deepest = 0

    def on_pou_enter(self, ctx: AnalysisContext) -> None:
        self._deepest = 0

    def on_assignment(self, ctx: AnalysisContext, stmt: Assignment) -> None:
        self._deepest = max(self._deepest, ctx.nesting_depth)

    def on_fb_invocation(self, ctx: AnalysisContext, stmt: FBInvocation) -> None:
        self._deepest = max(self._deepest, ctx.nesting_depth)

    def on_expression(self, ctx: AnalysisContext, expr: Expression) -> None:
        self._deepest = max(self._deepest, ctx.nesting_depth)

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        if self._deepest > self._max:
            ctx.findings.append(
                Finding(
                    rule_id="max-nesting-depth",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"Maximum nesting depth is {self._deepest} (threshold: {self._max})"),
                    details={"depth": self._deepest, "threshold": self._max},
                )
            )


# ---------------------------------------------------------------------------
# Wave 2: Project-level rules
# ---------------------------------------------------------------------------


class RecursiveCallRule(AnalysisVisitor):
    """Flag direct or mutual recursion between POUs.

    Builds a call graph in ``analyze_project`` and detects cycles via DFS.

    rule_id: ``"recursive-call"``
    """

    def __init__(self) -> None:
        super().__init__()
        self._calls: dict[str, set[str]] = defaultdict(set)
        self._pou_names: set[str] = set()

    def analyze_project(self, project: Project) -> AnalysisResult:
        self._pou_names = {p.name for p in project.pous}
        # Build call graph
        for pou in project.pous:
            self._collect_calls(pou)
        # Detect cycles
        findings: list[Finding] = []
        visited: set[str] = set()
        on_stack: set[str] = set()

        def _dfs(node: str, path: list[str]) -> None:
            if node in on_stack:
                cycle_start = path.index(node)
                cycle = [*path[cycle_start:], node]
                findings.append(
                    Finding(
                        rule_id="recursive-call",
                        severity=Severity.ERROR,
                        pou_name=node,
                        message=(f"Recursive call cycle: {' → '.join(cycle)}"),
                        details={"cycle": cycle},
                    )
                )
                return
            if node in visited:
                return
            visited.add(node)
            on_stack.add(node)
            for callee in self._calls.get(node, ()):
                _dfs(callee, [*path, node])
            on_stack.discard(node)

        for name in sorted(self._pou_names):
            if name not in visited:
                _dfs(name, [])

        return AnalysisResult(
            findings=findings,
            pou_count=len(project.pous),
            rule_count=1,
        )

    def _collect_calls(self, pou: POU) -> None:
        """Walk POU statements to find all FB invocations and function calls."""
        for network in pou.networks:
            for stmt in network.statements:
                self._walk_stmt(pou.name, stmt)
        if pou.sfc_body:
            for step in pou.sfc_body.steps:
                for action in step.actions + step.entry_actions + step.exit_actions:
                    for stmt in action.body:
                        self._walk_stmt(pou.name, stmt)
        for method in pou.methods:
            for network in method.networks:
                for stmt in network.statements:
                    self._walk_stmt(pou.name, stmt)
        for prop in pou.properties:
            for accessor in (prop.getter, prop.setter):
                if accessor is not None:
                    for network in accessor.networks:
                        for stmt in network.statements:
                            self._walk_stmt(pou.name, stmt)
        for action in pou.actions:
            for network in action.body:
                for stmt in network.statements:
                    self._walk_stmt(pou.name, stmt)

    def _walk_stmt(self, caller: str, stmt: object) -> None:
        if isinstance(stmt, FBInvocation):
            if isinstance(stmt.fb_type, NamedTypeRef):
                callee = stmt.fb_type.name
                if callee in self._pou_names:
                    self._calls[caller].add(callee)
        elif isinstance(stmt, FunctionCallStatement):
            if stmt.function_name in self._pou_names:
                self._calls[caller].add(stmt.function_name)
        # Recurse into compound statements
        if isinstance(stmt, IfStatement):
            for s in stmt.if_branch.body:
                self._walk_stmt(caller, s)
            for branch in stmt.elsif_branches:
                for s in branch.body:
                    self._walk_stmt(caller, s)
            for s in stmt.else_body:
                self._walk_stmt(caller, s)
        elif isinstance(stmt, CaseStatement):
            for branch in stmt.branches:
                for s in branch.body:
                    self._walk_stmt(caller, s)
            for s in stmt.else_body:
                self._walk_stmt(caller, s)
        elif isinstance(stmt, ForStatement):
            for s in stmt.body:
                self._walk_stmt(caller, s)
        elif isinstance(stmt, WhileStatement):
            for s in stmt.body:
                self._walk_stmt(caller, s)
        elif isinstance(stmt, RepeatStatement):
            for s in stmt.body:
                self._walk_stmt(caller, s)
        elif isinstance(stmt, TryCatchStatement):
            for s in stmt.try_body:
                self._walk_stmt(caller, s)
            for s in stmt.catch_body:
                self._walk_stmt(caller, s)
            for s in stmt.finally_body:
                self._walk_stmt(caller, s)


class VariableShadowRule(AnalysisVisitor):
    """Flag local variables that shadow global variable names.

    Requires project-level analysis to know global variable names.

    rule_id: ``"variable-shadow"``
    """

    def __init__(self) -> None:
        super().__init__()
        self._global_names: set[str] = set()

    def analyze_project(self, project: Project) -> AnalysisResult:
        self._global_names = set()
        for gvl in project.global_variable_lists:
            for v in gvl.variables:
                self._global_names.add(v.name)
        return super().analyze_project(project)

    def on_pou_enter(self, ctx: AnalysisContext) -> None:
        if not self._global_names:
            return
        if "." in ctx.pou_name:
            return
        for var_list in (
            ctx.pou.interface.input_vars,
            ctx.pou.interface.output_vars,
            ctx.pou.interface.inout_vars,
            ctx.pou.interface.static_vars,
            ctx.pou.interface.temp_vars,
        ):
            for v in var_list:
                if v.name in self._global_names:
                    ctx.findings.append(
                        Finding(
                            rule_id="variable-shadow",
                            severity=Severity.WARNING,
                            pou_name=ctx.pou_name,
                            message=(f"Variable '{v.name}' shadows a global variable"),
                            details={"variable": v.name},
                        )
                    )


# ---------------------------------------------------------------------------
# Wave 3: Cross-POU / data flow rules
# ---------------------------------------------------------------------------


class CrossTaskWriteRule(AnalysisVisitor):
    """Flag variables written by POUs in different tasks.

    Concurrent writes produce race conditions. Especially dangerous for
    non-atomic types (REAL, LREAL, STRING, STRUCT).

    rule_id: ``"cross-task-write"``
    """

    def analyze_project(self, project: Project) -> AnalysisResult:
        # Build task → POU set (direct assignments only for now)
        task_pous: dict[str, set[str]] = {}
        for task in project.tasks:
            task_pous[task.name] = set(task.assigned_pous)

        # Collect writes per POU — exclude definitely-local variables
        pou_writes: dict[str, set[str]] = {}
        for pou in project.pous:
            ctx = self._make_context(pou)
            self._visit_body(ctx, pou.networks, pou.sfc_body)
            for action in pou.actions:
                for network in action.body:
                    self._visit_network(ctx, network)
            # POU-local vars can't cause cross-task races
            iface = pou.interface
            local_names = (
                {v.name for v in iface.input_vars}
                | {v.name for v in iface.output_vars}
                | {v.name for v in iface.static_vars}
                | {v.name for v in iface.temp_vars}
                | {v.name for v in iface.constant_vars}
                | {v.name for v in iface.inout_vars}
            )
            pou_writes[pou.name] = set(ctx.writes.keys()) - local_names

        # Check for cross-task writes
        findings: list[Finding] = []
        # Map variable → set of task names that write it
        var_tasks: dict[str, set[str]] = defaultdict(set)
        for task_name, pou_names in task_pous.items():
            for pou_name in pou_names:
                for var_name in pou_writes.get(pou_name, ()):
                    var_tasks[var_name].add(task_name)

        for var_name in sorted(var_tasks):
            tasks = var_tasks[var_name]
            if len(tasks) > 1:
                findings.append(
                    Finding(
                        rule_id="cross-task-write",
                        severity=Severity.ERROR,
                        pou_name="(project)",
                        message=(
                            f"Variable '{var_name}' is written by POUs in multiple tasks: {', '.join(sorted(tasks))}"
                        ),
                        details={
                            "variable": var_name,
                            "tasks": sorted(tasks),
                        },
                    )
                )

        return AnalysisResult(
            findings=findings,
            pou_count=len(project.pous),
            rule_count=1,
        )


class UnusedPOURule(AnalysisVisitor):
    """Flag POUs that are never called and not assigned to any task.

    rule_id: ``"unused-pou"``
    """

    def analyze_project(self, project: Project) -> AnalysisResult:
        pou_names = {p.name for p in project.pous}

        # POUs assigned to tasks
        task_assigned: set[str] = set()
        for task in project.tasks:
            task_assigned.update(task.assigned_pous)

        # POUs called by other POUs (reuse RecursiveCallRule's pattern)
        called: set[str] = set()
        for pou in project.pous:
            self._collect_callees(pou, pou_names, called)

        # A POU is "used" if it's in a task OR called by another POU
        used = task_assigned | called
        findings: list[Finding] = []
        for pou in project.pous:
            if pou.name not in used:
                findings.append(
                    Finding(
                        rule_id="unused-pou",
                        severity=Severity.INFO,
                        pou_name=pou.name,
                        message=f"POU '{pou.name}' is never called or assigned to a task",
                    )
                )

        return AnalysisResult(
            findings=findings,
            pou_count=len(project.pous),
            rule_count=1,
        )

    def _collect_callees(
        self,
        pou: POU,
        pou_names: set[str],
        out: set[str],
    ) -> None:
        for network in pou.networks:
            for stmt in network.statements:
                self._walk(stmt, pou_names, out)
        if pou.sfc_body:
            for step in pou.sfc_body.steps:
                for action in step.actions + step.entry_actions + step.exit_actions:
                    for stmt in action.body:
                        self._walk(stmt, pou_names, out)
        for method in pou.methods:
            for network in method.networks:
                for stmt in network.statements:
                    self._walk(stmt, pou_names, out)
        for prop in pou.properties:
            for accessor in (prop.getter, prop.setter):
                if accessor is not None:
                    for network in accessor.networks:
                        for stmt in network.statements:
                            self._walk(stmt, pou_names, out)
        for action in pou.actions:
            for network in action.body:
                for stmt in network.statements:
                    self._walk(stmt, pou_names, out)

    def _walk(self, stmt: object, pou_names: set[str], out: set[str]) -> None:
        if isinstance(stmt, FBInvocation) and isinstance(stmt.fb_type, NamedTypeRef):
            if stmt.fb_type.name in pou_names:
                out.add(stmt.fb_type.name)
        elif isinstance(stmt, FunctionCallStatement):
            if stmt.function_name in pou_names:
                out.add(stmt.function_name)
        # Recurse into compound statements
        if isinstance(stmt, IfStatement):
            for s in stmt.if_branch.body:
                self._walk(s, pou_names, out)
            for branch in stmt.elsif_branches:
                for s in branch.body:
                    self._walk(s, pou_names, out)
            for s in stmt.else_body:
                self._walk(s, pou_names, out)
        elif isinstance(stmt, CaseStatement):
            for branch in stmt.branches:
                for s in branch.body:
                    self._walk(s, pou_names, out)
            for s in stmt.else_body:
                self._walk(s, pou_names, out)
        elif isinstance(stmt, ForStatement):
            for s in stmt.body:
                self._walk(s, pou_names, out)
        elif isinstance(stmt, WhileStatement):
            for s in stmt.body:
                self._walk(s, pou_names, out)
        elif isinstance(stmt, RepeatStatement):
            for s in stmt.body:
                self._walk(s, pou_names, out)
        elif isinstance(stmt, TryCatchStatement):
            for s in stmt.try_body:
                self._walk(s, pou_names, out)
            for s in stmt.catch_body:
                self._walk(s, pou_names, out)
            for s in stmt.finally_body:
                self._walk(s, pou_names, out)


class UnreachableCodeRule(AnalysisVisitor):
    """Flag statements after unconditional RETURN or EXIT.

    rule_id: ``"unreachable-code"``
    """

    def on_pou_enter(self, ctx: AnalysisContext) -> None:
        if "." in ctx.pou_name:
            return
        for network in ctx.pou.networks:
            self._check_stmts(ctx, network.statements)

    def _check_stmts(self, ctx: AnalysisContext, stmts: list[Statement]) -> None:
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, (ReturnStatement, ExitStatement)):
                remaining = stmts[i + 1 :]
                if remaining:
                    ctx.findings.append(
                        Finding(
                            rule_id="unreachable-code",
                            severity=Severity.WARNING,
                            pou_name=ctx.pou_name,
                            message=(
                                f"{len(remaining)} statement(s) after "
                                f"unconditional {'RETURN' if isinstance(stmt, ReturnStatement) else 'EXIT'}"
                            ),
                            location=self._location(ctx),
                        )
                    )
                    break
            # Recurse into compound statement bodies
            if isinstance(stmt, IfStatement):
                self._check_stmts(ctx, stmt.if_branch.body)
                for branch in stmt.elsif_branches:
                    self._check_stmts(ctx, branch.body)
                self._check_stmts(ctx, stmt.else_body)
            elif isinstance(stmt, CaseStatement):
                for branch in stmt.branches:
                    self._check_stmts(ctx, branch.body)
                self._check_stmts(ctx, stmt.else_body)
            elif isinstance(stmt, ForStatement):
                self._check_stmts(ctx, stmt.body)
            elif isinstance(stmt, WhileStatement):
                self._check_stmts(ctx, stmt.body)
            elif isinstance(stmt, RepeatStatement):
                self._check_stmts(ctx, stmt.body)
            elif isinstance(stmt, TryCatchStatement):
                self._check_stmts(ctx, stmt.try_body)
                self._check_stmts(ctx, stmt.catch_body)
                self._check_stmts(ctx, stmt.finally_body)


class IgnoredFBOutputRule(AnalysisVisitor):
    """Flag FB invocations whose outputs are never read.

    If an FB is invoked but no member of the instance is ever read,
    the FB's outputs (status, error, done, etc.) are being ignored.

    rule_id: ``"ignored-fb-output"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        if "." in ctx.pou_name:
            return

        # Collect all FB instance names that are invoked
        invoked: set[str] = set()
        for network in ctx.pou.networks:
            for stmt in network.statements:
                self._collect_invocations(stmt, invoked)
        if ctx.pou.sfc_body:
            for step in ctx.pou.sfc_body.steps:
                for action in step.actions + step.entry_actions + step.exit_actions:
                    for stmt in action.body:
                        self._collect_invocations(stmt, invoked)
        for action in ctx.pou.actions:
            for network in action.body:
                for stmt in network.statements:
                    self._collect_invocations(stmt, invoked)

        if not invoked:
            return

        # Collect all instance names whose members are read
        # A member read looks like MemberAccessExpr(struct=VariableRef("timer"), member="Q")
        read_instances: set[str] = set()
        for var_name in ctx.reads:
            # Variable name alone isn't enough — we need to check if any
            # MemberAccessExpr with this instance as struct exists in reads.
            # But ctx.reads only stores root variable names.
            # So: an instance is "read" if its name appears in ctx.reads
            # (which means a MemberAccessExpr like timer.Q was read,
            # and _collect_reads recorded "timer" as a read).
            if var_name in invoked:
                read_instances.add(var_name)

        for name in sorted(invoked - read_instances):
            ctx.findings.append(
                Finding(
                    rule_id="ignored-fb-output",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"FB instance '{name}' is invoked but its outputs are never read"),
                    details={"instance": name},
                )
            )

    def _collect_invocations(self, stmt: object, out: set[str]) -> None:
        if isinstance(stmt, FBInvocation) and isinstance(stmt.instance_name, str):
            out.add(stmt.instance_name)
        if isinstance(stmt, IfStatement):
            for s in stmt.if_branch.body:
                self._collect_invocations(s, out)
            for branch in stmt.elsif_branches:
                for s in branch.body:
                    self._collect_invocations(s, out)
            for s in stmt.else_body:
                self._collect_invocations(s, out)
        elif isinstance(stmt, CaseStatement):
            for branch in stmt.branches:
                for s in branch.body:
                    self._collect_invocations(s, out)
            for s in stmt.else_body:
                self._collect_invocations(s, out)
        elif isinstance(stmt, ForStatement):
            for s in stmt.body:
                self._collect_invocations(s, out)
        elif isinstance(stmt, WhileStatement):
            for s in stmt.body:
                self._collect_invocations(s, out)
        elif isinstance(stmt, RepeatStatement):
            for s in stmt.body:
                self._collect_invocations(s, out)
        elif isinstance(stmt, TryCatchStatement):
            for s in stmt.try_body:
                self._collect_invocations(s, out)
            for s in stmt.catch_body:
                self._collect_invocations(s, out)
            for s in stmt.finally_body:
                self._collect_invocations(s, out)


class UseBeforeDefRule(AnalysisVisitor):
    """Flag VAR_TEMP variables that are read before being written.

    Limited to temp vars since they're re-initialized each scan.
    Static/input/output vars persist across scans and are excluded.

    rule_id: ``"use-before-def"``
    """

    def on_pou_exit(self, ctx: AnalysisContext) -> None:
        if "." in ctx.pou_name:
            return

        temp_names = {v.name for v in ctx.pou.interface.temp_vars}
        if not temp_names:
            return

        # Walk the statement list sequentially, tracking which temps
        # have been definitely written before being read.
        written: set[str] = set()
        flagged: set[str] = set()

        for network in ctx.pou.networks:
            for stmt in network.statements:
                self._scan_stmt(ctx, stmt, temp_names, written, flagged)

        for var_name in sorted(flagged):
            ctx.findings.append(
                Finding(
                    rule_id="use-before-def",
                    severity=Severity.WARNING,
                    pou_name=ctx.pou_name,
                    message=(f"Temp variable '{var_name}' may be read before being written"),
                    details={"variable": var_name},
                )
            )

    def _scan_stmt(
        self,
        ctx: AnalysisContext,
        stmt: Statement,
        temps: set[str],
        written: set[str],
        flagged: set[str],
    ) -> None:
        if isinstance(stmt, Assignment):
            # Check reads in value expression BEFORE recording the write
            self._scan_reads(stmt.value, temps, written, flagged)
            target = self._extract_target_name(stmt.target)
            if target in temps:
                written.add(target)
        elif isinstance(stmt, FBInvocation):
            for expr in stmt.inputs.values():
                self._scan_reads(expr, temps, written, flagged)
        elif isinstance(stmt, FunctionCallStatement):
            for arg in stmt.args:
                self._scan_reads(arg.value, temps, written, flagged)
        elif isinstance(stmt, IfStatement):
            self._scan_reads(stmt.if_branch.condition, temps, written, flagged)
            # Writes inside branches are not definite — save/restore so
            # only pre-branch writes are visible to subsequent code.
            saved = set(written)
            for s in stmt.if_branch.body:
                self._scan_stmt(ctx, s, temps, written, flagged)
            written.clear()
            written.update(saved)
            for branch in stmt.elsif_branches:
                self._scan_reads(branch.condition, temps, written, flagged)
                for s in branch.body:
                    self._scan_stmt(ctx, s, temps, written, flagged)
                written.clear()
                written.update(saved)
            for s in stmt.else_body:
                self._scan_stmt(ctx, s, temps, written, flagged)
            written.clear()
            written.update(saved)
        elif isinstance(stmt, CaseStatement):
            self._scan_reads(stmt.selector, temps, written, flagged)
            saved = set(written)
            for branch in stmt.branches:
                for s in branch.body:
                    self._scan_stmt(ctx, s, temps, written, flagged)
                written.clear()
                written.update(saved)
            for s in stmt.else_body:
                self._scan_stmt(ctx, s, temps, written, flagged)
            written.clear()
            written.update(saved)
        elif isinstance(stmt, ForStatement):
            self._scan_reads(stmt.from_expr, temps, written, flagged)
            self._scan_reads(stmt.to_expr, temps, written, flagged)
            if stmt.by_expr:
                self._scan_reads(stmt.by_expr, temps, written, flagged)
            saved = set(written)
            for s in stmt.body:
                self._scan_stmt(ctx, s, temps, written, flagged)
            written.clear()
            written.update(saved)
        elif isinstance(stmt, WhileStatement):
            self._scan_reads(stmt.condition, temps, written, flagged)
            saved = set(written)
            for s in stmt.body:
                self._scan_stmt(ctx, s, temps, written, flagged)
            written.clear()
            written.update(saved)
        elif isinstance(stmt, RepeatStatement):
            for s in stmt.body:
                self._scan_stmt(ctx, s, temps, written, flagged)
            self._scan_reads(stmt.until, temps, written, flagged)
        elif isinstance(stmt, ReturnStatement):
            if stmt.value:
                self._scan_reads(stmt.value, temps, written, flagged)

    def _scan_reads(
        self,
        expr: Expression,
        temps: set[str],
        written: set[str],
        flagged: set[str],
    ) -> None:
        """Check if any temp variable is read before being written."""
        if isinstance(expr, VariableRef):
            if expr.name in temps and expr.name not in written:
                flagged.add(expr.name)
        elif isinstance(expr, BinaryExpr):
            self._scan_reads(expr.left, temps, written, flagged)
            self._scan_reads(expr.right, temps, written, flagged)
        elif isinstance(expr, UnaryExpr):
            self._scan_reads(expr.operand, temps, written, flagged)
        elif isinstance(expr, FunctionCallExpr):
            for arg in expr.args:
                self._scan_reads(arg.value, temps, written, flagged)
        elif isinstance(expr, ArrayAccessExpr):
            self._scan_reads(expr.array, temps, written, flagged)
            for idx in expr.indices:
                self._scan_reads(idx, temps, written, flagged)
        elif isinstance(expr, TypeConversionExpr):
            self._scan_reads(expr.source, temps, written, flagged)
        elif isinstance(expr, MemberAccessExpr):
            self._scan_reads(expr.struct, temps, written, flagged)

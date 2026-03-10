"""Vendor target validation for the plx framework.

When compiling a project with ``target=Vendor.AB`` (or SIEMENS), the
validation pass checks that the IR only uses features supported by that
vendor.  This catches Beckhoff-specific constructs early — before the
raise pass or exporter sees them.

Beckhoff follows IEC 61131-3 most closely and supports all current IR
features.  Allen Bradley and Siemens lack OOP (methods, properties,
interfaces) and pointer/reference types.  Enums are universal — the
raise pass for AB/Siemens will lower ``EnumType`` to DINT constants.

In addition to hard errors, the validation pass collects **portability
warnings** for features that will compile but require instruction
translation — e.g. RTO on Beckhoff, SR/RS on AB/Siemens.  Warnings
are returned via ``CompileResult`` and never block compilation.

Usage::

    from plx.framework import project, Vendor

    ir = project("MyProject", pous=[Main]).compile(target=Vendor.AB)
    # → VendorValidationError if Main uses @method, etc.
    # → CompileResult with .project and .warnings otherwise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from plx.model.project import Project
from plx.model.expressions import (
    Expression,
    FunctionCallExpr,
    BinaryExpr,
    UnaryExpr,
    ArrayAccessExpr,
    MemberAccessExpr,
    BitAccessExpr,
    TypeConversionExpr,
)
from plx.model.types import NamedTypeRef
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    WhileStatement,
)

from ._compiler_core import CompileError


# ---------------------------------------------------------------------------
# Vendor enum
# ---------------------------------------------------------------------------

class Vendor(str, Enum):
    """Target PLC vendor for compilation."""

    BECKHOFF = "beckhoff"
    AB = "ab"
    SIEMENS = "siemens"


# ---------------------------------------------------------------------------
# Portability warnings
# ---------------------------------------------------------------------------

@dataclass
class PortabilityWarning:
    """A non-blocking warning about a feature that requires translation.

    Unlike ``VendorValidationError`` (which rejects the project),
    portability warnings indicate that compilation will succeed but
    round-trip fidelity or semantics may differ on the target vendor.
    """

    category: str       # "fb_translation", "oop_flattening"
    pou_name: str       # which POU triggered it
    message: str        # human-readable description
    details: dict[str, Any] = field(default_factory=dict)


class CompileResult:
    """Wraps a compiled ``Project`` IR together with portability warnings.

    Returned by ``PlxProject.compile(target=...)`` when a vendor target
    is specified.  Delegates attribute access to ``.project`` so that
    existing code (``result.pous``, ``result.name``, etc.) works unchanged.
    """

    def __init__(
        self,
        project: Project,
        warnings: list[PortabilityWarning],
    ) -> None:
        object.__setattr__(self, "project", project)
        object.__setattr__(self, "warnings", warnings)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.project, name)

    def __repr__(self) -> str:
        w = len(self.warnings)
        return (
            f"CompileResult(project={self.project.name!r}, "
            f"warnings={w})"
        )


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class VendorValidationError(CompileError):
    """Raised when a project uses features not supported by the target vendor."""

    def __init__(self, target: Vendor, errors: list[str]) -> None:
        self.target = target
        self.errors = errors
        header = f"Project contains features not supported by {target.value}:"
        body = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{header}\n{body}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_target(
    project: Project, target: Vendor,
) -> list[PortabilityWarning]:
    """Validate that *project* only uses features supported by *target*.

    Called automatically by ``PlxProject.compile(target=...)`` when a
    target is specified.  Collects all hard errors and raises a single
    ``VendorValidationError`` listing every problem.  Returns a list of
    non-blocking ``PortabilityWarning`` items for translatable features.

    To add a new vendor-specific check, append a function to
    ``_CHECKS``.  Each check takes ``(project, target, errors)``
    and appends human-readable strings to *errors*.

    To add a new portability warning, either add an entry to
    ``_FB_TRANSLATION_WARNINGS`` or append a function to ``_WARNINGS``.
    """
    errors: list[str] = []

    # Hard checks — Beckhoff supports all current features, skip for it
    if target != Vendor.BECKHOFF:
        for check in _CHECKS:
            check(project, target, errors)

    if errors:
        raise VendorValidationError(target, errors)

    # Portability warnings — run for ALL vendors (including Beckhoff)
    warnings: list[PortabilityWarning] = []
    for warn_fn in _WARNINGS:
        warn_fn(project, target, warnings)

    return warnings


# ---------------------------------------------------------------------------
# Individual checks — append to _CHECKS to register
# ---------------------------------------------------------------------------

def _check_methods(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """Methods on FBs are Beckhoff-only."""
    for pou in project.pous:
        if pou.methods:
            names = ", ".join(m.name for m in pou.methods)
            errors.append(
                f"POU '{pou.name}' has methods ({names}) — "
                f"methods are Beckhoff-only"
            )


def _check_properties(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """Properties on FBs are Beckhoff-only."""
    for pou in project.pous:
        if pou.properties:
            names = ", ".join(p.name for p in pou.properties)
            errors.append(
                f"POU '{pou.name}' has properties ({names}) — "
                f"properties are Beckhoff-only"
            )


def _check_interfaces(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """INTERFACE POUs and implements lists are Beckhoff-only."""
    from plx.model.pou import POUType

    for pou in project.pous:
        if pou.pou_type == POUType.INTERFACE:
            errors.append(
                f"POU '{pou.name}' is an INTERFACE — "
                f"interfaces are Beckhoff-only"
            )
        if pou.implements:
            errors.append(
                f"POU '{pou.name}' implements {', '.join(pou.implements)} — "
                f"interfaces are Beckhoff-only"
            )


def _check_abstract_final(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """Abstract POUs and abstract/final methods/properties are Beckhoff-only."""
    for pou in project.pous:
        if pou.abstract:
            errors.append(
                f"POU '{pou.name}' is ABSTRACT — "
                f"abstract function blocks are Beckhoff-only"
            )
        for m in pou.methods:
            if m.abstract:
                errors.append(
                    f"Method '{pou.name}.{m.name}' is ABSTRACT — "
                    f"abstract methods are Beckhoff-only"
                )
            if m.final:
                errors.append(
                    f"Method '{pou.name}.{m.name}' is FINAL — "
                    f"final methods are Beckhoff-only"
                )
        for p in pou.properties:
            if p.abstract:
                errors.append(
                    f"Property '{pou.name}.{p.name}' is ABSTRACT — "
                    f"abstract properties are Beckhoff-only"
                )
            if p.final:
                errors.append(
                    f"Property '{pou.name}.{p.name}' is FINAL — "
                    f"final properties are Beckhoff-only"
                )


def _check_struct_extends(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """Struct inheritance (EXTENDS) is Beckhoff-only."""
    from plx.model.types import StructType

    for dt in project.data_types:
        if isinstance(dt, StructType) and dt.extends is not None:
            errors.append(
                f"Struct '{dt.name}' extends '{dt.extends}' — "
                f"struct inheritance is Beckhoff-only"
            )


def _check_pointer_reference_types(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """POINTER_TO and REFERENCE_TO are Beckhoff-only."""
    for pou in project.pous:
        all_vars = (
            pou.interface.input_vars
            + pou.interface.output_vars
            + pou.interface.inout_vars
            + pou.interface.static_vars
            + pou.interface.temp_vars
            + pou.interface.constant_vars
        )
        for var in all_vars:
            if _type_contains(var.data_type, "pointer"):
                errors.append(
                    f"Variable '{pou.name}.{var.name}' uses POINTER_TO — "
                    f"pointer types are Beckhoff-only"
                )
            if _type_contains(var.data_type, "reference"):
                errors.append(
                    f"Variable '{pou.name}.{var.name}' uses REFERENCE_TO — "
                    f"reference types are Beckhoff-only"
                )


def _type_contains(type_ref: object, kind: str) -> bool:
    """Recursively check if *type_ref* contains a type of the given kind."""
    if getattr(type_ref, "kind", None) == kind:
        return True
    # Recurse into wrapper types (POINTER_TO X, REFERENCE_TO X, ARRAY OF X)
    for attr in ("target_type", "element_type"):
        inner = getattr(type_ref, attr, None)
        if inner is not None and _type_contains(inner, kind):
            return True
    return False


# ---------------------------------------------------------------------------
# Check registry — add new checks here
# ---------------------------------------------------------------------------

_CHECKS = [
    _check_methods,
    _check_properties,
    _check_interfaces,
    _check_abstract_final,
    _check_struct_extends,
    _check_pointer_reference_types,
]


# ---------------------------------------------------------------------------
# FB translation warnings — data-driven
# ---------------------------------------------------------------------------

# Mapping: {fb_type: {vendor: message}}.  Adding a new FB translation
# warning is a single dict entry — no new check function needed.
_FB_TRANSLATION_WARNINGS: dict[str, dict[Vendor, str]] = {
    "RTO": {
        Vendor.BECKHOFF: (
            "RTO (retentive on-delay timer) has no native Beckhoff equivalent "
            "and must be synthesized from TON + latch logic. "
            "Use retentive() sentinel for portable code."
        ),
    },
    "SR": {
        Vendor.AB: (
            "SR (set-dominant bistable) has different parameter names on AB. "
            "The raise pass will translate parameter names automatically."
        ),
        Vendor.SIEMENS: (
            "SR (set-dominant bistable) has different parameter names on Siemens. "
            "The raise pass will translate parameter names automatically."
        ),
    },
    "RS": {
        Vendor.AB: (
            "RS (reset-dominant bistable) has different parameter names on AB. "
            "The raise pass will translate parameter names automatically."
        ),
        Vendor.SIEMENS: (
            "RS (reset-dominant bistable) has different parameter names on Siemens. "
            "The raise pass will translate parameter names automatically."
        ),
    },
    "CTU": {
        Vendor.AB: (
            "CTU (count-up counter) has a different interface on AB. "
            "The raise pass will translate parameters automatically."
        ),
        Vendor.SIEMENS: (
            "CTU (count-up counter) has a different interface on Siemens. "
            "The raise pass will translate parameters automatically."
        ),
    },
    "CTD": {
        Vendor.AB: (
            "CTD (count-down counter) has a different interface on AB. "
            "The raise pass will translate parameters automatically."
        ),
        Vendor.SIEMENS: (
            "CTD (count-down counter) has a different interface on Siemens. "
            "The raise pass will translate parameters automatically."
        ),
    },
}


def _collect_fb_types(project: Project) -> dict[str, set[str]]:
    """Walk all statements in *project* and collect FB invocation types.

    Returns ``{fb_type: {pou_name, ...}}``.
    """
    result: dict[str, set[str]] = {}

    def _walk_statements(stmts: list[Statement], pou_name: str) -> None:
        for stmt in stmts:
            if isinstance(stmt, FBInvocation):
                if isinstance(stmt.fb_type, NamedTypeRef):
                    result.setdefault(stmt.fb_type.name, set()).add(pou_name)
            elif isinstance(stmt, IfStatement):
                _walk_statements(stmt.if_branch.body, pou_name)
                for branch in stmt.elsif_branches:
                    _walk_statements(branch.body, pou_name)
                _walk_statements(stmt.else_body, pou_name)
            elif isinstance(stmt, CaseStatement):
                for branch in stmt.branches:
                    _walk_statements(branch.body, pou_name)
                _walk_statements(stmt.else_body, pou_name)
            elif isinstance(stmt, ForStatement):
                _walk_statements(stmt.body, pou_name)
            elif isinstance(stmt, WhileStatement):
                _walk_statements(stmt.body, pou_name)
            elif isinstance(stmt, RepeatStatement):
                _walk_statements(stmt.body, pou_name)

    for pou in project.pous:
        # Networks
        for net in pou.networks:
            _walk_statements(net.statements, pou.name)

        # SFC body
        if pou.sfc_body:
            for step in pou.sfc_body.steps:
                for action in step.actions + step.entry_actions + step.exit_actions:
                    _walk_statements(action.body, pou.name)

        # Methods
        for m in pou.methods:
            for net in m.networks:
                _walk_statements(net.statements, pou.name)
            if m.sfc_body:
                for step in m.sfc_body.steps:
                    for action in step.actions + step.entry_actions + step.exit_actions:
                        _walk_statements(action.body, pou.name)

    return result


# ---------------------------------------------------------------------------
# Warning checks — append to _WARNINGS to register
# ---------------------------------------------------------------------------

def _check_fb_translation(
    project: Project,
    target: Vendor,
    warnings: list[PortabilityWarning],
) -> None:
    """Warn about FBs that require instruction translation on the target."""
    fb_types = _collect_fb_types(project)
    for fb_type, pou_names in sorted(fb_types.items()):
        vendor_msgs = _FB_TRANSLATION_WARNINGS.get(fb_type)
        if vendor_msgs and target in vendor_msgs:
            for pou_name in sorted(pou_names):
                warnings.append(PortabilityWarning(
                    category="fb_translation",
                    pou_name=pou_name,
                    message=vendor_msgs[target],
                    details={"fb_type": fb_type, "target": target.value},
                ))


# ---------------------------------------------------------------------------
# Math function translation warnings — data-driven
# ---------------------------------------------------------------------------

_MATH_TRANSLATION_WARNINGS: dict[str, dict[Vendor, str]] = {
    "EXP": {
        Vendor.AB: (
            "EXP() has no native AB equivalent. "
            "The raise pass will rewrite to EXPT(2.718..., x)."
        ),
    },
    "CEIL": {
        Vendor.AB: (
            "CEIL() has no native AB equivalent. "
            "The raise pass will synthesize from TRN + conditional."
        ),
    },
    "FLOOR": {
        Vendor.AB: (
            "FLOOR() has no native AB equivalent. "
            "The raise pass will synthesize from TRN + conditional."
        ),
    },
}


def _walk_expressions(expr: Expression) -> list[FunctionCallExpr]:
    """Recursively collect all FunctionCallExpr nodes in an expression tree."""
    result: list[FunctionCallExpr] = []
    if isinstance(expr, FunctionCallExpr):
        result.append(expr)
        for arg in expr.args:
            result.extend(_walk_expressions(arg.value))
    elif isinstance(expr, BinaryExpr):
        result.extend(_walk_expressions(expr.left))
        result.extend(_walk_expressions(expr.right))
    elif isinstance(expr, UnaryExpr):
        result.extend(_walk_expressions(expr.operand))
    elif isinstance(expr, ArrayAccessExpr):
        result.extend(_walk_expressions(expr.array))
        for idx in expr.indices:
            result.extend(_walk_expressions(idx))
    elif isinstance(expr, MemberAccessExpr):
        result.extend(_walk_expressions(expr.struct))
    elif isinstance(expr, BitAccessExpr):
        result.extend(_walk_expressions(expr.target))
    elif isinstance(expr, TypeConversionExpr):
        result.extend(_walk_expressions(expr.source))
    return result


def _collect_function_calls(project: Project) -> dict[str, set[str]]:
    """Walk all expressions in *project* and collect function call names.

    Returns ``{function_name: {pou_name, ...}}``.
    """
    result: dict[str, set[str]] = {}

    def _extract_from_expr(expr: Expression, pou_name: str) -> None:
        for call in _walk_expressions(expr):
            result.setdefault(call.function_name, set()).add(pou_name)

    def _extract_from_stmts(stmts: list[Statement], pou_name: str) -> None:
        for stmt in stmts:
            if isinstance(stmt, Assignment):
                _extract_from_expr(stmt.value, pou_name)
                _extract_from_expr(stmt.target, pou_name)
            elif isinstance(stmt, FunctionCallStatement):
                _extract_from_expr(
                    FunctionCallExpr(function_name=stmt.function_name, args=stmt.args),
                    pou_name,
                )
            elif isinstance(stmt, ReturnStatement) and stmt.value is not None:
                _extract_from_expr(stmt.value, pou_name)
            elif isinstance(stmt, FBInvocation):
                for expr in stmt.inputs.values():
                    _extract_from_expr(expr, pou_name)
            elif isinstance(stmt, IfStatement):
                _extract_from_expr(stmt.if_branch.condition, pou_name)
                _extract_from_stmts(stmt.if_branch.body, pou_name)
                for branch in stmt.elsif_branches:
                    _extract_from_expr(branch.condition, pou_name)
                    _extract_from_stmts(branch.body, pou_name)
                _extract_from_stmts(stmt.else_body, pou_name)
            elif isinstance(stmt, CaseStatement):
                _extract_from_expr(stmt.selector, pou_name)
                for branch in stmt.branches:
                    _extract_from_stmts(branch.body, pou_name)
                _extract_from_stmts(stmt.else_body, pou_name)
            elif isinstance(stmt, ForStatement):
                _extract_from_expr(stmt.from_expr, pou_name)
                _extract_from_expr(stmt.to_expr, pou_name)
                if stmt.by_expr is not None:
                    _extract_from_expr(stmt.by_expr, pou_name)
                _extract_from_stmts(stmt.body, pou_name)
            elif isinstance(stmt, WhileStatement):
                _extract_from_expr(stmt.condition, pou_name)
                _extract_from_stmts(stmt.body, pou_name)
            elif isinstance(stmt, RepeatStatement):
                _extract_from_expr(stmt.until, pou_name)
                _extract_from_stmts(stmt.body, pou_name)

    for pou in project.pous:
        for net in pou.networks:
            _extract_from_stmts(net.statements, pou.name)
        if pou.sfc_body:
            for step in pou.sfc_body.steps:
                for action in step.actions + step.entry_actions + step.exit_actions:
                    _extract_from_stmts(action.body, pou.name)
        for m in pou.methods:
            for net in m.networks:
                _extract_from_stmts(net.statements, pou.name)

    return result


def _check_math_function_portability(
    project: Project,
    target: Vendor,
    warnings: list[PortabilityWarning],
) -> None:
    """Warn about math functions that require translation on the target."""
    func_calls = _collect_function_calls(project)
    for func_name, pou_names in sorted(func_calls.items()):
        vendor_msgs = _MATH_TRANSLATION_WARNINGS.get(func_name)
        if vendor_msgs and target in vendor_msgs:
            for pou_name in sorted(pou_names):
                warnings.append(PortabilityWarning(
                    category="math_translation",
                    pou_name=pou_name,
                    message=vendor_msgs[target],
                    details={"function": func_name, "target": target.value},
                ))


def _check_oop_flattening(
    project: Project,
    target: Vendor,
    warnings: list[PortabilityWarning],
) -> None:
    """Warn about FB inheritance that must be flattened for AB/Siemens."""
    if target == Vendor.BECKHOFF:
        return  # Beckhoff supports EXTENDS natively

    for pou in project.pous:
        if pou.extends:
            warnings.append(PortabilityWarning(
                category="oop_flattening",
                pou_name=pou.name,
                message=(
                    f"POU '{pou.name}' extends '{pou.extends}' — "
                    f"FB inheritance will be flattened for {target.value} "
                    f"(the raise pass inlines the parent hierarchy)."
                ),
                details={
                    "extends": pou.extends,
                    "target": target.value,
                },
            ))


# ---------------------------------------------------------------------------
# Warning registry — add new warnings here
# ---------------------------------------------------------------------------

_WARNINGS = [
    _check_fb_translation,
    _check_math_function_portability,
    _check_oop_flattening,
]


# ---------------------------------------------------------------------------
# Extension registration — allows private vendor repos to add checks
# ---------------------------------------------------------------------------

_BUILTIN_CHECK_COUNT = len(_CHECKS)
_BUILTIN_WARNING_COUNT = len(_WARNINGS)
_BUILTIN_FB_WARNINGS: dict[str, dict[Vendor, str]] = {
    k: dict(v) for k, v in _FB_TRANSLATION_WARNINGS.items()
}


def register_vendor_check(check_fn) -> None:
    """Register an additional vendor validation check.

    check_fn signature: (project: Project, target: Vendor, errors: list) -> None
    """
    _CHECKS.append(check_fn)


def register_vendor_warning(warning_fn) -> None:
    """Register an additional vendor portability warning.

    warning_fn signature: (project: Project, target: Vendor, warnings: list) -> None
    """
    _WARNINGS.append(warning_fn)


def register_fb_translation_warning(fb_type: str, vendor: Vendor, message: str) -> None:
    """Register an FB translation warning for a specific vendor."""
    _FB_TRANSLATION_WARNINGS.setdefault(fb_type, {})[vendor] = message


def _clear_vendor_extensions() -> None:
    """Remove all registered extensions, restoring built-in checks only. For tests."""
    del _CHECKS[_BUILTIN_CHECK_COUNT:]
    del _WARNINGS[_BUILTIN_WARNING_COUNT:]
    _FB_TRANSLATION_WARNINGS.clear()
    _FB_TRANSLATION_WARNINGS.update(
        {k: dict(v) for k, v in _BUILTIN_FB_WARNINGS.items()}
    )

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
    # → VendorValidationError if Main uses @fb_method, etc.
    # → CompileResult with .project and .warnings otherwise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from plx.model.project import Project
from plx.model.expressions import (
    DerefExpr,
    Expression,
    FunctionCallExpr,
)
from plx.model.types import NamedTypeRef
from plx.model.statements import (
    Assignment,
    FBInvocation,
    FunctionCallStatement,
    Statement,
)
from plx.model.walk import walk_expressions, walk_pou

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

    When ``round_trippable`` is False, the expansion is lossy — the
    original construct cannot be recovered on re-import.
    """

    category: str       # "fb_translation", "oop_flattening", "instruction_expansion"
    pou_name: str       # which POU triggered it
    message: str        # human-readable description
    details: dict[str, Any] = field(default_factory=dict)
    round_trippable: bool = True  # False for lossy expansions (e.g. RTO → TON + latch)


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

    # Library type checks — run for ALL vendors (AB type on Beckhoff, etc.)
    for check in _LIBRARY_CHECKS:
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


def _check_pointer_reference_operations(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """DerefExpr, ADR/ADRINST/SIZEOF, and REF= are Beckhoff-only."""
    _POINTER_FUNCS = {"ADR", "ADRINST", "SIZEOF"}

    # Check for pointer functions (ADR, ADRINST, SIZEOF)
    func_calls = _collect_function_calls(project)
    for func_name in _POINTER_FUNCS:
        if func_name in func_calls:
            for pou_name in sorted(func_calls[func_name]):
                errors.append(
                    f"POU '{pou_name}' uses {func_name}() — "
                    f"pointer functions are Beckhoff-only"
                )

    # Check for DerefExpr and ref_assign in statements
    for pou in project.pous:
        deref_reported = False

        def _on_stmt(stmt: Statement) -> None:
            nonlocal deref_reported
            if isinstance(stmt, Assignment) and stmt.ref_assign:
                errors.append(
                    f"POU '{pou.name}' uses REF= assignment — "
                    f"reference assignment is Beckhoff-only"
                )

        def _on_expr(expr: Expression) -> None:
            nonlocal deref_reported
            if not deref_reported and isinstance(expr, DerefExpr):
                errors.append(
                    f"POU '{pou.name}' uses pointer dereference — "
                    f"pointer operations are Beckhoff-only"
                )
                deref_reported = True

        walk_pou(pou, on_stmt=_on_stmt, on_expr=_on_expr)


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
    _check_pointer_reference_operations,
]


# ---------------------------------------------------------------------------
# Library type compatibility checks — run for ALL vendors
# ---------------------------------------------------------------------------

def _extract_named_type_refs(type_ref: object) -> set[str]:
    """Recursively collect NamedTypeRef names from a type tree."""
    names: set[str] = set()
    if isinstance(type_ref, NamedTypeRef):
        names.add(type_ref.name)
    for attr in ("element_type", "target_type"):
        inner = getattr(type_ref, attr, None)
        if inner is not None:
            names.update(_extract_named_type_refs(inner))
    return names


def _check_library_type_compatibility(
    project: Project, target: Vendor, errors: list[str],
) -> None:
    """Check that library types match the compile target vendor."""
    from ._library import get_library_type  # avoid circular import

    seen: set[tuple[str, str]] = set()  # (pou_name, type_name) dedup

    def _check_type(type_name: str, pou_name: str) -> None:
        if (pou_name, type_name) in seen:
            return
        seen.add((pou_name, type_name))
        lib_type = get_library_type(type_name)
        if lib_type is None:
            return
        vendor = lib_type._vendor
        if vendor and vendor != target.value:
            errors.append(
                f"POU '{pou_name}' uses {type_name} (vendor: {vendor}) "
                f"which is not compatible with target {target.value}"
            )

    # 1. FB invocations
    fb_types = _collect_fb_types(project)
    for fb_type_name, pou_names in fb_types.items():
        for pou_name in pou_names:
            _check_type(fb_type_name, pou_name)

    # 2. Variable type declarations
    for pou in project.pous:
        all_vars = (
            pou.interface.input_vars + pou.interface.output_vars
            + pou.interface.inout_vars + pou.interface.static_vars
            + pou.interface.temp_vars + pou.interface.constant_vars
        )
        for var in all_vars:
            for name in _extract_named_type_refs(var.data_type):
                _check_type(name, pou.name)


_LIBRARY_CHECKS = [
    _check_library_type_compatibility,
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
            "and will be synthesized from TON + latch logic. "
            "This expansion will not round-trip as RTO on re-import. "
            "Use retentive() sentinel for portable code."
        ),
        Vendor.SIEMENS: (
            "RTO (retentive on-delay timer) has no native Siemens equivalent "
            "and will be synthesized from TON + latch logic. "
            "This expansion will not round-trip as RTO on re-import. "
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

    for pou in project.pous:
        def _on_stmt(stmt: Statement, _name: str = pou.name) -> None:
            if isinstance(stmt, FBInvocation) and isinstance(stmt.fb_type, NamedTypeRef):
                result.setdefault(stmt.fb_type.name, set()).add(_name)
        walk_pou(pou, on_stmt=_on_stmt)

    return result


# ---------------------------------------------------------------------------
# Warning checks — append to _WARNINGS to register
# ---------------------------------------------------------------------------

# FB types whose instruction expansion is not round-trippable.
_NON_ROUND_TRIPPABLE_FBS: set[str] = {"RTO"}


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
                    round_trippable=fb_type not in _NON_ROUND_TRIPPABLE_FBS,
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


def _collect_function_calls(project: Project) -> dict[str, set[str]]:
    """Walk all expressions in *project* and collect function call names.

    Returns ``{function_name: {pou_name, ...}}``.
    """
    result: dict[str, set[str]] = {}

    for pou in project.pous:
        def _on_stmt(stmt: Statement, _name: str = pou.name) -> None:
            # FunctionCallStatement is a statement, not an expression —
            # capture its function_name directly
            if isinstance(stmt, FunctionCallStatement):
                result.setdefault(stmt.function_name, set()).add(_name)

        def _on_expr(expr: Expression, _name: str = pou.name) -> None:
            if isinstance(expr, FunctionCallExpr):
                result.setdefault(expr.function_name, set()).add(_name)

        walk_pou(pou, on_stmt=_on_stmt, on_expr=_on_expr)

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
_BUILTIN_LIBRARY_CHECK_COUNT = len(_LIBRARY_CHECKS)
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
    del _LIBRARY_CHECKS[_BUILTIN_LIBRARY_CHECK_COUNT:]
    del _WARNINGS[_BUILTIN_WARNING_COUNT:]
    _FB_TRANSLATION_WARNINGS.clear()
    _FB_TRANSLATION_WARNINGS.update(
        {k: dict(v) for k, v in _BUILTIN_FB_WARNINGS.items()}
    )

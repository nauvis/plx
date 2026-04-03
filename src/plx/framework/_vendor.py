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

Examples
--------
::

    from plx.framework import project, Vendor

    ir = project("MyProject", pous=[Main]).compile(target=Vendor.AB)
    # → VendorValidationError if Main uses @fb_method, etc.
    # → CompileResult with .project and .warnings otherwise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from plx.model.expressions import (
    DerefExpr,
    Expression,
    FunctionCallExpr,
)
from plx.model.project import Project
from plx.model.statements import (
    Assignment,
    ContinueStatement,
    FBInvocation,
    FunctionCallStatement,
    RepeatStatement,
    Statement,
    TryCatchStatement,
)
from plx.model.types import (
    AliasType,
    ArrayTypeRef,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
    SubrangeType,
    UnionType,
)
from plx.model.walk import walk_pou

from ._compiler_core import CompileError

# ---------------------------------------------------------------------------
# AB primitive type constraints
# Duplicated from private/src/plx/ab/_type_mappings.py (can't import private)
# ---------------------------------------------------------------------------

_AB_UNSUPPORTED_PRIMITIVES = frozenset(
    {
        PrimitiveType.CHAR,
        PrimitiveType.WCHAR,
        PrimitiveType.DATE,
        PrimitiveType.LDATE,
        PrimitiveType.TOD,
        PrimitiveType.LTOD,
        PrimitiveType.DT,
        PrimitiveType.LDT,
    }
)

_AB_LOSSY_TYPE_MAP: dict[PrimitiveType, str] = {
    PrimitiveType.BYTE: "SINT",
    PrimitiveType.WORD: "INT",
    PrimitiveType.DWORD: "DINT",
    PrimitiveType.LWORD: "LINT",
    PrimitiveType.TIME: "DINT",
    PrimitiveType.LTIME: "LINT",
}


# ---------------------------------------------------------------------------
# Vendor enum
# ---------------------------------------------------------------------------


class Vendor(StrEnum):
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

    When ``round_trippable`` is False, the expansion is lossy -- the
    original construct cannot be recovered on re-import.

    Attributes
    ----------
    category : str
        Warning category identifier (e.g. ``"fb_translation"``,
        ``"oop_flattening"``, ``"instruction_expansion"``).
    pou_name : str
        Name of the POU that triggered the warning.
    message : str
        Human-readable description of the portability concern.
    details : dict[str, Any]
        Arbitrary key-value metadata (e.g. ``{"fb_type": "RTO"}``).
    round_trippable : bool
        ``True`` if the translated output can be re-imported losslessly.
        ``False`` for lossy expansions (e.g. RTO synthesized from
        TON + latch logic).
    """

    category: str
    pou_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    round_trippable: bool = True


class CompileResult:
    """Wraps a compiled ``Project`` IR together with portability warnings.

    Returned by ``PlxProject.compile(target=...)`` when a vendor target
    is specified.  Delegates attribute access to ``.project`` so that
    existing code (``result.pous``, ``result.name``, etc.) works unchanged.

    Attributes
    ----------
    project : Project
        The compiled Universal IR project.
    warnings : list[PortabilityWarning]
        Non-blocking portability warnings collected during validation.
        Empty when the project uses only universally-supported features.
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
        return f"CompileResult(project={self.project.name!r}, warnings={w})"


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
    project: Project,
    target: Vendor,
    *,
    allow_lossy: bool = False,
) -> list[PortabilityWarning]:
    """Validate that *project* only uses features supported by *target*.

    Called automatically by ``PlxProject.compile(target=...)`` when a
    target is specified.  Collects all hard errors and raises a single
    ``VendorValidationError`` listing every problem.  Returns a list of
    non-blocking ``PortabilityWarning`` items for translatable features.

    Parameters
    ----------
    allow_lossy:
        When True, lossy transforms (e.g. inheritance flattening) are
        permitted — they are downgraded from hard errors to
        ``PortabilityWarning(round_trippable=False)``.  The resulting
        vendor code will be valid but cannot be round-tripped back to
        the original Python source.

    To add a new vendor-specific check, append a function to
    ``_CHECKS``.  Each check takes ``(project, target, errors)``
    and appends human-readable strings to *errors*.

    To add a new lossy check, append to ``_LOSSY_CHECKS``.  Same
    signature as ``_CHECKS``, but gated by ``allow_lossy``.

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

    # Lossy checks — hard errors unless allow_lossy=True
    if target != Vendor.BECKHOFF:
        lossy_errors: list[str] = []
        for check in _LOSSY_CHECKS:
            check(project, target, lossy_errors)

        if lossy_errors:
            if not allow_lossy:
                raise VendorValidationError(target, lossy_errors)
            # Downgrade to non-round-trippable warnings
            for msg in lossy_errors:
                warnings.append(
                    PortabilityWarning(
                        category="lossy_transform",
                        pou_name="",
                        message=msg,
                        round_trippable=False,
                    )
                )

    return warnings


# ---------------------------------------------------------------------------
# Individual checks — append to _CHECKS to register
# ---------------------------------------------------------------------------


def _check_methods(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """Methods on FBs are Beckhoff-only."""
    for pou in project.pous:
        if pou.methods:
            names = ", ".join(m.name for m in pou.methods)
            errors.append(f"POU '{pou.name}' has methods ({names}) — methods are Beckhoff-only")


def _check_properties(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """Properties on FBs are Beckhoff-only."""
    for pou in project.pous:
        if pou.properties:
            names = ", ".join(p.name for p in pou.properties)
            errors.append(f"POU '{pou.name}' has properties ({names}) — properties are Beckhoff-only")


def _check_interfaces(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """INTERFACE POUs and implements lists are Beckhoff-only."""
    from plx.model.pou import POUType

    for pou in project.pous:
        if pou.pou_type == POUType.INTERFACE:
            errors.append(f"POU '{pou.name}' is an INTERFACE — interfaces are Beckhoff-only")
        if pou.implements:
            errors.append(f"POU '{pou.name}' implements {', '.join(pou.implements)} — interfaces are Beckhoff-only")


def _check_abstract_final(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """Abstract POUs and abstract/final methods/properties are Beckhoff-only."""
    for pou in project.pous:
        if pou.abstract:
            errors.append(f"POU '{pou.name}' is ABSTRACT — abstract function blocks are Beckhoff-only")
        for m in pou.methods:
            if m.abstract:
                errors.append(f"Method '{pou.name}.{m.name}' is ABSTRACT — abstract methods are Beckhoff-only")
            if m.final:
                errors.append(f"Method '{pou.name}.{m.name}' is FINAL — final methods are Beckhoff-only")
        for p in pou.properties:
            if p.abstract:
                errors.append(f"Property '{pou.name}.{p.name}' is ABSTRACT — abstract properties are Beckhoff-only")
            if p.final:
                errors.append(f"Property '{pou.name}.{p.name}' is FINAL — final properties are Beckhoff-only")


def _check_struct_extends(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """Struct inheritance (EXTENDS) is Beckhoff-only."""
    from plx.model.types import StructType

    for dt in project.data_types:
        if isinstance(dt, StructType) and dt.extends is not None:
            errors.append(f"Struct '{dt.name}' extends '{dt.extends}' — struct inheritance is Beckhoff-only")


def _check_pointer_reference_types(
    project: Project,
    target: Vendor,
    errors: list[str],
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
                errors.append(f"Variable '{pou.name}.{var.name}' uses POINTER_TO — pointer types are Beckhoff-only")
            if _type_contains(var.data_type, "reference"):
                errors.append(f"Variable '{pou.name}.{var.name}' uses REFERENCE_TO — reference types are Beckhoff-only")


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


def _type_contains_primitive(
    type_ref: object,
    primitives: frozenset[PrimitiveType],
) -> PrimitiveType | None:
    """Recursively check if *type_ref* contains any of *primitives*.

    Returns the first matching ``PrimitiveType`` or ``None``.
    """
    if isinstance(type_ref, PrimitiveTypeRef) and type_ref.type in primitives:
        return type_ref.type
    for attr in ("element_type", "target_type"):
        inner = getattr(type_ref, attr, None)
        if inner is not None:
            result = _type_contains_primitive(inner, primitives)
            if result is not None:
                return result
    return None


def _check_pointer_reference_operations(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """DerefExpr, ADR/ADRINST/SIZEOF, and REF= are Beckhoff-only."""
    _POINTER_FUNCS = {"ADR", "ADRINST", "SIZEOF"}

    # Check for pointer functions (ADR, ADRINST, SIZEOF)
    func_calls = _collect_function_calls(project)
    for func_name in _POINTER_FUNCS:
        if func_name in func_calls:
            for pou_name in sorted(func_calls[func_name]):
                errors.append(f"POU '{pou_name}' uses {func_name}() — pointer functions are Beckhoff-only")

    # Check for DerefExpr and ref_assign in statements
    for pou in project.pous:
        deref_reported = False

        def _on_stmt(stmt: Statement) -> None:
            nonlocal deref_reported
            if isinstance(stmt, Assignment) and stmt.ref_assign:
                errors.append(f"POU '{pou.name}' uses REF= assignment — reference assignment is Beckhoff-only")

        def _on_expr(expr: Expression) -> None:
            nonlocal deref_reported
            if not deref_reported and isinstance(expr, DerefExpr):
                errors.append(f"POU '{pou.name}' uses pointer dereference — pointer operations are Beckhoff-only")
                deref_reported = True

        walk_pou(pou, on_stmt=_on_stmt, on_expr=_on_expr)


def _check_try_catch(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """TRY/CATCH is Beckhoff-only (__TRY/__CATCH)."""
    for pou in project.pous:
        found = False

        def _on_stmt(stmt: Statement) -> None:
            nonlocal found
            if not found and isinstance(stmt, TryCatchStatement):
                errors.append(f"POU '{pou.name}' uses TRY/CATCH — TRY/CATCH is Beckhoff-only")
                found = True

        walk_pou(pou, on_stmt=_on_stmt)


def _check_continue_statement(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """CONTINUE is not supported by AB Structured Text."""
    if target != Vendor.AB:
        return
    for pou in project.pous:
        found = False

        def _on_stmt(stmt: Statement) -> None:
            nonlocal found
            if not found and isinstance(stmt, ContinueStatement):
                errors.append(f"POU '{pou.name}' uses CONTINUE — AB Structured Text does not support CONTINUE")
                found = True

        walk_pou(pou, on_stmt=_on_stmt)


def _check_repeat_statement(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """REPEAT..UNTIL is not supported by AB Structured Text."""
    if target != Vendor.AB:
        return
    for pou in project.pous:
        found = False

        def _on_stmt(stmt: Statement) -> None:
            nonlocal found
            if not found and isinstance(stmt, RepeatStatement):
                errors.append(
                    f"POU '{pou.name}' uses REPEAT..UNTIL — AB Structured Text does not support REPEAT..UNTIL"
                )
                found = True

        walk_pou(pou, on_stmt=_on_stmt)


def _check_wstring(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """WSTRING is not supported by AB."""
    if target != Vendor.AB:
        return
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
            if _type_contains_wstring(var.data_type):
                errors.append(f"Variable '{pou.name}.{var.name}' uses WSTRING — AB does not support WSTRING")


def _type_contains_wstring(type_ref: object) -> bool:
    """Check if a type tree contains WSTRING."""
    if isinstance(type_ref, StringTypeRef) and type_ref.wide:
        return True
    for attr in ("element_type", "target_type"):
        inner = getattr(type_ref, attr, None)
        if inner is not None and _type_contains_wstring(inner):
            return True
    return False


def _check_unsupported_data_types(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """UnionType, AliasType, and SubrangeType are not supported by AB or Siemens."""
    for dt in project.data_types:
        if isinstance(dt, UnionType):
            errors.append(f"Data type '{dt.name}' is a UNION — {target.value} does not support union types")
        elif isinstance(dt, AliasType):
            errors.append(f"Data type '{dt.name}' is a type alias — {target.value} does not support type aliases")
        elif isinstance(dt, SubrangeType):
            errors.append(f"Data type '{dt.name}' is a subrange type — {target.value} does not support subrange types")


def _check_array_constraints(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """AB arrays must start at index 0 and use literal bounds."""
    if target != Vendor.AB:
        return
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
            _check_array_type(var.data_type, pou.name, var.name, errors)

    for dt in project.data_types:
        from plx.model.types import StructType

        if isinstance(dt, StructType):
            for member in dt.members:
                _check_array_type(member.data_type, dt.name, member.name, errors)


def _check_array_type(
    type_ref: object,
    scope_name: str,
    var_name: str,
    errors: list[str],
) -> None:
    """Recursively check array types for AB constraints."""
    if isinstance(type_ref, ArrayTypeRef):
        for dim in type_ref.dimensions:
            if not isinstance(dim.lower, int) or not isinstance(dim.upper, int):
                errors.append(
                    f"Variable '{scope_name}.{var_name}' uses expression-based "
                    f"array bounds — AB does not support expression-based array bounds"
                )
                return
            if dim.lower != 0:
                errors.append(
                    f"Variable '{scope_name}.{var_name}' has array lower bound "
                    f"{dim.lower} — AB arrays must start at index 0"
                )
                return
        # Also check element type (for nested arrays)
        _check_array_type(type_ref.element_type, scope_name, var_name, errors)


def _check_ab_siemens_extends(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """FB inheritance (EXTENDS) is not supported by AB or Siemens.

    Neither vendor has native inheritance — the raise pass flattens
    the hierarchy into a single AOI/FB.  This flattening is lossy
    and cannot be round-tripped, so it is blocked as a hard error.
    """
    if target not in (Vendor.AB, Vendor.SIEMENS):
        return
    for pou in project.pous:
        if pou.extends:
            errors.append(
                f"POU '{pou.name}' extends '{pou.extends}' — "
                f"FB inheritance is not supported by {target.value}. "
                f"Flattening is lossy and cannot be round-tripped."
            )


def _check_sfc_body(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """SFC bodies are not yet supported by the AB or Siemens raise passes.

    The raise passes silently drop sfc_body — this check prevents
    silent data loss by rejecting SFC POUs early.
    """
    if target not in (Vendor.AB, Vendor.SIEMENS):
        return
    for pou in project.pous:
        if pou.sfc_body is not None:
            errors.append(
                f"POU '{pou.name}' uses SFC (Sequential Function Chart) — SFC is not yet supported for {target.value}"
            )


def _check_pou_actions(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """POU actions are not yet supported by the AB or Siemens raise passes.

    The raise passes silently drop pou.actions — this check prevents
    silent data loss by rejecting POUs with actions early.
    """
    if target not in (Vendor.AB, Vendor.SIEMENS):
        return
    for pou in project.pous:
        if pou.actions:
            names = ", ".join(a.name for a in pou.actions)
            errors.append(
                f"POU '{pou.name}' has actions ({names}) — POU actions are not yet supported for {target.value}"
            )


def _check_startup_task(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """AB has no native startup task — would be silently mapped to periodic."""
    if target != Vendor.AB:
        return
    from plx.model.task import StartupTask

    for task in project.tasks:
        if isinstance(task, StartupTask):
            errors.append(f"Task '{task.name}' is a startup task — AB has no native startup task type")


def _check_multiple_gvls(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """AB supports only a single global variable list (controller tags)."""
    if target != Vendor.AB:
        return
    if len(project.global_variable_lists) > 1:
        names = ", ".join(g.name for g in project.global_variable_lists)
        errors.append(
            f"AB supports only a single global variable list (controller tags). "
            f"Project has {len(project.global_variable_lists)} GVLs: {names}. "
            f"Merge them into one before targeting AB."
        )


def _check_ab_unsupported_primitives(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """Reject CHAR, WCHAR, DATE, LDATE, TOD, LTOD, DT, LDT on AB."""
    if target != Vendor.AB:
        return

    # POU variables
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
            found = _type_contains_primitive(var.data_type, _AB_UNSUPPORTED_PRIMITIVES)
            if found is not None:
                errors.append(
                    f"Variable '{pou.name}.{var.name}' uses {found.value} — AB does not support {found.value}"
                )

    # Struct members
    from plx.model.types import StructType

    for dt in project.data_types:
        if isinstance(dt, StructType):
            for member in dt.members:
                found = _type_contains_primitive(member.data_type, _AB_UNSUPPORTED_PRIMITIVES)
                if found is not None:
                    errors.append(
                        f"Struct member '{dt.name}.{member.name}' uses {found.value} — "
                        f"AB does not support {found.value}"
                    )

    # GVL variables
    for gvl in project.global_variable_lists:
        for var in gvl.variables:
            found = _type_contains_primitive(var.data_type, _AB_UNSUPPORTED_PRIMITIVES)
            if found is not None:
                errors.append(
                    f"GVL variable '{gvl.name}.{var.name}' uses {found.value} — AB does not support {found.value}"
                )


def _check_ab_tp_timer(
    project: Project,
    target: Vendor,
    errors: list[str],
) -> None:
    """Reject TP (pulse timer) on AB — no native TP and no synthesis path."""
    if target != Vendor.AB:
        return
    fb_types = _collect_fb_types(project)
    if "TP" in fb_types:
        for pou_name in sorted(fb_types["TP"]):
            errors.append(
                f"POU '{pou_name}' uses TP (pulse timer) — AB does not support TP and there is no synthesis path"
            )


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
    _check_try_catch,
    _check_continue_statement,
    _check_repeat_statement,
    _check_wstring,
    _check_unsupported_data_types,
    _check_array_constraints,
    _check_multiple_gvls,
    _check_sfc_body,
    _check_pou_actions,
    _check_startup_task,
    _check_ab_unsupported_primitives,
    _check_ab_tp_timer,
]

# Lossy checks — blocked by default, allowed with allow_lossy=True.
# These represent transforms that produce valid vendor code but cannot
# be round-tripped back to the original source.
_LOSSY_CHECKS = [
    _check_ab_siemens_extends,
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
    project: Project,
    target: Vendor,
    errors: list[str],
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
            pou.interface.input_vars
            + pou.interface.output_vars
            + pou.interface.inout_vars
            + pou.interface.static_vars
            + pou.interface.temp_vars
            + pou.interface.constant_vars
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
                warnings.append(
                    PortabilityWarning(
                        category="fb_translation",
                        pou_name=pou_name,
                        message=vendor_msgs[target],
                        details={"fb_type": fb_type, "target": target.value},
                        round_trippable=fb_type not in _NON_ROUND_TRIPPABLE_FBS,
                    )
                )


# ---------------------------------------------------------------------------
# Math function translation warnings — data-driven
# ---------------------------------------------------------------------------

_MATH_TRANSLATION_WARNINGS: dict[str, dict[Vendor, str]] = {
    "EXP": {
        Vendor.AB: ("EXP() has no native AB equivalent. The raise pass will rewrite to EXPT(2.718..., x)."),
    },
    "CEIL": {
        Vendor.AB: ("CEIL() has no native AB equivalent. The raise pass will synthesize from TRN + conditional."),
    },
    "FLOOR": {
        Vendor.AB: ("FLOOR() has no native AB equivalent. The raise pass will synthesize from TRN + conditional."),
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
                warnings.append(
                    PortabilityWarning(
                        category="math_translation",
                        pou_name=pou_name,
                        message=vendor_msgs[target],
                        details={"function": func_name, "target": target.value},
                    )
                )


def _warn_ab_lossy_type_mappings(
    project: Project,
    target: Vendor,
    warnings: list[PortabilityWarning],
) -> None:
    """Warn when AB maps BYTE→SINT, WORD→INT, TIME→DINT, etc."""
    if target != Vendor.AB:
        return
    _lossy_primitives = frozenset(_AB_LOSSY_TYPE_MAP.keys())

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
            found = _type_contains_primitive(var.data_type, _lossy_primitives)
            if found is not None:
                warnings.append(
                    PortabilityWarning(
                        category="type_mapping",
                        pou_name=pou.name,
                        message=(
                            f"Variable '{var.name}' uses {found.value} which AB maps "
                            f"to {_AB_LOSSY_TYPE_MAP[found]}. This mapping is lossy."
                        ),
                        details={"type": found.value, "mapped_to": _AB_LOSSY_TYPE_MAP[found]},
                        round_trippable=False,
                    )
                )

    # GVL variables
    for gvl in project.global_variable_lists:
        for var in gvl.variables:
            found = _type_contains_primitive(var.data_type, _lossy_primitives)
            if found is not None:
                warnings.append(
                    PortabilityWarning(
                        category="type_mapping",
                        pou_name=gvl.name,
                        message=(
                            f"GVL variable '{var.name}' uses {found.value} which AB maps "
                            f"to {_AB_LOSSY_TYPE_MAP[found]}. This mapping is lossy."
                        ),
                        details={"type": found.value, "mapped_to": _AB_LOSSY_TYPE_MAP[found]},
                        round_trippable=False,
                    )
                )


def _warn_ab_temp_var_promotion(
    project: Project,
    target: Vendor,
    warnings: list[PortabilityWarning],
) -> None:
    """Warn when a POU has temp vars — AB promotes them to static."""
    if target != Vendor.AB:
        return
    for pou in project.pous:
        if pou.interface.temp_vars:
            names = ", ".join(v.name for v in pou.interface.temp_vars)
            warnings.append(
                PortabilityWarning(
                    category="temp_var_promotion",
                    pou_name=pou.name,
                    message=(
                        f"POU '{pou.name}' has VAR_TEMP variables ({names}) — "
                        f"AB does not support VAR_TEMP; these will be promoted to static variables"
                    ),
                    round_trippable=False,
                )
            )


# ---------------------------------------------------------------------------
# Warning registry — add new warnings here
# ---------------------------------------------------------------------------

_WARNINGS = [
    _check_fb_translation,
    _check_math_function_portability,
    _warn_ab_lossy_type_mappings,
    _warn_ab_temp_var_promotion,
]


# ---------------------------------------------------------------------------
# Extension registration — allows private vendor repos to add checks
# ---------------------------------------------------------------------------

_BUILTIN_CHECK_COUNT = len(_CHECKS)
_BUILTIN_LOSSY_CHECK_COUNT = len(_LOSSY_CHECKS)
_BUILTIN_LIBRARY_CHECK_COUNT = len(_LIBRARY_CHECKS)
_BUILTIN_WARNING_COUNT = len(_WARNINGS)
_BUILTIN_FB_WARNINGS: dict[str, dict[Vendor, str]] = {k: dict(v) for k, v in _FB_TRANSLATION_WARNINGS.items()}


def register_vendor_check(check_fn) -> None:
    """Register an additional vendor validation check.

    Parameters
    ----------
    check_fn : Callable[[Project, Vendor, list[str]], None]
        Validation function that inspects the project and appends
        human-readable error strings to *errors* for unsupported features.
    """
    _CHECKS.append(check_fn)



def register_vendor_warning(warning_fn) -> None:
    """Register an additional vendor portability warning.

    Parameters
    ----------
    warning_fn : Callable[[Project, Vendor, list[PortabilityWarning]], None]
        Warning function that inspects the project and appends
        ``PortabilityWarning`` instances to *warnings* for features
        that compile but may differ in semantics or fidelity on the
        target vendor.
    """
    _WARNINGS.append(warning_fn)


def register_fb_translation_warning(fb_type: str, vendor: Vendor, message: str) -> None:
    """Register an FB translation warning for a specific vendor."""
    _FB_TRANSLATION_WARNINGS.setdefault(fb_type, {})[vendor] = message


def _clear_vendor_extensions() -> None:
    """Remove all registered extensions, restoring built-in checks only. For tests."""
    del _CHECKS[_BUILTIN_CHECK_COUNT:]
    del _LOSSY_CHECKS[_BUILTIN_LOSSY_CHECK_COUNT:]
    del _LIBRARY_CHECKS[_BUILTIN_LIBRARY_CHECK_COUNT:]
    del _WARNINGS[_BUILTIN_WARNING_COUNT:]
    _FB_TRANSLATION_WARNINGS.clear()
    _FB_TRANSLATION_WARNINGS.update({k: dict(v) for k, v in _BUILTIN_FB_WARNINGS.items()})

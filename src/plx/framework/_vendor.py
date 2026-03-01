"""Vendor target validation for the plx framework.

When compiling a project with ``target=Vendor.AB`` (or SIEMENS), the
validation pass checks that the IR only uses features supported by that
vendor.  This catches Beckhoff-specific constructs early — before the
raise pass or exporter sees them.

Beckhoff follows IEC 61131-3 most closely and supports all current IR
features.  Allen Bradley and Siemens lack OOP (methods, properties,
interfaces) and pointer/reference types.  Enums are universal — the
raise pass for AB/Siemens will lower ``EnumType`` to DINT constants.

Usage::

    from plx.framework import project, Vendor

    ir = project("MyProject", pous=[Main]).compile(target=Vendor.AB)
    # → VendorValidationError if Main uses @method, etc.
"""

from __future__ import annotations

from enum import Enum

from plx.model.project import Project

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

def validate_target(project: Project, target: Vendor) -> None:
    """Validate that *project* only uses features supported by *target*.

    Called automatically by ``PlxProject.compile(target=...)`` when a
    target is specified.  Collects all issues and raises a single
    ``VendorValidationError`` listing every problem.

    To add a new vendor-specific check, append a function to
    ``_CHECKS``.  Each check takes ``(project, target, errors)``
    and appends human-readable strings to *errors*.
    """
    if target == Vendor.BECKHOFF:
        return  # Beckhoff supports all current IR features

    errors: list[str] = []
    for check in _CHECKS:
        check(project, target, errors)

    if errors:
        raise VendorValidationError(target, errors)


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

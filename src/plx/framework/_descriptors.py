"""Variable descriptors for the plx framework.

Users declare variables on their POU classes using annotation wrappers
and ``Field()`` for metadata::

    class MyFB:
        sensor: Input[bool]
        speed: Output[float] = Field(initial=60.0, retain=True)
        accumulator: float = 0.0      # bare annotation = static
        scratch: Temp[int]
        PI: Constant[float] = 3.14
        timer: TON
"""

from __future__ import annotations

from enum import Enum
import sys
from typing import Annotated, ForwardRef, Generic, TypeVar, get_origin, get_args

from plx.model.types import PrimitiveType, TypeRef
from plx.model.variables import Variable

from plx.model.types import NamedTypeRef

from datetime import timedelta

from ._errors import DeclarationError
from ._types import timedelta_to_iec, _resolve_type_ref


_T = TypeVar("_T")


class Input(Generic[_T]):
    """Annotation marker for input variables: ``speed: Input[float]``"""
    pass


class Output(Generic[_T]):
    """Annotation marker for output variables: ``running: Output[bool]``"""
    pass


class InOut(Generic[_T]):
    """Annotation marker for in-out variables: ``ref: InOut[float]``"""
    pass


class Static(Generic[_T]):
    """Annotation marker for explicit static variables: ``state: Static[int]``"""
    pass


class Temp(Generic[_T]):
    """Annotation marker for temp variables: ``scratch: Temp[int]``"""
    pass


class Constant(Generic[_T]):
    """Annotation marker for constant variables: ``PI: Constant[float] = 3.14``"""
    pass


class External(Generic[_T]):
    """Annotation marker for external variables: ``ext: External[int]``"""
    pass


class VarDirection(str, Enum):
    """Direction of a POU variable."""

    INPUT = "input"
    OUTPUT = "output"
    STATIC = "static"
    INOUT = "inout"
    TEMP = "temp"
    CONSTANT = "constant"
    EXTERNAL = "external"


_WRAPPER_DIRECTIONS: dict[type, VarDirection] = {
    Input: VarDirection.INPUT,
    Output: VarDirection.OUTPUT,
    InOut: VarDirection.INOUT,
    Static: VarDirection.STATIC,
    Temp: VarDirection.TEMP,
    Constant: VarDirection.CONSTANT,
    External: VarDirection.EXTERNAL,
}


class VarDescriptor:
    """Marker object that records variable metadata.

    Used internally as an intermediate representation during
    ``_collect_descriptors()``.
    """

    __slots__ = ("direction", "data_type", "initial_value", "description",
                 "retain", "persistent", "constant", "address")

    def __init__(
        self,
        direction: VarDirection,
        data_type: TypeRef,
        initial_value: str | None = None,
        description: str = "",
        retain: bool = False,
        persistent: bool = False,
        constant: bool = False,
        address: str | None = None,
    ) -> None:
        self.direction = direction
        self.data_type = data_type
        self.initial_value = initial_value
        self.description = description
        self.retain = retain
        self.persistent = persistent
        self.constant = constant
        self.address = address


# ---------------------------------------------------------------------------
# FieldDescriptor + Field() function
# ---------------------------------------------------------------------------

class FieldDescriptor:
    """Stores metadata for a variable declared with ``Field()``.

    Not a direction or type — those come from the annotation wrapper.
    """

    __slots__ = (
        "initial_value",
        "description",
        "retain",
        "persistent",
        "constant",
        "address",
    )

    def __init__(
        self,
        *,
        initial_value: str | None = None,
        description: str = "",
        retain: bool = False,
        persistent: bool = False,
        constant: bool = False,
        address: str | None = None,
    ) -> None:
        self.initial_value = initial_value
        self.description = description
        self.retain = retain
        self.persistent = persistent
        self.constant = constant
        self.address = address


def Field(
    *,
    initial: object = None,
    description: str = "",
    retain: bool = False,
    persistent: bool = False,
    constant: bool = False,
    address: str | None = None,
) -> FieldDescriptor:
    """Declare variable metadata via annotation syntax.

    Example::

        sensor: Input[bool] = Field(address="%I0.0", description="Proximity")
        speed: Output[float] = Field(initial=60.0, retain=True)
        state: Static[int] = Field(retain=True)
    """
    return FieldDescriptor(
        initial_value=_format_initial(initial),
        description=description,
        retain=retain,
        persistent=persistent,
        constant=constant,
        address=address,
    )


def _format_initial(value: object) -> str | None:
    """Convert a Python value to an IEC 61131-3 literal string.

    Returns ``None`` if the value is ``None``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, timedelta):
        return timedelta_to_iec(value)
    if isinstance(value, str):
        return value
    raise DeclarationError(
        f"Cannot convert {type(value).__name__} to IEC literal"
    )


# ---------------------------------------------------------------------------
# Field validation per direction
# ---------------------------------------------------------------------------

def _validate_field_for_direction(
    field: FieldDescriptor,
    direction: VarDirection,
    attr_name: str,
) -> None:
    """Validate that Field() kwargs are legal for the given direction."""
    if direction == VarDirection.TEMP:
        if field.retain:
            raise DeclarationError(f"Temp variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise DeclarationError(f"Temp variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise DeclarationError(f"Temp variable '{attr_name}' cannot use address")
        if field.description:
            raise DeclarationError(f"Temp variable '{attr_name}' cannot use description")
    elif direction == VarDirection.INOUT:
        if field.initial_value is not None:
            raise DeclarationError(f"InOut variable '{attr_name}' cannot use initial")
        if field.retain:
            raise DeclarationError(f"InOut variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise DeclarationError(f"InOut variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise DeclarationError(f"InOut variable '{attr_name}' cannot use address")
    elif direction == VarDirection.EXTERNAL:
        if field.initial_value is not None:
            raise DeclarationError(f"External variable '{attr_name}' cannot use initial")
        if field.retain:
            raise DeclarationError(f"External variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise DeclarationError(f"External variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise DeclarationError(f"External variable '{attr_name}' cannot use address")
    elif direction == VarDirection.CONSTANT:
        if field.retain:
            raise DeclarationError(f"Constant variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise DeclarationError(f"Constant variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise DeclarationError(f"Constant variable '{attr_name}' cannot use address")


# ---------------------------------------------------------------------------
# Annotated / FieldDescriptor helpers
# ---------------------------------------------------------------------------

def _unwrap_annotated(
    type_hint: object,
    attr_name: str,
) -> tuple[object, FieldDescriptor | None]:
    """Unwrap ``Annotated[T, Field(...)]``, returning the inner type and field.

    If *type_hint* is not ``Annotated``, returns ``(type_hint, None)``.
    Raises ``TypeError`` if multiple ``Field()`` instances are found.
    """
    if get_origin(type_hint) is not Annotated:
        return type_hint, None
    ann_args = get_args(type_hint)
    inner = ann_args[0]
    fields_found = [a for a in ann_args[1:] if isinstance(a, FieldDescriptor)]
    if len(fields_found) > 1:
        raise DeclarationError(
            f"Variable '{attr_name}' has multiple Field() in Annotated — only one allowed"
        )
    return inner, (fields_found[0] if fields_found else None)


def _field_to_variable(
    name: str,
    data_type: object,
    field: FieldDescriptor,
    default: object = None,
    *,
    is_constant: bool = False,
) -> Variable:
    """Build a ``Variable`` from a ``FieldDescriptor``, merging a class default.

    If *field.initial_value* is ``None`` and *default* is a plain literal,
    the default supplies the initial value.
    """
    if field.initial_value is None and default is not None and not isinstance(default, FieldDescriptor):
        if isinstance(default, (bool, int, float, str, timedelta)):
            field = FieldDescriptor(
                initial_value=_format_initial(default),
                description=field.description,
                retain=field.retain,
                persistent=field.persistent,
                constant=field.constant,
                address=field.address,
            )
    return Variable(
        name=name,
        data_type=data_type,
        initial_value=field.initial_value,
        description=field.description,
        retain=field.retain,
        persistent=field.persistent,
        constant=is_constant or field.constant,
        address=field.address,
    )


# ---------------------------------------------------------------------------
# MRO override helper
# ---------------------------------------------------------------------------

def _mro_upsert(
    collected: list[tuple],
    seen: set[str],
    name: str,
    entry: tuple,
) -> None:
    """Insert or replace an entry in an MRO-ordered collected list (in-place).

    If *name* already exists, the earlier entry is removed so the new one
    takes precedence (child overrides parent).
    """
    if name in seen:
        collected[:] = [item for item in collected if item[0] != name]
    seen.add(name)
    collected.append(entry)


# ---------------------------------------------------------------------------
# Per-attribute resolution helpers
# ---------------------------------------------------------------------------

def _unwrap_forward_ref(inner_type: object, declaring_cls: type) -> object:
    """Resolve a ForwardRef using the declaring class's module globals."""
    if not isinstance(inner_type, ForwardRef):
        return inner_type
    mod = sys.modules.get(declaring_cls.__module__)
    globalns = getattr(mod, '__dict__', {}) if mod else {}
    try:
        return eval(inner_type.__forward_arg__, globalns)
    except Exception:
        return inner_type.__forward_arg__


def _determine_direction(type_hint: object) -> tuple[VarDirection, object]:
    """Determine variable direction from annotation wrapper.

    Returns (direction, inner_type). Bare annotations return (STATIC, type_hint).
    """
    origin = get_origin(type_hint)
    direction = _WRAPPER_DIRECTIONS.get(origin)
    if direction is not None:
        return direction, get_args(type_hint)[0]
    return VarDirection.STATIC, type_hint


def _resolve_declaration(
    attr_name: str,
    type_hint: object,
    default: object,
    declaring_cls: type,
) -> VarDescriptor | None:
    """Resolve a single attribute's annotation + default into a VarDescriptor.

    Returns None if the attribute should be skipped (unresolvable type,
    non-value default, etc.).
    """
    type_hint, annotated_field = _unwrap_annotated(type_hint, attr_name)
    direction, inner_type = _determine_direction(type_hint)
    inner_type = _unwrap_forward_ref(inner_type, declaring_cls)

    try:
        data_type = _resolve_type_ref(inner_type)
    except TypeError:
        return None

    # Resolve field descriptor from Annotated[T, Field()] or = Field() default
    field = annotated_field
    if field is None and isinstance(default, FieldDescriptor):
        field = default
        default = None  # FieldDescriptor IS the default, not a value

    if field is not None:
        _validate_field_for_direction(field, direction, attr_name)
        is_constant = direction == VarDirection.CONSTANT or field.constant
        var = _field_to_variable(attr_name, data_type, field, default, is_constant=is_constant)
        if direction == VarDirection.CONSTANT and var.initial_value is None:
            raise DeclarationError(
                f"Constant variable '{attr_name}' requires an initial value"
            )
        return VarDescriptor(
            direction=direction,
            data_type=var.data_type,
            initial_value=var.initial_value,
            description=var.description,
            retain=var.retain,
            persistent=var.persistent,
            constant=var.constant,
            address=var.address,
        )

    # No field — skip non-value defaults (step objects, etc.)
    if default is not None and not isinstance(default, (bool, int, float, str, timedelta)):
        return None

    initial_value = _format_initial(default)
    is_constant = direction == VarDirection.CONSTANT
    if is_constant and initial_value is None:
        raise DeclarationError(
            f"Constant variable '{attr_name}' requires an initial value"
        )

    return VarDescriptor(
        direction=direction,
        data_type=data_type,
        initial_value=initial_value,
        constant=is_constant,
    )


# ---------------------------------------------------------------------------
# Collection helper
# ---------------------------------------------------------------------------

def _collect_descriptors(cls: type, *, own_only: bool = False) -> dict[str, list[Variable]]:
    """Find variable declarations on *cls* and return
    IR ``Variable`` nodes grouped by direction.

    When *own_only* is False (default), walks the MRO so that a
    derived class inherits its parent's descriptors.  Parent
    descriptors appear first, then the child's.  If the child
    redefines a name that the parent declared, the child's version
    wins (override).

    Returns a dict with keys: ``"input"``, ``"output"``, ``"inout"``,
    ``"static"``, ``"temp"``, ``"constant"``, ``"external"``
    — each mapping to a list of ``Variable``.
    """
    groups: dict[str, list[Variable]] = {
        "input": [],
        "output": [],
        "inout": [],
        "static": [],
        "temp": [],
        "constant": [],
        "external": [],
    }

    if own_only:
        sources = [cls.__dict__]
    else:
        # Walk MRO in reverse so parent attrs come first and child
        # overrides replace them via the ``seen`` set.
        sources = [
            base.__dict__
            for base in reversed(cls.__mro__)
            if base is not object
        ]

    seen: set[str] = set()
    collected: list[tuple[str, VarDescriptor]] = []

    from ._protocols import CompiledPOU

    # First pass: bare FB class assignments (valve_a = ValveCtrl)
    for ns in sources:
        for attr_name, value in ns.items():
            if isinstance(value, type) and isinstance(value, CompiledPOU):
                # Bare FB class assignment: valve_a = ValveCtrl
                desc = VarDescriptor(
                    direction=VarDirection.STATIC,
                    data_type=NamedTypeRef(name=value.__name__),
                )
                _mro_upsert(collected, seen, attr_name, (attr_name, desc))

    # Track names from first pass
    fb_names = set(seen)

    # Second pass: annotation-based declarations
    for base in reversed(cls.__mro__):
        if base is object:
            continue
        for attr_name, type_hint in base.__dict__.get("__annotations__", {}).items():
            if attr_name in fb_names:
                continue
            default = base.__dict__.get(attr_name)
            desc = _resolve_declaration(attr_name, type_hint, default, base)
            if desc is not None:
                _mro_upsert(collected, seen, attr_name, (attr_name, desc))

    for attr_name, desc in collected:
        var = Variable(
            name=attr_name,
            data_type=desc.data_type,
            initial_value=desc.initial_value,
            description=desc.description,
            retain=desc.retain,
            persistent=desc.persistent,
            constant=desc.constant,
            address=desc.address,
        )
        groups[desc.direction].append(var)

    return groups


# ---------------------------------------------------------------------------
# IEC 61131-3 standard function block types
# ---------------------------------------------------------------------------
# String constants so users can write:  timer: TON
# Resolves via _resolve_type_ref("TON") → NamedTypeRef("TON")
# Canonical set lives in _constants.py.

from ._constants import STANDARD_FB_TYPES

TON = "TON"
TOF = "TOF"
TP = "TP"
RTO = "RTO"
R_TRIG = "R_TRIG"
F_TRIG = "F_TRIG"
CTU = "CTU"
CTD = "CTD"
CTUD = "CTUD"
SR = "SR"
RS = "RS"

assert {TON, TOF, TP, RTO, R_TRIG, F_TRIG, CTU, CTD, CTUD, SR, RS} == STANDARD_FB_TYPES

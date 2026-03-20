"""Variable descriptors for the plx framework.

Users declare variables on their POU classes using annotation wrappers
and ``Field()`` for metadata::

    class MyFB:
        sensor: Input[bool]
        speed: Output[float] = Field(initial=60.0, retain=True)
        accumulator: float = 0.0      # bare annotation = static
        scratch: Temp[int]
        PI: float = Field(initial=3.14, constant=True)
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
    External: VarDirection.EXTERNAL,
}


class VarDescriptor:
    """Marker object that records variable metadata.

    Used internally as an intermediate representation during
    ``_collect_descriptors()``.
    """

    __slots__ = ("direction", "data_type", "initial_value", "description",
                 "retain", "persistent", "constant", "hardware", "external")

    def __init__(
        self,
        direction: VarDirection,
        data_type: TypeRef,
        initial_value: str | None = None,
        description: str = "",
        retain: bool = False,
        persistent: bool = False,
        constant: bool = False,
        hardware: str | None = None,
        external: str | None = None,
    ) -> None:
        self.direction = direction
        self.data_type = data_type
        self.initial_value = initial_value
        self.description = description
        self.retain = retain
        self.persistent = persistent
        self.constant = constant
        self.hardware = hardware
        self.external = external


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
        "hardware",
        "external",
    )

    def __init__(
        self,
        *,
        initial_value: str | None = None,
        description: str = "",
        retain: bool = False,
        persistent: bool = False,
        constant: bool = False,
        hardware: str | None = None,
        external: bool | str | None = None,
    ) -> None:
        self.initial_value = initial_value
        self.description = description
        self.retain = retain
        self.persistent = persistent
        self.constant = constant
        self.hardware = _validate_hardware(hardware)
        self.external = _normalize_external(external)


_VALID_HARDWARE = {"input", "output", "memory"}
_VALID_EXTERNAL = {"read", "readwrite"}


def _validate_hardware(value: str | None) -> str | None:
    """Validate hardware value at construction time."""
    if value is None:
        return None
    if value in _VALID_HARDWARE:
        return value
    raise DeclarationError(
        f"Invalid hardware value {value!r} — expected 'input', 'output', or 'memory'"
    )


def _normalize_external(value: bool | str | None) -> str | None:
    """Normalize external access value: True → "readwrite", False/None → None."""
    if value is True:
        return "readwrite"
    if value is False or value is None:
        return None
    if value in _VALID_EXTERNAL:
        return value
    raise DeclarationError(
        f"Invalid external value {value!r} — expected True, False, 'read', or 'readwrite'"
    )


def Field(
    *,
    initial: object = None,
    description: str = "",
    retain: bool = False,
    persistent: bool = False,
    constant: bool = False,
    hardware: str | None = None,
    external: bool | str | None = None,
) -> FieldDescriptor:
    """Declare variable metadata via annotation syntax.

    Attach to any variable declaration to specify initial values,
    documentation, retention behavior, hardware binding, or external
    access. Can be used as a default value or inside ``Annotated``.

    Parameters
    ----------
    initial : object, optional
        Initial value for the variable. Accepts Python literals (``bool``,
        ``int``, ``float``, ``str``), ``timedelta`` for time literals, or
        a ``dict`` for structured FB/struct initialization
        (e.g. ``{"PT": timedelta(seconds=5)}``).
    description : str, optional
        Human-readable description of the variable. Exported as a comment
        or documentation string in vendor formats.
    retain : bool, optional
        Mark the variable as retentive (preserves value across power
        cycles). Not valid on ``Temp`` or ``InOut`` variables.
    persistent : bool, optional
        Mark the variable as persistent (saved to non-volatile storage).
        Not valid on ``Temp`` or ``InOut`` variables.
    constant : bool, optional
        Mark the variable as constant. Requires ``initial`` to be set.
        Not valid with ``retain``, ``persistent``, ``hardware``, or
        ``external``.
    hardware : str, optional
        Hardware binding direction. Valid values: ``"input"``,
        ``"output"``, ``"memory"``. Maps to IEC ``%I``, ``%Q``, ``%M``
        address prefixes respectively.
    external : bool or str, optional
        External access level for OPC UA / HMI visibility. ``True`` is
        shorthand for ``"readwrite"``. Valid string values: ``"read"``,
        ``"readwrite"``.

    Returns
    -------
    FieldDescriptor
        A metadata descriptor attached to the variable declaration.

    Examples
    --------
    ::

        sensor: Input[bool] = Field(description="Proximity")
        speed: Output[float] = Field(initial=60.0, retain=True)
        state: Static[int] = Field(retain=True)
        motor: Output[bool] = Field(hardware="output", external=True)
    """
    return FieldDescriptor(
        initial_value=_format_initial(initial),
        description=description,
        retain=retain,
        persistent=persistent,
        constant=constant,
        hardware=hardware,
        external=external,
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
    if isinstance(value, dict):
        return _dict_to_iec_init(value)
    raise DeclarationError(
        f"Cannot convert {type(value).__name__} to IEC literal"
    )


def _dict_to_iec_init(d: dict) -> str:
    """Convert a Python dict to IEC FB/struct init: ``(Name := 'val', Flag := TRUE)``."""
    parts: list[str] = []
    for k, v in d.items():
        parts.append(f"{k} := {_format_init_param(v)}")
    return f"({', '.join(parts)})"


def _format_init_param(value: object) -> str:
    """Format a single FB init parameter value to IEC literal.

    Unlike ``_format_initial``, string values are wrapped in IEC single quotes
    since they represent parameter values inside ``(Param := 'value')`` syntax.
    """
    if isinstance(value, str):
        # Already an IEC literal (time, hex, etc.) — pass through
        if (value.startswith("T#") or value.startswith("16#") or
                value.startswith("8#") or value.startswith("2#") or
                value.startswith("(") or value == "TRUE" or value == "FALSE"):
            return value
        # Wrap plain strings in IEC single quotes
        return f"'{value}'"
    return _format_initial(value)


# ---------------------------------------------------------------------------
# Field validation per direction
# ---------------------------------------------------------------------------

def _validate_field_for_direction(
    field: FieldDescriptor,
    direction: VarDirection,
    attr_name: str,
    class_name: str | None = None,
) -> None:
    """Validate that Field() kwargs are legal for the given direction."""
    def _err(msg: str) -> DeclarationError:
        return DeclarationError(msg, class_name=class_name)

    # hardware/external not allowed on Temp or constant fields
    is_constant = field.constant or direction == VarDirection.CONSTANT
    if direction == VarDirection.TEMP or is_constant:
        label = "Constant" if is_constant else "Temp"
        if field.hardware is not None:
            raise _err(f"{label} variable '{attr_name}' cannot use hardware")
        if field.external is not None:
            raise _err(f"{label} variable '{attr_name}' cannot use external")

    if direction == VarDirection.TEMP:
        if field.retain:
            raise _err(f"Temp variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise _err(f"Temp variable '{attr_name}' cannot use persistent")
        if field.description:
            raise _err(f"Temp variable '{attr_name}' cannot use description")
    elif direction == VarDirection.INOUT:
        if field.initial_value is not None:
            raise _err(f"InOut variable '{attr_name}' cannot use initial")
        if field.retain:
            raise _err(f"InOut variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise _err(f"InOut variable '{attr_name}' cannot use persistent")
    elif direction == VarDirection.EXTERNAL:
        if field.initial_value is not None:
            raise _err(f"External variable '{attr_name}' cannot use initial")
        if field.retain:
            raise _err(f"External variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise _err(f"External variable '{attr_name}' cannot use persistent")

    # Constant-specific validation (whether from VarDirection.CONSTANT or field.constant)
    if is_constant:
        if field.retain:
            raise _err(f"Constant variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise _err(f"Constant variable '{attr_name}' cannot use persistent")


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
        if isinstance(default, (bool, int, float, str, timedelta, dict)):
            field = FieldDescriptor(
                initial_value=_format_initial(default),
                description=field.description,
                retain=field.retain,
                persistent=field.persistent,
                constant=field.constant,
                hardware=field.hardware,
                external=field.external,
            )
    metadata: dict[str, object] = {}
    if field.hardware is not None:
        metadata["hardware"] = field.hardware
    if field.external is not None:
        metadata["external"] = field.external
    return Variable(
        name=name,
        data_type=data_type,
        initial_value=field.initial_value,
        description=field.description,
        retain=field.retain,
        persistent=field.persistent,
        constant=is_constant or field.constant,
        metadata=metadata,
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
    except (NameError, AttributeError):
        # Forward ref can't be resolved — the name isn't in scope yet.
        # Fall back to the raw string so _resolve_type_ref() can handle
        # it as a NamedTypeRef.
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
        import warnings
        warnings.warn(
            f"plx: variable '{attr_name}' on {declaring_cls.__name__} has "
            f"unrecognizable type {inner_type!r} — skipped",
            stacklevel=4,
        )
        return None

    # Resolve field descriptor from Annotated[T, Field()] or = Field() default
    field = annotated_field
    if field is None and isinstance(default, FieldDescriptor):
        field = default
        default = None  # FieldDescriptor IS the default, not a value

    if field is not None:
        _validate_field_for_direction(field, direction, attr_name, class_name=declaring_cls.__name__)
        is_constant = direction == VarDirection.CONSTANT or field.constant
        var = _field_to_variable(attr_name, data_type, field, default, is_constant=is_constant)
        if is_constant and var.initial_value is None:
            raise DeclarationError(
                f"Constant variable '{attr_name}' requires an initial value",
                class_name=declaring_cls.__name__,
            )
        return VarDescriptor(
            direction=direction,
            data_type=var.data_type,
            initial_value=var.initial_value,
            description=var.description,
            retain=var.retain,
            persistent=var.persistent,
            constant=var.constant,
            hardware=field.hardware,
            external=field.external,
        )

    # No field — skip non-value defaults (step objects, etc.)
    if default is not None and not isinstance(default, (bool, int, float, str, timedelta, dict)):
        return None

    initial_value = _format_initial(default)
    is_constant = direction == VarDirection.CONSTANT
    if is_constant and initial_value is None:
        raise DeclarationError(
            f"Constant variable '{attr_name}' requires an initial value",
            class_name=declaring_cls.__name__,
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
    from ._library import LibraryType

    for ns in sources:
        for attr_name, value in ns.items():
            if isinstance(value, type) and isinstance(value, CompiledPOU):
                # Bare FB class assignment: valve_a = ValveCtrl
                desc = VarDescriptor(
                    direction=VarDirection.STATIC,
                    data_type=NamedTypeRef(name=value.__name__),
                )
                _mro_upsert(collected, seen, attr_name, (attr_name, desc))
            elif (
                isinstance(value, type)
                and issubclass(value, LibraryType)
                and "_abstract" not in value.__dict__
            ):
                # Bare library type assignment: power = MC_Power
                desc = VarDescriptor(
                    direction=VarDirection.STATIC,
                    data_type=NamedTypeRef(name=value._type_name),
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
        metadata: dict[str, object] = {}
        if desc.hardware is not None:
            metadata["hardware"] = desc.hardware
        if desc.external is not None:
            metadata["external"] = desc.external
        var = Variable(
            name=attr_name,
            data_type=desc.data_type,
            initial_value=desc.initial_value,
            description=desc.description,
            retain=desc.retain,
            persistent=desc.persistent,
            constant=desc.constant,
            metadata=metadata,
        )
        # Route static + constant=True to the "constant" group
        group = desc.direction
        if desc.direction == VarDirection.STATIC and desc.constant:
            group = VarDirection.CONSTANT
        groups[group].append(var)

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

# Lowercase aliases — Pythonic names for standard FB types
ton = TON
tof = TOF
tp = TP
rto = RTO
r_trig = R_TRIG
f_trig = F_TRIG
ctu = CTU
ctd = CTD
ctud = CTUD
sr = SR
rs = RS

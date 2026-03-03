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

from ._types import TimeLiteral, LTimeLiteral, _resolve_type_ref


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
    if isinstance(value, TimeLiteral):
        return value.to_iec()
    if isinstance(value, LTimeLiteral):
        return value.to_iec()
    if isinstance(value, str):
        return value
    raise TypeError(
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
            raise TypeError(f"Temp variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise TypeError(f"Temp variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise TypeError(f"Temp variable '{attr_name}' cannot use address")
        if field.description:
            raise TypeError(f"Temp variable '{attr_name}' cannot use description")
    elif direction == VarDirection.INOUT:
        if field.initial_value is not None:
            raise TypeError(f"InOut variable '{attr_name}' cannot use initial")
        if field.retain:
            raise TypeError(f"InOut variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise TypeError(f"InOut variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise TypeError(f"InOut variable '{attr_name}' cannot use address")
    elif direction == VarDirection.EXTERNAL:
        if field.initial_value is not None:
            raise TypeError(f"External variable '{attr_name}' cannot use initial")
        if field.retain:
            raise TypeError(f"External variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise TypeError(f"External variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise TypeError(f"External variable '{attr_name}' cannot use address")
    elif direction == VarDirection.CONSTANT:
        if field.retain:
            raise TypeError(f"Constant variable '{attr_name}' cannot use retain")
        if field.persistent:
            raise TypeError(f"Constant variable '{attr_name}' cannot use persistent")
        if field.address is not None:
            raise TypeError(f"Constant variable '{attr_name}' cannot use address")


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
                if attr_name in seen:
                    collected = [(n, v) for n, v in collected if n != attr_name]
                seen.add(attr_name)
                collected.append((attr_name, desc))

    # Track names from first pass
    descriptor_names = set(seen)

    # Direction dispatch table for annotation wrappers
    _WRAPPER_DIRECTIONS = {
        Input: VarDirection.INPUT,
        Output: VarDirection.OUTPUT,
        InOut: VarDirection.INOUT,
        Static: VarDirection.STATIC,
        Temp: VarDirection.TEMP,
        Constant: VarDirection.CONSTANT,
        External: VarDirection.EXTERNAL,
    }

    # Second pass: annotation-based vars
    for base in reversed(cls.__mro__):
        if base is object:
            continue
        base_annotations = base.__dict__.get("__annotations__", {})
        for attr_name, type_hint in base_annotations.items():
            if attr_name in descriptor_names:
                continue  # first-pass assignment takes precedence

            # Unwrap Annotated[X, Field(...), ...] if present
            annotated_field: FieldDescriptor | None = None
            if get_origin(type_hint) is Annotated:
                ann_args = get_args(type_hint)
                type_hint = ann_args[0]
                # Extract FieldDescriptor(s) from metadata
                fields_found = [a for a in ann_args[1:] if isinstance(a, FieldDescriptor)]
                if len(fields_found) > 1:
                    raise TypeError(
                        f"Variable '{attr_name}' has multiple Field() in Annotated — only one allowed"
                    )
                if fields_found:
                    annotated_field = fields_found[0]

            # Determine direction from annotation wrapper
            origin = get_origin(type_hint)
            direction = _WRAPPER_DIRECTIONS.get(origin)
            if direction is not None:
                inner_type = get_args(type_hint)[0]
                # Unwrap ForwardRef (happens when Generic is subscripted
                # with non-type values like PrimitiveType.BOOL)
                if isinstance(inner_type, ForwardRef):
                    mod = sys.modules.get(cls.__module__)
                    globalns = getattr(mod, '__dict__', {}) if mod else {}
                    try:
                        inner_type = eval(inner_type.__forward_arg__, globalns)
                    except Exception:
                        inner_type = inner_type.__forward_arg__
            else:
                # Bare annotation = static var
                direction = VarDirection.STATIC
                inner_type = type_hint

            # Skip non-resolvable annotations (e.g., step() objects)
            try:
                data_type = _resolve_type_ref(inner_type)
            except TypeError:
                continue

            default = base.__dict__.get(attr_name)

            # Merge Annotated Field with class default:
            # If Annotated provides a Field, use it as the field descriptor.
            # A plain class default (not FieldDescriptor) supplies the initial
            # value when Field(initial=...) is not set.
            if annotated_field is not None:
                field = annotated_field
                # If class default is a plain value (not FieldDescriptor),
                # use it as initial when Field doesn't specify one
                if field.initial_value is None and default is not None and not isinstance(default, FieldDescriptor):
                    if isinstance(default, (bool, int, float, str, TimeLiteral, LTimeLiteral)):
                        field = FieldDescriptor(
                            initial_value=_format_initial(default),
                            description=field.description,
                            retain=field.retain,
                            persistent=field.persistent,
                            constant=field.constant,
                            address=field.address,
                        )
                _validate_field_for_direction(field, direction, attr_name)
                is_constant = direction == VarDirection.CONSTANT or field.constant
                if direction == VarDirection.CONSTANT and field.initial_value is None:
                    raise TypeError(
                        f"Constant variable '{attr_name}' requires an initial value"
                    )
                if attr_name in seen:
                    collected = [(n, v) for n, v in collected if n != attr_name]
                seen.add(attr_name)
                collected.append((attr_name, VarDescriptor(
                    direction=direction,
                    data_type=data_type,
                    initial_value=field.initial_value,
                    description=field.description,
                    retain=field.retain,
                    persistent=field.persistent,
                    constant=is_constant,
                    address=field.address,
                )))
                continue

            # Handle FieldDescriptor defaults (= Field(...) syntax)
            if isinstance(default, FieldDescriptor):
                _validate_field_for_direction(default, direction, attr_name)
                # For Constant, auto-set constant=True
                is_constant = direction == VarDirection.CONSTANT or default.constant
                if direction == VarDirection.CONSTANT and default.initial_value is None:
                    raise TypeError(
                        f"Constant variable '{attr_name}' requires an initial value"
                    )
                if attr_name in seen:
                    collected = [(n, v) for n, v in collected if n != attr_name]
                seen.add(attr_name)
                collected.append((attr_name, VarDescriptor(
                    direction=direction,
                    data_type=data_type,
                    initial_value=default.initial_value,
                    description=default.description,
                    retain=default.retain,
                    persistent=default.persistent,
                    constant=is_constant,
                    address=default.address,
                )))
                continue

            # Skip if default is a non-value object (step, transition, etc.)
            if default is not None and not isinstance(default, (bool, int, float, str, TimeLiteral, LTimeLiteral)):
                continue

            initial_value = _format_initial(default)

            # For Constant wrapper, auto-set constant=True and require initial
            is_constant = direction == VarDirection.CONSTANT
            if is_constant and initial_value is None:
                raise TypeError(
                    f"Constant variable '{attr_name}' requires an initial value"
                )

            if attr_name in seen:
                # Child overrides parent annotation — remove earlier entry
                collected = [(n, v) for n, v in collected if n != attr_name]
            seen.add(attr_name)
            collected.append((attr_name, VarDescriptor(
                direction=direction,
                data_type=data_type,
                initial_value=initial_value,
                constant=is_constant,
            )))

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

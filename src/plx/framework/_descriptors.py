"""Variable descriptors for the plx framework.

Provides marker objects (not Python descriptors — ``__get__``/``__set__``
never fire since ``logic()`` source is parsed via AST, never executed).

Users declare variables on their POU classes like::

    class MyFB:
        sensor = input_var(BOOL)
        output = output_var(REAL, initial=0.0)
        timer_preset = static_var(TIME, initial=T(5))
"""

from __future__ import annotations

from enum import Enum

from plx.model.types import PrimitiveType, TypeRef
from plx.model.variables import Variable

from plx.model.types import NamedTypeRef

from ._types import TimeLiteral, LTimeLiteral, _resolve_type_ref


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

    Created by ``input_var()``, ``output_var()``, etc.  The ``@fb``/
    ``@program``/``@function`` decorator later collects these from the
    class ``__dict__`` and converts them into IR ``Variable`` nodes.
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
# Constructor functions
# ---------------------------------------------------------------------------

def input_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    initial: object = None,
    description: str = "",
    retain: bool = False,
    address: str | None = None,
) -> VarDescriptor:
    """Declare an input variable on a POU class."""
    return VarDescriptor(
        direction=VarDirection.INPUT,
        data_type=_resolve_type_ref(type_arg),
        initial_value=_format_initial(initial),
        description=description,
        retain=retain,
        address=address,
    )


def output_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    initial: object = None,
    description: str = "",
    retain: bool = False,
    address: str | None = None,
) -> VarDescriptor:
    """Declare an output variable on a POU class."""
    return VarDescriptor(
        direction=VarDirection.OUTPUT,
        data_type=_resolve_type_ref(type_arg),
        initial_value=_format_initial(initial),
        description=description,
        retain=retain,
        address=address,
    )


def static_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    initial: object = None,
    description: str = "",
    retain: bool = False,
    persistent: bool = False,
    constant: bool = False,
    address: str | None = None,
) -> VarDescriptor:
    """Declare a static (retained across scans) variable on a POU class."""
    return VarDescriptor(
        direction=VarDirection.STATIC,
        data_type=_resolve_type_ref(type_arg),
        initial_value=_format_initial(initial),
        description=description,
        retain=retain,
        persistent=persistent,
        constant=constant,
        address=address,
    )


def inout_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    description: str = "",
) -> VarDescriptor:
    """Declare an in-out variable on a POU class (no initial value)."""
    return VarDescriptor(
        direction=VarDirection.INOUT,
        data_type=_resolve_type_ref(type_arg),
        description=description,
    )


def temp_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    initial: object = None,
) -> VarDescriptor:
    """Declare a temp variable on a POU class."""
    return VarDescriptor(
        direction=VarDirection.TEMP,
        data_type=_resolve_type_ref(type_arg),
        initial_value=_format_initial(initial),
    )


def constant_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    initial: object,
    description: str = "",
) -> VarDescriptor:
    """Declare a constant variable on a POU class."""
    return VarDescriptor(
        direction=VarDirection.CONSTANT,
        data_type=_resolve_type_ref(type_arg),
        initial_value=_format_initial(initial),
        description=description,
        constant=True,
    )


def external_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    description: str = "",
) -> VarDescriptor:
    """Declare an external variable on a POU class (references a global var)."""
    return VarDescriptor(
        direction=VarDirection.EXTERNAL,
        data_type=_resolve_type_ref(type_arg),
        description=description,
    )


# ---------------------------------------------------------------------------
# Collection helper
# ---------------------------------------------------------------------------

def _collect_descriptors(cls: type, *, own_only: bool = False) -> dict[str, list[Variable]]:
    """Find ``VarDescriptor`` instances on *cls* and return
    IR ``Variable`` nodes grouped by direction.

    When *own_only* is False (default), walks the MRO so that a
    derived class inherits its parent's descriptors.  Parent
    descriptors appear first, then the child's.  If the child
    redefines a name that the parent declared, the child's version
    wins (override).

    Returns a dict with keys: ``"input"``, ``"output"``, ``"inout"``,
    ``"static"``, ``"temp"`` — each mapping to a list of ``Variable``.
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

    for ns in sources:
        for attr_name, value in ns.items():
            if isinstance(value, VarDescriptor):
                pass  # already a descriptor
            elif isinstance(value, type) and isinstance(value, CompiledPOU):
                # Bare FB class assignment: valve_a = ValveCtrl
                value = VarDescriptor(
                    direction=VarDirection.STATIC,
                    data_type=NamedTypeRef(name=value.__name__),
                )
            else:
                continue
            if attr_name in seen:
                # Child overrides parent — remove the earlier entry
                collected = [(n, v) for n, v in collected if n != attr_name]
            seen.add(attr_name)
            collected.append((attr_name, value))

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
# Pre-built VarDescriptor instances so users can write:
#     heat_timer = TON
# instead of:
#     heat_timer = static_var("TON")

TON = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="TON"))
TOF = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="TOF"))
TP = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="TP"))
R_TRIG = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="R_TRIG"))
F_TRIG = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="F_TRIG"))
CTU = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="CTU"))
CTD = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="CTD"))
CTUD = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="CTUD"))
SR = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="SR"))
RS = VarDescriptor(direction=VarDirection.STATIC, data_type=NamedTypeRef(name="RS"))

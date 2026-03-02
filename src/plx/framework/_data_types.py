"""User-defined data types: @struct and @enumeration decorators.

Provides decorators that compile Python classes into IR type definitions
(``StructType`` and ``EnumType``).  These are used in ``project()`` via
the ``data_types`` parameter and can be referenced in variable descriptors.

Enums are universal — the raise pass for AB/Siemens will lower
``EnumType`` to DINT constants.

Examples::

    @struct
    class MotorData:
        speed: REAL = 0.0
        running: BOOL = False
        fault_code: INT = 0

    @enumeration
    class MachineState:
        STOPPED = 0
        RUNNING = 1
        FAULTED = 2

    @enumeration(base_type=DINT)
    class AlarmCode:
        NONE = 0
        OVERHEAT = 100
"""

from __future__ import annotations

from typing import Any

from plx.model.types import (
    EnumMember,
    EnumType,
    PrimitiveType,
    StructMember,
    StructType,
)

from ._descriptors import _format_initial
from ._registry import register_type
from ._types import _resolve_type_ref


# ---------------------------------------------------------------------------
# @struct decorator
# ---------------------------------------------------------------------------

def struct(cls: type | None = None, *, folder: str = "") -> Any:
    """Decorate a class as a PLC struct type definition.

    Can be used as ``@struct`` or ``@struct(folder="...")``.

    Members are declared via class annotations with optional defaults::

        @struct
        class MotorData:
            speed: REAL = 0.0
            running: BOOL = False
            fault_code: INT = 0
    """
    def _apply(cls: type) -> type:
        annotations = cls.__dict__.get("__annotations__", {})
        if not annotations:
            raise TypeError(
                f"@struct class '{cls.__name__}' has no annotated members. "
                f"Add type annotations like: speed: REAL = 0.0"
            )

        members: list[StructMember] = []
        for member_name, type_hint in annotations.items():
            data_type = _resolve_type_ref(type_hint)
            default = cls.__dict__.get(member_name)
            initial_value = _format_initial(default)
            members.append(StructMember(
                name=member_name,
                data_type=data_type,
                initial_value=initial_value,
            ))

        compiled = StructType(name=cls.__name__, members=members, folder=folder)
        cls._compiled_type = compiled
        cls.__plx_struct__ = True
        register_type(cls)

        @classmethod  # type: ignore[misc]
        def compile(klass: type) -> StructType:
            return klass._compiled_type

        cls.compile = compile
        return cls

    if cls is not None:
        return _apply(cls)
    return _apply


# ---------------------------------------------------------------------------
# @enumeration decorator
# ---------------------------------------------------------------------------

def enumeration(
    cls: type | None = None,
    *,
    base_type: PrimitiveType | None = None,
    folder: str = "",
) -> Any:
    """Decorate a class as a PLC enumeration type definition.

    Can be used as ``@enumeration`` or ``@enumeration(base_type=DINT)``.

    Examples::

        @enumeration
        class MachineState:
            STOPPED = 0
            RUNNING = 1
            FAULTED = 2

        @enumeration(base_type=DINT)
        class AlarmCode:
            NONE = 0
            OVERHEAT = 100
    """
    def _apply(cls: type) -> type:
        # Collect non-dunder int attributes as enum members
        enum_values: dict[str, int] = {}
        ir_members: list[EnumMember] = []

        for attr_name, value in cls.__dict__.items():
            if attr_name.startswith("_"):
                continue
            if not isinstance(value, int):
                raise TypeError(
                    f"Enum member '{cls.__name__}.{attr_name}' must be an int, "
                    f"got {type(value).__name__}"
                )
            enum_values[attr_name] = value
            ir_members.append(EnumMember(name=attr_name, value=value))

        if not ir_members:
            raise TypeError(
                f"@enumeration class '{cls.__name__}' has no members. "
                f"Add integer attributes like: STOPPED = 0"
            )

        compiled = EnumType(
            name=cls.__name__,
            folder=folder,
            members=ir_members,
            base_type=base_type,
        )
        cls._compiled_type = compiled
        cls._enum_values = enum_values
        cls.__plx_enum__ = True
        register_type(cls)

        @classmethod  # type: ignore[misc]
        def compile(klass: type) -> EnumType:
            return klass._compiled_type

        cls.compile = compile
        return cls

    if cls is not None:
        # Used as @enumeration (no parentheses)
        return _apply(cls)
    # Used as @enumeration() or @enumeration(base_type=DINT)
    return _apply


# ---------------------------------------------------------------------------
# Type introspection helpers
# ---------------------------------------------------------------------------

def _is_struct(obj: object) -> bool:
    """Check if *obj* is a @struct-decorated class."""
    return getattr(obj, "__plx_struct__", False)


def _is_enumeration(obj: object) -> bool:
    """Check if *obj* is a @enumeration-decorated class."""
    return getattr(obj, "__plx_enum__", False)


def _is_data_type(obj: object) -> bool:
    """Check if *obj* is a @struct or @enumeration decorated class."""
    return _is_struct(obj) or _is_enumeration(obj)

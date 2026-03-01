"""Global variable lists: @global_vars decorator and global_var() constructor.

Provides the framework API for declaring named groups of global variables
that compile into ``GlobalVariableList`` IR nodes.

Examples::

    @global_vars
    class SystemConstants:
        max_speed: REAL = 100.0
        timeout: TIME = T(s=30)
        enabled: BOOL = True

    @global_vars(description="IO mappings for conveyor")
    class ConveyorIO:
        motor_run = global_var(BOOL, address="%Q0.0")
        speed_setpoint = global_var(REAL, initial=0.0, description="m/s")
        e_stop = global_var(BOOL, address="%I0.0", constant=True)

    # Hybrid: mix bare annotations and global_var() descriptors
    @global_vars
    class MixedGVL:
        simple_flag: BOOL = False
        retained_counter = global_var(DINT, retain=True)
"""

from __future__ import annotations

from typing import Any, Literal

from plx.model.project import GlobalVariableList
from plx.model.types import PrimitiveType, TypeRef
from plx.model.variables import Variable

from ._descriptors import _format_initial
from ._types import _resolve_type_ref


# ---------------------------------------------------------------------------
# GlobalVarDescriptor — marker object produced by global_var()
# ---------------------------------------------------------------------------

class GlobalVarDescriptor:
    """Stores metadata for a global variable declared with ``global_var()``."""

    __slots__ = (
        "data_type",
        "initial_value",
        "description",
        "constant",
        "retain",
        "persistent",
        "address",
    )

    def __init__(
        self,
        data_type: TypeRef,
        *,
        initial_value: str | None = None,
        description: str = "",
        constant: bool = False,
        retain: bool = False,
        persistent: bool = False,
        address: str | None = None,
    ) -> None:
        self.data_type = data_type
        self.initial_value = initial_value
        self.description = description
        self.constant = constant
        self.retain = retain
        self.persistent = persistent
        self.address = address


def global_var(
    type_arg: PrimitiveType | TypeRef | str,
    *,
    initial: object = None,
    description: str = "",
    constant: bool = False,
    retain: bool = False,
    persistent: bool = False,
    address: str | None = None,
) -> GlobalVarDescriptor:
    """Declare a global variable with full control over all Variable fields.

    Example::

        motor_run = global_var(BOOL, address="%Q0.0")
        speed = global_var(REAL, initial=50.0, retain=True)
    """
    if isinstance(type_arg, type) and not isinstance(type_arg, PrimitiveType):
        raise TypeError(
            "Did you mean @global_vars? "
            "global_var() declares individual variables inside a @global_vars class."
        )
    return GlobalVarDescriptor(
        data_type=_resolve_type_ref(type_arg),
        initial_value=_format_initial(initial),
        description=description,
        constant=constant,
        retain=retain,
        persistent=persistent,
        address=address,
    )


# ---------------------------------------------------------------------------
# @global_vars decorator
# ---------------------------------------------------------------------------

def global_vars(
    cls: type | None = None,
    *,
    description: str = "",
    folder: str = "",
    scope: Literal["", "controller", "program"] = "",
) -> Any:
    """Decorate a class as a global variable list.

    Can be used as ``@global_vars`` or ``@global_vars(description="...")``.

    Variables are declared either as bare annotations (with optional defaults)
    or via ``global_var()`` descriptors.  Both styles can be mixed freely.

    Examples::

        @global_vars
        class SystemIO:
            motor_run: BOOL = False
            speed: REAL = 0.0

        @global_vars(description="Conveyor IO mapping")
        class ConveyorIO:
            run_cmd = global_var(BOOL, address="%Q0.0")
    """
    def _apply(cls: type) -> type:
        variables: list[Variable] = []

        # First pass: collect global_var() descriptors from __dict__
        descriptor_names: set[str] = set()
        for attr_name, value in cls.__dict__.items():
            if attr_name.startswith("_"):
                continue
            if isinstance(value, GlobalVarDescriptor):
                descriptor_names.add(attr_name)
                variables.append(Variable(
                    name=attr_name,
                    data_type=value.data_type,
                    initial_value=value.initial_value,
                    description=value.description,
                    constant=value.constant,
                    retain=value.retain,
                    persistent=value.persistent,
                    address=value.address,
                ))

        # Second pass: bare annotations (not already handled by descriptors)
        annotations = cls.__dict__.get("__annotations__", {})
        for attr_name, type_hint in annotations.items():
            if attr_name.startswith("_"):
                continue
            if attr_name in descriptor_names:
                continue
            data_type = _resolve_type_ref(type_hint)
            default = cls.__dict__.get(attr_name)
            initial_value = _format_initial(default)
            variables.append(Variable(
                name=attr_name,
                data_type=data_type,
                initial_value=initial_value,
            ))

        if not variables:
            raise TypeError(
                f"@global_vars class '{cls.__name__}' has no variables. "
                f"Add type annotations (speed: REAL = 0.0) or "
                f"global_var() descriptors (speed = global_var(REAL))."
            )

        compiled = GlobalVariableList(
            name=cls.__name__,
            folder=folder,
            scope=scope,
            description=description,
            variables=variables,
        )
        cls._compiled_gvl = compiled
        cls.__plx_global_vars__ = True

        @classmethod  # type: ignore[misc]
        def compile(klass: type) -> GlobalVariableList:
            return klass._compiled_gvl

        cls.compile = compile
        return cls

    if cls is not None:
        # Used as @global_vars (no parentheses)
        return _apply(cls)
    # Used as @global_vars() or @global_vars(description="...")
    return _apply

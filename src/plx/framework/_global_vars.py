"""Global variable lists: @global_vars decorator.

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
        motor_run: BOOL = Field(address="%Q0.0")
        speed_setpoint: REAL = Field(initial=0.0, description="m/s")
        e_stop: BOOL = Field(address="%I0.0", constant=True)
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args, get_origin

from plx.model.project import GlobalVariableList
from plx.model.variables import Variable

from ._descriptors import FieldDescriptor, _format_initial
from ._types import TimeLiteral, LTimeLiteral, _resolve_type_ref


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

    Variables are declared as bare annotations (with optional defaults)
    or with ``Field()`` for metadata.

    Examples::

        @global_vars
        class SystemIO:
            motor_run: BOOL = False
            speed: REAL = 0.0

        @global_vars(description="Conveyor IO mapping")
        class ConveyorIO:
            run_cmd: BOOL = Field(address="%Q0.0")
            speed: REAL = Field(initial=50.0, retain=True)
    """
    def _apply(cls: type) -> type:
        variables: list[Variable] = []

        annotations = cls.__dict__.get("__annotations__", {})
        for attr_name, type_hint in annotations.items():
            if attr_name.startswith("_"):
                continue

            # Unwrap Annotated[T, Field(...), ...] if present
            annotated_field: FieldDescriptor | None = None
            if get_origin(type_hint) is Annotated:
                ann_args = get_args(type_hint)
                type_hint = ann_args[0]
                fields_found = [a for a in ann_args[1:] if isinstance(a, FieldDescriptor)]
                if len(fields_found) > 1:
                    raise TypeError(
                        f"Variable '{attr_name}' has multiple Field() in Annotated — only one allowed"
                    )
                if fields_found:
                    annotated_field = fields_found[0]

            data_type = _resolve_type_ref(type_hint)
            default = cls.__dict__.get(attr_name)

            if annotated_field is not None:
                field = annotated_field
                # Plain class default supplies initial when Field doesn't
                if field.initial_value is None and default is not None and not isinstance(default, FieldDescriptor):
                    field = FieldDescriptor(
                        initial_value=_format_initial(default),
                        description=field.description,
                        retain=field.retain,
                        persistent=field.persistent,
                        constant=field.constant,
                        address=field.address,
                    )
                variables.append(Variable(
                    name=attr_name,
                    data_type=data_type,
                    initial_value=field.initial_value,
                    description=field.description,
                    constant=field.constant,
                    retain=field.retain,
                    persistent=field.persistent,
                    address=field.address,
                ))
            elif isinstance(default, FieldDescriptor):
                variables.append(Variable(
                    name=attr_name,
                    data_type=data_type,
                    initial_value=default.initial_value,
                    description=default.description,
                    constant=default.constant,
                    retain=default.retain,
                    persistent=default.persistent,
                    address=default.address,
                ))
            else:
                # Bare annotation with optional simple default
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
                f"Field() descriptors (speed: REAL = Field(retain=True))."
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

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
        motor_run: BOOL
        speed_setpoint: REAL = Field(initial=0.0, description="m/s")
        e_stop: BOOL = Field(constant=True)
"""

from __future__ import annotations

from typing import Any, Literal

from plx.model.project import GlobalVariableList
from plx.model.variables import Variable

from ._descriptors import FieldDescriptor, _format_initial, _unwrap_annotated, _field_to_variable
from ._errors import DefinitionError
from ._types import _resolve_type_ref


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
            run_cmd: BOOL
            speed: REAL = Field(initial=50.0, retain=True)
    """
    def _apply(cls: type) -> type:
        variables: list[Variable] = []

        annotations = cls.__dict__.get("__annotations__", {})
        for attr_name, type_hint in annotations.items():
            if attr_name.startswith("_"):
                continue

            type_hint, annotated_field = _unwrap_annotated(type_hint, attr_name)

            data_type = _resolve_type_ref(type_hint)
            default = cls.__dict__.get(attr_name)

            if annotated_field is not None:
                variables.append(_field_to_variable(attr_name, data_type, annotated_field, default))
            elif isinstance(default, FieldDescriptor):
                variables.append(_field_to_variable(attr_name, data_type, default))
            else:
                # Bare annotation with optional simple default
                initial_value = _format_initial(default)
                variables.append(Variable(
                    name=attr_name,
                    data_type=data_type,
                    initial_value=initial_value,
                ))

        if not variables:
            raise DefinitionError(
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

        @classmethod  # type: ignore[misc]  — mypy can't verify dynamic classmethod assignment
        def compile(klass: type) -> GlobalVariableList:
            return klass._compiled_gvl

        cls.compile = compile
        return cls

    if cls is not None:
        # Used as @global_vars (no parentheses)
        return _apply(cls)
    # Used as @global_vars() or @global_vars(description="...")
    return _apply

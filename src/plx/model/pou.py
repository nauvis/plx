"""Program Organization Units for the Universal IR."""

from __future__ import annotations

from enum import Enum
from typing import Any, Self

from pydantic import Field, model_validator

from ._base import IRModel

from .sfc import SFCBody
from .statements import Statement
from .types import TypeRef
from .variables import Variable


def _check_body_exclusivity(networks: list, sfc_body: object | None, context: str) -> None:
    """Shared validation: at most one body type (networks or sfc_body)."""
    bodies = sum([bool(networks), sfc_body is not None])
    if bodies > 1:
        raise ValueError(
            f"{context} must have at most one body type "
            f"(networks or sfc_body)"
        )


class POUType(str, Enum):
    PROGRAM = "PROGRAM"
    FUNCTION_BLOCK = "FUNCTION_BLOCK"
    FUNCTION = "FUNCTION"
    INTERFACE = "INTERFACE"


class AccessSpecifier(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    PROTECTED = "PROTECTED"
    INTERNAL = "INTERNAL"


class Language(str, Enum):
    """IEC 61131-3 programming language for POU body."""
    ST = "ST"
    LD = "LD"
    FBD = "FBD"
    SFC = "SFC"


class Network(IRModel):
    """A single network / rung of logic."""

    label: str | None = None
    comment: str | None = None
    statements: list[Statement] = []


class POUInterface(IRModel):
    """The variable interface of a POU, Method, or similar code unit.

    Each list encodes the variable's role structurally — Variables carry
    no redundant direction/scope enums.
    """

    input_vars: list[Variable] = []
    output_vars: list[Variable] = []
    inout_vars: list[Variable] = []
    static_vars: list[Variable] = []
    temp_vars: list[Variable] = []
    constant_vars: list[Variable] = []
    external_vars: list[Variable] = []

    @model_validator(mode="after")
    def _no_duplicate_var_names(self) -> Self:
        seen: dict[str, str] = {}
        for section_name, var_list in (
            ("input_vars", self.input_vars),
            ("output_vars", self.output_vars),
            ("inout_vars", self.inout_vars),
            ("static_vars", self.static_vars),
            ("temp_vars", self.temp_vars),
            ("constant_vars", self.constant_vars),
            ("external_vars", self.external_vars),
        ):
            for var in var_list:
                if var.name in seen:
                    raise ValueError(
                        f"Duplicate variable name '{var.name}' "
                        f"(in {seen[var.name]} and {section_name})"
                    )
                seen[var.name] = section_name
        return self


class PropertyAccessor(IRModel):
    """Getter or setter body for a Property."""

    local_vars: list[Variable] = []
    networks: list[Network] = []


class Property(IRModel):
    """A property on a FUNCTION_BLOCK (OOP extension)."""

    name: str = Field(min_length=1)
    data_type: TypeRef
    access: AccessSpecifier = AccessSpecifier.PUBLIC
    abstract: bool = False
    final: bool = False
    getter: PropertyAccessor | None = None
    setter: PropertyAccessor | None = None


class Method(IRModel):
    """A method on a FUNCTION_BLOCK (OOP extension)."""

    name: str = Field(min_length=1)
    language: Language | None = None
    return_type: TypeRef | None = None
    access: AccessSpecifier = AccessSpecifier.PUBLIC
    abstract: bool = False
    final: bool = False
    description: str = ""
    interface: POUInterface = POUInterface()
    networks: list[Network] = []
    sfc_body: SFCBody | None = None

    @model_validator(mode="after")
    def _body_exclusivity(self) -> Self:
        _check_body_exclusivity(self.networks, self.sfc_body, "Method")
        return self


class POUAction(IRModel):
    """A named action on a POU.

    Actions execute in the parent POU's variable scope — they have
    direct access to all parent variables with no parameter passing.
    Used standalone or referenced by SFC steps via action qualifiers.
    """

    name: str = Field(min_length=1)
    body: list[Network] = []


class POU(IRModel):
    """Program Organization Unit.

    For INTERFACE POUs, only *methods* and *properties* are meaningful;
    *networks*, *sfc_body*, and *interface* are unused.

    ``folder`` is a forward-slash-delimited organizational path
    (e.g. ``"Utilities/Motors"``).  Empty string means root / no folder.
    Maps to Beckhoff folder tree, Siemens project navigator folders,
    AB program containers.  Vendor raise passes map to their native model.
    """

    pou_type: POUType
    name: str = Field(min_length=1)
    folder: str = ""
    abstract: bool = False
    description: str = ""
    safety: bool = False
    language: Language | None = None
    return_type: TypeRef | None = None
    interface: POUInterface = POUInterface()
    networks: list[Network] = []
    sfc_body: SFCBody | None = None
    actions: list[POUAction] = []
    methods: list[Method] = []
    properties: list[Property] = []
    extends: str | None = None
    implements: list[str] = []
    metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def _body_exclusivity(self) -> Self:
        _check_body_exclusivity(self.networks, self.sfc_body, "POU")
        return self

    @model_validator(mode="after")
    def _no_duplicate_method_names(self) -> Self:
        seen: set[str] = set()
        for m in self.methods:
            if m.name in seen:
                raise ValueError(
                    f"Duplicate method name '{m.name}' in POU '{self.name}'"
                )
            seen.add(m.name)
        return self

    @model_validator(mode="after")
    def _no_duplicate_property_names(self) -> Self:
        seen: set[str] = set()
        for p in self.properties:
            if p.name in seen:
                raise ValueError(
                    f"Duplicate property name '{p.name}' in POU '{self.name}'"
                )
            seen.add(p.name)
        return self

    @model_validator(mode="after")
    def _no_duplicate_action_names(self) -> Self:
        seen: set[str] = set()
        for a in self.actions:
            if a.name in seen:
                raise ValueError(
                    f"Duplicate action name '{a.name}' in POU '{self.name}'"
                )
            seen.add(a.name)
        return self

    @model_validator(mode="after")
    def _validate_return_type(self) -> Self:
        if self.return_type is not None and self.pou_type != POUType.FUNCTION:
            raise ValueError(
                f"return_type is only valid for FUNCTION POUs, "
                f"not {self.pou_type.value}"
            )
        return self

    @model_validator(mode="after")
    def _validate_interface_pou(self) -> Self:
        if self.pou_type == POUType.INTERFACE:
            if self.networks:
                raise ValueError(
                    "INTERFACE POUs must not have networks"
                )
            if self.sfc_body is not None:
                raise ValueError(
                    "INTERFACE POUs must not have sfc_body"
                )
            if self.interface.static_vars:
                raise ValueError(
                    "INTERFACE POUs must not have static_vars"
                )
            if self.interface.temp_vars:
                raise ValueError(
                    "INTERFACE POUs must not have temp_vars"
                )
            if self.actions:
                raise ValueError(
                    "INTERFACE POUs must not have actions"
                )
        return self

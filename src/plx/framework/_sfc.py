"""SFC decorator: @sfc compiles Python classes into POU with SFCBody.

Provides the user-facing API for Sequential Function Charts:

- ``step()`` — declare SFC steps as class attributes
- ``transition()`` — decorator for transition condition methods
- ``@sfc`` — class decorator that compiles to POU with ``sfc_body``

Steps support action decorators: ``.action``, ``.entry``, ``.exit``.
Divergence/convergence via ``>>`` (transition path) and ``&`` (parallel).

Implementation note: ``__set_name__`` fires *after* the class body finishes,
so decorators like ``@STEP.action`` execute during class body when the step
has no name yet.  All marking stores the ``StepDescriptor`` *object* reference;
``_compile_sfc_class`` builds a reverse lookup (id(descriptor) → name) to
resolve names after ``__set_name__`` has run.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from plx.model.pou import (
    POU,
    POUInterface,
    POUType,
)
from plx.model.sfc import (
    Action,
    ActionQualifier,
    SFCBody,
    Step,
    Transition,
)
from plx.model.types import TypeRef
from plx.model.variables import Variable

from ._compiler import ASTCompiler
from ._compiler_core import CompileError
from ._compilation_helpers import (
    _build_compile_context,
    _build_var_context,
    _detect_parent_pou,
    _discover_enums,
    _parse_function_source,
)
from ._decorators import _compile_all_methods, _compile_all_properties
from ._descriptors import VarDirection


# ---------------------------------------------------------------------------
# TransitionPath — data holder for >> operator results
# ---------------------------------------------------------------------------

class TransitionPath:
    """Source/target step descriptors for a transition, created by ``>>``."""

    __slots__ = ("source_descs", "target_descs")

    def __init__(
        self,
        source_descs: list[StepDescriptor],
        target_descs: list[StepDescriptor],
    ) -> None:
        self.source_descs = source_descs
        self.target_descs = target_descs

    # -- Guard operators against precedence / chaining mistakes --

    def __and__(self, other: Any) -> Any:
        raise TypeError(
            "Operator precedence error: `A >> B & C` binds as `(A >> B) & C`. "
            "Use parentheses: `A >> (B & C)`"
        )

    def __rand__(self, other: Any) -> Any:
        raise TypeError(
            "Operator precedence error: `A & B >> C` binds as `A & (B >> C)`. "
            "Use parentheses: `(A & B) >> C`"
        )

    def __rshift__(self, other: Any) -> Any:
        raise TypeError(
            "Cannot chain `>>`: `A >> B >> C` is not supported. "
            "Use separate @transition decorators for each step-to-step path."
        )

    def __rrshift__(self, other: Any) -> Any:
        raise TypeError(
            "Cannot chain `>>`: `A >> B >> C` is not supported. "
            "Use separate @transition decorators for each step-to-step path."
        )


# ---------------------------------------------------------------------------
# StepGroup — for AND-fork / AND-join via & operator
# ---------------------------------------------------------------------------

class StepGroup:
    """Multiple steps combined with ``&`` for simultaneous divergence/convergence."""

    __slots__ = ("descs",)

    def __init__(self, descs: list[StepDescriptor]) -> None:
        self.descs = descs

    def __and__(self, other: StepGroup | StepDescriptor) -> StepGroup:
        if isinstance(other, StepDescriptor):
            return StepGroup(self.descs + [other])
        if isinstance(other, StepGroup):
            return StepGroup(self.descs + other.descs)
        return NotImplemented

    def __rshift__(self, other: StepDescriptor | StepGroup) -> TransitionPath:
        if isinstance(other, StepDescriptor):
            return TransitionPath(source_descs=self.descs, target_descs=[other])
        if isinstance(other, StepGroup):
            return TransitionPath(source_descs=self.descs, target_descs=other.descs)
        return NotImplemented


# ---------------------------------------------------------------------------
# Marker dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ActionMarker:
    """Stored as ``func._plx_marker`` on step action methods."""
    step_desc: StepDescriptor
    qualifier: ActionQualifier
    slot: str  # "action" | "entry" | "exit"
    duration: str | None = None
    action_name: str | None = None


@dataclass(frozen=True)
class _TransitionMarker:
    """Stored as ``func._plx_marker`` on transition methods."""
    path: TransitionPath


# ---------------------------------------------------------------------------
# _StepActionDecorator — dual-mode decorator for step actions
# ---------------------------------------------------------------------------

class _StepActionDecorator:
    """Callable returned by ``StepDescriptor.action``.

    Supports both ``@STEP.action`` (bare) and
    ``@STEP.action(qualifier="L", duration=T(s=10))`` (with args).

    Stores a reference to the StepDescriptor (not its name, since
    ``__set_name__`` hasn't run yet during class body execution).
    """

    def __init__(self, step_desc: StepDescriptor) -> None:
        self._step_desc = step_desc

    def __call__(
        self,
        func: Any = None,
        *,
        qualifier: str = "N",
        duration: Any = None,
        resets: str | None = None,
    ) -> Any:
        if func is not None and callable(func):
            # Bare @STEP.action — func is the decorated function
            func._plx_marker = _ActionMarker(
                step_desc=self._step_desc,
                qualifier=ActionQualifier("N"),
                slot="action",
            )
            return func
        # Called with args: @STEP.action(qualifier="L", duration=...)
        resolved_qualifier = qualifier if func is None else func
        dur_str = _format_duration(duration) if duration is not None else None

        def decorator(fn: Any) -> Any:
            fn._plx_marker = _ActionMarker(
                step_desc=self._step_desc,
                qualifier=ActionQualifier(resolved_qualifier),
                slot="action",
                duration=dur_str,
                action_name=resets,
            )
            return fn
        return decorator


# ---------------------------------------------------------------------------
# StepDescriptor — class-attribute descriptor for SFC steps
# ---------------------------------------------------------------------------

class StepDescriptor:
    """Marker for SFC steps. Created by ``step(initial=True)``.

    During class body execution, ``__set_name__`` has not yet been called,
    so ``.action``, ``.entry``, ``.exit`` store a reference to ``self``
    (the descriptor object).  ``_compile_sfc_class`` later resolves
    descriptors to names.
    """

    __slots__ = ("initial", "name")

    def __init__(self, *, initial: bool = False) -> None:
        self.initial = initial
        self.name: str | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    # -- Operators for transition paths --

    def __rshift__(self, other: StepDescriptor | StepGroup) -> TransitionPath:
        if isinstance(other, StepDescriptor):
            return TransitionPath(source_descs=[self], target_descs=[other])
        if isinstance(other, StepGroup):
            return TransitionPath(source_descs=[self], target_descs=other.descs)
        return NotImplemented

    def __and__(self, other: StepDescriptor | StepGroup) -> StepGroup:
        if isinstance(other, StepDescriptor):
            return StepGroup([self, other])
        if isinstance(other, StepGroup):
            return StepGroup([self] + other.descs)
        return NotImplemented

    # -- Action decorators --

    @property
    def action(self) -> _StepActionDecorator:
        """Decorator for N-qualified (continuous) actions on this step."""
        return _StepActionDecorator(self)

    def entry(self, func: Any) -> Any:
        """Decorator for entry action (P1 — runs once on step activation)."""
        func._plx_marker = _ActionMarker(
            step_desc=self,
            qualifier=ActionQualifier.P1,
            slot="entry",
        )
        return func

    def exit(self, func: Any) -> Any:
        """Decorator for exit action (P0 — runs once on step deactivation)."""
        func._plx_marker = _ActionMarker(
            step_desc=self,
            qualifier=ActionQualifier.P0,
            slot="exit",
        )
        return func


# ---------------------------------------------------------------------------
# Public constructors
# ---------------------------------------------------------------------------

def step(*, initial: bool = False) -> StepDescriptor:
    """Declare an SFC step.

    Example::

        IDLE = step(initial=True)
        RUNNING = step()
    """
    return StepDescriptor(initial=initial)


def transition(path: TransitionPath) -> Any:
    """Decorator for SFC transition conditions.

    The decorated method's body must be a single ``return <expr>``
    statement. The expression becomes the transition condition.

    Example::

        @transition(IDLE >> RUNNING)
        def start(self):
            return self.start_cmd
    """
    def decorator(func: Any) -> Any:
        func._plx_marker = _TransitionMarker(path=path)
        return func
    return decorator


# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------

def _format_duration(duration: Any) -> str:
    """Convert a duration value to an IEC duration string."""
    from ._types import TimeLiteral, LTimeLiteral
    if isinstance(duration, (TimeLiteral, LTimeLiteral)):
        return duration.to_iec()
    if isinstance(duration, str):
        return duration
    raise TypeError(
        f"Duration must be a TimeLiteral (T(...)), LTimeLiteral (LT(...)), "
        f"or IEC duration string, got {type(duration).__name__}"
    )


# ---------------------------------------------------------------------------
# SFC compilation helpers
# ---------------------------------------------------------------------------

def _collect_and_validate_steps(
    cls: type,
) -> tuple[dict[str, StepDescriptor], dict[int, str]]:
    """Gather StepDescriptors from *cls*, validate initial step exists.

    Returns ``(step_descriptors, desc_to_name)`` where *desc_to_name*
    maps ``id(descriptor)`` → attribute name.
    """
    step_descriptors: dict[str, StepDescriptor] = {}
    desc_to_name: dict[int, str] = {}
    for attr_name, value in cls.__dict__.items():
        if isinstance(value, StepDescriptor):
            step_descriptors[attr_name] = value
            desc_to_name[id(value)] = attr_name

    if not step_descriptors:
        raise CompileError(
            f"@sfc class '{cls.__name__}' must define at least one step "
            f"(e.g. IDLE = step(initial=True))"
        )

    initial_steps = [n for n, s in step_descriptors.items() if s.initial]
    if len(initial_steps) == 0:
        raise CompileError(
            f"@sfc class '{cls.__name__}' must have exactly one initial step "
            f"(use step(initial=True))"
        )
    if len(initial_steps) > 1:
        raise CompileError(
            f"@sfc class '{cls.__name__}' has multiple initial steps: "
            f"{initial_steps}. Only one is allowed."
        )

    return step_descriptors, desc_to_name


def _categorize_sfc_methods(
    cls: type,
    desc_to_name: dict[int, str],
    step_names: set[str],
) -> tuple[
    list[tuple[str, Any, str, ActionQualifier, str, str | None, str | None]],
    list[tuple[str, Any, list[str], list[str]]],
]:
    """Classify action and transition methods, resolving descriptor refs.

    Returns ``(action_infos, transition_infos)`` where:

    - *action_infos*: ``(name, func, step_name, qualifier, slot, duration, action_name)``
    - *transition_infos*: ``(name, func, source_names, target_names)``
    """
    def _resolve_desc(desc: StepDescriptor) -> str:
        name = desc_to_name.get(id(desc))
        if name is None:
            name = desc.name
        if name is None or name not in step_names:
            raise CompileError(
                f"Step descriptor could not be resolved to a step name "
                f"in @sfc class '{cls.__name__}'"
            )
        return name

    action_infos: list[tuple[str, Any, str, ActionQualifier, str, str | None, str | None]] = []
    transition_infos: list[tuple[str, Any, list[str], list[str]]] = []

    for attr_name, value in cls.__dict__.items():
        if not callable(value):
            continue
        marker = getattr(value, '_plx_marker', None)
        if isinstance(marker, _ActionMarker):
            step_name = _resolve_desc(marker.step_desc)
            action_infos.append((
                attr_name, value, step_name,
                marker.qualifier,
                marker.slot,
                marker.duration,
                marker.action_name,
            ))
        elif isinstance(marker, _TransitionMarker):
            source_names = [_resolve_desc(d) for d in marker.path.source_descs]
            target_names = [_resolve_desc(d) for d in marker.path.target_descs]
            transition_infos.append((attr_name, value, source_names, target_names))

    return action_infos, transition_infos


def _compile_sfc_actions(
    action_infos: list[tuple[str, Any, str, ActionQualifier, str, str | None, str | None]],
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
    step_descriptors: dict[str, StepDescriptor],
    generated_static: list[Variable],
    generated_temp: list[Variable],
) -> dict[str, dict[str, list[Action]]]:
    """Compile all action bodies into a step-keyed, slot-keyed dict."""
    step_actions: dict[str, dict[str, list[Action]]] = {
        name: {"action": [], "entry": [], "exit": []}
        for name in step_descriptors
    }

    for method_name, method_func, step_name, qualifier, slot, duration, action_name in action_infos:
        statements = _compile_action_body(
            cls, method_name, method_func,
            declared_vars, static_var_types, source_file,
            generated_static, generated_temp,
        )
        action = Action(
            name=method_name,
            qualifier=qualifier,
            duration=duration,
            body=statements,
            action_name=action_name,
        )
        step_actions[step_name][slot].append(action)

    return step_actions


def _compile_sfc_transitions(
    transition_infos: list[tuple[str, Any, list[str], list[str]]],
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
    generated_static: list[Variable],
    generated_temp: list[Variable],
) -> list[Transition]:
    """Compile all transition conditions into IR Transition nodes."""
    transitions: list[Transition] = []
    for method_name, method_func, source_names, target_names in transition_infos:
        condition = _compile_transition_condition(
            cls, method_name, method_func,
            declared_vars, static_var_types, source_file,
            generated_static, generated_temp,
        )
        transitions.append(Transition(
            source_steps=source_names,
            target_steps=target_names,
            condition=condition,
        ))
    return transitions


def _build_sfc_steps(
    step_descriptors: dict[str, StepDescriptor],
    step_actions: dict[str, dict[str, list[Action]]],
) -> list[Step]:
    """Assemble Step IR nodes from descriptors and compiled actions."""
    steps: list[Step] = []
    for name, desc in step_descriptors.items():
        actions = step_actions[name]
        steps.append(Step(
            name=name,
            is_initial=desc.initial,
            actions=actions["action"],
            entry_actions=actions["entry"],
            exit_actions=actions["exit"],
        ))
    return steps


# ---------------------------------------------------------------------------
# Core SFC compilation orchestrator
# ---------------------------------------------------------------------------

def _compile_sfc_class(cls: type, pou_type: POUType, folder: str = "") -> type:
    """Compile an @sfc-decorated class into a POU with sfc_body."""

    if "logic" in cls.__dict__:
        raise CompileError(
            f"@sfc class '{cls.__name__}' must not define a logic() method. "
            f"SFC uses steps and transitions instead."
        )

    extends = _detect_parent_pou(cls)
    var_groups, declared_vars, static_var_types = _build_var_context(cls)

    try:
        source_file = inspect.getfile(cls)
    except (TypeError, OSError):
        source_file = "<unknown>"

    step_descriptors, desc_to_name = _collect_and_validate_steps(cls)
    action_infos, transition_infos = _categorize_sfc_methods(
        cls, desc_to_name, set(step_descriptors.keys()),
    )

    all_generated_static: list[Variable] = []
    all_generated_temp: list[Variable] = []

    step_actions = _compile_sfc_actions(
        action_infos, cls,
        declared_vars, static_var_types, source_file,
        step_descriptors, all_generated_static, all_generated_temp,
    )
    transition_ir_nodes = _compile_sfc_transitions(
        transition_infos, cls,
        declared_vars, static_var_types, source_file,
        all_generated_static, all_generated_temp,
    )

    sfc_body = SFCBody(
        steps=_build_sfc_steps(step_descriptors, step_actions),
        transitions=transition_ir_nodes,
    )
    compiled_methods = _compile_all_methods(
        cls, declared_vars, static_var_types, source_file,
    )
    compiled_properties = _compile_all_properties(
        cls, declared_vars, static_var_types, source_file,
    )

    interface = POUInterface(
        input_vars=var_groups["input"],
        output_vars=var_groups["output"],
        inout_vars=var_groups["inout"],
        static_vars=var_groups["static"] + all_generated_static,
        temp_vars=var_groups["temp"] + all_generated_temp,
        constant_vars=var_groups["constant"],
        external_vars=var_groups["external"],
    )

    pou = POU(
        pou_type=pou_type,
        name=cls.__name__,
        folder=folder,
        extends=extends,
        interface=interface,
        sfc_body=sfc_body,
        methods=compiled_methods,
        properties=compiled_properties,
    )

    cls._compiled_pou = pou

    @classmethod
    def compile(klass: type) -> POU:
        return klass._compiled_pou

    cls.compile = compile

    return cls


def _compile_action_body(
    cls: type,
    method_name: str,
    method_func: Any,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
    generated_static: list[Variable],
    generated_temp: list[Variable],
) -> list:
    """Compile an action method's body into IR statements."""
    context_name = f"{cls.__name__}.{method_name}()"
    func_def, _, start_lineno = _parse_function_source(
        method_func, context_name, validate_self_only=True,
    )

    ctx = _build_compile_context(
        method_func, cls,
        dict(declared_vars), dict(static_var_types),
        start_lineno, source_file,
    )

    compiler = ASTCompiler(ctx)
    statements = compiler.compile_body(func_def)

    generated_static.extend(ctx.generated_static_vars)
    generated_temp.extend(ctx.generated_temp_vars)

    return statements


def _compile_transition_condition(
    cls: type,
    method_name: str,
    method_func: Any,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
    generated_static: list[Variable],
    generated_temp: list[Variable],
):
    """Compile a transition method to an IR Expression (the condition)."""
    context_name = f"Transition '{method_name}' in @sfc class '{cls.__name__}'"
    func_def, _, start_lineno = _parse_function_source(
        method_func, context_name,
        validate_self_only=True,
        validate_single_return=True,
    )

    ctx = _build_compile_context(
        method_func, cls,
        dict(declared_vars), dict(static_var_types),
        start_lineno, source_file,
    )

    compiler = ASTCompiler(ctx)
    condition = compiler.compile_expression(func_def.body[0].value)

    generated_static.extend(ctx.generated_static_vars)
    generated_temp.extend(ctx.generated_temp_vars)

    return condition


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------

def sfc(cls: type = None, *, pou_type: str = "PROGRAM", folder: str = "") -> Any:
    """Decorate a class as an SFC POU.

    Can be used as ``@sfc`` or ``@sfc(pou_type="FB")``.

    Example::

        @sfc
        class FillSequence:
            start_cmd = input_var(BOOL)
            level = input_var(REAL)
            valve = output_var(BOOL)

            IDLE = step(initial=True)
            FILLING = step()

            @IDLE.action
            def idle_action(self):
                self.valve = False

            @FILLING.action
            def filling_action(self):
                self.valve = True

            @transition(IDLE >> FILLING)
            def start(self):
                return self.start_cmd
    """
    resolved_type = _resolve_sfc_pou_type(pou_type)
    if cls is not None:
        return _compile_sfc_class(cls, resolved_type, folder=folder)

    def decorator(c: type) -> type:
        return _compile_sfc_class(c, resolved_type, folder=folder)
    return decorator


def _resolve_sfc_pou_type(pou_type: str) -> POUType:
    """Resolve pou_type string, rejecting FUNCTION."""
    if pou_type == "PROGRAM":
        return POUType.PROGRAM
    if pou_type in ("FB", "FUNCTION_BLOCK"):
        return POUType.FUNCTION_BLOCK
    if pou_type == "FUNCTION":
        raise CompileError(
            "SFC cannot be used with FUNCTION POUs (SFC requires state)"
        )
    raise CompileError(
        f"Invalid pou_type '{pou_type}' for @sfc. "
        f"Valid options: 'PROGRAM', 'FB', 'FUNCTION_BLOCK'"
    )

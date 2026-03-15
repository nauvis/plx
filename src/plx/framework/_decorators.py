"""POU decorators: @fb, @program, @function, @fb_method.

These orchestrate the full compilation pipeline — collecting variable
descriptors, parsing the ``logic()`` method source, compiling via AST
transformation, and assembling the resulting POU IR node.

Compilation is eager (happens at decoration time), so errors surface
at import time.
"""

from __future__ import annotations

import ast
import inspect
import io
import tokenize
from dataclasses import dataclass
from typing import Any

from plx.model.pou import (
    AccessSpecifier,
    Language,
    Method,
    Network,
    POU,
    POUInterface,
    POUType,
)
from plx.model.types import TypeRef
from plx.model.variables import Variable

from ._compiler import ASTCompiler
from ._compiler_core import CompileContext, CompileError, resolve_annotation
from ._registry import register_pou
from ._compilation_helpers import (
    _build_compile_context,
    _build_var_context,
    _detect_parent_pou,
    _discover_enums,
    _parse_function_source,
)
from ._descriptors import VarDescriptor, VarDirection, _mro_upsert
from ._properties import (
    PropDescriptor,
    _collect_properties,
    _compile_property,
)


# ---------------------------------------------------------------------------
# @fb_method decorator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _MethodMarker:
    """Stored as ``func._plx_marker`` on @fb_method-decorated functions."""
    access: AccessSpecifier


def fb_method(
    func: Any = None,
    *,
    access: AccessSpecifier = AccessSpecifier.PUBLIC,
) -> Any:
    """Mark a function as a PLC method on a function block.

    Can be used as ``@fb_method`` or ``@fb_method(access=PRIVATE)``.

    Method parameters (with type annotations) become VAR_INPUT.
    The return annotation becomes the method's return type.

    Example::

        @fb
        class Conveyor:
            speed: REAL

            def logic(self):
                pass

            @fb_method
            def start(self, target_speed: REAL) -> BOOL:
                self.speed = target_speed
                return True

            @fb_method(access=PRIVATE)
            def _reset_internals(self):
                self.speed = 0.0
    """
    marker = _MethodMarker(access=access)

    def _apply(fn: Any) -> Any:
        fn._plx_marker = marker
        return fn

    if func is not None:
        return _apply(func)
    return _apply


def _is_method(obj: object) -> bool:
    """Check if an object is a @fb_method-decorated function."""
    return callable(obj) and isinstance(
        getattr(obj, '_plx_marker', None), _MethodMarker,
    )


def _collect_methods(cls: type) -> list[tuple[str, Any, AccessSpecifier]]:
    """Collect @fb_method-decorated functions from *cls* and its MRO.

    Returns ``(name, function, access)`` tuples.  Parent methods come
    first; child methods with the same name override the parent's.
    """
    seen: set[str] = set()
    collected: list[tuple[str, Any, AccessSpecifier]] = []

    # Walk MRO in reverse so parent methods appear first
    for base in reversed(cls.__mro__):
        if base is object:
            continue
        for attr_name, value in base.__dict__.items():
            if not _is_method(value):
                continue
            marker = value._plx_marker
            _mro_upsert(collected, seen, attr_name, (attr_name, value, marker.access))

    return collected


def _compile_method(
    method_name: str,
    method_func: Any,
    method_access: AccessSpecifier,
    cls: type,
    declared_vars: dict[str, str],
    static_var_types: dict[str, TypeRef],
    source_file: str,
) -> Method:
    """Compile a single @fb_method-decorated function into a Method IR node."""

    context_name = f"{cls.__name__}.{method_name}()"
    func_def, _, start_lineno = _parse_function_source(
        method_func, context_name, validate_self_only=False,
    )

    # Extract parameters → method input_vars
    method_input_vars: list[Variable] = []
    method_declared_vars = dict(declared_vars)  # copy — includes FB vars

    for arg in func_def.args.args:
        param_name = arg.arg
        if param_name == "self":
            continue

        if arg.annotation is None:
            raise CompileError(
                f"Method parameter '{param_name}' in {context_name} "
                f"must have a type annotation"
            )

        type_ref = _resolve_method_annotation(arg.annotation, cls, method_name)
        method_input_vars.append(Variable(name=param_name, data_type=type_ref))
        method_declared_vars[param_name] = VarDirection.INPUT

    # Extract return type
    return_type: TypeRef | None = None
    if func_def.returns is not None:
        return_type = _resolve_method_annotation(func_def.returns, cls, method_name)

    # Create compile context (includes FB's vars + method params)
    ctx = _build_compile_context(
        method_func, cls,
        method_declared_vars, static_var_types,
        start_lineno, source_file,
    )

    # Compile body
    compiler = ASTCompiler(ctx)
    statements = compiler.compile_body(func_def)

    # Assemble Method
    method_interface = POUInterface(
        input_vars=method_input_vars,
        static_vars=ctx.generated_static_vars,
        temp_vars=ctx.generated_temp_vars,
    )

    return Method(
        name=method_name,
        return_type=return_type,
        access=method_access,
        interface=method_interface,
        networks=[Network(statements=statements)],
    )


def _resolve_method_annotation(ann: ast.expr, cls: type, method_name: str) -> TypeRef | None:
    """Resolve a type annotation in a @fb_method context."""
    return resolve_annotation(
        ann,
        location_hint=f"{cls.__name__}.{method_name}()",
    )


# ---------------------------------------------------------------------------
# Language validation
# ---------------------------------------------------------------------------

def _validate_language(language: str | None) -> Language | None:
    """Validate and convert a language string to a Language enum value."""
    if language is None:
        return None
    if language == "SFC":
        raise CompileError(
            "language='SFC' is not supported on @fb/@program/@function. "
            "Use @sfc instead."
        )
    try:
        return Language(language)
    except ValueError:
        valid = ", ".join(f'"{v.value}"' for v in Language)
        raise CompileError(
            f"Invalid language '{language}'. Valid options: {valid}"
        ) from None


# ---------------------------------------------------------------------------
# Comment extraction
# ---------------------------------------------------------------------------

def _extract_comments(source: str) -> dict[int, str]:
    """Extract standalone comments from source.

    Returns ``{line_number: text}`` where *line_number* is 1-based and
    *text* is the comment content with the leading ``#`` and whitespace
    stripped.  Only standalone comments (nothing before ``#`` on the line)
    are included; inline comments and empty ``#`` lines are excluded.
    """
    comments: dict[int, str] = {}
    source_lines = source.splitlines()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            line_idx = tok.start[0] - 1
            if line_idx >= len(source_lines):
                continue
            # Only standalone comments (nothing before # on the line)
            preceding = source_lines[line_idx][:tok.start[1]].strip()
            if preceding:
                continue
            text = tok.string[1:].strip()  # strip '#' + whitespace
            if text:
                comments[tok.start[0]] = text
    except tokenize.TokenError as exc:
        import warnings
        warnings.warn(
            f"plx: failed to tokenize source for comment extraction: {exc}",
            stacklevel=2,
        )
    return comments


def _split_body_by_comments(
    func_def: ast.FunctionDef,
    comments: dict[int, str],
) -> list[tuple[str | None, list[ast.stmt]]]:
    """Split a function body into groups separated by standalone comments.

    Only top-level comments (not inside control structures) trigger splits.
    Consecutive comments are merged with ``"\\n"``.  Trailing comments after
    the last statement are discarded.

    Returns ``[(comment_or_None, [ast_nodes]), ...]``.
    """
    body = func_def.body
    if not body or not comments:
        return [(None, list(body))]

    # Determine which comment lines are top-level (not inside any body node)
    top_level_comments: set[int] = set()
    for line_no in comments:
        inside = False
        for node in body:
            # A comment is inside a node if the node spans multiple lines
            # and the comment falls within those lines (excluding the first
            # line, which is the node's own header line).
            if node.lineno < line_no and node.end_lineno is not None and line_no <= node.end_lineno:
                inside = True
                break
        if not inside:
            top_level_comments.add(line_no)

    if not top_level_comments:
        return [(None, list(body))]

    # Walk body nodes, splitting on preceding top-level comments
    groups: list[tuple[str | None, list[ast.stmt]]] = []
    current_comment: str | None = None
    current_nodes: list[ast.stmt] = []
    last_end: int = func_def.lineno + 1  # line after 'def ..():'

    for node in body:
        # Find top-level comments between last_end and this node
        preceding: list[int] = sorted(
            ln for ln in top_level_comments if last_end <= ln < node.lineno
        )

        if preceding:
            # Flush current group if it has nodes
            if current_nodes:
                groups.append((current_comment, current_nodes))
                current_comment = None
                current_nodes = []

            # Merge consecutive comment lines
            merged = "\n".join(comments[ln] for ln in preceding)
            if current_comment is not None:
                # Merge with unflushed comment that had no nodes
                current_comment = current_comment + "\n" + merged
            else:
                current_comment = merged

        current_nodes.append(node)
        last_end = (node.end_lineno or node.lineno) + 1

    # Flush final group (trailing comments with no following node are discarded)
    if current_nodes:
        groups.append((current_comment, current_nodes))

    if not groups:
        return [(None, list(body))]

    return groups


# ---------------------------------------------------------------------------
# Core compilation pipeline
# ---------------------------------------------------------------------------

def _parse_logic_source(cls: type) -> tuple[ast.FunctionDef, str, int]:
    """Extract logic() source, parse to AST, validate signature.

    Returns ``(func_def, source, start_lineno)``.
    """
    if not hasattr(cls, "logic"):
        raise CompileError(
            f"POU class '{cls.__name__}' must have a logic() method"
        )

    return _parse_function_source(
        cls.logic,
        f"{cls.__name__}.logic()",
        validate_self_only=True,
    )


def _compile_logic_networks(
    func_def: ast.FunctionDef,
    ctx: CompileContext,
    source: str,
) -> list[Network]:
    """Compile the logic() body into networks (split by comments)."""
    compiler = ASTCompiler(ctx)
    comments = _extract_comments(source)
    groups = _split_body_by_comments(func_def, comments)

    networks: list[Network] = []
    for comment, nodes in groups:
        stmts = compiler.compile_statements(nodes)
        networks.append(Network(comment=comment, statements=stmts))
    return networks


def _compile_all_methods(
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
) -> list[Method]:
    """Compile all @fb_method-decorated functions on *cls*."""
    compiled_methods: list[Method] = []
    for method_name, method_func, method_access in _collect_methods(cls):
        compiled_methods.append(_compile_method(
            method_name=method_name,
            method_func=method_func,
            method_access=method_access,
            cls=cls,
            declared_vars=declared_vars,
            static_var_types=static_var_types,
            source_file=source_file,
        ))
    return compiled_methods


def _compile_all_properties(
    cls: type,
    declared_vars: dict[str, VarDirection],
    static_var_types: dict[str, TypeRef],
    source_file: str,
) -> list:
    """Compile all @fb_property-decorated properties on *cls*."""
    from plx.model.pou import Property as PropertyModel
    compiled: list[PropertyModel] = []
    for prop_name, marker in _collect_properties(cls):
        compiled.append(_compile_property(
            prop_name=prop_name,
            marker=marker,
            cls=cls,
            declared_vars=declared_vars,
            static_var_types=static_var_types,
            source_file=source_file,
        ))
    return compiled


def _compile_pou_class(
    cls: type,
    pou_type: POUType,
    language: Language | None = None,
    folder: str = "",
    implements: list[str] | None = None,
) -> type:
    """Core compilation pipeline shared by @fb, @program, @function."""

    extends = _detect_parent_pou(cls)
    var_groups, declared_vars, static_var_types = _build_var_context(cls)
    # Snapshot before body compilation mutates declared_vars with temp vars
    descriptor_vars = dict(declared_vars)

    has_logic = hasattr(cls, "logic")

    # FUNCTION POUs always require logic() (return type comes from annotation)
    if not has_logic and pou_type == POUType.FUNCTION:
        raise CompileError(
            f"FUNCTION '{cls.__name__}' must have a logic() method "
            f"with a return type annotation"
        )

    networks: list[Network] = []
    generated_static_vars: list[Variable] = []
    generated_temp_vars: list[Variable] = []
    return_type: TypeRef | None = None

    if has_logic:
        func_def, source, start_lineno = _parse_logic_source(cls)

        # For FUNCTION POUs, extract return type from logic() annotation
        if pou_type == POUType.FUNCTION:
            if func_def.returns is None:
                raise CompileError(
                    f"FUNCTION '{cls.__name__}' requires a return type — "
                    f"annotate logic(): def logic(self) -> REAL:"
                )
            return_type = resolve_annotation(
                func_def.returns,
                location_hint=f"{cls.__name__}.logic()",
            )

        try:
            source_file = inspect.getfile(cls)
        except (TypeError, OSError):
            source_file = "<unknown>"

        ctx = _build_compile_context(
            cls.logic, cls,
            declared_vars, static_var_types,
            start_lineno, source_file,
        )
        ctx.known_methods = {name for name, _, _ in _collect_methods(cls)}

        networks = _compile_logic_networks(func_def, ctx, source)
        generated_static_vars = ctx.generated_static_vars
        generated_temp_vars = ctx.generated_temp_vars
    else:
        try:
            source_file = inspect.getfile(cls)
        except (TypeError, OSError):
            source_file = "<unknown>"

    compiled_methods = _compile_all_methods(cls, descriptor_vars, static_var_types, source_file)
    compiled_properties = _compile_all_properties(cls, descriptor_vars, static_var_types, source_file)

    interface = POUInterface(
        input_vars=var_groups["input"],
        output_vars=var_groups["output"],
        inout_vars=var_groups["inout"],
        static_vars=var_groups["static"] + generated_static_vars,
        temp_vars=var_groups["temp"] + generated_temp_vars,
        constant_vars=var_groups["constant"],
        external_vars=var_groups["external"],
    )

    pou = POU(
        pou_type=pou_type,
        name=cls.__name__,
        folder=folder,
        language=language,
        return_type=return_type,
        extends=extends,
        implements=implements or [],
        interface=interface,
        networks=networks,
        methods=compiled_methods,
        properties=compiled_properties,
    )

    cls._compiled_pou = pou
    register_pou(cls)

    @classmethod
    def compile(klass: type) -> POU:
        return klass._compiled_pou

    cls.compile = compile

    return cls


# ---------------------------------------------------------------------------
# Public decorators
# ---------------------------------------------------------------------------

def program(cls: type = None, *, language: str | None = None, folder: str = "") -> Any:
    """Decorate a class as a PROGRAM POU.

    Example::

        @program
        class Main:
            running: Input[BOOL]

            def logic(self):
                pass

        @program(language="FBD")
        class FbdMain:
            ...
    """
    lang = _validate_language(language)
    if cls is not None:
        return _compile_pou_class(cls, POUType.PROGRAM, language=lang, folder=folder)

    def decorator(c: type) -> type:
        return _compile_pou_class(c, POUType.PROGRAM, language=lang, folder=folder)
    return decorator


def fb(cls: type = None, *, language: str | None = None, folder: str = "", implements: list[type] | None = None) -> Any:
    """Decorate a class as a FUNCTION_BLOCK POU.

    Example::

        @fb
        class MyFB:
            sensor: Input[BOOL]
            output: Output[BOOL]

            def logic(self):
                self.output = self.sensor

        @fb(language="LD")
        class LadderFB:
            ...

        @fb(implements=[IMoveable])
        class Motor:
            ...
    """
    lang = _validate_language(language)
    impl = _resolve_implements(implements)
    if cls is not None:
        return _compile_pou_class(cls, POUType.FUNCTION_BLOCK, language=lang, folder=folder, implements=impl)

    def decorator(c: type) -> type:
        return _compile_pou_class(c, POUType.FUNCTION_BLOCK, language=lang, folder=folder, implements=impl)
    return decorator


def _resolve_implements(implements: list[type] | None) -> list[str]:
    """Resolve implements list to interface names."""
    if implements is None:
        return []
    names: list[str] = []
    for iface_cls in implements:
        if not getattr(iface_cls, "__plx_interface__", False):
            raise CompileError(
                f"'{iface_cls.__name__}' is not an @interface-decorated class"
            )
        names.append(iface_cls._compiled_pou.name)
    return names


def function(cls: type = None, *, language: str | None = None, folder: str = "") -> Any:
    """Decorate a class as a FUNCTION POU.

    The return type is taken from the ``logic()`` annotation::

        @function
        class AddOne:
            x: Input[REAL]

            def logic(self) -> REAL:
                return self.x + 1.0

        @function(language="FBD")
        class FbdFunc:
            ...
    """
    lang = _validate_language(language)
    if cls is not None:
        return _compile_pou_class(cls, POUType.FUNCTION, language=lang, folder=folder)

    def decorator(c: type) -> type:
        return _compile_pou_class(c, POUType.FUNCTION, language=lang, folder=folder)
    return decorator


# ---------------------------------------------------------------------------
# @interface decorator
# ---------------------------------------------------------------------------

def interface(cls: type = None, *, folder: str = "") -> Any:
    """Decorate a class as an IEC 61131-3 INTERFACE.

    Can be used as ``@interface`` or ``@interface(folder="...")``.

    Methods decorated with ``@fb_method`` are collected as signatures only
    (parameters + return type, no body compilation).  Supports ``extends``
    via Python class inheritance from another ``@interface``.

    Example::

        @interface
        class IMoveable:
            @fb_method
            def move_to(self, target: REAL) -> BOOL: ...

        @interface
        class IResettable(IMoveable):
            @fb_method
            def reset(self): ...
    """
    def _apply(cls: type) -> type:
        # Determine extends from parent interfaces
        extends: str | None = None
        for base in cls.__mro__[1:]:
            if base is object:
                continue
            if getattr(base, "__plx_interface__", False):
                extends = base._compiled_pou.name
                break

        # Collect @fb_method-decorated functions as signatures only
        method_irs: list[Method] = []
        for method_name, method_func, method_access in _collect_methods(cls):
            # Extract parameters and return type — no body compilation
            func_def, _, _ = _parse_function_source(
                method_func,
                f"{cls.__name__}.{method_name}()",
                validate_self_only=False,
            )

            method_input_vars: list[Variable] = []
            for arg in func_def.args.args:
                if arg.arg == "self":
                    continue
                if arg.annotation is None:
                    raise CompileError(
                        f"Interface method parameter '{arg.arg}' in "
                        f"{cls.__name__}.{method_name}() must have a type annotation"
                    )
                type_ref = resolve_annotation(
                    arg.annotation,
                    location_hint=f"{cls.__name__}.{method_name}()",
                )
                method_input_vars.append(Variable(name=arg.arg, data_type=type_ref))

            return_type_val: TypeRef | None = None
            if func_def.returns is not None:
                return_type_val = resolve_annotation(
                    func_def.returns,
                    location_hint=f"{cls.__name__}.{method_name}()",
                )

            method_irs.append(Method(
                name=method_name,
                return_type=return_type_val,
                access=method_access,
                interface=POUInterface(input_vars=method_input_vars),
            ))

        # Collect @fb_property signatures
        property_irs = []
        for prop_name, marker in _collect_properties(cls):
            from plx.model.pou import Property as PropertyModel
            property_irs.append(PropertyModel(
                name=prop_name,
                data_type=marker.data_type,
                access=marker.access,
                abstract=marker.abstract,
                final=marker.final,
            ))

        pou = POU(
            pou_type=POUType.INTERFACE,
            name=cls.__name__,
            folder=folder,
            extends=extends,
            methods=method_irs,
            properties=property_irs,
        )

        cls._compiled_pou = pou
        cls.__plx_interface__ = True
        register_pou(cls)

        @classmethod
        def compile(klass: type) -> POU:
            return klass._compiled_pou

        cls.compile = compile

        return cls

    if cls is not None:
        return _apply(cls)
    return _apply


# Backward-compat alias — will be removed in a future version
method = fb_method

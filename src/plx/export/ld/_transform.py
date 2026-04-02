"""IR → Ladder Diagram transformation (display only).

Converts Universal IR statements and expressions into a simplified LD
element tree for visual rendering in the web IDE.  Non-LD-native constructs
fall back to inline ST text boxes.

This is NOT a vendor code-generation path.  Vendor-native LD (Beckhoff
TcPOU, Siemens SimaticML FBD/LD, etc.) requires layout metadata, connection
IDs, and exact type-aware mapping — that work belongs in each vendor's
``raise_/`` module.
"""

from __future__ import annotations

from typing import Union

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.pou import Network, POU
from plx.model.statements import (
    Assignment,
    FBInvocation,
    FunctionCallStatement,
    IfStatement,
    Statement,
)
from plx.model.types import NamedTypeRef

from ..st import format_expression, format_statement
from ._model import (
    Box,
    Coil,
    CoilType,
    Contact,
    ContactType,
    LDElement,
    LDNetwork,
    Parallel,
    Pin,
    Rung,
    STBox,
    Series,
)

# Comparison operators that map to LD box elements
_COMPARISON_OPS = {
    BinaryOp.EQ, BinaryOp.NE,
    BinaryOp.GT, BinaryOp.GE,
    BinaryOp.LT, BinaryOp.LE,
}

_BINOP_LABEL: dict[BinaryOp, str] = {
    BinaryOp.EQ: "EQ",
    BinaryOp.NE: "NE",
    BinaryOp.GT: "GT",
    BinaryOp.GE: "GE",
    BinaryOp.LT: "LT",
    BinaryOp.LE: "LE",
}

# Arithmetic operators that map to LD box elements
_ARITHMETIC_OPS = {
    BinaryOp.ADD, BinaryOp.SUB,
    BinaryOp.MUL, BinaryOp.DIV,
    BinaryOp.MOD,
}

_ARITH_LABEL: dict[BinaryOp, str] = {
    BinaryOp.ADD: "ADD",
    BinaryOp.SUB: "SUB",
    BinaryOp.MUL: "MUL",
    BinaryOp.DIV: "DIV",
    BinaryOp.MOD: "MOD",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ir_to_ld(target: Union[POU, list[Network]]) -> LDNetwork:
    """Transform IR into an LD element tree.

    Accepts either a POU (uses its ``networks``) or a raw list of Networks.
    """
    if isinstance(target, POU):
        networks = target.networks
    elif isinstance(target, list):
        networks = target
    else:
        raise TypeError(
            f"ir_to_ld() expects POU or list[Network], got {type(target).__name__}"
        )

    transformer = _LDTransformer()
    return transformer.transform(networks)


# ---------------------------------------------------------------------------
# Transformer
# ---------------------------------------------------------------------------

class _LDTransformer:
    """Converts IR networks/statements/expressions into LD elements."""

    def transform(self, networks: list[Network]) -> LDNetwork:
        rungs: list[Rung] = []
        for net in networks:
            for i, stmt in enumerate(net.statements):
                rung = self._transform_statement(stmt)
                # Propagate network comment to the first rung of each network
                if i == 0 and net.comment:
                    rung = rung.model_copy(update={"comment": net.comment})
                rungs.append(rung)
        return LDNetwork(rungs=rungs)

    # -- Statement dispatch ------------------------------------------------

    def _transform_statement(self, stmt: Statement) -> Rung:
        if isinstance(stmt, Assignment):
            return self._transform_assignment(stmt)
        if isinstance(stmt, FBInvocation):
            return self._transform_fb_invocation(stmt)
        if isinstance(stmt, FunctionCallStatement):
            return self._transform_function_call_stmt(stmt)
        if isinstance(stmt, IfStatement):
            return self._transform_if_statement(stmt)
        # Everything else → ST fallback
        return self._st_fallback_rung(stmt)

    def _transform_assignment(self, stmt: Assignment) -> Rung:
        target_str = format_expression(stmt.target)

        # x := TRUE  → unconditional SET (latch)
        if isinstance(stmt.value, LiteralExpr) and stmt.value.value == "TRUE":
            return Rung(outputs=[Coil(variable=target_str, coil_type=CoilType.SET)])

        # x := FALSE  → unconditional RESET (unlatch)
        if isinstance(stmt.value, LiteralExpr) and stmt.value.value == "FALSE":
            return Rung(outputs=[Coil(variable=target_str, coil_type=CoilType.RESET)])

        # Arithmetic expression → Box with output pin (before boolean check,
        # since arithmetic ops are not boolean)
        if isinstance(stmt.value, BinaryExpr) and stmt.value.op in _ARITHMETIC_OPS:
            box = self._arithmetic_box(stmt.value, target_str)
            return Rung(outputs=[box])

        # Function call expression assigned to a variable → Box with output pin.
        # This must come before the boolean check: y := ABS(x) is a box, not
        # a contact network feeding a coil.
        if isinstance(stmt.value, FunctionCallExpr):
            box = self._function_call_box(stmt.value, target_str)
            return Rung(outputs=[box])

        # Type conversion → Box with output pin
        if isinstance(stmt.value, TypeConversionExpr):
            box = self._type_conversion_box(stmt.value, target_str)
            return Rung(outputs=[box])

        # Boolean expression → contact network → normal coil
        if self._is_boolean_expr(stmt.value):
            contact_network = self._transform_expr(stmt.value)
            coil = Coil(variable=target_str)
            return Rung(input_circuit=contact_network, outputs=[coil])

        # Non-boolean assignment → ST fallback
        return self._st_fallback_rung(stmt)

    def _transform_fb_invocation(self, stmt: FBInvocation) -> Rung:
        input_pins = [
            Pin(name=name, expression=format_expression(expr))
            for name, expr in stmt.inputs.items()
        ]
        output_pins = [
            Pin(name=name, expression=format_expression(expr))
            for name, expr in stmt.outputs.items()
        ]
        instance_label = stmt.instance_name if isinstance(stmt.instance_name, str) else format_expression(stmt.instance_name)
        type_name = stmt.fb_type.name if isinstance(stmt.fb_type, NamedTypeRef) else instance_label
        box = Box(
            name=instance_label,
            type_name=type_name,
            input_pins=input_pins,
            output_pins=output_pins,
        )
        return Rung(outputs=[box])

    def _transform_function_call_stmt(self, stmt: FunctionCallStatement) -> Rung:
        input_pins = [
            Pin(
                name=arg.name or f"IN{i + 1}",
                expression=format_expression(arg.value),
            )
            for i, arg in enumerate(stmt.args)
        ]
        box = Box(
            name=stmt.function_name,
            type_name=stmt.function_name,
            input_pins=input_pins,
        )
        return Rung(outputs=[box])

    def _transform_if_statement(self, stmt: IfStatement) -> Rung:
        # Only handle simple IF (no ELSIF, no ELSE)
        if stmt.elsif_branches or stmt.else_body:
            return self._st_fallback_rung(stmt)

        body = stmt.if_branch.body
        condition = stmt.if_branch.condition

        if not body:
            return self._st_fallback_rung(stmt)

        # -- Multi-statement body: all SET/RESET literals → multi-coil rung --
        if len(body) > 1:
            coils = self._try_multi_coil(body)
            if coils is not None:
                contact_network = self._make_condition_circuit(condition)
                return Rung(input_circuit=contact_network, outputs=coils)
            return self._st_fallback_rung(stmt)

        # -- Single-statement body --
        body_stmt = body[0]

        # IF cond THEN x := TRUE/FALSE → SET/RESET coil
        if (
            isinstance(body_stmt, Assignment)
            and isinstance(body_stmt.value, LiteralExpr)
            and body_stmt.value.value in ("TRUE", "FALSE")
        ):
            target_str = format_expression(body_stmt.target)
            coil_type = (
                CoilType.SET if body_stmt.value.value == "TRUE"
                else CoilType.RESET
            )
            contact_network = self._make_condition_circuit(condition)
            coil = Coil(variable=target_str, coil_type=coil_type)
            return Rung(input_circuit=contact_network, outputs=[coil])

        # IF cond THEN y := bool_expr → condition AND value → normal coil
        if (
            isinstance(body_stmt, Assignment)
            and self._is_boolean_expr(body_stmt.value)
        ):
            target_str = format_expression(body_stmt.target)
            cond_element = self._transform_expr(condition)
            value_element = self._transform_expr(body_stmt.value)
            # AND the condition with the value in a series
            series_elements = self._unwrap_series(cond_element) + self._unwrap_series(value_element)
            input_circuit: LDElement = (
                series_elements[0] if len(series_elements) == 1
                else Series(elements=series_elements)
            )
            coil = Coil(variable=target_str)
            return Rung(input_circuit=input_circuit, outputs=[coil])

        # IF cond THEN fb_call → Box with EN input
        if isinstance(body_stmt, FBInvocation):
            return self._if_fb_invocation(condition, body_stmt)

        # IF cond THEN func_call → Box with EN input
        if isinstance(body_stmt, FunctionCallStatement):
            return self._if_function_call(condition, body_stmt)

        # Complex IF → fallback
        return self._st_fallback_rung(stmt)

    def _try_multi_coil(self, body: list[Statement]) -> list[Coil] | None:
        """If every statement in body is a SET or RESET literal assignment,
        return the list of coils. Otherwise return None."""
        coils: list[Coil] = []
        for stmt in body:
            if not isinstance(stmt, Assignment):
                return None
            if not isinstance(stmt.value, LiteralExpr):
                return None
            if stmt.value.value == "TRUE":
                coils.append(Coil(
                    variable=format_expression(stmt.target),
                    coil_type=CoilType.SET,
                ))
            elif stmt.value.value == "FALSE":
                coils.append(Coil(
                    variable=format_expression(stmt.target),
                    coil_type=CoilType.RESET,
                ))
            else:
                return None
        return coils if coils else None

    def _make_condition_circuit(self, condition: Expression) -> LDElement:
        """Transform an IF condition into a contact network."""
        if self._is_boolean_expr(condition):
            return self._transform_expr(condition)
        return STBox(st_text=format_expression(condition))

    def _unwrap_series(self, element: LDElement) -> list[LDElement]:
        """Unwrap a Series into its elements, or wrap a single element."""
        if isinstance(element, Series):
            return list(element.elements)
        return [element]

    def _if_fb_invocation(self, condition: Expression, body_stmt: FBInvocation) -> Rung:
        input_pins = [
            Pin(name=name, expression=format_expression(expr))
            for name, expr in body_stmt.inputs.items()
        ]
        output_pins = [
            Pin(name=name, expression=format_expression(expr))
            for name, expr in body_stmt.outputs.items()
        ]
        en_circuit = self._make_condition_circuit(condition)
        instance_label = body_stmt.instance_name if isinstance(body_stmt.instance_name, str) else format_expression(body_stmt.instance_name)
        type_name = body_stmt.fb_type.name if isinstance(body_stmt.fb_type, NamedTypeRef) else instance_label
        box = Box(
            name=instance_label,
            type_name=type_name,
            input_pins=input_pins,
            output_pins=output_pins,
            en_input=en_circuit,
        )
        return Rung(outputs=[box])

    def _if_function_call(self, condition: Expression, body_stmt: FunctionCallStatement) -> Rung:
        input_pins = [
            Pin(
                name=arg.name or f"IN{i + 1}",
                expression=format_expression(arg.value),
            )
            for i, arg in enumerate(body_stmt.args)
        ]
        en_circuit = self._make_condition_circuit(condition)
        box = Box(
            name=body_stmt.function_name,
            type_name=body_stmt.function_name,
            input_pins=input_pins,
            en_input=en_circuit,
        )
        return Rung(outputs=[box])

    def _st_fallback_rung(self, stmt: Statement) -> Rung:
        st_text = format_statement(stmt)
        return Rung(outputs=[STBox(st_text=st_text)])

    # -- Expression → contact network -------------------------------------

    def _transform_expr(self, expr: Expression) -> LDElement:
        if isinstance(expr, VariableRef):
            return Contact(variable=expr.name, contact_type=ContactType.NO)

        if isinstance(expr, UnaryExpr) and expr.op == UnaryOp.NOT:
            return self._transform_not(expr)

        if isinstance(expr, BinaryExpr):
            if expr.op == BinaryOp.AND:
                return self._flatten_series(expr)
            if expr.op == BinaryOp.OR:
                return self._flatten_parallel(expr)
            if expr.op in _COMPARISON_OPS:
                return self._comparison_box(expr)

        if isinstance(expr, MemberAccessExpr):
            return Contact(
                variable=format_expression(expr),
                contact_type=ContactType.NO,
            )

        if isinstance(expr, LiteralExpr):
            return Contact(variable=expr.value, contact_type=ContactType.NO)

        if isinstance(expr, SystemFlagExpr):
            if expr.flag == SystemFlag.FIRST_SCAN:
                return Contact(variable="FirstScan", contact_type=ContactType.NO)

        if isinstance(expr, FunctionCallExpr):
            input_pins = [
                Pin(
                    name=arg.name or f"IN{i + 1}",
                    expression=format_expression(arg.value),
                )
                for i, arg in enumerate(expr.args)
            ]
            return Box(
                name=expr.function_name,
                type_name=expr.function_name,
                input_pins=input_pins,
            )

        if isinstance(expr, BitAccessExpr):
            return Contact(
                variable=format_expression(expr),
                contact_type=ContactType.NO,
            )

        if isinstance(expr, ArrayAccessExpr):
            return Contact(
                variable=format_expression(expr),
                contact_type=ContactType.NO,
            )

        # Fallback: inline ST
        return STBox(st_text=format_expression(expr))

    def _transform_not(self, expr: UnaryExpr) -> LDElement:
        """Transform NOT expr into an NC contact or equivalent."""
        operand = expr.operand

        # NOT variable → NC contact
        if isinstance(operand, VariableRef):
            return Contact(variable=operand.name, contact_type=ContactType.NC)

        # NOT member.access → NC contact
        if isinstance(operand, MemberAccessExpr):
            return Contact(
                variable=format_expression(operand),
                contact_type=ContactType.NC,
            )

        # NOT literal → NC contact
        if isinstance(operand, LiteralExpr):
            return Contact(variable=operand.value, contact_type=ContactType.NC)

        # NOT bit.access → NC contact
        if isinstance(operand, BitAccessExpr):
            return Contact(
                variable=format_expression(operand),
                contact_type=ContactType.NC,
            )

        # NOT array[access] → NC contact
        if isinstance(operand, ArrayAccessExpr):
            return Contact(
                variable=format_expression(operand),
                contact_type=ContactType.NC,
            )

        # NOT of function call or complex expression → STBox fallback
        return STBox(st_text=f"NOT ({format_expression(operand)})")

    # -- Box constructors --------------------------------------------------

    def _arithmetic_box(self, expr: BinaryExpr, target_str: str) -> Box:
        """Create an arithmetic box (ADD/SUB/MUL/DIV/MOD) with output pin."""
        label = _ARITH_LABEL[expr.op]
        return Box(
            name=label,
            type_name=label,
            input_pins=[
                Pin(name="IN1", expression=format_expression(expr.left)),
                Pin(name="IN2", expression=format_expression(expr.right)),
            ],
            output_pins=[Pin(name="OUT", expression=target_str)],
        )

    def _function_call_box(self, expr: FunctionCallExpr, target_str: str) -> Box:
        """Create a function call box with output pin for the assignment target."""
        input_pins = [
            Pin(
                name=arg.name or f"IN{i + 1}",
                expression=format_expression(arg.value),
            )
            for i, arg in enumerate(expr.args)
        ]
        return Box(
            name=expr.function_name,
            type_name=expr.function_name,
            input_pins=input_pins,
            output_pins=[Pin(name="OUT", expression=target_str)],
        )

    def _type_conversion_box(self, expr: TypeConversionExpr, target_str: str) -> Box:
        """Create a type conversion box."""
        from plx.model.types import PrimitiveTypeRef
        if isinstance(expr.target_type, PrimitiveTypeRef):
            type_name = f"TO_{expr.target_type.type.value}"
        elif isinstance(expr.target_type, NamedTypeRef):
            type_name = f"TO_{expr.target_type.name}"
        else:
            type_name = f"TO_{expr.target_type.kind}"
        return Box(
            name=type_name,
            type_name=type_name,
            input_pins=[Pin(name="IN", expression=format_expression(expr.source))],
            output_pins=[Pin(name="OUT", expression=target_str)],
        )

    # -- Flattening helpers ------------------------------------------------

    def _flatten_series(self, expr: BinaryExpr) -> Series:
        """Flatten nested AND into a single Series."""
        elements: list[LDElement] = []
        self._collect_and(expr, elements)
        return Series(elements=elements)

    def _collect_and(self, expr: Expression, out: list[LDElement]) -> None:
        if isinstance(expr, BinaryExpr) and expr.op == BinaryOp.AND:
            self._collect_and(expr.left, out)
            self._collect_and(expr.right, out)
        else:
            out.append(self._transform_expr(expr))

    def _flatten_parallel(self, expr: BinaryExpr) -> Parallel:
        """Flatten nested OR into a single Parallel."""
        branches: list[LDElement] = []
        self._collect_or(expr, branches)
        return Parallel(branches=branches)

    def _collect_or(self, expr: Expression, out: list[LDElement]) -> None:
        if isinstance(expr, BinaryExpr) and expr.op == BinaryOp.OR:
            self._collect_or(expr.left, out)
            self._collect_or(expr.right, out)
        else:
            out.append(self._transform_expr(expr))

    def _comparison_box(self, expr: BinaryExpr) -> Box:
        label = _BINOP_LABEL[expr.op]
        return Box(
            name=label,
            type_name=label,
            input_pins=[
                Pin(name="IN1", expression=format_expression(expr.left)),
                Pin(name="IN2", expression=format_expression(expr.right)),
            ],
        )

    # -- Type classification -----------------------------------------------

    def _is_boolean_expr(self, expr: Expression) -> bool:
        """Heuristic: is this expression boolean-typed (suitable for contacts)?"""
        if isinstance(expr, VariableRef):
            return True
        if isinstance(expr, LiteralExpr):
            return expr.value in ("TRUE", "FALSE")
        if isinstance(expr, UnaryExpr) and expr.op == UnaryOp.NOT:
            return True
        if isinstance(expr, BinaryExpr):
            if expr.op in (BinaryOp.AND, BinaryOp.OR):
                return True
            if expr.op in _COMPARISON_OPS:
                return True
        if isinstance(expr, MemberAccessExpr):
            return True
        if isinstance(expr, SystemFlagExpr):
            return True
        if isinstance(expr, FunctionCallExpr):
            return True
        if isinstance(expr, BitAccessExpr):
            return True
        if isinstance(expr, ArrayAccessExpr):
            return True
        return False

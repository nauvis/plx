"""Expression rewrite rules for AB math function compatibility.

These rules transform IEC math function calls that have no native AB
equivalent into expressions using only AB-supported primitives.  They
live in the public package so the private AB raise pass can import them.

Usage in the AB raise pass::

    from plx.framework._math_rewrites import (
        rewrite_exp_to_expt, rewrite_ceil, rewrite_floor,
        make_ab_name_rewriter,
    )

    # Apply to all networks in a POU
    rewrite_networks(pou.networks, [rewrite_exp_to_expt, rewrite_ceil, ...])
"""

from __future__ import annotations

from plx.model.expressions import (
    BinaryExpr,
    BinaryOp,
    CallArg,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
)


def rewrite_exp_to_expt(expr: Expression) -> Expression | None:
    """``EXP(x)`` → ``EXPT(2.718281828459045, x)``."""
    if not isinstance(expr, FunctionCallExpr):
        return None
    if expr.function_name != "EXP" or len(expr.args) != 1:
        return None
    return BinaryExpr(
        op=BinaryOp.EXPT,
        left=LiteralExpr(value="2.718281828459045"),
        right=expr.args[0].value,
    )


def rewrite_ceil(expr: Expression) -> Expression | None:
    """``CEIL(x)`` → ``TRUNC(x) + SEL(x > TRUNC(x), 0, 1)``.

    Correctly handles positive numbers (rounds up) and negative numbers
    (TRUNC already rounds toward zero, which is "up" for negatives).
    TRUNC is deterministic so repeating it is safe.
    """
    if not isinstance(expr, FunctionCallExpr):
        return None
    if expr.function_name != "CEIL" or len(expr.args) != 1:
        return None
    x = expr.args[0].value
    trunc_x = FunctionCallExpr(
        function_name="TRUNC",
        args=[CallArg(value=x)],
    )
    # x > TRUNC(x) means there's a fractional part above zero
    cmp = BinaryExpr(op=BinaryOp.GT, left=x, right=trunc_x)
    sel = FunctionCallExpr(
        function_name="SEL",
        args=[
            CallArg(value=cmp),
            CallArg(value=LiteralExpr(value="0")),
            CallArg(value=LiteralExpr(value="1")),
        ],
    )
    return BinaryExpr(op=BinaryOp.ADD, left=trunc_x, right=sel)


def rewrite_floor(expr: Expression) -> Expression | None:
    """``FLOOR(x)`` → ``TRUNC(x) - SEL(TRUNC(x) > x, 1, 0)``.

    TRUNC rounds toward zero.  For negative numbers with a fractional
    part, TRUNC(x) > x is true, so we subtract 1.  For positive numbers,
    TRUNC already equals floor.
    """
    if not isinstance(expr, FunctionCallExpr):
        return None
    if expr.function_name != "FLOOR" or len(expr.args) != 1:
        return None
    x = expr.args[0].value
    trunc_x = FunctionCallExpr(
        function_name="TRUNC",
        args=[CallArg(value=x)],
    )
    # TRUNC(x) > x means we truncated a negative fractional part
    cmp = BinaryExpr(op=BinaryOp.GT, left=trunc_x, right=x)
    sel = FunctionCallExpr(
        function_name="SEL",
        args=[
            CallArg(value=cmp),
            CallArg(value=LiteralExpr(value="0")),
            CallArg(value=LiteralExpr(value="1")),
        ],
    )
    return BinaryExpr(op=BinaryOp.SUB, left=trunc_x, right=sel)


# AB trig function name remapping
_AB_NAME_REMAP: dict[str, str] = {
    "SQRT": "SQR",
    "ASIN": "ASN",
    "ACOS": "ACS",
    "ATAN": "ATN",
    "TRUNC": "TRN",
}


def rewrite_function_name(
    expr: Expression, remap: dict[str, str] | None = None,
) -> Expression | None:
    """Rename function calls according to *remap* mapping.

    If *remap* is ``None``, uses the AB standard name remap
    (SQRT→SQR, ASIN→ASN, ACOS→ACS, ATAN→ATN, TRUNC→TRN).
    """
    if remap is None:
        remap = _AB_NAME_REMAP
    if not isinstance(expr, FunctionCallExpr):
        return None
    new_name = remap.get(expr.function_name)
    if new_name is None:
        return None
    return FunctionCallExpr(function_name=new_name, args=expr.args)


def make_ab_name_rewriter():
    """Return a rewrite function using the default AB name remap."""
    def _rewrite(expr: Expression) -> Expression | None:
        return rewrite_function_name(expr)
    return _rewrite

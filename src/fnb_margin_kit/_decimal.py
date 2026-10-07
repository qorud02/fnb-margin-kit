"""Decimal arithmetic settings independent of caller and DefaultContext changes."""

from decimal import (
    ROUND_HALF_EVEN,
    Context,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)


def decimal_context(precision: int, rounding: str = ROUND_HALF_EVEN) -> Context:
    return Context(
        prec=precision, rounding=rounding, Emin=-999999, Emax=999999,
        capitals=1, clamp=0, flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )

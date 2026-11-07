"""Deterministic money arithmetic. Never use floats; never let a model produce an amount."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.errors import Unprocessable

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999999.99")  # fits NUMERIC(18,2)
MAX_HOURS = Decimal("10000")
MAX_RATE = Decimal("100000000")


def to_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, float):
        # Floats are rejected to avoid binary rounding surprises; the API accepts strings/ints.
        value = repr(value)
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Unprocessable(f"{field} is not a valid number", code="INVALID_AMOUNT") from exc
    if not d.is_finite():
        raise Unprocessable(f"{field} is not a valid number", code="INVALID_AMOUNT")
    return d


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def validate_rate(rate: Decimal) -> Decimal:
    if rate < 0:
        raise Unprocessable("Rates cannot be negative", code="NEGATIVE_AMOUNT")
    if rate > MAX_RATE:
        raise Unprocessable("Rate is too large", code="AMOUNT_TOO_LARGE")
    return money(rate)


def line_amount(kind: str, *, hours: Decimal | None, rate: Decimal | None, fixed: Decimal | None) -> Decimal:
    if kind == "HOURLY":
        if hours is None or rate is None:
            raise Unprocessable("Hourly lines need approved hours and a rate", code="ESTIMATE_INCOMPLETE")
        if hours < 0:
            raise Unprocessable("Hours cannot be negative", code="NEGATIVE_AMOUNT")
        if hours > MAX_HOURS:
            raise Unprocessable("Too many hours on one line", code="AMOUNT_TOO_LARGE")
        if hours.as_tuple().exponent < -2:  # type: ignore[operator]
            raise Unprocessable("Hours support at most 2 decimal places", code="INVALID_AMOUNT")
        amount = money(hours * rate)
    elif kind == "FIXED":
        if fixed is None:
            raise Unprocessable("Fixed lines need an amount", code="ESTIMATE_INCOMPLETE")
        if fixed < 0:
            raise Unprocessable("Amounts cannot be negative", code="NEGATIVE_AMOUNT")
        amount = money(fixed)
    else:
        raise Unprocessable("Unknown line kind", code="INVALID_LINE_KIND")
    if amount > MAX_AMOUNT:
        raise Unprocessable("Amount is too large", code="AMOUNT_TOO_LARGE")
    return amount


def total(amounts: list[Decimal]) -> Decimal:
    result = money(sum(amounts, Decimal("0")))
    if result > MAX_AMOUNT:
        raise Unprocessable("Total is too large", code="AMOUNT_TOO_LARGE")
    return result

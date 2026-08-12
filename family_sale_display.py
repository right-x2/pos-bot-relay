from decimal import Decimal, InvalidOperation


def format_amount(value) -> str:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)

    if amount == amount.to_integral_value():
        return f"{int(amount):,}원"
    return f"{amount:,.2f}원"


def format_change_rate(value) -> str:
    if value is None:
        return "산정 불가 (전년도 0원)"
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)

    text = format(rate.quantize(Decimal("0.1")), "f")
    if text in {"-0.0", "0.0"}:
        text = "0.0"
    prefix = "+" if rate > 0 else ""
    return f"{prefix}{text}%"

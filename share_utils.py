from decimal import Decimal, ROUND_HALF_UP


MIN_SHARE_QUANTITY = Decimal("0.001")
SHARE_QUANTUM = Decimal("0.001")
SHARE_DISPLAY_PLACES = 3


def _to_decimal(value) -> Decimal:
    return Decimal(str(value))


def normalize_share_quantity(value) -> float:
    quantity = _to_decimal(value)
    normalized = quantity.quantize(SHARE_QUANTUM, rounding=ROUND_HALF_UP)
    return float(normalized)


def validate_share_quantity(value, *, field_name="shares") -> float:
    quantity = _to_decimal(value)
    if quantity < MIN_SHARE_QUANTITY:
        raise ValueError(f"{field_name} must be at least {MIN_SHARE_QUANTITY}")
    return normalize_share_quantity(value)


def format_share_quantity(value) -> str:
    normalized = normalize_share_quantity(value)
    return f"{normalized:,.{SHARE_DISPLAY_PLACES}f}"


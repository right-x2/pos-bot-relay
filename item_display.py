from decimal import Decimal, InvalidOperation


ITEM_PERCENTAGE_FIELDS = {
    "EMP_ENURI_RT",
    "GRP_CMP_ENURI_RT",
    "GNRL_MEM_ENURI_RT",
    "JSMN_BLK_ENURI_RT",
    "UCARD_PNT_ACM_RT",
    "OUTLET_PNT_ACM_RT",
    "TCP_PNT_ACM_RT",
    "HCARD_PNT_ACM_RT",
}


def format_product_result_value(field_name: str, value) -> str:
    if field_name not in ITEM_PERCENTAGE_FIELDS:
        return str(value)

    try:
        percentage = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if not percentage.is_finite():
        return str(value)

    if percentage == 0:
        percentage = Decimal("0")
    percentage_text = format(percentage, "f")
    if "." in percentage_text:
        percentage_text = percentage_text.rstrip("0").rstrip(".")
    if not percentage_text:
        percentage_text = "0"
    return f"{percentage_text}%"


def _format_item_date(value) -> str:
    text = str(value).strip()
    if not text:
        return "-"
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def format_item_use_period(start_value, end_value) -> str | None:
    if start_value is None and end_value is None:
        return None

    start_text = _format_item_date(start_value) if start_value is not None else "-"
    end_text = _format_item_date(end_value) if end_value is not None else "-"
    return f"{start_text} ~ {end_text}"

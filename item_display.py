from decimal import Decimal, InvalidOperation


ITEM_PERCENTAGE_FIELDS = {
    "EMP_ENURI_RT",
    "GRP_CMP_ENURI_RT",
    "GNRL_MEM_ENURI_RT",
    "JSMN_BLK_ENURI_RT",
    "UCARD_PNT_ACM_RT",
    "OUTLET_PNT_ACM_RT",
}


def format_product_result_value(field_name: str, value) -> str:
    if field_name not in ITEM_PERCENTAGE_FIELDS:
        return str(value)

    try:
        percentage = Decimal(str(value).strip()) * Decimal("100")
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

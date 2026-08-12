import re
from datetime import datetime


def normalize_refund_key(
    store_code: str,
    sale_date: str,
    pos_no: str,
    deal_no: str,
) -> tuple[str, str, str, str]:
    normalized_store_code = str(store_code or "").strip()
    raw_sale_date = str(sale_date or "").strip()
    normalized_pos_no = str(pos_no or "").strip()
    normalized_deal_no = str(deal_no or "").strip()

    if not normalized_store_code:
        raise ValueError("storeCode is empty")
    if not re.fullmatch(r"\d{8}|\d{4}[-/.]\d{2}[-/.]\d{2}", raw_sale_date):
        raise ValueError("saleDate must be YYYYMMDD or YYYY-MM-DD")

    normalized_sale_date = re.sub(r"[^0-9]", "", raw_sale_date)
    try:
        datetime.strptime(normalized_sale_date, "%Y%m%d")
    except ValueError as error:
        raise ValueError("saleDate must be YYYYMMDD or YYYY-MM-DD") from error

    if not normalized_pos_no:
        raise ValueError("posNo is empty")
    if not normalized_deal_no:
        raise ValueError("dealNo is empty")
    if any(
        len(value) > 30
        for value in (
            normalized_store_code,
            normalized_pos_no,
            normalized_deal_no,
        )
    ):
        raise ValueError("refund key is too long")

    return (
        normalized_store_code,
        normalized_sale_date,
        normalized_pos_no,
        normalized_deal_no,
    )

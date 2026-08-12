import json
from typing import Any

import aiohttp


async def request_refund_operation(
    *,
    target_url: str,
    store_code: str,
    sale_date: str,
    pos_no: str,
    deal_no: str,
) -> dict[str, Any]:
    payload = {
        "storeCode": store_code.strip(),
        "saleDate": sale_date.strip(),
        "posNo": pos_no.strip(),
        "dealNo": deal_no.strip(),
    }
    if not all(payload.values()):
        raise ValueError("점코드, 영업일자, POS번호, 거래번호가 모두 필요합니다.")

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(target_url, json=payload) as response:
            response_text = await response.text()
            status_code = response.status

    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError:
        response_json = {}

    return {
        "status": status_code,
        "response_text": response_text,
        "response_json": response_json,
    }

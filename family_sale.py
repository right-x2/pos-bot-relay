import json
from typing import Any

import aiohttp


async def request_family_sale_sales(
    *,
    target_url: str,
    search_type: str,
    start_datetime: str = "",
    end_datetime: str = "",
    display_end_datetime: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "searchType": search_type.strip(),
        "page": page,
        "pageSize": page_size,
    }
    if start_datetime.strip():
        payload["startDateTime"] = start_datetime.strip()
    if end_datetime.strip():
        payload["endDateTime"] = end_datetime.strip()
    if display_end_datetime.strip():
        payload["displayEndDateTime"] = display_end_datetime.strip()

    timeout = aiohttp.ClientTimeout(total=90)
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

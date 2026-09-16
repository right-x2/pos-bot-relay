import json
from typing import Any

import aiohttp


async def fetch_hpoint_events(
    *,
    target_url: str,
    user_id: str,
    selected_store_code: str,
    page: int,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    normalized_store_code = selected_store_code.strip()

    if not normalized_user_id:
        raise ValueError("사용자 아이디가 필요합니다.")
    if not normalized_store_code:
        raise ValueError("조회할 점포가 필요합니다.")
    if page < 1:
        raise ValueError("page는 1 이상이어야 합니다.")

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            target_url,
            json={
                "userId": normalized_user_id,
                "selectedStoreCode": normalized_store_code,
                "page": page,
            },
        ) as response:
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

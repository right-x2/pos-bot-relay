import json
from typing import Any

import aiohttp


async def fetch_store_access(
    *,
    target_url: str,
    user_id: str,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("사용자 아이디가 필요합니다.")

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            target_url,
            json={"userId": normalized_user_id},
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

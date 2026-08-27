import json
from typing import Any

import aiohttp


async def search_patterns(
    *,
    target_url: str,
    user_id: str,
    pos_no: str,
    search_type: str,
    search_value: str,
    page: int,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    normalized_pos_no = pos_no.strip()
    normalized_search_type = search_type.strip()
    normalized_search_value = search_value.strip()

    if not normalized_user_id:
        raise ValueError(
            "사용자 아이디가 필요합니다."
        )

    if not normalized_pos_no:
        raise ValueError(
            "POS 번호가 필요합니다."
        )

    if normalized_search_type not in (
        "all",
        "0",
        "1",
    ):
        raise ValueError(
            "searchType은 all, 0 또는 1이어야 합니다."
        )

    if page < 1:
        raise ValueError(
            "page는 1 이상이어야 합니다."
        )

    payload = {
        "userId": normalized_user_id,
        "posNo": normalized_pos_no,
        "searchType": (
            None
            if normalized_search_type == "all"
            else normalized_search_type
        ),
        "searchValue": normalized_search_value,
        "page": page,
    }

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:
        async with session.post(
            target_url,
            json=payload,
        ) as response:
            response_text = await response.text()
            status_code = response.status

    try:
        response_json = json.loads(
            response_text
        )
    except json.JSONDecodeError:
        response_json = {}

    return {
        "status": status_code,
        "response_text": response_text,
        "response_json": response_json,
    }

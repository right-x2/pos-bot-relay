import json
from typing import Any

import aiohttp


async def update_pattern(
    *,
    target_url: str,
    user_id: str,
    pattern_group_code: str,
    pattern_code: str,
    pattern_value: str,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    normalized_group_code = (
        pattern_group_code.strip()
    )
    normalized_pattern_code = (
        pattern_code.strip()
    )
    normalized_pattern_value = (
        pattern_value.strip()
    )

    if not normalized_user_id:
        raise ValueError(
            "사용자 아이디가 필요합니다."
        )

    if not normalized_group_code:
        raise ValueError(
            "패턴 그룹 코드가 필요합니다."
        )

    if not normalized_pattern_code:
        raise ValueError(
            "패턴 코드가 필요합니다."
        )

    if not normalized_pattern_value:
        raise ValueError(
            "패턴값이 필요합니다."
        )

    payload = {
        "userId": normalized_user_id,
        "patternGroupCode": normalized_group_code,
        "patternCode": normalized_pattern_code,
        "patternValue": normalized_pattern_value,
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

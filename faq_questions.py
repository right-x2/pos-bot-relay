import json
from typing import Any

import aiohttp


async def fetch_top_faq_questions(
    *,
    target_url: str,
    category: str,
    limit: int = 5,
) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=30)
    payload = {
        "category": category.strip(),
        "limit": limit,
    }

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

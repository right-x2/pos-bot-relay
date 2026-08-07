import json
from typing import Any, Optional

import aiohttp


async def search_items(
    *,
    target_url: str,
    item_type: str,
    code: str = "",
    image_bytes: Optional[bytes] = None,
    image_filename: str = "barcode-image.jpg",
    image_content_type: str = "image/jpeg",
) -> dict[str, Any]:
    normalized_item_type = item_type.strip()
    normalized_code = code.strip()

    if normalized_item_type not in (
        "상품",
        "단품",
    ):
        raise ValueError(
            "상단품구분은 상품 또는 단품이어야 합니다."
        )

    if not normalized_code and not image_bytes:
        raise ValueError(
            "코드 또는 바코드이미지가 필요합니다."
        )

    form = aiohttp.FormData(
        quote_fields=False
    )
    form.add_field(
        "상단품구분",
        normalized_item_type,
        content_type="text/plain",
    )

    # 백엔드 명세상 코드가 있으면 이미지보다 우선한다.
    if normalized_code:
        form.add_field(
            "코드",
            normalized_code,
            content_type="text/plain",
        )
    elif image_bytes:
        form.add_field(
            "바코드이미지",
            image_bytes,
            filename=image_filename,
            content_type=image_content_type,
        )

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:
        async with session.post(
            target_url,
            data=form,
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

import json
from typing import Any, Optional

import aiohttp


async def search_items(
    *,
    target_url: str,
    user_id: str,
    selected_store_code: str,
    item_type: str,
    code: str = "",
    op_code: str = "",
    sale_type: str = "",
    image_bytes: Optional[bytes] = None,
    image_filename: str = "barcode-image.jpg",
    image_content_type: str = "image/jpeg",
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    normalized_item_type = item_type.strip()
    normalized_code = code.strip()

    if not normalized_user_id:
        raise ValueError(
            "사용자 아이디가 필요합니다."
        )

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
        "userId",
        normalized_user_id,
        content_type="text/plain",
    )
    form.add_field(
        "selectedStoreCode",
        selected_store_code.strip(),
        content_type="text/plain",
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
        if normalized_item_type == "상품":
            if op_code.strip():
                form.add_field(
                    "OP_CD",
                    op_code.strip(),
                    content_type="text/plain",
                )
            if sale_type.strip():
                form.add_field(
                    "SALE_TP",
                    sale_type.strip(),
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


async def search_items_by_name(
    *,
    target_url: str,
    user_id: str,
    selected_store_code: str,
    item_type: str,
    keyword: str,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    normalized_store_code = selected_store_code.strip()
    normalized_item_type = item_type.strip()
    normalized_keyword = keyword.strip()

    if not normalized_user_id:
        raise ValueError("사용자 아이디가 필요합니다.")
    if not normalized_store_code:
        raise ValueError("점포코드가 필요합니다.")
    if normalized_item_type not in ("상품", "단품"):
        raise ValueError("상단품구분은 상품 또는 단품이어야 합니다.")
    if len(normalized_keyword) < 2:
        raise ValueError("검색어는 최소 2글자 이상 입력해주세요.")
    if len(normalized_keyword) > 100:
        raise ValueError("검색어는 100자 이하로 입력해주세요.")

    form = aiohttp.FormData(quote_fields=False)
    for field_name, value in (
        ("userId", normalized_user_id),
        ("selectedStoreCode", normalized_store_code),
        ("상단품구분", normalized_item_type),
        ("검색어", normalized_keyword),
    ):
        form.add_field(field_name, value, content_type="text/plain")

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(target_url, data=form) as response:
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

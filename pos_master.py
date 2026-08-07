import json
import re
from typing import Any

import aiohttp


POS_NUMBER_PATTERN = re.compile(r"^\d+$")
POS_RANGE_PATTERN = re.compile(
    r"^(\d+)\s*([~-])\s*(\d+)$"
)


def normalize_pos_no_input(
    pos_no: str,
) -> str:
    normalized = pos_no.strip()

    if not normalized:
        raise ValueError(
            "POS 번호를 입력해주세요."
        )

    if len(normalized) > 1000:
        raise ValueError(
            "POS 번호 입력은 1000자 이하로 입력해주세요."
        )

    if "," in normalized:
        if "~" in normalized or "-" in normalized:
            raise ValueError(
                "목록과 범위 형식은 함께 사용할 수 없습니다."
            )

        pos_numbers = [
            value.strip()
            for value in normalized.split(",")
        ]

        if (
            not pos_numbers
            or any(
                not POS_NUMBER_PATTERN.fullmatch(value)
                for value in pos_numbers
            )
        ):
            raise ValueError(
                "POS 목록은 숫자를 쉼표로 구분해주세요."
            )

        return ",".join(pos_numbers)

    range_match = POS_RANGE_PATTERN.fullmatch(
        normalized
    )
    if range_match:
        start_text = range_match.group(1)
        end_text = range_match.group(3)

        if int(start_text) > int(end_text):
            raise ValueError(
                "POS 범위는 시작 번호가 종료 번호보다 작거나 같아야 합니다."
            )

        return f"{start_text}~{end_text}"

    if not POS_NUMBER_PATTERN.fullmatch(normalized):
        raise ValueError(
            "POS 번호는 단건, 쉼표 목록 또는 정방향 범위로 입력해주세요."
        )

    return normalized


async def create_pos_master(
    *,
    target_url: str,
    pos_no: str,
) -> dict[str, Any]:
    normalized_pos_no = normalize_pos_no_input(
        pos_no
    )

    payload = {
        "posNo": normalized_pos_no,
    }

    timeout = aiohttp.ClientTimeout(
        total=120
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
        "normalized_pos_no": normalized_pos_no,
    }

import asyncio
import json
import os
import sys
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from image_forwarder import (
    download_teams_image_attachment,
    forward_teams_image,
)
from item_search import search_items
from pattern_search import search_patterns
from aiohttp import web

from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.core.teams import TeamsInfo
from botbuilder.core.integration import aiohttp_error_middleware
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)
from botbuilder.schema import Activity, Attachment, ChannelAccount

from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)
from botbuilder.core.teams import TeamsInfo
from botbuilder.schema import (
    Activity,
    Attachment,
    ChannelAccount,
)

CATEGORIES = ["POS공통", "APOS", "키오스크", "PPOS", "POS서버", "HBO"]
KST = timezone(timedelta(hours=9))

TOOL_POS_MASTER_CREATE = "pos_master_create"
TOOL_PRODUCT_SEARCH = "product_search"
TOOL_PRODUCT_LOOKUP = "product_lookup"
TOOL_SINGLE_PRODUCT_LOOKUP = "single_product_lookup"
TOOL_PATTERN_SEARCH = "pattern_search"
TOOL_GENERAL_CHAT = "general_chat"
TOOL_FOOD_KIOSK = "food_kiosk"
TOOL_FOOD_KIOSK_SOLD_OUT = "food_kiosk_sold_out"

TOOL_TITLES = {
    TOOL_POS_MASTER_CREATE: "POS 마스터 생성",
    TOOL_PRODUCT_SEARCH: "상·단품 검색",
    TOOL_PRODUCT_LOOKUP: "상품검색",
    TOOL_SINGLE_PRODUCT_LOOKUP: "단품검색",
    TOOL_PATTERN_SEARCH: "패턴 조회",
    TOOL_GENERAL_CHAT: "일반 질문",
    TOOL_FOOD_KIOSK: "푸드키오스크",
    TOOL_FOOD_KIOSK_SOLD_OUT: "푸드키오스크 품절처리",
}

ITEM_RESULT_FIELDS = (
    ("STORE_CD", "점포코드"),
    ("ITEM_CD", "상품코드"),
    ("ITEM_NM", "상품명"),
    ("BILL_ITEM_NM", "영수증 상품명"),
    ("SALE_KND", "판매구분"),
    ("ITEM_GRP", "상품그룹"),
    ("VEN_CD", "거래처코드"),
    ("PC_CD", "PC코드"),
    ("CORNER_CD", "코너코드"),
    ("USE_YN", "사용여부"),
)

PLU_RESULT_FIELDS = (
    ("STORE_CD", "점포코드"),
    ("PLU_CD", "단품코드"),
    ("SCAN_CD1", "스캔코드1"),
    ("SCAN_CD2", "스캔코드2"),
    ("PLU_NM", "단품명"),
    ("BILL_PLU_NM", "영수증 단품명"),
    ("ITEM_CD", "상품코드"),
    ("ITEM_NM", "상품명"),
    ("BRAND_CD", "브랜드코드"),
    ("PC_CD", "PC코드"),
    ("CORNER_CD", "코너코드"),
    ("GNRL_PRC", "일반가격"),
    ("USE_YN", "사용여부"),
)


class Config:
    PORT = int(os.getenv("PORT", "3978"))
    APP_ID = os.getenv("MicrosoftAppId", "")
    APP_PASSWORD = os.getenv("MicrosoftAppPassword", "")
    APP_TYPE = os.getenv("MicrosoftAppType", "SingleTenant")
    APP_TENANTID = os.getenv("MicrosoftAppTenantId", "")

    INTERNAL_API_URL = os.getenv(
        "INTERNAL_API_URL",
        "http://123.111.174.78:30002/test",
    )

    REGISTER_API_URL = os.getenv(
        "REGISTER_API_URL",
        "http://123.111.174.78:30002/faq-register",
    )

    FEEDBACK_API_URL = os.getenv(
       "FEEDBACK_API_URL",
       "http://123.111.174.78:30002/api/logs/help-yn",
    )

    ITEM_SEARCH_API_URL = os.getenv(
        "ITEM_SEARCH_API_URL",
        "http://123.111.174.78:30002/api/items/search",
    )

    PATTERN_SEARCH_API_URL = os.getenv(
        "PATTERN_SEARCH_API_URL",
        "http://123.111.174.78:30002/api/patterns/search",
    )

CONFIG = Config()

ADAPTER = CloudAdapter(
    ConfigurationBotFrameworkAuthentication(CONFIG)
)


async def on_error(
    turn_context: TurnContext,
    error: Exception,
) -> None:
    print(
        f"[BOT ERROR] {type(error).__name__}: {error}",
        file=sys.stderr,
        flush=True,
    )
    traceback.print_exc()

    try:
        await turn_context.send_activity(
            "봇 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )
    except Exception:
        pass


ADAPTER.on_turn_error = on_error

async def keep_typing(
   turn_context: TurnContext,
   stop_event: asyncio.Event,
) -> None:
   """
   응답이 끝날 때까지 Teams typing activity를 주기적으로 전송한다.
   """
   while not stop_event.is_set():
       try:
           await turn_context.send_activity(
               Activity(type="typing")
           )
       except Exception as error:
           print(
               "[TYPING ERROR]"
               f" type={type(error).__name__}"
               f" message={error}",
               flush=True,
           )
       try:
           await asyncio.wait_for(
               stop_event.wait(),
               timeout=4,
           )
       except asyncio.TimeoutError:
           pass


# 개발용 메모리 캐시
CARD_CACHE: dict[str, dict[str, str]] = {}
PENDING_SEARCH_CACHE: dict[str, dict[str, object]] = {}
PENDING_SEARCH_TTL = timedelta(minutes=5)


def get_tool_session_key(
    activity: Activity,
) -> str:
    conversation_id = (
        activity.conversation.id
        if activity.conversation
        else ""
    )
    sender = activity.from_property
    sender_id = sender.id if sender else ""

    return f"{conversation_id}:{sender_id}"


def is_barcode_image_attachment(
    attachment: Attachment,
) -> bool:
    content_type = str(
        attachment.content_type or ""
    ).strip().lower()

    if content_type.startswith("image/"):
        return bool(
            str(
                attachment.content_url or ""
            ).strip()
        )

    content = attachment.content

    if (
        content_type
        == "application/vnd.microsoft.teams.file.download.info"
        and isinstance(content, dict)
    ):
        file_type = str(
            content.get("fileType", "")
        ).strip().lower().lstrip(".")

        download_url = str(
            content.get("downloadUrl", "")
        ).strip()

        return (
            file_type in {
                "png",
                "jpg",
                "jpeg",
                "gif",
                "webp",
                "bmp",
            }
            and bool(download_url)
        )

    if content_type == "text/html":
        content_text = (
            " ".join(
                str(value)
                for value in content.values()
            )
            if isinstance(content, dict)
            else str(content or "")
        )

        return "<img" in content_text.lower()

    return False


def adaptive_attachment(card: dict) -> Attachment:
    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card,
    )


def create_tool_menu_card() -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "POS 업무 도구",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "처리할 업무를 선택해주세요.",
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "POS 마스터 생성",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_POS_MASTER_CREATE,
                },
            },
            {
                "type": "Action.Submit",
                "title": "상·단품 검색",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_PRODUCT_SEARCH,
                },
            },
            {
                "type": "Action.Submit",
                "title": "패턴 조회",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_PATTERN_SEARCH,
                },
            },
            {
                "type": "Action.Submit",
                "title": "푸드키오스크",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_FOOD_KIOSK,
                },
            },
            {
                "type": "Action.Submit",
                "title": "일반 질문",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_GENERAL_CHAT,
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_food_kiosk_tool_menu_card() -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "푸드키오스크",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "처리할 푸드키오스크 업무를 선택해주세요.",
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "품절처리",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_FOOD_KIOSK_SOLD_OUT,
                },
            },
            {
                "type": "Action.Submit",
                "title": "전체 도구",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_product_search_tool_menu_card() -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "상·단품 검색",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "검색할 대상을 선택해주세요.",
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "상품검색",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_PRODUCT_LOOKUP,
                },
            },
            {
                "type": "Action.Submit",
                "title": "단품검색",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_SINGLE_PRODUCT_LOOKUP,
                },
            },
            {
                "type": "Action.Submit",
                "title": "전체 도구",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_product_search_input_card(
    tool_name: str,
) -> Attachment:
    code_label = (
        "상품코드"
        if tool_name == TOOL_PRODUCT_LOOKUP
        else "단품코드"
    )

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": TOOL_TITLES[tool_name],
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    f"{code_label}를 입력하거나, 5분 안에 "
                    "Teams 채팅창에서 바코드 이미지를 첨부해주세요."
                ),
                "wrap": True,
                "isSubtle": True,
            },
            {
                "type": "Input.Text",
                "id": "search_code",
                "label": code_label,
                "placeholder": f"{code_label} 입력",
                "maxLength": 100,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "코드로 검색",
                "style": "positive",
                "data": {
                    "action": "product_search_code_submit",
                    "tool": tool_name,
                },
            },
            {
                "type": "Action.Submit",
                "title": "상·단품 검색 메뉴",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_PRODUCT_SEARCH,
                },
            },
            {
                "type": "Action.Submit",
                "title": "전체 도구",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_product_search_result_card(
    tool_name: str,
    response_json: dict,
) -> Attachment:
    found = bool(
        response_json.get("found")
    )
    result = response_json.get("result")

    if not isinstance(result, dict):
        result = {}

    field_definitions = (
        ITEM_RESULT_FIELDS
        if tool_name == TOOL_PRODUCT_LOOKUP
        else PLU_RESULT_FIELDS
    )

    facts = [
        {
            "title": "조회 구분",
            "value": str(
                response_json.get("itemType", "-")
                or "-"
            ),
        },
        {
            "title": "입력 코드",
            "value": str(
                response_json.get("inputCode", "-")
                or "-"
            ),
        },
        {
            "title": "바코드",
            "value": str(
                response_json.get("barcodeText", "-")
                or "-"
            ),
        },
        {
            "title": "조회 코드",
            "value": str(
                response_json.get("resolvedCode", "-")
                or "-"
            ),
        },
    ]

    if found:
        for field_name, field_title in field_definitions:
            if (
                field_name in result
                and result[field_name] is not None
            ):
                facts.append(
                    {
                        "title": field_title,
                        "value": str(
                            result[field_name]
                        )[:1000],
                    }
                )

    result_text = (
        "조회 결과를 찾았습니다."
        if found
        else "일치하는 조회 결과가 없습니다."
    )

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": f"{TOOL_TITLES[tool_name]} 결과",
                "weight": "Bolder",
                "size": "Medium",
                "color": (
                    "Good"
                    if found
                    else "Warning"
                ),
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": result_text,
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": facts,
                "spacing": "Medium",
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "다시 검색",
                "data": {
                    "action": "tool_select",
                    "tool": tool_name,
                },
            },
            {
                "type": "Action.Submit",
                "title": "상·단품 검색 메뉴",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_PRODUCT_SEARCH,
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_food_kiosk_status_card(
    tool_name: str,
) -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": TOOL_TITLES[tool_name],
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "실행 도구",
                        "value": tool_name,
                    },
                    {
                        "title": "상태",
                        "value": "API 연동 대기",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": "도구 선택 라우팅만 준비되어 있습니다.",
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "푸드키오스크 메뉴",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_FOOD_KIOSK,
                },
            },
            {
                "type": "Action.Submit",
                "title": "전체 도구",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_pos_master_form_card() -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "POS 마스터 생성",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    "생성할 POS 번호를 입력해주세요. "
                    "현재는 도구 연동을 위한 화면만 동작합니다."
                ),
                "isSubtle": True,
                "wrap": True,
            },
            {
                "type": "Input.Text",
                "id": "pos_no",
                "label": "POS 번호",
                "placeholder": "예: 1111",
                "isRequired": True,
                "errorMessage": "POS 번호를 입력해주세요.",
                "maxLength": 30,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "마스터 생성",
                "style": "positive",
                "data": {
                    "action": "pos_master_create_submit",
                    "tool": TOOL_POS_MASTER_CREATE,
                },
            },
            {
                "type": "Action.Submit",
                "title": "도구 메뉴",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_pattern_search_form_card() -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "패턴 조회",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    "POS 번호를 입력하고 검색 구분을 선택해주세요. "
                    "검색어를 비우면 해당 POS의 전체 패턴을 조회합니다."
                ),
                "isSubtle": True,
                "wrap": True,
            },
            {
                "type": "Input.Text",
                "id": "pos_no",
                "label": "POS 번호",
                "placeholder": "예: 1111",
                "isRequired": True,
                "errorMessage": "POS 번호를 입력해주세요.",
                "maxLength": 30,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "search_type",
                "label": "검색 구분",
                "style": "compact",
                "value": "0",
                "choices": [
                    {
                        "title": "패턴 코드",
                        "value": "0",
                    },
                    {
                        "title": "패턴명",
                        "value": "1",
                    },
                ],
                "isRequired": True,
                "errorMessage": "검색 구분을 선택해주세요.",
            },
            {
                "type": "Input.Text",
                "id": "search_value",
                "label": "검색어 (선택)",
                "placeholder": "패턴 코드 또는 패턴명 입력",
                "maxLength": 100,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "조회",
                "style": "positive",
                "data": {
                    "action": "pattern_search_submit",
                    "tool": TOOL_PATTERN_SEARCH,
                    "page": 1,
                },
            },
            {
                "type": "Action.Submit",
                "title": "도구 메뉴",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_pattern_search_result_card(
    response_json: dict,
) -> Attachment:
    def safe_int(
        value,
        default: int,
    ) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    pos_no = str(
        response_json.get("posNo", "")
        or ""
    )
    pattern_group_code = str(
        response_json.get(
            "patternGroupCode",
            "",
        )
        or ""
    )
    pattern_group_name = str(
        response_json.get(
            "patternGroupName",
            "",
        )
        or ""
    )
    search_type = str(
        response_json.get("searchType", "0")
    )
    search_value = str(
        response_json.get("searchValue", "")
        or ""
    )
    page = safe_int(
        response_json.get("page", 1),
        1,
    )
    page_size = safe_int(
        response_json.get("pageSize", 10),
        10,
    )
    total_count = safe_int(
        response_json.get("totalCount", 0),
        0,
    )
    total_pages = safe_int(
        response_json.get("totalPages", 0),
        0,
    )
    page = max(page, 1)
    page_size = max(page_size, 1)
    total_count = max(total_count, 0)
    total_pages = max(total_pages, 0)
    patterns = response_json.get("patterns")

    if not isinstance(patterns, list):
        patterns = []

    body = [
        {
            "type": "TextBlock",
            "text": "패턴 조회 결과",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": [
                {
                    "title": "POS 번호",
                    "value": pos_no or "-",
                },
                {
                    "title": "패턴 그룹",
                    "value": (
                        f"{pattern_group_code} "
                        f"{pattern_group_name}"
                    ).strip() or "-",
                },
                {
                    "title": "조회 결과",
                    "value": f"총 {total_count}건",
                },
                {
                    "title": "페이지",
                    "value": (
                        f"{page} / "
                        f"{max(total_pages, 1)}"
                        f" ({page_size}건 단위)"
                    ),
                },
            ],
        },
    ]

    if patterns:
        for pattern in patterns[:page_size]:
            if not isinstance(pattern, dict):
                continue

            pattern_code = str(
                pattern.get("patternCode", "")
                or "-"
            )
            pattern_name = str(
                pattern.get("patternName", "")
                or "-"
            )
            pattern_value = str(
                pattern.get("patternValue", "")
                or "-"
            )

            body.append(
                {
                    "type": "Container",
                    "separator": True,
                    "spacing": "Medium",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": (
                                f"{pattern_code} · "
                                f"{pattern_name}"
                            ),
                            "weight": "Bolder",
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": pattern_value[:4000],
                            "wrap": True,
                            "spacing": "Small",
                        },
                    ],
                }
            )
    else:
        body.append(
            {
                "type": "TextBlock",
                "text": "조회된 패턴이 없습니다.",
                "color": "Warning",
                "wrap": True,
                "spacing": "Medium",
            }
        )

    actions = []

    if page > 1:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "이전",
                "data": {
                    "action": "pattern_search_page",
                    "tool": TOOL_PATTERN_SEARCH,
                    "pos_no": pos_no,
                    "search_type": search_type,
                    "search_value": search_value,
                    "page": page - 1,
                },
            }
        )

    if page < total_pages:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "다음",
                "data": {
                    "action": "pattern_search_page",
                    "tool": TOOL_PATTERN_SEARCH,
                    "pos_no": pos_no,
                    "search_type": search_type,
                    "search_value": search_value,
                    "page": page + 1,
                },
            }
        )

    actions.extend(
        [
            {
                "type": "Action.Submit",
                "title": "다시 조회",
                "data": {
                    "action": "tool_select",
                    "tool": TOOL_PATTERN_SEARCH,
                },
            },
            {
                "type": "Action.Submit",
                "title": "도구 메뉴",
                "data": {
                    "action": "tool_menu",
                },
            },
        ]
    )

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body,
        "actions": actions,
    }

    return adaptive_attachment(card)


def create_tool_status_card(
    title: str,
    message: str,
) -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "도구 메뉴",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_pos_master_shell_result_card(
    pos_no: str,
) -> Attachment:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "POS 마스터 생성 도구 준비 완료",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "실행 도구",
                        "value": TOOL_POS_MASTER_CREATE,
                    },
                    {
                        "title": "POS 번호",
                        "value": pos_no,
                    },
                    {
                        "title": "상태",
                        "value": "API 연동 대기",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": (
                    "화면과 Action.Submit 라우팅만 연결된 상태입니다. "
                    "실제 POS 마스터 데이터는 생성하지 않았습니다."
                ),
                "isSubtle": True,
                "wrap": True,
                "spacing": "Medium",
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "다른 도구 선택",
                "data": {
                    "action": "tool_menu",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_answer_card(
    question: str,
    answer: str,
    request_id: str,
    selected: str = "",
) -> Attachment:
    safe_question = question[:1000]
    safe_answer = answer[:12000]

    helpful_action = {
        "type": "Action.Submit",
        "title": "👍 도움됨",
        "data": {
            "action": "feedback",
            "helpful": "Y",
            "request_id": request_id,
            "question": safe_question,
        },
    }

    not_helpful_action = {
        "type": "Action.ShowCard",
        "title": "👎 도움안됨",
        "card": {
            "type": "AdaptiveCard",
            "version": "1.3",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "어떤 점이 도움이 되지 않았나요?",
                    "weight": "Bolder",
                    "wrap": True,
                },
                {
                    "type": "TextBlock",
                    "text": "의견을 남겨주시면 FAQ 개선에 활용하겠습니다.",
                    "wrap": True,
                    "isSubtle": True,
                    "spacing": "Small",
                },
                {
                    "type": "TextBlock",
                    "text": "질문",
                    "weight": "Bolder",
                    "spacing": "Medium",
                    "wrap": True,
                },
                {
                    "type": "TextBlock",
                    "text": safe_question,
                    "wrap": True,
                    "isSubtle": True,
                    "spacing": "Small",
                },
                {
                    "type": "Input.Text",
                    "id": "feedback_text",
                    "isMultiline": True,
                    "placeholder": (
                        "예: 답변이 너무 일반적임 / "
                        "실제 오류코드 설명이 부족함"
                    ),
                },
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "의견 제출",
                    "data": {
                        "action": "feedback",
                        "helpful": "N",
                        "request_id": request_id,
                        "question": safe_question,
                    },
                }
            ],
        },
    }

    if selected == "Y":
        helpful_action["style"] = "positive"
    elif selected == "N":
        not_helpful_action["style"] = "positive"

    body = [
        {
            "type": "TextBlock",
            "text": "POS FAQ 답변",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": "질문",
            "weight": "Bolder",
            "spacing": "Medium",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": safe_question,
            "wrap": True,
            "spacing": "Small",
            "isSubtle": True,
        },
        {
            "type": "TextBlock",
            "text": "답변",
            "weight": "Bolder",
            "spacing": "Medium",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": safe_answer,
            "wrap": True,
            "spacing": "Small",
        },
        {
            "type": "TextBlock",
            "text": "답변이 도움이 되었나요?",
            "wrap": True,
            "spacing": "Medium",
            "isSubtle": True,
        },
    ]

    if selected == "Y":
        body.append(
            {
                "type": "TextBlock",
                "text": "✅ 도움됨으로 제출되었습니다.",
                "wrap": True,
                "spacing": "Small",
                "color": "Good",
            }
        )
    elif selected == "N":
        body.append(
            {
                "type": "TextBlock",
                "text": "✅ 의견이 제출되었습니다.",
                "wrap": True,
                "spacing": "Small",
                "color": "Good",
            }
        )

    card = {
       "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
       "type": "AdaptiveCard",
       "version": "1.3",
       "body": body,
       "actions": (
           []
           if selected in ("Y", "N")
           else [
               helpful_action,
               not_helpful_action,
           ]
       ),
    }

    return adaptive_attachment(card)


def create_register_form_card() -> Attachment:
    choices = [
        {
            "title": value,
            "value": value,
        }
        for value in CATEGORIES
    ]

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": [
            {
                "type": "TextBlock",
                "text": "FAQ 등록 요청",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "등록 요청한 FAQ는 관리자 승인 후 반영됩니다.",
                "wrap": True,
                "isSubtle": True,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "category",
                "label": "업무 구분",
                "style": "compact",
                "placeholder": "업무 구분을 선택해주세요.",
                "choices": choices,
                "isRequired": True,
                "errorMessage": "업무 구분을 선택해주세요.",
            },
            {
                "type": "Input.Text",
                "id": "question",
                "label": "질문",
                "isMultiline": True,
                "placeholder": (
                    "예: 카드 승인 오류 발생 시 "
                    "어떻게 처리하나요?"
                ),
                "isRequired": True,
                "errorMessage": "질문을 입력해주세요.",
            },
            {
                "type": "Input.Text",
                "id": "answer",
                "label": "답변",
                "isMultiline": True,
                "placeholder": (
                    "예: VAN 통신 상태 확인 후 "
                    "승인 응답코드를 확인합니다."
                ),
                "isRequired": True,
                "errorMessage": "답변을 입력해주세요.",
            },
            {
                "type": "Input.Text",
                "id": "keywords",
                "label": "키워드",
                "placeholder": (
                    "예: 카드승인,VAN,응답코드,E030"
                ),
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "등록 요청",
                "data": {
                    "action": "faq_register_submit",
                },
            },
            {
                "type": "Action.Submit",
                "title": "취소",
                "data": {
                    "action": "faq_register_cancel",
                },
            },
        ],
    }

    return adaptive_attachment(card)


def create_register_result_card(
    success: bool,
    category: str = "",
    question: str = "",
    request_id: object = None,
    message: str = "",
) -> Attachment:
    if success:
        body = [
            {
                "type": "TextBlock",
                "text": "✅ FAQ 등록 요청 완료",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "요청 번호",
                        "value": str(request_id or "-"),
                    },
                    {
                        "title": "업무 구분",
                        "value": category,
                    },
                    {
                        "title": "질문",
                        "value": question,
                    },
                    {
                        "title": "상태",
                        "value": "관리자 승인 대기",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": (
                    message
                    or "FAQ 등록 요청이 완료되었습니다."
                ),
                "wrap": True,
                "spacing": "Medium",
            },
        ]
    else:
        body = [
            {
                "type": "TextBlock",
                "text": "FAQ 등록 요청이 취소되었습니다.",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            }
        ]

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body,
    }

    return adaptive_attachment(card)

async def get_teams_account(
    turn_context: TurnContext,
) -> tuple[str, str]:
    """
    Teams 사용자 정보를 조회한다.

    반환값:
        account_id: UPN의 @ 앞 계정 아이디
        user_name: Teams 표시 이름
    """

    sender = turn_context.activity.from_property

    sender_id = (
        sender.id
        if sender
        else ""
    )

    sender_name = (
        sender.name
        if sender
        else ""
    )

    if not sender_id:
        return "", sender_name

    try:
        member = await TeamsInfo.get_member(
            turn_context,
            sender_id,
        )

        upn = str(
            getattr(
                member,
                "user_principal_name",
                None,
            )
            or getattr(
                member,
                "email",
                None,
            )
            or ""
        ).strip()

        # kimjungwoo@company.com -> kimjungwoo
        account_id = (
            upn.split("@", 1)[0].strip()
            if "@" in upn
            else upn
        )

        user_name = str(
            getattr(
                member,
                "name",
                None,
            )
            or sender_name
            or ""
        ).strip()

        print(
            "[TEAMS USER]"
            f" bot_user_id={sender_id}"
            f" upn={upn}"
            f" account_id={account_id}"
            f" user_name={user_name}",
            flush=True,
        )

        return account_id, user_name

    except Exception as error:
        print(
            "[TEAMS USER LOOKUP ERROR]"
            f" bot_user_id={sender_id}"
            f" type={type(error).__name__}"
            f" message={error}",
            flush=True,
        )

        # 조회 실패 시 29:... 값을 대신 넣지 않는다.
        return "", sender_name


class RelayBot(ActivityHandler):

    async def on_members_added_activity(
        self,
        members_added: list[ChannelAccount],
        turn_context: TurnContext,
    ) -> None:
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    "POS FAQ 중계 봇 연결 완료 ✅"
                )
                await turn_context.send_activity(
                    MessageFactory.attachment(
                        create_tool_menu_card()
                    )
                )

    async def update_source_card(
        self,
        turn_context: TurnContext,
        attachment: Attachment,
    ) -> bool:
        activity_id = turn_context.activity.reply_to_id

        if not activity_id:
            return False

        updated_activity = Activity(
            type="message",
            id=activity_id,
            attachments=[attachment],
        )

        await turn_context.update_activity(
            updated_activity
        )

        return True

    async def update_or_send_card(
        self,
        turn_context: TurnContext,
        attachment: Attachment,
    ) -> None:
        updated = await self.update_source_card(
            turn_context,
            attachment,
        )

        if not updated:
            await turn_context.send_activity(
                MessageFactory.attachment(
                    attachment
                )
            )

    async def handle_tool_menu(
        self,
        turn_context: TurnContext,
    ) -> None:
        self.clear_pending_search_tool(
            turn_context
        )

        await self.update_or_send_card(
            turn_context,
            create_tool_menu_card(),
        )

    def set_pending_search_tool(
        self,
        turn_context: TurnContext,
        tool_name: str,
    ) -> None:
        session_key = get_tool_session_key(
            turn_context.activity
        )

        PENDING_SEARCH_CACHE[session_key] = {
            "tool": tool_name,
            "expires_at": (
                datetime.now(KST)
                + PENDING_SEARCH_TTL
            ),
        }

        if len(PENDING_SEARCH_CACHE) > 1000:
            oldest_key = next(
                iter(PENDING_SEARCH_CACHE)
            )
            PENDING_SEARCH_CACHE.pop(
                oldest_key,
                None,
            )

    def get_pending_search_tool(
        self,
        turn_context: TurnContext,
    ) -> str:
        session_key = get_tool_session_key(
            turn_context.activity
        )
        pending = PENDING_SEARCH_CACHE.get(
            session_key
        )

        if not pending:
            return ""

        expires_at = pending.get("expires_at")

        if (
            not isinstance(expires_at, datetime)
            or datetime.now(KST) >= expires_at
        ):
            PENDING_SEARCH_CACHE.pop(
                session_key,
                None,
            )
            return ""

        tool_name = str(
            pending.get("tool", "")
        )

        if tool_name not in (
            TOOL_PRODUCT_LOOKUP,
            TOOL_SINGLE_PRODUCT_LOOKUP,
        ):
            PENDING_SEARCH_CACHE.pop(
                session_key,
                None,
            )
            return ""

        return tool_name

    def clear_pending_search_tool(
        self,
        turn_context: TurnContext,
    ) -> None:
        session_key = get_tool_session_key(
            turn_context.activity
        )
        PENDING_SEARCH_CACHE.pop(
            session_key,
            None,
        )

    async def handle_tool_select(
        self,
        turn_context: TurnContext,
        submit_value: dict,
    ) -> None:
        tool_name = str(
            submit_value.get("tool", "")
        ).strip()

        if tool_name == TOOL_POS_MASTER_CREATE:
            self.clear_pending_search_tool(
                turn_context
            )
            attachment = create_pos_master_form_card()
        elif tool_name == TOOL_PRODUCT_SEARCH:
            self.clear_pending_search_tool(
                turn_context
            )
            attachment = create_product_search_tool_menu_card()
        elif tool_name in (
            TOOL_PRODUCT_LOOKUP,
            TOOL_SINGLE_PRODUCT_LOOKUP,
        ):
            self.set_pending_search_tool(
                turn_context,
                tool_name
            )
            attachment = create_product_search_input_card(
                tool_name
            )
        elif tool_name == TOOL_FOOD_KIOSK:
            self.clear_pending_search_tool(
                turn_context
            )
            attachment = create_food_kiosk_tool_menu_card()
        elif tool_name == TOOL_FOOD_KIOSK_SOLD_OUT:
            self.clear_pending_search_tool(
                turn_context
            )
            attachment = create_food_kiosk_status_card(
                tool_name
            )
        elif tool_name == TOOL_GENERAL_CHAT:
            self.clear_pending_search_tool(
                turn_context
            )
            attachment = create_tool_status_card(
                "일반 질문",
                "채팅창에 질문을 입력하면 기존 LLM으로 전달합니다.",
            )
        elif tool_name == TOOL_PATTERN_SEARCH:
            self.clear_pending_search_tool(
                turn_context
            )
            attachment = create_pattern_search_form_card()
        else:
            await turn_context.send_activity(
                "올바르지 않은 도구 선택입니다."
            )
            return

        print(
            "[TOOL SELECT]"
            f" tool={tool_name}",
            flush=True,
        )

        await self.update_or_send_card(
            turn_context,
            attachment,
        )

    async def handle_product_search_code_submit(
        self,
        turn_context: TurnContext,
        submit_value: dict,
    ) -> None:
        tool_name = str(
            submit_value.get("tool", "")
        ).strip()
        search_code = str(
            submit_value.get("search_code", "")
        ).strip()

        if tool_name not in (
            TOOL_PRODUCT_LOOKUP,
            TOOL_SINGLE_PRODUCT_LOOKUP,
        ):
            await turn_context.send_activity(
                "올바르지 않은 검색 도구입니다."
            )
            return

        code_label = (
            "상품코드"
            if tool_name == TOOL_PRODUCT_LOOKUP
            else "단품코드"
        )

        if not search_code:
            await turn_context.send_activity(
                f"{code_label}를 입력해주세요."
            )
            return

        if len(search_code) > 100:
            await turn_context.send_activity(
                f"{code_label}는 100자 이하로 입력해주세요."
            )
            return

        await self.execute_product_search(
            turn_context,
            tool_name=tool_name,
            search_code=search_code,
            update_source=isinstance(
                turn_context.activity.value,
                dict,
            ),
        )

    async def handle_product_search_image(
        self,
        turn_context: TurnContext,
        tool_name: str,
        attachments: list[Attachment],
    ) -> None:
        image_attachments = [
            attachment
            for attachment in attachments
            if is_barcode_image_attachment(
                attachment
            )
        ]

        if not image_attachments:
            await turn_context.send_activity(
                "바코드 이미지를 찾지 못했습니다."
            )
            return

        await self.execute_product_search(
            turn_context,
            tool_name=tool_name,
            image_attachment=image_attachments[0],
            update_source=False,
        )

    async def execute_product_search(
        self,
        turn_context: TurnContext,
        *,
        tool_name: str,
        search_code: str = "",
        image_attachment: Optional[Attachment] = None,
        update_source: bool = False,
    ) -> None:
        if tool_name not in (
            TOOL_PRODUCT_LOOKUP,
            TOOL_SINGLE_PRODUCT_LOOKUP,
        ):
            await turn_context.send_activity(
                "올바르지 않은 검색 도구입니다."
            )
            return

        item_type = (
            "상품"
            if tool_name == TOOL_PRODUCT_LOOKUP
            else "단품"
        )

        typing_stop_event = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(
                turn_context,
                typing_stop_event,
            )
        )

        try:
            image_bytes = None
            image_content_type = "image/jpeg"
            image_filename = "barcode-image.jpg"

            if image_attachment is not None:
                (
                    image_bytes,
                    image_content_type,
                    image_filename,
                ) = await download_teams_image_attachment(
                    image_attachment,
                    app_id=CONFIG.APP_ID,
                    app_password=CONFIG.APP_PASSWORD,
                    tenant_id=CONFIG.APP_TENANTID,
                )

            api_result = await search_items(
                target_url=CONFIG.ITEM_SEARCH_API_URL,
                item_type=item_type,
                code=search_code,
                image_bytes=image_bytes,
                image_filename=image_filename,
                image_content_type=image_content_type,
            )

        except Exception as error:
            print(
                "[ITEM SEARCH API ERROR]"
                f" tool={tool_name}"
                f" type={type(error).__name__}"
                f" message={error}",
                file=sys.stderr,
                flush=True,
            )
            traceback.print_exc()

            await turn_context.send_activity(
                "상·단품 검색 중 오류가 발생했습니다.\n\n"
                f"{type(error).__name__}: {error}"
            )
            return

        finally:
            typing_stop_event.set()
            try:
                await typing_task
            except Exception as typing_error:
                print(
                    "[ITEM SEARCH TYPING TASK ERROR]"
                    f" type={type(typing_error).__name__}"
                    f" message={typing_error}",
                    flush=True,
                )

        status_code = int(
            api_result.get("status", 0)
            or 0
        )
        response_text = str(
            api_result.get("response_text", "")
        )
        response_json = api_result.get(
            "response_json"
        )

        if not isinstance(response_json, dict):
            response_json = {}

        print(
            "[ITEM SEARCH API RESPONSE]"
            f" tool={tool_name}"
            f" status={status_code}"
            f" body={response_text[:1000]}",
            flush=True,
        )

        if (
            status_code != 200
            or response_json.get("ok") is not True
        ):
            error_message = str(
                response_json.get("message")
                or response_json.get("detail")
                or response_json.get("error")
                or response_text
                or "알 수 없는 오류"
            )

            await turn_context.send_activity(
                "상·단품 검색 요청에 실패했습니다.\n\n"
                f"HTTP 상태: {status_code}\n"
                f"내용: {error_message}"
            )
            return

        self.clear_pending_search_tool(
            turn_context
        )

        result_attachment = (
            create_product_search_result_card(
                tool_name=tool_name,
                response_json=response_json,
            )
        )

        if update_source:
            await self.update_or_send_card(
                turn_context,
                result_attachment,
            )
        else:
            await turn_context.send_activity(
                MessageFactory.attachment(
                    result_attachment
                )
            )

    async def handle_pos_master_create_submit(
        self,
        turn_context: TurnContext,
        submit_value: dict,
    ) -> None:
        pos_no = str(
            submit_value.get("pos_no", "")
        ).strip()

        if not pos_no:
            await turn_context.send_activity(
                "POS 번호를 입력해주세요."
            )
            return

        if len(pos_no) > 30:
            await turn_context.send_activity(
                "POS 번호는 30자 이하로 입력해주세요."
            )
            return

        sender = turn_context.activity.from_property

        print(
            "[POS MASTER TOOL SHELL]"
            f" tool={TOOL_POS_MASTER_CREATE}"
            f" pos_no={pos_no}"
            f" user_id={sender.id if sender else ''}",
            flush=True,
        )

        await self.update_or_send_card(
            turn_context,
            create_pos_master_shell_result_card(
                pos_no
            ),
        )

    async def handle_pattern_search_submit(
        self,
        turn_context: TurnContext,
        submit_value: dict,
    ) -> None:
        pos_no = str(
            submit_value.get("pos_no", "")
        ).strip()
        search_type = str(
            submit_value.get("search_type", "0")
        ).strip()
        search_value = str(
            submit_value.get("search_value", "")
        ).strip()

        try:
            page = int(
                submit_value.get("page", 1)
                or 1
            )
        except (TypeError, ValueError):
            page = 0

        if not pos_no:
            await turn_context.send_activity(
                "POS 번호를 입력해주세요."
            )
            return

        if len(pos_no) > 30:
            await turn_context.send_activity(
                "POS 번호는 30자 이하로 입력해주세요."
            )
            return

        if search_type not in (
            "0",
            "1",
        ):
            await turn_context.send_activity(
                "검색 구분을 올바르게 선택해주세요."
            )
            return

        if len(search_value) > 100:
            await turn_context.send_activity(
                "검색어는 100자 이하로 입력해주세요."
            )
            return

        if page < 1:
            await turn_context.send_activity(
                "페이지 번호가 올바르지 않습니다."
            )
            return

        print(
            "[PATTERN SEARCH API REQUEST]"
            f" tool={TOOL_PATTERN_SEARCH}"
            f" pos_no={pos_no}"
            f" search_type={search_type}"
            f" search_value={search_value}"
            f" page={page}",
            flush=True,
        )

        typing_stop_event = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(
                turn_context,
                typing_stop_event,
            )
        )

        try:
            api_result = await search_patterns(
                target_url=CONFIG.PATTERN_SEARCH_API_URL,
                pos_no=pos_no,
                search_type=search_type,
                search_value=search_value,
                page=page,
            )

        except Exception as error:
            print(
                "[PATTERN SEARCH API ERROR]"
                f" type={type(error).__name__}"
                f" message={error}",
                file=sys.stderr,
                flush=True,
            )
            traceback.print_exc()

            await turn_context.send_activity(
                "패턴 조회 중 오류가 발생했습니다.\n\n"
                f"{type(error).__name__}: {error}"
            )
            return

        finally:
            typing_stop_event.set()
            try:
                await typing_task
            except Exception as typing_error:
                print(
                    "[PATTERN SEARCH TYPING TASK ERROR]"
                    f" type={type(typing_error).__name__}"
                    f" message={typing_error}",
                    flush=True,
                )

        status_code = int(
            api_result.get("status", 0)
            or 0
        )
        response_text = str(
            api_result.get("response_text", "")
        )
        response_json = api_result.get(
            "response_json"
        )

        if not isinstance(response_json, dict):
            response_json = {}

        print(
            "[PATTERN SEARCH API RESPONSE]"
            f" status={status_code}"
            f" body={response_text[:1000]}",
            flush=True,
        )

        if (
            status_code != 200
            or response_json.get("ok") is not True
        ):
            error_message = str(
                response_json.get("message")
                or response_json.get("detail")
                or response_json.get("error")
                or response_text
                or "알 수 없는 오류"
            )

            await turn_context.send_activity(
                "패턴 조회 요청에 실패했습니다.\n\n"
                f"HTTP 상태: {status_code}\n"
                f"내용: {error_message}"
            )
            return

        await self.update_or_send_card(
            turn_context,
            create_pattern_search_result_card(
                response_json
            ),
        )

    async def handle_feedback(
        self,
        turn_context: TurnContext,
        submit_value: dict,
    ) -> None:
        activity = turn_context.activity
        sender = activity.from_property

        # Teams가 이미지와 메시지를 어떤 구조로 보내는지 확인
        try:
            activity_payload = activity.serialize()

            activity_json = json.dumps(
                activity_payload,
                ensure_ascii=False,
                default=str,
            )

            print(
                "[ACTIVITY RAW] "
                + activity_json[:15000],
                flush=True,
            )

            print(
                "[ACTIVITY FIELDS]"
                f" text={(activity.text or '')[:500]}"
                f" attachment_count={len(activity.attachments or [])}"
                f" entity_count={len(activity.entities or [])}"
                f" value_type={type(activity.value).__name__}",
                flush=True,
            )

        except Exception as debug_error:
            print(
                "[ACTIVITY DEBUG ERROR]"
                f" type={type(debug_error).__name__}"
                f" message={debug_error}",
                flush=True,
            )

        helpful = str(
            submit_value.get("helpful", "")
        ).strip().upper()

        request_id = str(
            submit_value.get("request_id", "")
        ).strip()

        question = str(
            submit_value.get("question", "")
        ).strip()

        feedback_text = str(
            submit_value.get("feedback_text", "")
        ).strip()

        print(
            "[FEEDBACK]"
            f" request_id={request_id}"
            f" helpful={helpful}"
            f" user_id={sender.id if sender else ''}"
            f" user_name={sender.name if sender else ''}"
            f" question={question}"
            f" feedback_text={feedback_text}",
            flush=True,
        )

        if helpful not in ("Y", "N"):
            await turn_context.send_activity(
                "올바르지 않은 피드백 요청입니다."
            )
            return

        if helpful == "N" and not feedback_text:
            await turn_context.send_activity(
                "의견을 입력한 후 다시 제출해주세요."
            )
            return

        cached_card = CARD_CACHE.get(request_id)
        if not cached_card:
           await turn_context.send_activity(
               "피드백은 수신했지만 "
               "기존 카드 정보를 찾지 못했습니다."
           )
           return
        # 이미 피드백 저장이 완료된 카드면 재호출 차단
        if cached_card.get("feedbackSubmitted"):
           await turn_context.send_activity(
               "이미 피드백이 제출된 답변입니다."
           )
           return
        # 더블클릭 등으로 API가 동시에 두 번 호출되는 것 방지
        if cached_card.get("feedbackProcessing"):
           await turn_context.send_activity(
               "피드백을 저장하고 있습니다."
           )
           return
        log_reg_dt = cached_card.get("logRegDt")
        log_seq = cached_card.get("logSeq")
        if not log_reg_dt or log_seq is None:
           await turn_context.send_activity(
               "피드백 저장에 필요한 로그 정보를 찾지 못했습니다."
           )
           return
        cached_card["feedbackProcessing"] = True

        payload = {
           "regDt": str(log_reg_dt),
           "seq": int(log_seq),
           "helpYn": "1" if helpful == "Y" else "0",
           "feedbackText": feedback_text,
        }
        print(
           "[FEEDBACK API REQUEST]"
           f" request_id={request_id}"
           f" reg_dt={payload['regDt']}"
           f" seq={payload['seq']}"
           f" help_yn={payload['helpYn']}"
           f" feedback_text={payload['feedbackText']}",
           flush=True,
        )
        
        timeout = aiohttp.ClientTimeout(
           total=30
        )
        try:
            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:
                async with session.post(
                    CONFIG.FEEDBACK_API_URL,
                    json=payload,
                ) as response:
                    response_text = (
                        await response.text()
                    )
                    status_code = response.status
            print(
                "[FEEDBACK API RESPONSE]"
                f" request_id={request_id}"
                f" status={status_code}"
                f" body={response_text[:1000]}",
                flush=True,
            )
            try:
                result = json.loads(
                    response_text
                )
            except json.JSONDecodeError:
                result = {}
            if (
                status_code != 200
                or not result.get("success")
            ):
                cached_card[
                    "feedbackProcessing"
                ] = False
                await turn_context.send_activity(
                    "피드백 저장에 실패했습니다.\n\n"
                    f"HTTP 상태: {status_code}\n"
                    f"응답: {response_text}"
                )
                return
        except Exception as feedback_error:
            cached_card[
                "feedbackProcessing"
            ] = False
            print(
                "[FEEDBACK API ERROR]"
                f" request_id={request_id}"
                f" type="
                f"{type(feedback_error).__name__}"
                f" message={feedback_error}",
                file=sys.stderr,
                flush=True,
            )
            await turn_context.send_activity(
                "피드백 API 호출 중 오류가 "
                "발생했습니다.\n\n"
                f"{type(feedback_error).__name__}: "
                f"{feedback_error}"
            )
            return
        # API 저장에 성공한 경우에만 제출 완료 처리
        cached_card["feedbackProcessing"] = False
        cached_card["feedbackSubmitted"] = True
        cached_card["selectedFeedback"] = helpful
        cached_card["feedbackText"] = feedback_text

        updated_attachment = create_answer_card(
            question=cached_card["question"],
            answer=cached_card["answer"],
            request_id=request_id,
            selected=helpful,
        )
        

        updated = await self.update_source_card(
            turn_context,
            updated_attachment,
        )

        if not updated:
            await turn_context.send_activity(
                "원본 카드 메시지 ID를 확인하지 못했습니다."
            )

    async def handle_register_cancel(
        self,
        turn_context: TurnContext,
    ) -> None:
        cancelled_card = create_register_result_card(
            success=False
        )

        updated = await self.update_source_card(
            turn_context,
            cancelled_card,
        )

        if not updated:
            await turn_context.send_activity(
                MessageFactory.attachment(
                    cancelled_card
                )
            )

    async def handle_register_submit(
        self,
        turn_context: TurnContext,
        submit_value: dict,
    ) -> None:
        activity = turn_context.activity
        sender = activity.from_property

        # sender.id는 29:... 형태의 Teams 채널 전용 ID다.
        # Teams 사용자 상세정보를 조회해 실제 로그인 ID(UPN)를 가져온다.
        channel_user_id = (
            sender.id
            if sender
            else ""
        )

        teams_member = None

        if channel_user_id:
            try:
                teams_member = await TeamsInfo.get_member(
                    turn_context,
                    channel_user_id,
                )
            except Exception as error:
                print(
                    "[TEAMS MEMBER LOOKUP ERROR]"
                    f" type={type(error).__name__}"
                    f" message={error}",
                    file=sys.stderr,
                    flush=True,
                )

        user_principal_name = (
            getattr(
                teams_member,
                "user_principal_name",
                "",
            )
            or ""
        ).strip()

        user_email = (
            getattr(
                teams_member,
                "email",
                "",
            )
            or ""
        ).strip()

        aad_object_id = (
            getattr(
                teams_member,
                "aad_object_id",
                "",
            )
            or getattr(
                sender,
                "aad_object_id",
                "",
            )
            or ""
        ).strip()

        teams_user_name = (
            getattr(
                teams_member,
                "name",
                "",
            )
            or (
                sender.name
                if sender
                else ""
            )
            or "unknown"
        ).strip()

        # 등록 API의 teamsUserId에는 실제 회사 로그인 ID를 우선 전송한다.
        teams_user_id = (
            user_principal_name
            or user_email
            or aad_object_id
            or channel_user_id
            or "teams-anonymous"
        )

        print(
            "[TEAMS USER RESOLVED]"
            f" channel_user_id={channel_user_id}"
            f" upn={user_principal_name}"
            f" email={user_email}"
            f" aad_object_id={aad_object_id}"
            f" selected_teams_user_id={teams_user_id}"
            f" name={teams_user_name}",
            flush=True,
        )

        category = str(
            submit_value.get("category", "")
        ).strip()

        question = str(
            submit_value.get("question", "")
        ).strip()

        answer = str(
            submit_value.get("answer", "")
        ).strip()

        keywords = str(
            submit_value.get("keywords", "")
        ).strip()

        if category not in CATEGORIES:
            await turn_context.send_activity(
                "업무 구분을 올바르게 선택해주세요."
            )
            return

        if not question:
            await turn_context.send_activity(
                "질문을 입력해주세요."
            )
            return

        if not answer:
            await turn_context.send_activity(
                "답변을 입력해주세요."
            )
            return

        teams_account_id, teams_user_name = (
            await get_teams_account(
                turn_context
            )
        )

        if not teams_account_id:
            await turn_context.send_activity(
                "Teams 계정 아이디를 확인하지 못해 "
                "FAQ 등록 요청을 처리할 수 없습니다."
            )
            return

        payload = {
            "source": "TEAMS",
            "teamsUserId": teams_account_id,
            "teamsUserName": teams_user_name,
            "category": category,
            "question": question,
            "answer": answer,
            "keywords": keywords,
            "requestTime": datetime.now(
                KST
            ).isoformat(
                timespec="seconds"
            ),
        }

        print(
            "[FAQ REGISTER REQUEST]"
            f" user_id={payload['teamsUserId']}"
            f" user_name={payload['teamsUserName']}"
            f" category={category}"
            f" question={question}"
            f" keywords={keywords}",
            flush=True,
        )

        timeout = aiohttp.ClientTimeout(
            total=30
        )

        try:
            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:
                async with session.post(
                    CONFIG.REGISTER_API_URL,
                    json=payload,
                ) as response:
                    response_text = await response.text()
                    status_code = response.status

            print(
                "[FAQ REGISTER RESPONSE]"
                f" status={status_code}"
                f" body={response_text[:1000]}",
                flush=True,
            )

            try:
                result = json.loads(
                    response_text
                )
            except json.JSONDecodeError:
                result = {}

            success = bool(
                result.get("success")
            )

            result_request_id = result.get(
                "requestId"
            )

            result_message = str(
                result.get("message", "")
            ).strip()

            error_code = result.get(
                "errorCode"
            )

            if status_code == 200 and success:
                completed_card = (
                    create_register_result_card(
                        success=True,
                        category=category,
                        question=question,
                        request_id=result_request_id,
                        message=result_message,
                    )
                )

                updated = await self.update_source_card(
                    turn_context,
                    completed_card,
                )

                if not updated:
                    await turn_context.send_activity(
                        MessageFactory.attachment(
                            completed_card
                        )
                    )

                return

            await turn_context.send_activity(
                "FAQ 등록 요청에 실패했습니다.\n\n"
                f"HTTP 상태: {status_code}\n"
                f"오류 코드: {error_code or '-'}\n"
                f"내용: {result_message or response_text}"
            )

        except Exception as error:
            print(
                "[FAQ REGISTER ERROR]"
                f" type={type(error).__name__}"
                f" message={error}",
                file=sys.stderr,
                flush=True,
            )

            await turn_context.send_activity(
                "FAQ 등록 API 호출 중 오류가 발생했습니다.\n\n"
                f"{type(error).__name__}: {error}"
            )

    async def on_message_activity(
        self,
        turn_context: TurnContext,
    ) -> None:
        activity = turn_context.activity
        sender = activity.from_property
        attachments = activity.attachments or []

        pending_search_tool = (
            self.get_pending_search_tool(
                turn_context
            )
        )
        barcode_image_exists = any(
            is_barcode_image_attachment(
                attachment
            )
            for attachment in attachments
        )

        if (
            pending_search_tool
            and barcode_image_exists
        ):
            await self.handle_product_search_image(
                turn_context,
                pending_search_tool,
                attachments,
            )
            return

        # ===== TEAMS IMAGE FORWARD FINAL =====
        direct_image_exists = any(
            str(
                attachment.content_type or ""
            )
            .strip()
            .lower()
            .startswith("image/")
            and bool(
                str(
                    attachment.content_url or ""
                ).strip()
            )
            for attachment in attachments
        )

        if direct_image_exists:
            image_request_id = str(
                uuid.uuid4()
            )

            image_question = (
                activity.text or ""
            ).strip()

            try:
                (
                    teams_account_id,
                    teams_user_name,
                ) = await get_teams_account(
                    turn_context
                )

                if not teams_account_id:
                    await turn_context.send_activity(
                        "Teams 계정 아이디를 "
                        "확인하지 못해 이미지 요청을 "
                        "처리할 수 없습니다."
                    )
                    return

                typing_stop_event = asyncio.Event()
                typing_task = asyncio.create_task(
                   keep_typing(
                       turn_context,
                       typing_stop_event,
                   )
                )
                try:
                   image_result = await forward_teams_image(
                       turn_context,
                       app_id=CONFIG.APP_ID,
                       app_password=(
                           CONFIG.APP_PASSWORD
                       ),
                       tenant_id=(
                           CONFIG.APP_TENANTID
                       ),
                       target_url=os.getenv(
                           "INTERNAL_IMAGE_API_URL",
                           (
                               "http://"
                               "123.111.174.78:"
                               "30002/image-chat"
                           ),
                       ),
                       request_id=image_request_id,
                       user_id=teams_account_id,
                       user_name=teams_user_name,
                       question=image_question,
                   )
                finally:
                   typing_stop_event.set()
                   try:
                       await typing_task
                   except Exception as typing_error:
                       print(
                           "[IMAGE TYPING TASK ERROR]"
                           f" request_id={image_request_id}"
                           f" type={type(typing_error).__name__}"
                           f" message={typing_error}",
                           flush=True,
                       )

                if image_result is None:
                    raise RuntimeError(
                        "이미지 첨부정보를 "
                        "찾지 못했습니다."
                    )

                if image_result["ok"]:
                    image_answer = (
                        image_result["answer"]
                        or (
                            "텍스트와 이미지를 "
                            "내부 서버에 정상적으로 "
                            "전달했습니다."
                        )
                    )

                    image_response_json = (
                       image_result.get("response_json")
                       if isinstance(
                           image_result.get("response_json"),
                           dict,
                       )
                       else {}
                    )
                    CARD_CACHE[image_request_id] = {
                       "question": (
                           image_question
                           or "첨부 이미지 분석"
                       ),
                       "answer": image_answer,
                       "logRegDt": image_response_json.get(
                           "logRegDt"
                       ),
                       "logSeq": image_response_json.get(
                           "logSeq"
                       ),
                       "feedbackSubmitted": False,
                       "feedbackProcessing": False,
                    }
                    card_attachment = (
                        create_answer_card(
                            question=(
                                image_question
                                or "첨부 이미지 분석"
                            ),
                            answer=image_answer,
                            request_id=(
                                image_request_id
                            ),
                            selected="",
                        )
                    )

                    await turn_context.send_activity(
                        MessageFactory.attachment(
                            card_attachment
                        )
                    )
                    return

                await turn_context.send_activity(
                    "이미지 요청을 내부 서버로 "
                    "전달했지만 오류가 발생했습니다."
                    "\n\n"
                    f"HTTP 상태: "
                    f"{image_result['status']}\n"
                    f"응답 코드: "
                    f"{image_result['rest_cd']}\n"
                    f"응답: "
                    f"{image_result['response_text'][:500]}"
                )
                return

            except Exception as image_error:
                print(
                    "[IMAGE PIPELINE ERROR]"
                    f" request_id="
                    f"{image_request_id}"
                    f" type="
                    f"{type(image_error).__name__}"
                    f" message={image_error}",
                    file=sys.stderr,
                    flush=True,
                )

                traceback.print_exc()

                await turn_context.send_activity(
                    "이미지 처리 중 오류가 "
                    "발생했습니다.\n\n"
                    f"{type(image_error).__name__}: "
                    f"{image_error}"
                )
                return
        # ===== TEAMS IMAGE FORWARD FINAL 끝 =====


        # 일반 메시지 및 이미지 Activity 구조 확인
        try:
            activity_payload = activity.serialize()

            activity_json = json.dumps(
                activity_payload,
                ensure_ascii=False,
                default=str,
            )

            print(
                "[ACTIVITY RAW MESSAGE] "
                + activity_json[:20000],
                flush=True,
            )

            print(
                "[ACTIVITY FIELDS MESSAGE]"
                f" text={(activity.text or '')[:500]}"
                f" attachment_count={len(activity.attachments or [])}"
                f" entity_count={len(activity.entities or [])}"
                f" value_type={type(activity.value).__name__}",
                flush=True,
            )

        except Exception as debug_error:
            print(
                "[ACTIVITY DEBUG ERROR MESSAGE]"
                f" type={type(debug_error).__name__}"
                f" message={debug_error}",
                flush=True,
            )

        # ===== IMAGE POC GUARD V2 =====
        attachments = activity.attachments or []
        image_attachments = []
        html_image_found = False

        for index, attachment in enumerate(
            attachments,
            start=1,
        ):
            content_type = str(
                attachment.content_type or ""
            ).strip().lower()

            content_url = str(
                attachment.content_url or ""
            ).strip()

            attachment_name = str(
                attachment.name
                or f"attachment-{index}"
            ).strip()

            attachment_content = (
                attachment.content or ""
            )

            if isinstance(
                attachment_content,
                dict,
            ):
                content_text = json.dumps(
                    attachment_content,
                    ensure_ascii=False,
                    default=str,
                )
            else:
                content_text = str(
                    attachment_content
                )

            is_direct_image = (
                content_type.startswith("image/")
            )

            is_html_image = (
                content_type == "text/html"
                and "<img" in content_text.lower()
            )

            print(
                "[IMAGE CHECK]"
                f" index={index}"
                f" content_type={content_type}"
                f" name={attachment_name}"
                f" direct_image={is_direct_image}"
                f" html_image={is_html_image}"
                f" content_url_present={bool(content_url)}",
                flush=True,
            )

            if is_direct_image:
                image_attachments.append(
                    {
                        "index": index,
                        "name": attachment_name,
                        "content_type": content_type,
                        "content_url": content_url,
                    }
                )

            if is_html_image:
                html_image_found = True

        if image_attachments or html_image_found:
            print(
                "[IMAGE POC DETECTED]"
                f" attachment_count={len(attachments)}"
                f" direct_image_count={len(image_attachments)}"
                f" html_image_found={html_image_found}"
                f" question={(activity.text or '').strip()}",
                flush=True,
            )

            await turn_context.send_activity(
                "이미지 수신 확인 완료 ✅\n\n"
                f"- 전체 첨부: {len(attachments)}개\n"
                f"- 실제 이미지: "
                f"{len(image_attachments)}개\n"
                f"- 이미지 HTML: "
                f"{'확인됨' if html_image_found else '없음'}\n"
                f"- 질문: "
                f"{(activity.text or '').strip() or '(없음)'}\n\n"
                "Teams에서 실제 이미지 URL까지 "
                "정상적으로 전달됐습니다."
            )

            # 이미지가 포함된 메시지는 일반 텍스트 RAG로 보내지 않는다.
            return
        # ===== IMAGE POC GUARD V2 끝 =====

        submit_value = (
            activity.value
            if isinstance(activity.value, dict)
            else {}
        )

        action = str(
            submit_value.get("action", "")
        )

        if action == "tool_menu":
            await self.handle_tool_menu(
                turn_context
            )
            return

        if action == "tool_select":
            await self.handle_tool_select(
                turn_context,
                submit_value,
            )
            return

        if action == "pos_master_create_submit":
            await self.handle_pos_master_create_submit(
                turn_context,
                submit_value,
            )
            return

        if action == "product_search_code_submit":
            await self.handle_product_search_code_submit(
                turn_context,
                submit_value,
            )
            return

        if action in (
            "pattern_search_submit",
            "pattern_search_page",
        ):
            await self.handle_pattern_search_submit(
                turn_context,
                submit_value,
            )
            return

        if action == "feedback":
            await self.handle_feedback(
                turn_context,
                submit_value,
            )
            return

        if action == "faq_register_submit":
            await self.handle_register_submit(
                turn_context,
                submit_value,
            )
            return

        if action == "faq_register_cancel":
            await self.handle_register_cancel(
                turn_context
            )
            return

        raw_message = (
            activity.text or ""
        ).strip()

        mention_removed = (
            TurnContext.remove_recipient_mention(
                activity
            )
            or raw_message
        ).strip()

        compact_command = (
            mention_removed
            .replace(" ", "")
            .lower()
        )

        if compact_command in {
            "도구",
            "도구메뉴",
            "업무도구",
            "메뉴",
        }:
            self.clear_pending_search_tool(
                turn_context
            )
            await turn_context.send_activity(
                MessageFactory.attachment(
                    create_tool_menu_card()
                )
            )
            return

        if compact_command in {
            "pos마스터생성",
            "포스마스터생성",
        }:
            self.clear_pending_search_tool(
                turn_context
            )
            await turn_context.send_activity(
                MessageFactory.attachment(
                    create_pos_master_form_card()
                )
            )
            return

        if compact_command in {
            "푸드키오스크",
            "푸드키오스크도구",
        }:
            self.clear_pending_search_tool(
                turn_context
            )
            await turn_context.send_activity(
                MessageFactory.attachment(
                    create_food_kiosk_tool_menu_card()
                )
            )
            return

        if compact_command in {
            "상단품검색",
            "상품단품검색",
        }:
            self.clear_pending_search_tool(
                turn_context
            )
            await turn_context.send_activity(
                MessageFactory.attachment(
                    create_product_search_tool_menu_card()
                )
            )
            return

        if compact_command in {
            "패턴조회",
            "패턴검색",
        }:
            self.clear_pending_search_tool(
                turn_context
            )
            await turn_context.send_activity(
                MessageFactory.attachment(
                    create_pattern_search_form_card()
                )
            )
            return

        if compact_command in {
            "@등록",
            "등록",
        }:
            self.clear_pending_search_tool(
                turn_context
            )
            await turn_context.send_activity(
                MessageFactory.attachment(
                    create_register_form_card()
                )
            )
            return

        if pending_search_tool and mention_removed:
            await self.handle_product_search_code_submit(
                turn_context,
                {
                    "tool": pending_search_tool,
                    "search_code": mention_removed,
                },
            )
            return

        message = mention_removed

        if not message:
            await turn_context.send_activity(
                "질문 내용을 입력해주세요."
            )
            return

        request_id = str(
            uuid.uuid4()
        )

        print(
            "[MESSAGE]"
            f" request_id={request_id}"
            f" channel={activity.channel_id}"
            f" user_id={sender.id if sender else ''}"
            f" user_name={sender.name if sender else ''}"
            f" text={message}",
            flush=True,
        )

        teams_account_id, teams_user_name = await get_teams_account(turn_context)

        payload = {
            "message": message,
            "user_id": teams_account_id,
            "user_name": teams_user_name,
            "channel_id": activity.channel_id,
            "conversation_id": (
                activity.conversation.id
                if activity.conversation
                else None
            ),
            "request_id": request_id,
            "request_time": datetime.now(
                KST
            ).isoformat(
                timespec="seconds"
            ),
        }

        timeout = aiohttp.ClientTimeout(
            total=120
        )

        typing_stop_event = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(
                turn_context,
                typing_stop_event,
            )
        )

        try:
            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:
                async with session.post(
                    CONFIG.INTERNAL_API_URL,
                    json=payload,
                ) as response:
                    response_text = await response.text()
                    status_code = response.status

            print(
                "[INTERNAL RESPONSE]"
                f" request_id={request_id}"
                f" status={status_code}"
                f" body={response_text[:1000]}",
                flush=True,
            )

            try:
                rag_result = json.loads(
                    response_text
                )
            except json.JSONDecodeError:
                rag_result = {}

            rest_cd = str(
                rag_result.get("restCd", "")
            )

            rest_msg = str(
                rag_result.get("restMsg", "")
            )

            answer = str(
                rag_result.get("answer", "")
            ).strip()

            if status_code == 200 and answer:
                CARD_CACHE[request_id] = {
                   "question": message,
                   "answer": answer,
                   "logRegDt": rag_result.get("logRegDt"),
                   "logSeq": rag_result.get("logSeq"),
                   "feedbackSubmitted": False,
                   "feedbackProcessing": False,
                }

                if len(CARD_CACHE) > 1000:
                    oldest_request_id = next(
                        iter(CARD_CACHE)
                    )

                    CARD_CACHE.pop(
                        oldest_request_id,
                        None,
                    )

                card_attachment = create_answer_card(
                    question=message,
                    answer=answer,
                    request_id=request_id,
                    selected="",
                )

                await turn_context.send_activity(
                    MessageFactory.attachment(
                        card_attachment
                    )
                )

                return

            error_message = (
                rest_msg
                or response_text
            )

            await turn_context.send_activity(
                "RAG 서버 응답 중 오류가 발생했습니다.\n\n"
                f"HTTP 상태: {status_code}\n"
                f"응답 코드: {rest_cd}\n"
                f"메시지: {error_message}"
            )

        except Exception as error:
            print(
                "[INTERNAL API ERROR]"
                f" request_id={request_id}"
                f" type={type(error).__name__}"
                f" message={error}",
                file=sys.stderr,
                flush=True,
            )

            await turn_context.send_activity(
                "Teams 메시지는 수신했지만 "
                "내부 RAG 서버 호출에 실패했습니다.\n\n"
                f"{type(error).__name__}: {error}"
            )
        finally:
            typing_stop_event.set()
            try:
                await typing_task
            except Exception as typing_error:
                print(
                    "[MESSAGE TYPING TASK ERROR]"
                    f" request_id={request_id}"
                    f" type={type(typing_error).__name__}"
                    f" message={typing_error}",
                    flush=True,
                )


BOT = RelayBot()


async def messages(
    request: web.Request,
) -> web.Response:
    return await ADAPTER.process(
        request,
        BOT,
    )


async def health(
    _: web.Request,
) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "service": "pos-bot-relay",
            "chat_api_url": CONFIG.INTERNAL_API_URL,
            "register_api_url": CONFIG.REGISTER_API_URL,
            "server_time": datetime.now(
                KST
            ).isoformat(
                timespec="seconds"
            ),
        }
    )


APP = web.Application(
    middlewares=[
        aiohttp_error_middleware
    ]
)

APP.router.add_get(
    "/health",
    health,
)

APP.router.add_post(
    "/api/messages",
    messages,
)


if __name__ == "__main__":
    web.run_app(
        APP,
        host="127.0.0.1",
        port=CONFIG.PORT,
    )

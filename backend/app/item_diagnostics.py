from __future__ import annotations

from datetime import date, datetime
from typing import Any


ACTIVE_USE_VALUES = {
    "1",
    "Y",
    "YES",
    "TRUE",
    "T",
    "사용",
    "사용가능",
}
INACTIVE_USE_VALUES = {
    "0",
    "N",
    "NO",
    "FALSE",
    "F",
    "미사용",
    "사용불가",
}

EVENT_DEFINITIONS = (
    {
        "type": "PRICE",
        "label": "가격 행사",
        "code": "PRC_EVT_CD",
        "name": None,
        "start": "PRC_EVT_ST_DT",
        "end": "PRC_EVT_ED_DT",
        "details": ("PRC_EVT_PRC",),
    },
    {
        "type": "NN",
        "label": "N+N 행사",
        "code": "NN_EVT_CD",
        "name": "NN_EVT_NM",
        "start": "NN_EVT_ST_DT",
        "end": "NN_EVT_ED_DT",
        "details": (
            "NN_EVT_BASE_QTY",
            "NN_EVT_DC_QTY",
        ),
    },
    *(
        {
            "type": f"TARGET_{index}",
            "label": f"대상 행사 {index}",
            "code": f"TRGT_EVT_CD_{index}",
            "name": f"TRGT_EVT_NM_{index}",
            "start": f"TRGT_EVT_ST_DT_{index}",
            "end": f"TRGT_EVT_ED_DT_{index}",
            "details": (
                f"TRGT_EVT_PRC_{index}",
            ),
        }
        for index in range(1, 6)
    ),
)


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _has_value(value: Any) -> bool:
    return _normalized_text(value).upper() not in {
        "",
        "0",
        "NULL",
        "NONE",
    }


def _parse_date(value: Any) -> tuple[date | None, str]:
    text = _normalized_text(value)
    if text.upper() in {"", "0", "00000000", "NULL", "NONE"}:
        return None, ""

    compact = "".join(character for character in text if character.isdigit())
    candidates = [text]
    if len(compact) >= 8:
        candidates.append(compact[:8])

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return parsed.date(), parsed.date().isoformat()
        except ValueError:
            pass

        for date_format in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                parsed = datetime.strptime(candidate, date_format).date()
                return parsed, parsed.isoformat()
            except ValueError:
                continue

    return None, text


def _evaluate_period(
    start_value: Any,
    end_value: Any,
    evaluated_date: date,
) -> dict[str, str]:
    start_date, start_text = _parse_date(start_value)
    end_date, end_text = _parse_date(end_value)

    if not start_text and not end_text:
        return {
            "status": "UNSET",
            "label": "기간 미설정",
            "startDate": "",
            "endDate": "",
            "message": "행사 시작일과 종료일이 설정되지 않았습니다.",
        }

    if not start_text or not end_text:
        return {
            "status": "INVALID",
            "label": "기간 확인 필요",
            "startDate": start_text,
            "endDate": end_text,
            "message": "행사 시작일과 종료일 중 하나가 누락되었습니다.",
        }

    if (start_text and start_date is None) or (end_text and end_date is None):
        return {
            "status": "INVALID",
            "label": "기간 확인 필요",
            "startDate": start_text,
            "endDate": end_text,
            "message": "행사 기간 값의 날짜 형식을 확인해야 합니다.",
        }

    if start_date and end_date and start_date > end_date:
        return {
            "status": "INVALID",
            "label": "기간 오류",
            "startDate": start_text,
            "endDate": end_text,
            "message": "행사 시작일이 종료일보다 늦습니다.",
        }

    if start_date and evaluated_date < start_date:
        return {
            "status": "SCHEDULED",
            "label": "행사 예정",
            "startDate": start_text,
            "endDate": end_text,
            "message": f"{start_text}부터 사용할 수 있는 행사입니다.",
        }

    if end_date and evaluated_date > end_date:
        return {
            "status": "EXPIRED",
            "label": "행사 종료",
            "startDate": start_text,
            "endDate": end_text,
            "message": f"{end_text}에 종료된 행사입니다.",
        }

    period_text = " ~ ".join(value or "제한 없음" for value in (start_text, end_text))
    return {
        "status": "ACTIVE",
        "label": "행사 적용 가능",
        "startDate": start_text,
        "endDate": end_text,
        "message": f"현재 행사 사용기간({period_text})에 포함됩니다.",
    }


def _evaluate_use_yn(value: Any) -> dict[str, str]:
    normalized = _normalized_text(value).upper()
    if normalized in ACTIVE_USE_VALUES:
        return {
            "status": "PASS",
            "value": _normalized_text(value),
            "message": "사용 가능한 상태입니다.",
        }
    if normalized in INACTIVE_USE_VALUES:
        return {
            "status": "FAIL",
            "value": _normalized_text(value),
            "message": "사용 중지 상태이므로 POS에서 사용할 수 없습니다.",
        }
    return {
        "status": "WARN",
        "value": _normalized_text(value) or "미설정",
        "message": "사용여부 값이 없거나 정의되지 않은 값이므로 확인이 필요합니다.",
    }


def _configured_events(result: dict[str, Any], evaluated_date: date) -> list[dict[str, str]]:
    events = []
    for definition in EVENT_DEFINITIONS:
        relevant_fields = (
            definition["code"],
            definition["name"],
            definition["start"],
            definition["end"],
            *definition["details"],
        )
        if not any(
            _has_value(result.get(field_name))
            for field_name in relevant_fields
            if field_name
        ):
            continue

        period = _evaluate_period(
            result.get(definition["start"]),
            result.get(definition["end"]),
            evaluated_date,
        )
        events.append(
            {
                "type": definition["type"],
                "label": definition["label"],
                "code": _normalized_text(result.get(definition["code"])),
                "name": _normalized_text(result.get(definition["name"])),
                "periodStatus": period["status"],
                "periodLabel": period["label"],
                "startDate": period["startDate"],
                "endDate": period["endDate"],
                "message": period["message"],
            }
        )

    event_kind_code = _normalized_text(result.get("EVENT_KND_CD"))
    if not events and _has_value(event_kind_code):
        events.append(
            {
                "type": "UNRESOLVED",
                "label": "행사 구분",
                "code": event_kind_code,
                "name": "",
                "periodStatus": "UNSET",
                "periodLabel": "상세 확인 필요",
                "startDate": "",
                "endDate": "",
                "message": "행사 구분은 있으나 가격/N+N/대상 행사 상세값이 없습니다.",
            }
        )
    return events


def build_item_diagnosis(
    item_type: str,
    result: dict[str, Any],
    *,
    evaluated_date: date | None = None,
) -> dict[str, Any]:
    today = evaluated_date or date.today()
    use_check = _evaluate_use_yn(result.get("USE_YN"))
    events = _configured_events(result, today) if item_type == "PLU" else []

    active_count = sum(event["periodStatus"] == "ACTIVE" for event in events)
    scheduled_count = sum(event["periodStatus"] == "SCHEDULED" for event in events)
    expired_count = sum(event["periodStatus"] == "EXPIRED" for event in events)
    invalid_count = sum(
        event["periodStatus"] in {"INVALID", "UNSET"}
        for event in events
    )

    if item_type == "ITEM":
        event_check = {
            "status": "INFO",
            "value": "단품 조회 필요",
            "message": "행사와 사용기간은 연결된 단품 정보에서 판정합니다.",
        }
    elif not events:
        event_check = {
            "status": "INFO",
            "value": "행사 없음",
            "message": "설정된 가격/N+N/대상 행사가 없습니다.",
        }
    elif active_count:
        event_check = {
            "status": "PASS",
            "value": f"적용 가능 {active_count}건",
            "message": "현재 날짜에 적용 가능한 행사가 있습니다.",
        }
    elif invalid_count:
        event_check = {
            "status": "WARN",
            "value": f"확인 필요 {invalid_count}건",
            "message": "기간이 없거나 잘못된 행사 설정을 확인해야 합니다.",
        }
    else:
        event_check = {
            "status": "INFO",
            "value": "현재 적용 행사 없음",
            "message": "행사는 등록되어 있지만 현재 사용기간에 포함되지 않습니다.",
        }

    if item_type == "ITEM":
        period_check = {
            "status": "INFO",
            "value": "단품 조회 필요",
            "message": "상품 마스터 조회 결과에는 행사 기간 컬럼이 없습니다.",
        }
    elif not events:
        period_check = {
            "status": "INFO",
            "value": "해당 없음",
            "message": "설정된 행사가 없어 확인할 사용기간이 없습니다.",
        }
    else:
        period_check = {
            "status": "WARN" if invalid_count else "PASS",
            "value": (
                f"적용 {active_count} / 예정 {scheduled_count} / "
                f"종료 {expired_count} / 확인 {invalid_count}"
            ),
            "message": "행사별 시작일과 종료일을 현재 날짜 기준으로 판정했습니다.",
        }

    if use_check["status"] == "FAIL":
        overall_status = "UNAVAILABLE"
        overall_label = "사용 불가"
        summary = "사용여부가 미사용 상태입니다. 행사 설정과 관계없이 POS 사용이 어렵습니다."
    elif use_check["status"] == "WARN" or invalid_count:
        overall_status = "CHECK_REQUIRED"
        overall_label = "확인 필요"
        summary = "사용여부 또는 행사 기간에 확인이 필요한 값이 있습니다."
    elif item_type == "PLU" and active_count:
        overall_status = "AVAILABLE"
        overall_label = "사용 가능 · 행사 적용"
        summary = f"사용 가능한 단품이며 현재 적용 가능한 행사가 {active_count}건 있습니다."
    elif item_type == "PLU" and events:
        overall_status = "AVAILABLE"
        overall_label = "사용 가능 · 현재 행사 없음"
        summary = "단품은 사용 가능하지만 현재 기간에 적용되는 행사는 없습니다."
    else:
        overall_status = "AVAILABLE"
        overall_label = "사용 가능"
        summary = "사용여부 기준으로 사용 가능한 상태입니다."

    return {
        "overallStatus": overall_status,
        "overallLabel": overall_label,
        "evaluatedDate": today.isoformat(),
        "summary": summary,
        "checks": [
            {"key": "useYn", "label": "사용여부", **use_check},
            {"key": "event", "label": "행사", **event_check},
            {"key": "usePeriod", "label": "사용기간", **period_check},
        ],
        "events": events,
    }

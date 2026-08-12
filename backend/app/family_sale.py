from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pyodbc

from app.config import settings


KST_OFFSET = timedelta(hours=9)
MAX_CUSTOM_RANGE = timedelta(days=31)

SALES_QUERY = """
SELECT
    POS_NO,
    SUM(
        CASE
            WHEN DEAL_SECT = '0' THEN GSALE_AMT
            ELSE (-1) * GSALE_AMT
        END
    ) AS GROSS_SALE_AMT,
    SUM(COALESCE(GENURI_AMT, 0)) AS ENURI_AMT,
    COUNT(*) AS TRAN_COUNT
FROM HDTRAN..TR_TRAN_HEADER WITH (NOLOCK)
WHERE STORE_CD = ?
  AND POS_NO BETWEEN ? AND ?
  AND DEAL_SECT IN ('0', '1', '2')
  AND DEAL_TYPE IN ('0', '1', '2')
  AND DEAL_MODE = '01'
  AND (
        SALE_DT > ?
        OR (SALE_DT = ? AND SYS_TM >= ?)
      )
  AND (
        SALE_DT < ?
        OR (SALE_DT = ? AND SYS_TM < ?)
      )
GROUP BY POS_NO
ORDER BY POS_NO
"""


def _now_kst_naive() -> datetime:
    return datetime.utcnow() + KST_OFFSET


def _parse_custom_datetime(value: str | None, field_name: str) -> datetime:
    text = str(value or "").strip()
    for datetime_format in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, datetime_format)
        except ValueError:
            continue
    raise ValueError(f"{field_name} must be YYYY-MM-DDTHH:MM[:SS]")


def _event_date(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except ValueError as error:
        raise RuntimeError(f"{field_name} must be YYYY-MM-DD") from error


def normalize_family_sale_period(
    search_type: str,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    display_end_datetime: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_type = str(search_type or "").strip().lower()
    current_now = (now or _now_kst_naive()).replace(microsecond=0)

    if normalized_type == "recent_hour":
        start = current_now - timedelta(hours=1)
        end_exclusive = current_now
        display_end = current_now
    elif normalized_type in {"custom", "single"}:
        start = _parse_custom_datetime(start_datetime, "startDateTime")
        if normalized_type == "single" and display_end_datetime:
            end_exclusive = _parse_custom_datetime(end_datetime, "endDateTime")
            display_end = _parse_custom_datetime(
                display_end_datetime,
                "displayEndDateTime",
            )
            if start >= end_exclusive:
                raise ValueError("startDateTime must be before endDateTime")
        else:
            display_end = _parse_custom_datetime(end_datetime, "endDateTime")
            if start > display_end:
                raise ValueError("startDateTime must not be after endDateTime")
            end_exclusive = display_end + timedelta(minutes=1)
    elif normalized_type == "fixed":
        start = _parse_custom_datetime(start_datetime, "startDateTime")
        end_exclusive = _parse_custom_datetime(end_datetime, "endDateTime")
        display_end = (
            _parse_custom_datetime(display_end_datetime, "displayEndDateTime")
            if display_end_datetime
            else end_exclusive
        )
        if start >= end_exclusive:
            raise ValueError("startDateTime must be before endDateTime")
        if display_end < start or display_end > end_exclusive:
            raise ValueError("displayEndDateTime is outside the query period")
    else:
        raise ValueError("searchType must be recent_hour, custom, single or fixed")

    if display_end - start > MAX_CUSTOM_RANGE:
        raise ValueError("조회기간은 31일 이하여야 합니다.")

    current_event_start = _event_date(
        settings.FAMILY_SALE_CURRENT_EVENT_START_DATE,
        "FAMILY_SALE_CURRENT_EVENT_START_DATE",
    )
    previous_event_start = _event_date(
        settings.FAMILY_SALE_PREVIOUS_EVENT_START_DATE,
        "FAMILY_SALE_PREVIOUS_EVENT_START_DATE",
    )
    comparison_offset = current_event_start - previous_event_start
    if comparison_offset <= timedelta(0):
        raise RuntimeError("올해 행사 1일차는 전년도 행사 1일차보다 늦어야 합니다.")

    return {
        "search_type": normalized_type,
        "current_start": start,
        "current_end_exclusive": end_exclusive,
        "display_end": display_end,
        "previous_start": start - comparison_offset,
        "previous_end_exclusive": end_exclusive - comparison_offset,
        "previous_display_end": display_end - comparison_offset,
        "current_event_start_date": current_event_start.date().isoformat(),
        "previous_event_start_date": previous_event_start.date().isoformat(),
        "comparison_day_offset": comparison_offset.days,
    }


def get_family_sale_conn_str() -> str:
    if not settings.FAMILY_SALE_DB_USER or not settings.FAMILY_SALE_DB_PASSWORD:
        raise RuntimeError("한섬패밀리세일 DB 계정정보가 설정되지 않았습니다.")

    return (
        f"DRIVER={{{settings.FAMILY_SALE_DB_DRIVER}}};"
        f"SERVER=tcp:{settings.FAMILY_SALE_DB_HOST},{settings.FAMILY_SALE_DB_PORT};"
        f"DATABASE={settings.FAMILY_SALE_DB_DATABASE};"
        f"UID={settings.FAMILY_SALE_DB_USER};"
        f"PWD={settings.FAMILY_SALE_DB_PASSWORD};"
        f"TrustServerCertificate={settings.FAMILY_SALE_DB_TRUST_CERT};"
        f"Connection Timeout={settings.FAMILY_SALE_QUERY_TIMEOUT_SEC};"
    )


def _query_params(
    start: datetime,
    end_exclusive: datetime,
    pos_start: str,
    pos_end: str,
) -> tuple[Any, ...]:
    start_date = start.strftime("%Y%m%d")
    start_time = start.strftime("%H%M%S")
    end_date = end_exclusive.strftime("%Y%m%d")
    end_time = end_exclusive.strftime("%H%M%S")
    return (
        settings.FAMILY_SALE_STORE_CD,
        pos_start,
        pos_end,
        start_date,
        start_date,
        start_time,
        end_date,
        end_date,
        end_time,
    )


def _number(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _fetch_sales_rows(
    cursor,
    start: datetime,
    end_exclusive: datetime,
    pos_start: str,
    pos_end: str,
) -> dict[str, dict[str, Any]]:
    cursor.execute(
        SALES_QUERY,
        *_query_params(start, end_exclusive, pos_start, pos_end),
    )
    results: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall():
        pos_no = str(row[0]).strip()
        results[pos_no] = {
            "sales": _number(row[1]),
            "enuri": _number(row[2]),
            "count": int(row[3] or 0),
        }
    return results


def calculate_change_rate(current: Decimal, previous: Decimal) -> float | None:
    if previous == 0:
        return 0.0 if current == 0 else None
    return float(((current - previous) / abs(previous)) * Decimal("100"))


def _comparison_row(
    pos_no: str,
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    current_sales = _number(current.get("sales"))
    previous_sales = _number(previous.get("sales"))
    return {
        "posNo": pos_no,
        "currentSales": _json_number(current_sales),
        "previousSales": _json_number(previous_sales),
        "salesChangeRate": calculate_change_rate(current_sales, previous_sales),
        "currentEnuri": _json_number(_number(current.get("enuri"))),
        "previousEnuri": _json_number(_number(previous.get("enuri"))),
        "currentCount": int(current.get("count") or 0),
        "previousCount": int(previous.get("count") or 0),
    }


def fetch_family_sale_comparison(period: dict[str, Any]) -> dict[str, Any]:
    with pyodbc.connect(get_family_sale_conn_str()) as conn:
        conn.timeout = settings.FAMILY_SALE_QUERY_TIMEOUT_SEC
        cursor = conn.cursor()
        current_rows = _fetch_sales_rows(
            cursor,
            period["current_start"],
            period["current_end_exclusive"],
            settings.FAMILY_SALE_CURRENT_POS_START,
            settings.FAMILY_SALE_CURRENT_POS_END,
        )
        previous_rows = _fetch_sales_rows(
            cursor,
            period["previous_start"],
            period["previous_end_exclusive"],
            settings.FAMILY_SALE_PREVIOUS_POS_START,
            settings.FAMILY_SALE_PREVIOUS_POS_END,
        )

    pos_numbers = sorted(set(current_rows) | set(previous_rows))
    empty = {"sales": Decimal("0"), "enuri": Decimal("0"), "count": 0}
    rows = [
        _comparison_row(
            pos_no,
            current_rows.get(pos_no, empty),
            previous_rows.get(pos_no, empty),
        )
        for pos_no in pos_numbers
    ]

    current_total = {
        "sales": sum((_number(row["sales"]) for row in current_rows.values()), Decimal("0")),
        "enuri": sum((_number(row["enuri"]) for row in current_rows.values()), Decimal("0")),
        "count": sum(int(row["count"]) for row in current_rows.values()),
    }
    previous_total = {
        "sales": sum((_number(row["sales"]) for row in previous_rows.values()), Decimal("0")),
        "enuri": sum((_number(row["enuri"]) for row in previous_rows.values()), Decimal("0")),
        "count": sum(int(row["count"]) for row in previous_rows.values()),
    }

    return {
        "rows": rows,
        "total": _comparison_row("TOTAL", current_total, previous_total),
    }


def fetch_family_sale_single(period: dict[str, Any]) -> dict[str, Any]:
    current_event_start = _event_date(
        settings.FAMILY_SALE_CURRENT_EVENT_START_DATE,
        "FAMILY_SALE_CURRENT_EVENT_START_DATE",
    )
    if period["current_start"].date() < current_event_start.date():
        pos_start = settings.FAMILY_SALE_PREVIOUS_POS_START
        pos_end = settings.FAMILY_SALE_PREVIOUS_POS_END
    else:
        pos_start = settings.FAMILY_SALE_CURRENT_POS_START
        pos_end = settings.FAMILY_SALE_CURRENT_POS_END

    with pyodbc.connect(get_family_sale_conn_str()) as conn:
        conn.timeout = settings.FAMILY_SALE_QUERY_TIMEOUT_SEC
        cursor = conn.cursor()
        single_rows = _fetch_sales_rows(
            cursor,
            period["current_start"],
            period["current_end_exclusive"],
            pos_start,
            pos_end,
        )

    empty = {"sales": Decimal("0"), "enuri": Decimal("0"), "count": 0}
    rows = [
        _comparison_row(pos_no, single_rows[pos_no], empty)
        for pos_no in sorted(single_rows)
    ]
    total = {
        "sales": sum(
            (_number(row["sales"]) for row in single_rows.values()),
            Decimal("0"),
        ),
        "enuri": sum(
            (_number(row["enuri"]) for row in single_rows.values()),
            Decimal("0"),
        ),
        "count": sum(int(row["count"]) for row in single_rows.values()),
    }
    return {
        "rows": rows,
        "total": _comparison_row("TOTAL", total, empty),
        "posStart": pos_start,
        "posEnd": pos_end,
    }

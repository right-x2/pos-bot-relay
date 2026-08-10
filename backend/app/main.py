from pathlib import Path
import math
import re

from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse

from datetime import datetime

import traceback
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.azure_client import build_image_rag_query, extract_barcode_text, vision_answer
from app.command_router import parse_command
from app.db import (
    fetch_item_master_by_code,
    fetch_plu_master_by_code,
    get_post_request_by_key,
    get_post_request_by_seq,
    fetch_pos_pattern_group_by_pos,
    fetch_pos_pattern_lookup_count_by_pos,
    fetch_pos_pattern_lookup_page_by_pos,
    fetch_pos_pattern_details_by_pos,
    fetch_pos_pattern_groups_by_pos,
    insert_pos_faq_log,
    insert_post_request,
    insert_teams_faq_approval_notifications,
    update_pos_faq_log_help_yn,
    update_pos_pattern_value,
    update_pos_pattern_value_by_group_code,
    update_pos_master,
    update_pos_master_targets,
)
from app.rag import ask_rag, upsert_faq_vector, delete_faq_vector_by_key

logger = logging.getLogger("poschat.api")

app = FastAPI(title="POS FAQ RAG API")


@app.middleware("http")
async def log_api_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    start = time.perf_counter()
    logger.info(
        "[api] start method=%s path=%s request_id=%s",
        request.method,
        request.url.path,
        request_id,
    )

    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        status_code = response.status_code if response else "N/A"
        endpoint = request.scope.get("endpoint")
        endpoint_name = endpoint.__name__ if endpoint else None
        if endpoint_name:
            logger.info(
                "[api] end method=%s path=%s endpoint=%s status=%s elapsed_ms=%.1f request_id=%s",
                request.method,
                request.url.path,
                endpoint_name,
                status_code,
                elapsed_ms,
                request_id,
            )
        else:
            logger.info(
                "[api] end method=%s path=%s status=%s elapsed_ms=%.1f request_id=%s",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                request_id,
            )


class ChatRequest(BaseModel):
    userId: str | None = None
    question: str


class PostRequest(BaseModel):
    source: str
    teamsUserId: str
    teamsUserName: str
    category: str
    question: str
    answer: str
    keywords: str | None = None
    requestTime: datetime


class ApprovePostRequest(BaseModel):
    requestId: int
    adminUserName: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "requestId": 123,
                "adminUserName": "관리자홍길동"
            }
        }
    )


class ApprovePostByKeyRequest(BaseModel):
    regDt: str
    seq: int
    adminUserName: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "regDt": "20240101",
                "seq": 123,
                "adminUserName": "관리자홍길동"
            }
        }
    )


class DeleteEmbeddingByKeyRequest(BaseModel):
    regDt: str
    seq: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "regDt": "20240101",
                "seq": 123
            }
        }
    )


class UpdateHelpYnRequest(BaseModel):
    regDt: str
    seq: int
    helpYn: str
    feedbackText: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "regDt": "20260803",
                "seq": 12,
                "helpYn": "1",
                "feedbackText": "답변이 도움이 됐습니다."
            }
        }
    )


class CreatePosMasterRequest(BaseModel):
    posNo: str | None = None
    posKnd: str | None = None
    requestedBy: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "posNo": "1111,1112",
                "requestedBy": "system",
            }
        }
    )


class PatternLookupRequest(BaseModel):
    posNo: str
    searchType: str | None = None
    searchValue: str | None = None
    page: int = 1

    model_config = ConfigDict(
        json_schema_extra={
                "example": {
                    "posNo": "1011",
                    "searchType": None,
                    "searchValue": None,
                    "page": 1,
                }
        }
    )


class PatternUpdateRequest(BaseModel):
    patternGroupCode: str
    patternCode: str
    patternValue: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "patternGroupCode": "1001",
                "patternCode": "0001",
                "patternValue": "2",
            }
        }
    )


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def _error_response(message: str, error_code: str, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "requestId": None,
            "message": message,
            "errorCode": error_code,
        },
        media_type="application/json; charset=utf-8",
    )


def _success_response(request_id: int, message: str):
    return JSONResponse(
        content={
            "success": True,
            "requestId": request_id,
            "message": message,
            "errorCode": None,
        },
        media_type="application/json; charset=utf-8",
    )


def _is_approved_faq(record: dict) -> bool:
    return str(record.get("USE_YN") or "").strip() == "1"


def _complete_faq_approval(record: dict) -> int:
    """Reflect an externally approved FAQ in Chroma and queue Teams notices."""
    upsert_faq_vector(record)
    return insert_teams_faq_approval_notifications(
        record.get("TITLE"),
        record.get("REG_USER"),
    )


def _get_request_id(request: Request | None) -> str | None:
    if request is None:
        return None
    return getattr(request.state, "request_id", None)


def _log_api_step(request: Request | None, step: str, **kwargs) -> None:
    request_id = _get_request_id(request)
    if request_id:
        kwargs["request_id"] = request_id
    if kwargs:
        extras = " ".join(f"{key}={value}" for key, value in kwargs.items())
        logger.info("[api-step] %s %s", step, extras)
    else:
        logger.info("[api-step] %s", step)


def _save_history(
    request: Request | None,
    user_id: str | None,
    qry: str | None,
    answer: str | None,
    category: str | None,
    help_yn: str | None = None,
    filler1: str | None = None,
    filler2: str | None = None,
    filler3: str | None = None,
    reg_user: str | None = None,
) -> dict | None:
    try:
        reg_dt, seq = insert_pos_faq_log(
            user_id=user_id or "",
            qry=qry,
            answer=answer,
            category=category,
            help_yn=help_yn,
            filler1=filler1,
            filler2=filler2,
            filler3=filler3,
            reg_user=reg_user,
        )
        _log_api_step(
            request,
            "history_saved",
            log_reg_dt=reg_dt,
            log_seq=seq,
            category=category or "",
        )
        return {
            "saved": True,
            "regDt": reg_dt,
            "seq": seq,
        }
    except Exception as e:
        logger.exception("failed to save pos faq history: %s", e)
        return {
            "saved": False,
            "regDt": None,
            "seq": None,
        }


def _fit_log_value(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _get_reference_category(result: dict | None) -> str | None:
    if not result:
        return None
    references = result.get("references") or []
    if not references:
        return None
    first = references[0] or {}
    category = first.get("category")
    if category is None:
        return None
    text = str(category).strip()
    return text or None


def _normalize_limit(value: int | None) -> int | None:
    if value is None:
        return None
    if value <= 0:
        return None
    return value


def _normalize_reg_dt(value: str | None) -> str | None:
    raw = _empty_to_none(value)
    if raw is None:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 8:
        return None
    return digits


def _normalize_item_type(value: str | None) -> str | None:
    token = _empty_to_none(value)
    if token is None:
        return None

    normalized = re.sub(r"\s+", "", token).upper()
    if normalized in ("상", "상품", "ITEM", "SANG"):
        return "ITEM"
    if normalized in ("단", "단품", "PLU", "DAN"):
        return "PLU"
    return None


def _normalize_pos_token(value: str | None) -> str | None:
    raw = _empty_to_none(value)
    if raw is None:
        return None
    if not raw.isdigit():
        return None
    return raw


def _parse_pos_master_targets(pos_no_raw: str | None, pos_knd_raw: str | None) -> dict | None:
    pos_knd = _empty_to_none(pos_knd_raw)
    pos_no_text = _empty_to_none(pos_no_raw)

    if pos_knd and pos_no_text:
        raise ValueError("posNo and posKnd cannot be used together")

    if pos_knd:
        return {
            "type": "pos_knd",
            "pos_knd": pos_knd,
        }

    if pos_no_text is None:
        return None

    compact = re.sub(r"\s+", "", pos_no_text)
    if "," in compact:
        tokens = [token for token in compact.split(",") if token]
        if not tokens:
            return None
        pos_numbers = []
        for token in tokens:
            normalized = _normalize_pos_token(token)
            if normalized is None:
                raise ValueError("invalid posNo list")
            pos_numbers.append(normalized)
        return {
            "type": "list",
            "pos_numbers": pos_numbers,
        }

    for separator in ("~", "-"):
        if separator in compact:
            parts = [part for part in compact.split(separator) if part]
            if len(parts) != 2:
                raise ValueError("invalid posNo range")
            start = _normalize_pos_token(parts[0])
            end = _normalize_pos_token(parts[1])
            if start is None or end is None:
                raise ValueError("invalid posNo range")
            if len(start) != len(end):
                raise ValueError("range width mismatch")
            if int(start) > int(end):
                raise ValueError("range start must be <= end")
            return {
                "type": "range",
                "pos_range": (start, end),
            }

    normalized = _normalize_pos_token(compact)
    if normalized is None:
        raise ValueError("invalid posNo")
    return {
        "type": "single",
        "pos_numbers": [normalized],
    }


_PATTERN_CODE_KEYS = ("PTN_CD", "PATTERN_CD", "PAT_CD", "CODE", "CD")
_PATTERN_NAME_KEYS = ("PTN_GRP_NM", "PTN_NM", "PATTERN_NM", "PATTERN_NAME", "NAME", "NM")
_PATTERN_GROUP_CODE_KEYS = ("PTN_GRP_CD", "GRP_CD", "GROUP_CD")
_PATTERN_GROUP_NAME_KEYS = ("PTN_GRP_NM", "GRP_NM", "GROUP_NM", "PTN_GRP_NAME")
_PATTERN_VALUE_KEYS = ("PTN_VAL",)
_PATTERN_BIGO_KEYS = ("PTN_DTL_BIGO", "BIGO", "MEMO", "REMARK")


def _row_matches_keys(row: dict, keys: tuple[str, ...], token: str, exact: bool = False) -> bool:
    if not token:
        return True
    token_lower = token.lower()
    for key in keys:
        value = _get_row_value(row, (key,))
        if value is None:
            continue
        value_str = str(value)
        if exact:
            if value_str.lower() == token_lower:
                return True
        else:
            if token_lower in value_str.lower():
                return True
    return False


def _get_row_value(row: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        for row_key, value in row.items():
            if row_key.lower() == key.lower() and value not in (None, ""):
                return str(value)
    return None


def _summarize_group_row(row: dict) -> str | None:
    code = _get_row_value(row, _PATTERN_GROUP_CODE_KEYS)
    name = _get_row_value(row, _PATTERN_GROUP_NAME_KEYS)
    if code and name:
        return f"{code} | {name}"
    if code:
        return str(code)
    if name:
        return str(name)
    return None


def _summarize_detail_row(row: dict) -> str:
    code = _get_row_value(row, _PATTERN_CODE_KEYS)
    name = _get_row_value(row, _PATTERN_NAME_KEYS)
    values = []
    for key in _PATTERN_VALUE_KEYS:
        value = _get_row_value(row, (key,))
        if value not in (None, ""):
            values.append(str(value))
    bigo = _get_row_value(row, _PATTERN_BIGO_KEYS)

    parts = []
    if code:
        parts.append(f"코드: {code}")
    if name:
        parts.append(f"명: {name}")
    if values:
        parts.append(f"값: {', '.join(values)}")
    if bigo:
        parts.append(f"PTN_DTL_BIGO: {bigo}")
    if not parts:
        preview = list(row.items())[:3]
        parts = [f"{key}: {value}" for key, value in preview]
    return " | ".join(parts)


def _group_pattern_detail_rows(details: list[dict]) -> list[tuple[str, list[dict]]]:
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []

    for row in details:
        group_code = _get_row_value(row, _PATTERN_GROUP_CODE_KEYS) or "UNKNOWN"
        if group_code not in grouped:
            grouped[group_code] = []
            order.append(group_code)
        grouped[group_code].append(row)

    return [(group_code, grouped[group_code]) for group_code in order]


def _build_pattern_lookup_items(details: list[dict]) -> list[dict]:
    items: list[dict] = []
    for row in details:
        items.append(
            {
                "patternCode": _get_row_value(row, _PATTERN_CODE_KEYS),
                "patternName": _get_row_value(row, _PATTERN_NAME_KEYS),
                "patternValue": _get_row_value(row, _PATTERN_VALUE_KEYS),
                "PTN_DTL_BIGO": _get_row_value(row, _PATTERN_BIGO_KEYS),
            }
        )
    return items


def _normalize_pattern_lookup_search_type(value: str | None) -> tuple[str | None, bool]:
    if value is None:
        return None, True

    normalized = str(value).strip()
    if not normalized:
        return None, False

    if normalized in ("0", "1"):
        return normalized, True
    return None, False


def _normalize_pattern_lookup_page(value: int | None) -> int | None:
    if value is None:
        return 1
    if value < 1:
        return None
    return value


def _filter_pattern_rows(rows: list[dict], pattern: dict | None) -> list[dict]:
    if not pattern:
        return rows
    value = pattern.get("value")
    if not value:
        return rows

    p_type = pattern.get("type")
    if p_type == "code":
        return [row for row in rows if _row_matches_keys(row, _PATTERN_CODE_KEYS, value, exact=True)]
    return [row for row in rows if _row_matches_keys(row, _PATTERN_NAME_KEYS, value, exact=False)]


def _pattern_lookup_filters_from_request(
    pattern_code: str | None,
    pattern_name: str | None,
) -> tuple[str | None, str | None]:
    code = _empty_to_none(pattern_code)
    name = _empty_to_none(pattern_name)

    if code and name:
        raise ValueError("patternCode and patternName cannot be used together")

    return code, name


def _pattern_lookup_filters_from_command(pattern: dict | None) -> tuple[str | None, str | None]:
    if not pattern:
        return None, None

    value = _empty_to_none(str(pattern.get("value")) if pattern.get("value") is not None else None)
    if value is None:
        return None, None

    if pattern.get("type") == "code":
        return value, None
    if pattern.get("type") == "name":
        return None, value
    return None, None


def _format_pattern_answer(
    pos_no: str,
    pattern: dict | None,
    groups: list[dict],
    details: list[dict],
    max_rows: int = 20,
) -> str:
    label = None
    if pattern:
        p_type = pattern.get("type")
        p_value = pattern.get("value")
        if p_value:
            label = f"{'패턴코드' if p_type == 'code' else '패턴명'}: {p_value}"

    header = f"POS {pos_no} 패턴 조회 결과"
    if label:
        header += f" ({label})"

    lines = [header]

    group_label = None
    if groups:
        group_label = _summarize_group_row(groups[0])
    if group_label:
        lines.append(f"패턴그룹: {group_label}")
    lines.append(f"패턴상세 {len(details)}건 (최대 {max_rows}건 조회 가능)")

    if not details:
        lines.append("일치하는 패턴이 없습니다.")
        return "\n".join(lines)

    lines.append(f"패턴 목록 (최대 {max_rows}건 조회 가능)")
    for row in details[:max_rows]:
        lines.append(f"- {_summarize_detail_row(row)}")
    if len(details) > max_rows:
        lines.append(f"... 외 {len(details) - max_rows}건")

    return "\n".join(lines)


@app.post("/api/posts/request")
def register_post_request(req: PostRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        required_fields = {
            "source": req.source,
            "teamsUserId": req.teamsUserId,
            "teamsUserName": req.teamsUserName,
            "category": req.category,
            "question": req.question,
            "answer": req.answer,
        }

        for field_name, value in required_fields.items():
            if _empty_to_none(value) is None:
                _log_api_step(request, "validation_failed", field=field_name)
                return _error_response(f"{field_name} is empty", "VALIDATION_ERROR", 400)

        if req.requestTime.tzinfo is None or req.requestTime.utcoffset() is None:
            _log_api_step(request, "validation_failed", field="requestTime")
            return _error_response("requestTime must include timezone offset", "INVALID_REQUEST_TIME", 400)

        teams_user_id = _empty_to_none(req.teamsUserId) or ""

        _log_api_step(request, "db_insert_start")
        print(req)
        insert_result = insert_post_request(
            _empty_to_none(req.source) or "",
            teams_user_id,
            _empty_to_none(req.teamsUserName) or "",
            _empty_to_none(req.category) or "",
            _empty_to_none(req.question) or "",
            _empty_to_none(req.answer) or "",
            _empty_to_none(req.keywords),
            req.requestTime,
            use_yn="0",
        )
        record_id = insert_result["seq"]

        _log_api_step(request, "db_insert_done", record_id=record_id)
        return _success_response(record_id, "게시글이 승인대기 상태로 등록되었습니다.")

    except Exception:
        traceback.print_exc()
        return _error_response("게시글 등록 요청 처리 중 오류가 발생했습니다.", "REGISTER_FAILED", 500)


@app.post(
    "/api/admin/posts/approve",
    summary="게시글 승인",
    description="외부에서 승인된 FAQ를 확인하고 벡터DB 반영 후 Teams 승인 알림을 등록합니다."
)
def approve_post(req: ApprovePostRequest, request: Request):
    try:
        print("승인 API진입============")
        _log_api_step(request, "validate")
        if req.requestId <= 0:
            _log_api_step(request, "validation_failed", field="requestId")
            return _error_response("requestId is invalid", "VALIDATION_ERROR", 400)

        if _empty_to_none(req.adminUserName) is None:
            _log_api_step(request, "validation_failed", field="adminUserName")
            return _error_response("adminUserName is empty", "VALIDATION_ERROR", 400)

        _log_api_step(request, "db_lookup_start", post_request_id=req.requestId)
        record = get_post_request_by_seq(req.requestId)

        if record is None:
            _log_api_step(request, "not_found", post_request_id=req.requestId)
            return _error_response("승인 대상 FAQ를 찾을 수 없습니다.", "NOT_FOUND", 404)

        if not _is_approved_faq(record):
            _log_api_step(request, "not_approved", post_request_id=req.requestId)
            return _error_response(
                "아직 승인되지 않은 FAQ입니다.",
                "FAQ_NOT_APPROVED",
                409,
            )

        _log_api_step(request, "vector_upsert_start", post_request_id=req.requestId)
        notification_count = _complete_faq_approval(record)
        _log_api_step(request, "vector_upsert_done", post_request_id=req.requestId)
        _log_api_step(
            request,
            "teams_notification_queued",
            post_request_id=req.requestId,
            recipient_count=notification_count,
        )

        return _success_response(
            req.requestId,
            f"게시글이 승인되어 벡터에 반영되었고 알림 {notification_count}건이 등록되었습니다.",
        )

    except Exception:
        traceback.print_exc()
        return _error_response("게시글 승인 처리 중 오류가 발생했습니다.", "APPROVE_FAILED", 500)


@app.post(
    "/api/admin/posts/approve-by-key",
    summary="게시글 승인(등록일/SEQ)",
    description="REG_DT와 SEQ로 외부 승인 상태를 확인하고 벡터DB 반영 후 Teams 승인 알림을 등록합니다."
)
def approve_post_by_key(req: ApprovePostByKeyRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        print(req)
        reg_dt = _normalize_reg_dt(req.regDt)
        if reg_dt is None:
            _log_api_step(request, "validation_failed", field="regDt")
            return _error_response("regDt is invalid", "VALIDATION_ERROR", 400)

        if req.seq <= 0:
            _log_api_step(request, "validation_failed", field="seq")
            return _error_response("seq is invalid", "VALIDATION_ERROR", 400)

        _log_api_step(request, "db_lookup_start", reg_dt=reg_dt, seq=req.seq)
        record = get_post_request_by_key(reg_dt, req.seq)
        print(record)
        if record is None:
            _log_api_step(request, "not_found", reg_dt=reg_dt, seq=req.seq)
            return _error_response("승인 대상 FAQ를 찾을 수 없습니다.", "NOT_FOUND", 404)

        if not _is_approved_faq(record):
            _log_api_step(request, "not_approved", reg_dt=reg_dt, seq=req.seq)
            return _error_response(
                "아직 승인되지 않은 FAQ입니다.",
                "FAQ_NOT_APPROVED",
                409,
            )

        _log_api_step(request, "vector_upsert_start", reg_dt=reg_dt, seq=req.seq)
        notification_count = _complete_faq_approval(record)
        _log_api_step(request, "vector_upsert_done", reg_dt=reg_dt, seq=req.seq)
        _log_api_step(
            request,
            "teams_notification_queued",
            reg_dt=reg_dt,
            seq=req.seq,
            recipient_count=notification_count,
        )

        return _success_response(
            req.seq,
            f"게시글이 승인되어 벡터에 반영되었고 알림 {notification_count}건이 등록되었습니다.",
        )

    except Exception:
        traceback.print_exc()
        return _error_response("게시글 승인 처리 중 오류가 발생했습니다.", "APPROVE_FAILED", 500)


@app.post(
    "/api/logs/help-yn",
    summary="히스토리 HELP_YN 수정",
    description="POS_FAQ_LOG의 REG_DT와 SEQ 기준으로 HELP_YN 값을 수정합니다."
)
def update_help_yn(req: UpdateHelpYnRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        reg_dt = _normalize_reg_dt(req.regDt)
        if reg_dt is None:
            _log_api_step(request, "validation_failed", field="regDt")
            return _error_response("regDt is invalid", "VALIDATION_ERROR", 400)

        if req.seq <= 0:
            _log_api_step(request, "validation_failed", field="seq")
            return _error_response("seq is invalid", "VALIDATION_ERROR", 400)

        help_yn = _empty_to_none(req.helpYn) or ""
        if help_yn not in ("0", "1"):
            _log_api_step(request, "validation_failed", field="helpYn")
            return _error_response("helpYn must be 0 or 1", "VALIDATION_ERROR", 400)

        feedback_text = _fit_log_value(_empty_to_none(req.feedbackText), 300)

        _log_api_step(request, "db_update_help_yn_start", reg_dt=reg_dt, seq=req.seq, help_yn=help_yn)
        updated = update_pos_faq_log_help_yn(reg_dt, req.seq, help_yn, feedback_text)
        if updated <= 0:
            _log_api_step(request, "not_found", reg_dt=reg_dt, seq=req.seq)
            return _error_response("수정 대상 로그를 찾을 수 없습니다.", "NOT_FOUND", 404)

        _log_api_step(request, "db_update_help_yn_done", reg_dt=reg_dt, seq=req.seq, help_yn=help_yn, updated=updated)
        return _success_response(req.seq, "HELP_YN이 수정되었습니다.")

    except Exception:
        traceback.print_exc()
        return _error_response("HELP_YN 수정 중 오류가 발생했습니다.", "UPDATE_HELP_YN_FAILED", 500)


@app.post(
    "/api/admin/posts/delete-embedding-by-key",
    summary="게시글 임베딩 삭제(등록일/SEQ)",
    description="FAQ 등록일자(REG_DT)와 SEQ로 벡터DB에서 해당 문서를 삭제합니다."
)
def delete_post_embedding_by_key(req: DeleteEmbeddingByKeyRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        reg_dt = _normalize_reg_dt(req.regDt)
        if reg_dt is None:
            _log_api_step(request, "validation_failed", field="regDt")
            return _error_response("regDt is invalid", "VALIDATION_ERROR", 400)

        if req.seq <= 0:
            _log_api_step(request, "validation_failed", field="seq")
            return _error_response("seq is invalid", "VALIDATION_ERROR", 400)

        _log_api_step(request, "vector_delete_start", reg_dt=reg_dt, seq=req.seq)
        result = delete_faq_vector_by_key(reg_dt, req.seq)
        if not result.get("found"):
            _log_api_step(request, "not_found", reg_dt=reg_dt, seq=req.seq)
            return _error_response("벡터에서 삭제할 FAQ를 찾을 수 없습니다.", "NOT_FOUND", 404)

        _log_api_step(request, "vector_delete_done", reg_dt=reg_dt, seq=req.seq)
        return _success_response(req.seq, "벡터에서 삭제되었습니다.")

    except Exception:
        traceback.print_exc()
        return _error_response("벡터 삭제 처리 중 오류가 발생했습니다.", "DELETE_FAILED", 500)


@app.get("/api/health")
def health(request: Request):
    _log_api_step(request, "health")
    return JSONResponse(
        content={
            "resCd": "0000",
            "resMsg": "OK",
            "answer": ""
        },
        media_type="application/json; charset=utf-8"
    )


def _update_pos_master_and_message(targets: dict):
    store_cd = "210"
    target_type = targets.get("type")
    if target_type == "pos_knd":
        updated = update_pos_master_targets(
            store_cd,
            pos_knd=targets["pos_knd"],
        )
        label = f"POS_KND {targets['pos_knd']}"
    elif target_type == "range":
        start, end = targets["pos_range"]
        updated = update_pos_master_targets(
            store_cd,
            pos_range=(start, end),
        )
        label = f"POS {start}~{end}"
    elif target_type in ("single", "list"):
        pos_numbers = targets["pos_numbers"]
        updated = update_pos_master_targets(
            store_cd,
            pos_numbers=pos_numbers,
        )
        if len(pos_numbers) == 1:
            label = f"POS {pos_numbers[0]}"
        else:
            label = f"POS {','.join(pos_numbers)}"
    else:
        raise ValueError("invalid POS master target")

    ok = updated > 0
    if ok:
        message = f"POS 마스터 업데이트 완료: {store_cd} {label} (반영 {updated}건)"
    else:
        message = "대상 POS를 찾을 수 없습니다."
    return ok, message, store_cd, updated


@app.post("/tools/create_pos_master")
def create_pos_master_tool(req: CreatePosMasterRequest, request: Request):
    _log_api_step(request, "validate")
    try:
        targets = _parse_pos_master_targets(req.posNo, req.posKnd)
    except ValueError as e:
        _log_api_step(request, "validation_failed", field="pos_target")
        return JSONResponse(
            content={
                "ok": False,
                "message": str(e),
            },
            media_type="application/json; charset=utf-8",
        )

    if targets is None:
        _log_api_step(request, "validation_failed", field="posNo")
        return JSONResponse(
            content={
                "ok": False,
                "message": "posNo or posKnd is required",
            },
            media_type="application/json; charset=utf-8",
        )

    try:
        _log_api_step(request, "update_pos_master_start", target_type=targets.get("type"))
        ok, message, store_cd, updated = _update_pos_master_and_message(targets)
        _log_api_step(request, "update_pos_master_done", target_type=targets.get("type"), updated=updated)

        return JSONResponse(
            content={
                "ok": ok,
                "message": message,
                "storeCd": store_cd,
                "posNo": req.posNo,
                "posKnd": req.posKnd,
                "targetType": targets.get("type"),
                "updated": updated,
            },
            media_type="application/json; charset=utf-8",
        )
    except Exception:
        traceback.print_exc()
        return JSONResponse(
            content={
                "ok": False,
                "message": "POS 마스터 업데이트 중 오류가 발생했습니다.",
            },
            media_type="application/json; charset=utf-8",
        )


@app.post("/tools/pattern_update")
def pattern_update_tool(req: PatternUpdateRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        pattern_group_code = _empty_to_none(
            str(req.patternGroupCode) if req.patternGroupCode is not None else None
        )
        pattern_code = _empty_to_none(str(req.patternCode) if req.patternCode is not None else None)
        pattern_value = _empty_to_none(
            str(req.patternValue) if req.patternValue is not None else None
        )

        if pattern_group_code is None:
            _log_api_step(request, "validation_failed", field="patternGroupCode")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "patternGroupCode is empty",
                },
                media_type="application/json; charset=utf-8",
            )

        if pattern_code is None:
            _log_api_step(request, "validation_failed", field="patternCode")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "patternCode is empty",
                },
                media_type="application/json; charset=utf-8",
            )

        if pattern_value is None:
            _log_api_step(request, "validation_failed", field="patternValue")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "patternValue is empty",
                },
                media_type="application/json; charset=utf-8",
            )

        _log_api_step(
            request,
            "pattern_update_start",
            pattern_group_code=pattern_group_code,
            pattern_code=pattern_code,
        )
        updated = update_pos_pattern_value_by_group_code(
            pattern_group_code,
            pattern_code,
            pattern_value,
        )
        ok = updated > 0
        message = (
            f"패턴 수정 완료: {pattern_group_code}-{pattern_code} (반영 {updated}건)"
            if ok
            else "대상 패턴을 찾을 수 없습니다."
        )
        _log_api_step(
            request,
            "pattern_update_done",
            pattern_group_code=pattern_group_code,
            pattern_code=pattern_code,
            updated=updated,
        )

        return JSONResponse(
            content={
                "ok": ok,
                "message": message,
                "patternGroupCode": pattern_group_code,
                "patternCode": pattern_code,
                "patternValue": pattern_value,
                "updated": updated,
            },
            media_type="application/json; charset=utf-8",
        )
    except Exception:
        traceback.print_exc()
        return JSONResponse(
            content={
                "ok": False,
                "message": "패턴 수정 중 오류가 발생했습니다.",
            },
            media_type="application/json; charset=utf-8",
        )


@app.post("/tools/pattern_lookup")
def pattern_lookup_tool(req: PatternLookupRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        pos_no = _empty_to_none(str(req.posNo) if req.posNo is not None else None)
        search_type, search_type_valid = _normalize_pattern_lookup_search_type(req.searchType)
        search_value = _empty_to_none(str(req.searchValue) if req.searchValue is not None else None)
        page = _normalize_pattern_lookup_page(req.page)

        if pos_no is None:
            _log_api_step(request, "validation_failed", field="posNo")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "posNo is empty",
                },
                media_type="application/json; charset=utf-8",
            )

        if not search_type_valid:
            _log_api_step(request, "validation_failed", field="searchType")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "searchType must be null, 0 or 1",
                },
                media_type="application/json; charset=utf-8",
            )

        if search_type is not None and search_value is None:
            _log_api_step(request, "validation_failed", field="searchValue")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "searchValue is empty",
                },
                media_type="application/json; charset=utf-8",
            )

        if page is None:
            _log_api_step(request, "validation_failed", field="page")
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "page must be 1 or greater",
                },
                media_type="application/json; charset=utf-8",
            )

        page_size = 10

        _log_api_step(
            request,
            "lookup_count_start",
            pos_no=pos_no,
            search_type=search_type or "",
            search_value=search_value or "",
            page=page,
        )
        pattern_group = fetch_pos_pattern_group_by_pos(pos_no)
        total_count = fetch_pos_pattern_lookup_count_by_pos(pos_no, search_type, search_value)
        total_pages = math.ceil(total_count / page_size) if total_count else 0
        _log_api_step(
            request,
            "lookup_count_done",
            pos_no=pos_no,
            total_count=total_count,
            total_pages=total_pages,
        )

        _log_api_step(
            request,
            "lookup_page_start",
            pos_no=pos_no,
            search_type=search_type or "",
            search_value=search_value or "",
            page=page,
            page_size=page_size,
        )
        rows = fetch_pos_pattern_lookup_page_by_pos(
            pos_no,
            search_type,
            search_value,
            page,
            page_size,
        )
        _log_api_step(
            request,
            "lookup_page_done",
            pos_no=pos_no,
            row_count=len(rows),
        )

        pattern_group_code = None
        pattern_group_name = None
        if pattern_group is not None:
            pattern_group_code = _get_row_value(pattern_group, _PATTERN_GROUP_CODE_KEYS)
            pattern_group_name = _get_row_value(pattern_group, _PATTERN_GROUP_NAME_KEYS)
        if pattern_group_code is None and rows:
            pattern_group_code = _get_row_value(rows[0], _PATTERN_GROUP_CODE_KEYS)
        if pattern_group_name is None and rows:
            pattern_group_name = _get_row_value(rows[0], _PATTERN_GROUP_NAME_KEYS)

        has_previous = page > 1
        has_next = total_pages > 0 and page < total_pages

        return JSONResponse(
            content={
                "ok": True,
                "posNo": pos_no,
                "patternGroupCode": pattern_group_code,
                "patternGroupName": pattern_group_name,
                "searchType": search_type,
                "searchValue": search_value,
                "page": page,
                "pageSize": page_size,
                "totalCount": total_count,
                "totalPages": total_pages,
                "hasPrevious": has_previous,
                "hasNext": has_next,
                "patterns": _build_pattern_lookup_items(rows),
            },
            media_type="application/json; charset=utf-8",
        )
    except Exception:
        traceback.print_exc()
        return JSONResponse(
            content={
                "ok": False,
                "message": "패턴 조회 중 오류가 발생했습니다.",
            },
            media_type="application/json; charset=utf-8",
        )


@app.post("/api/rag/chat")
def chat(req: ChatRequest, request: Request):
    try:
        _log_api_step(request, "validate")
        question = req.question.strip()

        if not question:
            _log_api_step(request, "validation_failed", field="question")
            return JSONResponse(
                content={
                    "resCd": "9999",
                    "resMsg": "question is empty",
                    "answer": "질문을 입력해주세요."
                },
                media_type="application/json; charset=utf-8"
            )

        cmd = parse_command(question)
        _log_api_step(request, "parse_command", cmd_type=cmd.get("type") if cmd else "NONE")
        if cmd and cmd.get("type") == "CREATE_POS_MASTER":
            try:
                targets = _parse_pos_master_targets(cmd["pos_no"], None)
                if targets is None:
                    raise ValueError("invalid POS master target")

                _log_api_step(
                    request,
                    "cmd_create_pos_master_start",
                    pos_no=cmd["pos_no"],
                    target_type=targets.get("type"),
                )
                _, message, store_cd, _ = _update_pos_master_and_message(targets)
                answer = message or f"POS 마스터 업데이트 완료: {store_cd}-{cmd['pos_no']}"
                history = _save_history(
                    request,
                    user_id=req.userId,
                    qry=question,
                    answer=answer,
                    category=None,
                )

                _log_api_step(
                    request,
                    "cmd_create_pos_master_done",
                    pos_no=cmd["pos_no"],
                    target_type=targets.get("type"),
                )
                return JSONResponse(
                    content={
                        "resCd": "0000",
                        "resMsg": "success",
                        "answer": answer,
                        "logSaved": history["saved"],
                        "logRegDt": history["regDt"],
                        "logSeq": history["seq"],
                    },
                    media_type="application/json; charset=utf-8"
                )
            except Exception:
                traceback.print_exc()
                return JSONResponse(
                    content={
                        "resCd": "9999",
                        "resMsg": "mcp_error",
                        "answer": "POS 마스터 생성 중 오류가 발생했습니다."
                    },
                    media_type="application/json; charset=utf-8"
                )

        if cmd and cmd.get("type") == "PATTERN_LOOKUP":
            try:
                pos_no = cmd["pos_no"]
                pattern = cmd.get("pattern")
                pattern_code, pattern_name = _pattern_lookup_filters_from_command(pattern)

                _log_api_step(
                    request,
                    "cmd_pattern_lookup_start",
                    pos_no=pos_no,
                    pattern_code=pattern_code or "",
                    pattern_name=pattern_name or "",
                )
                groups = fetch_pos_pattern_groups_by_pos(
                    pos_no,
                    200,
                    pattern_code=pattern_code,
                    pattern_name=pattern_name,
                )
                details = fetch_pos_pattern_details_by_pos(
                    pos_no,
                    500,
                    pattern_code=pattern_code,
                    pattern_name=pattern_name,
                )

                answer = _format_pattern_answer(pos_no, pattern, groups, details)
                history = _save_history(
                    request,
                    user_id=req.userId,
                    qry=question,
                    answer=answer,
                    category=None,
                )

                _log_api_step(
                    request,
                    "cmd_pattern_lookup_done",
                    pos_no=pos_no,
                    group_count=len(groups),
                    detail_count=len(details),
                )
                return JSONResponse(
                    content={
                        "resCd": "0000",
                        "resMsg": "success",
                        "answer": answer,
                        "logSaved": history["saved"],
                        "logRegDt": history["regDt"],
                        "logSeq": history["seq"],
                    },
                    media_type="application/json; charset=utf-8"
                )
            except Exception:
                traceback.print_exc()
                return JSONResponse(
                    content={
                        "resCd": "9999",
                        "resMsg": "mcp_error",
                        "answer": "패턴 조회 중 오류가 발생했습니다."
                    },
                    media_type="application/json; charset=utf-8"
                )

        if cmd and cmd.get("type") == "PATTERN_UPDATE":
            try:
                pos_no = cmd["pos_no"]
                pattern = cmd["pattern"]
                new_value = cmd["value"]

                _log_api_step(request, "cmd_pattern_update_start", pos_no=pos_no)
                updated = update_pos_pattern_value(
                    pos_no,
                    pattern.get("type") or "code",
                    pattern.get("value") or "",
                    new_value,
                )

                if updated > 0:
                    label = "패턴코드" if pattern.get("type") == "code" else "패턴명"
                    answer = f"POS {pos_no} {label} {pattern.get('value')} PTN_VAL을 {new_value}로 수정했습니다. (반영 {updated}건)"
                else:
                    answer = "대상 패턴을 찾을 수 없습니다."
                history = _save_history(
                    request,
                    user_id=req.userId,
                    qry=question,
                    answer=answer,
                    category=None,
                )

                _log_api_step(request, "cmd_pattern_update_done", pos_no=pos_no, updated=updated)
                return JSONResponse(
                    content={
                        "resCd": "0000",
                        "resMsg": "success",
                        "answer": answer,
                        "logSaved": history["saved"],
                        "logRegDt": history["regDt"],
                        "logSeq": history["seq"],
                    },
                    media_type="application/json; charset=utf-8"
                )
            except Exception:
                traceback.print_exc()
                return JSONResponse(
                    content={
                        "resCd": "9999",
                        "resMsg": "mcp_error",
                        "answer": "패턴 수정 중 오류가 발생했습니다."
                    },
                    media_type="application/json; charset=utf-8"
                )

        if cmd and cmd.get("type") == "PATTERN_LOOKUP_MISSING_POS":
            _log_api_step(request, "cmd_pattern_lookup_missing_pos")
            answer = "POS번호를 함께 입력해주세요. 예) POS 1011 패턴 조회 또는 POS 1011 패턴명 카드결제 조회"
            history = _save_history(
                request,
                user_id=req.userId,
                qry=question,
                answer=answer,
                category=None,
            )
            return JSONResponse(
                content={
                    "resCd": "0000",
                    "resMsg": "success",
                    "answer": answer,
                    "logSaved": history["saved"],
                    "logRegDt": history["regDt"],
                    "logSeq": history["seq"],
                },
                media_type="application/json; charset=utf-8"
            )

        if cmd and cmd.get("type") == "PATTERN_UPDATE_MISSING_POS":
            _log_api_step(request, "cmd_pattern_update_missing_pos")
            answer = "POS번호를 함께 입력해주세요. 예) POS 5556 1001 패턴 1로 수정"
            history = _save_history(
                request,
                user_id=req.userId,
                qry=question,
                answer=answer,
                category=None,
            )
            return JSONResponse(
                content={
                    "resCd": "0000",
                    "resMsg": "success",
                    "answer": answer,
                    "logSaved": history["saved"],
                    "logRegDt": history["regDt"],
                    "logSeq": history["seq"],
                },
                media_type="application/json; charset=utf-8"
            )

        if cmd and cmd.get("type") == "PATTERN_UPDATE_MISSING_PATTERN":
            _log_api_step(request, "cmd_pattern_update_missing_pattern")
            answer = "패턴코드 또는 패턴명을 함께 입력해주세요. 예) POS 5556 1001 패턴 1로 수정"
            history = _save_history(
                request,
                user_id=req.userId,
                qry=question,
                answer=answer,
                category=None,
            )
            return JSONResponse(
                content={
                    "resCd": "0000",
                    "resMsg": "success",
                    "answer": answer,
                    "logSaved": history["saved"],
                    "logRegDt": history["regDt"],
                    "logSeq": history["seq"],
                },
                media_type="application/json; charset=utf-8"
            )

        if cmd and cmd.get("type") == "PATTERN_UPDATE_MISSING_VALUE":
            _log_api_step(request, "cmd_pattern_update_missing_value")
            answer = "변경할 패턴값을 함께 입력해주세요. 예) POS 5556 1001 패턴 1로 수정"
            history = _save_history(
                request,
                user_id=req.userId,
                qry=question,
                answer=answer,
                category=None,
            )
            return JSONResponse(
                content={
                    "resCd": "0000",
                    "resMsg": "success",
                    "answer": answer,
                    "logSaved": history["saved"],
                    "logRegDt": history["regDt"],
                    "logSeq": history["seq"],
                },
                media_type="application/json; charset=utf-8"
            )

        result = ask_rag(question)
        history = _save_history(
            request,
            user_id=req.userId,
            qry=question,
            answer=result["answer"],
            category=_get_reference_category(result),
        )
        _log_api_step(
            request,
            "rag_answer_done",
            ref_count=len(result.get("references", [])),
        )

        return JSONResponse(
            content={
                "resCd": "0000",
                "resMsg": "success",
                "answer": result["answer"],
                "logSaved": history["saved"],
                "logRegDt": history["regDt"],
                "logSeq": history["seq"],
            },
            media_type="application/json; charset=utf-8"
        )

    except Exception as e:
        traceback.print_exc()

        return JSONResponse(
            content={
                "resCd": "9999",
                "resMsg": str(e),
                "answer": "답변 생성 중 오류가 발생했습니다."
            },
            media_type="application/json; charset=utf-8"
        )


@app.post("/api/items/search")
async def search_item_api(
    request: Request,
    itemType: str = Form(..., alias="상단품구분"),
    code: str = Form("", alias="코드"),
    barcodeImage: UploadFile | None = File(None, alias="바코드이미지"),
):
    try:
        normalized_type = _normalize_item_type(itemType)
        if normalized_type is None:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": "itemType must be 상품 or 단품",
                },
                media_type="application/json; charset=utf-8",
            )

        input_code = _empty_to_none(code)
        barcode_text = None

        if barcodeImage is not None:
            content_type = str(barcodeImage.content_type or "").strip().lower()
            if not content_type.startswith("image/"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "message": "barcodeImage must be an image",
                    },
                    media_type="application/json; charset=utf-8",
                )

            image_bytes = await barcodeImage.read()
            if not image_bytes:
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "message": "barcodeImage is empty",
                    },
                    media_type="application/json; charset=utf-8",
                )

            if len(image_bytes) > 10 * 1024 * 1024:
                return JSONResponse(
                    status_code=413,
                    content={
                        "ok": False,
                        "message": "barcodeImage exceeds 10MB",
                    },
                    media_type="application/json; charset=utf-8",
                )

            try:
                barcode_text = extract_barcode_text(image_bytes, content_type)
            except Exception:
                traceback.print_exc()
                return JSONResponse(
                    status_code=500,
                    content={
                        "ok": False,
                        "message": "failed to extract barcode text",
                    },
                    media_type="application/json; charset=utf-8",
                )

        resolved_code = input_code or barcode_text
        if resolved_code is None:
            message = "barcodeImage could not be decoded" if barcodeImage is not None else "code or barcodeImage is required"
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "message": message,
                },
                media_type="application/json; charset=utf-8",
            )

        _log_api_step(
            request,
            "item_search_start",
            item_type=normalized_type,
            resolved_code=resolved_code,
            has_barcode_image=barcodeImage is not None,
        )

        if normalized_type == "ITEM":
            result = fetch_item_master_by_code(resolved_code)
        else:
            result = fetch_plu_master_by_code(resolved_code)

        _log_api_step(
            request,
            "item_search_done",
            item_type=normalized_type,
            resolved_code=resolved_code,
            found=bool(result),
        )

        return JSONResponse(
            content={
                "ok": True,
                "itemType": normalized_type,
                "inputCode": input_code,
                "barcodeText": barcode_text,
                "resolvedCode": resolved_code,
                "found": bool(result),
                "result": result,
            },
            media_type="application/json; charset=utf-8",
        )
    except Exception:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "message": "상/단품 검색 중 오류가 발생했습니다.",
            },
            media_type="application/json; charset=utf-8",
        )


# ===== TEAMS IMAGE CHAT POC =====
@app.post("/api/rag/image-chat")
async def rag_image_chat(
    source: str = Form(...),
    requestId: str = Form(...),
    userId: str = Form(...),
    userName: str = Form(""),
    question: str = Form(...),
    requestTime: str = Form(...),
    image: UploadFile = File(...),
):
    """Teams image and text multipart API with Azure vision analysis."""

    content_type = str(
        image.content_type or ""
    ).strip().lower()

    if not content_type.startswith("image/"):
        return JSONResponse(
            status_code=400,
            content={
                "restCd": "4000",
                "restMsg": "image file is required",
                "answer": "",
            },
        )

    image_bytes = await image.read()

    if not image_bytes:
        return JSONResponse(
            status_code=400,
            content={
                "restCd": "4001",
                "restMsg": "image file is empty",
                "answer": "",
            },
        )

    # PoC ?? ?? 10MB
    max_size = 10 * 1024 * 1024

    if len(image_bytes) > max_size:
        return JSONResponse(
            status_code=413,
            content={
                "restCd": "4002",
                "restMsg": "image file exceeds 10MB",
                "answer": "",
            },
        )

    original_name = Path(
        image.filename or "teams-image"
    ).name

    safe_file_name = re.sub(
        r"[^0-9A-Za-z?-?._-]",
        "_",
        original_name,
    )

    safe_request_id = re.sub(
        r"[^0-9A-Za-z_-]",
        "_",
        requestId,
    )[:80]

    save_directory = (
        Path(__file__).resolve().parent
        / "received_images"
    )

    save_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    save_path = (
        save_directory
        / f"{safe_request_id}_{safe_file_name}"
    )

    save_path.write_bytes(image_bytes)

    print(
        "[IMAGE CHAT RECEIVED]"
        f" source={source}"
        f" requestId={requestId}"
        f" userId={userId}"
        f" userName={userName}"
        f" question={question}"
        f" requestTime={requestTime}"
        f" fileName={original_name}"
        f" contentType={content_type}"
        f" fileSize={len(image_bytes)}"
        f" savePath={save_path}",
        flush=True,
    )

    try:
        vision_analysis = vision_answer(
            question=question,
            image_bytes=image_bytes,
            mime_type=content_type,
        )
    except Exception:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "restCd": "5001",
                "restMsg": "vision analysis failed",
                "answer": "이미지는 저장되었지만 Vision 분석 중 오류가 발생했습니다.",
                "requestId": requestId,
                "fileName": original_name,
                "contentType": content_type,
                "fileSize": len(image_bytes),
                "savedPath": str(save_path),
            },
            media_type="application/json; charset=utf-8",
        )

    try:
        rag_query = build_image_rag_query(question=question, vision_analysis=vision_analysis)
    except Exception:
        traceback.print_exc()
        rag_query = ""

    if not rag_query:
        rag_query = "\n".join(
            value for value in [question.strip(), vision_analysis.strip()] if value
        )

    try:
        rag_result = ask_rag(question=question, retrieval_question=rag_query)
        answer = rag_result["answer"]
    except Exception:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "restCd": "5002",
                "restMsg": "rag answer failed",
                "answer": "이미지 분석은 완료되었지만 FAQ 답변 생성 중 오류가 발생했습니다.",
                "requestId": requestId,
                "fileName": original_name,
                "contentType": content_type,
                "fileSize": len(image_bytes),
                "savedPath": str(save_path),
                "visionAnalysis": vision_analysis,
                "ragQuery": rag_query,
            },
            media_type="application/json; charset=utf-8",
        )

    history = _save_history(
        request=None,
        user_id=userId,
        qry=question,
        answer=answer,
        category=_get_reference_category(rag_result),
        filler3=_fit_log_value(f"received_images\\{save_path.name}", 50),
        reg_user=userId or userName or "system",
    )

    return JSONResponse(
        status_code=200,
        content={
            "restCd": "0000",
            "restMsg": "success",
            "answer": answer,
            "requestId": requestId,
            "fileName": original_name,
            "contentType": content_type,
            "fileSize": len(image_bytes),
            "savedPath": str(save_path),
            "visionAnalysis": vision_analysis,
            "ragQuery": rag_query,
            "logSaved": history["saved"],
            "logRegDt": history["regDt"],
            "logSeq": history["seq"],
        },
        media_type="application/json; charset=utf-8",
    )
# ===== TEAMS IMAGE CHAT POC ? =====

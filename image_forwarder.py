import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from botframework.connector.auth import (
    MicrosoftAppCredentials,
)
from botbuilder.core import TurnContext


KST = timezone(timedelta(hours=9))

MAX_IMAGE_SIZE = 10 * 1024 * 1024


def _infer_image_info(
    image_bytes: bytes,
    response_content_type: str,
) -> tuple[str, str]:
    """
    반환:
        MIME 타입, 파일 확장자
    """

    mime_type = (
        response_content_type
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if mime_type == "image/png":
        return "image/png", ".png"

    if mime_type in (
        "image/jpeg",
        "image/jpg",
    ):
        return "image/jpeg", ".jpg"

    if mime_type == "image/gif":
        return "image/gif", ".gif"

    if mime_type == "image/webp":
        return "image/webp", ".webp"

    if mime_type == "image/bmp":
        return "image/bmp", ".bmp"

    # 응답 헤더가 image/*가 아닌 경우 파일 시그니처 확인
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"

    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"

    if image_bytes.startswith(
        (b"GIF87a", b"GIF89a")
    ):
        return "image/gif", ".gif"

    if (
        len(image_bytes) >= 12
        and image_bytes[:4] == b"RIFF"
        and image_bytes[8:12] == b"WEBP"
    ):
        return "image/webp", ".webp"

    if image_bytes.startswith(b"BM"):
        return "image/bmp", ".bmp"

    raise ValueError(
        "다운로드한 데이터가 지원되는 이미지 형식이 아닙니다."
    )


async def _download_teams_image(
    content_url: str,
    app_id: str,
    app_password: str,
    tenant_id: str,
) -> tuple[bytes, str]:
    """
    Teams 인라인 이미지 URL에서 실제 이미지 바이트를 가져온다.
    """

    credentials = MicrosoftAppCredentials(
        app_id,
        app_password,
        channel_auth_tenant=(
            tenant_id or None
        ),
    )

    access_token = credentials.get_access_token()

    timeout = aiohttp.ClientTimeout(total=60)

    headers = {
        "Authorization": (
            f"Bearer {access_token}"
        ),
    }

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:
        async with session.get(
            content_url,
            headers=headers,
            allow_redirects=True,
        ) as response:
            # 일부 환경에서 URL이 직접 접근 가능한 경우를
            # 고려해 401/403이면 인증 없이 한 번 더 확인한다.
            if response.status in (401, 403):
                first_status = response.status
            else:
                first_status = None

                if response.status != 200:
                    response_text = (
                        await response.text()
                    )

                    raise RuntimeError(
                        "Teams 이미지 다운로드 실패: "
                        f"HTTP {response.status}, "
                        f"body={response_text[:300]}"
                    )

                content_length = (
                    response.content_length
                )

                if (
                    content_length is not None
                    and content_length
                    > MAX_IMAGE_SIZE
                ):
                    raise ValueError(
                        "이미지 크기가 10MB를 초과합니다."
                    )

                image_bytes = await response.read()

                response_content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                )

                print(
                    "[IMAGE DOWNLOAD]"
                    f" status={response.status}"
                    f" size={len(image_bytes)}"
                    f" content_type="
                    f"{response_content_type}",
                    flush=True,
                )

                return (
                    image_bytes,
                    response_content_type,
                )

        if first_status is not None:
            async with session.get(
                content_url,
                allow_redirects=True,
            ) as retry_response:
                if retry_response.status != 200:
                    retry_text = (
                        await retry_response.text()
                    )

                    raise RuntimeError(
                        "Teams 이미지 다운로드 실패: "
                        f"auth_http={first_status}, "
                        f"direct_http="
                        f"{retry_response.status}, "
                        f"body={retry_text[:300]}"
                    )

                image_bytes = (
                    await retry_response.read()
                )

                response_content_type = (
                    retry_response.headers.get(
                        "Content-Type",
                        "",
                    )
                )

                print(
                    "[IMAGE DOWNLOAD DIRECT]"
                    f" status={retry_response.status}"
                    f" size={len(image_bytes)}"
                    f" content_type="
                    f"{response_content_type}",
                    flush=True,
                )

                return (
                    image_bytes,
                    response_content_type,
                )


async def forward_teams_image(
    turn_context: TurnContext,
    *,
    app_id: str,
    app_password: str,
    tenant_id: str,
    target_url: str,
    request_id: str,
    user_id: str,
    user_name: str,
    question: str,
) -> dict[str, Any] | None:
    """
    Teams 이미지와 질문을 내부 multipart API로 전송한다.

    이미지 첨부가 없으면 None을 반환한다.
    """

    activity = turn_context.activity
    attachments = activity.attachments or []

    image_attachments = [
        attachment
        for attachment in attachments
        if (
            str(
                attachment.content_type or ""
            )
            .strip()
            .lower()
            .startswith("image/")
            and str(
                attachment.content_url or ""
            ).strip()
        )
    ]

    if not image_attachments:
        return None

    # PoC에서는 첫 번째 이미지만 처리
    image_attachment = image_attachments[0]

    if len(image_attachments) > 1:
        print(
            "[IMAGE NOTICE]"
            f" received={len(image_attachments)}"
            " processing=1",
            flush=True,
        )

    image_bytes, response_content_type = (
        await _download_teams_image(
            content_url=str(
                image_attachment.content_url
            ).strip(),
            app_id=app_id,
            app_password=app_password,
            tenant_id=tenant_id,
        )
    )

    if not image_bytes:
        raise ValueError(
            "다운로드된 이미지가 비어 있습니다."
        )

    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise ValueError(
            "이미지 크기가 10MB를 초과합니다."
        )

    mime_type, extension = _infer_image_info(
        image_bytes,
        response_content_type,
    )

    filename = (
        f"teams-{request_id}{extension}"
    )

    form = aiohttp.FormData()

    form.add_field(
        "source",
        "TEAMS",
    )

    form.add_field(
        "requestId",
        request_id,
    )

    form.add_field(
        "userId",
        user_id,
    )

    form.add_field(
        "userName",
        user_name,
    )

    form.add_field(
        "question",
        (
            question
            or "첨부된 POS 화면을 분석해주세요."
        ),
    )

    form.add_field(
        "requestTime",
        datetime.now(KST).isoformat(),
    )

    form.add_field(
        "image",
        image_bytes,
        filename=filename,
        content_type=mime_type,
    )

    timeout = aiohttp.ClientTimeout(total=180)

    print(
        "[IMAGE FORWARD START]"
        f" request_id={request_id}"
        f" target={target_url}"
        f" user_id={user_id}"
        f" question={question}"
        f" file_name={filename}"
        f" mime_type={mime_type}"
        f" size={len(image_bytes)}",
        flush=True,
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

    print(
        "[IMAGE FORWARD RESPONSE]"
        f" request_id={request_id}"
        f" status={status_code}"
        f" body={response_text[:1000]}",
        flush=True,
    )

    rest_cd = str(
        response_json.get("restCd", "")
    ).strip()

    success_value = response_json.get(
        "success"
    )

    is_success = (
        200 <= status_code < 300
        and (
            rest_cd in ("", "0000")
            or success_value is True
        )
    )

    answer = str(
        response_json.get(
            "answer",
            response_json.get(
                "message",
                "",
            ),
        )
        or ""
    ).strip()

    return {
        "ok": is_success,
        "status": status_code,
        "answer": answer,
        "rest_cd": rest_cd,
        "response_text": response_text,
        "response_json": response_json,
        "file_name": filename,
        "mime_type": mime_type,
        "file_size": len(image_bytes),
    }

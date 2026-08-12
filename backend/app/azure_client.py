import base64
import io
import re

from openai import AzureOpenAI
from app.config import settings


def get_client():
    return AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    client = get_client()

    res = client.embeddings.create(
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        input=texts
    )

    return [item.embedding for item in res.data]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def chat_answer(prompt: str) -> str:
    client = get_client()

    res = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": "너는 현대백화점 POS FAQ 기반 업무지원 챗봇이다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
        max_completion_tokens=1000
    )

    return res.choices[0].message.content


def extract_barcode_text(image_bytes: bytes, mime_type: str) -> str | None:
    if not image_bytes:
        raise ValueError("image_bytes is empty")

    local_text = _extract_barcode_text_locally(image_bytes)
    if local_text:
        return local_text

    if not settings.AZURE_OPENAI_CHAT_DEPLOYMENT:
        return None

    client = get_client()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:{mime_type};base64,{image_b64}"

    res = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 바코드 이미지를 읽는 도우미다. "
                    "이미지에서 읽은 바코드 또는 QR 값을 그대로 출력한다. "
                    "설명, 라벨, 따옴표, 마크다운 없이 값만 출력한다. "
                    "확실히 읽히지 않으면 NONE 만 출력한다."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "이미지의 바코드 값을 읽어서 값만 출력해줘.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                        },
                    },
                ],
            },
        ],
        temperature=0,
        max_completion_tokens=100,
    )

    text = (res.choices[0].message.content or "").strip()
    text = text.replace("```", "").strip()
    text = re.sub(r"\s+", "", text)
    if not text or text.upper() == "NONE":
        return None
    return text


def _extract_barcode_text_locally(image_bytes: bytes) -> str | None:
    try:
        from PIL import Image
        import zxingcpp
    except Exception:
        return None

    reader = getattr(zxingcpp, "read_barcodes", None)
    single_reader = getattr(zxingcpp, "read_barcode", None)
    if reader is None and single_reader is None:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()

            candidate_images = [image]
            if image.mode != "L":
                candidate_images.append(image.convert("L"))
            if image.mode != "RGB":
                candidate_images.append(image.convert("RGB"))

            for candidate in candidate_images:
                decoded = None
                if reader is not None:
                    decoded = reader(candidate)
                elif single_reader is not None:
                    decoded = single_reader(candidate)

                if decoded is None:
                    continue

                if hasattr(decoded, "text"):
                    text = (getattr(decoded, "text", "") or "").strip()
                    if text:
                        return text
                    continue

                for barcode in decoded:
                    text = (getattr(barcode, "text", "") or "").strip()
                    if text:
                        return text
    except Exception:
        return None

    return None


def vision_answer(question: str, image_bytes: bytes, mime_type: str) -> str:
    if not image_bytes:
        raise ValueError("image_bytes is empty")

    if not settings.AZURE_OPENAI_CHAT_DEPLOYMENT:
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is required")

    client = get_client()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:{mime_type};base64,{image_b64}"
    user_question = (question or "").strip()
    prompt = (
        "아래 사용자 입력에서 확인하려는 부분을 고려해 화면 정보를 추출해줘.\n"
        f"사용자 입력: {user_question}"
        if user_question
        else "FAQ 검색에 사용할 수 있도록 화면 정보를 추출해줘."
    )

    res = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 현대백화점 POS FAQ 검색을 위한 화면 정보 추출기다. "
                    "이미지에서 오류 분석과 FAQ 검색에 필요한 정보만 추출한다. "
                    "반드시 '화면:', '오류문구:', '오류코드:', '상태:' 네 줄 형식으로만 출력한다. "
                    "서론, 결론, 인사, 설명 문단, 마크다운, 글머리표를 출력하지 않는다. "
                    "'다음과 같이 화면 정보를 추출할 수 있습니다' 같은 안내 문구를 출력하지 않는다. "
                    "오류 문구와 오류 코드는 검색에 사용되므로 이미지에 보이는 값을 원문 그대로 보존한다. "
                    "값이 보이지 않는 필드는 '없음'으로 출력한다. "
                    "로고, 브랜드, 사용자명, 시각, 금액 등은 오류 원인과 직접 관련되거나 사용자가 요청한 경우가 아니면 제외한다. "
                    "해결 방법, 대처 순서, 재시도 방법은 만들지 않고 이미지에서 확실히 확인되는 사실만 출력한다."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                        },
                    },
                ],
            },
        ],
        temperature=0,
        max_completion_tokens=500,
    )

    return res.choices[0].message.content or ""

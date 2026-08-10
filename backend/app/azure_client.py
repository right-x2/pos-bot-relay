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


def build_image_rag_query(question: str, vision_analysis: str) -> str:
    client = get_client()
    user_question = (question or "").strip()
    image_summary = (vision_analysis or "").strip()

    if not user_question and not image_summary:
        return ""

    res = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 POS FAQ 벡터 검색용 질의를 만드는 도우미다. "
                    "사용자 질문과 이미지 분석 결과를 바탕으로 FAQ 검색에 가장 잘 걸릴 한국어 질의 1개만 만들어라. "
                    "메뉴명, 오류문구, 기능명, 화면명, 키워드를 보존하고 추측은 하지 마라. "
                    "설명 없이 검색 질의 문장만 출력해라."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"[사용자 질문]\n{user_question}\n\n"
                    f"[이미지 분석 결과]\n{image_summary}\n\n"
                    "[출력 규칙]\n"
                    "- FAQ 검색에 바로 넣을 질의 1개만 작성\n"
                    "- 불필요한 수식어 제거\n"
                    "- 확인된 오류문구, 버튼명, 메뉴명, 증상은 최대한 유지"
                ),
            },
        ],
        temperature=0,
        max_completion_tokens=300,
    )

    return (res.choices[0].message.content or "").strip()


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
    prompt = (question or "").strip() or "이미지를 분석해서 핵심 내용을 한국어로 설명해줘."

    res = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 현대백화점 POS 업무지원 챗봇이다. "
                    "사용자가 올린 이미지를 보고 질문에 맞게 한국어로 간결하고 정확하게 답변한다. "
                    "이미지에서 확실히 확인되지 않는 내용은 추측하지 말고 추가 확인이 필요하다고 안내한다."
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
        max_completion_tokens=1000,
    )

    return res.choices[0].message.content or ""

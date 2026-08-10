import os
import hashlib
import time

os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["CHROMADB_TELEMETRY"] = "False"

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.azure_client import embed_text, chat_answer
from app.db import increment_faq_counts


def get_collection(create: bool = False):
    chroma_client = chromadb.PersistentClient(
        path=settings.CHROMA_DIR,
        settings=ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=True,
        )
    )

    if create:
        return chroma_client.get_or_create_collection(settings.CHROMA_COLLECTION)

    return chroma_client.get_collection(settings.CHROMA_COLLECTION)


def _safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").strip()
        except UnicodeDecodeError:
            return value.decode("cp949", errors="replace").strip()
    return str(value).strip()


def _timing_enabled() -> bool:
    value = os.getenv("RAG_TIMING_LOG", "")
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _log_timing(step: str, elapsed_s: float, **kwargs) -> None:
    elapsed_ms = elapsed_s * 1000.0
    if kwargs:
        extras = " ".join(f"{key}={value}" for key, value in kwargs.items())
        print(f"[rag-timing] {step} {elapsed_ms:.1f}ms {extras}")
    else:
        print(f"[rag-timing] {step} {elapsed_ms:.1f}ms")


def _get_record_value(record: dict, key: str):
    if key in record:
        return record.get(key)
    key_lower = key.lower()
    for k, v in record.items():
        if str(k).lower() == key_lower:
            return v
    return None


def _normalize_seq(value) -> str:
    if value is None:
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def _make_doc_id(reg_dt: str, seq: str) -> str:
    return f"POSFAQ_{reg_dt}_{seq}"


def _make_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_faq_content(record: dict) -> str:
    reg_dt = _safe_str(_get_record_value(record, "REG_DT"))
    title = _safe_str(_get_record_value(record, "TITLE"))
    answer = _safe_str(_get_record_value(record, "ANSWER"))
    category = _safe_str(_get_record_value(record, "CATEGORY"))
    keywords = _safe_str(_get_record_value(record, "KEYWORDS"))

    return f"""
[카테고리]
{category}

[제목]
{title}

[키워드]
{keywords}

[등록일]
{reg_dt}

[내용]
{answer}
""".strip()


def upsert_faq_vector(record: dict) -> dict:
    if not record:
        raise ValueError("FAQ record is empty")

    reg_dt = _safe_str(_get_record_value(record, "REG_DT"))
    seq = _normalize_seq(_get_record_value(record, "SEQ"))
    title = _safe_str(_get_record_value(record, "TITLE"))
    answer = _safe_str(_get_record_value(record, "ANSWER"))
    category = _safe_str(_get_record_value(record, "CATEGORY"))
    keywords = _safe_str(_get_record_value(record, "KEYWORDS"))

    if not reg_dt or not seq:
        raise ValueError("REG_DT or SEQ is missing")

    timing_on = _timing_enabled()
    t_start = time.perf_counter()
    t_mark = t_start

    doc_id = _make_doc_id(reg_dt, seq)
    content = _build_faq_content(record)
    if timing_on:
        t_now = time.perf_counter()
        _log_timing("build_content", t_now - t_mark, reg_dt=reg_dt, seq=seq)
        t_mark = t_now

    embedding = embed_text(content)
    if timing_on:
        t_now = time.perf_counter()
        _log_timing("embed_text", t_now - t_mark, doc_id=doc_id)
        t_mark = t_now

    metadata = {
        "source": "POS_FAQ_MST",
        "doc_id": doc_id,
        "reg_dt": reg_dt,
        "seq": seq,
        "title": title,
        "category": category,
        "keywords": keywords,
        "content_hash": _make_content_hash(content),
    }

    collection = get_collection(create=True)
    if timing_on:
        t_now = time.perf_counter()
        _log_timing("get_collection", t_now - t_mark, collection=settings.CHROMA_COLLECTION)
        t_mark = t_now

    collection.upsert(
        ids=[doc_id],
        documents=[content],
        embeddings=[embedding],
        metadatas=[metadata],
    )
    if timing_on:
        t_now = time.perf_counter()
        _log_timing("upsert", t_now - t_mark, doc_id=doc_id)
        t_mark = t_now
        _log_timing("total", t_mark - t_start, doc_id=doc_id)

    return {
        "doc_id": doc_id,
        "reg_dt": reg_dt,
        "seq": seq,
        "content_hash": metadata["content_hash"],
    }


def delete_faq_vector_by_key(reg_dt: str, seq) -> dict:
    reg_dt = _safe_str(reg_dt)
    seq = _normalize_seq(seq)

    if not reg_dt or not seq:
        raise ValueError("REG_DT or SEQ is missing")

    doc_id = _make_doc_id(reg_dt, seq)
    collection = get_collection(create=True)

    found = False
    try:
        existing = collection.get(ids=[doc_id], include=["ids"])
        found = bool(existing.get("ids"))
    except Exception:
        found = False

    collection.delete(ids=[doc_id])

    return {
        "doc_id": doc_id,
        "reg_dt": reg_dt,
        "seq": seq,
        "found": found,
    }


def search_faq(question: str, top_k: int = 4) -> list[dict]:
    collection = get_collection()

    q_emb = embed_text(question)

    result = collection.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    refs = []

    for doc, meta, distance in zip(docs, metas, distances):
        refs.append({
            "content": doc,
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "keywords": meta.get("keywords", ""),
            "seq": meta.get("seq", ""),
            "reg_dt": meta.get("reg_dt", ""),
            "distance": float(distance),
        })

    return refs


def build_prompt(question: str, refs: list[dict]) -> str:
    context_lines = []

    for i, r in enumerate(refs, start=1):
        context_lines.append(f"""
[FAQ {i}]
제목: {r.get("title", "")}
카테고리: {r.get("category", "")}
키워드: {r.get("keywords", "")}
내용:
{r.get("content", "")}
거리값: {r.get("distance", "")}
""".strip())

    context = "\n\n---\n\n".join(context_lines)

    return f"""
너는 현대백화점 POS FAQ 기반 업무지원 챗봇이다.

규칙:
1. 반드시 아래 FAQ 내용만 근거로 답변한다.
2. FAQ에 없는 내용은 추측하지 않는다.
3. 참고 FAQ 내용과 사용자 질문의 관련성이 낮으면, FAQ 내용을 억지로 연결하지 말고 관련 답변을 찾을 수 없다고 안내한다.
4. 점포 직원이 바로 따라 할 수 있게 단계별로 답변한다. (단계별 작성시 한줄씩 밑에 여백도 추가해라)
5. 단계별 답변 구조가 아닌 경우 억지로 단계별로 설명하지 않고 흐름대로 설명한다.
6. 각 순서 및 단계 표시는 1.,2.,3. 이런 방식 또는 1단계, 2단계, 3단계 방식으로 표시한다
7. 답변은 한국어로 간결하게 작성한다.
8. 답변이 불확실한 경우 단정적으로 표현하지 않고, 추가 확인이 필요하다고 안내한다.
9. 참고한 FAQ는 밑에 기재한다.

[사용자 질문]
{question}

[참고 FAQ]
{context}

[답변]
""".strip()


def build_rank_weights(n: int) -> list[float]:
    base = [1.0, 0.7, 0.4, 0.2]
    if n <= len(base):
        return base[:n]
    return base + [base[-1]] * (n - len(base))

MAX_COUNT_DISTANCE = 0.5


def ask_rag(question: str, top_k: int = 4, retrieval_question: str | None = None) -> dict:
    search_question = (retrieval_question or question).strip()
    refs = search_faq(search_question, top_k=top_k)

    if not refs:
        return {
            "answer": "관련 FAQ를 찾지 못했습니다.",
            "references": []
        }

    try:
        weights = build_rank_weights(len(refs))
        items = []
        for r, w in zip(refs, weights):
            reg_dt = str(r.get("reg_dt", "")).strip()
            val = r.get("seq", "")
            seq = str(int(float(val))) if val not in (None, "") else ""
            distance = float(r.get("distance", 999))
            print(distance)
            if reg_dt and seq and distance <= MAX_COUNT_DISTANCE:
                distance_weight = max(0.0, 1.0 - distance)
                items.append((reg_dt, seq, float(w) * distance_weight))
        if items:
            increment_faq_counts(items)
    except Exception as e:
        print(f"[warn] failed to increment faq counts: {e}")

    prompt = build_prompt(question, refs)
    answer = chat_answer(prompt)

    return {
        "answer": answer,
        "references": refs
    }

import hashlib
import pandas as pd
from langchain_core.documents import Document

def safe_str(v) -> str:
    return "" if pd.isna(v) else str(v).strip()

def make_doc_id(reg_dt: str, seq: str) -> str:
    return f"POSFAQ_{reg_dt}_{seq}"

def make_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def row_to_document(row) -> Document:
    reg_dt = safe_str(row.get("REG_DT"))
    seq = safe_str(row.get("SEQ"))
    title = safe_str(row.get("TITLE"))
    answer = safe_str(row.get("ANSWER"))
    category = safe_str(row.get("CATEGORY"))
    keywords = safe_str(row.get("KEYWORDS"))

    content = f"""
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

    metadata = {
        "source": "POS_FAQ_MST",
        "doc_id": make_doc_id(reg_dt, seq),
        "reg_dt": reg_dt,
        "seq": seq,
        "title": title,
        "category": category,
        "keywords": keywords,
        "content_hash": make_content_hash(content),
    }

    return Document(page_content=content, metadata=metadata)

def df_to_documents(df) -> list[Document]:
    return [row_to_document(row) for _, row in df.iterrows()]
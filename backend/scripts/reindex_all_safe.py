import argparse
import sys
from pathlib import Path

import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.db import load_pos_faq_df
from app.rag import upsert_faq_vector


def _to_record(row) -> dict:
    record = {}
    for key, value in row.items():
        record[key] = None if pd.isna(value) else value
    return record


def _validate_clean_target(allow_existing: bool) -> Path:
    target = Path(settings.CHROMA_DIR).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not allow_existing:
        raise RuntimeError(
            f"CHROMA_DIR is not empty: {target}. "
            "Use a new path for recovery, or pass --allow-existing intentionally."
        )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reindex active FAQs without issuing Chroma delete operations."
    )
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow upserting into a non-empty CHROMA_DIR.",
    )
    args = parser.parse_args()

    target = _validate_clean_target(args.allow_existing)
    print(f"CHROMA_DIR: {target}")
    print("[1/3] 승인 FAQ 조회")
    df = load_pos_faq_df()
    print(f"FAQ count: {len(df)}")

    print("[2/3] 삭제 없이 upsert")
    for index, (_, row) in enumerate(df.iterrows(), start=1):
        result = upsert_faq_vector(_to_record(row))
        print(f"{index}/{len(df)} {result['doc_id']}")

    print("[3/3] 완료")
    print(f"Reindexed {len(df)} FAQs into {target}")


if __name__ == "__main__":
    main()

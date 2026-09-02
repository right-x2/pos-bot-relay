# Chroma Windows HNSW 장애 진단 및 복구

## 확인된 증상

첨부 로그는 `collection.upsert()`가 Chroma 0.5.23의 네이티브 HNSW
`_apply_batch`를 실행하는 동안 Windows `access violation`으로 프로세스가
종료된 기록이다. Python 예외가 아니므로 `try/except`로 복구할 수 없다.

로그의 호출 경로는 다음과 같다.

```text
register_post_request
  -> _complete_faq_approval
  -> upsert_faq_vector
  -> collection.upsert
  -> local_persistent_hnsw._apply_batch
  -> Windows fatal exception: access violation
```

## 원인 판단

- ZIP의 `app/rag.py`는 기존 안전 버전과 기능상 동일하다. 최근 FAQ/Confluence
  기능이 HNSW 구현을 직접 변경한 것은 아니다.
- ZIP에 포함된 `scripts/reindex_faq.py`는 현재 `CHROMA_DIR`의 컬렉션을
  `delete_collection()`한 뒤 같은 위치에 다시 생성한다. API가 열려 있거나
  기존 HNSW 상태가 불완전한 상황에서 이 스크립트를 실행하면 안전하지 않다.
- 새 Confluence 발행 API와 기존 자동 승인 API는 모두 `upsert_faq_vector()`를
  호출한다. FastAPI threadpool에서 두 쓰기 또는 검색과 쓰기가 겹치지 않도록
  Chroma 연산을 직렬화해야 한다.
- 이미 access violation이 발생한 `CHROMA_DIR`은 계속 재사용하지 않는다. 다음
  upsert에서 같은 네이티브 충돌이 반복될 수 있다.

## 복구 절차

아래 명령은 `D:\rag-master\poschat\backend`를 기준으로 한다.

1. Uvicorn API와 Confluence 동기화 작업을 모두 중지한다.
2. 현재 `.env`의 경로를 확인한다. 장애 당시 경로는 `./data/chroma_0811`이었다.
3. 손상 의심 디렉터리는 삭제하지 말고 이름을 바꿔 보관한다.

```powershell
Rename-Item .\data\chroma_0811 chroma_0811_corrupt_20260902
```

4. `.env`를 아직 사용하지 않은 새 경로로 변경한다.

```dotenv
CHROMA_DIR=./data/chroma_20260902
```

5. 동일한 Python 3.11 가상환경에서 런타임과 임시 Chroma 쓰기를 검증한다.

```powershell
cd D:\rag-master\poschat\backend
.\.venv-new\Scripts\Activate.ps1
python .\scripts\verify_runtime.py --chroma-smoke
```

6. API가 중지된 상태에서 안전 재색인을 실행한다.

```powershell
python .\scripts\reindex_all_safe.py
```

7. 출력 건수와 SQL의 승인 FAQ 건수가 일치하는지 확인한 뒤 API를 한 개 worker로
   기동한다. 검색을 먼저 확인하고 FAQ 한 건을 승인해 upsert까지 확인한다.

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

## 금지 사항

- 손상된 `chroma_0811`에 `--allow-existing`을 사용하지 않는다.
- ZIP의 `scripts/reindex_faq.py`를 운영에서 실행하지 않는다.
- API 실행 중 별도 Python 프로세스로 같은 `CHROMA_DIR`을 재색인하지 않는다.
- 손상 디렉터리의 일부 HNSW 파일만 골라 삭제하거나 새 디렉터리에 복사하지 않는다.
- 원인 확인 없이 Chroma 관련 패키지 버전을 개별 업그레이드하지 않는다.

운영 조합은 `chromadb==0.5.23`, `chroma-hnswlib==0.7.6`,
`numpy==1.26.4`로 고정되어 있다. Windows Server 자체에서 단순 upsert도 네이티브
access violation이 날 수 있으므로, 임시 디렉터리 smoke test가 실패하면 데이터
복구보다 먼저 런타임 또는 Chroma 실행 플랫폼을 변경해야 한다.

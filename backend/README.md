# POS RAG backend

FastAPI, SQL Server, Azure OpenAI와 ChromaDB를 사용하는 POS FAQ/RAG 백엔드입니다.

## 기준 환경

- Windows Server 2019 계열 (`10.0.17763`)
- CPython 3.11 64비트
- Chroma 핵심 조합은 `requirements/constraints-chroma.txt` 참고
- `requirements/requirements-lock-full.txt`는 재임베딩까지 성공한 전체 환경의 freeze

전체 lock에는 개발 도구와 실험용 패키지도 포함되어 있으므로 운영 환경에 그대로 전부 설치하지 않습니다. 운영 설치는 직접 의존성 목록과 전체 lock을 constraints로 함께 사용합니다.

## 외부망에서 wheelhouse 만들기

인터넷이 되는 Windows PC에서 Python 3.11 64비트를 사용합니다.

```powershell
cd backend
py -3.11 -m venv .venv-wheel
.\.venv-wheel\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip download `
  --dest wheelhouse `
  --requirement requirements\requirements-runtime.in `
  --constraint requirements\requirements-lock-full.txt
```

`backend` 폴더와 생성된 `wheelhouse`를 내부망으로 전달합니다. `wheelhouse`는 Git에 올리지 않습니다.

## 내부망 설치

기존 정상 환경을 덮어쓰지 말고 새 가상환경을 만듭니다.

```powershell
cd D:\rag-master\poschat\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install `
  --no-index `
  --find-links .\wheelhouse `
  --requirement .\requirements\requirements-runtime.in `
  --constraint .\requirements\requirements-lock-full.txt
python .\scripts\verify_runtime.py --chroma-smoke
```

`pyodbc`와 별도로 Microsoft ODBC Driver 17 for SQL Server가 서버에 설치되어 있어야 합니다.

## 설정

`.env.example`을 `.env`로 복사한 뒤 실제 값을 내부 서버에서만 입력합니다. `.env`는 Git에 포함되지 않습니다.

Chroma 경로는 새 배포 때 임의로 변경하지 않습니다. 상대 경로를 사용한다면 반드시 `backend` 디렉터리에서 서버를 실행해야 같은 저장소를 엽니다.

FAQ 삭제는 Windows HNSW 네이티브 충돌을 피하기 위해 물리 삭제 대신 별도
SQLite tombstone으로 처리합니다. 기본 파일은 `CHROMA_DIR` 옆의
`<CHROMA_DIR 이름>.tombstones.sqlite3`이며, 필요하면
`CHROMA_TOMBSTONE_DB` 환경변수로 경로를 고정할 수 있습니다.

`Delete of nonexisting embedding ID` 다음 `Windows fatal exception: access violation`이
발생한 Chroma 저장소는 실행을 중지한 상태에서 기존 디렉터리를 백업하고 새
`CHROMA_DIR`에 승인 FAQ 전체를 재임베딩해야 합니다. 손상된 저장소를 그대로
재사용하면 남아 있는 DELETE 작업이 다음 upsert 때 다시 실행될 수 있습니다.

복구 재임베딩은 Chroma 물리 삭제를 호출하지 않는 전용 스크립트를 사용합니다.

```powershell
# .env의 CHROMA_DIR을 사용하지 않은 새 경로로 먼저 변경합니다.
# 예: CHROMA_DIR=./data/chroma_v3
python .\scripts\reindex_all_safe.py
```

대상 디렉터리가 비어 있지 않으면 스크립트가 중단됩니다. 복구 시에는
`--allow-existing`을 사용하지 않습니다.

## 실행

```powershell
cd D:\rag-master\poschat\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 내부망 Git 갱신

실행 중인 API를 먼저 종료하고 갱신합니다. Git pull은 Python 가상환경이나 Chroma 데이터를 변경하지 않습니다.

```powershell
cd D:\rag-master\poschat
git status
git pull --ff-only origin main
cd backend
.\.venv\Scripts\Activate.ps1
python .\scripts\verify_runtime.py
```

코드 변경으로 패키지 목록이 달라졌다면 외부망에서 wheelhouse를 다시 만든 후 내부망에 반입해야 합니다.

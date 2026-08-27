# 백엔드 소스 동기화 기록 (2026-08-27)

내부 서버에서 반출한 백엔드 ZIP과 PowerShell 중계 서버를 현재 저장소와 비교한 기록입니다.

## 입력 파일

- `pip-check.zip`
  - SHA-256: `388e5c67f79a634085361741826a7f9570c79156d5d12d13aefe73ff26dc59e6`
- `rag_relay_server.ps1`
  - SHA-256: `03b8a2b9a7772a3593b125f1efee993a19a81e5a90a2fed3aa89d1e1da85659c`

## 비교 결과

- PowerShell 중계 서버는 줄바꿈 형식(CRLF/LF)을 제외하면 저장소 파일과 동일합니다.
- 백엔드 `app/*.py`는 대부분 줄바꿈 형식을 제외하면 저장소 파일과 동일합니다.
- `command_router.py`는 저장소 버전이 POS 단건, 쉼표 목록, 정방향 범위를 모두 지원합니다. 반출본은 단건만 지원하므로 기능 회귀를 막기 위해 저장소 버전을 유지했습니다.
- 저장소의 테스트, API 문서, 안전 재색인 스크립트와 tombstone 방식 벡터 삭제 로직은 반출본보다 확장된 구성입니다.

## 커밋 제외 항목

- 실제 접속정보가 포함될 수 있는 `.env`
- `__pycache__`, `*.pyc` 등 실행 캐시
- 빈 노트북과 중첩 ZIP 같은 실행에 불필요한 산출물
- 로컬 절대경로(`D:/rag-master/...`)가 포함된 전체 환경 freeze
- 기존 컬렉션을 물리 삭제하는 구형 재색인 스크립트

운영 설정은 `backend/.env.example`을 기준으로 내부 서버에서만 입력하며, 재색인은 `backend/scripts/reindex_all_safe.py`를 사용합니다.

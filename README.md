# POS Bot monorepo

Microsoft Teams POS 챗봇과 RAG 백엔드를 한 저장소에서 관리합니다.

## 구성

- 루트 Python/PowerShell 파일: Teams 봇 및 내부망 릴레이
- `backend/app`: FastAPI RAG 백엔드
- `backend/requirements`: 운영 환경 의존성 및 정상 환경 전체 lock
- `backend/scripts`: 내부망 배포 전 환경 검증 도구
- `backend/docs`: 백엔드 API 문서

백엔드 설치와 내부망 반영 절차는 [`backend/README.md`](backend/README.md)를 참고합니다.

`.env`, 가상환경, Chroma 데이터, 업로드 파일과 wheelhouse는 Git에 포함하지 않습니다.

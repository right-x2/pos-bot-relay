# POSChat API 문서

이 문서는 현재 프로젝트의 수신 API를 코드 기준으로 정리한 문서다.
기준 범위는 `main.py`에 정의된 FastAPI 라우트다.

## 1. API 목록

| Method | Path | 용도 |
| --- | --- | --- |
| POST | `/api/rag/chat` | 챗봇 메인 진입점. 일반 질문은 FAQ RAG로 처리하고, 일부 자연어 명령은 직접 실행 |
| POST | `/api/posts/request` | 신규 FAQ 게시 요청 등록 |
| POST | `/api/admin/posts/approve` | 외부 승인 확인 후 벡터DB 및 Teams 알림 반영 |
| POST | `/api/admin/posts/approve-by-key` | `REG_DT + SEQ` 기준 외부 승인 확인 후 벡터DB 및 Teams 알림 반영 |
| POST | `/api/admin/posts/approve-with-content` | 전달받은 FAQ 본문으로 DB 재조회 없이 벡터DB 및 Teams 알림 반영 |
| POST | `/api/admin/posts/upsert-embedding-by-key` | `REG_DT + SEQ` 기준 FAQ 임베딩 upsert |
| POST | `/api/admin/posts/delete-embedding-by-key` | `REG_DT + SEQ` 기준 FAQ 임베딩 삭제 |
| POST | `/api/faqs/top-questions` | 카테고리별 `FILLER1` 가중치 상위 FAQ 질문 조회 |
| POST | `/api/items/search` | 상품·단품 조회 및 사용/행사 상태 판정 |
| GET | `/api/health` | 헬스체크 |
| POST | `/tools/create_pos_master` | POS 마스터 상태 갱신용 도구 API |
| POST | `/tools/pattern_lookup` | POS 패턴 그룹/상세 조회용 도구 API |
| POST | `/tools/pattern_update` | POS 패턴 상세값 수정용 도구 API |
| POST | `/tools/refund_status` | 원거래 키 기준 반품 진행 상태 및 진행 POS 조회 |
| POST | `/tools/refund_cancel` | 원거래 키 기준 반품 진행 데이터 삭제 |

## 2. 공통 사항

- 요청/응답 포맷은 JSON 기준이다.
- 응답 `Content-Type`은 `application/json; charset=utf-8`이다.
- `/api/posts/*`, `/api/admin/posts/*` 계열은 아래 형식을 사용한다.

```json
{
  "success": true,
  "requestId": 123,
  "message": "처리 메시지",
  "errorCode": null
}
```

- `/api/posts/*`, `/api/admin/posts/*` 계열 오류 응답은 아래 형식을 사용한다.

```json
{
  "success": false,
  "requestId": null,
  "message": "오류 메시지",
  "errorCode": "ERROR_CODE"
}
```

- `/api/rag/chat`, `/api/health` 계열은 아래 형식을 사용한다.

```json
{
  "resCd": "0000",
  "resMsg": "success",
  "answer": "응답 메시지"
}
```

- `/tools/*` 계열은 `ok` 필드를 중심으로 응답한다.

### 상·단품 판정 규칙

`/api/items/search`가 조회 결과를 찾으면 `diagnosis`에 아래 판정 근거를 함께 반환한다.

- `사용여부`: `USE_YN`이 `1/Y/YES/TRUE/T`이면 사용 가능, `0/N/NO/FALSE/F`이면 사용 불가로 판정한다. 그 밖의 값과 미설정 값은 확인 필요로 판정한다.
- `행사`: 단품의 가격 행사(`PRC_EVT_*`), N+N 행사(`NN_EVT_*`), 대상 행사(`TRGT_EVT_*_1`~`5`)를 각각 확인한다. 행사 관련 값이 하나라도 있으면 설정된 행사로 본다.
- `사용기간`: 행사별 시작일과 종료일에 오늘 날짜가 포함되면 적용 가능, 시작 전이면 예정, 종료 후이면 종료로 판정한다. 날짜가 없거나 시작일이 종료일보다 늦거나 날짜 형식을 해석할 수 없으면 확인 필요로 판정한다.
- 상품 마스터에는 행사 기간 컬럼이 없으므로 상품 조회에서는 행사와 사용기간을 판정하지 않고 연결된 단품 조회가 필요하다고 안내한다.
- `USE_YN`이 사용 불가이면 행사 상태와 관계없이 최종 판정은 사용 불가다. 알 수 없는 `USE_YN` 또는 잘못된 행사 기간이 있으면 최종 판정은 확인 필요다.
- 상품 조회 결과에는 직원(`EMP_ENURI_RT`), 그룹사(`GRP_CMP_ENURI_RT`), 일반회원(`GNRL_MEM_ENURI_RT`), 자스민블랙(`JSMN_BLK_ENURI_RT`), 백화점 임직원(`UCARD_PNT_ACM_RT`), 협력사(`OUTLET_PNT_ACM_RT`) 에누리율을 포함한다. Teams 카드에서는 DB 비율값에 100을 곱해 표시한다(예: `0.1` → `10%`).

### 반품 상태조회 및 취소

`/tools/refund_status`와 `/tools/refund_cancel`은 같은 원거래 키를 사용한다.

요청 예시:

```json
{
  "storeCode": "210",
  "saleDate": "20260812",
  "posNo": "1111",
  "dealNo": "000123"
}
```

- 상태조회는 `HDTRAN..TR_POS_TRANCALL_RFND`에서 `STORE_CD`, `SALE_DT`, `POS_NO`, `DEAL_NO`가 모두 일치하는 데이터를 찾는다.
- 조회되면 `SET_STORE_CD`, `SET_SALE_DT`, `SET_POS_NO`를 현재 반품 진행 위치로 반환한다.
- 취소는 동일한 네 개 조건으로 반품 진행 데이터를 삭제하며, 삭제 대상이 없으면 `deleted`가 `0`이다.

상태조회 성공 응답 예시:

```json
{
  "ok": true,
  "found": true,
  "message": "반품 진행중입니다.",
  "originalTransaction": {
    "storeCode": "210",
    "saleDate": "20260812",
    "posNo": "1111",
    "dealNo": "000123"
  },
  "refundProgress": {
    "storeCode": "220",
    "saleDate": "20260812",
    "posNo": "2001"
  }
}
```

취소 성공 응답 예시:

```json
{
  "ok": true,
  "deleted": 1,
  "message": "반품 진행이 취소되었습니다."
}
```

## 3. 상세 명세

### 3.1 POST `/api/rag/chat`

챗봇 메인 진입점이다.

- 일반 질문은 FAQ 임베딩 검색 후 RAG 답변을 생성한다.
- 일부 자연어 명령은 FAQ 검색 없이 직접 처리한다.

요청 예시:

```json
{
  "userId": "u001",
  "question": "영수증 재발행은 어떻게 하나요?"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `userId` | string | N | 사용자 식별자 |
| `question` | string | Y | 사용자 질문. 공백만 입력하면 오류 |

내부 처리 분기:

- POS 마스터 생성 명령 예시: `1011 POS 마스터 생성`, `POS 마스터 생성 1011`
- 패턴 조회 명령 예시: `POS 1011 패턴 조회`, `POS 1011 패턴명 카드결제 조회`
- 패턴 수정 명령 예시: `POS 5556 1001 패턴 1로 수정`
- 그 외 질문은 FAQ RAG 검색 후 답변 생성

성공 응답 예시:

```json
{
  "resCd": "0000",
  "resMsg": "success",
  "answer": "관련 FAQ를 기반으로 생성된 답변"
}
```

오류/안내 예시:

```json
{
  "resCd": "9999",
  "resMsg": "question is empty",
  "answer": "질문을 입력해주세요."
}
```

메모:

- 패턴 조회/수정에서 POS 번호나 패턴값이 부족한 경우에도 HTTP 오류 대신 안내 문구를 반환한다.
- 현재 응답에는 참고 FAQ 목록이 포함되지 않고 `answer`만 반환한다.

### 3.2 POST `/api/posts/request`

신규 FAQ 게시 요청을 등록한다. 요청자가 권한 그룹 `8000`에 포함되면 즉시 승인하고,
벡터DB 반영 후 권한 그룹 `8001`의 모든 사용자에게 Teams 알림을 등록한다.
그 외 사용자는 승인대기 상태로 등록한다.

요청 예시:

```json
{
  "source": "teams",
  "teamsUserId": "honggildong",
  "teamsUserName": "홍길동",
  "category": "1",
  "question": "영수증 재발행은 어떻게 하나요?",
  "answer": "영수증 재발행 메뉴에서 승인번호를 조회한 뒤 재출력합니다.",
  "keywords": "영수증,재발행,승인번호",
  "requestTime": "2026-07-24T10:15:00+09:00"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `source` | string | Y | 요청 출처 |
| `teamsUserId` | string | Y | 요청자 ID |
| `teamsUserName` | string | Y | 요청자 이름 |
| `category` | string | Y | FAQ 카테고리 코드: `1` POS공통, `2` PPOS, `3` APOS, `4` 서버, `5` HBO, `6` 키오스크 |
| `question` | string | Y | FAQ 질문 |
| `answer` | string | Y | FAQ 답변 |
| `keywords` | string | N | 검색 키워드 |
| `requestTime` | datetime | Y | 타임존 오프셋 포함 필수 |

성공 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "게시글이 승인대기 상태로 등록되었습니다.",
  "errorCode": null
}
```

권한 그룹 `8000` 사용자의 자동 승인 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "게시글이 즉시 승인되어 벡터에 반영되었고 알림 3건이 등록되었습니다.",
  "errorCode": null
}
```

대표 오류 코드:

- `VALIDATION_ERROR`
- `INVALID_REQUEST_TIME`
- `REGISTER_FAILED`

### 3.3 POST `/api/admin/posts/approve`

외부 시스템에서 승인 완료 API를 호출하면 FAQ를 조회해 벡터DB에 반영한 뒤,
권한 그룹 `8001`의 모든 사용자에게 Teams 알림을 등록한다.

요청 예시:

```json
{
  "requestId": 123,
  "adminUserName": "관리자홍길동"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `requestId` | int | Y | 승인 대상 식별값 |
| `adminUserName` | string | Y | 승인자 이름 |

성공 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "게시글이 승인되어 벡터에 반영되었고 알림 3건이 등록되었습니다.",
  "errorCode": null
}
```

대표 오류 코드:

- `VALIDATION_ERROR`
- `NOT_FOUND`
- `APPROVE_FAILED`

주의:

- 코드상 `requestId`는 별도 요청 테이블 ID가 아니라 FAQ의 `SEQ` 기준으로 승인 처리된다.
- 이 API는 `USE_YN`을 조회하거나 변경하지 않으며, 외부 시스템의 승인 완료 호출을 신뢰한다.
- 승인 확인과 벡터 반영이 끝나면 권한 그룹 `8001` 사용자별로 `TASK_GBCD = '04'` 알림을 등록한다.

### 3.4 POST `/api/admin/posts/approve-by-key`

`REG_DT + SEQ` 기준으로 FAQ를 조회해 벡터DB에 반영한 뒤,
권한 그룹 `8001`의 모든 사용자에게 Teams 알림을 등록한다.

요청 예시:

```json
{
  "regDt": "20240101",
  "seq": 123,
  "adminUserName": "관리자홍길동"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `regDt` | string | Y | 8자리 날짜 문자열 |
| `seq` | int | Y | FAQ 순번. 0보다 커야 함 |
| `adminUserName` | string | N | 승인자 이름. 없으면 `system` 사용 |

`adminUserName`은 기존 호출 형식 호환을 위해 유지하며, 백엔드에서는 승인 상태를 변경하지 않는다.

성공 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "게시글이 승인되어 벡터에 반영되었고 알림 3건이 등록되었습니다.",
  "errorCode": null
}
```

대표 오류 코드:

- `VALIDATION_ERROR`
- `NOT_FOUND`
- `APPROVE_FAILED`

Teams 알림 메시지 형식:

```text
FAQ가 등록됐습니다. FAQ 제목 : {FAQ 제목} / 등록자 : {등록자 이름}
```

### 3.4.1 POST `/api/admin/posts/approve-with-content`

외부 시스템이 승인 UPDATE 결과를 직접 전달하는 API다. `POS_FAQ_MST`를 다시 조회하지 않고
전달받은 내용으로 Chroma 임베딩과 권한 그룹 `8001` Teams 알림을 처리한다.

DB의 승인 트랜잭션을 `COMMIT`한 후 이 API를 호출해야 한다.

요청 예시:

```json
{
  "regDt": "20260811",
  "seq": 123,
  "title": "상품 검색 오류 처리 방법",
  "answer": "HBO에서 상품 사용 여부를 확인합니다.",
  "category": "1",
  "keywords": "상품검색,상품미존재",
  "registrantName": "김정우"
}
```

SQL `OUTPUT INSERTED` 결과를 그대로 보내기 쉽도록 아래 대문자 필드명도 허용한다.

```json
{
  "REG_DT": "20260811",
  "SEQ": 123,
  "TITLE": "상품 검색 오류 처리 방법",
  "ANSWER": "HBO에서 상품 사용 여부를 확인합니다.",
  "CATEGORY": "1",
  "KEYWORDS": "상품검색,상품미존재",
  "REG_USER": "김정우"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `regDt` | string | Y | FAQ 등록일, `YYYYMMDD` |
| `seq` | int | Y | FAQ 순번, 0보다 커야 함 |
| `title` | string | Y | FAQ 제목 |
| `answer` | string | Y | FAQ 답변 |
| `category` | string | Y | FAQ 카테고리 |
| `keywords` | string | N | 검색 키워드 |
| `registrantName` | string | Y | FAQ 등록자 이름 |

성공 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "게시글이 벡터에 반영되었고 알림 3건이 등록되었습니다.",
  "errorCode": null
}
```

대표 오류 코드:

- `VALIDATION_ERROR`
- `APPROVE_WITH_CONTENT_FAILED`

### 3.5 POST `/api/admin/posts/upsert-embedding-by-key`

DB 상태는 변경하지 않고, 특정 FAQ를 벡터DB에 즉시 upsert한다.

요청 예시:

```json
{
  "regDt": "20240101",
  "seq": 123
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `regDt` | string | Y | 8자리 날짜 문자열 |
| `seq` | int | Y | FAQ 순번. 0보다 커야 함 |

성공 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "게시글이 벡터에 반영되었습니다.",
  "errorCode": null
}
```

대표 오류 코드:

- `VALIDATION_ERROR`
- `NOT_FOUND`
- `EMBED_FAILED`

### 3.6 POST `/api/admin/posts/delete-embedding-by-key`

특정 FAQ 문서를 RAG 검색 대상에서 제거한다.

Windows의 Chroma/HNSW 네이티브 삭제 안정성 문제를 피하기 위해
`collection.delete()`를 호출하지 않고 별도 SQLite tombstone에 문서 ID를 기록한다.
검색 시 tombstone 문서는 제외하며, 같은 키가 다시 승인되면 tombstone을 해제한다.
이미 제거된 키를 다시 요청해도 성공으로 처리하는 멱등 API다.

요청 예시:

```json
{
  "regDt": "20240101",
  "seq": 123
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `regDt` | string | Y | 8자리 날짜 문자열 |
| `seq` | int | Y | FAQ 순번. 0보다 커야 함 |

성공 응답 예시:

```json
{
  "success": true,
  "requestId": 123,
  "message": "FAQ가 검색 대상에서 제거되었습니다.",
  "errorCode": null
}
```

대표 오류 코드:

- `VALIDATION_ERROR`
- `DELETE_FAILED`

### 3.7 POST `/api/faqs/top-questions`

활성 FAQ를 카테고리별로 조회하고 `FILLER1` 수치를 내림차순 정렬하여 최대
5개의 상위 질문을 반환한다. 동일 가중치는 최신 등록일과 SEQ 순으로 정렬한다.

요청 예시:

```json
{
  "category": "1",
  "limit": 5
}
```

카테고리는 `1` POS공통, `2` PPOS, `3` APOS, `4` 서버, `5` HBO, `6` 키오스크를 사용한다.
과거 한글 카테고리 데이터도 같은 코드의 조회 결과에 포함한다.

기존 숫자 코드 `4`를 KIOSK, `5`를 서버로 저장한 데이터는 신규 체계 적용 전에
각각 `6` 키오스크, `4` 서버로 데이터 이관이 필요하다.

성공 응답 예시:

```json
{
  "ok": true,
  "category": "1",
  "categoryName": "POS공통",
  "questions": [
    {
      "regDt": "20260811",
      "seq": 12,
      "question": "상품이 조회되지 않을 때 어떻게 하나요?",
      "category": "1",
      "weight": 8.5
    }
  ]
}
```

### 3.8 GET `/api/health`

서비스 상태 확인용 API다.

성공 응답 예시:

```json
{
  "resCd": "0000",
  "resMsg": "OK",
  "answer": ""
}
```

### 3.8 POST `/tools/create_pos_master`

POS 마스터 상태를 갱신하는 내부 도구 API다.
`posNo`는 단건, 콤마 구분 목록, 범위 입력을 모두 지원한다.
`targetType`은 `single`, `list`, `range`, `pos_knd` 중 하나로 응답된다.

요청 예시:

```json
{
  "posNo": "1111,1112",
  "requestedBy": "system"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `posNo` | string | Y | POS 번호. `1111`, `1111,1112`, `1111~1200`, `1111-1200` 형식 지원 |
| `requestedBy` | string | N | 요청자 식별용 필드. 현재 내부 로직에서는 미사용 |

허용 예시:

```json
{ "posNo": "1111" }
```

```json
{ "posNo": "1111,1112" }
```

```json
{ "posNo": "1111~1200" }
```

```json
{ "posNo": "1111-1200" }
```

성공 응답 예시:

```json
{
  "ok": true,
  "message": "POS 마스터 업데이트 완료: 210 POS 1111,1112 (반영 2건)",
  "storeCd": "210",
  "posNo": "1111,1112",
  "posKnd": null,
  "targetType": "list",
  "updated": 2
}
```

실패 응답 예시:

```json
{
  "ok": false,
  "message": "posNo is empty"
}
```

메모:

- 내부적으로 점포코드 `210` 고정으로 처리한다.

### 3.9 POST `/tools/pattern_lookup`

POS 기준 패턴 그룹과 패턴 상세 목록을 조회하는 내부 도구 API다.

요청 예시:

```json
{
  "posNo": "1111",
  "searchType": null,
  "searchValue": null,
  "page": 1
}
```

`searchType`이 `null`이면 전체조회다. `0`은 패턴코드 exact 조회, `1`은 패턴명 LIKE 조회다.

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `posNo` | string | Y | POS 번호 |
| `searchType` | string \| null | N | `null`이면 전체조회 |
| `searchValue` | string \| null | N | `searchType`이 `0` 또는 `1`일 때만 사용 |
| `page` | int | N | 1부터 시작하는 10건 단위 페이징 |

성공 응답 예시:

```json
{
  "ok": true,
  "posNo": "1111",
  "patternGroupCode": "1001",
  "patternGroupName": "할인",
  "searchType": null,
  "searchValue": null,
  "page": 1,
  "pageSize": 10,
  "totalCount": 23,
  "totalPages": 3,
  "hasPrevious": false,
  "hasNext": true,
  "patterns": [
    {
      "patternCode": "0001",
      "patternName": "일반할인",
      "patternValue": "1",
      "PTN_DTL_BIGO": "비고"
    }
  ]
}
```

실패 응답 예시:

```json
{
  "ok": false,
  "message": "패턴 조회 중 오류가 발생했습니다."
}
```

### 3.10 POST `/tools/pattern_update`

POS 패턴 상세값을 수정하는 도구 API다.

요청 예시:

```json
{
  "userId": "kimjungwoo",
  "patternGroupCode": "1001",
  "patternCode": "0001",
  "patternValue": "2"
}
```

요청 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `userId` | string | Y | 수정 요청자 ID. `SYS_USER_MST.ASSIGN_STORE_CD` 조회에 사용 |
| `patternGroupCode` | string | Y | 패턴 그룹 코드 |
| `patternCode` | string | Y | 패턴 코드 |
| `patternValue` | string | Y | 수정할 패턴값 |

성공 응답 예시:

```json
{
  "ok": true,
  "message": "패턴 수정 완료: 1001-0001 (반영 1건)",
  "patternGroupCode": "1001",
  "patternCode": "0001",
  "patternValue": "2",
  "storeCode": "210",
  "updated": 1
}
```

수정 SQL에는 요청자의 `ASSIGN_STORE_CD`가 `STORE_CD` 조건으로 적용된다.
사용자 또는 배정 점코드를 찾을 수 없으면 패턴을 수정하지 않는다.

실패 응답 예시:

```json
{
  "ok": false,
  "message": "대상 패턴을 찾을 수 없습니다.",
  "patternGroupCode": "1001",
  "patternCode": "0001",
  "patternValue": "2",
  "updated": 0
}
```

## 4. 운영 메모

- FAQ 임베딩 반영은 승인 API 또는 임베딩 관리 API를 통해 개별 문서 단위로 처리된다.
- `/api/rag/chat`은 단순 FAQ 검색 API가 아니라 명령형 업무 처리까지 포함하는 복합 진입점이다.
- 외부 연동 문서를 별도로 배포할 경우 `/tools/*` 엔드포인트를 공개 대상에 포함할지 먼저 결정하는 것이 좋다.

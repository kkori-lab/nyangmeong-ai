# AI 매니저 도구 목록 API 설계 (초안)

2026-11-05, LJS. `tool-calling.md`의 다음 차수 정식 도입에서 도구를 어디서 만들지 정한 문서다. **Java가 도구 목록 API로 실행에
필요한 사실을 주고, Python은 LLM이 읽는 설명만 갖는다**(2번 안, 2026-11-05 결정). 팀 확인 전 초안이다.
들어가려면 기능명세서 AI매니저에 기능 ID를 먼저 넣고, 내부 API 계약은 백엔드 PR과 함께 낸다(AGENTS.md 4번).

## 0. 한 줄 요약

백엔드가 AI 매니저에 열 API의 컨트롤러 메서드에 `@AiTool`을 붙인다. Java는 표시가 붙은 메서드와 요청 DTO의 검증 어노테이션을
읽어 `GET /internal/ai/tools`로 도구 목록(경로·칸·필수·조건부 규칙·공통코드 값·version)을 준다. Python은 기동 때 이 목록과
`data/tool_prompts.yaml`(설명·예문·hook)을 이름으로 합쳐 pydantic 모델과 Anthropic 도구 정의를 만든다.

## 1. 결정한 것 (2026-11-05)

| 항목 | 결정 | 이유 |
| --- | --- | --- |
| 도구 목록 출처 | Java API (파일 관리 안 대신) | 경로·필수 값·공통코드의 정본이 Java 하나. 어긋나면 등록이 조용히 실패한다 |
| 나눔 | Java = 실행에 필요한 사실, Python = LLM 설명·예문·도구별 처리(hook) | 설명은 평가하며 자주 고친다. 문구 수정마다 백엔드 배포를 하지 않는다 |
| 공통코드 값 | Java가 DB에서 읽어 응답에 넣는다. 파일·문서에 적지 않는다 | 공통코드는 DB에만 둔다 |
| LLM에 주는 `required` | 주지 않는다. 필수 판단은 Python이 Java 규칙으로 한다 | 필수라고 하면 LLM이 값을 지어낸다 |
| 범위 | 아래 2절 (1단계 읽기에서 알림·채팅 제외, 2단계 쓰기는 건강·가계부만) | 2026-11-05 사람 지정 |

## 2. 범위

### 2-1. 1단계 — 읽기 (Python이 바로 실행, `kind: READ`)

| 도메인 | 도구 후보 | Java API |
| --- | --- | --- |
| 반려동물·캐릭터 | 내 반려동물 목록·상세, 공동양육자, 받은 초대, 오늘의 케어 미션, 포인트·내역, 캐릭터·보유 아이템 | `GET /api/pets`, `/api/pets/{petSn}`, `/api/pets/{petSn}/caregivers`, `GET /api/caregiver-invitations`, `GET /api/pets/{petSn}/daily-missions`, `GET /api/members/me/points`, `GET /api/point-ledgers`, `GET /api/pixel-characters`, `/{pixelCharSn}/held-items` |
| 건강 | 일정, 케어 항목·완료, 건강 일지, 검진·처방약·검사 수치·기타검사, 반복 예방, 건강 지표, 관찰(메인 노출 여부는 `list_care_items`의 `mainExpsrYn`. `/care-item-exposures`는 PUT만 있어 읽기 아님, 2026-11-06 백엔드 확인) | `/api/pets/{petSn}/care-schedules`, `/care-items`, `/care-completions`, `/daily-health-records`, `/checkups`, `/prescriptions`, `/inspection-values`, `/etc-inspections`, `/repeat-preventions`, `/health-indicators`, `/observation-items`, `/observation-cycles` |
| 가계부 | 지출 목록·합계·월별·통계·반려동물별, 영수증 상세 | `GET /api/expenses`, `/totals`, `/months`, `/statistics`, `/pets`, `/api/receipts/{recptSn}` |
| 커뮤니티·플레이스 | 글 목록·인기·건강 팁·상세·댓글, 실종 신고, 돌봄 모집, 뉴스, 장소·즐겨찾기 | `GET /api/posts`, `/popular-photo`, `/health-tips`, `/{pstSn}`, `/{pstSn}/comments`, `GET /api/lost-reports`, `GET /api/care-recruitments`, `GET /api/news`, `GET /api/places`, `GET /api/place-bookmarks` |
| 고객센터 | 자주 묻는 질문 | `GET /api/faqs` |

제외: 알림(`/api/notifications/**`, 알림 설정), 1:1 채팅(`/api/chat-rooms/**`).

### 2-2. 2단계 — 쓰기 (카드 확인 → [확인] → React 실행, `kind: CARD`)

| 도메인 | 도구 후보 | Java API |
| --- | --- | --- |
| 건강 | 일정 등록·수정(지금 `draft_schedule`), 케어 항목 등록·수정(지금 `draft_care_item`), 오늘 케어 완료 체크, 건강 일지 기록, 관찰 기록 추가, 반려동물 정보 일부 수정(몸무게 등) | `POST /api/pets/{petSn}/care-schedules`, `/{schdlSn}`, `/care-items`, `/care-completions`, `POST /daily-health-records`, `/observation-cycles`, `PATCH /api/pets/{petSn}` |
| 가계부 | 지출 등록(중복 확인 먼저)·수정, 월 지출 한도, 영수증 인식 결과 저장(SCR-AIM-013 [확인 후 저장]을 카드로) | `POST /api/expenses`(`/duplicate-check`), `/api/expenses/{expndSn}`, `PUT /api/members/me/expense-limit`, `/api/receipts/{recptSn}/save` |

제외: 설정(알림 설정·읽음 처리), 커뮤니티(글·댓글·실종 신고 초안·즐겨찾기).

### 2-3. 3단계 — `navigate`만 (`@AiTool`을 붙이지 않는다)

반려동물 등록(필수 9칸·품종·털색 조건부 규칙), 모든 삭제, 회원정보·비밀번호·닉네임 수정과 탈퇴(본인 확인), 공동양육 초대·수락·거절·해제와
대표 반려동물 변경, 캐릭터 장착·아이템 구매(포인트), 돌봄 매칭·모집 쓰기, 좋아요·신고, 1:1 채팅 보내기, 실종 신고 찾음·연장,
검진 첨부·검사 수치 올리기. `admin`·`auth`·`scheduler`·내부 API는 처음부터 대상이 아니다.

경로는 백엔드 develop의 컨트롤러에서 뽑았다(2026-11-05). 메서드가 표시되지 않은 행은 이름으로 짐작했으므로 백엔드 PR에서 확인한다.

## 3. Java가 하는 일 (백엔드)

### 3-1. 어노테이션

| 어노테이션 | 붙이는 곳 | 내용 |
| --- | --- | --- |
| `@AiTool(name, domain, kind)` | 컨트롤러 메서드 | 이 API를 AI 매니저가 써도 된다. `name`은 Python 설명과 짝짓는 키, `kind`는 `READ`·`CARD` |
| `@AiCode("그룹")` | 요청 DTO 필드·`@RequestParam` | 공통코드 그룹. 값은 응답을 만들 때 DB에서 |
| `@AiRequiredIf(field, when, equals)` | 요청 DTO | 조건부 필수(예: 병원 일정이면 검진유형·병원명) |
| `@AiOneOf({a, b})` | 요청 DTO | 둘 중 하나만(예: 품종 번호·품종 직접 입력) |

필수·형식은 이미 있는 `@NotNull`·`@NotBlank`·`@Size`·`@Positive`·`@Digits`·`@Pattern`을 그대로 읽는다. `min < max`처럼
어노테이션으로 표현하기 어려운 규칙은 표시하지 않는다(Java 서비스 검사 + Python hook).

표시를 빠뜨리면 그 API가 도구로 열리지 않을 뿐이다(잘못 열리는 쪽의 사고는 없다).

### 3-2. `GET /internal/ai/tools` (확정, 백엔드 PR #174·#177)

- 위치·인증: 다른 Python → Java 내부 API와 같다(nginx 밖, 키 없음). 회원과 관계없는 목록이라 쿠키가 없어도 된다.
- 만드는 법: `RequestMappingHandlerMapping`에서 `@AiTool` 메서드를 모으고, 매핑(메서드·경로), `@PathVariable`·`@RequestParam`,
  `@RequestBody` DTO 필드와 검증 어노테이션을 읽는다. `@AiCode`는 공통코드 테이블에서 사용 중인 값만 붙인다.
- `version`: 응답 본문(코드 값 제외 구조 + 코드 값)의 해시. 구조만의 해시 `structureVersion`도 따로 준다(스냅샷 비교용).

```json
{
  "version": "<해시>",
  "structureVersion": "<해시>",
  "tools": [
    {
      "name": "draft_schedule",
      "domain": "health",
      "kind": "CARD",
      "call": {"method": "POST", "path": "/api/pets/{petSn}/care-schedules"},
      "params": {
        "petSn": {"in": "path", "type": "long", "required": true},
        "schdlKndCd": {"in": "body", "type": "code", "group": "<그룹>", "required": true,
                       "codes": [{"cd": "<코드>", "nm": "<이름>"}]},
        "schdlYmd": {"in": "body", "type": "date", "required": true},
        "hsptlNm": {"in": "body", "type": "string", "maxLength": 50}
      },
      "rules": [{"requiredIf": {"field": "hsptlNm", "when": "schdlKndCd", "equals": "<코드>"}}]
    },
    {
      "name": "list_checkups",
      "domain": "health",
      "kind": "READ",
      "call": {"method": "GET", "path": "/api/pets/{petSn}/checkups"},
      "params": {
        "petSn": {"in": "path", "type": "long", "required": true},
        "year": {"in": "query", "type": "int", "min": 1900, "max": 2200},
        "ckupTypeCd": {"in": "query", "type": "code", "group": "<그룹>",
                       "codes": [{"cd": "<코드>", "nm": "<이름>"}]},
        "page": {"in": "query", "type": "int", "min": 1},
        "size": {"in": "query", "type": "int", "min": 1, "max": 50}
      },
      "rules": []
    }
  ]
}
```

`in`: `path`·`query`(`@RequestParam`과 `@ModelAttribute` 검색 조건·페이지 칸, PR #177)·`body`.

칸 `type`: `string`·`long`·`int`·`decimal`(`precision`·`scale`)·`boolean`·`date`·`time`·`datetime`·`code`. 숫자 칸은
`@Min`·`@Max`를 `min`·`max`로 준다(Python은 `input_schema`의 `minimum`·`maximum`으로 싣고 범위 밖 값은 비운다). 목록(`List<…>`)·중첩 객체는
1단계에서 쓰지 않는다(나오면 그 도구를 싣지 않고 경고).

### 3-3. 같이 맞출 것

| 항목 | 내용 | 왜 |
| --- | --- | --- |
| 오류에 필드 이름 | 400 응답은 지금 모양 그대로 `data: [{field, message}]`(Bean Validation 오류만 칸 이름이 있다). 서비스 검사(`INVALID_INPUT_VALUE`)의 칸 이름은 백엔드 PR #175로 `CareScheduleService`·`CareItemService`만 담는다. 다른 서비스는 칸 없이 그대로라, 2단계에서 새 도메인에 CARD를 붙일 때 그 서비스도 칸을 담게 바꾼다 | 지금은 `checkPet` 등 서비스 오류가 칸을 알려 주지 않아 다시 물을 칸을 정할 수 없다 |
| 수정은 PATCH | 2-2절 수정 API는 이미 PATCH다(일정 `/{schdlSn}`·케어 항목·지출 `/{expndSn}`·반려동물 `/{petSn}`, 2026-11-06 백엔드 확인). PUT은 월 지출 한도(값 하나)뿐이라 그대로 둔다 | 말하지 않은 칸 때문에 필수 오류 |
| 출처 기록 | 대화로 실행한 쓰기는 등록 출처 코드(지금 일정의 AI 대화창 출처와 같은 방식)를 남긴다 | 감사·통계 |
| 검증만 하는 호출 | 규칙이 많은 도구만 나중에(`POST …/validate`, 저장 없이 `fieldErrors`) | 처음부터 맞게 보내기. 1단계 범위 밖 |

## 4. Python이 하는 일 (이 저장소)

### 4-1. 파일

| 파일 | 내용 |
| --- | --- |
| `data/tool_prompts.yaml` | 도구 이름별 설명(쓸 때·쓰지 않을 때·예문·말하는 법), hook 이름, 결과 요약 방식. 코드 값은 적지 않는다 |
| `data/tools.snapshot.json` | Java 응답의 구조 부분(코드 값 제외). CI·평가·Java 장애 때 기준. 6절 |
| `app/chat/catalog.py`(가칭) | 목록 받기·합치기·모델 만들기·version 확인 |

### 4-2. 기동 때

1. `GET /internal/ai/tools`를 부른다. 실패하면 `tools.snapshot.json`으로 뜨고 코드 값이 필요한 카드 도구는 싣지 않는다(경고 로그).
2. `structureVersion`이 스냅샷과 다르면 경고 로그(배포 순서 어긋남). Java 응답을 쓴다.
3. Java 목록과 `tool_prompts.yaml`을 이름으로 합친다. 한쪽에만 있는 도구는 싣지 않고 경고한다.
4. 도구마다 `pydantic.create_model`로 검증 모델을 만든다. 이 모델로 Anthropic `input_schema`를 만들되 `required`는 빼고,
   `code` 칸은 `enum`(코드 값)과 설명(코드 이름)을 붙인다. 지금 `tools.py`의 손으로 쓴 모델과 설명 속 코드 값은 이것으로 바뀐다.
5. 결과는 메모리에 둔다(`@lru_cache`, `routing_table()`과 같은 방식). 다시 받는 주기는 기동 때 1회 + 정해진 간격(결정 남음).

### 4-3. 한 턴

```
메시지 → 룰 앞단(지금과 같음) → 도메인 고르기 → 그 도메인 도구 + navigate·search_guide·decline으로 LLM 도구 선택
  ├─ READ  → 인자 검증 → Python이 Java 공개 API를 브라우저 Cookie 그대로 실어 호출 → 결과 요약을 tool_result로 → 답변 스트리밍
  ├─ CARD  → 인자 검증(틀린 칸 비움) → Java 규칙(required·rules) + hook으로 빈 칸 → 되물음 카드 또는 확인 카드
  │          → 회원 [확인] → React가 Java 공개 API 실행 → 실패하면 fieldErrors의 칸만 다시 묻기, 없으면 navigate 안내
  └─ navigate·search_guide·decline → 지금과 같음
```

- 도메인 고르기: 도구 수십 개를 한 번에 싣지 않는다. 지금 분류 LLM 자리에서 도메인을 고르거나, 도메인이 분명한 룰 앞단 결과를 쓴다(결정 남음).
- 인증: Python → Java는 브라우저에서 받은 `Cookie`를 그대로 보내고 회원은 Java가 판정한다(2026-10-27 결정, `docs/api/internal.md`).
  `mbrSn`을 넘기지 않는다. 읽기도 Java 공개 API의 소유 검사를 그대로 탄다.
- 읽기 결과는 대화 이력에 원문을 남기지 않는다. 답변 글만 저장된다(지금 이력 규칙).
- 프롬프트 인젝션: 글·댓글 같은 남이 쓴 글을 읽은 턴에서는 쓰기 도구를 고르더라도 카드 확인 없이는 실행되지 않는다(쓰기는 항상 회원 확인).

### 4-4. hook (도구 이름으로 등록한 Python 함수)

| hook | 하는 일 |
| --- | --- |
| `pet` | `petSn`을 문장과 대화의 반려동물로 정한다(지금 FN-AIM-012-04 규칙) |
| `date` | "다음 주 화요일" 같은 말을 오늘 기준 날짜로(지금 등록 칸 추출과 같음) |
| `same_name_warning` | 같은 이름 케어 항목 경고(FN-AIM-012-08) |
| `duplicate_expense` | 지출 중복 확인(`/api/expenses/duplicate-check`) |
| `weight_range` 등 | 어노테이션으로 표현 못 하는 형식 규칙 |
| 결과 요약 | READ 결과를 답변용 글로, CARD 결과를 이력용 한 줄로 |

## 5. 프론트가 하는 일

- 범용 카드: 확인 카드의 `params`(타입·필수·코드 목록·검증)를 SSE로 받아 폼을 그린다. 공통코드는 칩, 날짜는 날짜 입력, 숫자는
  숫자 입력. 필수 칸이 비면 [확인]이 눌리지 않는다. 지금 등록 카드(SCR-AIM-012)를 이것으로 넓힌다.
- 실행: [확인]이면 카드의 `call`(메서드·경로)로 Java 공개 API를 부르고, `register-result`처럼 요약 한 줄을 대화 이력에 남긴다.
- 본창 새로고침: 대화창에서 쓰기가 성공하면 본창에 바뀐 도메인·`petSn`을 알린다(지금 없음, `tool-calling.md` 2절).
- SSE 계약 추가는 `tool-calling.md` 6절 응답 계약 변경안과 함께 낸다.

## 6. 빌드·배포

```
백엔드 main 배포 성공
  └─ 도구 목록 구조(코드 값 제외)를 deploy-latest 릴리스에 함께 올림
  └─ repository_dispatch → AI 저장소 워크플로
        └─ 받아서 data/tools.snapshot.json에 쓰고, structureVersion이 바뀌었으면 PR 생성 + check.sh
              └─ 사람이 확인(필요하면 tool_eval) → 병합 → 기존 main.yml 배포
```

- 조건은 Java "빌드 성공"이 아니라 "배포 성공"이다. Java 롤백이면 스냅샷 PR도 되돌린다.
- 구조 목록은 DB 없이 만든다(앱을 띄우지 않고 어노테이션·DTO를 읽는 Gradle 작업이나 테스트). 코드 값은 실행 중에만.
- Python 혼자 배포(설명·프롬프트 수정)는 그대로 된다. 마지막 스냅샷을 쓴다.
- 저장소를 건너 깨우는 데 토큰(PAT 또는 GitHub App)이 필요하다. 공개 저장소이므로 비밀값으로만 둔다.
- 처음에는 자동 PR 없이 사람이 로컬에서 받아 커밋해도 된다(같은 파일, 같은 테스트).

## 7. 테스트·평가

- CI는 Java 없이 돈다. `tools.snapshot.json`과 가짜 코드 값으로 합치기·모델 만들기를 테스트한다(AGENTS.md 5번).
- 테스트: ① 스냅샷의 모든 도구에 `tool_prompts.yaml` 설명이 있고 그 반대도 같다 ② hook 이름이 Python에 다 있다
  ③ 2-3절(`navigate`만) API가 스냅샷에 없다 ④ 만든 모델이 Java 필수·규칙대로 빈 칸을 찾는다 ⑤ `required`가 LLM 스키마에 없다.
- 평가: 도구를 늘릴 때마다 `tests/chat/data/tool_eval.jsonl`에 그 도구와 헷갈리는 문항을 더한다. "쓰기 도구 잘못 고름 0"을 넘어야
  다음 도메인을 연다. 결과에 `structureVersion`을 남긴다.
- 지금 도구 5개를 이 구조로 옮긴 뒤 `tool_eval`이 1단계 실험 값(지금 32/44, 도구 Haiku 35~36/44, 쓰기 잘못 0)에서 떨어지지 않아야 한다.

## 8. 진행 순서 (마일스톤 후보)

| 차례 | 내용 | 담당 | 선행 |
| --- | --- | --- | --- |
| 0 | 기능명세서 AI매니저에 도구 목록·읽기 도구·확인 카드 기능 ID 추가, 팀 확인 | LJS(명세) | — |
| 1 | Python: 목록 받기·합치기·동적 모델(`catalog.py`), 지금 도구 5개를 가짜 Java 응답(`tests/` 가짜 + 스냅샷)으로 옮김, `tool_eval` 재측정 | LJS(AI) | 0 |
| 2 | Java: 어노테이션, `GET /internal/ai/tools`, `fieldErrors`, 지금 일정·케어 항목 API에 표시 | 백엔드 | 0 |
| 3 | 연결: 가짜 → 실제 Java, `docs/api/internal.md` 행 확정 (끝 2026-11-06) | LJS·백엔드 | 1·2 |
| 4 | 1단계 읽기를 도메인별로 연다(건강 → 가계부 → 반려동물 → 커뮤니티·플레이스·FAQ). 도메인 고르기 | LJS·백엔드 | 3 |
| 5 | 프론트 범용 카드·본창 새로고침, 2단계 쓰기(건강 → 가계부). Python: ① ACTION 계약·단순 등록 3개(끝 2026-11-09), ② 수정 4개(READ → CARD, 경로 번호를 못 정하면 카드 없이 안내 글), ③ 배열·파일 칸 3개, ④ 기존 등록 카드 2개 전환 | 프론트·LJS | 3, 응답 계약 |
| 6 | 스냅샷 자동 PR 파이프라인 | LJS·백엔드 | 3 |

1은 Java가 없어도 된다(가짜 응답으로 먼저 만들고 나중에 연결). `CHAT_TOOL_AGENT` 설정은 2026-11-09 지웠다(앱은 항상 도구 흐름).

## 9. 결정 남음

- 도메인 고르기 방법(분류 LLM에 도메인 칸 추가 vs 룰 앞단 vs 두 단계 도구 선택)
- 목록을 다시 받는 주기(기동 때만 vs 몇 분마다)와 Java 장애 때 카드 도구를 끌지
- 읽기 결과가 길 때(지출 목록 수백 건) 자르는 기준: Java 쪽 페이지 크기 vs Python 요약
- 2단계 실행을 React가 할지, 확인 토큰을 받아 서버가 할지(지금 원칙은 React)
- `@AiTool` 표시를 붙일 API 목록 최종(2절은 후보). PATCH 여부는 3-3절에서 정함(백엔드 PUT 10개 중 2-2절 대상은 월 지출 한도뿐)

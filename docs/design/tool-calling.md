# AI 매니저 tool calling 설계 (초안)

2026-11-05, LJS. **다음 차수로 결정**(5절). AI매니저 범위는 2026-10-26에 v0.9로 확정했으므로 이번 차수에는 1단계 실험(평가)만 한다.
들어가려면 기능명세서에 기능 ID를 먼저 넣고, 응답 계약 변경은 프론트·백엔드 PR과 함께 낸다(AGENTS.md 4번).
도구를 어디서 만들지(Java 도구 목록 API + Python 설명 파일)는 `tool-catalog.md`(2026-11-05 결정).

## 0. 한 줄 요약

"캐릭터 어디서 만들어?"에 화면 이동만 하지 않고, **대화창 안에서 그 일을 끝까지** 하게 한다. LLM은 도구를 고르고 인자를
채우기만 한다. 저장·변경은 대화창 카드에서 회원이 확인한 뒤 React가 기존 API로 실행한다. 본창으로 보내는 것은 `navigate`
하나뿐이다. Python은 지금처럼 상태 없는 AI 서버로 남는다.

## 1. 지금 흐름과 바꿀 곳

```
메시지
 ├─ 이미지 첨부 → 영수증 분석(RECEIPT)                     규칙
 ├─ 등록 요청 정규식 → 추출 LLM → 등록 카드(REGISTER)        규칙 + LLM ①
 ├─ 룰 라우팅(routing.yaml) → 이동(ROUTE)                   규칙
 └─ 분류 LLM(ROUTE·SEARCH·GUIDE·OUT_OF_SCOPE·UNKNOWN)       LLM ②
       └─ SEARCH·GUIDE → 답변 LLM(스트리밍)                 LLM ③
```

- 갈래마다 프롬프트와 LLM 호출이 따로다(분류·추출·답변). 새 동작을 넣을 때마다 분류 종류, 추출 프롬프트, SSE 갈래가 하나씩 는다.
- 사용법 질문은 안내서 답변이나 이동으로 끝난다. 대화창에서 그 일을 할 수는 없다.
- 이미 대화창 안에서 끝나게 만든 것: 등록 카드(SCR-AIM-012). React가 대화창에서 저장하고 `register-result`로 요약을 남긴다.
  다만 저장 부분은 아직 가짜다(3-2-1). 영수증 [확인 후 저장](SCR-AIM-013 ⑤)은 본창 확인 모달을 열고 대화창을 닫는다(10-26 확정).

tool calling으로 바꾸면 ②의 분류와 ①의 추출이 **도구 선택 한 번**으로 합쳐진다. 답변(③)은 도구 결과를 받은 같은 대화 안에서 이어 쓴다.

## 2. 원칙

| 원칙 | 내용 | 근거 |
| --- | --- | --- |
| LLM은 고르기만 | LLM은 도구 이름과 인자만 낸다. Python이 pydantic으로 인자를 검증(공통코드 enum, `routing.yaml` 화면 ID, `petSn`은 양육 반려동물 중 하나)한 뒤 내보낸다 | 환각 인자 차단 |
| 대화창에서 끝낸다 | `navigate`를 뺀 모든 도구는 대화창 안의 카드로 확인·입력·실행·결과 표시까지 한다. 본창 모달을 열거나 대화창을 닫지 않는다 | 2026-11-05 결정(5절, 예외 없음). 지금 등록 카드 방식을 넓힌 것 |
| 쓰기는 사람 확인 | 저장·변경 도구는 카드의 버튼을 회원이 눌러야 실행된다. 실행은 React가 하고 Python은 쓰기 API를 부르지 않는다 | REQ-AIM-004(확인 없이 저장 안 함)를 넓힌 것 |
| 실행은 화면에서 | React가 지금 화면에서 쓰는 Java API·`/ai/**`를 대화창에서 그대로 부른다 | `chat`은 다른 기능 패키지를 import하지 않는다. 백엔드 계약·인증 위치 그대로 |
| 권한은 Java | 주양육자인지, 캐릭터가 이미 있는지, 남의 반려동물인지는 Java가 판정한다. Python 검증은 엉뚱한 카드를 띄우지 않으려는 것일 뿐이다 | 2026-10-26 결정 |
| 글은 초안까지 | 게시글·문의는 LLM이 초안을 채우고, 회원이 카드에서 고친 뒤 [올리기]를 눌러야 올라간다 | 회원 이름으로 나가는 글 |
| 되돌리기 어려운 일은 도구가 아님 | 삭제, 탈퇴, 포인트 구매·장착, 공동양육 초대·해제는 `navigate`만 한다 | 오작동 비용 |
| 규칙 앞단 유지 | 룰 라우팅은 LLM 앞에 그대로 둔다. 이미지 첨부는 LLM이 용도를 판단한다(5절) | FN-AIM-002-10(LLM 장애와 무관한 이동), 비용 |
| 대화 이력은 글로 | Java `AI_CNVRS_MSG`에는 역할과 글만 저장된다. 도구 결과는 요약 한 줄(예: `✔ 기록됨 — 복실 체중 5.2kg`)로 남기고 `tool_use` 블록은 저장하지 않는다 | `register-result`·`receipt-result`와 같은 방식. ERD 변경 없음 |
| 본창 새로고침 | 대화창에서 저장하면 본창이 낡은 화면을 보여 줄 수 있다. 대화창이 본창에 "바뀜(종류·petSn)"을 알리고 본창이 그 화면만 다시 읽는다 | 프론트 작업(창 사이 메시지). 지금은 이 장치가 없다(3-2-1) |

## 3. 도구 후보 (AI 매니저 관련 기능 위주)

종류: **서버** = Python이 그 자리에서 실행하고 결과를 LLM에 돌려준다(읽기만). **카드** = 대화창 카드에서 확인·입력하고
React가 실행한다. **이동** = 본창 이동(지금 ROUTE). "Java API"는 지금 화면이 쓰는 공개 API를 대화창에서 그대로 부른다는 뜻이다
(있는지·요청 형식은 프론트 코드로 확인 필요).

### 3-1. 1단계 — 지금 기능을 도구로 (응답 계약 그대로)

| 도구 | 종류 | 대화창에서 하는 일 | 실행 | 지금 기능 |
| --- | --- | --- | --- | --- |
| `navigate(scrId, param, query?)` | 이동 | 본창을 그 화면으로 보내거나 모달을 연다. `query`는 검색어가 채워진 채로 열기("근처 24시 동물병원", "펫이야기 사료 글") | React(지금과 같음) | FN-AIM-004. `query`는 프론트가 경로에 검색어를 받는지 확인 필요 |
| `search_guide(query, chunk_id?)` | 서버 | 안내서 사용법 청크 3개를 꺼내 답한다 | Python(파일) | FN-AIM-002-02. 지금 목차 선택(`guide_id`)은 `chunk_id`로 옮긴다 |
| `draft_schedule(...)` | 카드 | 일정 확인 카드(빈 칸이면 되물음) → [등록] | Java 일정 등록 | FN-AIM-012-05·06. 인자 = `RegisterDraft` |
| `draft_care_item(...)` | 카드 | 케어 항목 확인 카드, 같은 이름 경고 → [등록] | Java 케어 항목 등록 | FN-AIM-012-07·08 |

### 3-2. 2단계 — 대화창에서 하는 새 일 (응답 계약 추가, 6절)

앞쪽일수록 먼저 한다. 짧고 자주 하는 입력, 되돌리기 쉬운 것부터.

"실행 API"는 2026-11-05 프론트 develop(db70917)의 `src/features/*/api.js`와 백엔드 develop `docs/api/*.md`에서 확인했다.
`/ai/**`는 이 저장소, 나머지는 Java 공개 API다. 필수 칸은 백엔드 요청 DTO의 필수(Y) 필드다.

| 도구 | 예시 말 | 대화창에서 하는 일 | 실행 API (요청 DTO · 담당) | LLM이 채울 인자 | 대조에서 나온 것 |
| --- | --- | --- | --- | --- | --- |
| `draft_daily_record` | "복실이 오늘 5.2kg, 산책 30분" | 오늘 기록 카드(지표별 줄) → [기록] | `POST /pets/{petSn}/daily-health-records` (DailyHealthRecordCreateRequest · JAJ). 필수 `dailyRcdIdctCd`·`rcdDt`, 값은 `rcdNvl` 또는 배변 `crsdSttsCd` | `petSn`, 지표별 `{dailyRcdIdctCd, rcdNvl \| crsdSttsCd}`, 시각(없으면 지금) | **지표 하나에 한 건**이다. "체중·산책"은 React가 두 번 부른다. 일괄 등록 API는 없다 |
| `complete_care_item` | "심장사상충약 먹였어" | 완료 카드(반려동물·항목) → [완료] | `POST /pets/{petSn}/care-completions` (CareCompletionCreateRequest · JAJ). 필수 `careArtclSn` | `petSn`, 항목 이름 | 요청은 **항목 번호**인데 Python이 받는 `register-context`에는 이름만 있다. React가 `GET /pets/{petSn}/care-items`로 이름 → 번호를 찾거나, Java가 `register-context`에 `careArtclSn`을 더한다(백엔드와 정함). 같은 날 중복은 Java가 막는다(`UK_CARE_CMPTN_HSTRY_1`). 완료일은 오늘뿐(지난 날짜 칸 없음) |
| `draft_expense` | "사료 3만 2천원 샀어" | 지출 카드(날짜·분류·금액·사용처·반려동물) → [등록] | `POST /expenses/duplicate-check` → `POST /expenses` (ExpenseCreateRequest · SJM). 필수 `expndYmd`·`expndClsfCd`·`expndInptMthCd`·`lines[{petSn?, expndAmt}]`·`idmptDmndId` | `expndYmd`, `expndClsfCd`, 금액, 사용처, `petSn` | 지금 화면처럼 **중복 확인을 먼저** 부른다. `idmptDmndId`(중복 저장 방지)는 React가 만든다. 사진이면 지금 영수증 흐름(`POST /ai/receipts`, 출처 가계부) |
| `preview_items` | "복실이한테 모자 씌워 봐" | 맞는 아이템 후보 칩 → 고르면 미리보기 이미지 | `GET /pixel-characters/{pixelCharSn}/shop-items`(LJS)로 후보 → `POST /ai/characters/{pixelCharSn}/preview` `{itemSns}`(PNG) | 반려동물, 부위(`itemRegnCd`)·검색어 | Python은 아이템 **이름 목록을 모른다**(내부 `bake-items`는 번호·부위·굽기 지시뿐). 후보 고르기는 React가 상점 목록으로 한다. 미리보기는 **주양육자만**. 사기·장착은 `navigate` |
| `start_character(petSn)` | "캐릭터 만들어 줘" | 반려동물·사진 고르기 → [만들기] → 진행 표시 → 결과 이미지 | `POST /ai/characters` multipart `photo`·`petSn` → 202 `{charCrtJobSn}` → `GET /pixel-characters`의 `crtJobSttsCd`를 볼 때까지 반복(지금 마이페이지와 같음) | `petSn` | 품종·털색은 Java 등록값을 읽어 보내지 않는다. 생성 30~40초라 카드에 진행 표시와 "대화창을 닫아도 계속돼요" 안내 |
| `draft_inquiry` | "캐릭터가 이상하게 나왔어요" | 문의 초안 카드(유형·제목·내용) → 고치기 → [보내기] | `POST /inquiries` multipart (InquiryCreateRequest · KSJ). 필수 `inqryTypeCd`·`inqryTtl`·`inqryCn`, 캐릭터 문의면 `pixelCharSn`·`charPhotoSn` | 유형, 제목, 내용 초안, 캐릭터 문의 여부 | 유형 목록은 `GET /common-codes?prntComCd=`(지금 화면과 같음). 캐릭터 문의 칸이 이미 있다(MYP-010-12·24) |
| `set_expense_limit` | "한도 20만원으로" | 한도 카드(지금 값 → 바꿀 값) → [저장] | `PUT /members/me/expense-limit` `{mmExpndLimAmt}` (SJM) | 금액 | 처음 저장하면 한도 알림이 켜진다(Java). 카드에 한 줄 안내 |
| `set_notification` | "댓글 알림 꺼줘" | 알림 카드(바꿀 항목만 표시) → [바꾸기] | `GET` → `PUT /members/me/notification-settings` (NotificationSettingUpdateRequest · LJS) | 바꿀 항목과 켜기·끄기 | PUT은 **8개 칸 모두 필수**(일괄 저장)라 React가 지금 값을 읽어 하나만 바꿔 보낸다. 케어 일정을 켜는데 `leadTimes`가 비면 400 |
| `draft_checkup` | "어제 메이병원에서 접종했어" | 검진기록 카드(날짜·병원·검진유형) → [등록] | `POST /pets/{petSn}/checkups` (CheckupCreateRequest · JAJ). 필수 `ckupYmd`·`hsptlNm`·`ckupTypeCd` | `petSn`, 날짜, 병원명, 검진유형, 내용 | 같은 날짜 병원 일정은 Java가 자동 연결하거나 만든다. **가까운 일정 옮겨 연결**(HLT-002-46)은 고르는 단계가 있어 카드에서는 뺀다 |
| `draft_prescription` | "병원에서 항생제 5일치 받았어, 하루 두 번" | 처방약 카드: 위쪽에 "어느 진료에서 받은 약인가요?"(최근 검진기록 칩 + [새 진료로 기록]) → 약 칸 → [등록] | 기존 진료: `POST /pets/{petSn}/prescriptions` (PrescriptionCreateRequest · JAJ). 새 진료: `POST /pets/{petSn}/checkups` → 돌려받은 `ckupRcdSn`으로 `POST .../prescriptions`. 필수 `ckupRcdSn`·`mdcnNm`·`mdcnBgngYmd`·`mdcnEndYmd`·`dayMdcnNmtm`·`prscSttsCd` | `petSn`, 약 이름, 시작일, 종료일(또는 일수), 하루 횟수, 주기 체크(`careRfltYn`), 새 진료면 날짜·병원·검진유형 | **`ckupRcdSn` 필수**라 진료를 카드에서 고르거나 같이 만든다. 검진기록 후보는 `GET /pets/{petSn}/checkups`. 새 진료는 두 번 호출이라 두 번째가 실패하면 "진료는 기록됐고 약은 저장하지 못했어요 [다시 시도]"(묶으려면 백엔드에 합친 API 요청). 주기 체크를 켜면 투약 케어 항목은 Java가 만든다. 진료 없이 반복하는 예방약은 `draft_care_item` |
| `show_health_report(petSn)` | "복실이 요즘 어때?" | 리포트 카드 | `GET /ai/pets/{petSn}/health-report` | `petSn` | Python API는 있지만 **Java 내부 API 2개가 미구현**이고 메인 위젯도 아직 샘플(`dashboardSample.js`)이다. 메인 위젯 연결 뒤에 한다 |
| `refresh_health_report(petSn)` | "리포트 다시 만들어 줘" | 확인 카드 → [새로 만들기] → 새 리포트 카드 | `POST /ai/pets/{petSn}/health-report/refresh` | `petSn` | 위와 같다. 하루 1회 제한(409 `HEALTH_REPORT_REFRESH_LIMIT`) |
| `request_receipt()` | (사진 없이) "영수증 등록할래" | 대화창 파일 고르기를 연다 → 지금 영수증 흐름 | 지금 대화창 영수증(`POST /ai/receipts` 출처 `AIMC0031` → `receipt-result`) | 없음 | 새 API 없음. 지금은 건강 일지로 이동(부록 A No.14)이라 명세 변경 |
| `receipt_confirm` | (영수증 인식 뒤) | [확인 후 저장]을 대화창 카드에서 확인·수정·저장 | `GET /receipts/{recptSn}?petSn=` → `POST /receipts/{recptSn}/save-check` → `POST /receipts/{recptSn}/save` (ReceiptSaveRequest · LJS) | 없음(인식 결과 그대로) | 저장 한 번에 반려동물별 검진기록·병원 일정·처방약·가계부가 묶인다. 중복 지출·가까운 일정 고르기까지 있어 **가장 큰 카드**다. 이번 차수는 본창 모달 그대로, 다음 차수에 대화창으로(5절) |
| `draft_lost_post` | "복실이 잃어버렸어요" | 실종 글 초안 카드 → 고치기 → [올리기] | `POST /lost-reports` multipart (LostReportCreateRequest · KSJ). 필수 `petSeCd`·`petNm`·`colrNm`·`lastWtnsDt`·`wtnsPlcLat`·`wtnsPlcLot`·`cnpl`·`pstTtl`·`pstCn`·`prvcRlsAgreYn` | 반려동물(이름·구분·품종·털색은 등록값), 마지막 본 때, 장소 이름, 제목·내용 초안 | **목격 좌표가 필수**라 카드에 지도 고르기가 있어야 한다. 연락처·개인정보 공개 동의도 회원이 직접 한다. 품종은 `GET /breeds` 번호 |
| `draft_care_request` | "주말에 복실이 산책 맡길 사람 구해 줘" | 돌봄 요청 글 초안 카드 → 빈 칸 되물음 → 장소·동의 → [올리기] | `POST /care-recruitments` multipart (CareRecruitmentCreateRequest · KSJ). 필수 `pets`·`prtcShpCds`·`schdlCnsltnPsbltyYn`·`cstUnitCd`·`cstAmt`·`rlsRgnNm`·`prtcPlcDaddr`·`prtcPlcLat`·`prtcPlcLot`·`pstTtl`·`pstCn`·`utztnRulAgreYn` | 대상 반려동물, 돌봄 형태 이름, 기간 또는 일정 협의 가능, 비용 단위 이름·금액, 제목·내용 초안 | 칸을 셋으로 나눈다. LLM: 위 인자. 등록값: 반려동물 구분·품종·크기(`GET /pets`). 회원이 카드에서: 공개 지역·상세 주소·좌표(지도·주소 검색), 이용 규칙 동의, 사진. 빈 칸은 등록 카드 ASK처럼 하나씩 묻는다. 비용에 최저시급 안내(`GET /care-recruitments/minimum-wage`). 지도는 `draft_lost_post` 카드와 같은 컴포넌트라 그 뒤에 만든다 |

처음 대조(2026-11-05)에서 뺐던 처방약·돌봄 요청 글은 같은 날 위 방식으로 다시 넣었다. 처방약은 진료 고르기·같이 만들기, 돌봄 글은 회원이 채울 칸을 카드로 분리.

### 3-2-1. 대조에서 나온 공통 문제

- **지금 등록 카드도 아직 가짜로 저장한다.** 프론트 `src/features/ai/api.js` `registerToHealth`가 "JAJ 연결 전 가짜"로 300ms 기다리기만 한다.
  Java `POST /pets/{petSn}/care-schedules`·`POST /pets/{petSn}/care-items`는 있다. 1단계 전에 이 연결부터 해야 "대화창에서 끝낸다"가 실제로 된다.
- **본창 새로고침 장치가 없다.** 대화창은 `openInMainWindow`(`window.opener.location`)로 본창 이동만 하고, 캐시 무효화(`invalidateQueries`)는 각 창 안에서만 한다.
  창 사이 알림(`BroadcastChannel` 등)을 새로 만들어야 한다. 등록 카드가 실제로 저장하게 되면 같은 문제가 생긴다.
- **번호는 React가 찾는다.** 케어 항목·아이템·품종처럼 요청에 번호가 필요한데 Python이 모르는 것은, LLM이 이름이나 검색어를 내고 React가 화면 API로 번호를 찾는다.
  못 찾거나 여럿이면 카드에 후보 칩을 보인다.
- **카드 크기.** 영수증 확인·실종 글·돌봄 글은 지금 화면 컴포넌트(여러 마리 탭, 지도)를 대화창 폭에 넣어야 한다. 나머지는 일정 카드 크기다.
- **공통코드는 이름으로.** 돌봄 형태·비용 단위처럼 공통코드인 칸은 LLM이 이름("산책", "시간당")을 내고 React가 `GET /common-codes`로 코드로 바꾼다.
  이 문서와 도구 설명에는 코드 값을 적지 않는다(코드는 DB에만).

### 3-5. 도구 설명 (LLM이 고르는 기준)

도구를 고르는 정확도는 거의 도구 설명이 정한다. 그래서 도구마다 설명을 쓰되, **정본은 `data/tool_prompts.yaml`**에 둔다
(2026-11-05 `tool-catalog.md` 결정. 처음의 "Python 도구 모델 docstring이 정본" 결정을 바꿨다).

- 위치: `data/tool_prompts.yaml`의 도구 이름별 `description`(도구 설명)과 `params.<칸>.description`(인자 설명).
  등록 도구(`draft_*`)의 칸·필수·코드 값은 Java 도구 목록(`GET /internal/ai/tools`)이 정본이고, `app/chat/catalog.py`가 둘을 합쳐
  검증 모델과 `input_schema`를 만든다. `navigate`·`search_guide`·`decline`은 `builtin: true`(Java API가 아님)이고 인자 모델은 `app/chat/tools.py`에 있다.
- 이 문서에는 쓰는 규칙과 예시만 두고 전문을 옮기지 않는다(두 곳이 어긋나지 않게).
- 말: 한국어. 회원 질문과 안내서가 한국어다. 도구 이름과 인자 이름은 영어.
- 도구마다 다섯 칸을 쓴다.

| 칸 | 쓰는 것 |
| --- | --- |
| 하는 일 | 한두 문장. "대화창에 카드를 띄운다. 회원이 누르기 전에는 아무것도 저장하지 않는다"처럼 실행 결과까지 |
| 쓸 때 | 이 도구를 고를 말의 특징과 예시 말 2~3개 |
| 쓰지 않을 때 | 헷갈리는 이웃 도구와 그쪽으로 보낼 기준. 예: 진료 없는 반복 약 → `draft_care_item` |
| 인자 | 칸마다 채우는 법. 모르면 비워 두라고 쓴다(지어내지 않게). 공통코드는 이름으로, 날짜는 오늘 기준 계산 |
| 말하는 법 | 도구를 부른 뒤 회원에게 할 말의 규칙. 예: "등록했어요"라고 하지 않고 "확인 후 [등록]을 눌러 주세요" |

예시(초안, 실제 문구는 구현 때 평가로 다듬는다):

```python
class DraftPrescription(BaseModel):
    """병원에서 받은 약을 처방약으로 등록하는 카드를 대화창에 띄운다. 회원이 [등록]을 누르기 전에는 저장하지 않는다.

    쓸 때: 진료·병원에서 받은 약, 며칠치·하루 몇 번처럼 기간이 정해진 약.
      예) "항생제 5일치 받았어", "병원에서 소화제 처방받았어"
    쓰지 않을 때: 진료와 상관없이 주기마다 반복하는 예방약·영양제("넥스가드 한 달마다", "유산균 매일")는
      draft_care_item. 약을 먹였다는 말("약 먹였어")은 complete_care_item. 약에 대한 지식 질문은 도구 없이 답한다.
    말하는 법: "등록했어요"라고 하지 않고 카드를 확인해 달라고 한다. 용량이 맞는지 같은 의료 판단을 하지 않는다.
    """

    pet_sn: int | None = Field(
        None, description="대상 반려동물 번호. 회원이 말하지 않았고 여러 마리면 비운다"
    )
    mdcn_nm: str = Field(description="약 이름. 회원이 말한 그대로")
    start_ymd: date | None = Field(None, description="복용 시작일. 말하지 않았으면 오늘")
    end_ymd: date | None = Field(
        None, description='복용 종료일. "5일치"면 시작일 + 4일. 모르면 비운다'
    )
    day_times: int | None = Field(
        None, description="하루 복용 횟수. 말하지 않았으면 비운다(지어내지 않는다)"
    )


class Navigate(BaseModel):
    """본창을 그 화면으로 옮긴다. 대화창에서 할 수 있는 일이 있는 화면이면 그 도구를 먼저 쓴다.

    쓸 때: 화면을 보고 싶다는 말("가계부 보여 줘", "실종센터 가자"), 대화창 도구가 없는 일(삭제·구매·탈퇴·초대)
    쓰지 않을 때: "어떻게 해?" 사용법 질문은 search_guide. 대화창에서 할 수 있는 일("캐릭터 만들어 줘")은 그 도구
    """

    ...
```

- 이웃 도구끼리 "쓰지 않을 때"가 서로를 가리키게 쓴다(오늘 기록 ↔ 케어 완료, 처방약 ↔ 케어 항목, `navigate` ↔ `search_guide` ↔ 카드 도구).
- 헷갈리면 고르지 말고 묻게 한다. 공통 system 규칙에 "두 도구가 다 맞아 보이면 도구 없이 짧게 되묻는다"를 둔다.
- 설명만 믿지 않는다. 인자는 Python이 검증하고(2절), 쓰기 도구는 카드 확인을 거치며, 설명을 고칠 때마다 7절 평가 세트로 다시 잰다.
  평가 세트에는 이웃 도구가 헷갈리는 문항을 일부러 넣는다.

### 3-3. 3단계 — 내 데이터 읽기 (Java 내부 읽기 API 신설)

Python이 Java 내부 GET을 쿠키와 함께 불러 결과를 LLM에 돌려주고, 답변을 대화창에 스트리밍한다. 모두 백엔드 작업이다.

| 도구 | 예시 말 | 돌려받는 것 |
| --- | --- | --- |
| `get_schedules(petSn?, from, to)` | "이번 주 병원 언제야?" | 다가오는 일정·케어 예정·예방접종 예정일 |
| `get_records(petSn, kind)` | "요즘 체중 어때?" | 최근 체중·식사·배변 요약. `health-report-input`을 다시 쓸 수 있는지 확인 |
| `get_missions()` | "오늘 미션 뭐 남았어?" | 오늘의 케어미션·내 포인트 |
| `get_expense_summary(month)` | "이번 달 얼마 썼어?" | 월 지출 합계·분류별·한도 대비 |
| `get_medications(petSn)` | "지금 먹는 약 뭐야?" | 복용 중인 처방약 |
| `get_pet_profile(petSn)` | (지식 질문에 덧붙임) | 알레르기·기저질환. SEARCH 답변을 그 반려동물에 맞춘다. 개인 데이터 범위(5절)와 묶인다 |

### 3-4. 넣지 않는 것

| 기능 | 이유 |
| --- | --- |
| 삭제(일정·기록·글·반려동물), 회원 탈퇴 | 되돌릴 수 없다 → `navigate` |
| 아이템 구매·장착 | 포인트가 쓰인다 → `navigate`(입혀 보기는 `preview_items`) |
| 공동양육 초대·수락·해제 | 다른 회원에게 영향 → `navigate` |
| 검사결과지 PDF 분석 | 대화창은 PDF를 받지 않는다(SCR-AIM-013 ①·POL-006) |
| 좋아요·신고·댓글·즐겨찾기 | 대화로 할 이유가 적다. 대상 글·장소를 고르는 단계가 길다 || 회원정보(닉네임·휴대폰·비밀번호) 변경 | 본인 확인이 필요하다 → `navigate` |

## 4. 한 턴의 흐름

```
메시지 ── 룰 라우팅 ── 걸리면 지금과 같음 (이미지는 LLM이 용도 판단, 5절)
   └─ LLM(system: 규칙·안내서 목차·도구 정의, 캐시)  tool_choice auto
        ├─ 글만 → SEARCH 답변 스트리밍(의료 고지 붙임)
        ├─ 범위 밖 → 지금 OUT_OF_SCOPE 문구
        ├─ 서버 도구 → Python 실행 → tool_result → 다시 LLM (최대 2번) → 답변 스트리밍
        ├─ 이동 도구 → ROUTE (본창 이동, 지금과 같음)
        └─ 카드 도구 → 인자 검증 → SSE done.action → 턴 끝
                 React(대화창): 카드 표시 → 회원 입력·확인 → 기존 API 실행 → 결과를 카드에 표시
                                → POST .../action-result(요약 저장) → 본창에 "바뀜" 알림
```

- 서버 도구의 반복 상한은 2번이다. 넘으면 그때까지의 결과로 답한다(지연·비용 상한).
- 카드 도구의 실행 결과는 그 턴의 LLM에 돌려주지 않는다(HTTP 요청이 이미 끝남). 다음 메시지에서는 저장된 요약 한 줄이 컨텍스트다.
  저장 뒤 이어 물어보기("다음 접종 일정도 잡을까요?")가 필요하면 `action-result` 응답에 고정 문구로 붙인다(LLM 호출 없음).
- 첫 글자 10초 제한, 미완료 답변 저장(FN-AIM-002-07), 의료 고지는 지금 규칙 그대로다.
- LLM 호출 수: 지금 사용법·검색 질문은 분류 1 + 답변 1이다. 바꾼 뒤 글 답변은 1(도구 없이 바로 답), 서버 도구는 2~3, 카드·이동 도구는 1.
  도구 정의는 system과 함께 캐시한다. 도구가 20개를 넘으면 정의 토큰이 커지므로 평가로 정확도와 함께 잰다.

## 5. 결정한 것 (2026-11-05, LJS)

| 항목 | 결정 | 따라오는 일 |
| --- | --- | --- |
| 차수 | **다음 차수.** 1단계(계약 그대로)는 지금 실험 브랜치에서 평가만 먼저 한다 | 실험은 `/start`로 기획. develop 병합은 다음 차수 기능 ID가 생긴 뒤 |
| 대화창에서 끝내기 | **예외 없이 전부 대화창.** 영수증 확인(여러 마리 탭)·실종 글·돌봄 글(지도)도 대화창 카드에 넣는다. [자세히 고치기]로 본창을 여는 예외도 두지 않는다 | 프론트 작업이 가장 크다(지도·탭을 대화창 폭에). 프론트에 미리 알린다 |
| 영수증 확인 위치(SCR-AIM-013 ⑤) | **이번 차수는 10-26 확정 그대로(본창 모달).** 다음 차수에 대화창 카드로 바꾸자고 팀에 제안한다 | 다음 차수 회의 안건. 화면설계서 수정은 DMS 모음 |
| 개인 데이터 범위(3단계) | **요약만.** 날짜·이름·수치만 보내고 메모·자유 입력 글은 보내지 않는다. 의료 판단 문구는 SEARCH 규칙 그대로 | Java 내부 읽기 API 응답을 처음부터 요약 칸만으로 정한다 |
| 모델 | **Haiku 5.5로 평가 세트를 재고 판단.** 도구 고르기가 부정확하면 도구 턴만 Sonnet으로 올린다 | 7절 평가에 모델 비교 칸 |
| 첨부 이미지 용도 | **입력창 [＋] 이미지도 LLM이 용도를 판단한다**(영수증·캐릭터 사진·실종 글 사진 등). 카드 안의 [사진 고르기]는 그 카드 용도 | 아래 "이미지 용도 판단" |
| 카드 UI | **프론트가 정한다.** 기준은 대화창 폭(새 창·모바일)에 맞는지 | 없음 |

이미지 용도 판단(첨부 이미지 결정에 따라오는 것):

- SCR-AIM-013 ②(이미지 첨부 = 판정 없이 영수증, 함께 보낸 글은 분석에 쓰지 않음, 10-26 확정)를 바꾼다. ⑤와 같이 다음 차수 안건·DMS 모음.
- 판단 순서(제안): ① 함께 보낸 글로 판단한다("캐릭터 만들어 줘" + 사진 → `start_character`). 이미지를 LLM에 보내지 않는다.
  ② 글이 없거나 글로 정하지 못하면 이미지 축소본을 LLM에 보내 판단한다. ③ 그래도 모르면 "영수증인가요, 캐릭터 사진인가요?" 칩으로 묻는다.
- ②는 반려동물·영수증 사진이 Anthropic으로 간다(지금은 OCR 벤더로만 간다). 개인정보 처리방침에 넣을지 확인 필요. 이미지 입력 토큰만큼 비용이 는다.
- 2절 "규칙 앞단 유지"의 "이미지 첨부 → 영수증"은 이 결정으로 없어진다. 룰 라우팅은 그대로.

## 6. 응답 계약 변경안 (2단계부터, 백엔드·프론트와 함께)

1단계는 계약을 바꾸지 않는다. `navigate` → `intent.kind=ROUTE`, `draft_schedule`·`draft_care_item` → `REGISTER` + `done.card`,
글 답변 → `SEARCH`로 지금 값에 맞춰 내보낸다.

2단계에서 추가할 것(초안):

| 위치 | 추가 | 설명 |
| --- | --- | --- |
| `intent.kind` | `ACTION` | 카드 도구. 기존 값은 그대로 |
| `done` | `action: {tool, input, notice?}` | `tool`은 3-2 표의 도구 이름(대문자 스네이크). `input`은 Python이 검증한 인자(`petSn`·초안 칸 등). 카드 모양은 React가 `tool`로 정한다 |
| 새 API | `POST /ai/conversations/{aiCnvrsRoomSn}/action-result` `{tool, status, summary}` | `status`: 완료·취소·실패. 결과 요약을 AI 메시지로 저장. `register-result`·`receipt-result`를 이것으로 합칠지는 나중에 |
| 초안 되돌려 보내기 | `MessageSendRequest.draft` 넓히기 | 지금 등록 카드처럼 카드 되물음에 답할 때 직전 초안을 돌려보낸다. `draft`를 `{tool, input}`으로 넓힌다 |

## 7. 평가

- 도구 고르기 평가 세트: 질문 → 기대 도구·핵심 인자(`{"tool": "navigate", "scrId": "SCR-MYP-010"}`). 지금 `tests/chat/data/guide_eval*.jsonl`과 같은 형식에 `tool` 칸을 더한다.
- 세트는 안내서·도구 정의를 보지 않은 사람(또는 별도 에이전트)이 화면설계서만 보고 쓴다(`service-guide-search.md` 4-1절 방식).
- 잴 것: 도구 정확도, 인자 정확도, 쓰기 도구를 잘못 고른 수(가장 중요, 0이 목표), 범위 밖 거절, 턴당 토큰·지연. 지금 흐름과 같은 세트로 비교한다.
- 테스트(CI)는 지금처럼 가짜 Anthropic으로 도구 응답을 흉내 낸다(AGENTS.md 5번).

### 7-1. 1단계 실험 결과 (2026-11-05, 1회)

`uv run python -m scripts.tool_eval`로 쟀다(실제 Anthropic 호출). 도구 흐름은 `CHAT_TOOL_AGENT`를 켰을 때의 판정
`service.judge_tools` 그대로다. 지금 흐름의 판정은 6절 대응표로 도구 이름으로 바꿔 셌다(ROUTE → navigate,
안내서 SEARCH → search_guide, 그 밖 SEARCH → 글 답변, REGISTER → 카드 종류, FALLBACK → decline). 문항별 결과는
`.cache/tool_eval/`(git 제외)에 남는다.

세트 `tests/chat/data/tool_eval.jsonl`(44문항)은 안내서·도구 정의·라우팅 표를 보지 않은 별도 에이전트가
화면설계서(AI매니저·건강기록·마이페이지·메인)만 보고 썼다.

| 흐름 | 도구 정확 | 인자까지 정확 | 쓰기 도구 잘못 | 범위 밖 거절 | 판정 토큰 평균 입력(캐시)/출력 | 판정 지연 중앙값 |
| --- | --- | --- | --- | --- | --- | --- |
| 지금 흐름(Haiku 5.5) | 32/44 | 30/44 | 0 | 4/5 | 3,911(3,750) / 80 | 756ms |
| 도구 Haiku 5.5 | 35/44 | 34/44 | 0 | 4/5 | 7,351(7,255) / 159 | 1,127ms |
| 도구 Sonnet 5.5 | 35/44 | 34/44 | 0 | 4/5 | 7,351(7,005) / 123 | 1,565ms |

| 유형 | 문항 | 지금 | 도구 Haiku | 도구 Sonnet |
| --- | --- | --- | --- | --- |
| 사용법 | 12 | 8 | 8 | 8 |
| 이동 | 8 | 8 | 8 | 8 |
| 일정 | 5 | 3 | 4 | 4 |
| 케어 | 5 | 2 | 4 | 4 |
| 지식 | 4 | 4 | 4 | 4 |
| 범위 밖 | 4 | 4 | 4 | 4 |
| 헷갈림 | 6 | 3 | 3 | 3 |

- **도구 흐름이 지금보다 3문항 더 맞혔다.** 늘어난 곳은 등록 요청이다. 지금 흐름은 등록 정규식(부록 B)에 안 걸린 등록 요청이
  분류 LLM으로 가는데, 분류에는 REGISTER가 없어 이동이나 사용법이 된다(T24 "일정 추가", T29 "일주일에 한번 … 만들어줘",
  T30 "열흘에 한번"). 도구 흐름에서는 LLM이 `draft_*`를 고른다.
- **쓰기 도구를 잘못 고른 문항은 셋 다 0이다.** 등록이 아닌 질문에 등록 카드를 띄운 적이 없다. 일정과 케어 항목이 뒤바뀐 적도 없다.
- **Haiku와 Sonnet이 문항별로 같은 답을 냈다.** 5절 "부정확하면 도구 턴만 Sonnet"은 이 세트에서는 필요 없다. Sonnet은 더 느리다.
- **세 흐름이 같이 틀린 9문항은 LLM 앞의 룰 라우팅에서 정해진다**(LLM을 부르지 않음): T01·T03·T05·T08(사용법 질문인데
  "어디서 바꿔요"·"어디예요"·"어케 보내요"가 질문꼴 표지에 없어 바로 이동), T25·T28(등록 요청인데 "일정에 넣어줘"·
  "한달에 한번 … 등록해 줄래"가 등록 정규식에 없어 키워드 화면으로 이동), T42·T43(범위 밖·지식 질문에 화면 키워드),
  T16(정답 화면 SCR-HLT-005가 매핑표의 라우팅 대상이 아님, 세트 쪽 문제). 도구 흐름의 이점을 다 보려면 룰 앞단을 줄여야 한다.
  이 세트에 맞춰 키워드를 보강하면 시험지 맞춤이 되므로 고치지 않았다(다음 차수 판단).
- LLM이 실제로 틀린 것은 도구 흐름에서 T41("가계부는 어떻게 쓰는거야" → 범위 밖) 하나다. 지금 분류 규칙("가계부"만 있고
  반려동물·앱을 가리키는 말이 없으면 범위 밖)을 도구 system에 그대로 옮겨서 생긴 것이라 지금 흐름도 같이 틀렸다.
- 토큰·지연은 그대로 비교할 수 없다. 도구 흐름은 도구 정의와 답변 규칙이 붙어 입력이 약 3,400토큰 늘었다(두 배 가까이). 대부분 캐시 읽기라 비용은
  작다. 출력과 지연에는 글 답변 문항의 답변 생성이 들어가 있다(지금 흐름은 판정만 셈). 글 답변 문항은 도구 흐름이 LLM 호출
  1번, 지금 흐름이 2번(분류 + 답변)이다.
- 한 번만 돌렸다. `guide_eval` 때처럼 2~3문항씩 움직일 수 있다. 4문항(T03·T05·T08·T16)은 정답 화면이 매핑표의 라우팅 대상이 아닌
  상세 화면이라, 어느 흐름도 인자까지 맞힐 수 없다.

- **2회차(2026-11-05 15:30, `--no-sonnet`)**: 목차 선택을 앞에 두는 합치기(`rules.merge_guide`)와 안내서 `C-7`을 넣은 뒤 다시 쟀다.
  지금 흐름 32/44·인자 30/44·쓰기 잘못 0·범위 밖 4/5(토큰 3,929(캐시 3,769)/76, 775ms)로 1회차와 같다. 이 평가는 도구 이름과 화면만 세고
  고른 청크는 세지 않아서, 합치기의 효과는 `service-guide-search.md` 4-2절에서 본다. 도구 Haiku는 36/44·인자 34/44·쓰기 잘못 0
  (7,379(캐시 7,032)/165, 1,065ms)이다. 1회차보다 하나 늘어난 것은 T41 "가계부는 어떻게 쓰는거야"를 이번에는 `search_guide`로 고른 것이다.
  LLM이 실행마다 다르게 고르는 범위로 본다.

판단: 도구 흐름은 다음 차수에 들일 만하다. 쓰기 오작동이 없고, 등록 판정이 정규식에 덜 묶인다. 모델은 Haiku 5.5로 충분하다.
들일 때 같이 볼 것: 룰 라우팅의 질문꼴 표지와 등록 정규식을 LLM 앞에서 얼마나 걷어 낼지, 사용법 답변 품질(`--answer`로 답변 본문을 받아 사람이 채점),
글 답변 질문의 연관 바로가기(FN-AIM-002-04)가 1단계 도구 흐름에는 없다는 점(도구 없이 답하면 바로가기를 만들 근거가 없음).

## 8. 지금 코드에서 바뀌는 곳 (1단계)

2026-11-05 실험으로 구현한 것이다. `CHAT_TOOL_AGENT`(기본 `false`)를 켰을 때만 쓰이고, 끄면 지금 흐름 그대로다.

| 파일 | 바뀐 것 |
| --- | --- |
| `app/chat/tools.py` (새 파일) | 도구 5개. `navigate`·`search_guide`·`decline`은 인자 모델(`Navigate`·`SearchGuide`·`Decline`), `draft_schedule`·`draft_care_item`은 도구 목록 1차(2026-11-05, `tool-catalog.md`)부터 `app/chat/catalog.py`가 Java 도구 목록과 `data/tool_prompts.yaml`로 만든다. 설명은 yaml(3-5절). Anthropic `tools` 목록과 인자 enum(매핑표의 라우팅 가능 행 번호, 안내서 목차 번호)도 여기서 `rules.routing_table()`·`rules.guide_chunks()`로 만든다. 인자 재검증(`parse`·`route_row`·`register_values`·`guide_ids`)도 여기 있다 |
| `app/chat/clients.py` | `ToolAgent` Protocol과 `AnthropicToolAgent`(스트리밍 한 번, 첫 블록이 글이면 그대로 답변, `search_guide`면 `tool_result`를 붙여 한 번 더 부름), `tool_system`(답변 규칙·서비스 범위·화면 목록·안내서 목차, 캐시), `get_tool_agent`(설정이 꺼져 있으면 `None`). 지금 `IntentClassifier`·`RegisterExtractor`는 그대로 둔다 |
| `app/chat/service.py` | `judge_tools`·`_tool_judged`(도구 → 지금 intent 값). 이미지·초안 이어 쓰기·룰 라우팅은 그대로, 등록 정규식에 걸리면 룰 라우팅을 건너뛰고 LLM으로. `build_card`는 도구 인자를 AI 보충 값으로 받는다 |
| `app/chat/router.py` | `send_message`가 `get_tool_agent`를 받아 넘긴다 |
| `app/core/config.py`·`.env.local.example` | `chat_tool_agent`·`CHAT_TOOL_AGENT=false` |
| `app/chat/rules.py`·`app/chat/schemas.py` | 1단계 변경 없음. 2단계에 `ACTION`·`action` |
| `tests/chat/` | `test_tools.py`(도구 정의·인자 검증·도구별 SSE·Anthropic 스트리밍 흉내), `fakes.py`의 `FakeToolAgent`. 기존 테스트는 설정을 끈 채 그대로 |
| `scripts/tool_eval.py`·`tests/chat/data/tool_eval.jsonl` | 7-1절 평가 |

`service-guide-search.md`의 "M1과 목차 선택 합치기"는 1단계에서 `search_guide` 도구 인자로 바뀌므로 따로 고치지 않는다. 안내서 빈칸(대화창 영수증 task `C-7`)은 그대로 필요하다.

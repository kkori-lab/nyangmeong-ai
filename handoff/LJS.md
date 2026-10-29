# LJS 핸드오프

## 지금 하는 것
SCR-AIM-012 대화창 · 일정 생성 확인 (등록 카드) — 끝 (검증 1회차 통과, 사람 확인 2026-10-29. 카드·되물음·수정·결과 요약 저장, 반려동물 목록은 가짜)
기획 상태: 승인됨 (2026-10-29 12:08)
- 고른 이유: "다음에 할 것" 맨 위(DMS 버전 11 삭제)는 DMS 화면에서 사람이 할 일이라 건너뛰고, "다음 `/start`는 SCR-AIM-012" 줄과 대기 맨 위를 따랐다. 직전 작업(명세 갱신 FN-AIM-004, 끝) 기획은 git 이력(457f13e)에 있다.
- 출처: DMS `AI매니저_기능명세서_v0.10_20261029.xlsx` FN-AIM-012-01~18, `AI매니저_화면설계서_v0.11_20261026.html` SCR-AIM-012.
- 범위: 판정(FN-AIM-012-01, 이미 `rules.is_register_request`) 뒤 흐름. 저장(FN-AIM-012-09 등록 확정·12 서버 재검증·13 등록 규칙·15 결과 표시·17 알림)은 React가 Java 일정·케어 항목 등록 API(JAJ, 출처 'AI 생성')를 부르는 몫이라 이번 범위 밖. Python은 카드를 만들고, 결과 요약만 저장한다.
- 상태 없음 유지: 카드 초안은 Python이 저장하지 않는다. React가 가장 최근 카드·되물음의 초안(`draft`)을 다음 메시지에 돌려보낸다(수정 FN-010·되물음 답 FN-005용). 초안 없이 온 메시지는 기존 판정 그대로.
- 계약 초안 먼저 고친다(`docs/api/chat.md`, React↔Python이라 LJS 혼자 정함): MessageSendRequest에 `draft: RegisterDraft?` 추가 / MessageEvent `done`에 `card: RegisterCard?` 추가(REGISTER일 때 카드나 되물음) / 새 API `POST /ai/conversations/{aiCnvrsRoomSn}/register-result` 요청 `{result: REGISTERED|CANCELED, card: RegisterCard}` 응답 ConversationMessage / DTO RegisterDraft·RegisterCard 절 추가. `docs/api/internal.md` "Python → Java"에 미정 행 `GET /internal/ai/register-context`(쿠키 회원의 양육 반려동물 `[{petSn, petNm, careArtclNms[]}]`) 추가.
- RegisterCard 모양(필드 이름은 SCHDL·CARE_ARTCL 컬럼, 코드는 공통코드 그대로): `{cardType: SCHEDULE|CARE_ITEM|ASK, petSn?, petNm?, petChoices[{petSn,petNm}]?, missing[], schdlKndCd?(HLTG19), schdlYmd?, schdlTm?(없으면 시간 미입력 = HR_INPT_YN N), ckupTypeCd?(HLTG01), hsptlNm?(≤80), schdlNm?(≤40), memoCn?(≤500), careArtclNm?(≤40), careZoneCd?(HLTG13), careCycleCd?(HLTG15), cycleDays?(HLTC0042 직접입력일 때), lastCmptnYmd?, nxtmPrnmntYmd?, duplicateName: bool}`.
- 공통코드(백엔드 `db/20261029_insert_base_data_v0.10.sql`, 2026-10-29 확인): 일정종류 HLTG19 = HLTC0057 병원·HLTC0058 미용·목욕·HLTC0059 케어·투약·HLTC0060 기타 / 검진유형 HLTG01 = HLTC0001 정기검진·HLTC0002 예방접종·HLTC0003 질병진료·HLTC0004 검사·HLTC0005 기타 진료 / 케어구역 HLTG13 = HLTC0036 일상관리(매일)·HLTC0037 정기관리(주기) / 케어주기 HLTG15 = HLTC0038 1주·HLTC0039 2주·HLTC0040 한달·HLTC0041 1년·HLTC0042 직접입력 / 일정출처 HLTG22 HLTC0067 AI 생성(React→Java 등록 때 씀). 코드→한글 이름은 `data/register_dict.yaml`에 둔다. 규칙 매핑: "격주"·"2주마다" → HLTC0039, "매주"·"1주마다" → HLTC0038, "매달"·"한달마다" → HLTC0040, "매년"·"1년마다" → HLTC0041, 그 밖의 n주·n일·n년 → HLTC0042 + `cycleDays`. "매일" → HLTC0036(주기 없음).
- 가짜 응답: Java `register-context`는 아직 없다. `app/chat/repository.py`에 `RegisterContextRepository` Protocol과 가짜(`초코`·`뭉치` 2마리, 뭉치에 `발톱 깎기` 케어 항목)를 두고 먼저 만든다. 연결은 "다음에 할 것".
- FN-AIM-012-02 규칙 해석: `app/chat/rules.py`에 `parse_register(text, today) -> RegisterFields`(날짜: 오늘·내일·모레·이번/다음/지난주 요일·n일 후·m월 d일·d일·m/d·YYYY-MM-DD, 시간: 오전/오후 n시·n시 반·HH:MM, 주기: 매일·매주·n주마다·격주·매달·매년·n일마다, 일정 종류 키워드는 `data/register_dict.yaml`에 `schedule_types`·`checkup_types` 추가, "지난주 토요일에 했어" → 마지막으로 한 날). 다음 예정일 = 마지막으로 한 날(없으면 오늘) + 주기, 매일은 다음 날. 완료 조건 `명령:` `tests/chat/test_register_rules.py`가 화면설계서 예시 3개(오늘 2026-09-29 기준 → 10-06(화) 15:00 병원·예방접종·메이 동물병원 / 뭉치 2주·마지막 09-26·다음 10-10 / 금요일 병원 → 병원명·검진유형 빔)를 통과, `sh scripts/check.sh` 0.
- FN-AIM-012-03 AI 보조 해석: `app/chat/clients.py`에 `RegisterExtractor` Protocol, `MockRegisterExtractor`(아무 칸도 채우지 않음), `AnthropicRegisterExtractor`(Haiku 구조화 출력, 요청 문장과 오늘 날짜(KST)만 보냄). 규칙으로 필수 칸이 다 찼으면 부르지 않는다. AI가 준 날짜는 `rules`에서 다시 검증(형식·실재 날짜, 틀리면 빈 칸). 실패하면 되물음으로 넘어간다(오류 이벤트 아님). 완료 조건 `명령:` 필수 칸이 찬 입력에서 추출기가 불리지 않음, 가짜 추출기가 준 잘못된 날짜(`2026-02-30`)가 빈 칸이 됨, 추출기가 받은 입력에 반려동물 이름 목록이 없음을 테스트.
- FN-AIM-012-04 반려동물 결정: `app/chat/service.py` — 문장 속 이름 1마리 일치 → 그 반려동물 / 이름 없음 → 방의 `petSn` 태그 / 불일치·여럿·[전체] 태그 → `ASK` 카드에 `petChoices` / 1마리 회원 → 자동. 완료 조건 `명령:` 네 경우 테스트.
- FN-AIM-012-05 되물음: 빈 필수 칸(병원: 날짜·검진유형·병원명 / 그 외: 날짜·일정명 / 케어 항목: 항목명·주기)만 묻는 문구를 만들어 AI 메시지로 저장하고 `done.card`는 `ASK`(`missing` 채움). 문구는 규칙 템플릿(예: "어느 병원인가요? 검진 종류도 알려 주세요. (예: 정기검진, 예방접종)"), LLM 생성 아님. 완료 조건 `명령:` '금요일에 병원 예약 잡아줘'가 저장된 되물음과 `ASK` 카드, 이어서 `draft`와 '메이 동물병원 예방접종'을 보내면 SCHEDULE 카드.
- FN-AIM-012-06 일정 카드·FN-AIM-012-07 케어 항목 카드: 필수 칸이 다 찼을 때만 `done.card`에 SCHEDULE / 주기가 있으면 CARE_ITEM(일정 단건, FN-014). 카드 자체는 저장하지 않는다(무응답이면 아무것도 남지 않음, FN-011). 완료 조건 `명령:` '내일 3시 병원 일정 잡아줘'는 검진유형·병원명이 비어 ASK, '다음 주 화요일 오후 3시에 메이 동물병원 예방접종 잡아줘'는 SCHEDULE 카드. `화면:` Postman으로 SSE 응답의 `intent`(REGISTER) → `done.card` 확인.
- FN-AIM-012-08 같은 이름 케어 항목: 가짜 `register-context`의 `careArtclNms`에 같은 이름이 있으면 `duplicateName=true`와 안내 문구 '{반려동물명}에게 '{항목명}' 항목이 이미 있어요. 그래도 새로 등록할까요?'. 완료 조건 `명령:` '뭉치 2주마다 발톱 깎기 넣어줘' → `duplicateName=true`.
- FN-AIM-012-10 카드 수정: `draft`가 있을 때 규칙으로 뽑힌 칸이 하나라도 있으면 초안에 덮어써 새 카드를 준다(등록 동사가 없어도 됨, '4시로 바꿔줘'). 뽑힌 칸이 없으면 초안을 버리고 기존 판정. 이전 카드 비활성은 React 몫. 완료 조건 `명령:` SCHEDULE 초안 + '4시로 바꿔줘' → `schdlTm` 16:00 카드.
- FN-AIM-012-11 취소·무응답 / FN-AIM-012-16 결과 이력 저장: `register-result`가 요약을 AI 메시지로 저장 — 등록됨 "✔ 등록됨 — 초코 예방접종 · 10-06(화) 15:00", 취소됨 "취소됨 — 등록하지 않았어요."(디자인 v5). 다시 열면 이 텍스트만 남는다. `app/chat/router.py`·`service.py`. 완료 조건 `명령:` 두 결과의 저장 본문 테스트, 카드 필드 누락 400 `INVALID_REQUEST`, 남의 방 404. `화면:` Postman으로 `register-result` 호출 뒤 GET 대화에 요약 메시지가 보임.
- 마일스톤 완료 조건(mock): '내일 3시 병원 일정 잡아줘' → 되물음, 필수 칸이 찬 입력 → 카드, 결과 → 텍스트 요약 저장. 위 테스트로 덮는다.
- 하지 않는 것: FN-AIM-012-09·12·13·15·17(React→Java 등록, JAJ), FN-018(자동 생성 없음, 만들 것 없음).
- 백엔드에 물을 것: CARE_ARTCL에 직접입력(HLTC0042) 일수를 담을 컬럼이 없다(코드 설명은 "일수 별도 입력"). 카드는 `cycleDays`로 주고, 저장 방법은 JAJ 등록 API 몫으로 "다음에 할 것"에 남긴다. (정정 2026-10-29: 컬럼 `CARE_ARTCL.CYCLE_DRCT_INPT_DAY_CNT`가 이미 있다. 백엔드 LJS 확인)
새 의존성: 없음(날짜 계산은 표준 `datetime`·`zoneinfo`, LLM은 기존 `anthropic`)

## 다음에 할 것
- mock 제거, 실행은 real만(요청 2026-10-29, 범위 "실행만 real" 선택): 앱의 Mock* 클래스(제목·분류·답변·등록 추출기·OCR·캐릭터)와 `AI_MODE`를 지우고, 테스트는 `tests/`의 가짜 객체 주입만으로 실제 API를 부르지 않게 한다. AGENTS.md 5번 문구를 고치는 PR이 같이 필요하다. 기획 때 키 공유(`LLM_API_KEY`·Google Vision·이미지 생성)와 키 없는 팀원의 실행 방법을 정한다. SCR-AIM-012 `/end` 뒤 `/start`로 별도 마일스톤
- 연결 남음: `GET /internal/ai/register-context`(백엔드 LJS 구현 중, 2026-10-29). 응답 `[{petSn, petNm, careArtclNms}]`, `careArtclNms`는 JAJ 케어 항목 service가 생길 때까지 빈 배열. 백엔드 PR 번호가 오면 `FakeRegisterContextRepository`를 Java 호출로 바꾸고 `docs/api/internal.md` 미정 행을 확정으로 고친다
- JAJ 대기: React→Java 일정·케어 항목 등록 API(출처 HLTC0067, SCR-HLT-003 토탈 케어리스트 대기). 카드 `cycleDays`는 `CARE_ARTCL.CYCLE_DRCT_INPT_DAY_CNT`에 대응(요청 필드 이름은 JAJ API가 정함)
- DMS AI매니저 기능명세서 버전 11(v1.0 표기, 버전 12로 대체)은 MCP에 삭제 도구가 없어 남아 있을 수 있다. 남아 있으면 DMS 화면에서 지운다(LJS)
- DMS 명세 갱신 모음(LJS): 하나씩 올리지 않고 모아서 한 번에 버전업한다. 코드에는 이미 반영돼 있다
  - 기능명세서 FN-AIM-011: 15자 이하 첫 메시지는 그대로 제목(PR #13 추가-3)
  - 기능명세서 부록 B: 등록 판정 사전에 요일만 쓴 표현(`[월화수목금토일]요일`) 추가. 화면설계서 SCR-AIM-012 ⑦ 예시("금요일에 병원 예약 잡아줘")가 근거, `data/register_dict.yaml`
  - 기능명세서 FN-AIM-012-02: 오전·오후가 없는 1~7시는 오후로 해석, "했어" 앞 날짜는 마지막으로 한 날
  - 기능명세서 FN-AIM-012-05: 되물음 문구는 AI 생성이 아니라 빈 칸별 고정 문구(`app/chat/service.py` `ask_message`)
  - 기능명세서 FN-AIM-012-07: 다음 예정일 = 마지막으로 한 날(없으면 오늘) + 주기, 매일은 다음 날, 한달·1년은 같은 날짜(말일 넘으면 말일)
  - 화면설계서 SCR-AIM-012 ⑥: 같은 이름 안내 문구 "미결"을 FN-AIM-012-08 확정 문구로 바꾼다
  - 화면설계서 SCR-AIM-012 ⑤: 케어 항목 등록 결과 요약 예시 추가("✔ 등록됨 — 뭉치 발톱 깎기 · 2주마다 · 다음 예정일 10-10(토)")
- 프론트(LJS)가 맞출 것: ROUTE 뒤 `done.message`(저장된 이동 안내)와 화면 안내 겹침 정리, 분류 장애 `error`는 연속 실패로 세지 않고 [다시 시도]. 프론트 세션에 알림(2026-10-29)
- 백엔드에 요청(LJS 백엔드): 대화 제목 수정 내부 API. 마일스톤 "첫 답변 요약 제목"이 기다림
- 백엔드에 요청(LJS 백엔드): AI 설정값 조회 내부 API(SYS_STNG_AI_TKN_UPLMT_CNT·SYS_STNG_AI_CNVRS_TURN_CNT, 연결되면 가짜 `get_ai_settings` 교체), AI 역할 메시지 `cnvrsCn` 1,000자 상한 확대(상한 없이 저장 요청 중, 넘으면 저장 실패). `docs/api/internal.md` "미정" 행은 "설정값 조회"만 남긴다(최근 6턴은 GET 대화, 미완료 완료 처리는 불필요)
- 프론트(LJS)와 맞출 것: 메시지 API SSE 이벤트(`intent`·`delta`·`done`·`error`, `chat.md` MessageEvent), 화면 ID → 프론트 경로 변환, 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫
- 백엔드에 요청(LJS 백엔드, 영수증·캐릭터 흐름 재설계): Python이 부를 원본 이미지·RECPT·영수증 상태(AIMG01) 저장, 캐릭터 작업 생성·결과·상태 보고, (PDF를 Java에서 받는 방법이면) 첨부 조회 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- SCR-HLT-005 기획 때 정할 것: Python이 PDF를 받는 방법(React가 다시 올림 / 첨부 번호로 Java에서 받음), 인식 결과 모양(SCR-HLT-007 입력값)
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

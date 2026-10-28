# LJS 핸드오프

## 지금 하는 것
SCR-AIM-004 대화창 · 페이지 라우팅 (의도 판정) — 끝 (검증 통과 1회차, 사람 확인 2026-10-28 pytest 목록 기준. 판정 함수까지, 엔드포인트는 SCR-AIM-002)
기획 상태: 승인됨
- 고른 이유: "다음에 할 것" 맨 위가 "다음 `/start`는 대기 맨 위 SCR-AIM-004".
- 범위: 입력 한 건 → 의도 판정 함수까지. 메시지 전송 엔드포인트(`/ai/**` 메시지·스트리밍)는 SCR-AIM-002에서 만들고 이 함수를 부른다. 그래서 이번에는 API 행·DTO가 없다(`api-row.sh SCR-AIM-004` 결과 없음). 3초 유예·[취소]·본창 이동·창 닫힘(FN-AIM-004-03~07)은 프론트 몫.
- 기준: AI매니저 기능명세서 v0.9 기능 목록·부록 A(라우팅 매핑표 45행)·부록 B(등록 판정 사전), 화면설계서 v0.11 SCR-AIM-004.
- 판정 결과 모양(`app/chat/schemas.py` `Intent`): `kind` = `REGISTER`(SCR-AIM-012) / `ROUTE`(SCR-AIM-004) / `SEARCH`(SCR-AIM-002) / `FALLBACK`(SCR-AIM-005) / `RECEIPT`(SCR-AIM-013), `ROUTE`면 `scrId`·`param`(예: `?cat=hospital`, 없으면 null)·`moveType`(`PAGE` / `MODAL` — SCR-COM-009만 모달)·`scrNm`(안내 문구용 화면명). 화면 ID → 프론트 경로 변환은 프론트 몫(SCR-AIM-002 연결 때 프론트 LJS와 맞춤).
- FN-AIM-004-09 매핑표 관리: `data/routing.yaml`에 부록 A를 옮긴다(No·구분·대상 화면·화면 ID·파라미터·키워드·이동 방식, 버전 `v0.9` 표기). '라우팅 대상 아님'·'제외'·'보류' 행은 `routable: false`로 남겨 키워드 없이 둔다. 부록 B는 `data/register_dict.yaml`(등록 동사·날짜·시간·주기 표현). 로드는 `app/chat/rules.py`에서 한 번(`lru_cache`).
  - 해석 하나: 부록 A No.3(플레이스, `?cat=…` "아래 행 참조")의 미용·용품·호텔·동반은 No.17~20과 길이가 같아 위쪽 행 우선 규칙이면 파라미터 없는 No.3이 이긴다. yaml에서 No.3 키워드를 '플레이스'만 두고 나머지는 No.17~20 탭으로 가게 한다(결과는 매핑표 의도와 같음). 명세는 고치지 않는다.
  - 완료 조건 `명령:` 매핑표 로드 테스트 — No 45개, 라우팅 가능 행의 화면 ID가 `SCR-` 형식, 대표 칩 7행이 모두 있음, 결번(SCR-HLT-000·001 등)·SCR-AIM-0xx가 라우팅 대상에 없음.
- FN-AIM-012-01 등록 요청 판정 + FN-AIM-004-13 등록 분기 우선: `rules.py` `is_register_request(text)` — 공백을 뺀 문장에 등록 동사(잡아·등록해·넣어·추가해·예약해·만들어 + 줘/주세요 계열)와 날짜·시간·주기 표현이 둘 다 있으면 참.
  - 완료 조건 `명령:` "내일 3시 병원 일정 잡아줘"·"다음 주 화요일 병원 일정 잡아줘"·"매일 산책 추가해 주세요"·"2주마다 구충 넣어줘" → `REGISTER`, "일정 등록할래"(날짜 없음) → `ROUTE` SCR-HLT-003, "내일 병원"(동사 없음) → 등록 아님.
- FN-AIM-004-01 룰 기반 매칭 + FN-AIM-004-10 파라미터: `rules.py` `match_route(text)` — 공백을 뺀 문장·키워드로 포함 여부를 보고, 여러 개면 가장 긴 키워드, 길이가 같으면 매핑표 위쪽 행.
  - 완료 조건 `명령:` "병원 찾아줘" → SCR-HOS-001 `?cat=hospital`, "근처 애견미용실" → SCR-HOS-001 `?cat=beauty`, "이번 달 병원비 얼마 썼어" → SCR-MYP-030(병원비가 병원보다 김), "채팅 보여줘" → SCR-COM-009 `MODAL`, "알림 꺼줘" → SCR-COM-008, 화면설계서 예시 11개 전부 기대 화면.
- FN-AIM-004-11 데이터 컨텍스트 미수용: 반려동물 이름 등은 해석하지 않고 화면 단위로만 매칭.
  - 완료 조건 `명령:` "초코 체중 그래프 보여줘" → SCR-HLT-002, 파라미터 없음.
- FN-AIM-004-08 라우팅 대상 범위: 매핑표의 라우팅 가능 행 전체가 대상(칩 7종 한정 아님).
  - 완료 조건 `명령:` 매핑표의 라우팅 가능 행마다 첫 키워드를 넣으면 그 행 화면이 나온다(표 전체 반복 테스트, 최장 일치로 다른 행이 이기는 키워드는 예외 목록에 이유와 함께).
- FN-AIM-004-02 AI 의도 분류: `app/chat/clients.py`에 `IntentClassifier` Protocol + `MockIntentClassifier`. 룰 매칭이 실패한 입력에만 부른다. 결과는 `ROUTE`(매핑표의 라우팅 가능 화면 ID만 인정, 아니면 버림) / `SEARCH` / `UNKNOWN`. mock은 물음표·의문 표현(뭐·왜·어떻게·알려줘 등)이 있으면 `SEARCH`, 아니면 `UNKNOWN`. real은 Anthropic(키 받은 뒤, "다음에 할 것"). `get_intent_classifier`는 제목 생성기와 같은 방식(real이면 `NotImplementedError`).
  - 완료 조건 `명령:` mock에서 "강아지가 포도 먹어도 돼?" → `SEARCH`, "ㅁㄴㅇㄹ" → `FALLBACK`. 가짜 분류기가 매핑표에 없는 화면 ID를 주면 `FALLBACK`.
- FN-AIM-004-12 매칭 실패 분기: 등록·룰·AI 모두 판단 못 하면 `FALLBACK`.
- FN-AIM-001-05 의도 분기 처리: `app/chat/service.py` `judge_intent(text, has_image, classifier)` — 이미지가 있으면 바로 `RECEIPT`, 아니면 ① 등록 → ② 룰 라우팅 → ③ AI 분류(`ROUTE`/`SEARCH`) → ④ `FALLBACK`. AI 분류는 ①②가 실패한 경우에만 부른다.
  - 완료 조건 `명령:` 순서 테스트 — 등록과 라우팅 키워드가 함께 있으면 `REGISTER`, 룰이 맞으면 분류기를 부르지 않음(호출 횟수 0), 이미지 첨부면 문장과 관계없이 `RECEIPT`.
- 테스트: `tests/chat/test_intent.py`(판정 순서·예시 입력), `tests/chat/test_routing_table.py`(매핑표 로드·표 전체 반복).
- 완료 조건 `화면:` 엔드포인트가 없어 Postman 대신 README "사람 확인" 6번 방식: `uv run python -m pytest tests/chat/test_intent.py -v`의 예시 입력·결과 목록을 사람이 훑어본다(부록 A·B와 다른 판정이 있는지).
- 공통 완료 조건 `명령:` `sh scripts/check.sh` 종료 코드 0.
새 의존성: `pyyaml` 6.0.3 (`uv add pyyaml`). 매핑표·사전을 `data/*.yaml`로 두는 규칙(`architecture.md`) 때문. 이미 `uvicorn[standard]`를 통해 `uv.lock`에 같은 버전이 있어 새로 내려받는 것은 없고, 직접 의존성으로 명시만 한다.

## 다음에 할 것
- 다음 `/start`는 대기 맨 위 SCR-AIM-005. 새 대기 마일스톤 4개(SCR-AIM-008 전환·SCR-AIM-013·SCR-MYP-010 전환·SCR-HLT-005)는 맨 뒤에 둠
- 연결 남음: SCR-AIM-004 FN-AIM-004-02 AI 의도 분류 real 클라이언트 (Anthropic 키·모델 정한 뒤, LJS). 판정 함수 `judge_intent`는 SCR-AIM-002 메시지 전송에서 부른다. 화면 ID → 프론트 경로 변환은 그때 프론트 LJS와 맞춘다
- 백엔드에 요청(LJS 백엔드, 영수증·캐릭터 흐름 재설계): Python이 부를 원본 이미지·RECPT·영수증 상태(AIMG01) 저장, 캐릭터 작업 생성·결과·상태 보고, (PDF를 Java에서 받는 방법이면) 첨부 조회 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- SCR-HLT-005 기획 때 정할 것: Python이 PDF를 받는 방법(React가 다시 올림 / 첨부 번호로 Java에서 받음), 인식 결과 모양(SCR-HLT-007 입력값)
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-AIM-011 FN-AIM-011-11 제목 생성 real 클라이언트 (LLM 제공자 Anthropic 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`), `verify-collect.sh:37-38` `case` 문법
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

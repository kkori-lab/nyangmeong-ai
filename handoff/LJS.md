# LJS 핸드오프

## 지금 하는 것
LLM real 연결 (SCR-AIM-011 FN-AIM-011-11 제목 생성 · SCR-AIM-004 FN-AIM-004-02 의도 분류) — 끝 (검증 통과, 사람 확인 2026-10-28. 들어간 SDK는 `anthropic` 2.3.0)
기획 상태: 승인됨
- 고른 이유: "다음에 할 것" 맨 위가 LLM real 연결(2026-10-28 사람 요청). 두 화면 절은 이미 `끝`이고 이 작업의 마일스톤 절이 없어 `milestone-status.sh`는 돌리지 않았다(연결 작업, 상태 바꿀 절 없음).
- 범위: `app/chat/clients.py`의 real 분기 두 곳(지금 `NotImplementedError`)을 Anthropic 클라이언트로 채운다. mock 동작·`judge_intent`·`create_conversation` 흐름은 그대로. OCR·캐릭터 real은 이번 범위 밖(계속 `NotImplementedError`이라 `AI_MODE=real`이면 그 기능은 아직 500).
- 기준: AI매니저 기능명세서 v0.9 FN-AIM-011-11(첫 메시지로 1회 생성, 200자 서버 검증), FN-AIM-011-16·POL-006(반려동물 기록은 AI API에 보내지 않음 — 사용자가 입력한 문장만 보낸다), FN-AIM-004-02(룰 매칭 실패 입력에만 보조 분류), FN-AIM-004-12(판단 못 하면 폴백). 부를 남의 API 없음(Java 계약 변경 없음).
- 설정(`app/core/config.py`): 키 설정(`LLM_API_KEY`, SecretStr, 기본 빈 값), `llm_model: str = "claude-haiku-5-5"`(`LLM_MODEL`), `llm_timeout_sec: float = 10.0`(`LLM_TIMEOUT_SEC`). `.env.local.example`에 `LLM_MODEL`·`LLM_TIMEOUT_SEC` 추가(값 없는 키 목록만, `docs/convention/config.md` 규칙). real인데 키가 비면 의존성 함수에서 명확한 오류.
- 모델: 기본 `claude-haiku-5-5`(2026-10-28 사람 결정 "일단 하이쿠"), `output_config.effort="low"`(분류·짧은 생성). 바꿀 때는 `LLM_MODEL`만 고친다.
- 공통: `clients.py`에 `AsyncAnthropic(api_key, timeout=llm_timeout_sec, max_retries=1)`를 설정당 한 번 만드는 `get_anthropic_client`. 실패(시간 초과·API 오류·`stop_reason="refusal"`)는 요청을 깨지 않고 아래 대체값으로 간다. 로그는 길이·소요 시간·실패 종류만(원문 금지, architecture.md "로그와 예외").
- FN-AIM-011-11 제목 생성: `AnthropicTitleGenerator.generate(first_message)` — 시스템 프롬프트 "대화 제목을 한국어 한 줄(30자 안팎)로, 따옴표·마침표 없이" + 사용자 메시지에 첫 메시지만. 응답 text를 한 줄로 정리해 돌려주고, 200자 자르기·빈 값 `DEFAULT_TITLE`은 기존 `service.create_conversation`이 한다. 실패하면 mock과 같은 첫 메시지 앞 30자(대화 생성을 막지 않는다).
  - 완료 조건 `명령:` 가짜 Anthropic 응답(httpx2 MockTransport를 단 `AsyncAnthropic`)으로: 요청 본문의 `model`·`system`·`messages`에 첫 메시지 원문만 있음, 응답 text가 제목으로 나옴, 줄바꿈·따옴표 정리, 500·시간 초과·refusal이면 앞 30자 대체. real 모드 키 빈 값이면 오류.
- FN-AIM-004-02 의도 분류: `AnthropicIntentClassifier.classify(text)` — `messages.parse(output_format=...)` 구조화 출력 `{kind: ROUTE|SEARCH|UNKNOWN, route_num: int|null}`. 시스템 프롬프트에 `rules.routing_table()`의 routable 행(num·화면명·키워드)을 넣는다(고정 내용이라 앞에 두고 매 요청 같게). `route_num`을 행으로 바꿔 `Classified(ROUTE, scr_id, param)`, 없는 번호·`ROUTE`인데 번호 없음은 `UNKNOWN`. 실패하면 `UNKNOWN`(→ 기존 흐름대로 `FALLBACK`). 등록 판정은 룰이 먼저 하므로 분류 대상에 없다.
  - 완료 조건 `명령:` 가짜 응답으로: SEARCH·ROUTE(num → 매핑표의 scr_id·param)·UNKNOWN 각각, 없는 num → UNKNOWN, 500·시간 초과·refusal → UNKNOWN, 시스템 프롬프트에 routable 행만 들어감.
- 테스트: `tests/chat/test_llm_clients.py`(실제 API를 부르지 않음, `AGENTS.md` 5번). 기존 테스트는 mock 그대로.
- 완료 조건 `화면:` `scripts/llm_smoke.py`(사람만 돌리는 확인용, pytest가 모으지 않음): `.env.local`의 키로 제목 2건·분류 4건("병원 찾아줘 근처에"처럼 룰에 안 걸리는 이동·"강아지 포도 먹어도 돼?"·"ㅁㄴㅇㄹ"·"바보야")을 실제로 불러 결과와 소요 시간을 출력. 이어서 `AI_MODE=real` + 가짜 Java로 서버를 띄워 Postman `POST /ai/conversations` 응답의 제목이 LLM 생성인지 본다(README "사람 확인").
- 공통 완료 조건 `명령:` `sh scripts/check.sh` 종료 코드 0.
- 다음에 할 것에 남길 것: "연결 남음" 두 줄(제목 생성·의도 분류) 삭제. SCR-AIM-002 검색 응답에서 같은 `get_anthropic_client` 재사용.
새 의존성: `anthropic` 1.x(`uv add anthropic`, 공식 SDK. 1.x는 이 저장소와 같은 `httpx2` 위에서 돈다). 이유: Anthropic API 호출.

## 다음에 할 것
- 다음 `/start`는 대기 맨 위 SCR-AIM-002(검색 응답은 `get_anthropic_client`·`LLM_MODEL` 재사용, Java "미정" API 3개 요청). 새 대기 마일스톤 4개(SCR-AIM-008 전환·SCR-AIM-013·SCR-MYP-010 전환·SCR-HLT-005)는 맨 뒤에 둠
- 공용 하네스 PR로 따로: `scripts/llm_smoke.py`(LLM 실제 호출 사람 확인용, 이번 커밋에서 뺌)
- SCR-AIM-002 메시지 전송에서 `judge_intent`를 부르고(화면 ID → 프론트 경로 변환은 그때 프론트 LJS와 맞춘다), 판정이 `FALLBACK`이면 `reply_fallback`(SCR-AIM-005)을 부르고 응답에 판정·저장된 AI 메시지를 담는다. 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫. 프론트 연결은 엔드포인트와 한 번에
- 백엔드에 요청(LJS 백엔드, 영수증·캐릭터 흐름 재설계): Python이 부를 원본 이미지·RECPT·영수증 상태(AIMG01) 저장, 캐릭터 작업 생성·결과·상태 보고, (PDF를 Java에서 받는 방법이면) 첨부 조회 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- SCR-HLT-005 기획 때 정할 것: Python이 PDF를 받는 방법(React가 다시 올림 / 첨부 번호로 Java에서 받음), 인식 결과 모양(SCR-HLT-007 입력값)
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`), `verify-collect.sh:37-38` `case` 문법
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

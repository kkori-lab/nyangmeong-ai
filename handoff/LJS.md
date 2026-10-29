# LJS 핸드오프

## 지금 하는 것
SCR-AIM-011·008·MYP-010 공통 · mock 제거, 실행은 real만 (추가 요청) — 끝 (검증 1회차 통과, 사람 확인 2026-10-29. Mock·AI_MODE 삭제, 키 없으면 502, register-context Java 연결)
기획 상태: 승인됨 (2026-10-29, register-context 연결 포함)
- 고른 이유: "다음에 할 것" 맨 위(요청 2026-10-29, 범위 "실행만 real" 선택). 명세 밖 추가 요청이라 기능 ID·DMS 문서가 없고, 마일스톤 절을 새로 만들었다.
- 범위: 앱의 Mock* 6개(`MockTitleGenerator`·`MockIntentClassifier`·`MockAnswerGenerator`·`MockRegisterExtractor`·`MockOcrClient`·`MockCharacterClient`)와 `AiMode`·`AI_MODE`를 지운다. 계약(`ApiResponse`·오류 코드·SSE 이벤트)은 바꾸지 않는다. 키 없음은 기존 502 `EXTERNAL_API_ERROR`로 답한다.
- 설정(`app/core/config.py`·`app/core/health.py`): `AiMode`·`ai_mode` 삭제. `/health`는 `{"status": "ok"}`만(`aiMode` 삭제, `docs/api/`에 없는 값이라 계약 변경 아님). 완료 조건 `명령:` `grep -rnE "AI_MODE|AiMode|ai_mode|class Mock" app scripts .env.local.example .github` 결과 없음.
- 대화창 클라이언트(`app/chat/clients.py`): Mock 4개 삭제, `get_*`는 Anthropic 구현만 돌려준다. `LLM_API_KEY`가 비면 `get_anthropic_client`가 `RuntimeError`(지금 500) 대신 `AppError("EXTERNAL_API_ERROR", 502, ...)`를 내고 로그에 빠진 키 이름만 남긴다(값은 남기지 않음). 인증 의존성이 먼저 돌게 해 쿠키 없는 요청은 키와 관계없이 401. 완료 조건 `명령:` 키 없이 방 생성·메시지 전송 → 502 `EXTERNAL_API_ERROR`, 쿠키 없이 → 401.
- OCR·캐릭터(`app/ocr/clients.py`·`app/character/clients.py`): Mock 삭제. real 클라이언트는 아직 없으므로 `get_*`가 `NotImplementedError`(500) 대신 502 `EXTERNAL_API_ERROR`를 내고 "연결 전" 로그를 남긴다. 연결은 기존 "연결 남음"(Google Vision·OpenAI 이미지) 그대로. 규격 PNG 만드는 코드(`_mock_png`)는 테스트 가짜로 옮긴다. 완료 조건 `명령:` 두 API가 502.
- 테스트(`tests/`): 새 `tests/conftest.py` autouse 픽스처가 `LLM_API_KEY`·`OPENAI_API_KEY`·`GOOGLE_APPLICATION_CREDENTIALS`를 빈 값으로 두고 `get_settings.cache_clear()`. 가짜를 안 끼운 테스트는 실제 API 대신 502로 실패하므로 각자 PC의 키가 테스트에 새지 않는다. 지운 Mock의 동작은 `tests/chat/fakes.py`(`FakeTitleGenerator`·`FakeIntentClassifier`·`FakeAnswerGenerator`·`FakeRegisterExtractor`, 동작은 지금 Mock과 같음)로 옮기고 `tests/chat/conftest.py` `client`가 `dependency_overrides`로 끼운다. OCR·캐릭터 테스트도 가짜를 끼운다. `monkeypatch.setenv("AI_MODE", ...)` 전부 삭제. `test_llm_clients.py`의 mock 선택 테스트는 "키 없으면 502" 테스트로 바꾸고, `test_health.py` 기대값은 `{"status": "ok"}`로 바꾼다(기능 변경에 따른 기대값 변경). 완료 조건 `명령:` 키가 빈 상태로 `sh scripts/check.sh` 0, 테스트 수가 줄지 않음(mock 선택 테스트 2개는 키 없음 테스트로 대체).
- 규칙 문서(같은 PR): `AGENTS.md` 5번 → "**테스트에서 외부 AI API를 부르지 않는다.** 앱에는 실제 클라이언트만 두고, 테스트는 `tests/`의 가짜 객체를 끼운다. 키가 없는 CI에서도 통과해야 한다." / `docs/convention/test.md` 8줄·`config.md` 8줄·`architecture.md` `clients.py` 행·`docs/api/internal.md` 80줄(mock 문단 삭제)·`README.md` 23·43·57줄·`.claude/skills/verify/SKILL.md`와 `.agents/skills/verify/SKILL.md` 50줄·`.github/workflows/build.yml` 1줄 주석. 완료 조건 `명령:` `grep -rn "AI_MODE" --exclude-dir=.venv --exclude-dir=handoff .` 결과 없음.
- 설정 파일·점검(`.env.local.example`·`scripts/doctor.py`): `AI_MODE` 줄 삭제. doctor는 모드 판단 없이 `LLM_API_KEY`가 비면 할 일("디스코드의 .env.local에서 받기, 없으면 AI 대화는 502")로, Vision·이미지 키는 연결 전이라 [비움] 표시만.
- 키 공유와 키 없는 팀원(정할 것, 제안): `LLM_API_KEY`는 팀 키 하나를 디스코드 `.env.local`로 공유(기존 방식). Vision·OpenAI 키는 받으면 같은 방식. 키 없는 팀원은 서버를 띄울 수 있고 `/health`·`/ai/me`·대화 목록·조회는 되며, LLM이 필요한 API만 502다. 테스트는 키 없이 돈다. 프론트는 키 있는 사람의 서버 대신 각자 키를 받아 띄운다.
- `화면:` `LLM_API_KEY`를 비우고 띄워 Postman으로 방 생성 → 502 `EXTERNAL_API_ERROR`, `GET /health` → `{"status":"ok"}`. 키를 넣고 다시 띄워 방 생성·메시지 전송이 실제 답변으로 오는지(키가 있을 때만).
- register-context Java 연결(승인 때 사람 요청으로 포함, 2026-10-29. 백엔드 #54 develop 병합): `app/chat/repository.py` `FakeRegisterContextRepository`를 지우고 Java `GET /internal/ai/register-context`를 부르는 구현으로 바꾼다(브라우저 `Cookie` 그대로, `X-Requested-With: XMLHttpRequest`, 대화 저장 API와 같은 `app/core/backend.py` 호출 방식. 응답 `data [{petSn: Long, petNm: String, careArtclNms: [String]}]`, `careArtclNms`는 당분간 빈 배열). Java 4xx 그대로·연결 실패 502는 기존 규칙. 가짜(`초코`·`뭉치`)는 `tests/chat/`로 옮겨 등록 테스트가 그대로 돈다. `docs/api/internal.md` 미정 행을 확정(백엔드 #54)으로 고친다. 완료 조건 `명령:` 가짜 Java(`MockTransport`)가 받은 요청의 경로·쿠키·`X-Requested-With` 확인, 응답이 등록 카드 반려동물 결정에 쓰임, Java 오류(4xx·연결 실패)면 SSE `error` `EXTERNAL_API_ERROR`(스트림 시작 뒤라 Java 본문을 그대로 전달할 수 없음). `화면:` 로컬 Java develop을 띄우고 Postman으로 등록 문장을 보내 `done.card`의 반려동물이 내 실제 반려동물인지.
- 하지 않는 것: OCR·캐릭터 real 클라이언트(각 마일스톤), Java 가짜 `get_ai_settings`(설정값 조회 API가 아직 없음).
새 의존성: 없음

## 다음에 할 것
- 공용 하네스 PR(LJS, mock 제거 마일스톤에서 뺀 것): `.claude/skills/verify/SKILL.md`·`.agents/skills/verify/SKILL.md` 50줄(`AI_MODE` 대신 필요한 키 이름·키 비우고 띄우기), `scripts/doctor.py`(`AI_MODE` 점검 삭제, `LLM_API_KEY` 비면 할 일). 커밋하지 않은 채 작업 트리에 있다. `.github/workflows/build.yml`(깃 플로우 빌드)은 LJS가 따로 고친다
- 연결 남음(JAJ): Java register-context의 `careArtclNms`가 빈 배열이라 같은 이름 케어 항목 안내(FN-AIM-012-08)가 실제로는 뜨지 않는다. JAJ 케어 항목 service가 생기면 Python은 고칠 것 없음
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

# LJS 핸드오프

## 지금 하는 것
SCR-AIM-002 대화창 · 검색 질문/응답 · 연결 끊김 문서 정정과 회귀 테스트 — 끝 (검증 통과 1회차, 사람 확인 2026-10-29. 연결 끊김 문구 두 곳 정정, 끊겨도 완료 저장 회귀 테스트 추가). 프론트 사람 확인 추가 요청 3건(아래 표)도 끝, check.sh 통과·사람 확인 2026-10-29, PR #13 병합
기획 상태: 승인됨 (2026-10-28 23:56)
결정: 추천안대로 (질문 아님. 제목의 "질문" 글자를 impl-check.sh가 질문으로 읽음)
- 고른 이유: "다음에 할 것" 맨 위. 직전 SCR-AIM-002(끝, 사람 확인 2026-10-28)의 구현 중 조정 "연결 끊김은 끝까지 생성·완료 저장"(`docs/convention/architecture.md` 22줄 "질문 한 번의 순서")이 문서 두 곳에 반영되지 않았고 테스트가 없다. 기능 변경 없음, 이전 기획은 git 이력(8fd1e31)에 있다.
  - 결정: 추천안대로 (질문 아님. architecture.md 절 이름의 "질문" 글자를 impl-check.sh가 질문으로 읽음)
- 범위 밖: `app/` 코드는 바꾸지 않는다(이미 `app/chat/service.py` `answer_turn`이 `asyncio.create_task`로 생성을 떼어 둠). 새 API·DTO 변경 없음.
- FN-AIM-002-07 문서: `docs/api/chat.md` 메시지 API 행의 "첫 글자 뒤 60초 초과·오류·연결 끊김은 부분 답변을 미완료" → "첫 글자 뒤 60초 초과·오류는 부분 답변을 미완료(`cmptnYn=false`)로 저장. 연결이 끊겨도 생성·저장은 끝까지 한다(완료로 저장)". MessageEvent `done` 설명은 이미 "(60초 초과·도중 오류)"라 그대로.
- FN-AIM-002-07 마일스톤: `milestones/LJS.md` SCR-AIM-002 완료 조건의 "전체 60초 초과·연결 끊김은 부분 답변을 미완료" → "전체 60초 초과·도중 오류는 부분 답변을 미완료(…)로 저장하고 이후 컨텍스트에서 빼며, 연결이 끊겨도 답변을 끝까지 만들어 완료로 저장한다".
- FN-AIM-002-07 테스트: `tests/chat/test_messages.py`에 `test_연결이_끊겨도_답변을_끝까지_만들어_완료로_저장` 추가. HTTP `TestClient`는 스트림 중간 끊김을 흉내 내기 어려워 서비스 수준에서 부른다: `JavaConversationRepository`(가짜 Java `MockTransport`) + 조각 사이에 잠깐 쉬는 가짜 답변 생성기로 `service.answer_turn`을 만들고 → 첫 이벤트(`intent`)만 받고 `aclose()`(연결 끊김) → 떼어 둔 작업(`service._running`)이 끝나길 기다린 뒤 → 저장된 AI 메시지가 전체 답변 + 고지, `cmptnYn` true인지 본다. 생성이 스트림과 함께 취소되면(조정 전 설계) 저장이 없거나 미완료라 실패한다. pytest-asyncio가 없어 테스트 안에서 `asyncio.run`을 쓴다.
- 완료 조건 `명령:` 위 테스트 통과, `sh scripts/check.sh` 종료 코드 0.
- 완료 조건 `화면:` 없음(동작 변경 없음. 문서 두 곳의 문구를 diff로 확인).
- 하네스(보고만, 이번에 고치지 않음): `scripts/milestone-status.sh`가 macOS BSD `sed -i`에서 실패해도 종료 코드 0이다(이번 세션 실측: "invalid command code m" 출력 뒤 exit 0). 이미 "다음에 할 것"의 하네스 수정 PR 후보에 BSD `sed` 항목이 있어 거기에 "실패해도 0" 을 덧붙인다.
새 의존성: 없음

### 추가 요청
| 번호 | 바꿀 파일 | 완료 조건 | 요청 |
| --- | --- | --- | --- |
| 추가-1 | `app/chat/service.py`, `docs/api/chat.md`, `tests/chat/test_messages.py` | 명령: ROUTE 판정이면 이동 안내가 AI 메시지로 저장되고 `done.message`로 온다 | 요청 2026-10-29 10:42 "프론트 사람 확인 요청: ROUTE 이동 안내를 저장해 다시 열어도 답이 남게(저장한다)" |
| 추가-2 | `app/chat/clients.py`, `app/chat/service.py`, `tests/chat/test_messages.py`, `tests/chat/test_llm_clients.py` | 명령: 룰에 안 걸린 문장에서 분류 LLM이 실패하면 `error` 이벤트, 폴백 저장 없음. 룰 라우팅은 LLM 오류여도 ROUTE | 요청 2026-10-29 10:42 "분류 단계 LLM 장애는 폴백이 아니라 error 이벤트로" |
| 추가-3 | `app/chat/clients.py`, `tests/chat/test_llm_clients.py` | 명령: 15자 이하 첫 메시지는 LLM을 부르지 않고 그대로 제목이 된다 | 요청 2026-10-29 "'가계부' 한 단어가 '가계부 작성 방법' 제목이 됨. 짧은 입력은 그대로 제목으로(답변 요약 제목은 마일스톤으로)" |

## 다음에 할 것
- 명세 갱신(LJS, DMS): 기능명세서 FN-AIM-004에 ROUTE 이동 안내 저장("<화면명>(으)로 이동할게요"), 분류 LLM 장애는 error 이벤트(폴백 아님)를 반영
- 프론트(LJS)가 맞출 것: ROUTE 뒤 `done.message`(저장된 이동 안내)와 화면 안내 겹침 정리, 분류 장애 `error`는 연속 실패로 세지 않고 [다시 시도]. 프론트 세션에 알림(2026-10-29)
- 백엔드에 요청(LJS 백엔드): 대화 제목 수정 내부 API. 마일스톤 "첫 답변 요약 제목"이 기다림
- 다음 `/start`는 대기 맨 위 SCR-AIM-012(등록 카드). 메시지 API의 REGISTER 판정 뒤 흐름을 잇는다
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

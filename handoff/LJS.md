# LJS 핸드오프

## 지금 하는 것
SCR-AIM-005 대화창 · 매칭 실패 폴백 — 끝 (검증 통과 1회차, 사람 확인 2026-10-28 pytest 목록 기준. 폴백 문구 저장 함수까지, 엔드포인트는 SCR-AIM-002)
기획 상태: 승인됨
- 고른 이유: "다음에 할 것" 맨 위가 "다음 `/start`는 대기 맨 위 SCR-AIM-005".
- 범위: 판정 결과가 `FALLBACK`일 때 안내 문구를 AI 역할 메시지로 Java에 저장하고 응답 모양을 만드는 함수까지. 메시지 전송 엔드포인트(사용자 메시지 저장·`judge_intent` 호출·응답)는 SCR-AIM-002에서 만들고 이 함수를 부른다. 칩 재노출·연속 실패 카운트·FAQ 버튼·카운트 초기화(FN-AIM-005-03~06)는 브라우저 sessionStorage 기준이라 프론트 몫(마일스톤에도 없음).
- 기준: AI매니저 기능명세서 v0.9 FN-AIM-005-01~07, 화면설계서 v0.11 SCR-AIM-005. `api-row.sh SCR-AIM-005` 결과 없음. 부를 API는 이미 확정된 Java 내부 API `POST /internal/ai/conversations/{aiCnvrsRoomSn}/messages`(백엔드 LJS, `docs/api/internal.md`), 요청 `{roleCd(AIMC0024 사용자·AIMC0025 AI), cnvrsCn(1~1,000), cmptnYn: Boolean?(기본 true)}`, 201 ConversationMessageResponse. 그 행의 "Python은 아직 쓰지 않음(SCR-AIM-002·012에서 사용)"을 "SCR-AIM-005 폴백 문구 저장에서 사용(SCR-AIM-002·012도 사용 예정)"으로 고친다(계약은 그대로, 사용처 표기만).
- FN-AIM-005-01 매칭 실패 판정: 이미 `judge_intent`의 ④ `FALLBACK`(SCR-AIM-004에서 구현). 이번에는 바꾸지 않고 테스트로만 묶는다.
  - 완료 조건 `명령:` 기존 `tests/chat/test_intent.py`의 "ㅁㄴㅇㄹ" → `FALLBACK`이 그대로 통과.
- FN-AIM-005-02 실패 안내 표출: `app/chat/repository.py` `ConversationRepository`에 `add_message(room_sn, role_cd, cn)` 추가, `JavaConversationRepository`가 위 POST를 부르고 `ConversationMessage`로 파싱(응답의 `cmptnYn` 등 모르는 필드는 무시). `app/chat/service.py`에 `FALLBACK_MESSAGE`(화면설계서 SCR-AIM-005 ② 실패 안내 문구 그대로, "…을 이해하지 못했어요. 다시 입력하거나 아래에서 선택해 주세요.")와 `reply_fallback(repo, room_sn) -> ConversationMessage` — 실패 사유는 묻지 않고 고정 문구를 `AIMC0025`로 저장해 저장된 메시지를 돌려준다. 역할 코드는 `schemas.py`에 `ROLE_USER = "AIMC0024"`·`ROLE_AI = "AIMC0025"` 상수로 둔다. "찾으시는 내용이 없다면…" FAQ 문구는 2회 연속 실패 때만 프론트가 붙이므로 저장하지 않는다.
  - 완료 조건 `명령:` 가짜 저장소로 `reply_fallback` 호출 시 `add_message`가 `(room_sn, "AIMC0025", FALLBACK_MESSAGE)`로 한 번 불림. `JavaConversationRepository.add_message`가 httpx MockTransport에서 경로·메서드·본문 `{roleCd, cnvrsCn}`·`X-Requested-With`·Cookie 전달을 지키고, Java 404·401을 그대로 전달(기존 대화 저장 테스트 방식).
- FN-AIM-005-07 부적절 입력 처리: 별도 필터 없이 같은 폴백. 룰·분류에 걸리지 않는 욕설은 `FALLBACK`.
  - 완료 조건 `명령:` mock 분류기에서 욕설 예시(예: "바보야", "꺼져") → `FALLBACK`, 그 결과로 `reply_fallback`이 같은 문구를 저장.
- 테스트: `tests/chat/test_fallback.py`(판정·문구 저장·부적절 입력), Java 호출은 `tests/chat/test_conversations.py`에 `add_message` 케이스 추가.
- 완료 조건 `화면:` 엔드포인트가 없어 Postman 대신 README "사람 확인" 6번 방식: `uv run python -m pytest tests/chat/test_fallback.py -v` 목록을 사람이 훑어본다(문구가 화면설계서와 같은지, 부적절 입력이 같은 폴백인지).
- 공통 완료 조건 `명령:` `sh scripts/check.sh` 종료 코드 0.
- 다음에 할 것에 남길 것: SCR-AIM-002 메시지 전송 엔드포인트에서 `FALLBACK`이면 `reply_fallback`을 부르고 응답에 `intent`·저장된 AI 메시지를 담는다.
새 의존성: 없음

## 다음에 할 것
- 다음 `/start`는 LLM real 연결(2026-10-28 사람 요청 "오늘 LLM까지 붙여보자"): SCR-AIM-011 FN-AIM-011-11 제목 생성과 SCR-AIM-004 FN-AIM-004-02 의도 분류의 Anthropic real 클라이언트. 키는 LJS가 직접 발급해 `.env.local` `LLM_API_KEY`에 넣는다. 모델은 기획 때 정한다. 그다음 대기 맨 위 SCR-AIM-002(mock 먼저, Java "미정" API 3개 요청). 새 대기 마일스톤 4개(SCR-AIM-008 전환·SCR-AIM-013·SCR-MYP-010 전환·SCR-HLT-005)는 맨 뒤에 둠
- SCR-AIM-002 메시지 전송에서 판정이 `FALLBACK`이면 `reply_fallback`(SCR-AIM-005)을 부르고 응답에 판정·저장된 AI 메시지를 담는다. 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫. 프론트 연결은 엔드포인트와 한 번에
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

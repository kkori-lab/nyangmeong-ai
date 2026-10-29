# LJS 핸드오프

## 지금 하는 것
SCR-AIM-002 대화창 · 검색 질문/응답 — 끝 (검증 통과 1회차, 사람 확인 2026-10-28. 메시지 전송 SSE API와 LLM 답변 스트리밍)
기획 상태: 승인됨
- 고른 이유: "다음에 할 것" 맨 위. 기준은 AI매니저 기능명세서 v0.9(FN-AIM-002-01~11, FN-AIM-011-15·16), 화면설계서 v0.11 SCR-AIM-002 처리 조건.
- 범위: 메시지 전송 API 하나로 사용자 메시지 저장 → `judge_intent` → 판정별 응답. SEARCH는 LLM 답변 스트리밍(SSE), FALLBACK은 `reply_fallback`, ROUTE·REGISTER·RECEIPT는 판정만 돌려준다(이동은 React, 등록 SCR-AIM-012·영수증 SCR-AIM-013은 그 마일스톤). FN-AIM-002-01·05·06(말풍선·이동·로딩·중복 전송 차단)은 React 몫.
- 새 API(React, LJS): `POST /ai/conversations/{aiCnvrsRoomSn}/messages`, 요청 `MessageSendRequest {cnvrsCn: String?(공백만 불가, 1~1,000)}`. `cnvrsCn`이 있으면 사용자 메시지로 저장하고 답한다. 없으면 저장 없이 방의 마지막 사용자 메시지에 답한다(첫 메시지 직후 — `POST /ai/conversations`가 이미 저장, [다시 시도], [다시 생성]). 사용자 메시지가 없는 방은 400 `INVALID_REQUEST`. 인증은 LLM 전에 `require_member`, `X-Requested-With` 필수.
  - 응답은 `text/event-stream`(이 API만 `ApiResponse` 껍데기 예외, `docs/api/README.md`에 적는다). 스트림 시작 전 오류(400·401·403·404·502)는 지금과 같은 JSON `ApiResponse`. 이벤트: `intent`(Intent), `delta`(`{text}`, SEARCH만), `done`(`{message: ConversationMessage|null, shortcut: Intent|null}`), `error`(`{code: "EXTERNAL_API_ERROR", message: "일시적으로 답변할 수 없어요"}`).
  - `docs/api/chat.md`에 행·`MessageSendRequest`·이벤트 DTO 추가, `ConversationMessage`에 `cmptnYn: Boolean` 추가(Java GET 대화가 이미 주는 값. 다시 열었을 때 미완료 표시용). 머리말의 "SCR-AIM-001·002… 해당 마일스톤에서 추가" 문장 고침.
- FN-AIM-002-02·11, FN-AIM-011-15 컨텍스트: Java `GET /internal/ai/conversations/{sn}`(이미 있음, 메시지별 `cmptnYn`)로 방을 읽어 `cmptnYn=false`를 빼고 답할 사용자 메시지까지의 최근 6턴(12메시지)만 보낸다. 맨 앞이 AI 메시지면 버린다. 다른 대화는 읽지 않는다. → Java "미정" 3개 중 "최근 6턴"은 이것으로 대신하므로 요청하지 않는다.
- 설정값(SYS_STNG_AI_TKN_UPLMT_CNT 4500·SYS_STNG_AI_CNVRS_TURN_CNT 6): Java 설정 조회 API가 없어 가짜로 먼저 만들고 나중에 연결. `app/chat/repository.py`에 `AiSettings`(max_tokens·turns) + 기본값을 주는 `get_ai_settings` 의존성. 연결은 "다음에 할 것"에.
- FN-AIM-002-07 시간 제한: `config.py`에 `ANSWER_FIRST_TOKEN_SEC=10`·`ANSWER_TOTAL_SEC=60`(테스트에서 줄인다). 첫 글자 전 시간 초과·API 오류·거절 → `error` 이벤트, AI 메시지는 저장하지 않음(사용자 메시지는 남아 [다시 시도]가 `cnvrsCn` 없이 다시 부른다). 첫 글자 뒤 60초 초과·API 오류 → 부분 답변을 `cmptnYn=false`로 저장하고 `done`. 클라이언트 연결 끊김 → 부분 답변을 `cmptnYn=false`로 저장(취소에 휩쓸리지 않게 `asyncio.shield`). [다시 생성]은 새 메시지를 덧붙이고 미완료 메시지는 그대로 둔다(컨텍스트에서 빠지므로 Java "미완료 완료 처리" PATCH는 필요 없음 — 요청하지 않는다). 완료 답변은 `cmptnYn=true`로 저장. `repository.add_message`에 `cmptn_yn` 인자 추가(기존 내부 API 요청 필드 그대로).
  - 구현 중 조정(2026-10-28, 사람 확인 필요): 클라이언트 연결 끊김은 `docs/convention/architecture.md` "질문 한 번의 순서"(브라우저 연결이 끊겨도 생성·저장은 끝까지)를 따라 답변 생성을 별도 작업으로 끝까지 하고 완료(`cmptnYn=true`)로 저장한다. 위의 "부분 답변을 미완료로 저장(shield)"은 하지 않는다. 미완료 저장은 60초 초과·도중 오류만. `cmptnYn`은 Java 기본값이 true라 false일 때만 보낸다(기존 테스트의 요청 본문 유지).
- FN-AIM-002-03 의료 고지: SEARCH 답변 끝에 화면설계서 문구 "※ 참고 정보이며 의료 진단이 아닙니다. 이상 징후가 있다면 수의사와 상담하세요."를 마지막 `delta`로 보내고 본문에 포함해 저장. 건강 관련 여부를 따로 판정하지 않고 모든 검색 답변에 붙인다(검색 범위 D-003 미결, 판정 실수로 고지가 빠지는 쪽이 더 위험). 미완료 답변에는 붙이지 않는다.
- FN-AIM-002-08·09, FN-AIM-011-16: 답변 시스템 프롬프트에 "앱 안의 내 기록·내 병원 같은 개인 데이터는 알 수 없으니 해당 화면을 안내", "진단·처방은 하지 않고 일반 정보 + 수의사 상담 안내", "한국어로 답한다"를 넣는다(길이 제한 없음, 아래 결정). AI에는 대화 메시지 텍스트만 보낸다(펫 번호·기록 없음).
- FN-AIM-002-04 연관 바로가기: 의도 분류 구조화 출력에 `related_num`(SEARCH일 때 관련 화면 번호, 없으면 null) 추가 → `Classified`에 실어 `done.shortcut`(Intent ROUTE 모양, 저장 안 함). 호출을 늘리지 않는다. mock 분류기는 null.
- FN-AIM-002-10: 룰 라우팅은 LLM 앞에서 끝나고 분류 실패는 UNKNOWN→FALLBACK이라 이미 독립. LLM 오류 상태에서 라우팅 문장이 ROUTE로 나오는 테스트로 확인.
- 클라이언트(`app/chat/clients.py`): `AnswerGenerator` Protocol(`stream(messages, max_tokens) -> AsyncIterator[str]`), `MockAnswerGenerator`(고정 문장을 몇 조각으로), `AnthropicAnswerGenerator`(`get_anthropic_client` 재사용, `messages.stream`, `LLM_MODEL`, refusal은 오류로), `get_answer_generator`. 로그는 길이·소요 시간·실패 종류만.
- 서비스(`app/chat/service.py`): `build_context`, `send_message`(이벤트를 내는 async generator). 라우터(`app/chat/router.py`): `StreamingResponse`.
- 완료 조건 `명령:` `tests/chat/test_messages.py`(가짜 Java·가짜 답변 생성기): `cnvrsCn` 있음/없음, 사용자 메시지 없는 방 400, SEARCH 스트림(intent→delta…→고지 delta→done, 저장 본문 끝에 고지, cmptnYn true), ROUTE·FALLBACK·REGISTER 이벤트, 컨텍스트 12메시지 상한·미완료 제외·맨 앞 AI 제거, 첫 글자 시간 초과·오류 → error 이벤트·저장 없음, 전체 시간 초과·중간 오류 → 부분 답변 cmptnYn false 저장, LLM 오류여도 룰 라우팅 ROUTE, 로그인 안 함 401·`X-Requested-With` 없음 403(LLM 안 부름). `tests/chat/test_llm_clients.py`에 Anthropic 스트리밍 가짜 응답으로 요청 본문(system·messages에 대화 텍스트만, max_tokens), refusal·500 처리, `related_num` → shortcut.
- 완료 조건 `화면:` mock 모드로 서버를 띄워 Postman(또는 `curl -N`)으로 대화 생성 → `cnvrsCn` 없이 메시지 전송 → 이벤트가 차례로 흘러오고 끝에 고지, 이어서 GET 대화에 AI 메시지가 저장됨. `scripts/llm_smoke.py`에 답변 스트리밍 1건 추가해 real 첫 글자·전체 시간 출력.
- 공통 완료 조건 `명령:` `sh scripts/check.sh` 종료 코드 0.
- 확인 필요(Java, 백엔드 LJS): 메시지 내부 API `cnvrsCn` 1~1,000자 제한이 AI 답변(최대 4500토큰)에 너무 짧다. AI 역할 메시지 상한을 늘려 달라고 요청한다.
  - 결정: 상한을 두지 않고 받아 본다(2026-10-28 사람). Python은 프롬프트로 길이를 유도하지 않고 자르지도 않는다. 답변 전체를 그대로 저장 요청한다(Java가 1,000자 넘는 답을 거절하면 지금은 저장 실패 → 그 응답의 `done.message`는 null, 로그에 길이만).
- 다음에 할 것에 남길 것: Java AI 설정값 조회 API 요청·연결(가짜 `get_ai_settings` 교체), AI 메시지 길이 상한 변경 요청(실제 답변 길이 분포를 보고), internal.md "미정" 행을 "설정값 조회"만으로 줄임.
새 의존성: 없음

### 추가 요청
| 번호 | 바꿀 파일 | 완료 조건 | 요청 |
| --- | --- | --- | --- |
| 추가-1 | `app/chat/service.py`, `docs/api/chat.md`, `tests/chat/test_messages.py` | 명령: ROUTE 판정이면 이동 안내가 AI 메시지로 저장되고 `done.message`로 온다 | 요청 2026-10-29 10:42 "프론트 사람 확인 요청: ROUTE 이동 안내를 저장해 다시 열어도 답이 남게(저장한다)" |
| 추가-2 | `app/chat/clients.py`, `app/chat/service.py`, `tests/chat/test_messages.py`, `tests/chat/test_llm_clients.py` | 명령: 룰에 안 걸린 문장에서 분류 LLM이 실패하면 `error` 이벤트, 폴백 저장 없음. 룰 라우팅은 LLM 오류여도 ROUTE | 요청 2026-10-29 10:42 "분류 단계 LLM 장애는 폴백이 아니라 error 이벤트로" |
| 추가-3 | `app/chat/clients.py`, `tests/chat/test_llm_clients.py` | 명령: 15자 이하 첫 메시지는 LLM을 부르지 않고 그대로 제목이 된다 | 요청 2026-10-29 "'가계부' 한 단어가 '가계부 작성 방법' 제목이 됨. 짧은 입력은 그대로 제목으로(답변 요약 제목은 마일스톤으로)" |

## 다음에 할 것
- 문서 정정: 연결 끊김은 구현 중 조정대로 끝까지 생성·완료 저장한다(architecture.md). `docs/api/chat.md` 메시지 API 행과 `milestones/LJS.md` SCR-AIM-002 완료 조건에 남은 "연결 끊김 → 미완료 저장" 문구를 뺀다. 연결 끊김 테스트도 없음
- 다음 `/start`는 대기 맨 위 SCR-AIM-012(등록 카드). 메시지 API의 REGISTER 판정 뒤 흐름을 잇는다
- 백엔드에 요청(LJS 백엔드): AI 설정값 조회 내부 API(SYS_STNG_AI_TKN_UPLMT_CNT·SYS_STNG_AI_CNVRS_TURN_CNT, 연결되면 가짜 `get_ai_settings` 교체), AI 역할 메시지 `cnvrsCn` 1,000자 상한 확대(상한 없이 저장 요청 중, 넘으면 저장 실패). `docs/api/internal.md` "미정" 행은 "설정값 조회"만 남긴다(최근 6턴은 GET 대화, 미완료 완료 처리는 불필요)
- 프론트(LJS)와 맞출 것: 메시지 API SSE 이벤트(`intent`·`delta`·`done`·`error`, `chat.md` MessageEvent), 화면 ID → 프론트 경로 변환, 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫
- 백엔드에 요청(LJS 백엔드, 영수증·캐릭터 흐름 재설계): Python이 부를 원본 이미지·RECPT·영수증 상태(AIMG01) 저장, 캐릭터 작업 생성·결과·상태 보고, (PDF를 Java에서 받는 방법이면) 첨부 조회 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- SCR-HLT-005 기획 때 정할 것: Python이 PDF를 받는 방법(React가 다시 올림 / 첨부 번호로 Java에서 받음), 인식 결과 모양(SCR-HLT-007 입력값)
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`), `verify-collect.sh:37-38` `case` 문법
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

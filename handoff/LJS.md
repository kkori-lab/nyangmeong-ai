# LJS 핸드오프

## 지금 하는 것
SCR-AIM-011 대화창 · 첫 답변 요약 제목 (추가 요청) — 끝 (검증 확인 못 함 있음(연결 남음만), 사람 확인 2026-10-30. 방의 첫 AI 답변이 SEARCH로 끝나면 질문·답변 요약으로 Java PATCH 한 번, 실패해도 답변 유지. Java PATCH 없음 → 연결 남음)
- 결정: 바꾸는 때는 방의 첫 AI 답변이 SEARCH로 끝까지 나왔을 때(`turn.messages`에 AI 역할 메시지가 없고 `complete`). 첫 답변이 ROUTE·폴백·등록·미완료면 바꾸지 않고, 그 뒤 SEARCH가 와도 바꾸지 않는다(의도 종류가 메시지에 저장되지 않아 "첫 SEARCH"를 알 수 없음). 그래서 한 방에서 한 번만 부른다
- 결정: 요약 입력은 첫 질문 + 답변 본문(고지 문구 제외), 출력은 기존 제목 규칙(한 줄, 200자 이내, `_clean_title`). 모델은 `llm_model`(Haiku) 한 번. 실패·거절·빈 결과면 제목을 바꾸지 않는다(로그만). 제목 수정 실패도 답변·`done`에 영향 없음(로그만)
- 결정: 순서는 `done`을 보낸 뒤 같은 작업 안에서 요약·수정(답변 지연 없음). React에 새 이벤트 없음(목록을 다시 읽으면 바뀐 제목). React 계약(`docs/api/chat.md` SSE·Intent) 그대로
- 명세 차이: FN-AIM-011-11 "생성 시 1회만, 재생성 기능 없음"과 다르다(사용자 변경이 아닌 서버 1회 교체). DMS 반영은 "다음에 할 것"에 모아 둔다
- (명세 밖, 관련 FN-AIM-011-11) → `app/chat/clients.py`(`TitleGenerator.summarize(question, answer)`, `AnthropicTitleGenerator.summarize`, 요약 프롬프트), `app/chat/repository.py`(`update_title(room_sn, title)`, `JavaConversationRepository`가 `PATCH /internal/ai/conversations/{sn}` `{cnvrsTtl}` 호출), `app/chat/service.py`(`answer_turn`·`_run_turn`·`_search_answer`에 제목 교체), `app/chat/router.py`(메시지 전송에 `get_title_generator` 주입), `tests/chat/fakes.py`(`FakeTitleGenerator.summarize` 호출 기록), `tests/chat/conftest.py` `FakeJava`(PATCH 받기·기록), `tests/chat/test_messages.py`(새 테스트), `docs/api/internal.md`(PATCH 행 초안). 부를 API: Java `PATCH /internal/ai/conversations/{aiCnvrsRoomSn}` 요청 `{cnvrsTtl: String(1~200)}` 응답 ConversationSummary, 200(LJS 백엔드, 아직 없음 — 초안을 이번에 `internal.md`에 "초안(백엔드 PR 전)"으로 적고 가짜는 `tests/chat/conftest.py` `FakeJava`). 완료 조건 — 명령: `sh scripts/check.sh` 통과, 테스트 ① 첫 SEARCH 답변 완료 뒤 요약 제목으로 PATCH 한 번 ② 같은 방 두 번째 SEARCH 답변은 요약·PATCH 안 부름 ③ 첫 답변이 ROUTE·FALLBACK이면 안 부름 ④ 미완료(도중 오류·시간 초과) 답변이면 안 부름 ⑤ 요약 실패·PATCH 실패여도 `done`과 답변 저장 그대로 ⑥ 요약 입력에 고지 문구 없음. 화면: Java PATCH가 생기기 전에는 없음(연결은 "다음에 할 것"), 생긴 뒤 Postman으로 새 대화 → 메시지 전송(SEARCH) → `GET /ai/conversations`에서 제목이 바뀐 것 확인
- 새 의존성: 없음

## 다음에 할 것
- 연결 남음: SCR-AIM-011 첫 답변 요약 제목 (Java PATCH 대기, LJS 백엔드. 10-30 15시 backend-3c 세션에 계약 보냄, 아직 작업 시작 전). LJS 백엔드에 `PATCH /internal/ai/conversations/{aiCnvrsRoomSn}` `{cnvrsTtl}`(1~200자, 암호화 저장, 본인 대화 판정, 200 ConversationSummary)를 만들고 백엔드 `docs/api/ai.md`에 행 추가. 생기면 `docs/api/internal.md` 초안을 확정으로 바꾸고 Postman으로 확인
- 프론트(LJS) 알리기: SCR-AIM-011 첫 SEARCH 답변은 `done` 뒤 제목 요약(Haiku 한 번)이 끝나야 SSE 스트림이 닫힌다. 입력창 다시 열기는 스트림 종료가 아닌 `done` 기준으로. 바뀐 제목은 대화 목록을 다시 읽어 반영
- DMS 반영(모아서): AI매니저 기능명세서 FN-AIM-011-11에 "첫 AI 답변이 SEARCH로 완료되면 질문·답변 요약으로 제목을 한 번 바꾼다(서버, 사용자 변경 없음)" 추가
- DMS 반영(모아서): AI매니저 화면설계서·기능명세서 SCR-AIM-005에 서비스 범위 밖 질문 안내 문구 "반려동물 케어와 관련된 질문만 도와드릴 수 있어요. 반려동물이나 서비스 이용에 관해 물어봐 주세요."와 판정(룰 키워드 + 물음꼴이면 AI로 범위 확인) 추가. FN-AIM-005-07(같은 폴백)과 문구가 달라짐
- 프론트(LJS) 알리기: 범위 밖 질문도 `intent.kind` FALLBACK 그대로(칩·연속 실패 카운트 같음), `done.message.cnvrsCn`만 범위 안내 문구. 프론트가 폴백 문구를 하드코딩하면 `done.message`를 쓰게 맞춘다
- backend-90에 알리기: requirements.txt 커밋됨(`bf28ade`, LJS). 배포는 develop → master 병합 뒤. 서버 gunicorn은 워커 1개(`_in_progress` 프로세스 메모리)
- 다듬기(선택): `app/chat/clients.py` 분류 프롬프트 두 곳(`"…OUT_OF_SCOPE,"` 뒤, `_hint_note`의 `"…OUT_OF_SCOPE."` 뒤) 문자열 이음 공백
- frontend-83 세션에 알리기: 영수증 원본·상태가 실제 Java 영수증 내부 API로 저장된다(SCR-AIM-008·013, 대화창은 `ocrRqstSrcCd=AIMC0031`)
- 로컬 Java DB 정리(선택): 검증으로 생긴 RECPT 515~527과 원본 파일
- JAJ에 요청(2026-10-30 LJS 결정): 검사결과지 PDF 분석은 React → Python `POST /ai/checkups/lab-results`로 고정한다. 백엔드 `docs/api/health.md`의 Java `POST /pets/{petSn}/checkup-attachments/{ckupRcdAtchSn}/analyses`와 InspectionAnalysisResponse(`anlysRslt`)는 지운다. 항목 이름은 Python이 InspectionAnalysisItem(INSP_NVL)에 맞췄다(`registered`는 React가 검진상세 목록으로 판정). HLTG12에 SDMA 코드가 없어 지금은 직접입력명 `SDMA`로 보낸다. 명세대로 드롭다운에 넣으려면 JAJ가 SDMA 코드를 추가하고 `data/lab_items.yaml`에 `cd`를 넣는다
- 프론트(LJS) 대기: 검진상세 첨부 자료 [PDF 분석] → `POST /ai/checkups/lab-results`(파일 다시 올림) → 성공 시 SCR-HLT-007에 채움, `excludedArtclNms`는 저장 대상 밖으로 안내, `registered`(이미 등록됨)는 검진상세 혈액검사 목록으로 판정, 실패·422·504는 SCR-HLT-005에서 사유 안내, 다시 분석 중복 요청은 버튼 잠금
- 검사결과지 인식률: 합성 결과지 1건으로만 확인(2026-10-30). 실제 병원 결과지·스캔본으로 더 확인(원본은 git 제외)
- 연결 남음: FN-MYP-010-08·17·18 생성기 붙이기 — 다른 곳에서 만드는 생성기(사진 분석 포함)를 `app/character/clients.py` `get_character_client`에 붙인다. 입출력이 다르면 그 파일에 맞춤 코드만. 분석 방식(한 번에 / 분석 뒤 생성)·반려동물 사진 판정은 그때 정한다. 붙인 뒤 얼굴 영역 위치·샘플 10건 이상 검증(FN-MYP-010-18), 규격 미확보 시 대체(FN-MYP-010-19) 판단 (LJS)
- 연결 남음: FN-MYP-010-09 Java 캐릭터 작업 생성·결과 보고 내부 API(LJS 백엔드, 캐릭터 흐름 재설계). 연결되면 `app/character/repository.py` `FakeCharacterJobRepository` 교체, 작업 번호 이름(`chrcJobSn`)·실패 사유를 Java에 맞춘다. 초안은 `docs/api/internal.md` "Python → Java" 미정 행
- 프론트(LJS) 대기: 대화창 영수증 연결(SCR-AIM-013 — 이미지 첨부 시 `/messages` 대신 `POST /ai/receipts`(`ocrRqstSrcCd=AIMC0031`) → 끝나면 `receipt-result`). 프론트 핸드오프에 적혀 있고 프론트 `/start` 때 진행. 건강 일지 SCR-AIM-008 연결은 프론트 PR #112로 끝남
- 백엔드에 요청(LJS 백엔드): Java `/api/receipts`(업로드)·`/{recptSn}/analyze`·`FakeOcrClient` 흐름 정리. 분석은 React → Python `/ai/receipts`라 Java 분석 경로는 `/internal/v1/ocr` 삭제와 함께 정리. Postman이 8080으로 가면 가짜 결과(초코·아포퀠)가 온다
- 중복 분석 차단(`_in_progress`)은 프로세스 메모리라 워커 1개 전제. 여러 워커로 띄우면 Java 영수증 상태로 옮긴다
- OCR 인식률: 실제 영수증 1건(메이동물메디컬센터, 1구역)으로 맞춤. 프론트 확인(2026-10-29)에서 아조딜은 `mdcnUsage`가 null이라 1일 횟수 칸이 빈다(회원 입력). 2마리 청구서·다른 병원 영수증으로 더 확인(샘플 10건 목표, 사진은 git 제외)
- 각자 `.env.local`: `GOOGLE_APPLICATION_CREDENTIALS` → `GOOGLE_VISION_API_KEY`(API 키), `OCR_TIMEOUT_SEC` 15. 디스코드 `.env.local` 갱신
- 연결 남음(JAJ): Java register-context의 `careArtclNms`가 빈 배열이라 같은 이름 케어 항목 안내(FN-AIM-012-08)가 실제로는 뜨지 않는다. JAJ 케어 항목 service가 생기면 Python은 고칠 것 없음
- JAJ 대기: React→Java 일정·케어 항목 등록 API(출처 HLTC0067, SCR-HLT-003 토탈 케어리스트 대기). 카드 `cycleDays`는 `CARE_ARTCL.CYCLE_DRCT_INPT_DAY_CNT`에 대응(요청 필드 이름은 JAJ API가 정함)
- DMS AI매니저 기능명세서 버전 11(v1.0 표기, 버전 12로 대체)은 MCP에 삭제 도구가 없어 남아 있을 수 있다. 남아 있으면 DMS 화면에서 지운다(LJS)
- DMS 명세 갱신 모음(LJS): 하나씩 올리지 않고 모아서 한 번에 버전업한다. 코드에는 이미 반영돼 있다
  - 화면설계서 SCR-AIM-012 ⑥: 같은 이름 안내 문구 "미결"을 FN-AIM-012-08 확정 문구로 바꾼다
  - 화면설계서 SCR-AIM-012 ⑤: 케어 항목 등록 결과 요약 예시 추가("✔ 등록됨 — 뭉치 발톱 깎기 · 2주마다 · 다음 예정일 10-10(토)")
- 프론트(LJS)가 맞출 것: ROUTE 뒤 `done.message`(저장된 이동 안내)와 화면 안내 겹침 정리, 분류 장애 `error`는 연속 실패로 세지 않고 [다시 시도]. 프론트 세션에 알림(2026-10-29)
- 백엔드에 요청(LJS 백엔드): 대화 제목 수정 내부 API. 마일스톤 "첫 답변 요약 제목"이 기다림
- 백엔드에 요청(LJS 백엔드): AI 설정값 조회 내부 API(SYS_STNG_AI_TKN_UPLMT_CNT·SYS_STNG_AI_CNVRS_TURN_CNT, 연결되면 가짜 `get_ai_settings` 교체), AI 역할 메시지 `cnvrsCn` 1,000자 상한 확대(상한 없이 저장 요청 중, 넘으면 저장 실패). `docs/api/internal.md` "미정" 행은 "설정값 조회"만 남긴다(최근 6턴은 GET 대화, 미완료 완료 처리는 불필요)
- 프론트(LJS)와 맞출 것: 메시지 API SSE 이벤트(`intent`·`delta`·`done`·`error`, `chat.md` MessageEvent), 화면 ID → 프론트 경로 변환, 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫
- 백엔드에 요청(LJS 백엔드, 캐릭터 흐름 재설계): Python이 부를 캐릭터 작업 생성·결과·상태 보고 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

# LJS 핸드오프

## 지금 하는 것
SCR-AIM-013 대화창 · 영수증 분석 (대화 이력) — 끝 (검증 1회차 통과, 사람 확인 2026-10-29. `POST /ai/conversations/{aiCnvrsRoomSn}/receipt-result`로 함께 보낸 텍스트·결과 요약 한 줄 저장, `/ai/receipts` 출처에 AI 대화창 `AIMC0031`)
기획 상태: 승인됨 (2026-10-29 15:46, 출처 코드 AIMC0031 포함)
- 기획과 다른 점: 쿠키 없음 401을 저장 전에 주려고 `receipt-result`에 `require_member`를 붙였다(메시지 전송 API와 같음). 출처 번호는 기획 때 정한 "하나씩 미루기"(`AIMC0028`)에서 백엔드 결정으로 맨 뒤 새 번호 `AIMC0031`로 바꿨다.
- 고른 이유: "다음에 할 것" 맨 위는 프론트 저장소 일(`receiptApi.js` 연결)이라 이 저장소에서 할 수 없어 "대기 맨 위"를 골랐다. 기준 DMS: AI매니저_기능명세서_v0.10_20261029, AI매니저_화면설계서_v0.11_20261026.
- 흐름: 이미지가 붙은 전송이면 React가 `/messages`(의도 판정)를 부르지 않고 `POST /ai/receipts`(SCR-AIM-008에서 만듦)로 분석한다. 분석이 끝나면(인식·인식 실패·일시 오류·분석 취소) React가 새 API `POST /ai/conversations/{aiCnvrsRoomSn}/receipt-result`로 함께 보낸 텍스트와 결과를 보내고, Python이 사용자 메시지·요약 AI 메시지를 Java 대화 내부 API에 저장한다. 기능 패키지끼리 import하지 않으므로 `ocr`의 분석과 `chat`의 저장을 한 API로 합치지 않는다(SCR-AIM-012 `register-result`와 같은 방식).
- 계약 초안(구현 전에 먼저): `docs/api/chat.md`에 행 추가. `POST /ai/conversations/{aiCnvrsRoomSn}/receipt-result` 요청 `ReceiptResultRequest`(`result` String 필수 `RECOGNIZED`·`FAILED`·`ERROR`·`CANCELED`, `cnvrsCn` String 선택 — 함께 보낸 텍스트, 메시지 전송과 같은 1~1,000자·공백만 불가, `hsptlNm` String·`ckupYmd` LocalDate·`recptAmt` Integer 선택 — `ReceiptOcrResponse`와 같은 이름, `RECOGNIZED`일 때만 쓰고 다른 결과면 무시) / 응답 201 `ConversationMessage[]`(저장한 순서: 사용자 메시지(있으면) → AI 요약). 오류: `result` 허용값 밖·`cnvrsCn` 길이 위반 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND`(Java 오류 그대로). 문서 첫 줄의 "영수증(SCR-AIM-013) 이어 가기는 해당 마일스톤에서 추가" 문구를 고친다.
- FN-AIM-013-02 영수증 분석 분기(`app/chat/schemas.py`·`service.py`·`router.py`): 의도 판정을 거치지 않는 것은 React가 `/messages`를 부르지 않는 것으로 된다(Python 쪽 분류기는 부르지 않음). 함께 보낸 텍스트는 `ROLE_USER`로 저장해 이후 대화의 AI 컨텍스트(최근 턴)에 들어가고, 분석에는 쓰지 않는다(`/ai/receipts`에 텍스트를 보내지 않음). 완료 조건 `명령:` `cnvrsCn`이 있으면 가짜 Java가 사용자 → AI 순서로 2건 받음, 없으면 AI 1건만, 분류기·LLM 가짜 호출 0회, 1,001자·공백만 → 400이고 저장 0건, 쿠키 없음 → 401.
- FN-AIM-013-09 결과 이력 저장(`app/chat/service.py` `receipt_result_message`): 요약 한 줄 AI 메시지. `RECOGNIZED`: `영수증 분석 — 메이 동물병원, 10월 20일, 145,000원`(없는 값은 빼고 쉼표로 잇고, 셋 다 없으면 `영수증 분석 — 결과를 확인해 주세요`). `FAILED`: `영수증 분석 — 영수증을 읽지 못했어요`. `ERROR`: `영수증 분석 — 일시적인 오류로 분석하지 못했어요`. `CANCELED`: `영수증 분석 — 취소했어요`. 결과 카드의 [취소](저장 안 함)는 이미 요약이 저장된 뒤라 다시 부르지 않는다(카드 '취소됨'은 프론트 표시). 다시 열면 GET 대화가 요약만 돌려준다(버튼 없음, 기존 그대로). 완료 조건 `명령:` 네 결과·값 일부 없음·셋 다 없음 각각 가짜 Java가 받은 AI 메시지 문구가 위와 같음, 남의 대화(가짜 Java 404) → 404.
- FN-AIM-013-04 요청 출처 'AI 대화창'(사람 요청으로 포함, 2026-10-29): AIMG07에 대화창 값이 없어 공통코드를 새로 받는다. 처음엔 번호를 하나씩 미루기로 했다가 백엔드 결정(사람 확인 2026-10-29)으로 맨 뒤 새 번호 `AIMC0031`(AIMG07, SORT_SEQ 3)로 바꿨다 — 미루면 이미 DB에 있는 0028·0030 행이 다른 뜻으로 오류 없이 읽힌다. 기존 0028·0029·0030은 그대로. 이 저장소는 `app/ocr/service.py` `SOURCE_CODES`에 `AIMC0031` 추가, `docs/api/ocr.md` `ocrRqstSrcCd` 설명(건강 일지 `AIMC0026`·AI 대화창 `AIMC0031`)과 주석을 고친다. 백엔드 공통코드 추가 PR과 같은 때 병합한다(AGENTS.md 4번). 완료 조건 `명령:` `ocrRqstSrcCd=AIMC0031`이면 200이고 가짜 Java가 `AIMC0031`을 받음, `AIMC0027`(가계부)·`AIMC0028`(다른 그룹) → 400 `INVALID_REQUEST`이고 Java·OCR 호출 0회.
- 테스트: `tests/chat/test_receipt_result.py` 새로, 출처는 `tests/ocr/test_receipt_ai.py`에 추가. 기존 `tests/chat/fakes.py` 가짜 대화 저장소·인증을 쓴다.
- `화면:` `uv run python -m uvicorn app.main:app`으로 띄우고 Postman으로 대화 생성 → `POST .../receipt-result`(쿠키·`X-Requested-With`, `RECOGNIZED`+텍스트) → 201에 2건, `GET /ai/conversations/{번호}`에 사용자 텍스트와 요약 한 줄이 이어서 보인다. `result: "X"` → 400.
- 하지 않는 것: 백엔드·프론트·ERD의 공통코드 번호 변경(각 저장소 세션 몫, "다음에 할 것"에 남김), 다시 열었을 때 결과 카드 다시 불러오기(FN-AIM-013-09 미결, 스키마 변경 필요), 대상 반려동물 되물음·결과 카드·확인 모달·실패 버튼(FN-AIM-013-01·03·05~07, 프론트 몫).
새 의존성: 없음

## 다음에 할 것
- 공통코드 `AIMC0031` AI 대화창(AIMG07, 2026-10-29 백엔드 결정, 맨 뒤 새 번호): 백엔드(LJS 백엔드)가 기준 SQL·`ReceiptSource.java`에 추가한다. 이 저장소 PR과 같은 때 병합. 프론트는 대화창 영수증 분석을 `ocrRqstSrcCd=AIMC0031`로 보낸다(알림 코드 변경 없음). 문서(LJS): ERD·공통코드 문서에 `AIMC0031` 추가
- 프론트(LJS) 대기: 대화창 영수증 연결(SCR-AIM-013 — 이미지 첨부 시 `/messages` 대신 `POST /ai/receipts`(`ocrRqstSrcCd=AIMC0031`) → 끝나면 `receipt-result`). 프론트 핸드오프에 적혀 있고 프론트 `/start` 때 진행. 건강 일지 SCR-AIM-008 연결은 프론트 PR #112로 끝남
- 병합 조건: 이 저장소의 `AIMC0031` 허용(`app/ocr/service.py` `SOURCE_CODES`)은 백엔드 공통코드 `AIMC0031` 추가 PR과 같은 때 병합한다
- 연결 남음: FN-AIM-008-09·010-06·013-08, 008-07 상태 보고 — Java 영수증 원본 저장·결과·상태 보고 내부 API(LJS 백엔드). 연결되면 `app/ocr/repository.py` `FakeReceiptRepository` 교체, 상태 이름을 AIMG01 코드로
- 백엔드에 요청(LJS 백엔드): Java `/api/receipts`(업로드)·`/{recptSn}/analyze`·`FakeOcrClient` 흐름 정리. 분석은 React → Python `/ai/receipts`라 Java 분석 경로는 `/internal/v1/ocr` 삭제와 함께 정리. Postman이 8080으로 가면 가짜 결과(초코·아포퀠)가 온다
- 중복 분석 차단(`_in_progress`)은 프로세스 메모리라 워커 1개 전제. 여러 워커로 띄우면 Java 영수증 상태로 옮긴다
- OCR 인식률: 실제 영수증 1건(메이동물메디컬센터, 1구역)으로 맞춤. 프론트 확인(2026-10-29)에서 아조딜은 `mdcnUsage`가 null이라 1일 횟수 칸이 빈다(회원 입력). 2마리 청구서·다른 병원 영수증으로 더 확인(샘플 10건 목표, 사진은 git 제외)
- 각자 `.env.local`: `GOOGLE_APPLICATION_CREDENTIALS` → `GOOGLE_VISION_API_KEY`(API 키), `OCR_TIMEOUT_SEC` 15. 디스코드 `.env.local` 갱신
- 연결 남음(JAJ): Java register-context의 `careArtclNms`가 빈 배열이라 같은 이름 케어 항목 안내(FN-AIM-012-08)가 실제로는 뜨지 않는다. JAJ 케어 항목 service가 생기면 Python은 고칠 것 없음
- JAJ 대기: React→Java 일정·케어 항목 등록 API(출처 HLTC0067, SCR-HLT-003 토탈 케어리스트 대기). 카드 `cycleDays`는 `CARE_ARTCL.CYCLE_DRCT_INPT_DAY_CNT`에 대응(요청 필드 이름은 JAJ API가 정함)
- DMS AI매니저 기능명세서 버전 11(v1.0 표기, 버전 12로 대체)은 MCP에 삭제 도구가 없어 남아 있을 수 있다. 남아 있으면 DMS 화면에서 지운다(LJS)
- DMS 명세 갱신 모음(LJS): 하나씩 올리지 않고 모아서 한 번에 버전업한다. 코드에는 이미 반영돼 있다
  - 기능명세서 FN-AIM-013-04 비고: "※ 확인 필요 — AIMG07 신설"을 `AIMC0031` AI 대화창 확정으로(2026-10-29)
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
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

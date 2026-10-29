# LJS 핸드오프

## 지금 하는 것
SCR-AIM-008 영수증 촬영 · 업로드 (프론트 직접 호출 전환) — 끝 (검증 3회차 통과, 사람 확인 2026-10-29. `/ai/receipts`, Google Vision + LLM 정리, 가짜 Java 원본·상태 저장)
기획 상태: 승인됨 (2026-10-29 14:38, Google Vision 실제 분석 포함)
- 기획과 다른 점: OCR 키가 없으면 502 `EXTERNAL_API_ERROR`(기획 문구는 `OCR_API_ERROR`). 기존 `/internal/v1/ocr` 테스트와 `architecture.md` 키 없음 규칙에 맞췄다. 사람 확인 때 Vision 원문 순서가 섞여 금액이 틀려 `app/ocr/rules.py` `layout_text`(낱말 위치로 줄 다시 세우기, 글자 간격으로 수량·금액 나누기)를 넣고, LLM 정리는 분석 제한 15초·재시도 없음으로 바꿨다.
- 고른 이유: "다음에 할 것" 맨 위(공용 하네스 PR)는 #15(15e1ad5)로 병합돼 지웠고, 그다음 항목은 남이 할 일·연결 대기라 "대기 맨 위"를 골랐다. 기준 DMS: AI매니저_기능명세서_v0.10_20261029, AI매니저_화면설계서_v0.11_20261026.
- 흐름: React `POST /ai/receipts`(multipart) → Python 검증 → Java 원본 저장·영수증 생성(상태 분석중) → OCR(15초) → Java 결과·상태 보고 → React에 `recptSn` + `ReceiptOcrResponse`. Java 내부 API는 아직 없으므로 가짜 응답으로 먼저 만들고 나중에 연결한다. 가짜는 `app/ocr/repository.py` `FakeReceiptRepository`(대화 register-context 때와 같은 방식, 요청을 기록만 하고 `recptSn` 1부터 증가).
- 계약 초안(구현 전에 먼저): `docs/api/ocr.md` 새로 만든다(React → `/ai/**`). `POST /ai/receipts` 요청 `ReceiptAnalyzeRequest`(`file` 필수, `petSn` Long 필수 FN-AIM-008-03, `ocrRqstSrcCd` String 필수 — 건강 일지 `AIMC0026`, AI 대화창 값은 AIMG07에 신설 대기라 SCR-AIM-013 때 추가) / 응답 `ReceiptAnalyzeResponse`(`recptSn` Long, `ocr` ReceiptOcrResponse — 기존 DTO를 그대로 감싸 백엔드와 맞춘 모양을 바꾸지 않는다). `docs/api/internal.md` "Python → Java"에 영수증 원본 저장·결과 보고 2행을 "미정(LJS 백엔드)"으로 추가.
- FN-AIM-008-05 업로드 제약 검증(`app/ocr/service.py`·`router.py`): 확장자(jpg·jpeg·png·webp)와 실제 형식(`app/core/image.py` `detect_image_type`)이 모두 맞아야 하고, PDF 거부. 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 형식 400 `FILE_TYPE_NOT_ALLOWED`(백엔드 `ErrorCode` 이름 확인 후 확정). 검증 실패면 Java·OCR 둘 다 부르지 않는다. 인증은 `require_requested_with` + `require_member`(쿠키 없음 401, Java 오류 그대로). 완료 조건 `명령:` txt를 png로 바꾼 파일·pdf·10MB+1바이트 → 400이고 가짜 Java·OCR 호출 0회, 쿠키 없음 → 401.
- FN-AIM-008-06·013-04 OCR 호출·중복 차단(다시 하는 것): 같은 회원의 분석이 진행 중이면 409 `OCR_IN_PROGRESS`(프로세스 메모리의 회원 번호 집합. 워커 1개 전제, 여러 워커면 Java 영수증 상태로 옮길 것을 다음에 할 것에 남김). 끝나면(성공·실패·취소 모두) 풀린다. 완료 조건 `명령:` 느린 가짜 OCR로 동시 2요청 → 하나 200, 하나 409. 끝난 뒤 다시 요청 → 200.
- FN-AIM-008-07·010-01 분석 대기(서버 부분): OCR만 15초 제한(`OCR_TIMEOUT_SEC` 12 → 15, 이제 Java 제한 아래 둘 필요 없음), 초과 504 `OCR_TIMEOUT`(상태 일시오류), 외부 API 오류 502 `OCR_API_ERROR`(일시오류), 추출 0건 200 빈 응답(상태 인식실패), 성공은 상태 인식완료. 취소는 React가 요청을 끊는 것으로 하고, Python은 연결 끊김을 감지하면 OCR을 멈추고 상태 취소로 보고한다(응답 없음). 상태 코드값(AIMG01)은 가짜 Java에 문자열 이름으로 넘기고 연결 때 코드로 맞춘다. 완료 조건 `명령:` 시간 초과·API 오류·0건·성공·끊김 각각 가짜 Java가 받은 상태가 일시오류(시간초과)·일시오류(API)·인식실패·인식완료·취소.
- FN-AIM-008-09·010-06·013-08 원본 보관: OCR 전에 원본을 Java 저장 요청(실패해도 원본은 이미 저장돼 유지). Java 저장 실패면 OCR을 부르지 않고 기존 규칙(4xx 그대로, 연결 실패 502). 대화 이력에는 이미지를 넣지 않는다(013 마일스톤 몫). 완료 조건 `명령:` 모든 결과에서 가짜 Java가 원본 바이트·`petSn`·`ocrRqstSrcCd`를 받음, Java 저장 4xx면 OCR 호출 0회.
- Google Vision 실제 분석(사람 요청으로 포함, 2026-10-29): `.env.local`의 Google 값은 서비스 계정 파일 경로가 아니라 API 키(`AIza…`)라 SDK 없이 Vision REST `images:annotate`(`DOCUMENT_TEXT_DETECTION`, `?key=`)를 기존 httpx2로 부른다. 키 변수 이름은 `GOOGLE_APPLICATION_CREDENTIALS`(구글 라이브러리가 파일 경로로 읽는 이름)에서 `GOOGLE_VISION_API_KEY`로 바꾼다(`app/core/config.py`·`.env.local.example`·`tests/conftest.py`·`scripts/doctor.py`·`docs/convention/config.md`). `app/ocr/clients.py` `GoogleVisionOcrClient`: Vision 원문 → 구조화는 Anthropic(`llm_model`)에 JSON 출력으로 맡겨 `ReceiptOcrResponse`로 검증한다(규칙 파싱은 병원마다 양식이 달라 샘플 3건으로는 못 맞춘다). 두 호출 합쳐 15초 제한. 원문 텍스트가 비면 LLM을 부르지 않고 0건. 키가 없거나 Vision·LLM 오류면 502 `OCR_API_ERROR`. `chat`의 `get_anthropic_client`는 `app/core/llm.py`로 옮겨 두 패키지가 같이 쓴다(기능 패키지끼리 import 금지). 완료 조건 `명령:` `MockTransport`로 Vision 요청 모양(키·base64 본문)·가짜 원문 → 가짜 LLM 응답이 `ReceiptOcrResponse`로 바뀜, Vision 4xx·5xx·LLM 잘못된 JSON → 502. `화면:` 키를 넣고 띄워 Postman으로 실제 영수증 사진(확보한 3건, git에 올리지 않음)을 보내 병원명·금액·구역(2마리 청구서는 2구역)·약품이 맞는지 사람이 본다.
- 테스트(`tests/ocr/test_receipt_ai.py` 새로): 가짜 OCR·가짜 Java를 `dependency_overrides`로 끼우고 인증은 기존 대화 테스트의 가짜 Java 확인을 쓴다. 기존 `/internal/v1/ocr` 테스트는 그대로 둔다.
- `화면:` `uv run python -m uvicorn app.main:app`으로 띄우고 Postman으로 `POST /ai/receipts`(쿠키·`X-Requested-With`, png) → 실제 분석 결과와 `recptSn`(가짜 Java), 서버 로그에 가짜 Java의 원본 저장·인식완료 보고. pdf → 400 `FILE_TYPE_NOT_ALLOWED`, 쿠키 없음 → 401.
- 하지 않는 것: `/internal/v1/ocr` 삭제와 `internal.md` OCR 행 삭제(백엔드 PR과 함께 — 그때 따로), Java 내부 API 실제 연결, 실패 문구(프론트 몫), AI 대화창 출처 코드(SCR-AIM-013).
새 의존성: 없음

## 다음에 할 것
- 프론트(LJS)에 요청함(2026-10-29): `receiptApi.js` 가짜 분석 결과를 `POST /ai/receipts`로 연결(필드 이름 변환, `code`별 안내, AbortController 취소, `recptSn` 보관). 저장 전 확인·저장은 Java API 전까지 가짜
- 연결 남음: FN-AIM-008-09·010-06·013-08, 008-07 상태 보고 — Java 영수증 원본 저장·결과·상태 보고 내부 API(LJS 백엔드). 연결되면 `app/ocr/repository.py` `FakeReceiptRepository` 교체, 상태 이름을 AIMG01 코드로
- 백엔드에 요청(LJS 백엔드): Java `/api/receipts`(업로드)·`/{recptSn}/analyze`·`FakeOcrClient` 흐름 정리. 분석은 React → Python `/ai/receipts`라 Java 분석 경로는 `/internal/v1/ocr` 삭제와 함께 정리. Postman이 8080으로 가면 가짜 결과(초코·아포퀠)가 온다
- 중복 분석 차단(`_in_progress`)은 프로세스 메모리라 워커 1개 전제. 여러 워커로 띄우면 Java 영수증 상태로 옮긴다
- OCR 인식률: 실제 영수증 1건(메이동물메디컬센터, 1구역)으로 맞춤. 2마리 청구서·다른 병원 영수증으로 더 확인(샘플 10건 목표, 사진은 git 제외)
- 각자 `.env.local`: `GOOGLE_APPLICATION_CREDENTIALS` → `GOOGLE_VISION_API_KEY`(API 키), `OCR_TIMEOUT_SEC` 15. 디스코드 `.env.local` 갱신
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
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

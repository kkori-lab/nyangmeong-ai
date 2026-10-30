# LJS 핸드오프

## 지금 하는 것
SCR-HLT-005 검진상세 · 검사결과지 PDF 분석 — 끝 (검증 1회차 통과, 사람 확인 2026-10-30. React가 `POST /ai/checkups/lab-results`로 검사결과지 PDF를 다시 올리면 형식·크기 검증 → LLM(`LLM_MODEL`)에 PDF document 블록으로 보내 구조화 출력 → 12종 약어 정규화(`data/lab_items.yaml`)·숫자·참고범위 정리 → SCR-HLT-007 입력값 모양 `items` 반환. 저장하지 않는다. 새 패키지 `app/checkup/`, API 초안 `docs/api/checkup.md`)
- 기획과 다른 점: 못 읽은 값은 필드를 빼지 않고 null로 준다(영수증과 같음). 구조화 출력은 tool use가 아니라 `messages.parse`(영수증과 같음). 기획의 `.env.example`은 실제 파일 `.env.local.example`.
- 병합 조건: 응답 필드 이름(`inspArtclNm` 등)은 초안. 건강기록 백엔드의 검사 수치 저장 DTO와 맞춘 뒤 백엔드 PR과 함께 병합한다(AGENTS.md 4번).

## 다음에 할 것
- 바로 다음(2026-10-30 frontend-83 요청, `/start AIM-013`): FN-AIM-008-09·010-06·013-08, 008-07 — `app/ocr/repository.py` `FakeReceiptRepository`를 Java 영수증 내부 API(백엔드 PR #64, develop 병합)로 교체. `POST /internal/ai/receipts`(multipart `file`·`petSn`·`ocrDmndSrcCd`) → 201 `recptSn`, `POST /internal/ai/receipts/{recptSn}/result`(`ocrRslt` RECOGNIZED·UNRECOGNIZED·TIMEOUT·API_ERROR·CANCELED, RECOGNIZED면 `ocr`). 실패·취소도 꼭 보고(안 하면 RECPT가 분석중으로 남고 Java 정리 배치 없음), React 응답 전에 보고를 await하는 순서 유지, `docs/api/internal.md` 미정 2행 확정. 계약은 메시지가 아니라 백엔드 `docs/api/receipt.md`·코드와 대조(필드 이름·오류 코드 `FILE_TOO_LARGE` 등). 끝나면 frontend-83 세션에 알린다
- 연결 남음: FN-HLT-005-04 응답 필드 이름(`inspArtclNm`·`rsltVl`·`unitNm`·`refMinVl`·`refMaxVl`·`bloodYn`)을 건강기록 백엔드의 검사 수치 저장 DTO와 맞춘다(건강기록 백엔드 담당). 맞추기 전에는 이 PR을 병합하지 않는다
- 프론트(LJS) 대기: 검진상세 첨부 자료 [PDF 분석] → `POST /ai/checkups/lab-results`(파일 다시 올림) → 성공 시 SCR-HLT-007에 채움, `bloodYn` N 행은 저장 대상에서 빼고 안내, 실패·422·504는 SCR-HLT-005에서 사유 안내, 다시 분석 중복 요청은 버튼 잠금
- 검사결과지 인식률: 합성 결과지 1건으로만 확인(2026-10-30). 실제 병원 결과지·스캔본으로 더 확인(원본은 git 제외)
- 연결 남음: FN-MYP-010-08·17·18 생성기 붙이기 — 다른 곳에서 만드는 생성기(사진 분석 포함)를 `app/character/clients.py` `get_character_client`에 붙인다. 입출력이 다르면 그 파일에 맞춤 코드만. 분석 방식(한 번에 / 분석 뒤 생성)·반려동물 사진 판정은 그때 정한다. 붙인 뒤 얼굴 영역 위치·샘플 10건 이상 검증(FN-MYP-010-18), 규격 미확보 시 대체(FN-MYP-010-19) 판단 (LJS)
- 연결 남음: FN-MYP-010-09 Java 캐릭터 작업 생성·결과 보고 내부 API(LJS 백엔드, 캐릭터 흐름 재설계). 연결되면 `app/character/repository.py` `FakeCharacterJobRepository` 교체, 작업 번호 이름(`chrcJobSn`)·실패 사유를 Java에 맞춘다. 초안은 `docs/api/internal.md` "Python → Java" 미정 행
- 사람 확인 때 주의: `.env.local`의 `BACKEND_BASE_URL`이 실제 Java면 가짜 쿠키(`member-<번호>`)는 401이다. 가짜 Java로 볼 때는 `BACKEND_BASE_URL`을 8081 포트로 바꿔 띄운다
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

# LJS 핸드오프

## 지금 하는 것
SCR-MYP-010 픽셀 캐릭터 관리 (생성기 붙이기) — 끝 (검증 통과, 사람 확인 2026-11-02)
- pixel-dog-generator `pipeline/chibi-style` 138f722의 생성 경로를 `app/character/`로 이식. 눈 판별 → 2×2 시트 1회 생성 → 서기 정면 컷 → 높이 341px·눈 (256, 207), 상단이 y=100 아래면 100으로 보정해 512 PNG. 검은 털은 흰 하이라이트로 눈을 찾는다
- 샘플 10건(개 6·고양이 4, 검은 털 7건) 실제 생성: 눈 찾음 10/10, 잘림 0건, 마젠타 0화소. 상단 보정은 저장된 컷 재처리로 확인

## 다음에 할 것
- 굽기·합성·`/preview` 이식 마일스톤: FN-MYP-011 담당, Java 저장 자리(맨몸 시트·착용 시트·배치값 `scale, originX, originY`), 비용, `generate` 반환형을 정한 뒤. 머리 착용 그림을 바탕으로 쓰는 합성은 엔진에도 아직 없다. 지금 만든 캐릭터는 맨몸 시트를 저장하지 않는다 (LJS)
- DMS 모음: FN-MYP-010-13 "고정 좌표로 겹쳐 표시" vs 서버 합성, FN-MYP-010-17 "기준 좌표 고정" vs 상단 보정(눈 y가 캐릭터마다 다를 수 있음), 얼굴 영역 값 변경 (LJS)
- 눈 찾기 위험: `dog_fluffy` 512 재검출이 눈이 아닌 쌍을 잡았다. 실제 배치 경로에서는 샘플 10건 모두 맞았으나, 틀리면 규격을 통과한 채 조용히 어긋난다. 검은 털은 하이라이트 기준이라 눈 높이가 몇 px 다를 수 있고 측정하지 않았다 (LJS)
- 약한 테스트: EXIF 제거·회전 테스트 입력에 EXIF가 없다. 고양이 분기는 가짜 저장소가 항상 `PETC0001`을 줘 API 경로로는 안 지나간다(Java 연결 뒤 확인) (LJS)
- 얼굴 영역 `(128, 64, 256, 256)` → `(96, 32, 320, 320)` 변경 (LJS 결정 2026-11-02): 백엔드 `CharacterSpec.FACE`·`cropFace`의 256 축소 여부·AI `schemas.py`를 같이 바꾼다(`AGENTS.md` 4번, 백엔드 PR과 함께). AI는 눈 y=207 계산이 `FACE_Y`에 묶여 있어 상수를 분리한다 (LJS)
- 연결 남음: FN-MYP-010-09 Java 캐릭터 작업 생성·결과 보고 내부 API(LJS 백엔드, 캐릭터 흐름 재설계). 연결되면 `app/character/repository.py` `FakeCharacterJobRepository` 교체, 작업 번호 이름(`chrcJobSn`)·실패 사유를 Java에 맞춘다. 초안은 `docs/api/internal.md` "Python → Java" 미정 행
- 프론트(LJS) 알리기: SCR-AIM-011 첫 SEARCH 답변은 `done` 뒤 제목 요약(Haiku 한 번)이 끝나야 SSE 스트림이 닫힌다. 입력창 다시 열기는 스트림 종료가 아닌 `done` 기준으로. 바뀐 제목은 대화 목록을 다시 읽어 반영
- 프론트(LJS) 알리기: 범위 밖 질문도 `intent.kind` FALLBACK 그대로(칩·연속 실패 카운트 같음), `done.message.cnvrsCn`만 범위 안내 문구. 프론트가 폴백 문구를 하드코딩하면 `done.message`를 쓰게 맞춘다
- backend-90에 알리기: requirements.txt 커밋됨(`bf28ade`, LJS). 배포는 develop → master 병합 뒤. 서버 gunicorn은 워커 1개(`_in_progress` 프로세스 메모리)
- 다듬기(선택): `app/chat/clients.py` 분류 프롬프트 두 곳(`"…OUT_OF_SCOPE,"` 뒤, `_hint_note`의 `"…OUT_OF_SCOPE."` 뒤) 문자열 이음 공백
- frontend-83 세션에 알리기: 영수증 원본·상태가 실제 Java 영수증 내부 API로 저장된다(SCR-AIM-008·013, 대화창은 `ocrRqstSrcCd=AIMC0031`)
- 로컬 Java DB 정리(선택): 검증으로 생긴 RECPT 515~527과 원본 파일
- JAJ에 요청(2026-10-30 LJS 결정): 검사결과지 PDF 분석은 React → Python `POST /ai/checkups/lab-results`로 고정한다. 백엔드 `docs/api/health.md`의 Java `POST /pets/{petSn}/checkup-attachments/{ckupRcdAtchSn}/analyses`와 InspectionAnalysisResponse(`anlysRslt`)는 지운다. 항목 이름은 Python이 InspectionAnalysisItem(INSP_NVL)에 맞췄다(`registered`는 React가 검진상세 목록으로 판정). HLTG12에 SDMA 코드가 없어 지금은 직접입력명 `SDMA`로 보낸다. 명세대로 드롭다운에 넣으려면 JAJ가 SDMA 코드를 추가하고 `data/lab_items.yaml`에 `cd`를 넣는다
- 프론트(LJS) 대기: 검진상세 첨부 자료 [PDF 분석] → `POST /ai/checkups/lab-results`(파일 다시 올림) → 성공 시 SCR-HLT-007에 채움, `excludedArtclNms`는 저장 대상 밖으로 안내, `registered`(이미 등록됨)는 검진상세 혈액검사 목록으로 판정, 실패·422·504는 SCR-HLT-005에서 사유 안내, 다시 분석 중복 요청은 버튼 잠금
- 검사결과지 인식률: 합성 결과지 1건으로만 확인(2026-10-30). 실제 병원 결과지·스캔본으로 더 확인(원본은 git 제외)
- 프론트(LJS) 대기: 대화창 영수증 연결(SCR-AIM-013 — 이미지 첨부 시 `/messages` 대신 `POST /ai/receipts`(`ocrRqstSrcCd=AIMC0031`) → 끝나면 `receipt-result`). 프론트 핸드오프에 적혀 있고 프론트 `/start` 때 진행. 건강 일지 SCR-AIM-008 연결은 프론트 PR #112로 끝남
- 백엔드에 요청(LJS 백엔드): Java `/api/receipts`(업로드)·`/{recptSn}/analyze`·`FakeOcrClient` 흐름 정리. 분석은 React → Python `/ai/receipts`라 Java 분석 경로는 `/internal/v1/ocr` 삭제와 함께 정리. Postman이 8080으로 가면 가짜 결과(초코·아포퀠)가 온다
- 중복 분석 차단(`_in_progress`)은 프로세스 메모리라 워커 1개 전제. 여러 워커로 띄우면 Java 영수증 상태로 옮긴다
- OCR 인식률: 실제 영수증 1건(메이동물메디컬센터, 1구역)으로 맞춤. 프론트 확인(2026-10-29)에서 아조딜은 `mdcnUsage`가 null이라 1일 횟수 칸이 빈다(회원 입력). 2마리 청구서·다른 병원 영수증으로 더 확인(샘플 10건 목표, 사진은 git 제외)
- 각자 `.env.local`: `GOOGLE_APPLICATION_CREDENTIALS` → `GOOGLE_VISION_API_KEY`(API 키), `OCR_TIMEOUT_SEC` 15. 디스코드 `.env.local` 갱신
- 연결 남음(JAJ): Java register-context의 `careArtclNms`가 빈 배열이라 같은 이름 케어 항목 안내(FN-AIM-012-08)가 실제로는 뜨지 않는다. JAJ 케어 항목 service가 생기면 Python은 고칠 것 없음
- JAJ 대기: React→Java 일정·케어 항목 등록 API(출처 HLTC0067, SCR-HLT-003 토탈 케어리스트 대기). 카드 `cycleDays`는 `CARE_ARTCL.CYCLE_DRCT_INPT_DAY_CNT`에 대응(요청 필드 이름은 JAJ API가 정함)
- DMS AI매니저 기능명세서 표지(v0.12)의 "대상 화면 … (화면설계서 v0.11 기준)"·"기준 문서 … AI매니저 화면설계서 v0.11(2026-10-26)"을 v0.12로 맞춘다. 다음 DMS 모음 때 함께(LJS)
- DMS AI매니저 기능명세서 버전 11(v1.0 표기, 버전 12로 대체)은 MCP에 삭제 도구가 없어 남아 있을 수 있다. 남아 있으면 DMS 화면에서 지운다(LJS)
- 프론트(LJS)가 맞출 것: ROUTE 뒤 `done.message`(저장된 이동 안내)와 화면 안내 겹침 정리, 분류 장애 `error`는 연속 실패로 세지 않고 [다시 시도]. 프론트 세션에 알림(2026-10-29)
- 백엔드에 요청(LJS 백엔드): AI 설정값 조회 내부 API(SYS_STNG_AI_TKN_UPLMT_CNT·SYS_STNG_AI_CNVRS_TURN_CNT, 연결되면 가짜 `get_ai_settings` 교체), AI 역할 메시지 `cnvrsCn` 1,000자 상한 확대(상한 없이 저장 요청 중, 넘으면 저장 실패). `docs/api/internal.md` "미정" 행은 "설정값 조회"만 남긴다(최근 6턴은 GET 대화, 미완료 완료 처리는 불필요)
- 프론트(LJS)와 맞출 것: 메시지 API SSE 이벤트(`intent`·`delta`·`done`·`error`, `chat.md` MessageEvent), 화면 ID → 프론트 경로 변환, 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫
- 백엔드에 요청(LJS 백엔드, 캐릭터 흐름 재설계): Python이 부를 캐릭터 작업 생성·결과·상태 보고 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

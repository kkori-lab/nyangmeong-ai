# LJS 핸드오프

## 지금 하는 것
SCR-MYP-011 아이템 상점 모달 (테스트 보강·문서 정리) — 끝 (2026-11-03). 겹침 순서 테스트를 겹치는 화소로 바꿔 `LAYER_ORDER`가 바뀌면 실패하게 했고(얼굴 > 의상, 의상 > 머리 착용 바탕), `OpenAICharacterClient.bake` 호출·디코딩·오류 테스트를 더했다. 캐릭터 설계 문서(`charCrtJobSn`·Java 내부 API·5부위 표)와 `milestone.md` 담당 표(SCR-MYP-011·ADM-070)를 갱신

## 다음에 할 것
- 연결 남음: FN-MYP-031-05·03 Java 백엔드 PR (LJS 백엔드, AI 계약 변경과 같은 때 병합): ① `ReceiptService.create`가 `CHAT` 말고는 모두 `HEALTH`로 저장 → `ReceiptSource.EXPENSE` 분기 ② 가계부 출처는 `petAuthorizer.checkCaregiver` 건너뜀·`ReceiptOriginalRequest` `petSn` 선택·`ocrDmndSrcCd`에 `AIMC0027` ③ `global.external.ReceiptOcrResponse`에 `expndPlcusNm`·`expndClsfCd`(없으면 Jackson이 버려 `OCR_RSPNS_JSON`에서 조용히 빠짐) ④ `ReceiptOcrConverter.classify` 가계부 판정: 머리 값에 `expndPlcusNm`, 가계부 출처의 완전 인식은 `hsptlNm` 대신 `expndPlcusNm`, 품목 0개(펫월드 영수증 실측)도 부분 인식이 되지 않게
- 연결 남음: FN-MYP-031-03·05 프론트 가계부 (SJM): `src/features/expense/api.js` `recognizeReceipt` 가짜(`POST /receipts/recognize`) → `POST /ai/receipts`(form `ocrRqstSrcCd=AIMC0027`, `petSn` 없음). 응답 `data.ocr`의 `ckupYmd`·`recptAmt`를 `expndYmd`·`expndAmt`로, `expndPlcusNm`·`expndClsfCd`는 그대로. 0건은 값이 모두 null인 200, 504 `OCR_TIMEOUT`·502 `OCR_API_ERROR`는 "영수증을 읽지 못했어요"
- OCR 출력 모양(`app/ocr/clients.py` `ReceiptOutput`)에 필드를 더하면 Anthropic API가 400 "Schema is too complex"로 거절할 수 있다(2026-11-03 실측: 기본값 있는 필드 2개 추가로 모든 인식 실패, 가짜 LLM 테스트로는 안 잡힘). 필드를 더하면 실제 영수증으로 한 번 돌려 본다 (LJS)
- 개발 DB 정리: 2026-11-03 검증이 회원 1·반려동물 2의 RECPT 501·502와 원본 파일을 남겼다. 필요하면 지운다 (LJS 백엔드)
- 전체 굽기 재설계 (FN-ADM-070-02, 맨 먼저): 2026-11-03 백엔드(사람) 결정으로 시트 내부 API 4개(sheets·sheet-files·PUT item-sheets·POST item-sheets/failure)는 쿠키 인증만 받는다. 지금 `POST /ai/items/{itemSn}/bake`의 쿠키 없는 저장소(`get_server_character_repository`)는 운영에서 401로 전부 건너뛴다. 토큰 30분 만료·남의 캐릭터 시트를 쿠키 전제에서 푸는 방식을 정해 백엔드에 계약 제안. 후보: 관리자 쿠키로 남의 캐릭터 시트 읽기·쓰기 허용 + 관리자 화면이 페이지 단위로 여러 번 호출(요청 하나가 토큰 수명 안에 끝나는 크기) (LJS)
- 연결 남음: FN-MYP-011-01·FN-ADM-070-02 실제 Java 굽기 계약: 백엔드 PR #120(develop 대상, 2026-11-03 병합 전)에 `bake-items` `{itemSn, regnCd, bakeHint}`(판매 중·지시 있음, 시드 30개), `GET /internal/ai/items/{itemSn}/bake-targets?page=`(0부터, 100개, 관리자 쿠키만, 403 `ADMIN_ONLY`·404 `ITEM_NOT_FOUND`), 관리자 등록·수정 `bakeHint`(300자, 신발은 400, 바뀌면 그 아이템 시트 삭제). 공용 DB v0.12 (3) 적용됨. 병합 순서: 백엔드 #120 먼저 → AI `LJS` PR. AI 쪽 `bake-targets` 연결은 위 "전체 굽기 재설계"와 함께. 곰돌이 후드티 지시는 hood down으로 고치자고 backend-95에 답함
- 연결 남음: FN-ADM-070-02 관리자 프론트 아이템 등록 화면에 [굽기 지시 만들기](`POST /ai/items/bake-hints`)·[시험해 보기](`POST /ai/items/trial-preview`)·등록 성공 뒤 `POST /ai/items/{itemSn}/bake` 호출 (관리자 프론트)
- 로컬 시험 데이터: 관리자 mbrSn 2의 반려동물 petSn 1001 "시험복실"·캐릭터 pixelCharSn 601 (시험 굽기용, 2026-11-03)
- 결정 남음: `bake-hints`의 그림 형식·10MB 오류는 `/ai/characters`와 같은 `FILE_TYPE_NOT_ALLOWED`·`FILE_SIZE_EXCEEDED`로 했다(기획은 `INVALID_REQUEST`) (LJS)
- 병합 순서: 백엔드 PR #105(`d73ca54`, 캐릭터 내부 API 포함) 먼저 → 병합 직후 공용 DB v0.12 적용(사람) → AI `LJS` PR. 순서가 바뀌면 캐릭터 생성 502 (LJS)
- 옛 흐름으로 만든 캐릭터는 맨몸 시트가 없어 `/preview`가 404 `PIXEL_CHARACTER_NOT_FOUND`다. 다시 만들어야 한다. 무료 재생성(FN-MYP-010-23)은 사진이 Java로 오지 않아 SCR-ADM-042 전에 계약을 정한다 (LJS 백엔드)
- 하네스 수정 PR 후보(공용): `verify-loop.sh guard`가 읽기 전용 비교(`git diff --no-index`)까지 막아 verify 절차와 어긋난다
- 굽기·합성 최적화: 굽기 26개 실측 1회 104.2초(동시 10, 아이템당 31.5~37.0초, 재시도 없음). 동시 13으로 올린 값은 미측정. 합성 1.4초는 시험 그림 값. 후보는 전용 스레드 풀(기본 풀은 CPU+4라 코어 9개 미만 서버에서 13이 안 나온다), 429 대기 후 재시도, OpenAI 계정 한도 확인, 이미지 품질 `low` (LJS)
- 고양이 꼬리 경계선·다리 사이 분홍 점: 원인 미확인(착용 지시 변경의 영향 포함). 정렬 2단계 탐색은 촘촘한 무늬에서 빗나갈 수 있고 그림체 샘플 1장으로만 확인 (LJS)
- 굽기 켜기: 팀 비용 결정(26개 기준 캐릭터당 약 $1.64), Java 시트 저장 연결 뒤. 켜기 전 access_token(30분) 만료 대책을 정한다: 만료 뒤 아이템은 비용을 내고도 저장·실패 표시가 안 되어 "안 구운 아이템"으로 남고, 성공 보고 401이면 결과를 잃고 작업은 시간 초과 실패가 된다 (LJS)
- 백엔드(LJS): 신발을 안 넣기로 해서 공통코드 `MYPC0006`과 시드 신발 4개는 정리 대상이다(공통코드는 DB에서만 고친다) (LJS)
- DMS 모음: FN-MYP-010-13 겹침 순서(캐릭터 → 의상 → … → 머리장식) vs 합성 순서(머리 착용 바탕 위에 의상) (LJS)
- DMS 모음: FN-MYP-010-13 "고정 좌표로 겹쳐 표시" vs 서버 합성, FN-MYP-010-17 "기준 좌표 고정" vs 상단 보정(눈 y가 캐릭터마다 다를 수 있음), 얼굴 영역 값 변경 (LJS)
- 눈 찾기 위험: `dog_fluffy` 512 재검출이 눈이 아닌 쌍을 잡았다. 실제 배치 경로에서는 샘플 10건 모두 맞았으나, 틀리면 규격을 통과한 채 조용히 어긋난다. 검은 털은 하이라이트 기준이라 눈 높이가 몇 px 다를 수 있고 측정하지 않았다 (LJS)
- 약한 테스트: EXIF 제거·회전 테스트 입력에 EXIF가 없다. 고양이 분기는 가짜 저장소가 짝수 `petSn`일 때만 `PETC0002`를 준다(실제 값은 Java 연결 뒤 확인) (LJS)
- 얼굴 영역 `(128, 64, 256, 256)` → `(96, 32, 320, 320)` 변경 (LJS 결정 2026-11-02): 백엔드 `CharacterSpec.FACE`·`cropFace`의 256 축소 여부·AI `schemas.py`를 같이 바꾼다(`AGENTS.md` 4번, 백엔드 PR과 함께). AI는 눈 y=207 계산이 `FACE_Y`에 묶여 있어 상수를 분리한다 (LJS)
- 프론트(LJS) 알리기: SCR-AIM-011 첫 SEARCH 답변은 `done` 뒤 제목 요약(Haiku 한 번)이 끝나야 SSE 스트림이 닫힌다. 입력창 다시 열기는 스트림 종료가 아닌 `done` 기준으로. 바뀐 제목은 대화 목록을 다시 읽어 반영
- 프론트(LJS) 알리기: 범위 밖 질문도 `intent.kind` FALLBACK 그대로(칩·연속 실패 카운트 같음), `done.message.cnvrsCn`만 범위 안내 문구. 프론트가 폴백 문구를 하드코딩하면 `done.message`를 쓰게 맞춘다
- backend-90에 알리기: requirements.txt 커밋됨(`bf28ade`, LJS). 배포는 develop → master 병합 뒤. 서버 gunicorn은 워커 1개(`_in_progress` 프로세스 메모리)
- frontend-83 세션에 알리기: 영수증 원본·상태가 실제 Java 영수증 내부 API로 저장된다(SCR-AIM-008·013, 대화창은 `ocrRqstSrcCd=AIMC0031`)
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
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다
- AI 없는 아이템 얹기 시험(2026-11-03 사람 결정: AI 굽기 연결 뒤 마지막에): 얼굴·목 아이템을 도트 변환(`pixelize`) + 눈·목 기준점으로 얹어(`place_face`·`place_neck`, `app/character/overlay.py`) 샘플 2~3마리 × 안경 2·목걸이 2를 `scripts/overlay-trial.py` 모음 그림으로 사람이 판정. 앱·API 변경 없음, 샘플은 git 제외 (LJS)

# LJS 핸드오프

## 지금 하는 것
SCR-AIM-002 대화창 · 서비스 기능 안내 후속 (프론트 대조·새 평가 세트 평가·분류 캐시, 추가 요청) — 끝 (2026-11-05). ① 안내서를 프론트 develop de4b256과 대조해 32곳 고침(`docs/guide-review.md` "프론트 대조"). ② 안내서를 보지 않고 만든 새 세트 50문항으로 재평가: M1+LLM hit@3 22~24/44, 화면 이동 14/14, 범위 밖 5/5, 답변 정확도 24/27(`docs/design/service-guide-search.md` 4-1절), 평가 스크립트 `scripts/guide_eval.py`. ③ 분류 `system` 캐시 켬(캐시 읽기 7,501토큰). 추가-1 `llm_smoke` 분류 로그 INFO. 검증 1회차 통과, 사람 확인 완료

## 다음에 할 것
- DMS 모음: AI매니저 기능명세서에 사용법 안내 기능 ID 추가(GUIDE 분류·안내서 검색, 지금은 FN-AIM-002-02·002-04·004-02에 걸어 둠), 사용법 답변에도 의료 고지를 붙일지(지금은 명세대로 붙임), 부록 A에 1:1 문의(SCR-CSC-003) 행 없음 (LJS)
- 서비스 안내 후속 (LJS): M1에 결과가 있으면 목차 선택을 버려 R03·R08·R19를 놓친다(`docs/design/service-guide-search.md` 4-1절) — "M1과 목차 선택이 다르면 목차 선택을 앞에 붙이기"를 고치면 세 번째 세트로 다시 잰다. 로그인·비밀번호 찾기는 안내서 밖(R18). 안내서에 "대화창에 영수증 사진 올려 등록하기"(SCR-AIM-013) task가 없다(R03 사람 채점 틀림). 답변 정확도 24/27 맞음(4-1절). 실제 대화 로그·팀원 질문 평가는 아직
- 프론트에 알리기: `screenPaths.js`가 num 27 공동양육 관리를 라우트에 없는 `/mypage/caregivers`로 보냄(실제 화면은 `/mypage/pets` 카드 아래 가족 영역). 사용법 답변 바로가기(`done.shortcut`)가 SCR-MYP-004를 줄 수 있음. 2026-11-05 대조로 더 나온 것(`docs/guide-review.md` "프론트 대조"): 메인 [토탈 케어리스트] 해시 `#c-care` → `#hlt003-care`, 폭 760px 이하에서 회원정보 수정 가는 메뉴 없음, `/mypage/withdraw` 라우트 없음, 플레이스 회원 전용(96707a9)이 의도인지 확인
- 병합 순서: 백엔드 PR #149(LJS, 대표 이미지 저장·관리자 쿠키 시트 허용·`CharacterSpec.FACE` `(96, 32, 320, 320)`) 먼저 → AI `LJS` PR. 각자 로컬 DB에 `PIXEL_CHAR.WEAR_IMG_FILE_SN` ALTER(v0.13 (1)) (LJS 백엔드)
- 연결 남음: FN-ADM-070-02 관리자 프론트 아이템 등록 화면 (관리자 프론트): [굽기 지시 만들기](`POST /ai/items/bake-hints`)·[시험해 보기](`POST /ai/items/trial-preview`), 등록 성공 뒤 `POST /ai/items/{itemSn}/bake`를 `lastYn` true까지 반복(한 번 30~40초, 매 호출 전 토큰 갱신, 502면 멈춤)
- 연결 남음: FN-MYP-010-16 프론트 꾸미기 [장착] (SJM): Java `PUT equipped-items`(`hldItemSns`) 성공 뒤 `POST /ai/characters/{pixelCharSn}/equipped-image` `{itemSns}`(아이템 번호)
- 로컬 시험 데이터: 관리자 mbrSn 2(601 주양육자)의 petSn 1001 "시험복실"·pixelCharSn 601. 2026-11-04 문의 207을 복원(CHRC0009) 처리, 아이템 31(hldItemSn 1313)·1(1312) 구매
- 연결 남음: FN-MAN-006 Java 리포트 내부 API 2개 (LJS 백엔드): `GET /internal/ai/pets/{petSn}/health-report-input?baseYmd=`(분석 입력 + 최근 저장본 + `rfrshPsblYn`·`autoRgnrPsblYn`), `PUT /internal/ai/pets/{petSn}/health-report`(`inputHash`·`rfrshYn` 저장, 새로고침 1회·자동 재생성 5회 셈). 새 테이블이라 ERD 변경. 계약 초안은 `docs/api/internal.md`, 백엔드 PR과 함께 확정. 백엔드 `docs/api/issues.md` 4번(위젯 정의 없음)을 이 계약으로 닫는다
- 연결 남음: FN-MAN-006 메인 위젯 연결 (프론트): `AiReportCard.jsx`가 샘플 대신 `GET /ai/pets/{petSn}/health-report`를 부른다. `rptTtl`을 "{petNm}는 지금 ___"에, `tips`·`notice` 표시, `staleYn`이면 "최근 기록이 아직 반영되지 않았어요", `dataLackYn`이면 기록 유도, `rfrshPsblYn`으로 새로고침 버튼(`POST .../refresh`, 409 `HEALTH_REPORT_REFRESH_LIMIT`). 이름 받침에 따라 은/는("복실은"), 새로 만들 때 3~6초 걸려 로딩 표시(실제 LLM 측정)
- 각자 `.env.local`에 `HEALTH_REPORT_TIMEOUT_SEC=20` 추가(없어도 기본값 20) — 디스코드 `.env.local` 갱신
- 연결 남음: FN-AIM-010-06 프론트 [직접 입력] 영수증 연결 (LJS 프론트, 맨 먼저): frontend-11 세션에 전달함(2026-11-03, SCR-ADM-050 루프 중이라 사람이 그 대화에서 요청해야 반영). `ReceiptUploadModal.jsx` `onError`에서 `setFailedRecptSn(error.data?.recptSn ?? null)`, [직접 입력]이 넘기는 키 `rcptSn`을 받는 쪽 이름과 맞춤, 다시 촬영·닫기 때 초기화. 계약 변경이라 AI PR과 프론트 PR을 함께 낸다
- 연결 남음: FN-AIM-010-06 직접 입력 저장 뒤 영수증 상태 저장완료 (LJS 백엔드): `CheckupService.create(…, recptSn)`은 상태를 보지 않고 연결만 한다(상태 보고 실패로 분석중이어도 거절 안 함). 저장완료로 바꾸는지 확인([확인 필요] 명세 문구)
- 인식·0건인데 결과 보고가 실패한 경우(Java 4xx 그대로·502 `EXTERNAL_API_ERROR`)와 프론트 20초 가드가 먼저 끊은 경우는 `recptSn`이 없어 [직접 입력]이 연결 없는 기록이 된다(그대로 두기로 함) (LJS)
- 병합 대기: FN-MYP-031-05·03 Java 백엔드 PR #124(backend-95, 2026-11-03 올림, 4가지 모두 반영: `AIMC0027` 허용·가계부만 `petSn` 생략(다른 출처는 400 `INVALID_INPUT_VALUE`)·RECPT 출처 `AIMC0027` 저장·`checkCaregiver` 건너뜀, `ReceiptOcrResponse` `expndPlcusNm`·`expndClsfCd`(null 가능, `OCR_RSPNS_JSON`에 남음 확인), 가계부 완전 인식은 `expndPlcusNm`·`ckupYmd`·`recptAmt`로 보고 품목 0개 허용). AI PR #33은 이미 병합돼 #124 병합 전까지 develop에서 가계부 출처 인식은 Java가 거절한다. #124 병합 뒤 실제 가계부 영수증 1건으로 확인 (LJS 백엔드)
- 연결 남음: FN-MYP-031-03·05 프론트 가계부 (SJM): `src/features/expense/api.js` `recognizeReceipt` 가짜(`POST /receipts/recognize`) → `POST /ai/receipts`(form `ocrRqstSrcCd=AIMC0027`, `petSn` 없음). 응답 `data.ocr`의 `ckupYmd`·`recptAmt`를 `expndYmd`·`expndAmt`로, `expndPlcusNm`·`expndClsfCd`는 그대로. 0건은 값이 모두 null인 200, 504 `OCR_TIMEOUT`·502 `OCR_API_ERROR`는 "영수증을 읽지 못했어요"
- OCR 출력 모양(`app/ocr/clients.py` `ReceiptOutput`)에 필드를 더하면 Anthropic API가 400 "Schema is too complex"로 거절할 수 있다(2026-11-03 실측: 기본값 있는 필드 2개 추가로 모든 인식 실패, 가짜 LLM 테스트로는 안 잡힘). 필드를 더하면 실제 영수증으로 한 번 돌려 본다 (LJS)
- 개발 DB 정리: 2026-11-03 검증이 회원 1·반려동물 2의 RECPT 501·502(백엔드 #124 검증으로 505·508, SCR-AIM-010 검증으로 514 추가)와 원본 파일을 남겼다. 필요하면 지운다 (LJS 백엔드)
- 결정 남음: `bake-hints`의 그림 형식·10MB 오류는 `/ai/characters`와 같은 `FILE_TYPE_NOT_ALLOWED`·`FILE_SIZE_EXCEEDED`로 했다(기획은 `INVALID_REQUEST`) (LJS)
- 옛 흐름으로 만든 캐릭터는 맨몸 시트가 없어 `/preview`가 404 `PIXEL_CHARACTER_NOT_FOUND`다. 다시 만들어야 한다. 무료 재생성(FN-MYP-010-23)은 사진이 Java로 오지 않아 SCR-ADM-042 전에 계약을 정한다 (LJS 백엔드)
- 하네스 수정 PR 후보(공용): `verify-loop.sh guard`가 읽기 전용 비교(`git diff --no-index`)까지 막아 verify 절차와 어긋난다
- 굽기·합성 최적화: 굽기 26개 실측 1회 104.2초(동시 10, 아이템당 31.5~37.0초, 재시도 없음). 동시 13으로 올린 값은 미측정. 합성 1.4초는 시험 그림 값. 후보는 전용 스레드 풀(기본 풀은 CPU+4라 코어 9개 미만 서버에서 13이 안 나온다), 429 대기 후 재시도, OpenAI 계정 한도 확인, 이미지 품질 `low` (LJS)
- 고양이 꼬리 경계선·다리 사이 분홍 점: 원인 미확인(착용 지시 변경의 영향 포함). 정렬 2단계 탐색은 촘촘한 무늬에서 빗나갈 수 있고 그림체 샘플 1장으로만 확인 (LJS)
- 굽기 켜기: 팀 비용 결정(26개 기준 캐릭터당 약 $1.64), Java 시트 저장 연결 뒤. 켜기 전 access_token(30분) 만료 대책을 정한다: 만료 뒤 아이템은 비용을 내고도 저장·실패 표시가 안 되어 "안 구운 아이템"으로 남고, 성공 보고 401이면 결과를 잃고 작업은 시간 초과 실패가 된다 (LJS) — 관리자 전체 굽기는 2026-11-04 나눠 굽기로 해결, 회원 캐릭터 생성 뒤 굽기는 남음
- 백엔드(LJS): 신발을 안 넣기로 해서 공통코드 `MYPC0006`과 시드 신발 4개는 정리 대상이다(공통코드는 DB에서만 고친다) (LJS)
- DMS 모음: FN-MYP-010-13 겹침 순서(캐릭터 → 의상 → … → 머리장식) vs 합성 순서(머리 착용 바탕 위에 의상) (LJS)
- DMS 모음: FN-MYP-010-13 "고정 좌표로 겹쳐 표시" vs 서버 합성, FN-MYP-010-17 "기준 좌표 고정" vs 상단 보정(눈 y가 캐릭터마다 다를 수 있음), 얼굴 영역 값 변경 (LJS)
- 눈 찾기 위험: `dog_fluffy` 512 재검출이 눈이 아닌 쌍을 잡았다. 실제 배치 경로에서는 샘플 10건 모두 맞았으나, 틀리면 규격을 통과한 채 조용히 어긋난다. 검은 털은 하이라이트 기준이라 눈 높이가 몇 px 다를 수 있고 측정하지 않았다 (LJS)
- 약한 테스트: EXIF 제거·회전 테스트 입력에 EXIF가 없다. 고양이 분기는 가짜 저장소가 짝수 `petSn`일 때만 `PETC0002`를 준다(실제 값은 Java 연결 뒤 확인) (LJS)
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

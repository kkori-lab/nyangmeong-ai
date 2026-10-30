# LJS 핸드오프

## 지금 하는 것
SCR-AIM-004·005 대화창 · 서비스 범위 밖 질문 차단 (추가 요청) — 끝 (검증 통과, 사람 확인 2026-10-30. 룰 키워드에 걸린 물음꼴은 분류 LLM으로 서비스 범위 확인, 범위 밖은 FALLBACK + 범위 안내 문구(`OUT_OF_SCOPE_MESSAGE`), 뜻 없는 입력은 기존 폴백 문구. 추가-1~4: 가짜 Java 삭제, Python 3.12 대응, 범위 밖 문구, requirements.txt)
- 결정: 범위 밖 질문에 새 의도는 만들지 않는다. FALLBACK으로 보낸다(SCR-AIM-005 문구·칩·연속 실패 카운트 그대로). 근거 FN-AIM-005-07(부적절 입력도 같은 폴백). React 계약(`docs/api/chat.md` Intent·SSE)은 그대로
- 결정: 판정 위치는 ② 룰 매칭 뒤. 룰에 걸려도 물음꼴(방법·어떻게·알려줘·뭐야·왜·`?` 등, `data/routing.yaml` `question_markers`)이면 ③ AI 분류로 확인. 이동 지시(보여줘·가줘·열어 등)나 키워드만 있는 입력은 지금처럼 바로 ROUTE(LLM 호출 없음). 물음꼴 확인 중 분류 LLM 장애면 룰 결과로 ROUTE(룰 라우팅은 LLM 장애와 무관, FN-AIM-002-10 유지)
- 결정: (2026-10-30 LJS, 허용 목록 방식) 분류 프롬프트에 서비스 범위(반려동물 건강·케어·일정·병원·가계부 등 반려동물 지출, 이 앱 기능 사용법)를 적고, 범위 안이면 ROUTE·SEARCH, 나머지는 전부 기존 UNKNOWN → FALLBACK. 분류 결과 종류는 그대로(ROUTE·SEARCH·UNKNOWN), 새 값 없음. 걸린 룰 행 번호를 힌트로 주고, AI가 ROUTE·SEARCH면 그 결과대로
- FN-AIM-004-12·005-01·005-07 → `app/chat/clients.py`(`classify_system` 서비스 범위 규칙, `classify(text, hint)`), `app/chat/rules.py`(`is_question`), `app/chat/service.py` `judge`, `data/routing.yaml`(`question_markers`), `tests/chat/fakes.py`(가짜 분류기 힌트 기록), `tests/chat/test_intent.py`·`test_fallback.py`, `docs/api/chat.md` 메시지 전송 행 설명 한 줄(모양 변화 없음). 부를 API 없음. 완료 조건 — 명령: `sh scripts/check.sh` 통과, 테스트 ① "가계부 작성 방법 알려줘"(가짜 분류기 UNKNOWN) → FALLBACK·안내 저장 ② "가계부 보여줘"·"가계부" → 분류기 안 부르고 ROUTE SCR-MYP-030 ③ "반려동물 가계부 쓰는 법 알려줘"(가짜 분류기 ROUTE/SEARCH) → 그 결과대로 ④ 물음꼴 확인 중 분류기 장애 → 룰 ROUTE ⑤ 룰에 안 걸리는 범위 밖("파이썬 코딩 알려줘", 가짜 분류기 UNKNOWN) → FALLBACK. 화면: 서버를 띄워 Postman `POST /ai/conversations/{sn}/messages`로 ①②⑤의 `intent.kind`·`done.message` 확인(①⑤는 LLM 키가 있으면 real 분류)
- 새 의존성: 없음

### 추가 요청
| 번호 | 바꿀 파일 | 완료 조건 | 요청 |
| --- | --- | --- | --- |
| 추가-1 | `scripts/fake_backend.py`(삭제), `README.md` "사람 확인"의 가짜 Java 줄, `docs/convention/architecture.md` 전환 상태의 가짜 Java 문장, `handoff/LJS.md` 가짜 Java 주의 줄 | 명령: `sh scripts/check.sh` 통과, `grep -rn "fake_backend" app tests scripts docs README.md AGENTS.md --include=*.py --include=*.md` 출력 없음, `scripts/fake_backend.py` 없음. 화면: 없음(사람 확인은 실제 Java로) | 요청 2026-10-30 12:43 "가짜 자바는 삭제해" |
| 추가-2 | `pyproject.toml`(`requires-python = ">=3.12,<3.14"`, ruff `target-version = "py312"`), `uv.lock`(재생성), `AGENTS.md`·`README.md` 스택 줄(3.12·3.13), 3.12에서 안 되는 코드가 있으면 그 파일. `.python-version`은 3.13 그대로. requirements.txt는 만들지 않음(배포 때 `uv export`, 커밋 여부는 따로 정함) | 명령: `sh scripts/check.sh` 통과, `uv run --python 3.12 --isolated pytest` 통과. 화면: 없음 | 요청 2026-10-30 12:50 "파이썬 3.12도 대응 될 수 있도록 버전 범위 늘리고"(backend-90 요청: 배포 서버 CentOS Stream 8은 dnf python3.12까지) |
| 추가-3 | `app/chat/clients.py`(ClassifiedKind `OUT_OF_SCOPE`: 서비스 범위 밖 질문만, 뜻 없는 글자·욕설은 UNKNOWN 그대로), `app/chat/service.py`(범위 밖 안내 문구 `OUT_OF_SCOPE_MESSAGE` "반려동물 케어와 관련된 질문만 도와드릴 수 있어요. 반려동물이나 서비스 이용에 관해 물어봐 주세요."), `tests/chat/test_intent.py`·`test_fallback.py`·`test_llm_clients.py`·`test_messages.py`(새 테스트, 가짜 분류기에 `hint` 인자), `docs/api/chat.md` 설명. Intent는 FALLBACK 그대로(칩·연속 실패 카운트 같음, React 계약 그대로), 저장 문구만 다름 | 명령: `sh scripts/check.sh` 통과, 테스트: 범위 밖 분류면 FALLBACK·범위 밖 문구 저장, UNKNOWN이면 기존 폴백 문구. 화면: Postman으로 "가계부 작성 방법 알려줘"·"파이썬 코딩 알려줘" → `intent.kind` FALLBACK, `done.message.cnvrsCn` 범위 밖 문구, "ㅁㄴㅇㄹ" → 기존 폴백 문구 | 요청 2026-10-30 12:50 "차단 됐을 때 응답을 다르게 가자, 질문을 이해하지 못했어요…는 안맞는 거 같음" |
| 추가-4 | `requirements.txt`(새로, `uv export --no-dev --no-hashes --no-header --frozen`), `scripts/check.sh`(requirements.txt가 uv.lock과 같은지 확인 줄), `scripts/doctor.py` `check()`(같은 확인, check.sh 주석 규칙), `AGENTS.md` 의존성 줄(requirements.txt 같이 커밋) | 명령: `sh scripts/check.sh` 통과, requirements.txt를 한 줄 바꾸면 `sh scripts/check.sh`가 requirements.txt 단계에서 실패. 화면: 없음 | 요청 2026-10-30 13:50 "requirements.txt 커밋하고 check.sh에 확인 줄 넣어줘"(배포 워크플로가 서버에서 `pip install -r requirements.txt`, 워크플로 파일은 사람이 따로 맞춤) |

## 다음에 할 것
- 공용 하네스 PR 따로: `scripts/check.sh`(requirements.txt 확인 줄)·`scripts/doctor.py` `check()`(같은 확인)는 이번 기능 커밋에서 뺐다. 따로 PR로 올린다. `scripts/fake_backend.py` 삭제는 실수로 `bf28ade`(requirements.txt 커밋)에 같이 들어가 이미 푸시됨
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

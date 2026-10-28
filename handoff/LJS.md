# LJS 핸드오프

## 지금 하는 것
SCR-AIM-011 AI 대화창 (새 창) · 대화 저장 전환 (Java 내부 API) — 끝 (검증 통과 3회차, 사람 확인 2026-10-27 프론트 대화창·실제 Java 8080 기준)

기획 상태: 승인됨

- 고른 이유: 마일스톤을 기능명세서 v0.9(DMS, 2026-10-27)로 다시 만들었고, "대기" 맨 위다. "다음에 할 것" 맨 위(백엔드 PR 확인)는 이 저장소에서 코드로 할 일이 아니다.
- 경로: 한 세션. 큰 변경 조건 해당: 바꿀 파일 3개 이상, 새 서버 간 계약(Python → Java 대화 내부 API).
- 전제: Java 대화 내부 API가 아직 없다(경로 미정). **가짜 응답으로 먼저 만들고 나중에 연결**한다. 가짜는 테스트의 `httpx2.MockTransport`(`tests/chat/conftest.py`)와 사람 확인용 `scripts/fake_backend.py`에 둔다.
- **먼저 할 것 (사람 요청 2026-10-27): FN-AIM-011-03 인증 확인용 `GET /ai/me`.** DB 없이 프론트 로그인 → Python → Java `/internal/auth/check` → 200을 확인하려는 것. `app/chat/router.py`(또는 같은 `/ai` 접두사의 작은 라우터)에 `require_member`만 거쳐 `{mbrSn}`을 돌려주는 엔드포인트를 둔다. DB·저장소·암호화 의존성을 받지 않는다. `docs/api/chat.md`에 행 추가(응답 `{mbrSn: Long}`, 오류는 Java 인증 오류 그대로·502 `EXTERNAL_API_ERROR`). 부를 API: Java `GET /internal/auth/check`(백엔드, LJS, 있음).
  - 완료 조건 `명령:` 가짜 Java로 쿠키 있음 → 200 `data.mbrSn`, 쿠키 없음 → 401 Java 본문 그대로, Java 연결 실패 → 502. DB 설정이 비어 있어도 통과.
  - 완료 조건 `화면:` `.env.local`에 `BACKEND_BASE_URL=http://localhost:8080`만(DB 키 없이), 실제 Java·Python·프론트(`npm run dev`, Vite가 `/ai/`를 8000으로 넘김)를 띄우고 `localhost:5173`에서 로그인한 뒤 브라우저 콘솔 `fetch('/ai/me', {headers: {'X-Requested-With': 'XMLHttpRequest'}})` → 200과 내 `mbrSn`. 로그아웃 뒤 → 401. Java를 끄면 → 502.
- Java ai 도메인 요청: 아래 계약 초안을 백엔드 세션에 보냄(2026-10-27). 회신이 오면 경로·필드를 맞춘다.
- 계약 초안 먼저(구현 전, Java 담당 LJS 백엔드와 맞출 것): `docs/api/internal.md`에 Python → Java 행 4개를 추가하고 탈퇴 파기 행(`DELETE /internal/v1/members/{mbrSn}/conversations`)을 지운다. 경로는 기존 `/internal/auth/check`와 같은 버전 없는 형식. Java가 암호화·본인 대화 판정을 하고, Python은 `/internal/auth/check`로 얻은 `mbrSn`을 넘긴다.
  - `POST /internal/ai/conversations` 요청 `{mbrSn, petSn, cnvrsTtl, cnvrsCn}`, 응답 201 `ConversationSummary`. 방과 첫 메시지(사용자 역할)를 한 트랜잭션으로 저장.
  - `GET /internal/ai/conversations?mbrSn=&petSn=` 응답 `List<ConversationSummary>` (최신순, `petSn` 필터 규칙은 `/ai/conversations`와 같음).
  - `GET /internal/ai/conversations/{aiCnvrsRoomSn}?mbrSn=` 응답 `ConversationDetail`. 남의 대화·없는 번호 404 `NOT_FOUND`.
  - `DELETE /internal/ai/conversations/{aiCnvrsRoomSn}?mbrSn=` 응답 200. 남의 대화·없는 번호 404 `NOT_FOUND`.
  - DTO는 `docs/api/chat.md`의 `ConversationSummary`·`ConversationDetail`을 그대로 쓴다(`/ai/**` 응답 모양을 바꾸지 않음).
- FN-AIM-011-07·11·14 새 대화 생성·제목 생성·서버 저장: `app/chat/service.py`가 제목을 만든 뒤(기존 그대로, mock) 암호화 없이 저장소에 넘긴다. `app/chat/repository.py`의 `SqlConversationRepository`를 Java 내부 API를 부르는 구현으로 바꾼다(Protocol 유지, 반환을 평문 행으로). 부를 API: `POST /internal/ai/conversations`(LJS 백엔드, 가짜).
  - 완료 조건 `명령:` 생성 테스트에서 Java로 간 요청 본문에 `mbrSn`·`petSn`·제목·첫 메시지가 평문으로 있고, `/ai/conversations` 응답이 201 `ConversationSummary`.
- FN-AIM-011-08·09 펫 태그·목록: `GET /internal/ai/conversations` 호출(LJS 백엔드, 가짜). `petSn`을 쿼리로 그대로 넘긴다.
  - 완료 조건 `명령:` `petSn` 있음·없음 두 경우에 Java로 간 쿼리와 응답 배열이 맞음.
- FN-AIM-011-10 대화 선택: `GET /internal/ai/conversations/{sn}` 호출(LJS 백엔드, 가짜).
  - 완료 조건 `명령:` 메시지가 `msgSeq` 순으로 오고, Java 404는 본문 그대로 404 `NOT_FOUND`.
- FN-AIM-011-13 대화 삭제: `DELETE /internal/ai/conversations/{sn}` 호출(LJS 백엔드, 가짜).
  - 완료 조건 `명령:` 성공 200, Java 404는 그대로 404.
- Java 오류 처리(011 전체): Java가 준 4xx 오류 본문은 그대로 전달(인증 전환과 같은 방식), Java에 닿지 못하거나 5xx·시간 초과면 502 `EXTERNAL_API_ERROR`. `app/core/backend.py`의 공유 클라이언트를 쓴다.
  - 완료 조건 `명령:` Java 연결 실패 → 502 `EXTERNAL_API_ERROR` 테스트.
  - 완료 조건 `화면:` `scripts/fake_backend.py`에 대화 API 4개(메모리 저장)를 더하고, `.env.local`에 `BACKEND_BASE_URL`을 가짜(포트는 fake_backend 기본값)로 두고 Postman으로 생성 → 목록(`petSn` 필터) → 조회 → 삭제 → 다시 조회 404. 가짜를 끄면 502.
- 전환 전 코드 정리:
  - 삭제: `app/core/db.py`, `app/core/crypto.py`, `app/chat/internal_router.py`(탈퇴 파기, FN-AIM-011-19는 Java 몫으로 제외), `app/main.py`의 엔진·키 점검·내부 라우터 등록.
  - `app/core/config.py`: `app_profile`·`local_db_*`·`prod_db_*`·`conversation_enc_key`와 `db_*` 속성 삭제(DB 밖에서 쓰는 곳 없음 확인). `.env.local.example`의 해당 줄 삭제.
  - `scripts/doctor.py`: DB 키 점검·DB 접속·권한 확인(`db_keys`·`db_setup` 등) 삭제.
  - 완료 조건 `명령:` `grep -rn "sqlalchemy\|asyncmy\|cryptography\|app.core.db\|app.core.crypto" app scripts tests`가 비어 있음.
- 테스트 삭제·바꿈(승인 필요, 별도 커밋, 검사하던 코드 자체를 지우기 때문): `tests/chat/test_repository.py`, `tests/core/test_crypto.py`, `tests/core/test_db.py` 삭제. `tests/chat/test_conversations.py`의 탈퇴 파기 테스트 삭제, 나머지는 `FakeRepo` 대신 가짜 Java(`MockTransport`)로 바꾼다. 응답 기대값은 그대로.
- 문서: `AGENTS.md` 3번의 "전환 전 코드" 문장과 기술 스택의 SQLAlchemy·asyncmy·cryptography·pyjwt 문장, `docs/convention/architecture.md` 27행 "전환 상태"와 38행 `repository.py` 설명("SQL" → "저장 요청(Java 내부 API 호출)"), `docs/convention/config.md`의 DB·암호화 키, 루트 `README.md` "사람 확인"의 DB 설정. 새 내부 API 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번).
- 공통 완료 조건: `명령:` `sh scripts/check.sh` 종료 코드 0.

새 의존성: 없음. 대신 삭제 `uv remove sqlalchemy asyncmy cryptography` (전환 전 코드만 썼음). `pyjwt`는 이미 `pyproject.toml`에 없음.

### 추가 요청
| 추가-1 | `app/chat/repository.py`·`app/chat/router.py`·`app/chat/service.py`·`app/core/backend.py`, `tests/chat/conftest.py`·`tests/chat/test_conversations.py`, `scripts/fake_backend.py`, `docs/api/internal.md` | `명령:` 대화 API 4개가 Java로 보낸 요청에 브라우저 `Cookie` 원문이 있고 `mbrSn` 쿼리·본문이 없음. 목록·조회·삭제는 Python이 `/internal/auth/check`를 부르지 않고 Java 대화 API의 401·403(본문·`Set-Cookie`)을 그대로 전달. 생성만 제목 생성(LLM) 전에 `/internal/auth/check`로 막는다(비로그인 요청이 LLM 비용을 쓰지 않게). `화면:` 가짜 Java(쿠키로 회원 판정)로 생성 → 목록 → 조회 → 삭제, 쿠키 없이 목록 → 401 | 요청 2026-10-27 14:30 "쿠키 방식으로 가는 게 나을 것 같다"(대화 API에 `mbrSn` 대신 `Cookie` 전달) |
| 추가-2 | `app/chat/repository.py`, `tests/chat/test_conversations.py` | `명령:` Java 대화 API로 보내는 요청에 `X-Requested-With: XMLHttpRequest`가 있음(Java `RequestedWithFilter`가 `/internal/**`의 POST·DELETE에도 걸려 없으면 403). `화면:` 실제 Java(8080, 백엔드 `ai` 도메인)에 붙여 생성 201 → 목록 → 조회 → 삭제 200 → 다시 조회 404 | 요청 2026-10-27 15:00 "이제 실제 자바랑 붙이자" |
| 추가-3 | `app/core/errors.py`, `tests/chat/test_conversations.py` | `명령:` Java 오류를 전달할 때 JSON 본문의 `path`를 Python 요청 경로(`/ai/...`)로 바꾸고, 나머지 필드·상태·`Set-Cookie`는 그대로. `path`가 없는 본문은 바이트 그대로. `화면:` 실제 Java에서 삭제한 대화 조회 → 404 `path`가 `/ai/conversations/{번호}`, 쿠키 없이 목록 → 401 `path`가 `/ai/conversations` | 요청 2026-10-27 15:05 "내부 경로 노출은 막아야 하는 거 아니냐" |

## 다음에 할 것
- **결정 2026-10-27(사람): 영수증 OCR(검진·가계부)·채팅 영수증 분석·캐릭터 생성도 프론트 → Python 직접 호출(`/ai/...`).** 명세 기능 ID는 그대로(캐릭터는 마이페이지 SCR-MYP-010). DB는 여전히 Java만. 다음 `/start`에서 마일스톤을 다시 만든다(대기 맨 위는 SCR-AIM-004). 그 전에 `AGENTS.md` 2번, `docs/convention/architecture.md`, `docs/convention/milestone.md` "Python 몫" 표를 고친다.
  - Python 몫이 되는 AIM 기능(제안): FN-AIM-008-05 업로드 검증, 008-06 OCR(프론트용 노출·중복 차단), 008-07 서버 부분(15초·취소), 010-01, 013-02 분기, 013-04 분석 요청, 013-09 결과 요약 저장. 원본 보관(008-09·010-06·013-08)은 Python이 Java에 저장 요청. 009 확인·저장은 그대로 Java.
  - 정할 것: (1) 원본 이미지·RECPT·영수증 상태(AIMG01)와 캐릭터 이미지·생성 작업 상태를 Python이 Java에 저장하는 내부 API(백엔드에 요청) (2) 캐릭터 생성이 동기 응답인지 작업 번호 + 상태 조회인지 (3) Java `PythonOcrClient`·`PythonCharacterGenerator` 경유 흐름과 `/internal/v1/ocr`·`/internal/v1/character` 폐기 여부(백엔드 PR과 함께) (4) 검사결과지 PDF 분석(건강기록 SCR-HLT-005)을 Python으로 가져올지
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-AIM-011 FN-AIM-011-11 제목 생성 real 클라이언트 (LLM 제공자 Anthropic 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- `scripts/doctor.py`(DB 점검 삭제)·`scripts/fake_backend.py`(대화 API 가짜)는 이번 기획의 변경인데 end-check가 공용 하네스로 분류함. 커밋 방법은 사람이 정함(doctor.py를 빼면 삭제된 `app.core.db`를 import해 setup이 깨짐)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`), `verify-collect.sh:37-38` `case` 문법
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다

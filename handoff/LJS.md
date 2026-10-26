# LJS 핸드오프

## 지금 하는 것
SCR-AIM-011 AI 대화창 (새 창) · 인증 전환 (Java 확인 호출) — 끝 (검증 통과 1회차, 사람 확인 완료 2026-10-26, 가짜 Java 기준)

기획 상태: 승인됨

- 결정 1: 인증은 라우터 의존성으로 한다(미들웨어 아님). `architecture.md:16` 문구를 고친다. 결정: 추천안대로(승인)
- 결정 2: JWT 테스트·`make_token` 삭제를 승인, 별도 커밋. 결정: 승인
- 결정 3: 의존성 변경(`httpx2` 런타임으로, `pyjwt` 제거) 승인. 결정: 승인

- 고른 이유: "다음에 할 것" 맨 위(로그아웃한 access 토큰이 통함)는 2026-10-26 결정(요청마다 Java 확인, 캐시 없음)으로 이 전환이 해결한다. 대화 저장 전환은 Java API 경로가 미정(`docs/api/internal.md` "Python → Java")이라 범위 밖, 기능명세서 v0.9는 DMS에 아직 없음(검색 결과 v0.8뿐).
- FN-AIM-011-03 본창 세션 공유: `app/core/auth.py`의 `require_member`를 JWT 검증에서 Java 호출로 바꾼다. 요청의 `Cookie` 헤더 원문 + `X-Internal-Key: BACKEND_INTERNAL_KEY`로 `GET {BACKEND_BASE_URL}/internal/auth/check`(백엔드, `docs/api/internal.md` 행 그대로) → 200이면 `data.mbrSn`(int) 반환. 결과는 캐시하지 않는다. `require_requested_with`는 그대로.
  - Java 401·403: 새 예외 `BackendAuthError`(상태·본문 바이트·`Set-Cookie` 전부)로 올리고 `app/core/errors.py` 핸들러가 그대로 돌려준다(`AGENTS.md` 4번, 본문을 다시 만들지 않음).
  - 연결 실패·시간 초과·5xx·200인데 `data.mbrSn` 없음 → 502 `EXTERNAL_API_ERROR`("외부 서비스 호출에 실패했습니다. 잠시 후 다시 시도해 주세요.", `architecture.md:18`). `BACKEND_BASE_URL`이 비어도 502.
  - HTTP 클라이언트: `app/core/backend.py`에 `httpx2.AsyncClient`를 앱 lifespan에서 하나 만들고 의존성 `get_backend_client`로 꺼낸다. 시간 제한은 코드 상수 3초(새 환경변수를 만들지 않음).
  - `config.py`: `backend_base_url`·`backend_internal_key` 추가, `jwt_secret_base64` 삭제. `.env.local.example`·`scripts/doctor.py` "인증" 키를 `BACKEND_BASE_URL`·`BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`로.
  - 완료 조건: `명령:` tests/core/test_auth.py에서 `httpx2.MockTransport`로 (a) 200 → `mbr_sn`, Java로 간 요청에 `Cookie` 원문·`X-Internal-Key` 있음 (b) Java 401 `TOKEN_EXPIRED` → 같은 상태·본문 (c) Java 403 `MEMBER_INACTIVE` + `Set-Cookie` → `Set-Cookie`까지 같음 (d) 연결 실패·시간 초과 → 502 `EXTERNAL_API_ERROR` (e) Java 500·`mbrSn` 없는 200 → 502 (f) 기존 `X-Requested-With` 테스트 유지.
- tests/chat: `as_member`를 JWT 쿠키 대신 가짜 Java(MockTransport, 쿠키 값 → 회원 번호)로 바꾼다. 대화 API 테스트의 기대값은 바꾸지 않는다.
- 테스트 삭제(승인 필요, 별도 커밋): tests/core/test_auth.py의 JWT 테스트(서명 틀림·refresh·만료)와 tests/chat/conftest.py `make_token`. 검증하던 코드 자체를 지우기 때문이고, 같은 오류 경로는 위 (b)(c)가 Java 응답 기준으로 대신한다.
- 문서: `docs/api/README.md:19`·`docs/api/chat.md:5`의 "(전환 전 코드는 … JWT …)" 괄호, `docs/convention/config.md:17`의 `JWT_SECRET_BASE64`, `architecture.md:27` 전환 상태에서 JWT 부분을 지운다. `architecture.md:16`의 "미들웨어"는 "라우터 의존성"으로 고친다(아래 결정 1).
- 가짜로 먼저: Java `/internal/auth/check`는 MockTransport로 완료. `화면:` 확인용으로 `scripts/fake_backend.py`(`/internal/auth/check`만, 쿠키 `access_token=member-<번호>`면 그 번호, `expired`면 401 `TOKEN_EXPIRED`, `inactive`면 403 + 쿠키 삭제 `Set-Cookie`)를 두고 `BACKEND_BASE_URL`을 그쪽으로. 실제 Java 연결은 "다음에 할 것".
- 공통 완료 조건: `명령:` `sh scripts/check.sh` 종료 코드 0. `화면:` 가짜 Java를 띄운 상태로 Postman에서 목록 200, `expired` 쿠키 401 `TOKEN_EXPIRED`, `inactive` 쿠키 403 + `Set-Cookie`, 가짜 Java를 끄면 502.

새 의존성: `httpx2`를 dev에서 런타임으로 옮김(`uv remove --dev httpx2 && uv add httpx2`, 이미 설치된 2.16.0). `pyjwt` 제거(`uv remove pyjwt`, 쓰는 곳이 `auth.py`·`tests/chat/conftest.py`뿐). `pyproject.toml`·`uv.lock` 같이 커밋.

### 추가 요청

## 다음에 할 것
- 연결 남음: SCR-AIM-011 FN-AIM-011-03 실제 Java 연결 확인 (Spring의 키 제거 반영 뒤, LJS). `BACKEND_BASE_URL=http://localhost:8080`만 넣고 dev-tokens 쿠키로 `/ai/conversations` 200·쿠키 없음 401 확인. 백엔드 `/internal/auth/check`는 아직 커밋 전(백엔드 LJS 작업 트리)
- 다음 작업: 서버 간 `X-Internal-Key` 양방향 제거 (결정 2026-10-26, 사람). Spring 반영 알림을 받은 뒤 `/start`로. `/internal/auth/check` 호출의 헤더 제거, `INTERNAL_API_KEY` 검사(`app/core/internal_auth.py`) 제거, `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY` 정리, `AGENTS.md`(PR)·`docs/api/README.md`·`architecture.md`·`config.md` 계약 문구 수정. Spring 반영 전에 헤더를 먼저 빼면 실행 중인 Java가 401 `INVALID_INTERNAL_KEY`로 막는다(실측)
- 키 제거 전까지 주의: Java가 키 불일치에 401 `INVALID_INTERNAL_KEY`를 주는데 Python은 401을 그대로 브라우저에 넘긴다(`app/core/auth.py`). 키 제거로 이 코드가 없어지므로 따로 고치지 않음(결정 2026-10-26)
- 문서: 루트 `README.md` "사람 확인" 절이 아직 `JWT_SECRET_BASE64`를 말함. 가짜 Java(`scripts/fake_backend.py`)·`BACKEND_BASE_URL` 기준으로 고친다
- 연결 남음: SCR-AIM-011 제목 생성 real 클라이언트 (LLM 제공자·키 결정 뒤, LJS)
- 연결 남음: SCR-AIM-011 공용 DB 실행 확인 (Python 전용 DB 계정 수령 뒤, LJS). 로컬 DB는 검증에서 확인됨
- 연결 남음: SCR-AIM-011 대화창 화면과 연결 확인 (LJS 프론트)
- 결정 필요: SCR-AIM-011 없는 `petSn`으로 대화를 만들면 로컬 DB의 `FK_AI_CNVRS_ROOM_PET` 때문에 500(IntegrityError, 검증 실측). 기획의 "DDL에 FK 없음"은 `CREATE TABLE`만 보고 쓴 것이라 틀렸음(백엔드 `ALTER TABLE` 미확인). 400 `INVALID_REQUEST`로 바꿀지 정하고, 바꾸면 `docs/api/chat.md` 오류 목록도 고친다
- `CONVERSATION_ENC_KEY`는 백엔드 `app.crypto.aes-key-base64`와 같아야 함. 팀 공용 키가 확정되기 전에 쓴 로컬 대화는 키가 바뀌면 못 읽음. 공용 DB에 쓰기 전에 키 확정 확인
- 다음 마일스톤: SCR-AIM-002 대화창 · 검색 질문/응답 (`/start`로 시작)
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트 (API·키 팀 결정, LJS)
- 연결 남음: SCR-MYP-010 얼굴 영역 위치 검증·샘플 10건 이상 검증 (real 생성기 결정 뒤. 얼굴 추출은 프론트에서 먼저 시도, LJS)
- 연결 남음: Java `PythonCharacterGenerator` 신설·연결 (LJS 백엔드. 지금은 `FakeCharacterGenerator`뿐)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 연결 남음: Java `PythonOcrClient` 연결 확인 (LJS 백엔드)
- 하네스 수정 PR 후보(공용, 이번 커밋에서 뺌): `scripts/doctor.py` "인증" 키 변경·`scripts/fake_backend.py`(SCR-AIM-011 인증 전환분), `scripts/start-check.sh` 수정분, 그리고 macOS BSD `sed` 문제(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`)와 `verify-collect.sh:37-38`의 `case` 문법. 백엔드 `8b015d0`이 같은 종류를 고쳤는지 비교
- `docs/api/internal.md`는 mock이 Java `FakeOcrClient` 시나리오(`fake`, `fake-empty` 등)를 따른다고 적었으나 mock은 고정 응답 1개. 필요해지면 구현

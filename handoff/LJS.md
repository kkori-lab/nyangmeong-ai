# LJS 핸드오프

## 지금 하는 것
SCR-AIM-011 AI 대화창 (새 창) · 인증 전환 — 서버 간 키 양방향 제거와 실제 Java 연결 확인 — 끝 (검증 통과 1회차, 사람 확인 완료 2026-10-26, 실제 Java 8080 기준)

기획 상태: 승인됨

- 고른 이유: "다음에 할 것" 맨 위(실제 Java 연결 확인)에 둘째 줄(서버 간 `X-Internal-Key` 양방향 제거, 결정 2026-10-26)을 합친다(사람 요청 2026-10-26). 전제인 Spring 키 검사 제거는 실측으로 충족 추정: 키 헤더 없이 `GET http://localhost:8080/internal/auth/check` → 401 `UNAUTHORIZED`(`INVALID_INTERNAL_KEY` 아님).
- 경로: 한 세션(`.sap/config` 없음). 큰 변경 조건 해당: 바꿀 파일 3개 이상, 공개 계약(내부 키 헤더) 변경.
- FN-AIM-011-03 본창 세션 공유 (Python → Java): `app/core/auth.py`에서 `X-Internal-Key` 헤더를 빼고 `Cookie`만 보낸다. 부를 API: Java `GET /internal/auth/check`(백엔드, LJS), 쿠키 발급 `POST /api/auth/dev-tokens`(백엔드, LJS).
  - 완료 조건 `명령:` tests/core/test_auth.py에서 Java로 간 요청에 `Cookie` 원문이 있고 `X-Internal-Key`가 없음.
  - 완료 조건 `화면:` 실제 Java(8080), `.env.local`에 `BACKEND_BASE_URL=http://localhost:8080`, 로컬 DB 설정: (1) dev-tokens 쿠키로 `GET http://localhost:8000/ai/conversations` → 200 (2) 쿠키 없이 → 401 `UNAUTHORIZED`, Java 본문 그대로 (3) Java를 끄면 → 502 `EXTERNAL_API_ERROR`.
- 내부 API (Java → Python, `/internal/v1/ocr`·`/internal/v1/character`·`/internal/v1/members`): `app/core/internal_auth.py` 삭제, 세 라우터(`app/ocr/router.py`·`app/character/router.py`·`app/chat/internal_router.py`)에서 `require_internal_key` 의존성 제거.
  - 완료 조건 `명령:` 각 내부 API가 헤더 없이 정상 응답(기존 정상 경로 테스트에서 `KEY`·`INTERNAL` 헤더를 뺀 채 통과).
  - 완료 조건 `화면:` Postman에서 `X-Internal-Key` 없이 `POST http://localhost:8000/internal/v1/ocr/...` → 200(mock).
- 설정: `app/core/config.py`에서 `internal_api_key`·`backend_internal_key` 삭제, `.env.local.example` 두 줄 삭제, `scripts/doctor.py` "인증" 키를 `BACKEND_BASE_URL`만으로(커밋 안 된 기존 수정분 위에 이어서).
- 테스트 삭제·기대값 변경(승인 필요, 별도 커밋): 잘못된·빈 키 → 401 테스트(`tests/character/test_generate.py:76`, `tests/chat/test_conversations.py:177`, `tests/ocr/test_receipt.py:51`·`:62-65`), `tests/core/test_auth.py:53`의 키 헤더 단언을 "헤더 없음"으로. 검사하던 코드 자체를 지우기 때문.
- 문서·계약(백엔드 PR과 함께, `AGENTS.md` 4번): `AGENTS.md:13`·`:4번` 문구, `docs/api/README.md:20`, `docs/api/internal.md:15`, `docs/convention/architecture.md:25`, `docs/convention/config.md:13-14`·`:20`, 루트 `README.md:61`과 "사람 확인" 절의 `JWT_SECRET_BASE64`, `.claude/skills/verify/SKILL.md:52`·`.agents/skills/verify/SKILL.md:52`(공용 스킬). "nginx 밖에 둔다"는 남긴다.
- 공통 완료 조건: `명령:` `sh scripts/check.sh` 종료 코드 0.

새 의존성: 없음

### 추가 요청

## 다음에 할 것
- 계약 변경(서버 간 키 제거)은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번). 백엔드 `/internal/auth/check`가 커밋·PR됐는지 확인. Java의 Python 호출 클라이언트가 아직 `X-Internal-Key`를 보내도 Python은 무시한다
- 각자 `.env.local`에서 `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`를 지우고 `BACKEND_BASE_URL`을 넣는다(없으면 `/ai/**` 전부 502, 사람 확인에서 실측)
- 배포 확인: 키가 없어져 `/internal/**`는 Nginx에 열지 않는 것으로만 막힌다(`/internal/v1/members`는 회원 대화 파기). 운영 Nginx 설정이 `/internal`을 막는지 확인
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
- 하네스 수정 PR 후보(공용, 이번 커밋에서 뺌): `scripts/doctor.py` "인증" 키를 `BACKEND_BASE_URL`만으로·`scripts/fake_backend.py`(SCR-AIM-011 인증 전환분), `verify-collect.sh:18` `cut -c8-`가 멀티바이트 "시작 "을 잘못 자름, `scripts/start-check.sh` 수정분, 그리고 macOS BSD `sed` 문제(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`)와 `verify-collect.sh:37-38`의 `case` 문법. 백엔드 `8b015d0`이 같은 종류를 고쳤는지 비교
- `docs/api/internal.md`는 mock이 Java `FakeOcrClient` 시나리오(`fake`, `fake-empty` 등)를 따른다고 적었으나 mock은 고정 응답 1개. 필요해지면 구현

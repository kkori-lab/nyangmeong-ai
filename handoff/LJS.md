# LJS 핸드오프

## 지금 하는 것
SCR-AIM-011 AI 대화창 (새 창) · 대화 저장·조회·삭제 — 끝 (검증 통과 2회차, 사람 확인 완료 2026-10-25)

기획 상태: 승인됨

- 선행: `docs/api/chat.md` 신설(`docs/api/README.md` 분류표 링크 갱신). 아래 4개 `/ai/conversations` 행과 DTO(`ConversationCreateRequest`·`ConversationSummary`·`ConversationDetail`·`ConversationMessage`)를 구현 전에 먼저 쓴다. 경로 변수는 `{aiCnvrsRoomSn}`(README 규칙). `docs/convention/config.md`의 "백엔드와 같아야 하는 값"에 `CONVERSATION_ENC_KEY` = 백엔드 `app.crypto.aes-key-base64`(base64, 32바이트)를 추가한다(결정 2026-10-25: 백엔드 `FieldCryptoService`가 같은 컬럼을 이미 이 키·형식으로 암호화함, 시더 `AiSeeder.java:36,46`). 환경변수 이름은 `.env.local.example`·`doctor.py`에 이미 있는 `CONVERSATION_ENC_KEY`를 유지한다.
- FN-AIM-011-03 본창 세션 공유: `app/core/auth.py` 신설. 쿠키 `access_token`을 HS256(`JWT_SECRET_BASE64`)으로 검증하고 `typ=access`·`exp`를 본다. 성공하면 `sub`를 `mbr_sn`(int)으로 돌려주는 의존성. 토큰 없음/서명·형식 오류는 401 `UNAUTHORIZED`, 만료는 401 `TOKEN_EXPIRED`(백엔드 `JwtTokenProvider.parse`·`ErrorCode`와 같은 이름). `app/core/requested_with.py`: GET·HEAD·OPTIONS 밖의 `/ai/**` 요청에 `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`(백엔드 `RequestedWithFilter`와 같음). `config.py`에 `jwt_secret_base64`·`conversation_enc_key` 추가. 백엔드는 `sid`로 DB 세션을 다시 보지만 Python은 그 테이블을 못 읽으므로 서명·만료만 본다.
  - 완료 조건: `명령:` tests/core에서 (a) 정상 토큰 → `mbr_sn` (b) 쿠키 없음·서명 틀림·`typ=refresh` 401 `UNAUTHORIZED` (c) 만료 401 `TOKEN_EXPIRED` (d) DELETE에 헤더 없음 403 `FORBIDDEN`, GET은 헤더 없이 통과.
- FN-AIM-011-07·11·14 새 대화 생성·제목 자동 생성·서버 저장: `app/chat/{router,service,schemas,repository,clients}.py` 신설, `app/core/crypto.py`(AES-256-GCM 암복호화, 저장값 = 백엔드 `FieldCryptoService`와 같은 `v1.{nonce}.{암호문+태그}`, 각 부분 Base64URL 패딩 없음, nonce 12바이트·태그 128비트, `cryptography` 패키지 사용 — 이미 설치됨. 키가 비었거나 32바이트가 아니면 서버 시작 때 실패). `POST /ai/conversations` (`ConversationCreateRequest`: `petSn` Long 선택(null = 전체), `cnvrsCn` 필수 1~1000자·공백만 금지, LJS) → 201 `ConversationSummary` `{aiCnvrsRoomSn, petSn, cnvrsTtl, regDt}`. 서비스 순서: 제목 생성(clients `TitleGenerator` Protocol, mock은 첫 메시지 앞 30자) → 200자 넘으면 자름 → 제목·본문 암호화 → 한 트랜잭션에서 `AI_CNVRS_ROOM` INSERT + 첫 메시지 `AI_CNVRS_MSG`(`ROLE_CD` `AIMC0024` 사용자, `MSG_SEQ` 1) INSERT. AI 답변 생성과 이어지는 메시지 추가는 이 마일스톤 밖(SCR-AIM-002 등).
  - 완료 조건: `명령:` tests/chat에서 (e) 생성 → 201, 가짜 저장소에 방 1·메시지 1, 저장된 제목·본문이 평문이 아니고 복호화하면 원문. Java `FieldCryptoService`로 만든 암호문 1건을 고정값으로 테스트에 넣어 Python이 복호화한다(형식 호환 확인, 구현 때 jshell 등으로 생성) (f) 1001자·공백만 400 `INVALID_REQUEST` (g) 쿠키 없음 401.
- FN-AIM-011-08·09 펫 태그 · 목록 조회: `GET /ai/conversations?petSn=` → 200 `List<ConversationSummary>`, 본인(`MBR_SN` = 토큰 `sub`) 것만 `REG_DT` 내림차순. `petSn`을 주면 그 태그만(`PET_SN` NULL인 "전체" 대화는 안 나온다, 결정 2026-10-25), 안 주면 전부. 오늘·어제·지난 7일 그룹은 React가 `regDt`로 나눈다(브라우저 시간대 기준). 반려동물 칩 목록·대표 반려동물은 React가 Java에서 받는다(Python은 `petSn` 값만 저장, 소유권 판단 안 함 — `architecture.md` 경계).
  - 완료 조건: `명령:` (h) 회원 A·B 방이 섞인 가짜 저장소에서 A 목록에 B 방 없음, `petSn` 필터 동작, 최신순.
- FN-AIM-011-10 대화 선택: `GET /ai/conversations/{aiCnvrsRoomSn}` → 200 `ConversationDetail` = Summary + `messages: [{aiCnvrsMsgSn, roleCd, cnvrsCn, msgSeq, regDt}]`(`MSG_SEQ` 오름차순, 복호화). 남의 방·없는 방은 404 `NOT_FOUND`(존재 여부를 숨기려고 403 대신 404).
  - 완료 조건: `명령:` (i) 본인 방 → 메시지 평문 순서대로 (j) 남의 방·없는 번호 404 `NOT_FOUND`.
- FN-AIM-011-13 대화 삭제: `DELETE /ai/conversations/{aiCnvrsRoomSn}` → 200(`data` null). 한 트랜잭션에서 `AI_CNVRS_MSG` → `AI_CNVRS_ROOM` 순으로 물리 삭제(DDL에 FK·CASCADE가 없음 — 백엔드 `db/20261012_create_tables_v0.9.sql`). 남의 방·없는 방 404.
  - 완료 조건: `명령:` (k) 삭제 후 방·메시지 모두 없음 (l) 남의 방 404이고 그 방은 남아 있음 (m) 헤더 없음 403.
- FN-AIM-011-19 탈퇴 파기: 이미 문서에 있는 `DELETE /internal/v1/members/{mbrSn}/conversations` (`X-Internal-Key`, LJS 백엔드가 호출) → 200, 그 회원의 메시지·방 전부 물리 삭제, 없어도 200. 보관일수(`SYS_STNG.WHDWL_MBR_KPNG_DAY_CNT`) 경과 판단은 Java가 하고 부른다.
  - 완료 조건: `명령:` (n) A 회원 파기 → A 방·메시지 0, B는 그대로 (o) 대화 없는 회원 200 (p) 키 없음 401.
- 저장소: `repository.py`는 `ConversationRepository` Protocol + SQLAlchemy Core 구현. 테스트는 Protocol을 만족하는 메모리 가짜를 의존성 오버라이드로 넣는다(공용 DB에 붙지 않음, `AGENTS.md` 3번).
- 가짜로 먼저: 제목 생성 real(LLM 제공자·키 미정)은 mock 기준으로 완료, 연결은 "다음에 할 것". SQLAlchemy 구현은 Python 전용 DB 계정이 없어 실 DB 실행 확인 없이 단위 테스트(가짜 저장소)만으로 완료하고, 실 DB 확인은 "다음에 할 것".
- 공통 완료 조건: `명령:` `sh scripts/check.sh` 종료 코드 0. `화면:` 서버를 띄워 Postman에서 테스트용 JWT 쿠키로 생성 → 목록 → 상세 → 삭제가 순서대로 되고, 쿠키 빼면 401·헤더 빼면 403.

새 의존성: `PyJWT` (JWT 서명·`exp` 검증용, 결정 2026-10-25: 직접 구현 대신 라이브러리). `uv add PyJWT`로만 추가하고 `pyproject.toml`·`uv.lock`을 같이 커밋한다.

### 추가 요청

## 다음에 할 것
- 연결 남음: SCR-AIM-011 로그아웃한 access 토큰이 만료 전까지 `/ai/**`에서 통함. 백엔드는 `sid`로 DB 세션을 다시 보지만(`JwtAuthenticationFilter.java:65`) Python은 세션 테이블을 못 읽음. 팀 결정 필요(access 만료 시간 확인, 짧게 두기 / Java가 세션 확인 API 제공 — 후자는 "Python은 Java를 부르지 않는다" 위반이라 불가). 결정 2026-10-25: 이번엔 그대로 둠
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
- 하네스 수정 PR 후보(공용, 이번 커밋에서 뺌): `scripts/start-check.sh` 수정분, 그리고 macOS BSD `sed` 문제(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`)와 `verify-collect.sh:37-38`의 `case` 문법. 백엔드 `8b015d0`이 같은 종류를 고쳤는지 비교
- `docs/api/internal.md`는 mock이 Java `FakeOcrClient` 시나리오(`fake`, `fake-empty` 등)를 따른다고 적었으나 mock은 고정 응답 1개. 필요해지면 구현

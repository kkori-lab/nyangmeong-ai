# LJS 핸드오프

## 지금 하는 것
SCR-MYP-010 픽셀 캐릭터 관리 (생성 입력·규격) — 끝 (검증 통과 1회차, 사람 확인 완료 2026-10-25)

기획 상태: 승인됨

- FN-MYP-010-08 1단계 · 사진 첨부: `app/character/{router,service,schemas,clients,rules}.py` 신설(`rules.py`는 PNG 규격 검증 전용), `app/main.py`에 라우터 등록. 부를 API는 없음(내가 제공): `POST /internal/v1/character/generate` (multipart `CharacterGenerationRequest`: `photo` 필수·`petSeCd` 필수·`vrtyNm`·`colrNm`·`chrcCn` 선택, LJS) → 성공 시 본문 `image/png`(`ApiResponse` 껍데기 없음), 오류는 `ApiResponse`. `X-Internal-Key` 검사는 `app/core` 기존 것 재사용. `petSeCd`는 `PETC0001`(강아지)·`PETC0002`(고양이)만 받고 그 밖은 기존 검증 오류 응답(백엔드 `db/20261012_insert_com_cd_v0.9.sql:54-55`). 이미지 시그니처 판독은 `app/ocr/rules.py`의 `detect_image_type`을 `app/core/image.py`로 옮겨(결정 2026-10-25: 중복 대신 core 이동) OCR과 캐릭터가 같이 쓴다. `app/ocr/rules.py`는 이 함수뿐이라 삭제하고 `app/ocr/service.py:5` import만 바꾼다(동작 변경 없음, 기존 OCR 테스트가 회귀 확인). `photo`가 jpg·png·webp 시그니처가 아니면 400 `FILE_TYPE_NOT_ALLOWED`(구현 전에 `docs/api/internal.md` 캐릭터 행 오류 목록에 먼저 추가). `clients.py`는 `AI_MODE`로 mock/real을 고르는 Protocol, 이번에는 mock만.
  - 완료 조건: `명령:` `sh scripts/check.sh` 종료 코드 0, tests/character에서 (a) mock 요청 → 200·`image/png`·512×512 (b) `X-Internal-Key` 없음/틀림 401 (c) `photo` 비이미지 400 `FILE_TYPE_NOT_ALLOWED` (d) `photo`·`petSeCd` 누락 또는 `petSeCd`가 두 코드 밖이면 기존 검증 오류 응답. `화면:` 서버를 띄워 Postman으로 multipart 요청 → PNG 미리보기가 512×512로 보인다.
- FN-MYP-010-17 캐릭터 규격 고정: `schemas.py`에 `CharacterSpec`(캔버스 512×512, 얼굴 영역 x128·y64·w256·h256 — `docs/api/internal.md` mock 절 값) 상수. mock 클라이언트는 이 규격의 고정 PNG를 표준 라이브러리(`zlib`·`struct`)로 만들어 돌려준다(파일 커밋 없음).
  - 완료 조건: `명령:` (a)와 같음.
- FN-MYP-010-18 규격 일관성 검증: `rules.py`에 PNG 시그니처·IHDR 폭·높이를 읽어 `CharacterSpec`과 비교하는 함수. 서비스는 생성 결과가 규격 밖이면 502 `CHARACTER_SPEC_MISMATCH`, 클라이언트 예외는 502 `CHARACTER_API_ERROR`.
  - 완료 조건: `명령:` mock 클라이언트를 (511×512 PNG / PNG 아님 / 예외)로 바꿔 502와 두 코드가 구분돼 나온다.
- 가짜로 먼저: 이미지 생성 real 클라이언트는 API·키 미정이라 mock 기준으로 완료. 명세의 "착수 전 샘플 10건 이상 검증"과 얼굴 영역 위치 검증은 real 생성기가 정해진 뒤 "다음에 할 것".

새 의존성: 없음

### 추가 요청

## 다음에 할 것
- 다음 마일스톤: SCR-AIM-011 AI 대화창 · 대화 저장·조회·삭제 (`/start`로 시작)
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트 (API·키 팀 결정, LJS)
- 연결 남음: SCR-MYP-010 얼굴 영역 위치 검증·샘플 10건 이상 검증 (real 생성기 결정 뒤. 얼굴 추출은 프론트에서 먼저 시도, LJS)
- 연결 남음: Java `PythonCharacterGenerator` 신설·연결 (LJS 백엔드. 지금은 `FakeCharacterGenerator`뿐)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 연결 남음: Java `PythonOcrClient` 연결 확인 (LJS 백엔드)
- 하네스 수정 PR 후보(공용, 이번 커밋에서 뺌): `scripts/start-check.sh` 수정분, 그리고 macOS BSD `sed` 문제(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`)와 `verify-collect.sh:37-38`의 `case` 문법. 백엔드 `8b015d0`이 같은 종류를 고쳤는지 비교
- `docs/api/internal.md`는 mock이 Java `FakeOcrClient` 시나리오(`fake`, `fake-empty` 등)를 따른다고 적었으나 mock은 고정 응답 1개. 필요해지면 구현

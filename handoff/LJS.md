# LJS 핸드오프

## 지금 하는 것
SCR-AIM-008 영수증 OCR 인식·파싱 — 끝 (검증 통과 2회차, 사람 확인 완료 2026-10-25)

기획 상태: 승인됨

- FN-AIM-008-06 OCR API 호출: `app/ocr/{router,service,schemas,clients,rules}.py` 신설, `app/main.py`에 라우터 등록. 부를 API는 없음(내가 제공): `POST /internal/v1/ocr/receipt` (multipart `file`, LJS) → `ReceiptOcrResponse`(`ApiResponse.data`). `clients.py`는 `AI_MODE`로 mock/real을 고르는 Protocol, 이번에는 mock만. 공통으로 `app/core`에 `X-Internal-Key` 검사(틀리면 401)와 `ApiResponse` 껍데기·예외 변환을 함께 만든다.
  - 완료 조건: `명령:` `sh scripts/check.sh` 종료 코드 0, 그리고 tests/ocr에서 (a) mock 응답이 `ReceiptOcrResponse` 필드·`sections` 구조와 일치 (b) `X-Internal-Key` 없음/틀림 401 (c) 이미지로 안 읽히는 파일 거절. `화면:` 서버를 띄워 Postman으로 multipart 요청 → `ApiResponse` 껍데기 안 `data`에 mock 영수증.
- FN-AIM-010-01 인식 실패·일시 오류 판정(화면은 SCR-AIM-010): 추출 0건은 200 + 값 모두 null, `sections` 빈 배열. 분석 시간 초과 504 `OCR_TIMEOUT`, 외부 API 오류 502 `OCR_API_ERROR`(두 오류를 구분해 돌려준다). 시간 제한은 Java 15초보다 짧게 — 설정값 `OCR_TIMEOUT_SEC`.
  - 완료 조건: `명령:` 같은 테스트에서 mock 클라이언트를 (0건 / 지연 / 예외)로 바꿔 200·504·502와 코드가 나온다.
- 가짜로 먼저: Google Vision real 클라이언트는 서비스 계정 키가 없어 mock 기준으로 완료. real 연결은 "다음에 할 것".

결정(2026-10-25): 이미지 판독은 파일 시그니처(매직 바이트, jpg·png·webp)로 한다(Pillow 안 씀). 판독 불가는 400, `code`는 백엔드 `ErrorCode.FILE_TYPE_NOT_ALLOWED`와 같은 이름을 쓴다(구현 전에 `docs/api/internal.md` OCR 행 오류 목록에 먼저 추가). `OCR_TIMEOUT_SEC` 기본 12.

### 추가 요청
| 추가-1 | scripts/start-check.sh | 명령: `sh -n scripts/start-check.sh` 종료 코드 0 | 요청 2026-10-25 15:40 "1. ㅇㅇ 수정하고 다시 실행가자" (macOS sh에서 `case` 패턴 `)` 문법 오류, 패턴 앞에 `(` 추가) |

새 의존성: python-multipart (FastAPI `UploadFile` multipart 파싱에 필수, 이유: 현재 `pyproject.toml`에 없음).

## 다음에 할 것
- 다음 마일스톤: SCR-MYP-010 캐릭터 (`/start`로 시작)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 연결 남음: Java `PythonOcrClient` 연결 확인 (LJS 백엔드)
- 하네스 수정 PR 후보(공용, 이번 커밋에서 뺌): `scripts/start-check.sh` 수정분, 그리고 macOS BSD `sed` 문제(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`)와 `verify-collect.sh:37-38`의 `case` 문법. 백엔드 `8b015d0`이 같은 종류를 고쳤는지 비교
- `docs/api/internal.md`는 mock이 Java `FakeOcrClient` 시나리오(`fake`, `fake-empty` 등)를 따른다고 적었으나 mock은 고정 응답 1개. 필요해지면 구현

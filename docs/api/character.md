# 캐릭터 생성 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 픽셀 캐릭터 만들기(SCR-MYP-010 10-3)의 서버 부분을 다룬다.

- 인증: `chat.md`와 같다. 쿠키 `access_token`을 Java `/internal/auth/check`로 확인하고, 인증 오류는 본문·`Set-Cookie` 그대로, Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`. `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`.
- 흐름: 업로드 검증 → 생성기 준비 확인 → Java에 작업 생성(주양육자 여부·이미 캐릭터 있음·생성 중 판정, 등록된 품종·털색·특징을 돌려받음) → 202·작업 번호 → 응답 뒤 백그라운드 생성 → 512×512 규격 검증 → Java에 결과·상태 보고. Java 캐릭터 작업 내부 API는 아직 없어 가짜(`app/character/repository.py` `FakeCharacterJobRepository`)로 돈다(`internal.md` "Python → Java" 미정 행).
- 품종·털색·특징은 React가 보내지 않는다(FN-MYP-010-08 등록된 값 읽기 전용). 보내도 쓰지 않는다.
- 상태 조회·결과 자동 저장·완료 알림·실패 시 종별 기본 캐릭터 표시·멈춘 작업 정리는 Java가 한다. React는 상태를 Java에서 조회한다.
- 생성기(사진 분석 포함)는 다른 곳에서 만드는 것을 붙인다. 붙이기 전에는 502 `EXTERNAL_API_ERROR`다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/characters | 사진과 반려동물로 픽셀 캐릭터 생성을 시작한다. 202와 작업 번호를 바로 주고, 생성은 응답 뒤에 한다. 결과(성공이면 512×512 PNG, 실패면 `CHARACTER_API_ERROR`·`CHARACTER_SPEC_MISMATCH`)는 Java에 보고한다. 오류: 형식(확장자·실제 형식 불일치, PDF 포함) 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, `petSn`·`photo` 없음 400 `INVALID_REQUEST`(검증 실패는 Java 작업을 만들지 않는다), 생성기가 없음 502 `EXTERNAL_API_ERROR`(Java 작업을 만들기 전에 판정), 주양육자 아님·이미 캐릭터 있음·생성 중 등 Java 4xx 그대로, Java 연결 실패 502 `EXTERNAL_API_ERROR` | MYP-010-08·09·17·18 | LJS | CharacterCreateRequest | CharacterCreateResponse |

## DTO

### CharacterCreateRequest
쓰는 API: POST /ai/characters (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| photo | 파일 | Y | jpg·jpeg·png·webp, 10MB 이하. 확장자와 실제 형식(파일 시그니처)이 같아야 한다. PDF 불가 | MYP-010-08 |
| petSn | Long | Y | 캐릭터를 만들 반려동물. 주양육자 여부 검사는 Java가 작업 생성 때 한다 | MYP-010-08 |

### CharacterCreateResponse
쓰는 API: POST /ai/characters (202)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| chrcJobSn | Long | Y | Java가 만든 생성 작업 번호. 상태 조회에 쓴다. 이름은 Java 작업 테이블이 정해지면 맞춘다 | MYP-010-09 |

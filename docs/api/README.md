# 냥멍케어 AI API·DTO 명세 (초안)

AI 서버(이 저장소)의 API와 요청·응답 DTO다. **팀 확인 전 초안이다.** 필요한 파일만 연다. 기능 ID로 찾을 때는 `sh scripts/api-row.sh <기능 ID>`로 그 행과 DTO 절만 뽑는다.

## 분류표

| 영역 | 파일 | 호출자 | 담당 |
| --- | --- | --- | --- |
| 내부 API(OCR, 캐릭터 생성, Python이 부르는 Java API) | [`internal.md`](internal.md) | Java ↔ Python | LJS |
| AI 대화창 | [`chat.md`](chat.md) | React | LJS |

## 공통 규칙

- **구현된 API는 FastAPI 문서(`/docs`)가 정본이다.** 구현 전에는 이 문서를 먼저 고치고 코드를 고친다. 구현하면서 달라지면 같은 PR에서 이 문서도 고친다. Java·React 담당이 이 문서를 보고 부를 경로를 정하기 때문이다.
- 경로: React가 부르는 것은 전부 `/ai/...`(nginx가 접두사를 그대로 넘긴다), Java ↔ Python 서버 간 호출은 `/internal/v1/...`이다. 리소스는 복수형 kebab-case, 경로 변수는 그 테이블 일련번호 컬럼 이름의 camelCase다(백엔드 `docs/convention/api.md`와 같다).
- 응답 껍데기: 백엔드와 같은 `ApiResponse` `{timestamp, status, httpCode, message, path, code, data}`로 감싼다. 이미지 바이트를 돌려주는 API만 껍데기 없이 본문이 이미지다. 표의 응답 DTO는 `data`의 모양이다.
- 오류의 `code`는 오류 상수 이름이다(예: `OCR_TIMEOUT`). 받는 쪽은 `code`로만 분기하고 `message`로 분기하지 않는다.
- 필드 이름은 DB 약어 기반 camelCase다(백엔드 DTO와 같다). 읽지 못한 값은 `null`, 목록은 빈 배열이다.
- `/ai/**`: 요청마다 쿠키 `access_token`을 Java `/internal/auth/check`에 넘겨 인증한다(`architecture.md` "인증"). Java의 인증 오류(401 `UNAUTHORIZED`·`TOKEN_EXPIRED`, 403 `MEMBER_INACTIVE`)는 본문·`Set-Cookie`까지 그대로 전달하고, Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`다. 상태를 바꾸는 요청은 `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`이다. (전환 전 코드는 아직 JWT를 직접 검증한다.)
- `/internal/v1/**`(Java → Python): `X-Internal-Key` 헤더가 `.env.local`의 `INTERNAL_API_KEY`와 다르면 401 `UNAUTHORIZED`다. Python → Java 내부 API에는 `BACKEND_INTERNAL_KEY`를 같은 헤더로 보낸다(키는 방향마다 따로 둔다). 둘 다 외부(Nginx)에 열지 않는다.
- 필수: 요청은 반드시 보내야 하는 것, 응답은 항상 값이 있는 것(null 아님).

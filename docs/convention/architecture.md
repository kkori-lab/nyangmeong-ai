# 구조와 의존 방향

코드를 쓸 때, 파일·모듈을 새로 만들 때 연다. `AGENTS.md` "패키지 구조"에서 이어지는 문서다.

## 서비스 사이의 경계

```
React  ──▶ Java      비즈니스 API(일정·케어 항목 등록, 영수증 확인·저장, 캐릭터 작업 상태·이미지 조회 등)
React  ──▶ Python    /ai/**  AI 대화창, 영수증 OCR, 캐릭터 생성 요청, 검사결과지 PDF 분석
Python ──▶ Java      내부 API  인증 확인(/internal/auth/check), 대화 저장·조회, 원본·결과·작업 상태 저장
Java   ──▶ Python    /internal/v1/**  폐기 예정(2026-10-27). 코드·계약 삭제는 백엔드 PR과 함께
```

2026-10-26 결정: **DB는 Java만 다룬다.** Python은 DB에 붙지 않는 상태 없는 AI 서버다. AI 벤더 API(LLM·OCR·이미지 생성) 호출은 전부 Python이 한다. (10-25의 A안 — Python이 분석 단계 테이블을 소유 — 은 폐기됐다.) 배포는 nginx 한 도메인에서 `/api/`는 Java, `/ai/`는 Python으로 접두사를 자르지 않고 넘긴다. `/internal/**`와 `/health`는 nginx로 내보내지 않는다. 같은 오리진이라 CORS 설정은 필요 없다.

- **인증**: Python은 JWT를 검증하지 않고 키도 두지 않는다. 라우터 의존성(`app/core/auth.py` `require_member`)이 모든 `/ai/**` 요청에서 브라우저의 `Cookie` 헤더를 그대로 실어 Java `GET /internal/auth/check`를 부른다. 통과하면 `data { mbrSn, mbrAuthrtCd }`를 받는다. 결과는 캐시하지 않는다(로그아웃·정지가 바로 반영되어야 함). `/ai/**` 라우터를 새로 만들면 이 의존성을 빠뜨리지 않는다(미들웨어가 아니라 자동으로 붙지 않는다).
  - Java가 401(`UNAUTHORIZED`·`TOKEN_EXPIRED`)이나 403(`MEMBER_INACTIVE`)을 주면 상태 코드·`ApiResponse` 오류 본문·`Set-Cookie`를 다시 만들지 않고 그대로 브라우저에 전달한다. `MEMBER_INACTIVE`의 `Set-Cookie`가 쿠키를 지운다.
  - Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`("외부 서비스 호출에 실패했습니다. 잠시 후 다시 시도해 주세요.")를 준다.
  - `X-Requested-With` 검사(GET·HEAD·OPTIONS 외 `XMLHttpRequest` 필수, 없으면 403 `FORBIDDEN`)는 Python이 계속 한다. 인증 확인이 GET이라 Java의 같은 검사를 거치지 않기 때문이다.
  - Python은 토큰을 갱신·발급하지 않는다. `refresh_token`(`Path=/api/auth`)은 여기에 오지 않는다.
- **대화 저장**: 대화방·메시지 저장과 조회, 본인 대화 판정, 제목·본문 암호화는 Java가 한다. Python은 같은 `Cookie`를 실어 Java 내부 API를 부른다. AI 역할 메시지 추가는 내부 전용 경로로만 한다(React가 직접 부를 수 있으면 AI 답변을 꾸며 넣을 수 있다).
- **질문 한 번의 순서**: ① 사용자 메시지를 Java에 저장(여기서 실패하면 LLM을 부르지 않는다) → ② 최근 6턴·설정값으로 LLM 호출 → ③ SSE로 React에 흘려보냄 → ④ 답변을 멱등 키와 함께 Java에 저장(실패하면 재시도). 브라우저 연결이 끊겨도 ②~④는 끝까지 한다. 메시지 테이블은 INSERT 전용이라 미완료 행을 먼저 넣고 UPDATE하는 방식은 쓰지 않는다.
- **영수증·캐릭터·검사결과지 PDF** (2026-10-27 결정, 백엔드 흐름은 재설계 중): React가 Python `/ai/**`를 직접 부른다. Python은 업로드를 받아 인식·생성하고, 원본·결과·상태 저장은 Java 내부 API에 요청한다. 파일·DB 저장, 확인 모달 뒤 저장, 알림은 계속 Java가 한다. 저장·상태 내부 API는 아직 없다(백엔드 재설계 뒤 계약).
  - 영수증(SCR-AIM-008·010·013): 채팅 영수증 분석도 같은 경로다. 채팅 결과 요약은 Python이 대화 저장 내부 API로 남긴다.
  - 캐릭터(SCR-MYP-010): 작업 상태는 Java가 갖는다. ① Python이 Java에 작업 생성을 요청하고 React에 202·작업 번호를 준다 → ② Python이 백그라운드에서 생성한다 → ③ 결과·상태(성공·실패)를 Java 내부 API로 보낸다 → ④ React는 Java에서 상태를 조회한다. 생성 중 Python이 죽어 멈춘 작업의 타임아웃 정리는 Java가 한다.
  - 검사결과지 PDF(SCR-HLT-005, FN-HLT-005-04): 인식만 Python이 한다. 원본은 Java 첨부 자료에 있으므로 Python이 PDF를 받는 방법(React가 다시 올림 / Python이 첨부 번호로 Java에서 받음)은 마일스톤 기획에서 정한다.
- 채팅으로 만든 일정·케어 항목은 여기서 저장하지 않는다. 미리보기 카드를 돌려주고, React가 Java 일정 등록 API(`schdlSrcCd`='AI 생성')를 부른 뒤 결과(등록됨·취소됨)를 대화에 기록한다.
- **서버 간 호출**: 양방향 모두 키 없이 부른다(2026-10-26 결정). 내부 경로(`/internal/**`)는 외부(Nginx)에 열지 않는 것으로만 막는다.
- 개인 데이터(반려동물 기록 등)는 외부 AI API에 보내지 않는다(POL-006, FN-AIM-011-16).
- **전환 상태**: Python은 DB에 붙지 않는다(2026-10-27). 인증은 Java `/internal/auth/check`, 대화 저장·조회·삭제는 Java `/internal/ai/conversations`(초안, `docs/api/internal.md`)를 부른다. Java에 대화 API가 생기기 전에는 가짜 Java(`scripts/fake_backend.py`)로 확인한다. 탈퇴 회원 대화 파기는 Java가 자기 테이블에서 직접 한다.

## 패키지 안

기능 패키지(`chat`·`ocr`·`character`)는 필요한 만큼만 아래 파일로 나눈다. 처음부터 다 만들지 않는다.

| 파일 | 넣는 것 | 넣지 않는 것 |
| --- | --- | --- |
| `router.py` | FastAPI 라우터, 요청 검증, 응답 껍데기 | 업무 분기 |
| `service.py` | 흐름(판정 순서, 모델 호출, 저장 순서) | `Request` 객체 |
| `schemas.py` | 요청·응답 pydantic 모델 | DB 행 매핑 |
| `repository.py` | 저장 요청(Java 내부 API 호출). Python은 DB에 붙지 않는다 | 업무 판단 |
| `clients.py` | 외부 AI API 호출. `AI_MODE`에 따라 실제 구현과 mock 구현을 고른다 | 프롬프트 밖의 업무 규칙 |
| `rules.py` | 모델 없이 정해지는 규칙(키워드 매칭, 날짜 해석, 파싱) | 외부 호출 |

- 부록처럼 명세에서 오는 기준 데이터(라우팅 매핑표, 등록 판정 사전)는 코드가 아니라 `data/*.yaml`로 둔다. 명세가 바뀌면 그 파일만 고친다.
- 의존 방향: `router` → `service` → `repository`·`clients`·`rules`. 거꾸로 부르지 않는다. 모두 `core`를 쓸 수 있다.
- 외부 API 클라이언트는 같은 인터페이스(Protocol)로 실제·mock을 둔다. 테스트는 mock이나 가짜 객체로 돈다.

## 이름

- JSON 필드는 백엔드와 같은 DB 약어 기반 camelCase다(예: `hsptlNm`, `ckupYmd`). Python 속성은 snake_case로 쓰고 pydantic alias로 맞춘다.
- DB 컬럼·테이블 이름은 ERD 그대로 쓴다(대문자, 약어).
- 기능명세서 ID(`FN-AIM-002-07`)는 그 규칙을 구현한 함수의 주석에 적는다.

## 로그와 예외

- 로그에 질문·답변 원문, 토큰, 키, 영수증 원문을 남기지 않는다. 길이·건수·소요 시간만 남긴다.
- 외부 API 오류와 시간 초과는 구분해서 돌려준다(Java가 `TIMEOUT`·`API_ERROR`로 화면 문구를 나눈다, FN-AIM-010-07).

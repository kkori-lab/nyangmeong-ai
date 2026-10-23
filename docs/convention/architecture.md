# 구조와 의존 방향

코드를 쓸 때, 파일·모듈을 새로 만들 때 연다. `AGENTS.md` "패키지 구조"에서 이어지는 문서다.

## 서비스 사이의 경계

```
React  ──▶ Java      비즈니스 API 전부(일정 등록 포함)
React  ──▶ Python    /ai/**  AI 대화창
Java   ──▶ Python    /internal/v1/**  OCR 인식, 캐릭터 생성, 탈퇴 회원 대화 파기
Python ─X─▶ Java     호출 없음
```

- Python이 아는 것은 자기 API, 대화 테이블 2개, `SYS_STNG`의 AI 설정값(읽기), JWT 검증 키, 내부 호출 공유 키뿐이다.
- 회원·반려동물 데이터는 요청에 실려 온다(예: 채팅 요청의 `pets: [{id, name}]`). 그 값으로 저장 권한을 판단하지 않는다. 소유권은 Java가 저장할 때 다시 검사한다.
- 채팅으로 만든 일정·케어 항목은 여기서 저장하지 않는다. 미리보기 카드를 돌려주고, React가 Java 일정 등록 API를 부른 뒤 결과(등록됨·취소됨)를 여기에 기록한다.
- `ocr`·`character`는 결과만 돌려준다. 영수증·캐릭터 상태, 파일 저장, 알림은 Java가 한다.
- 개인 데이터(반려동물 기록 등)는 외부 AI API에 보내지 않는다(POL-006, FN-AIM-011-16).

## 패키지 안

기능 패키지(`chat`·`ocr`·`character`)는 필요한 만큼만 아래 파일로 나눈다. 처음부터 다 만들지 않는다.

| 파일 | 넣는 것 | 넣지 않는 것 |
| --- | --- | --- |
| `router.py` | FastAPI 라우터, 요청 검증, 응답 껍데기 | 업무 분기 |
| `service.py` | 흐름(판정 순서, 모델 호출, 저장 순서) | `Request` 객체 |
| `schemas.py` | 요청·응답 pydantic 모델 | DB 행 매핑 |
| `repository.py` | SQL(SQLAlchemy Core) | 업무 판단 |
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

# 냥멍케어 AI

냥멍케어의 AI 기능을 맡는 Python 서비스다. 업무 데이터 저장은 백엔드(`nyangmeong-backend`)가 맡는다.

| 패키지 | 맡는 일 | 호출자 |
|---|---|---|
| `app/chat` | AI 대화창 전체(답변, 제목, 의도 판정, 채팅 일정 등록 해석). 대화 저장은 Java 내부 API로 | React (`/ai/**`) |
| `app/ocr` | 영수증 인식·파싱 | Java (내부 API) |
| `app/character` | 픽셀 캐릭터 이미지 생성 | Java (내부 API) |
| `app/core` | 설정, Java 호출(인증 확인), 공통 응답 | — |

Java는 Python의 `/internal/v1/**`(OCR·캐릭터)를, Python은 Java의 `/internal/**`(인증 확인·대화 저장)를 부른다. Python은 DB에 붙지 않는다.

## 개발 환경

Git만 있으면 된다. setup이 Claude Code, uv, Python 3.13, 의존성, VS Code 확장, 커밋 훅, DMS MCP를 맞추고 서버가 뜨는지 확인한다. 여러 번 실행해도 된다.

```bash
bash setup.sh      # 맥
setup.bat          # Windows (cmd·PowerShell·탐색기 더블클릭)
```

`.env.local`이 없으면 `AI_MODE=mock`으로 만든다. 실제 값은 디스코드에서 받아 바꾼다.

## 실행

```bash
uv run uvicorn app.main:app --reload      # http://localhost:8000/health, API 문서 http://localhost:8000/docs
```

## 검사

```bash
sh scripts/check.sh      # ruff check, ruff format --check, pytest. CI와 하네스가 같은 파일을 쓴다
```

## AI로 작업하기

백엔드 저장소와 같은 하네스다(`/start` → `승인` → `/impl` → 사람 확인 → `/end`). 흐름 그림과 도구별 시작 방법은 백엔드 README "AI로 작업하기"에 있다. 이 저장소에서 다른 것만 적는다.

- 검증 명령은 `sh scripts/check.sh`다.
- 마일스톤은 Python 몫만 적는다(`docs/convention/milestone.md` "Python 몫"). 파일이 없으면 첫 `/start`가 만든다.
- 외부 AI API가 정해지지 않았거나 키가 없으면 `AI_MODE=mock`으로 먼저 만든다.

| 할 일 | 입력 |
| --- | --- |
| 다음 작업 시작 | `/start` |
| 특정 화면 시작 | `/start AIM-002` |
| 기획 승인 (구현·검증 루프 시작) | `승인` 또는 `/impl` |
| 다시 검증 (직접 고친 뒤) | `/verify` |
| 마무리 | `/end` → `확인` → `커밋` → `푸시` → (마일스톤이 끝나면) `PR`. 병합은 GitHub에서 사람이 |

### 사람 확인

`/impl`이 끝에 주는 "`/end` 전에 확인할 것"(직접 `/verify`를 돌렸으면 그 보고)의 "사람 확인" 목록대로 Postman 데스크톱 앱으로 확인한다.

1. 이 저장소에서 `uv run uvicorn app.main:app --reload` → `Application startup complete`가 나오면 준비 완료. 목록에 적힌 `AI_MODE`인지 `.env.local`을 확인한다.
2. 로그인이 필요한 `/ai/**` API면 백엔드 저장소에서 `./gradlew bootRun`을 띄우고 쿠키를 받는다.
   - `POST http://localhost:8080/api/auth/dev-tokens`, Headers `X-Requested-With: XMLHttpRequest`, Body → raw → JSON `{"mbrSn": <MBR에 있는 번호>}` → 200
   - 쿠키는 포트와 관계없이 `localhost`에 붙으므로 Postman이 `http://localhost:8000` 요청에도 실어 보낸다. 이 저장소 `.env.local`의 `BACKEND_BASE_URL`이 `http://localhost:8080`이어야 한다(Python이 쿠키를 Java에 넘겨 인증을 확인한다).
   - Java에 아직 없는 내부 API(대화 저장 등)는 가짜 Java로 확인한다: `uv run uvicorn scripts.fake_backend:app --port 8081`, `BACKEND_BASE_URL=http://localhost:8081`, 쿠키는 Postman에서 `access_token=member-<번호>`를 직접 넣는다.
3. 내부 API(`/internal/v1/**`)는 키 헤더 없이 보낸다. 파일은 Body → form-data에서 필드 종류를 File로 바꿔 고른다.
4. 목록의 요청을 그대로 보낸다: 메서드·URL, Headers, Body. POST·PUT·PATCH·DELETE의 `/ai/**` 요청에는 `X-Requested-With: XMLHttpRequest`를 넣는다.
5. 응답 코드와 JSON(또는 이미지)을 기대 결과와 비교한다. 스트리밍 응답은 Postman 응답 창에 이벤트가 차례로 쌓이는지 본다.
6. Postman으로 만들기 어려운 조건(만료 토큰, 외부 API 시간 초과 등)은 목록의 테스트로 확인한다: `uv run pytest <파일>::<테스트 이름>`
7. 확인용으로 만든 대화는 목록의 정리 방법대로 지운다(실제 Java면 공용 DB에 남는다).
8. 목록의 "바뀐 파일"을 훑어본다. 기획에 없는 파일이면 문제로 답한다.
9. Ctrl+C로 끈다.

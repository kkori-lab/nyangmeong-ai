# 냥멍케어 AI 컨벤션

이 저장소에서 코드를 쓰는 사람과 AI 도구가 따르는 규칙이다. 이 파일에는 항상 필요한 규칙만 두고, 나머지는 `docs/convention/`에 있다("나머지 규칙이 있는 곳").

- Codex는 이 파일을 자동으로 읽는다. Claude Code는 `CLAUDE.md`의 `@AGENTS.md` 한 줄로 읽는다. 그 줄을 지우면 규칙이 통째로 빠진다.
- 이 파일은 AI 도구가 매번 통째로 읽으므로 짧게 유지한다. 특정 작업에만 필요한 규칙은 `docs/convention/`에 쓴다.

## 코드를 쓰기 전에 꼭 알 것

어기면 되돌리기 어렵거나 오류 없이 조용히 잘못되는 것만 모았다.

1. **비밀값을 커밋하지 않는다.** 이 저장소는 공개다. 키·비밀번호·토큰·서버 주소는 git에 올리지 않는 `.env.local`(디스코드로 공유)에만 넣는다. 영수증·반려동물 사진 원본도 올리지 않는다. (`docs/convention/config.md`)
2. **Python은 상태 없는 AI 서버다.** 외부 AI 벤더 API(LLM·OCR·이미지 생성) 호출만 여기서 하고, 저장·인증·소유 검사는 Java가 한다(2026-10-26 결정). React는 AI 채팅·영수증 OCR·캐릭터 생성·검사결과지 PDF 분석을 `/ai/**`로 부르고, 원본·결과·작업 상태 저장은 Python이 Java 내부 API로 요청한다(2026-10-27 결정). Java가 부르던 `/internal/v1/**`는 폐기 예정이다(코드·계약 삭제는 백엔드 PR과 함께). 서버 간 호출은 키 없이 하고 nginx 밖에 둔다(2026-10-26 결정). (`docs/convention/architecture.md`)
3. **DB에 붙지 않는다.** 읽기도 하지 않는다. 대화 저장·조회, 설정값은 Java 내부 API로 한다(`docs/api/internal.md` "Python → Java"). 대화 암호화도 Java가 한다.
4. **백엔드와 맞춘 계약을 혼자 바꾸지 않는다.** OCR 응답(`ReceiptOcrResponse`), 캐릭터 규격(512×512, 얼굴 영역), 응답 껍데기(`ApiResponse`), `X-Requested-With` 검사, Java 인증 오류(본문·`Set-Cookie`)를 그대로 전달하는 규칙은 백엔드 코드와 같아야 한다. 어긋나면 오류 없이 조용히 깨진다. 바꾸려면 백엔드 PR과 함께 낸다. (`docs/api/README.md`)
5. **테스트에서 외부 AI API를 부르지 않는다.** 앱에는 실제 클라이언트만 두고, 테스트는 `tests/`의 가짜 객체를 끼운다(`tests/conftest.py`가 키를 비운다). 키가 없는 CI에서도 통과해야 한다.
6. **테스트를 끄거나 지워서 통과시키지 않는다.** (`docs/convention/test.md`)

## 기술 스택과 편집기

Python 3.13, FastAPI, pydantic-settings, uv, ruff, pytest. Docker는 쓰지 않는다. Java 호출은 httpx2.

- VS Code로 작업한다. 저장할 때 Ruff로 포맷한다(`.vscode/settings.json`). 줄바꿈은 LF, 한 줄 100자다.
- 의존성은 `uv add`·`uv remove`로만 바꾼다. `pyproject.toml`과 `uv.lock`을 같이 커밋한다.

## 패키지 구조

```
app/
├─ main.py         앱 생성, 라우터 등록
├─ core/           설정, 인증(Java 확인 호출), 공통 응답·예외. 기능 패키지를 모른다
├─ chat/           AI 대화창(SCR-AIM-001·002·004·005·011·012). React가 /ai/** 로 부른다
├─ ocr/            영수증 인식·파싱. React가 /ai/** 로 부른다(전환 전). 저장은 Java 내부 API로
├─ character/      캐릭터 이미지 생성. React가 /ai/** 로 부른다(전환 전). 작업 상태·저장은 Java 내부 API로
└─ checkup/        검사결과지 PDF 분석(SCR-HLT-005). React가 /ai/** 로 부른다. 저장하지 않는다
tests/             app/ 과 같은 폴더 구조
scripts/           setup 점검(doctor.py), 검증 명령(check.sh), 하네스 스크립트
```

- 기능 패키지(`chat`·`ocr`·`character`·`checkup`)는 `core`만 쓴다. 기능 패키지끼리는 import하지 않는다.
- 기능 패키지 안의 파일 나누기는 `docs/convention/architecture.md`에 있다.

## 나머지 규칙이 있는 곳

아래 파일은 자동으로 읽히지 않는다. 해당하는 일을 하기 전에 그 파일만 연다.

| 이럴 때 | 읽는 파일 |
| --- | --- |
| 코드를 쓸 때 항상, 파일·모듈을 만들 때 | `docs/convention/architecture.md` |
| API 경로·요청·응답을 정할 때(기획 포함) | `docs/api/README.md`, `docs/api/<영역>.md`에서 기능 ID로 검색한 행과 그 DTO |
| 테스트를 쓰거나 실패한 테스트를 고칠 때 | `docs/convention/test.md` |
| 설정 파일·비밀값·환경변수를 다룰 때, 핸드오프를 쓸 때 | `docs/convention/config.md` |
| 브랜치·커밋·PR을 만들 때 | `docs/convention/git.md` |
| 내 담당 화면·API를 마일스톤으로 나눌 때 | `docs/convention/milestone.md` |

## AI 도구 작업 방식

사용량 한도가 있는 플랜을 쓰는 팀원이 있어 토큰을 아낀다.

- 이 파일은 이미 읽혀 있으므로 다시 읽지 않는다. `docs/convention/`은 위 표에서 해당하는 파일만 연다.
- 파일은 필요한 부분만 읽는다. 위치를 모르면 먼저 검색하고 그 주변만 읽는다. `.venv/`, `.cache/`, `__pycache__/`는 읽지 않는다.
- 검증 명령은 `sh scripts/check.sh`다(ruff check, ruff format --check, pytest). 실패한 부분만 본다. `/end`가 이 명령의 종료 코드가 0이 아니면 마일스톤을 끝내지 않는다.
- `화면:` 완료 조건은 서버를 띄워(`uv run uvicorn app.main:app --reload`) Postman으로 요청을 보내 확인한다. 방법은 README "사람 확인"에 있다.
- 기능 구현은 기획(`/start`, Opus) → 사람 승인(`승인` 또는 `/impl`) → 구현과 검증 루프(`/impl`: 구현은 Sonnet, 검증은 대화를 보지 않는 별도 에이전트 Opus, `실패`면 고쳐서 최대 3회, 그래도 실패면 사람에게 넘긴다) → 사람 확인(README "사람 확인") → `/end` 순서다. 첫 검증 실패 뒤에는 기준 파일(기획·검증 명령·의존성·테스트)을 고칠 수 없다(`scripts/verify-loop.sh` 훅). 세션을 끊어도 잠금은 보관됐다가 이어지고, 루프를 버리는 것(`clear`)은 사람만 한다. 예외는 `/end`가 사람 확인을 거쳐 마일스톤을 `끝`으로 판정할 때 보관된 루프를 버리는 것이다. 기획이 승인되기 전에는 코드를 쓰지 않는다. 승인된 뒤 사람이 기획에 없는 것을 요청하면 다시 기획하지 않고, 고치기 전에 `handoff/<이름>.md`의 `### 추가 요청`에 먼저 적는다(형식은 `.claude/skills/impl/SKILL.md` 6번). `/impl` 밖의 대화에서 요청받아도 같다.
- 몇 개 파일로 끝나는 일에는 서브에이전트를 쓰지 않는다. 서브에이전트도 사용량을 쓴다.
- 작업 하나가 끝나면 `/end`로 핸드오프를 남기고 `/clear`한 뒤, 다음 작업은 `/start`로 시작한다.
- 개인 지시는 `CLAUDE.local.md`, 개인 설정은 `.claude/settings.local.json`, 개인 명령은 `~/.claude/skills/my-<이름>/`에 둔다(모두 git 제외). 저장소의 `.claude/skills/`는 공용이라 PR로만 바꾼다.
- 개인 지시는 일하는 방식(설명·기획 형식·말투)만 바꾼다. 기획 승인 → 검증 → 사람 확인 → `/end` 흐름과 이 파일의 규칙이 개인 지시보다 우선한다.

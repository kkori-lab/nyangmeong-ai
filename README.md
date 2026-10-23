# 냥멍케어 AI

냥멍케어의 AI 기능을 맡는 Python 서비스다. 업무 데이터 저장은 백엔드(`nyangmeong-backend`)가 맡는다.

| 패키지 | 맡는 일 | 호출자 |
|---|---|---|
| `app/chat` | AI 대화창 전체(답변, 제목, 의도 판정, 채팅 일정 등록 해석). 대화 테이블 소유 | React (`/ai/**`) |
| `app/ocr` | 영수증 인식·파싱 | Java (내부 API) |
| `app/character` | 픽셀 캐릭터 이미지 생성 | Java (내부 API) |
| `app/core` | 설정, DB, 인증 검증, 공통 응답 | — |

호출은 Java → Python 한 방향이다. Python은 Java를 부르지 않는다.

## 개발 환경

Git만 있으면 된다. setup이 Claude Code, uv, Python 3.13, 의존성, VS Code 확장, 커밋 훅, DMS MCP를 맞추고 서버가 뜨는지 확인한다. 여러 번 실행해도 된다.

```bash
bash setup.sh      # 맥
setup.bat          # Windows (cmd·PowerShell·탐색기 더블클릭)
```

`.env.local`이 없으면 `AI_MODE=mock`으로 만든다. 실제 값은 디스코드에서 받아 바꾼다.

## 실행

```bash
uv run uvicorn app.main:app --reload      # http://localhost:8000/health
```

## 검사

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

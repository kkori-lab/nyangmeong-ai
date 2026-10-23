# 냥멍케어 AI

냥멍케어의 AI 기능을 맡는 Python 서비스다. 업무 데이터 저장은 백엔드(`nyangmeong-backend`)가 맡는다.

| 패키지 | 맡는 일 | 호출자 |
|---|---|---|
| `app/chat` | AI 대화창 전체(답변, 제목, 의도 판정, 채팅 일정 등록 해석). 대화 테이블 소유 | React (`/ai/**`) |
| `app/ocr` | 영수증 인식·파싱 | Java (내부 API) |
| `app/character` | 픽셀 캐릭터 이미지 생성 | Java (내부 API) |
| `app/clients` | Java 내부 API 호출 | — |
| `app/core` | 설정, DB, 인증 검증, 공통 응답 | — |

## 실행

[uv](https://docs.astral.sh/uv/)가 Python 3.13과 의존성을 설치한다.

```bash
uv sync                                   # Python 3.13 + 의존성 설치
cp .env.local.example .env.local          # 값은 디스코드에서 받는다. 없으면 AI_MODE=mock 으로 뜬다
uv run uvicorn app.main:app --reload      # http://localhost:8000/health
```

## 검사

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

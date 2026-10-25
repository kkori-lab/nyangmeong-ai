from typing import Annotated, Protocol

from fastapi import Depends

from app.core.config import AiMode, Settings, get_settings

MOCK_TITLE_LENGTH = 30


class TitleGenerator(Protocol):
    async def generate(self, first_message: str) -> str: ...


class MockTitleGenerator:
    # AI_MODE=mock 전용 : LLM 없이 첫 메시지 앞부분을 제목으로 쓴다
    async def generate(self, first_message: str) -> str:
        return first_message.strip()[:MOCK_TITLE_LENGTH]


def get_title_generator(settings: Annotated[Settings, Depends(get_settings)]) -> TitleGenerator:
    if settings.ai_mode is AiMode.MOCK:
        return MockTitleGenerator()
    # LLM 제공자·키 미정 : 결정 후 연결
    raise NotImplementedError("제목 생성 real 모드는 아직 연결되지 않았습니다")

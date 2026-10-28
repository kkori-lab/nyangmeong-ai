"""사람 확인용 LLM 실제 호출. .env.local의 LLM_API_KEY로 Anthropic API를 부른다(비용이 든다)

돌리기: uv run python -m scripts.llm_smoke
pytest가 모으지 않는다(tests/ 밖). 테스트·CI에서 부르지 않는다(AGENTS.md 5번)
"""

import asyncio
import logging
import time

from app.chat.clients import (
    AnthropicIntentClassifier,
    AnthropicTitleGenerator,
    get_anthropic_client,
)
from app.core.config import get_settings

TITLES = [
    "우리 강아지가 어제부터 밥을 안 먹어요. 병원에 가야 할까요?",
    "고양이 예방접종 언제 맞혀야 하는지 정리해 주세요",
]
# 룰에 안 걸리는 이동 · 질문 · 뜻 없는 글자 · 욕설
INTENTS = [
    "근처에 아이 데리고 갈 만한 곳 보여줘",
    "강아지 포도 먹어도 돼?",
    "ㅁㄴㅇㄹ",
    "바보야",
]


async def main() -> None:
    settings = get_settings()
    client = get_anthropic_client(settings)
    print(f"모델: {settings.llm_model}")
    titles = AnthropicTitleGenerator(client, settings.llm_model)
    for text in TITLES:
        started = time.monotonic()
        title = await titles.generate(text)
        print(f"[제목] {text} → {title} ({(time.monotonic() - started) * 1000:.0f}ms)")
    classifier = AnthropicIntentClassifier(client, settings.llm_model)
    for text in INTENTS:
        started = time.monotonic()
        result = await classifier.classify(text)
        detail = f" {result.scr_id} {result.param or ''}" if result.scr_id else ""
        elapsed = (time.monotonic() - started) * 1000
        print(f"[분류] {text} → {result.kind}{detail} ({elapsed:.0f}ms)")


if __name__ == "__main__":
    # 실패하면 clients.py가 남기는 경고(실패 종류)를 보이게
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())

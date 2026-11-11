"""사람 확인용 LLM 실제 호출. .env.local의 LLM_API_KEY로 Anthropic API를 부른다(비용이 든다)

돌리기: uv run python -m scripts.llm_smoke
pytest 수집 제외(tests/ 밖), 테스트·CI에서 미호출(AGENTS.md 5번)
"""

import asyncio
import logging
import time

from app.chat import rules, tools
from app.chat.clients import (
    AnswerError,
    AnthropicTitleGenerator,
    AnthropicToolAgent,
    ClassifyError,
    get_anthropic_client,
)
from app.chat.repository import get_ai_settings
from app.core.config import get_settings
from tests.chat.fakes import fake_catalog

TITLES = [
    "우리 강아지가 어제부터 밥을 안 먹어요. 병원에 가야 할까요?",
    "고양이 예방접종 언제 맞혀야 하는지 정리해 주세요",
]
# 이동 · 질문 · 뜻 없는 글자 · 욕설
INTENTS = [
    "근처에 아이 데리고 갈 만한 곳 보여줘",
    "강아지 포도 먹어도 돼?",
    "ㅁㄴㅇㄹ",
    "바보야",
]
# 이어지는 질문 : 앞 대화를 맥락으로 쓰는지 본다
ANSWER_CONTEXT = [
    {"role": "user", "content": "강아지 포도 먹어도 돼?"},
    {"role": "assistant", "content": "포도는 강아지에게 위험해요. 소량이라도 먹이지 마세요."},
    {"role": "user", "content": "그럼 건포도는?"},
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
    # 도구 고르기 : 도구 목록은 테스트와 같은 가짜 Java 목록(Java는 부르지 않는다)
    tools.use_catalog(fake_catalog())
    agent = AnthropicToolAgent(client, settings.llm_model)
    max_tokens = get_ai_settings().max_tokens
    today = rules.today_kst()
    for text in INTENTS:
        started = time.monotonic()
        try:
            decision = await agent.decide(
                [{"role": "user", "content": text}], max_tokens, today, rules.match_route(text)
            )
        except ClassifyError as error:
            print(f"[도구] {text} → 실패: {error.reason}")
            continue
        elapsed = (time.monotonic() - started) * 1000
        if decision.call is not None:
            picked = f"{decision.call.name} {decision.call.raw}"
        else:
            picked = "글 답변" if decision.text is not None else "빈 응답"
            if decision.text is not None:
                await decision.text.aclose()
        print(f"[도구] {text} → {picked} ({elapsed:.0f}ms)")
    # SCR-AIM-002 답변 스트리밍 : 첫 글자·전체 시간(제한 10초·60초)과 답변 길이
    started = time.monotonic()
    first_ms = None
    chunks = []
    try:
        decision = await agent.decide(ANSWER_CONTEXT, max_tokens, today)
        if decision.text is None:
            name = decision.call.name if decision.call else "빈 응답"
            print(f"[답변] 글 답변 대신 {name}")
        else:
            async for chunk in decision.text:
                if first_ms is None:
                    first_ms = (time.monotonic() - started) * 1000
                chunks.append(chunk)
    except (ClassifyError, AnswerError) as error:
        print(f"[답변] 실패: {error.reason}")
    text = "".join(chunks)
    total_ms = (time.monotonic() - started) * 1000
    print(f"[답변] 첫 글자 {first_ms or 0:.0f}ms · 전체 {total_ms:.0f}ms · {len(text)}자\n{text}")


if __name__ == "__main__":
    # 실패하면 clients.py가 남기는 경고(실패 종류)를 보이게
    logging.basicConfig(level=logging.WARNING)
    # 도구 고르기 로그(입력·캐시 읽기·쓰기 토큰)를 보이게 : 두 번째부터 캐시 읽기 0 초과
    logging.getLogger("app.chat.clients").setLevel(logging.INFO)
    asyncio.run(main())

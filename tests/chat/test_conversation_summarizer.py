import asyncio

import httpx2
import pytest

from app.chat import clients
from app.chat.clients import SUMMARY_MAX_LENGTH, AnthropicConversationSummarizer
from app.core.response import AppError
from app.core.usage import CallResult, ExternalApi
from tests.chat.test_llm_clients import FakeAnthropic, message, server_error, settings
from tests.chat.test_usage_report import RecordingUsage


def summarize(fake: FakeAnthropic, monkeypatch, previous: str | None, usage=None) -> str:
    monkeypatch.setattr(clients, "get_anthropic_client", lambda _: fake.client())
    summarizer = AnthropicConversationSummarizer(settings(), usage or RecordingUsage())
    return asyncio.run(summarizer.summarize(previous, "[11월 3일] 회원: 초코 4.2kg"))


def test_이전_요약과_새_대화를_한_사용자_메시지로_보내야_한다(monkeypatch):
    # Arrange
    fake = FakeAnthropic(lambda _: httpx2.Response(200, json=message("새 요약")))

    # Act
    result = summarize(fake, monkeypatch, "11월 1일: 초코 산책")

    # Assert
    content = fake.requests[0]["messages"][0]["content"]
    assert content.startswith("이전 요약:\n11월 1일: 초코 산책\n\n새 대화:\n")
    assert "[11월 3일] 회원: 초코 4.2kg" in content
    assert fake.requests[0]["system"] == clients.CONVERSATION_SUMMARY_SYSTEM
    assert result == "새 요약"


def test_이전_요약이_없으면_없음으로_보내야_한다(monkeypatch):
    # Arrange
    fake = FakeAnthropic(lambda _: httpx2.Response(200, json=message("새 요약")))

    # Act
    summarize(fake, monkeypatch, None)

    # Assert
    assert fake.requests[0]["messages"][0]["content"].startswith("이전 요약:\n없음\n\n")


def test_요약이_2000자를_넘으면_잘라야_한다(monkeypatch):
    # Arrange
    fake = FakeAnthropic(lambda _: httpx2.Response(200, json=message("가" * 2500)))

    # Act
    result = summarize(fake, monkeypatch, None)

    # Assert
    assert len(result) == SUMMARY_MAX_LENGTH


def test_요약_성공은_AI_대화로_사용량을_통지해야_한다(monkeypatch):
    # Arrange
    fake = FakeAnthropic(lambda _: httpx2.Response(200, json=message("새 요약")))
    usage = RecordingUsage()

    # Act
    summarize(fake, monkeypatch, None, usage)

    # Assert
    assert [(c.api, c.result) for c in usage.calls] == [(ExternalApi.CHAT, CallResult.SUCCESS)]


def test_API_오류면_빈_요약을_주고_실패를_통지해야_한다(monkeypatch):
    # Arrange
    fake = FakeAnthropic(server_error)
    usage = RecordingUsage()

    # Act
    result = summarize(fake, monkeypatch, None, usage)

    # Assert
    assert result == ""
    assert [c.result for c in usage.calls] == [CallResult.FAIL]


def test_거절이면_빈_요약을_줘야_한다(monkeypatch):
    # Arrange
    fake = FakeAnthropic(lambda _: httpx2.Response(200, json=message("", "refusal")))

    # Act
    result = summarize(fake, monkeypatch, None)

    # Assert
    assert result == ""


def test_키가_비면_요약할_때_502를_내고_의존성은_만들어져야_한다():
    # Arrange : 메시지 전송 의존성은 키가 없어도 만들어짐
    summarizer = clients.get_conversation_summarizer(settings(""))

    # Act·Assert
    with pytest.raises(AppError):
        asyncio.run(summarizer.summarize(None, "대화"))

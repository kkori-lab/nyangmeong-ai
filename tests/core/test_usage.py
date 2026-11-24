import asyncio
import json
import logging
from typing import Annotated

import anthropic
import httpx2
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import usage
from app.core.config import Settings
from app.core.usage import (
    NO_USAGE,
    CallResult,
    ExternalApi,
    ExternalCall,
    JavaUsageReporter,
    UsageReporter,
    errored,
    failed,
    get_usage_reporter,
    succeeded,
    token_counts,
)

BASE = "http://backend.test"
COOKIE = "access_token=member-7"


class FakeJava:
    """통지 API 흉내 : 받은 요청 기록, status로 응답 코드, 0이면 연결 실패"""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.status == 0:
            raise httpx2.ConnectError("down")
        return httpx2.Response(self.status, json={"data": {"extlApiCallLogSn": 1}})

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self))


class Usage:
    def __init__(self, input_tokens=10, output_tokens=5, cache_read=None, cache_creation=None):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = cache_creation


def settings(base_url: str = BASE) -> Settings:
    return Settings(_env_file=None, backend_base_url=base_url)


def report(java: FakeJava, call: ExternalCall, cookie: str | None = COOKIE, base: str = BASE):
    async def run():
        JavaUsageReporter(java.client(), settings(base), cookie).record(call)
        await usage.flush()

    asyncio.run(run())


CALL = ExternalCall(ExternalApi.CHAT, CallResult.SUCCESS, 120, 200, 30, 5)


def test_통지는_쿠키와_X_Requested_With를_실어_내부_API로_보낸다():
    java = FakeJava()
    report(java, CALL)

    assert len(java.requests) == 1
    sent = java.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == f"{BASE}/internal/ai/external-api-calls"
    assert sent.headers["cookie"] == COOKIE
    assert sent.headers["x-requested-with"] == "XMLHttpRequest"
    assert json.loads(sent.content) == {
        "extlApiSeCd": "SYSC0015",
        "callRsltCd": "SYSC0021",
        "rspnsMs": 120,
        "httpSttsVl": 200,
        "inptTknCnt": 30,
        "otptTknCnt": 5,
    }


def test_통지_본문은_값_없는_칸을_빼고_callDt를_보내지_않는다():
    call = ExternalCall(ExternalApi.PDF, CallResult.TIMEOUT, 50, fail_reason="timeout")
    assert call.body() == {
        "extlApiSeCd": "SYSC0025",
        "callRsltCd": "SYSC0023",
        "rspnsMs": 50,
        "failRsn": "timeout",
    }


def test_실패_이유는_1000자까지만():
    call = ExternalCall(ExternalApi.OCR, CallResult.FAIL, 1, fail_reason="x" * 1500)
    assert len(call.body()["failRsn"]) == 1000


@pytest.mark.parametrize(("cookie", "base"), [(None, BASE), ("", BASE), (COOKIE, "")])
def test_쿠키나_Java_주소가_없으면_보내지_않는다(cookie, base):
    java = FakeJava()
    report(java, CALL, cookie=cookie, base=base)
    assert java.requests == []


@pytest.mark.parametrize(("status", "reason"), [(500, "Java 500"), (400, "Java 400"), (0, "Conn")])
def test_통지가_실패해도_예외_없이_경고_로그만(caplog, status, reason):
    java = FakeJava(status)
    with caplog.at_level(logging.WARNING, logger="app.core.usage"):
        report(java, CALL)

    lines = [r.getMessage() for r in caplog.records if r.name == "app.core.usage"]
    assert len(lines) == 1
    assert lines[0].startswith("외부 API 사용량 통지 실패(")
    assert reason in lines[0]
    assert COOKIE not in lines[0]


def test_이벤트_루프_밖에서는_보내지_않고_예외도_없다():
    java = FakeJava()
    JavaUsageReporter(java.client(), settings(), COOKIE).record(CALL)
    assert java.requests == []


def test_record는_통지를_기다리지_않고_바로_돌아온다():
    gate = asyncio.Event()

    async def run():
        async def slow(request: httpx2.Request) -> httpx2.Response:
            await gate.wait()
            return httpx2.Response(201)

        client = httpx2.AsyncClient(transport=httpx2.MockTransport(slow))
        JavaUsageReporter(client, settings(), COOKIE).record(CALL)
        pending = len(usage._pending)
        gate.set()
        await usage.flush()
        return pending

    assert asyncio.run(run()) == 1
    assert usage._pending == set()


# 2026-11-24 사람 결정 : 입력 = input + 캐시 읽기 + 캐시 쓰기, 출력 = output


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Usage(10, 5), (10, 5)),
        (Usage(10, 5, cache_read=300, cache_creation=40), (350, 5)),
        (Usage(0, 0, cache_read=0, cache_creation=0), (0, 0)),
        (None, (None, None)),
    ],
)
def test_토큰_수(value, expected):
    assert token_counts(value) == expected


def test_성공은_SYSC0021_상태_200과_토큰():
    call = succeeded(ExternalApi.CLASSIFY, 0.0, Usage(10, 5, cache_read=2))
    assert call.api is ExternalApi.CLASSIFY
    assert call.result is CallResult.SUCCESS
    assert (call.http_status, call.input_tokens, call.output_tokens) == (200, 12, 5)
    assert call.fail_reason is None
    assert call.rspns_ms >= 0


def test_응답은_왔지만_못_쓰면_SYSC0022와_이유():
    call = failed(ExternalApi.CHAT, 0.0, "refusal", Usage(10, 1))
    assert (call.result, call.fail_reason, call.input_tokens) == (CallResult.FAIL, "refusal", 10)


REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("error", "result", "status", "reason"),
    [
        (anthropic.APITimeoutError(request=REQUEST), CallResult.TIMEOUT, None, "timeout"),
        (httpx2.ReadTimeout("t", request=REQUEST), CallResult.TIMEOUT, None, "timeout"),
        (TimeoutError(), CallResult.TIMEOUT, None, "timeout"),
        (
            anthropic.APIStatusError(
                "overloaded", response=httpx2.Response(529, request=REQUEST), body=None
            ),
            CallResult.FAIL,
            529,
            "api_error 529",
        ),
        (anthropic.APIConnectionError(request=REQUEST), CallResult.FAIL, None, "api_error"),
        (httpx2.ConnectError("down"), CallResult.FAIL, None, "network ConnectError"),
    ],
)
def test_예외는_시간초과와_실패로_나눈다(error, result, status, reason):
    call = errored(ExternalApi.CHAT, 0.0, error)
    assert (call.result, call.http_status, call.fail_reason) == (result, status, reason)
    assert call.input_tokens is None


def reporter_app(backend: httpx2.AsyncClient | None) -> FastAPI:
    app = FastAPI()
    if backend is not None:
        app.state.backend_client = backend

    @app.post("/ai/x")
    async def x(reporter: Annotated[UsageReporter, Depends(get_usage_reporter)]):
        reporter.record(CALL)
        await usage.flush()
        return {"kind": type(reporter).__name__}

    return app


def test_의존성은_요청_쿠키로_Java_통지기를_만든다(monkeypatch):
    monkeypatch.setenv("BACKEND_BASE_URL", BASE)
    from app.core.config import get_settings

    get_settings.cache_clear()
    java = FakeJava()
    res = TestClient(reporter_app(java.client())).post("/ai/x", headers={"Cookie": COOKIE})

    assert res.json() == {"kind": "JavaUsageReporter"}
    assert [r.headers["cookie"] for r in java.requests] == [COOKIE]


def test_Java_클라이언트가_없는_앱은_통지하지_않는다():
    res = TestClient(reporter_app(None)).post("/ai/x", headers={"Cookie": COOKIE})
    assert res.json() == {"kind": "NoUsageReporter"}


def test_기본_통지기는_아무것도_하지_않는다():
    assert NO_USAGE.record(CALL) is None

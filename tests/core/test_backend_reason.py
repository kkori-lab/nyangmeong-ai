import asyncio

import httpx2
import pytest

from app.core.backend import TIMEOUT_SEC, BackendError, call_backend, failure_reason
from app.core.config import Settings
from app.core.response import AppError


def _settings(url: str = "http://backend.test") -> Settings:
    return Settings(_env_file=None, backend_base_url=url)


def _reason_of(handler, url: str = "http://backend.test") -> str:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler), timeout=TIMEOUT_SEC)
    with pytest.raises((AppError, BackendError)) as caught:
        asyncio.run(call_backend(client, _settings(url), "GET", "/internal/x"))
    return failure_reason(caught.value)


def test_제한_시간_초과면_예외_이름과_함께_이유를_남겨야_한다():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    assert _reason_of(handler) == "제한 시간 초과 ReadTimeout"


def test_연결_실패면_연결_실패_이유를_남겨야_한다():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    assert _reason_of(handler) == "연결 실패 ConnectError"


def test_Java_5xx면_상태_코드를_남기고_502로_바꿔야_한다():
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(503)))
    with pytest.raises(AppError) as caught:
        asyncio.run(call_backend(client, _settings(), "GET", "/internal/x"))

    assert caught.value.http_code == 502
    assert failure_reason(caught.value) == "Java 503"


def test_Java_4xx면_상태_코드를_남겨야_한다():
    assert _reason_of(lambda r: httpx2.Response(401)) == "Java 401"


def test_주소가_비면_주소_비어_있음을_남겨야_한다():
    assert _reason_of(lambda r: httpx2.Response(200), url="") == "주소 비어 있음"


def test_응답이_JSON이_아니면_그_이유를_남겨야_한다():
    assert _reason_of(lambda r: httpx2.Response(200, text="<html>")) == "응답 JSON 아님"


def test_원인이_없는_예외는_예외_이름을_남겨야_한다():
    assert failure_reason(RuntimeError("x")) == "RuntimeError"


@pytest.mark.parametrize("error", [httpx2.InvalidURL("Invalid port: 'abc'"), OverflowError("port")])
def test_주소_꼴이_틀리면_502로_바꾸고_주소_꼴_틀림을_남겨야_한다(error):
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    with pytest.raises(AppError) as caught:
        asyncio.run(call_backend(client, _settings(), "GET", "/internal/x"))

    assert caught.value.http_code == 502
    assert failure_reason(caught.value) == f"주소 꼴 틀림 {type(error).__name__}"


def test_포트가_문자인_실제_주소로_부르면_502여야_한다():
    client = httpx2.AsyncClient(timeout=TIMEOUT_SEC)
    with pytest.raises(AppError) as caught:
        asyncio.run(call_backend(client, _settings("http://localhost:abc"), "GET", "/internal/x"))

    assert caught.value.http_code == 502
    assert failure_reason(caught.value) == "주소 꼴 틀림 InvalidURL"

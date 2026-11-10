import asyncio
import contextlib

import httpx2
import pytest

from app.core.backend import (
    TIMEOUT_SEC,
    BackendError,
    call_backend,
    failure_reason,
    fetch_backend_bytes,
)
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


BACKEND_LOGGER = "app.core.backend"
COOKIE = "access_token=secret-token-value"


def _logged(
    caplog: pytest.LogCaptureFixture,
    handler,
    path: str = "/internal/x",
    url: str = "http://backend.test",
) -> list[str]:
    caplog.set_level("WARNING", logger=BACKEND_LOGGER)
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler), timeout=TIMEOUT_SEC)
    with pytest.raises((AppError, BackendError)):
        asyncio.run(
            call_backend(
                client,
                _settings(url),
                "POST",
                path,
                headers={"Cookie": COOKIE},
                json={"msg": "secret-body"},
            )
        )
    return [r.getMessage() for r in caplog.records if r.name == BACKEND_LOGGER]


def _raise(error_type):
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error_type("x", request=request)

    return handler


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (_raise(httpx2.ConnectError), "연결 실패 ConnectError"),
        (_raise(httpx2.ReadTimeout), "제한 시간 초과 ReadTimeout"),
        (lambda r: httpx2.Response(503, text="secret-body"), "Java 503"),
        (lambda r: httpx2.Response(200, text="<html>secret-body"), "응답 JSON 아님"),
    ],
)
def test_502로_바꾸면_이유와_경로를_한_줄_남기고_주소_쿠키_본문_번호는_남기지_않아야_한다(
    handler, reason, caplog: pytest.LogCaptureFixture
):
    logs = _logged(caplog, handler, path="/internal/ai/conversations/123/messages?mbrSn=45")

    assert logs == [f"Java 호출 실패({reason}), 502 POST /internal/ai/conversations/{{n}}/messages"]
    for secret in ("backend.test", "secret-token-value", "secret-body", "123", "45"):
        assert secret not in caplog.text


def test_주소가_비면_주소_비어_있음을_한_줄_남겨야_한다(caplog: pytest.LogCaptureFixture):
    logs = _logged(caplog, lambda r: httpx2.Response(200), url="")

    assert logs == ["Java 호출 실패(주소 비어 있음), 502 POST /internal/x"]


def test_주소_꼴이_틀리면_주소_값_없이_한_줄_남겨야_한다(caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING", logger=BACKEND_LOGGER)
    client = httpx2.AsyncClient(timeout=TIMEOUT_SEC)
    with pytest.raises(AppError):
        asyncio.run(call_backend(client, _settings("http://localhost:abc"), "GET", "/internal/x"))

    assert [r.getMessage() for r in caplog.records if r.name == BACKEND_LOGGER] == [
        "Java 호출 실패(주소 꼴 틀림 InvalidURL), 502 GET /internal/x"
    ]
    assert "localhost" not in caplog.text


def test_파일이_빈_본문이면_502로_바꾸고_빈_본문을_남겨야_한다(caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING", logger=BACKEND_LOGGER)
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))
    with pytest.raises(AppError) as caught:
        asyncio.run(fetch_backend_bytes(client, _settings(), "/internal/files/7"))

    assert caught.value.http_code == 502
    assert failure_reason(caught.value) == "빈 본문"
    assert [r.getMessage() for r in caplog.records if r.name == BACKEND_LOGGER] == [
        "Java 호출 실패(빈 본문), 502 GET /internal/files/{n}"
    ]


@pytest.mark.parametrize(
    "handler",
    [lambda r: httpx2.Response(401), lambda r: httpx2.Response(200, json={"data": 1})],
)
def test_4xx_전달과_성공은_로그를_남기지_않아야_한다(handler, caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING", logger=BACKEND_LOGGER)
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    with contextlib.suppress(BackendError):
        asyncio.run(call_backend(client, _settings(), "GET", "/internal/x"))

    assert [r for r in caplog.records if r.name == BACKEND_LOGGER] == []

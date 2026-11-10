from collections.abc import Callable
from typing import Annotated

import httpx2
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import require_admin, require_member
from app.core.backend import get_backend_client
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers

BACKEND = "http://backend.test"
EXPIRED_BODY = b'{"status":"error","httpCode":401,"code":"TOKEN_EXPIRED","message":"m"}'
CLEAR_COOKIE = "access_token=; Max-Age=0; Path=/; HttpOnly"


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response], base_url: str = BACKEND
) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/ai/me")
    async def me(mbr_sn: Annotated[int, Depends(require_member)]) -> dict:
        return {"mbrSn": mbr_sn}

    @app.get("/ai/admin")
    async def admin(mbr_sn: Annotated[int, Depends(require_admin)]) -> dict:
        return {"mbrSn": mbr_sn}

    settings = Settings(_env_file=None, backend_base_url=base_url)
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_backend_client] = lambda: backend
    return TestClient(app)


def test_Java가_통과시키면_회원_번호_Java로_쿠키만_보낸다() -> None:
    # FN-AIM-011-03
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"data": {"mbrSn": 42, "mbrAuthrtCd": "U"}})

    client = _client(handler)
    client.cookies.set("access_token", "abc")
    res = client.get("/ai/me")

    assert res.status_code == 200
    assert res.json() == {"mbrSn": 42}
    assert str(seen[0].url) == f"{BACKEND}/internal/auth/check"
    assert "x-internal-key" not in seen[0].headers
    assert seen[0].headers["cookie"] == "access_token=abc"


def test_Java_401은_상태와_본문을_그대로() -> None:
    client = _client(
        lambda r: httpx2.Response(
            401, content=EXPIRED_BODY, headers={"content-type": "application/json"}
        )
    )

    res = client.get("/ai/me")

    assert res.status_code == 401
    assert res.content == EXPIRED_BODY
    assert res.headers["content-type"] == "application/json"


def test_Java_403은_Set_Cookie까지_그대로() -> None:
    body = b'{"code":"MEMBER_INACTIVE"}'
    client = _client(
        lambda r: httpx2.Response(
            403,
            content=body,
            headers=[
                ("content-type", "application/json"),
                ("set-cookie", CLEAR_COOKIE),
                ("set-cookie", "refresh_token=; Max-Age=0; Path=/"),
            ],
        )
    )

    res = client.get("/ai/me")

    assert res.status_code == 403
    assert res.content == body
    assert res.headers.get_list("set-cookie") == [
        CLEAR_COOKIE,
        "refresh_token=; Max-Age=0; Path=/",
    ]


@pytest.mark.parametrize("error", [httpx2.ConnectError("down"), httpx2.ReadTimeout("slow")])
def test_Java에_닿지_못하면_502(error: Exception) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    res = _client(handler).get("/ai/me")

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


@pytest.mark.parametrize(
    "java",
    [
        httpx2.Response(500, json={"code": "INTERNAL_ERROR"}),
        httpx2.Response(200, json={"data": {}}),
        httpx2.Response(200, content=b"not json"),
    ],
)
def test_Java_5xx나_형식이_틀린_200은_502(java: httpx2.Response) -> None:
    res = _client(lambda r: java).get("/ai/me")

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_Java_주소가_비어_있으면_부르지_않고_502() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("호출되면 안 됨")

    res = _client(handler, base_url="").get("/ai/me")

    assert res.status_code == 502


@pytest.mark.parametrize("error", [httpx2.InvalidURL("Invalid port: 'abc'"), OverflowError("port")])
def test_Java_주소_꼴이_틀리면_502(error: Exception) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    res = _client(handler).get("/ai/me")

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_포트가_문자인_실제_주소면_502() -> None:
    app = _client(lambda r: httpx2.Response(200)).app
    settings = Settings(_env_file=None, backend_base_url="http://localhost:abc")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_backend_client] = lambda: httpx2.AsyncClient()

    res = TestClient(app).get("/ai/me")

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


# FN-ADM-001-01 : 관리자 확인
def _authority(code: object) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda r: httpx2.Response(200, json={"data": {"mbrSn": 1, "mbrAuthrtCd": code}})


def test_require_admin_관리자는_통과() -> None:
    res = _client(_authority("USRC0005")).get("/ai/admin")

    assert res.status_code == 200
    assert res.json() == {"mbrSn": 1}


@pytest.mark.parametrize("code", ["USRC0001", None, 5])
def test_require_admin_관리자가_아니면_403_FORBIDDEN(code: object) -> None:
    res = _client(_authority(code)).get("/ai/admin")

    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


def test_require_admin_Java_401은_그대로() -> None:
    client = _client(
        lambda r: httpx2.Response(
            401, content=EXPIRED_BODY, headers={"content-type": "application/json"}
        )
    )

    res = client.get("/ai/admin")

    assert res.status_code == 401
    assert res.content == EXPIRED_BODY


def test_require_member는_권한과_관계없이_통과() -> None:
    res = _client(_authority("USRC0001")).get("/ai/me")

    assert res.status_code == 200


# 인증 확인 502 이유 로그
AUTH_LOGGER = "app.core.auth"
COOKIE = "access_token=secret-token-value"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == AUTH_LOGGER]


def _raise(error: Exception) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (_raise(httpx2.ConnectError("down")), "연결 실패 ConnectError"),
        (_raise(httpx2.ReadTimeout("slow")), "제한 시간 초과 ReadTimeout"),
        (_raise(httpx2.RemoteProtocolError("bad")), "통신 실패 RemoteProtocolError"),
        (_raise(httpx2.InvalidURL("Invalid port: 'abc'")), "주소 꼴 틀림 InvalidURL"),
        (_raise(OverflowError("port")), "주소 꼴 틀림 OverflowError"),
        (lambda r: httpx2.Response(500, json={"code": "INTERNAL_ERROR"}), "Java 500"),
        (lambda r: httpx2.Response(200, content=b"not json"), "응답 형식 틀림"),
        (lambda r: httpx2.Response(200, json={"data": {}}), "응답 형식 틀림"),
    ],
)
def test_502로_바꾸면_이유를_한_줄_남기고_주소와_쿠키는_남기지_않는다(
    handler: Callable[[httpx2.Request], httpx2.Response],
    reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger=AUTH_LOGGER)

    res = _client(handler).get("/ai/me", headers={"Cookie": COOKIE})

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"
    assert _warnings(caplog) == [f"인증 확인 실패({reason}), 502"]
    assert "backend.test" not in caplog.text
    assert "secret-token-value" not in caplog.text


def test_주소가_비면_주소_비어_있음을_남긴다(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING", logger=AUTH_LOGGER)

    res = _client(lambda r: httpx2.Response(200), base_url="").get("/ai/me")

    assert res.status_code == 502
    assert _warnings(caplog) == ["인증 확인 실패(주소 비어 있음), 502"]


def test_포트가_문자인_실제_주소면_주소_값_없이_이유를_남긴다(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger=AUTH_LOGGER)
    app = _client(lambda r: httpx2.Response(200)).app
    settings = Settings(_env_file=None, backend_base_url="http://localhost:abc")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_backend_client] = lambda: httpx2.AsyncClient()

    res = TestClient(app).get("/ai/me")

    assert res.status_code == 502
    assert _warnings(caplog) == ["인증 확인 실패(주소 꼴 틀림 InvalidURL), 502"]
    assert "localhost:abc" not in caplog.text


@pytest.mark.parametrize("status", [401, 403])
def test_Java_401_403을_그대로_넘길_때는_로그를_남기지_않는다(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING", logger=AUTH_LOGGER)

    res = _client(lambda r: httpx2.Response(status, content=EXPIRED_BODY)).get("/ai/me")

    assert res.status_code == status
    assert _warnings(caplog) == []


def test_통과하면_로그를_남기지_않는다(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING", logger=AUTH_LOGGER)

    res = _client(lambda r: httpx2.Response(200, json={"data": {"mbrSn": 7}})).get("/ai/me")

    assert res.status_code == 200
    assert _warnings(caplog) == []

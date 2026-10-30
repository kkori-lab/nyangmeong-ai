from collections.abc import Callable
from typing import Annotated

import httpx2
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import require_member
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

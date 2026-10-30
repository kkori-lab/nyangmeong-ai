import httpx2

from app.core.backend import get_backend_client
from tests.chat.conftest import as_member

URL = "/ai/me"


def test_쿠키_있으면_회원_번호(client, java):
    # FN-AIM-011-03 : 인증만 거치고 DB·대화 API 미호출
    as_member(client, 42)
    res = client.get(URL)

    assert res.status_code == 200
    assert res.json()["data"] == {"mbrSn": 42}
    assert java.requests == []


def test_쿠키_없으면_Java_401_그대로(client):
    res = client.get(URL)

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_Java에_닿지_못하면_502(client):
    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(refused))
    client.app.dependency_overrides[get_backend_client] = lambda: backend
    as_member(client, 42)
    res = client.get(URL)

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.chat import clients
from app.chat.clients import ImageIntentError
from app.chat.schemas import ImageIntentKind
from tests.chat.conftest import AJAX, as_member

URL = "/ai/image-intent"


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(out, fmt)
    return out.getvalue()


class FakeImageIntentJudge:
    def __init__(self, kind: ImageIntentKind = ImageIntentKind.CHARACTER, fail: bool = False):
        self.kind = kind
        self.fail = fail
        self.calls: list[tuple[bytes, str | None]] = []

    async def judge(self, jpeg: bytes, text: str | None) -> ImageIntentKind:
        self.calls.append((jpeg, text))
        if self.fail:
            raise ImageIntentError("timeout")
        return self.kind


@pytest.fixture
def judge(client: TestClient) -> FakeImageIntentJudge:
    fake = FakeImageIntentJudge()
    client.app.dependency_overrides[clients.get_image_intent_judge] = lambda: fake
    as_member(client, 7)
    return fake


def post(client: TestClient, data: dict | None = None, file=None, headers=AJAX):
    files = {"file": file or ("pet.png", image_bytes(), "image/png")}
    return client.post(URL, data=data or {}, files=files, headers=headers)


# 성공·응답 모양
@pytest.mark.parametrize("kind", list(ImageIntentKind))
def test_image_intent_판단_결과를_그대로_돌려줌(client, judge, kind):
    judge.kind = kind
    res = post(client, {"cnvrsCn": "이거 봐줘", "petSn": "3"})
    assert res.status_code == 200
    assert res.json()["data"] == {"kind": kind.value}


def test_image_intent_글과_축소한_jpeg를_넘김(client, judge):
    big = image_bytes("PNG", (3000, 1500))
    res = post(client, {"cnvrsCn": " 가계부에 넣어줘 "}, ("r.png", big, "image/png"))
    assert res.status_code == 200
    jpeg, text = judge.calls[0]
    assert text == "가계부에 넣어줘"
    with Image.open(io.BytesIO(jpeg)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (1024, 512)


def test_image_intent_작은_사진은_키우지_않음(client, judge):
    post(client, file=("p.webp", image_bytes("WEBP", (300, 200)), "image/webp"))
    with Image.open(io.BytesIO(judge.calls[0][0])) as opened:
        assert opened.size == (300, 200)


@pytest.mark.parametrize("data", [{}, {"cnvrsCn": ""}, {"cnvrsCn": "   "}])
def test_image_intent_글이_없거나_공백이면_None(client, judge, data):
    res = post(client, data)
    assert res.status_code == 200
    assert judge.calls[0][1] is None


def test_image_intent_판단_실패는_ASK(client, judge):
    judge.fail = True
    res = post(client, {"cnvrsCn": "이거 뭐야"})
    assert res.status_code == 200
    assert res.json()["data"] == {"kind": "ASK"}


# 인증·검증 실패는 판단기 미호출
def test_image_intent_쿠키_없음_401(client, judge):
    client.cookies.clear()
    res = post(client)
    assert res.status_code == 401
    assert judge.calls == []


def test_image_intent_X_Requested_With_없음_403(client, judge):
    res = post(client, headers={})
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert judge.calls == []


@pytest.mark.parametrize(
    ("file", "code"),
    [
        (("r.pdf", b"%PDF-1.7 0000", "application/pdf"), "FILE_TYPE_NOT_ALLOWED"),
        (("r.jpg", image_bytes("PNG"), "image/jpeg"), "FILE_TYPE_NOT_ALLOWED"),
        (("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16, "image/png"), "FILE_TYPE_NOT_ALLOWED"),
        (
            ("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024), "image/png"),
            "FILE_SIZE_EXCEEDED",
        ),
    ],
)
def test_image_intent_파일_검증_400(client, judge, file, code):
    res = post(client, file=file)
    assert res.status_code == 400
    assert res.json()["code"] == code
    assert judge.calls == []


@pytest.mark.parametrize("data", [{"cnvrsCn": "가" * 1001}, {"petSn": "abc"}, {"petSn": "0"}])
def test_image_intent_폼_값_검증_400(client, judge, data):
    res = post(client, data)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert judge.calls == []


def test_image_intent_file_없음_400(client, judge):
    res = client.post(URL, data={"cnvrsCn": "사진"}, headers=AJAX)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert judge.calls == []


def test_image_intent_LLM_키_없음_502(client):
    as_member(client, 7)
    res = post(client)
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"

import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from app.character.clients import CharacterApiError, CharacterRequest, get_character_client
from app.character.rules import matches_spec, png_size
from app.core.config import get_settings
from app.main import create_app

URL = "/internal/v1/character/generate"
PHOTO = b"\x89PNG\r\n\x1a\n" + b"0" * 16
FORM = {"petSeCd": "PETC0001", "vrtyNm": "말티즈", "colrNm": "흰색", "chrcCn": "귀가 쳐짐"}


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = (b"\x00" + b"\x00" * (width * 4)) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class _FakeClient:
    def __init__(self, result: bytes | Exception) -> None:
        self._result = result

    async def generate(self, request: CharacterRequest) -> bytes:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.fixture
def app():
    get_settings.cache_clear()
    app = create_app()
    # 규격(512×512) PNG를 돌려주는 가짜 생성기
    app.dependency_overrides[get_character_client] = lambda: _FakeClient(_png(512, 512))
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _post(
    client: TestClient,
    photo: bytes | None = PHOTO,
    data: dict | None = None,
):
    files = {"photo": ("p.png", photo)} if photo is not None else None
    return client.post(URL, files=files, data=FORM if data is None else data)


def test_요청하면_512x512_PNG를_껍데기_없이_돌려준다(client: TestClient) -> None:
    response = _post(client)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert png_size(response.content) == (512, 512)


def test_사진이_이미지가_아니면_400_FILE_TYPE_NOT_ALLOWED(client: TestClient) -> None:
    response = _post(client, photo=b"not an image")

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_TYPE_NOT_ALLOWED"


@pytest.mark.parametrize(
    ("photo", "data"),
    [
        (None, FORM),  # photo 누락
        (PHOTO, {"vrtyNm": "말티즈"}),  # petSeCd 누락
        (PHOTO, {"petSeCd": "PETC0003"}),  # 허용값 밖
    ],
)
def test_필수값이_없거나_petSeCd가_허용값_밖이면_400_INVALID_REQUEST(
    client: TestClient, photo: bytes | None, data: dict
) -> None:
    response = _post(client, photo=photo, data=data)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_선택_필드_없이_필수값만_보내도_200(client: TestClient) -> None:
    response = _post(client, data={"petSeCd": "PETC0002"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (_png(511, 512), "CHARACTER_SPEC_MISMATCH"),  # FN-MYP-010-18
        (b"not a png", "CHARACTER_SPEC_MISMATCH"),  # FN-MYP-010-18
        (CharacterApiError(), "CHARACTER_API_ERROR"),  # FN-MYP-010-17
    ],
)
def test_생성_결과가_규격_밖이거나_생성기가_실패하면_502와_코드를_구분한다(
    app, client: TestClient, result: bytes | Exception, code: str
) -> None:
    app.dependency_overrides[get_character_client] = lambda: _FakeClient(result)

    response = _post(client)

    assert response.status_code == 502
    assert response.json()["code"] == code


def test_규격_검증은_캔버스_크기가_512x512인_PNG만_통과시킨다() -> None:
    assert matches_spec(_png(512, 512))
    assert not matches_spec(_png(512, 511))
    assert not matches_spec(b"\x89PNG\r\n\x1a\n")


def test_생성_클라이언트가_연결되기_전에는_502_EXTERNAL_API_ERROR(app, client: TestClient) -> None:
    del app.dependency_overrides[get_character_client]

    response = _post(client)

    assert response.status_code == 502
    assert response.json()["code"] == "EXTERNAL_API_ERROR"

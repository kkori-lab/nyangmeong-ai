import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.character import engine
from app.character.clients import OpenAICharacterClient
from tests.character.fakes import FakeImagesOpenAI, magenta_drawing
from tests.character.test_items import ADMIN, MEMBER, item_png, make_client, repo  # noqa: F401

RED = (200, 30, 30, 255)


# FN-ADM-070-02 : 실사 사진 -> 픽셀 아이템 그림 (상점 이미지)
def post_pixel(client: TestClient, headers=ADMIN, regn_cd="MYPC0001", name="i.png", **kwargs):
    form = {"regnCd": regn_cd, "itemNm": kwargs.pop("item_nm", "빨간 털모자")}
    files = {"image": (name, kwargs.pop("image", item_png()), "image/png")}
    return client.post("/ai/items/pixel-image", data=form, files=files, headers=headers)


def pixel_client(monkeypatch, repo, answer: bytes | Exception | None = None):  # noqa: F811
    fake = FakeImagesOpenAI(magenta_drawing() if answer is None else answer)
    generator = OpenAICharacterClient(fake, "image-model", "vision-model")
    return make_client(monkeypatch, repo, generator), fake


def rgba(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGBA")


def test_pixel_image_투명_배경_256_PNG를_돌려주고_저장하지_않는다(monkeypatch, repo) -> None:  # noqa: F811
    client, fake = pixel_client(monkeypatch, repo)
    res = post_pixel(client)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    image = rgba(res.content)
    assert image.size == (engine.ITEM_PX, engine.ITEM_PX)
    for corner in [(0, 0), (255, 0), (0, 255), (255, 255)]:
        assert image.getpixel(corner)[3] == 0
    # 빨간 테는 남고 바탕색 구멍(가운데)은 투명
    assert image.getpixel((engine.ITEM_PAD + 2, 128)) == RED
    assert image.getpixel((128, 128))[3] == 0
    assert all(not saved.item_sheets and not saved.failed_items for saved in repo.jobs.values())


def test_pixel_image_화풍_기준과_사진을_이미지_모델에_보낸다(monkeypatch, repo) -> None:  # noqa: F811
    client, fake = pixel_client(monkeypatch, repo)
    post_pixel(client)
    call = fake.calls[0]
    assert call["model"] == "image-model"
    assert [ref[0] for ref in call["image"]] == ["style_ref.png", "item.png"]
    assert "빨간 털모자" in call["prompt"]
    assert "on the head" in call["prompt"]


def test_pixel_image_생성기가_없으면_502_EXTERNAL(monkeypatch, repo) -> None:  # noqa: F811
    res = post_pixel(make_client(monkeypatch, repo, None))
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


@pytest.mark.parametrize(
    "answer",
    [RuntimeError("down"), magenta_drawing(item=False), b"not image"],
    ids=["생성_실패", "바탕만", "그림_아님"],
)
def test_pixel_image_생성_실패와_빈_그림은_502_CHARACTER(monkeypatch, repo, answer) -> None:  # noqa: F811
    client, _ = pixel_client(monkeypatch, repo, answer)
    res = post_pixel(client)
    assert res.status_code == 502
    assert res.json()["code"] == "CHARACTER_API_ERROR"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"regn_cd": "MYPC0006"}, "INVALID_REQUEST"),
        ({"regn_cd": "MYPC9999"}, "INVALID_REQUEST"),
        ({"item_nm": ""}, "INVALID_REQUEST"),
        ({"item_nm": "가" * 51}, "INVALID_REQUEST"),
        ({"image": b"GIF89a" + b"0" * 20, "name": "i.gif"}, "FILE_TYPE_NOT_ALLOWED"),
        ({"image": b"not image"}, "FILE_TYPE_NOT_ALLOWED"),
        ({"image": b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024)}, "FILE_SIZE_EXCEEDED"),
    ],
)
def test_pixel_image_입력이_틀리면_400이고_생성하지_않는다(monkeypatch, repo, kwargs, code):  # noqa: F811
    client, fake = pixel_client(monkeypatch, repo)
    res = post_pixel(client, **kwargs)
    assert res.status_code == 400
    assert res.json()["code"] == code
    assert fake.calls == []


def test_pixel_image_그림이_없으면_400(monkeypatch, repo) -> None:  # noqa: F811
    client, _ = pixel_client(monkeypatch, repo)
    form = {"regnCd": "MYPC0001", "itemNm": "모자"}
    res = client.post("/ai/items/pixel-image", data=form, headers=ADMIN)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_pixel_image_회원은_403이고_생성하지_않는다(monkeypatch, repo) -> None:  # noqa: F811
    client, fake = pixel_client(monkeypatch, repo)
    res = post_pixel(client, headers=MEMBER)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert fake.calls == []


def test_cut_item_바탕을_투명하게_하고_테와_구멍을_지킨다() -> None:
    image = rgba(engine.cut_item(magenta_drawing()))
    assert image.size == (engine.ITEM_PX, engine.ITEM_PX)
    alpha = image.getchannel("A")
    left, top, right, bottom = alpha.getbbox()
    # 400×200 테가 긴 변 기준 224px로 줄어 가운데
    assert (right - left, bottom - top) == (224, 112)
    assert (left, top) == (engine.ITEM_PAD, (engine.ITEM_PX - 112) // 2)
    assert image.getpixel((left + 2, top + 2)) == RED
    assert image.getpixel((128, 128))[3] == 0
    # 작은 얼룩은 버림 : 테 바깥에 불투명 화소 없음
    assert alpha.crop((0, 0, engine.ITEM_PX, top)).getbbox() is None


def test_cut_item_바탕만_있으면_ItemImageError() -> None:
    with pytest.raises(engine.ItemImageError):
        engine.cut_item(magenta_drawing(item=False))

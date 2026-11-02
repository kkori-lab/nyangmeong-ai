import asyncio
import base64
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.character import canvas, engine
from app.character.clients import (
    CharacterApiError,
    CharacterRequest,
    OpenAICharacterClient,
    get_character_client,
)
from app.character.rules import matches_spec
from app.core.config import get_settings

MAGENTA = (255, 0, 255, 255)
FUR = (200, 150, 90, 255)
BLACK = (0, 0, 0, 255)


def _sheet(*, eyes: bool = True, figures: int = 4) -> bytes:
    image = Image.new("RGBA", (1024, 1024), MAGENTA)
    draw = ImageDraw.Draw(image)
    for x, y in [(100, 100), (620, 100), (100, 620), (620, 620)][:figures]:
        draw.ellipse((x, y, x + 300, y + 300), fill=FUR, outline=BLACK, width=4)
        if eyes:
            for eye_x in (x + 90, x + 190):
                draw.ellipse((eye_x, y + 110, eye_x + 22, y + 132), fill=BLACK)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _photo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2000, 1000), (120, 120, 120)).save(buffer, "JPEG")
    return buffer.getvalue()


class FakeOpenAI:
    """받은 호출 기록, 정해 둔 시트·눈 답변 반환"""

    def __init__(self, sheet: bytes | Exception, eye_answer: str | Exception = "{}") -> None:
        self.sheet = sheet
        self.eye_answer = eye_answer
        self.edits: list[dict] = []
        self.images = SimpleNamespace(edit=self._edit)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _edit(self, **kwargs):
        self.edits.append(kwargs)
        if isinstance(self.sheet, Exception):
            raise self.sheet
        encoded = base64.b64encode(self.sheet).decode()
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])

    def _create(self, **_):
        if isinstance(self.eye_answer, Exception):
            raise self.eye_answer
        message = SimpleNamespace(content=self.eye_answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _generate(fake: FakeOpenAI, request: CharacterRequest | None = None) -> bytes:
    client = OpenAICharacterClient(fake, "image-model", "vision-model")
    return asyncio.run(client.generate(request or CharacterRequest(_photo(), "PETC0002"))).image


# FN-MYP-010-17 : 512 배치
def test_stand_front_서기_정면_컷을_자른다():
    front = engine.stand_front(_sheet())
    assert 295 <= front.width <= 305
    assert 295 <= front.height <= 305
    alpha = np.array(front)[..., 3]
    assert alpha[0, 0] == 0
    assert alpha[front.height // 2, front.width // 2] == 255


def test_place_눈이_고정_위치에_놓인다():
    placed = canvas.place(engine.stand_front(_sheet()))
    assert placed is not None
    assert matches_spec(placed.png)
    result = Image.open(io.BytesIO(placed.png))
    assert result.size == (512, 512)
    # find_eyes 기준은 그림에 맞게 잘린 크기 : 512 전체로 재면 눈 사이 하한에 걸림
    box = result.getbbox()
    found = canvas.find_eyes(result.crop(box))
    assert found is not None
    (left_x, left_y), (right_x, right_y) = found
    assert box[3] - box[1] == pytest.approx(341, abs=2)
    assert box[0] + (left_x + right_x) / 2 == pytest.approx(256, abs=2)
    assert box[1] + (left_y + right_y) / 2 == pytest.approx(207, abs=2)
    assert not placed.clipped


def test_place_눈이_그림_위쪽이면_상단을_보정한다():
    image = Image.new("RGBA", (400, 800))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, 399, 799), fill=FUR, outline=BLACK, width=4)
    for x in (110, 250):
        draw.ellipse((x, 120, x + 40, 160), fill=BLACK)
    placed = canvas.place(image)
    assert placed is not None
    assert placed.origin[1] == canvas.TOP_MAX
    assert not placed.clipped
    result = Image.open(io.BytesIO(placed.png))
    assert result.getbbox()[1] == pytest.approx(100, abs=1)
    (_, left_y), (_, right_y) = placed.canvas_eyes
    assert (left_y + right_y) / 2 == pytest.approx(100 + 140 * placed.scale, abs=1)


def test_place_눈이_없으면_None():
    assert canvas.place(engine.stand_front(_sheet(eyes=False))) is None


def test_stand_front_네_마리가_아니면_오류():
    with pytest.raises(engine.SheetError):
        engine.stand_front(_sheet(figures=3))


def test_find_eyes_검은_털은_흰_하이라이트로_찾는다():
    image = Image.new("RGBA", (320, 360))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 310, 350), fill=(25, 25, 25, 255), outline=BLACK, width=6)
    for x in (100, 210):
        draw.ellipse((x, 120, x + 30, 150), fill=BLACK)
        draw.rectangle((x + 10, 125, x + 19, 134), fill=(255, 255, 255, 255))
    found = canvas.find_eyes(image)
    assert found is not None
    (left_x, left_y), (right_x, right_y) = found
    assert (left_x, left_y) == pytest.approx((114.5, 129.5), abs=1)
    assert (right_x, right_y) == pytest.approx((224.5, 129.5), abs=1)


def test_defringe_세_겹보다_깊은_마젠타_테두리를_지운다():
    rgb = np.full((60, 60, 3), (255, 0, 255), dtype=np.uint8)
    rgb[10:50, 10:50] = (170, 1, 200)
    rgb[20:40, 20:40] = (25, 25, 25)
    mask = np.zeros((60, 60), dtype=bool)
    mask[10:50, 10:50] = True
    result = engine._defringe(mask, rgb)
    assert result.sum() == 400
    assert result[20:40, 20:40].all()


# FN-MYP-010-08 : 입력·프롬프트
def test_normalize_photo_긴_변을_1024로_줄인_PNG():
    result = Image.open(io.BytesIO(engine.normalize_photo(_photo())))
    assert result.format == "PNG"
    assert max(result.size) == 1024
    assert not result.getexif()


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ('{"shape": "almond", "color": "dark brown"}', engine.Eyes("almond", "dark-brown")),
        ('답변: {"shape": "star", "color": "red"}', engine.Eyes()),
        ("모르겠음", engine.Eyes()),
        ("{broken", engine.Eyes()),
    ],
)
def test_parse_eyes(answer, expected):
    assert engine.parse_eyes(answer) == expected


def test_build_prompt_등록_정보가_들어간다():
    prompt = engine.build_prompt("cat", engine.Eyes(), "코리안숏헤어", "고등어", "귀 {접힘}")
    assert "{eyes}" not in prompt
    assert "EYES, the same construction for every cat" in prompt
    for value in ("코리안숏헤어", "고등어", "귀 {접힘}"):
        assert json.dumps(value, ensure_ascii=False) in prompt


def test_build_prompt_등록_정보가_없으면_붙이지_않는다():
    assert "owner registered" not in engine.build_prompt("dog", engine.Eyes())


# 생성기 전체
def test_generate_512_PNG를_돌려주고_기준_그림과_사진을_순서대로_보낸다():
    fake = FakeOpenAI(_sheet(), '{"shape": "droopy"}')
    image = _generate(fake, CharacterRequest(_photo(), "PETC0002", vrty_nm="코리안숏헤어"))
    assert matches_spec(image)
    call = fake.edits[0]
    assert call["model"] == "image-model"
    assert [ref[0] for ref in call["image"]] == ["style_ref.png", "photo.png"]
    assert "코리안숏헤어" in call["prompt"]
    assert "outer corners tilt DOWN" in call["prompt"]


def test_generate_눈_판별이_실패해도_생성한다():
    assert matches_spec(_generate(FakeOpenAI(_sheet(), RuntimeError("vision down"))))


def test_generate_눈을_못_찾으면_규격_밖_결과():
    assert not matches_spec(_generate(FakeOpenAI(_sheet(eyes=False))))


@pytest.mark.parametrize(
    "sheet",
    [RuntimeError("api down"), _sheet(figures=3)],
    ids=["외부 오류", "시트 오류"],
)
def test_generate_외부_오류와_시트_오류는_CharacterApiError(sheet):
    with pytest.raises(CharacterApiError):
        _generate(FakeOpenAI(sheet))


def test_generate_사진을_읽을_수_없으면_CharacterApiError():
    with pytest.raises(CharacterApiError):
        _generate(FakeOpenAI(_sheet()), CharacterRequest(b"not image", "PETC0001"))


def test_get_character_client_키가_없으면_None():
    assert get_character_client(get_settings()) is None


def test_get_character_client_키가_있으면_생성기(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    assert isinstance(get_character_client(get_settings()), OpenAICharacterClient)
    get_settings.cache_clear()

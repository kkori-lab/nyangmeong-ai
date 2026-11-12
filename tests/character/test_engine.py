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


# FN-MYP-011-01 : 굽기 (이미지 API 호출)
SWEATER = engine.BakeItem(7, "MYPC0004", "a green knitted dog sweater")


def _bake(fake: FakeOpenAI, bare: bytes, pet_se_cd="PETC0002") -> bytes:
    client = OpenAICharacterClient(fake, "image-model", "vision-model")
    return asyncio.run(client.bake(bare, pet_se_cd, SWEATER))


def test_bake_맨몸_시트를_설정한_모델로_보낸다():
    fake = FakeOpenAI(_sheet())
    bare = _sheet(figures=3)
    _bake(fake, bare)
    edit = fake.edits[0]
    assert edit["model"] == "image-model"
    assert (edit["size"], edit["quality"], edit["n"]) == ("1024x1024", "medium", 1)
    [(name, file, mime)] = edit["image"]
    assert (name, mime) == ("character.png", "image/png")
    assert file.getvalue() == bare


def test_bake_프롬프트에_종을_바꾼_굽기_지시가_들어간다():
    fake = FakeOpenAI(_sheet())
    _bake(fake, _sheet(), "PETC0002")
    assert "a green knitted cat sweater" in fake.edits[0]["prompt"]


def test_bake_응답_그림을_디코딩해_돌려준다():
    worn = _sheet(figures=2)
    assert _bake(FakeOpenAI(worn), _sheet()) == worn


def test_bake_외부_오류는_CharacterApiError():
    with pytest.raises(CharacterApiError):
        _bake(FakeOpenAI(RuntimeError("api down")), _sheet())


# 그림 참고 굽기 (설계 9절) : 아이템 그림을 둘째 그림으로
BAG_BY_IMAGE = engine.BakeItem(8, "MYPC0005", None, 77)
BAG_BY_HINT = engine.BakeItem(9, "MYPC0005", "a small red dog backpack")


def _item_png() -> bytes:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((16, 16, 48, 48), fill=(30, 160, 60, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _bake_item(fake: FakeOpenAI, item: engine.BakeItem, item_image: bytes | None) -> dict:
    client = OpenAICharacterClient(fake, "image-model", "vision-model")
    asyncio.run(client.bake(_sheet(), "PETC0001", item, item_image))
    return fake.edits[0]


def test_bake_그림_참고는_시트와_아이템_그림_두_장을_보낸다():
    edit = _bake_item(FakeOpenAI(_sheet()), BAG_BY_IMAGE, _item_png())
    [(first, sheet, _), (last, reference, mime)] = edit["image"]
    assert (first, last, mime) == ("character.png", "item.png", "image/png")
    assert sheet.getvalue() == _sheet()
    # 투명 배경은 흰 바탕으로 올려 보낸다
    pixels = Image.open(reference).convert("RGB")
    assert pixels.getpixel((0, 0)) == (255, 255, 255)
    assert pixels.getpixel((32, 32)) == (30, 160, 60)


def test_bake_그림_참고_프롬프트는_머리말과_부위_문장을_쓴다():
    prompt = _bake_item(FakeOpenAI(_sheet()), BAG_BY_IMAGE, _item_png())["prompt"]
    assert prompt.startswith("Two images are given.")
    assert "The FIRST image is a 2x2 sheet" in prompt
    assert "item exactly like the one shown in the LAST image" in prompt
    assert "worn as a backpack in all four figures" in prompt
    assert "{" not in prompt


def test_bake_굽기_지시_아이템은_그림_한_장과_지금_프롬프트():
    edit = _bake_item(FakeOpenAI(_sheet()), BAG_BY_HINT, None)
    assert [name for name, _, _ in edit["image"]] == ["character.png"]
    template = (engine.PROMPTS / "chibi_wear.txt").read_text(encoding="utf-8")
    assert edit["prompt"] == template.format(species="dog", wear="a small red dog backpack")
    assert "LAST image" not in edit["prompt"]
    assert "worn as a backpack" not in edit["prompt"]


@pytest.mark.parametrize(
    ("regn_cd", "text"),
    [
        ("MYPC0001", "on its head in all four figures"),
        ("MYPC0002", "on its face in all four figures"),
        ("MYPC0003", "around its neck in all four figures: a snug band"),
        ("MYPC0004", "on its torso in all four figures"),
        ("MYPC0005", "worn as a backpack in all four figures"),
    ],
)
def test_build_wear_prompt_그림_참고는_부위마다_착용_문장이_있다(regn_cd, text):
    prompt = engine.build_wear_prompt("cat", engine.BakeItem(1, regn_cd, None, 5), by_image=True)
    assert text in prompt
    assert "the one shown in the LAST image" in prompt
    assert "{" not in prompt


def test_build_wear_prompt_굽기_지시_목_아이템은_부위_문장을_붙이지_않는다():
    item = engine.BakeItem(1, "MYPC0003", "a red collar with a bell around its neck")
    prompt = engine.build_wear_prompt("dog", item)
    assert "wearing a red collar with a bell around its neck." in prompt
    assert "a snug band" not in prompt


def test_get_character_client_키가_없으면_None():
    assert get_character_client(get_settings()) is None


def test_get_character_client_키가_있으면_생성기(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    assert isinstance(get_character_client(get_settings()), OpenAICharacterClient)
    get_settings.cache_clear()

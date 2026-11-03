import asyncio
import io
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.character import bake, compose, engine, service
from app.character.canvas import Layout
from app.character.clients import CharacterApiError, GeneratedCharacter
from app.character.repository import CharacterJob
from app.character.rules import matches_spec
from app.character.schemas import FACE_W, FACE_X, FACE_Y
from tests.character.fakes import FakeCharacterJobRepository, SavedJob, fake_item, seed_rows

MAGENTA = (255, 0, 255, 255)
FUR = (200, 150, 100, 255)
BLACK = (0, 0, 0, 255)
RED = (220, 30, 30, 255)
BLUE = (30, 30, 220, 255)
GREEN = (30, 200, 30, 255)
CELLS = [(100, 150), (620, 150), (100, 650), (620, 650)]
LAYOUT = Layout(0.8, 136.0, 90.0)
BODY = "MYPC0004"
FACE = "MYPC0002"


def sheet(
    *, hat=False, body=False, face=False, shift=(0, 0), over_body: tuple | None = None
) -> bytes:
    """over_body : 의상 상자와 겹치는 자리에 칠할 색 (겹침 순서 확인용)"""
    image = Image.new("RGBA", (1024, 1024), MAGENTA)
    draw = ImageDraw.Draw(image)
    for x, y in CELLS:
        x, y = x + shift[0], y + shift[1]
        draw.rectangle((x, y, x + 300, y + 300), fill=FUR, outline=BLACK, width=4)
        if hat:
            draw.rectangle((x + 60, y - 70, x + 240, y + 40), fill=RED)
        if body:
            draw.rectangle((x + 40, y + 200, x + 260, y + 280), fill=BLUE)
        if face:
            draw.rectangle((x + 80, y + 90, x + 220, y + 130), fill=GREEN)
        if over_body:
            draw.rectangle((x + 100, y + 170, x + 200, y + 240), fill=over_body)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def rgba(png: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(png)).convert("RGBA"))


def count(pixels: np.ndarray, color: tuple[int, int, int, int]) -> int:
    return int((pixels == color).all(axis=2).sum())


def layer_of(worn_sheet: bytes) -> bake.Sprite | None:
    bare = engine.stand_front_cut(sheet())
    worn = engine.stand_front_cut(worn_sheet)
    return bake.item_layer(bare.image, bake.worn_sprite(bare, worn))


# FN-MYP-011-01 : 착용 시트 -> 레이어
def test_item_layer_맨몸_컷_좌표로_아이템만_뽑는다():
    layer = layer_of(sheet(body=True))
    assert layer is not None
    assert (layer.x, layer.y) == (40, 200)
    assert layer.image.size == (221, 81)
    pixels = np.array(layer.image)
    assert count(pixels, BLUE) == pixels.shape[0] * pixels.shape[1]


def test_item_layer_맨몸과_같으면_빈_레이어():
    assert layer_of(sheet()) is None


def test_worn_sprite_밀려_그려진_시트도_맞춘다():
    layer = layer_of(sheet(body=True, shift=(5, -6)))
    assert layer is not None
    assert (layer.x, layer.y) == (40, 200)


def test_worn_sprite_맨몸_위로_나온_머리_아이템은_음수_좌표():
    bare = engine.stand_front_cut(sheet())
    sprite = bake.worn_sprite(bare, engine.stand_front_cut(sheet(hat=True)))
    assert sprite.y == -70


def test_validate_레이어가_비면_거절():
    with pytest.raises(engine.SheetError):
        bake.validate(sheet(), sheet(), BODY)


def test_validate_머리는_착용_컷만_있으면_통과():
    bake.validate(sheet(), sheet(hat=True), bake.REGN_HEAD)


# FN-MYP-011-01·FN-MYP-010-13 : 합성
def test_render_맨몸은_512_규격():
    assert matches_spec(compose.render(sheet(), LAYOUT, {}))


def test_render_얼굴_영역에서_레이어가_덮지_않은_화소는_맨몸과_같다():
    bare = rgba(compose.render(sheet(), LAYOUT, {}))
    worn = rgba(compose.render(sheet(), LAYOUT, {BODY: sheet(body=True)}))
    box = (slice(FACE_Y, FACE_Y + FACE_W), slice(FACE_X, FACE_X + FACE_W))
    differs = (bare[box] != worn[box]).any(axis=2)
    assert differs.any()
    assert (worn[box][differs] == BLUE).all()


def _painted(worn: dict[str, bytes], color) -> np.ndarray:
    return (rgba(compose.render(sheet(), LAYOUT, worn)) == color).all(axis=2)


def test_render_얼굴은_의상_위에_겹친다():
    body = {BODY: sheet(body=True)}
    face = {FACE: sheet(over_body=GREEN)}
    # 따로 입혔을 때 둘 다 칠해지는 자리
    overlap = _painted(body, BLUE) & _painted(face, GREEN)
    assert overlap.sum() > 100
    pixels = rgba(compose.render(sheet(), LAYOUT, body | face))
    assert (pixels[overlap] == GREEN).all()
    assert count(pixels, BLUE) > 0


def test_render_의상은_머리_착용_바탕_위에_겹친다():
    head = {bake.REGN_HEAD: sheet(over_body=RED)}
    body = {BODY: sheet(body=True)}
    overlap = _painted(head, RED) & _painted(body, BLUE)
    assert overlap.sum() > 100
    pixels = rgba(compose.render(sheet(), LAYOUT, head | body))
    assert (pixels[overlap] == BLUE).all()
    assert count(pixels, RED) > 0


def test_render_머리_착용_컷이_바탕():
    pixels = rgba(compose.render(sheet(), LAYOUT, {bake.REGN_HEAD: sheet(hat=True)}))
    assert count(pixels, RED) > 0


def test_render_머리와_의상을_같이_입는다():
    pixels = rgba(
        compose.render(sheet(), LAYOUT, {bake.REGN_HEAD: sheet(hat=True), BODY: sheet(body=True)})
    )
    assert count(pixels, RED) > 0 and count(pixels, BLUE) > 0


# 굽기 지시
def test_굽기_지시_시드는_다섯_부위_26개_신발_없음():
    rows = seed_rows()
    assert len(rows) == 26
    regions = sorted({row["regn_cd"] for row in rows})
    assert regions == ["MYPC0001", "MYPC0002", "MYPC0003", "MYPC0004", "MYPC0005"]


def test_build_wear_prompt_종을_치환한다():
    item = fake_item("green-sweater")
    prompt = engine.build_wear_prompt("cat", item)
    assert "green knitted cat sweater" in prompt
    assert "{" not in prompt


def test_가짜_저장소_아이템은_모두_목록에_있다():
    targets = asyncio.run(FakeCharacterJobRepository().list_bake_items())
    assert len(targets) == 26
    assert {item.bake_hint for item in targets.values()} == {
        row["bake_hint"] for row in seed_rows()
    }
    assert all(sn == item.item_sn for sn, item in targets.items())


# 굽기 큐
class BakeClient:
    """아이템별로 정해 둔 결과를 내는 가짜 생성기"""

    def __init__(self, fail: frozenset[int] = frozenset(), flaky: frozenset[int] = frozenset()):
        self.fail = fail
        self.flaky = flaky
        self.calls: list[int] = []

    async def generate(self, request) -> GeneratedCharacter:
        return GeneratedCharacter(compose.render(sheet(), LAYOUT, {}), sheet(), LAYOUT)

    async def bake(self, bare: bytes, pet_se_cd, item: engine.BakeItem) -> bytes:
        self.calls.append(item.item_sn)
        if item.item_sn in self.fail:
            raise CharacterApiError
        if item.item_sn in self.flaky and self.calls.count(item.item_sn) == 1:
            return sheet()
        return sheet(body=True)


class Repo(FakeCharacterJobRepository):
    async def list_bake_items(self) -> dict[int, engine.BakeItem]:
        names = {1: "green-sweater", 2: "hoodie", 3: "bow-tie"}
        return {sn: replace(fake_item(name), item_sn=sn) for sn, name in names.items()}


def run(client: BakeClient, repo: Repo, enabled: bool) -> None:
    job = CharacterJob(1, "PETC0001")
    repo.jobs[1] = SavedJob(job, 3)
    queue = service.BakeQueue()
    asyncio.run(service.generate_and_report(client, repo, queue, job, b"photo", enabled))


def test_굽기가_꺼져_있으면_이미지_API를_부르지_않는다():
    client, repo = BakeClient(), Repo()
    run(client, repo, False)
    assert client.calls == []
    assert repo.jobs[1].image is not None


def test_굽기가_켜져_있으면_전_아이템을_한_번씩_굽는다():
    client, repo = BakeClient(), Repo()
    run(client, repo, True)
    assert sorted(client.calls) == [1, 2, 3]
    assert set(repo.jobs[1].item_sheets) == {1, 2, 3}


def test_굽기_실패는_한_번_다시_해_보고_실패로_보고한다():
    client, repo = BakeClient(fail=frozenset({2})), Repo()
    run(client, repo, True)
    assert client.calls.count(2) == 2
    assert repo.jobs[1].failed_items == {2}
    assert set(repo.jobs[1].item_sheets) == {1, 3}


def test_빈_레이어는_다시_굽는다():
    client, repo = BakeClient(flaky=frozenset({2})), Repo()
    run(client, repo, True)
    assert client.calls.count(2) == 2
    assert 2 in repo.jobs[1].item_sheets


def test_put_first_앞으로_올리고_굽는_중이면_넣지_않는다():
    queue = service.BakeQueue()
    client, repo = BakeClient(), Repo()
    item = fake_item("hoodie")
    first = service.BakeTask(client, repo, 1, 1, item, b"", "PETC0001")
    second = service.BakeTask(client, repo, 1, 2, item, b"", "PETC0001")
    queue.add(first)
    queue.add(second)
    queue.add(first)
    queue.put_first(second)
    assert [task.item_sn for task in queue._tasks] == [2, 1]
    queue._running.add(first.key)
    queue._tasks.clear()
    queue.put_first(first)
    assert not queue._tasks


# 어두운 털 : 추가-4
DARK = (30, 30, 30, 255)
WHITE = (250, 250, 250, 255)


def dark_sheet(*, source: bool = False, item: bool = False, pearl: bool = False) -> bytes:
    """검은 털 캐릭터 (source면 털을 밝힌 굽기 입력에 그린 착용 시트)"""
    image = Image.new("RGBA", (1024, 1024), MAGENTA)
    draw = ImageDraw.Draw(image)
    fur = (188, 188, 188, 255) if source else DARK
    for x, y in CELLS:
        draw.rectangle((x, y, x + 300, y + 300), fill=fur, outline=BLACK, width=6)
        draw.rectangle((x + 100, y + 100, x + 130, y + 130), fill=(150, 80, 30, 255))
        if item:
            fill = WHITE if pearl else RED
            draw.rectangle((x + 60, y + 180, x + 240, y + 250), fill=fill, outline=BLACK, width=8)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def dark_layer(worn_sheet: bytes) -> bake.Sprite | None:
    base = bake.layer_base(dark_sheet())
    assert base.lit
    worn = bake.worn_sprite(base.cut, engine.stand_front_cut(worn_sheet))
    return bake.item_layer(base.cut.image, worn, base.lit)


def test_bake_source_어두운_털은_밝히고_머리는_원본():
    source = bake.bake_source(dark_sheet(), BODY)
    assert source != dark_sheet()
    assert rgba(source)[300, 300, 0] >= bake.LIT_BASE
    assert bake.bake_source(dark_sheet(), bake.REGN_HEAD) == dark_sheet()


def test_bake_source_밝은_털은_그대로():
    assert bake.bake_source(sheet(), BODY) == sheet()
    assert not bake.layer_base(sheet()).lit


def test_item_layer_검은_털에서_검은_외곽선을_유지한다():
    layer = dark_layer(dark_sheet(source=True, item=True))
    assert layer is not None
    assert layer.image.size == (181, 71)
    pixels = np.array(layer.image)
    assert count(pixels, BLACK) == 2 * (181 + 71) * 8 - 4 * 64


def test_item_layer_검은_외곽선_안쪽_흰_아이템은_남는다():
    layer = dark_layer(dark_sheet(source=True, item=True, pearl=True))
    assert layer is not None
    assert count(np.array(layer.image), WHITE) > 0


def test_item_layer_밝힌_털은_레이어에_남지_않는다():
    source = Image.open(io.BytesIO(dark_sheet(source=True, item=True))).convert("RGBA")
    draw = ImageDraw.Draw(source)
    for x, y in CELLS:
        draw.rectangle((x + 40, y + 200, x + 58, y + 230), fill=(235, 235, 235, 255))
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    layer = dark_layer(buffer.getvalue())
    assert layer is not None
    assert count(np.array(layer.image), (235, 235, 235, 255)) == 0


def test_item_layer_밝은_털의_외곽선_복구는_맨몸_외곽선을_넘지_않는다():
    layer = layer_of(sheet(body=True))
    assert layer is not None
    assert layer.image.size == (221, 81)


def test_render_검은_털_바탕은_원본_색():
    worn = {BODY: dark_sheet(source=True, item=True)}
    pixels = rgba(compose.render(dark_sheet(), LAYOUT, worn))
    assert count(pixels, DARK) > 0
    assert count(pixels, RED) > 0
    assert count(pixels, (188, 188, 188, 255)) == 0


def test_굽기_입력은_어두운_털이면_밝힌_시트():
    received: list[bytes] = []

    class Client:
        async def bake(self, source: bytes, pet_se_cd, item: engine.BakeItem) -> bytes:
            received.append(source)
            return dark_sheet(source=True, item=True)

    repo = Repo()
    repo.jobs[1] = SavedJob(CharacterJob(1, "PETC0001"), 3)
    item = fake_item("bow-tie")
    task = service.BakeTask(Client(), repo, 1, 3, item, dark_sheet(), "PETC0001")
    asyncio.run(service._bake_one(task))
    assert received == [bake.bake_source(dark_sheet(), item.regn_cd)]
    assert 3 in repo.jobs[1].item_sheets


# 착용 지시 : 추가-6
@pytest.mark.parametrize(
    ("item_id", "phrase"),
    [
        ("red-beanie", "the ears are completely hidden under it"),
        ("green-sweater", "the tail stay uncovered"),
        ("round-glasses", "resting on the muzzle"),
    ],
)
def test_build_wear_prompt_부위별_착용_지시(item_id: str, phrase: str):
    assert phrase in engine.build_wear_prompt("cat", fake_item(item_id))


# 시간 기록 : 추가-5
def test_굽기_시간과_시도_횟수를_남긴다(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", "app.character.service")
    run(BakeClient(flaky=frozenset({2})), Repo(), True)
    assert "굽기 시간: pixelCharSn=1, itemSn=2" in caplog.text
    assert "2회 시도" in caplog.text
    assert "전체 굽기 시간" in caplog.text


def test_합성_구간별_시간을_남긴다(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", "app.character.compose")
    compose.render(sheet(), LAYOUT, {BODY: sheet(body=True)})
    assert "합성 시간: 아이템 1개" in caplog.text

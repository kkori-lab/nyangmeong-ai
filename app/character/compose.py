"""FN-MYP-011-01·FN-MYP-010-13 : 착장 합성

- 머리 착용 컷을 바탕으로 레이어를 얹는 방식 : `docs/design/pixel-character-engine.md` 5번
- 외부 호출 없음
"""

import io
import logging
import time
from collections.abc import Mapping
from dataclasses import replace

from PIL import Image

from app.character import bake, engine
from app.character.canvas import Layout
from app.character.schemas import CANVAS_SIZE

logger = logging.getLogger(__name__)

# MYPG01 공통코드 : 의상 → 가방 → 목 → 얼굴
LAYER_ORDER = ("MYPC0004", "MYPC0005", "MYPC0003", "MYPC0002")


def _paste(canvas: Image.Image, sprite: bake.Sprite, layout: Layout) -> None:
    width, height = sprite.image.size
    size = (max(1, round(width * layout.scale)), max(1, round(height * layout.scale)))
    # 도트 유지 : NEAREST
    big = sprite.image.convert("RGBA").resize(size, Image.NEAREST)
    x = round(layout.origin_x + sprite.x * layout.scale)
    y = round(layout.origin_y + sprite.y * layout.scale)
    canvas.paste(big, (x, y), big)


def render(bare_sheet: bytes, layout: Layout, worn_sheets: Mapping[str, bytes]) -> bytes:
    """부위 코드별 착용 시트를 입힌 512×512 PNG"""
    started = time.perf_counter()
    bare = engine.stand_front_cut(bare_sheet)
    head = bake.Sprite(bare.image, 0, 0)
    if bake.REGN_HEAD in worn_sheets:
        head = bake.worn_sprite(bare, engine.stand_front_cut(worn_sheets[bake.REGN_HEAD]))
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE))
    _paste(canvas, head, layout)
    base_done = time.perf_counter()

    layers = [regn_cd for regn_cd in LAYER_ORDER if regn_cd in worn_sheets]
    if layers:
        base = bake.layer_base(bare_sheet)
        # 밝힌 시트의 컷은 맨몸 컷과 잘린 범위가 조금 다를 수 있음
        shift_x, shift_y = base.cut.left - bare.left, base.cut.top - bare.top
        for regn_cd in layers:
            worn = engine.stand_front_cut(worn_sheets[regn_cd])
            sprite = bake.worn_sprite(base.cut, worn)
            layer = bake.item_layer(base.cut.image, sprite, base.lit)
            if layer is not None:
                _paste(canvas, replace(layer, x=layer.x + shift_x, y=layer.y + shift_y), layout)
    layers_done = time.perf_counter()

    buffer = io.BytesIO()
    canvas.save(buffer, "PNG", optimize=True)
    logger.info(
        "합성 시간: 아이템 %d개, 바탕 %.2f초, 레이어 %.2f초, PNG %.2f초",
        len(worn_sheets),
        base_done - started,
        layers_done - base_done,
        time.perf_counter() - layers_done,
    )
    return buffer.getvalue()

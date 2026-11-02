"""착용 컷 정렬·아이템 레이어 추출

- pixel-dog-generator `pipeline/chibi-style`(138f722)의 `extract.py`에서 일부만 옮긴 코드
- 굽기 캐시·판별 사다리는 제외 : 시트는 Java 보관
- 외부 호출 없음
"""

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from app.character import engine

# MYPG01 공통코드 : 머리는 착용 컷 전체가 바탕, 나머지는 레이어
REGN_HEAD = "MYPC0001"

# 채널 차이 : 8이면 다시 그려진 털 음영까지 잡힘
DIFF_TOL = 32
# 시트가 조금 밀려 그려지는 경우의 평행이동 탐색 : 성긴 탐색 뒤 그 주변만
ALIGN_SEARCH = 8
ALIGN_COARSE_STEP = 4
ALIGN_FINE_SEARCH = 3
ALIGN_FINE_STEP = 2
MIN_BLOB_PX = 40
# 가장 큰 덩어리 대비 : 끈·안경처럼 나뉜 아이템 유지
KEEP_BLOB_RATIO = 0.3
OPEN_SIZE = (3, 3)

# 어두운 털 판정 : 외곽선보다 밝고 채도 낮은 화소가 캐릭터의 절반 이상
FUR_MIN, FUR_MAX = 26, 120
FUR_CHROMA_MAX = 40
DARK_FUR_SHARE = 0.5
# 밝힌 털 : 검은 외곽선·아이템과 구분되는 밝은 회색
LIT_BASE = 170
LIT_GAIN = 0.6
LIT_CHROMA_MAX = 24
# 맨몸과 색이 비슷해 빠진 외곽선 복구 범위
OUTLINE_MAX = 60
OUTLINE_REACH = 8


@dataclass(frozen=True)
class Sprite:
    """맨몸 컷 기준 좌표에 놓일 그림"""

    image: Image.Image
    x: int
    y: int


@dataclass(frozen=True)
class LayerBase:
    """레이어 차이의 기준 컷 : lit이면 털을 밝힌 시트의 컷"""

    cut: engine.Cut
    lit: bool


def _pixels(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGBA")).astype(int)


def _lit_sheet(sheet: bytes) -> bytes | None:
    """어두운 털을 밝힌 시트 (어두운 털이 아니면 None)"""
    pixels = _pixels(Image.open(io.BytesIO(sheet)))
    rgb = pixels[..., :3]
    shown = (pixels[..., 3] >= 128) & (np.abs(rgb - rgb[0, 0]).sum(axis=2) > engine.BG_THRESHOLD)
    top, low = rgb.max(axis=2), rgb.min(axis=2)
    fur = shown & (top >= FUR_MIN) & (top < FUR_MAX) & (top - low < FUR_CHROMA_MAX)
    if fur.sum() < DARK_FUR_SHARE * max(1, shown.sum()):
        return None
    rgb[fur] = (LIT_BASE + top[fur] * LIT_GAIN).astype(int)[:, None]
    buffer = io.BytesIO()
    Image.fromarray(pixels.astype(np.uint8), "RGBA").save(buffer, "PNG")
    return buffer.getvalue()


def bake_source(sheet: bytes, regn_cd: str) -> bytes:
    """굽기 입력 : 검은 털 위 검은 외곽선은 차이로 못 찾음, 머리는 합성 바탕이라 원본"""
    if regn_cd == REGN_HEAD:
        return sheet
    return _lit_sheet(sheet) or sheet


def layer_base(sheet: bytes) -> LayerBase:
    lit = _lit_sheet(sheet)
    return LayerBase(engine.stand_front_cut(lit or sheet), lit is not None)


def _matched(bare: np.ndarray, worn: np.ndarray, x: int, y: int, step: int) -> int:
    """worn을 (x, y)에 놓을 때 맨몸과 색이 같은 화소 수 (step 간격 표본)"""
    top, left = max(0, y), max(0, x)
    bottom = min(bare.shape[0], y + worn.shape[0])
    right = min(bare.shape[1], x + worn.shape[1])
    if top >= bottom or left >= right:
        return 0
    a = bare[top:bottom:step, left:right:step]
    b = worn[top - y : bottom - y : step, left - x : right - x : step]
    same = np.abs(a[..., :3] - b[..., :3]).max(axis=2) <= DIFF_TOL
    return int((same & (a[..., 3] > 0) & (b[..., 3] > 0)).sum())


def _best(
    bare: np.ndarray, worn: np.ndarray, center: tuple[int, int], reach: int, gap: int, step: int
) -> tuple[int, int]:
    offsets = [
        (center[0] + dx, center[1] + dy)
        for dy in range(-reach, reach + 1, gap)
        for dx in range(-reach, reach + 1, gap)
    ]
    return max(offsets, key=lambda offset: _matched(bare, worn, *offset, step))


def worn_sprite(bare: engine.Cut, worn: engine.Cut) -> Sprite:
    """착용 컷을 맨몸 컷 좌표로 정렬 (컷마다 잘린 범위가 달라 시트 위치에서 출발)"""
    bare_px, worn_px = _pixels(bare.image), _pixels(worn.image)
    start = (worn.left - bare.left, worn.top - bare.top)
    coarse = _best(bare_px, worn_px, start, ALIGN_SEARCH, ALIGN_COARSE_STEP, ALIGN_COARSE_STEP)
    x, y = _best(bare_px, worn_px, coarse, ALIGN_FINE_SEARCH, 1, ALIGN_FINE_STEP)
    return Sprite(worn.image, x, y)


def _keep(mask: np.ndarray) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if not count:
        return mask
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    floor = max(MIN_BLOB_PX, KEEP_BLOB_RATIO * sizes.max())
    kept = [k + 1 for k in range(count) if sizes[k] >= floor]
    return np.isin(labels, kept)


def _without_lit_fur(mask: np.ndarray, over: np.ndarray) -> np.ndarray:
    """바깥에서 이어진 밝힌 털만 제거 : 외곽선 안쪽의 흰 진주·회색 옷은 유지"""
    rgb = over[..., :3]
    top = rgb.max(axis=2)
    lit = (top >= LIT_BASE) & (top - rgb.min(axis=2) <= LIT_CHROMA_MAX)
    seeds = lit & ndimage.binary_dilation(~mask)
    return mask & ~ndimage.binary_propagation(seeds, mask=lit)


def item_layer(bare: Image.Image, worn: Sprite, lit: bool = False) -> Sprite | None:
    """착용 컷에서 맨몸과 다른 화소만 남긴 레이어 (달라진 곳이 없으면 None)"""
    bare_px, worn_px = _pixels(bare), _pixels(worn.image)
    left, top = min(0, worn.x), min(0, worn.y)
    right = max(bare_px.shape[1], worn.x + worn_px.shape[1])
    bottom = max(bare_px.shape[0], worn.y + worn_px.shape[0])

    base = np.zeros((bottom - top, right - left, 4), dtype=int)
    base[-top : -top + bare_px.shape[0], -left : -left + bare_px.shape[1]] = bare_px
    over = np.zeros_like(base)
    y, x = worn.y - top, worn.x - left
    over[y : y + worn_px.shape[0], x : x + worn_px.shape[1]] = worn_px

    opaque = over[..., 3] > 0
    changed = np.abs(base[..., :3] - over[..., :3]).max(axis=2) > DIFF_TOL
    mask = opaque & (changed | (base[..., 3] == 0))
    mask = _keep(ndimage.binary_opening(mask, structure=np.ones(OPEN_SIZE)))
    if not mask.any():
        return None
    # 안경알 안쪽 : 밝힌 시트에서 채우면 밝힌 털이 바탕을 가림
    mask = _without_lit_fur(mask, over) if lit else ndimage.binary_fill_holes(mask) & opaque
    dark = opaque & (over[..., :3].max(axis=2) < OUTLINE_MAX)
    near = ndimage.binary_dilation(mask, structure=np.ones((3, 3)), iterations=OUTLINE_REACH)
    mask |= near & dark
    if not mask.any():
        return None

    ys, xs = np.where(mask)
    y1, y2, x1, x2 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    cropped = over[y1:y2, x1:x2].astype(np.uint8)
    cropped[~mask[y1:y2, x1:x2]] = 0
    return Sprite(Image.fromarray(cropped, "RGBA"), int(x1) + left, int(y1) + top)


def validate(bare_sheet: bytes, worn_sheet: bytes, regn_cd: str) -> None:
    """구운 시트를 합성에 쓸 수 있는지 판정 (쓸 수 없으면 SheetError)"""
    worn = engine.stand_front_cut(worn_sheet)
    if regn_cd == REGN_HEAD:
        return
    base = layer_base(bare_sheet)
    if item_layer(base.cut.image, worn_sprite(base.cut, worn), base.lit) is None:
        raise engine.SheetError("아이템 레이어가 비어 있음")

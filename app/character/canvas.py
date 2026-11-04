"""512 캔버스 배치

- pixel-dog-generator `spike/canvas512.py`·`spike/canvas512_v4.py`에서 옮긴 코드
- 규칙은 `docs/design/pixel-character-engine.md` 4번
"""

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from app.character.schemas import CANVAS_SIZE

# FN-MYP-010-17 : 캐릭터 높이 통일 뒤 눈 위치 고정 -> 크기·얼굴 자리 일정
CHARACTER_HEIGHT = 341
# 얼굴 영역과 떼어 숫자로 고정 : 지금까지 만든 캐릭터와 같은 눈 높이
# (옛 얼굴 영역 (128, 64, 256, 256)의 가운데·56% 지점, 새 영역 (96, 32, 320, 320)에서 약 55%)
EYE_X = 256.0
EYE_Y = 207.36
# 눈이 그림 위쪽에 있는 캐릭터 보정 : 입이 얼굴 영역 아래로 잘림 방지
TOP_MAX = 100

DARK_MAX = 70
# 턱·몸의 어두운 무늬 제외
EYE_SEARCH_TOP = 0.6
OPEN_PASSES = 2
OUTLINE_REACH = 3
BLOB_MIN_PX, BLOB_MAX_PX = 60, 4000
BLOB_RATIO_MIN, BLOB_RATIO_MAX = 0.5, 2.0
SAME_ROW = 0.06
MIN_APART = 0.15
SIZE_SIMILAR = 0.5
HIGHLIGHT_MIN = 200
HIGHLIGHT_MIN_PX, HIGHLIGHT_MAX_PX = 30, 400

Point = tuple[float, float]


@dataclass(frozen=True)
class Layout:
    """맨몸 컷에서 잰 배치값 : 모든 착장에 재사용 -> 얼굴 자리 고정"""

    scale: float
    origin_x: float
    origin_y: float


@dataclass(frozen=True)
class Placement:
    png: bytes
    eyes: tuple[Point, Point]
    scale: float
    origin: Point
    clipped: bool

    @property
    def layout(self) -> Layout:
        return Layout(self.scale, *self.origin)

    @property
    def canvas_eyes(self) -> tuple[Point, Point]:
        """512 캔버스 위 눈 좌표 (eyes는 원본 컷 기준)"""
        (x1, y1), (x2, y2) = self.eyes
        origin_x, origin_y = self.origin
        return (
            (origin_x + x1 * self.scale, origin_y + y1 * self.scale),
            (origin_x + x2 * self.scale, origin_y + y2 * self.scale),
        )


def _pair(blobs: list[tuple[int, float, float]], image: Image.Image) -> tuple[Point, Point] | None:
    """나란하고 크기가 비슷한 덩어리 쌍 중 가장 큰 것"""
    best = None
    for i, (size1, x1, y1) in enumerate(blobs):
        for size2, x2, y2 in blobs[i + 1 :]:
            if (
                abs(y1 - y2) < SAME_ROW * image.height
                and abs(x1 - x2) > MIN_APART * image.width
                and min(size1, size2) / max(size1, size2) > SIZE_SIMILAR
                and (best is None or size1 + size2 > best[0])
            ):
                left, right = sorted([(x1, y1), (x2, y2)])
                best = (size1 + size2, left, right)
    return (best[1], best[2]) if best else None


def _blobs(
    mask: np.ndarray, outside: np.ndarray, min_px: int, max_px: int
) -> list[tuple[int, float, float]]:
    """둥글고 그림 바깥에 닿지 않은 덩어리 (바깥에 닿으면 눈이 아닌 외곽선)"""
    labels, count = ndimage.label(mask)
    blobs = []
    for k in range(1, count + 1):
        ys, xs = np.where(labels == k)
        if outside[ys, xs].any():
            continue
        ratio = (np.ptp(ys) + 1) / (np.ptp(xs) + 1)
        if min_px <= ys.size <= max_px and BLOB_RATIO_MIN <= ratio <= BLOB_RATIO_MAX:
            blobs.append((ys.size, float(xs.mean()), float(ys.mean())))
    return blobs


def find_eyes(image: Image.Image) -> tuple[Point, Point] | None:
    """위쪽 60%의 어두운 눈동자 쌍, 없으면 흰 하이라이트 쌍 (맨몸 그림 전용 : 모자 그림은 오검출)"""
    pixels = np.array(image.convert("RGBA")).astype(int)
    opaque = pixels[..., 3] > 0
    top = np.zeros(opaque.shape, dtype=bool)
    top[: int(image.height * EYE_SEARCH_TOP)] = True
    outside = ndimage.binary_dilation(~opaque, iterations=OUTLINE_REACH)

    dark = opaque & top & (pixels[..., :3].max(axis=2) < DARK_MAX)
    opened = ndimage.binary_opening(dark, iterations=OPEN_PASSES)
    pair = _pair(_blobs(opened, outside, BLOB_MIN_PX, BLOB_MAX_PX), image)
    if pair is not None:
        return pair

    # 검은 털 : 눈동자가 털과 붙음 -> 프롬프트가 고정한 눈마다 흰 점 1개
    white = opaque & top & (pixels[..., :3].min(axis=2) > HIGHLIGHT_MIN)
    return _pair(_blobs(white, outside, HIGHLIGHT_MIN_PX, HIGHLIGHT_MAX_PX), image)


def place(image: Image.Image) -> Placement | None:
    """FN-MYP-010-17 : 높이 통일 뒤 두 눈 기준 512×512 배치 (눈을 못 찾으면 None)"""
    eyes = find_eyes(image)
    if eyes is None:
        return None
    (x1, y1), (x2, y2) = eyes
    scale = CHARACTER_HEIGHT / image.height
    origin_x = EYE_X - (x1 + x2) / 2 * scale
    # 입력은 그림에 맞게 잘린 컷 : origin_y가 곧 캐릭터 상단
    origin_y = min(EYE_Y - (y1 + y2) / 2 * scale, TOP_MAX)

    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    # 도트 유지 : NEAREST
    big = image.convert("RGBA").resize(size, Image.NEAREST)
    x, y = round(origin_x), round(origin_y)
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE))
    canvas.paste(big, (x, y), big)
    clipped = x < 0 or y < 0 or x + size[0] > CANVAS_SIZE or y + size[1] > CANVAS_SIZE

    buffer = io.BytesIO()
    canvas.save(buffer, "PNG", optimize=True)
    return Placement(buffer.getvalue(), eyes, scale, (origin_x, origin_y), clipped)

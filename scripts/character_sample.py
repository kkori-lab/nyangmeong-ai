"""FN-MYP-010-18 : 실제 생성 샘플로 규격 일관성 확인 (유료, CI 제외)

사진 폴더의 `dog_*`·`cat_*` 파일을 생성해 결과 그림과 result.csv를 저장소 밖 폴더에 저장.
사용: uv run python scripts/character_sample.py <사진 폴더> <결과 폴더>
"""

import csv
import sys
from pathlib import Path

from openai import OpenAI

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.character.clients import CharacterRequest, OpenAICharacterClient  # noqa: E402
from app.character.rules import matches_spec  # noqa: E402
from app.core.config import get_settings  # noqa: E402

PREFIX = {"dog": "PETC0001", "cat": "PETC0002"}
FIELDS = [
    "photo",
    "eyes_found",
    "left_eye_x",
    "left_eye_y",
    "right_eye_x",
    "right_eye_y",
    "canvas_eye_x",
    "canvas_eye_y",
    "scale",
    "clipped",
    "matches_spec",
    "error",
]


def main(photo_dir: Path, out_dir: Path) -> int:
    if out_dir.resolve().is_relative_to(REPO):
        print("결과 폴더는 저장소 밖이어야 합니다(사진·결과 커밋 금지)", file=sys.stderr)
        return 2
    settings = get_settings()
    key = settings.openai_api_key.get_secret_value()
    if not key:
        print("OPENAI_API_KEY가 없습니다", file=sys.stderr)
        return 2
    client = OpenAICharacterClient(
        OpenAI(api_key=key, timeout=settings.character_timeout_sec, max_retries=1),
        settings.character_image_model,
        settings.character_vision_model,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for photo in sorted(p for p in photo_dir.iterdir() if p.is_file()):
        species = photo.name.split("_")[0].lower()
        if species not in PREFIX:
            print(f"건너뜀(dog_·cat_ 아님): {photo.name}")
            continue
        row: dict[str, object] = {"photo": photo.name}
        try:
            rendered = client.render(CharacterRequest(photo.read_bytes(), PREFIX[species]))
        except Exception as exc:
            row["error"] = type(exc.__cause__ or exc).__name__
            rows.append(row)
            print(row)
            continue
        (out_dir / f"{photo.stem}_front.png").write_bytes(rendered.front)
        placed = rendered.placement
        row["eyes_found"] = placed is not None
        if placed is not None:
            (out_dir / f"{photo.stem}_512.png").write_bytes(placed.png)
            (left_x, left_y), (right_x, right_y) = placed.eyes
            (canvas_left_x, canvas_left_y), (canvas_right_x, canvas_right_y) = placed.canvas_eyes
            row.update(
                canvas_eye_x=round((canvas_left_x + canvas_right_x) / 2, 1),
                canvas_eye_y=round((canvas_left_y + canvas_right_y) / 2, 1),
                left_eye_x=round(left_x, 1),
                left_eye_y=round(left_y, 1),
                right_eye_x=round(right_x, 1),
                right_eye_y=round(right_y, 1),
                scale=round(placed.scale, 3),
                clipped=placed.clipped,
                matches_spec=matches_spec(placed.png),
            )
        rows.append(row)
        print(row)
    with (out_dir / "result.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))

"""턴 기록 주 단위 집계 (SCR-AIM-004 추가 요청, 2026-11-26). 외부 API를 부르지 않는다

돌리기: uv run python -m scripts.turn_stats <LOG_DIR> [--weeks 4]
- LOG_DIR의 ai_YYYY-MM-DD.log에서 app.chat.turnlog 줄(턴·카드 결과)만 읽어 ISO 주로 묶는다
- 턴 수·종류·결과·도구·READ 횟수·실패 태그 비율·재요청 후보·카드 결과를 찍는다
- 줄 모양과 집계는 app/chat/turnlog.py 한 곳. 없는 폴더·빈 로그는 0건
"""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    # uv run python scripts/turn_stats.py 로 돌려도 app을 찾게
    sys.path.insert(0, str(ROOT))

from app.chat import turnlog  # noqa: E402


def main(argv: list[str] | None = None, today: date | None = None) -> str:
    parser = argparse.ArgumentParser(description="턴 기록 주 단위 집계")
    parser.add_argument("log_dir", help="LOG_DIR (ai_YYYY-MM-DD.log가 있는 폴더)")
    parser.add_argument("--weeks", type=int, default=4, help="이번 주 포함 몇 주 (기본 4)")
    args = parser.parse_args(argv)
    since = turnlog.week_start(today or date.today(), args.weeks)
    weeks = turnlog.summarize(turnlog.log_lines(Path(args.log_dir), since))
    return turnlog.render(weeks)


if __name__ == "__main__":
    sys.stdout.write(main())

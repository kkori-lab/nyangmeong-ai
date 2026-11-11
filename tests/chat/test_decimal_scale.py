"""건강 수치 소수 자리수(2026-11-11) : 확인 카드 decimal 칸을 Java @Digits 자리수로 반올림"""

from datetime import datetime

import pytest

from app.chat import catalog, tools
from tests.chat.fakes import fake_catalog_json

NOW = datetime(2026, 11, 11, 9, 0)
DAILY = "draft_daily_health_record"
CYCLE = "draft_observation_cycle"


def build(raw: dict) -> catalog.Catalog:
    return catalog.build(catalog.ToolCatalogResponse.model_validate(raw))


def entry(name: str, raw: dict | None = None) -> catalog.CatalogEntry:
    return build(raw or fake_catalog_json()).entries[name]


def daily_card(rcd_nvl: float, raw: dict | None = None) -> dict:
    card = entry(DAILY, raw)
    tools.use_catalog(build(raw or fake_catalog_json()))
    call = tools.parse(
        DAILY, {"daily_rcd_idct_cd": "HLTC0014", "rcd_ymd": "2026-11-11", "rcd_nvl": rcd_nvl}
    )
    assert call.args is not None
    return catalog.card_input(card, call.args.model_dump(exclude_none=True), NOW, {}, None)


def test_스냅샷의_일상_기록_수치와_관찰_크기는_소수_둘째_자리여야_한다():
    raw = fake_catalog_json()
    params = {tool["name"]: tool["params"] for tool in raw["tools"]}

    assert params[DAILY]["rcdNvl"]["scale"] == 2
    assert params[CYCLE]["obsrvSz"]["scale"] == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4.256, 4.26), (4.255, 4.26), (4.254, 4.25), (0.005, 0.01), (4.2, 4.2), (4, 4)],
)
def test_일상_기록_수치는_소수_둘째_자리로_반올림해야_한다(value, expected):
    assert daily_card(value)["rcdNvl"] == expected


def test_돌려받은_카드의_수치도_소수_둘째_자리로_반올림해야_한다():
    card = entry(DAILY)
    prior = {"dailyRcdIdctCd": "HLTC0014", "rcdDt": "2026-11-11T09:00:00", "rcdNvl": 3.14159}

    values = catalog.card_input(card, {}, NOW, {}, prior)

    assert values["rcdNvl"] == 3.14


def test_관찰_크기는_소수_둘째_자리로_반올림해야_한다():
    card = entry(CYCLE)

    values = catalog.card_input(card, {}, NOW, {}, {"obsrvSz": 1.2345})

    assert values["obsrvSz"] == 1.23


def test_Java_도구_목록의_scale을_따라야_한다():
    raw = fake_catalog_json()
    next(tool for tool in raw["tools"] if tool["name"] == DAILY)["params"]["rcdNvl"]["scale"] = 3

    assert daily_card(4.2567, raw)["rcdNvl"] == 4.257


def test_scale이_없는_decimal_칸은_반올림하지_않아야_한다():
    raw = fake_catalog_json()
    del next(tool for tool in raw["tools"] if tool["name"] == DAILY)["params"]["rcdNvl"]["scale"]

    assert daily_card(4.2567, raw)["rcdNvl"] == 4.2567


def test_카드_params에는_scale을_싣지_않아야_한다():
    params = catalog.card_params(entry(DAILY))

    assert "scale" not in params["rcdNvl"]

"""tool_eval --off 지름길 끄기(정규식 지름길 줄이기 ①). 외부 API 안 부름"""

import argparse

import pytest

from app.chat import rules
from app.chat.clients import AnthropicToolAgent
from scripts.tool_eval import off_line, off_names, off_tag, shortcuts_off


def test_off_names_accepts_known_names_in_order():
    assert off_names("chain") == ("chain",)
    assert off_names(" chain , chain ") == ("chain",)


@pytest.mark.parametrize("value", ["nope", "hint", "chain,nope", "", ","])
def test_off_names_rejects_unknown_or_empty(value):
    with pytest.raises(argparse.ArgumentTypeError):
        off_names(value)


def test_off_line_and_tag():
    assert off_line(("chain",)) == "끈 지름길: chain"
    assert off_line(()) == "끈 지름길: 없음"
    assert off_tag(("chain",)) == "-off-chain"
    assert off_tag(()) == ""


def test_chain_off_only_inside_block():
    more, after = rules.chains_more, rules.chains_after_move
    with shortcuts_off(("chain",)):
        assert rules.chains_more("일정 넣고 그리고 체중도 기록해 줘") is False
        assert rules.chains_after_move("일정 화면 열고 내일 일정도 알려 줘") is False
        assert AnthropicToolAgent.decide is not None
    assert rules.chains_more is more
    assert rules.chains_after_move is after


def test_restores_even_on_error():
    more = rules.chains_more
    with pytest.raises(RuntimeError), shortcuts_off(("chain",)):
        raise RuntimeError
    assert rules.chains_more is more

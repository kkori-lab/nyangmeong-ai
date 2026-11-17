"""추가-1 (2026-11-13) : AI 매니저 자신의 동작 방식·내부 구조 질문은 범위 밖으로 막는다"""

from app.chat import tools
from app.chat.clients import tool_system


def test_도구_system은_내부_동작_질문을_범위_밖으로_decline하게_해야_한다():
    system = tool_system()
    assert "동작 방식·내부 구조" in system
    assert "'너는 어떤 방식으로 동작해?'" in system
    assert "설명하지 않고 decline(unclear false)" in system


def test_decline_설명에도_내부_동작_질문이_unclear_false로_있어야_한다():
    decline = next(d for d in tools.tool_definitions() if d["name"] == tools.DECLINE)
    assert "동작 방식·내부 구조" in decline["description"]
    assert "질문도 unclear false" in decline["description"]

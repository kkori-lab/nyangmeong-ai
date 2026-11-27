"""에이전트 루프 서명 토큰 (docs/design/agent.md 4절, 에이전트 ③ 2026-11-26)
- Python은 상태가 없으므로 카드로 멈춘 루프를 React가 들고 있다가 agent-continue로 돌려준다
- 모양 : base64url(JSON 본문) + "." + base64url(HMAC-SHA256(본문)). 암호화는 하지 않음(9절 1번)
- 키 : AGENT_STATE_KEY, 비면 프로세스마다 무작위 키(key_of, 2026-11-27 결정)
  Python 혼자 만들고 검사하므로 다른 서버와 나눌 필요가 없다
  재시작하면 발급된 토큰만 무효, 서버 여러 대면 env에 같은 값"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass, field

# 형식 버전 : 담는 칸을 바꾸면 올림(옛 토큰은 400)
VERSION = 1
# 발급 뒤 만료(초)
TTL_SEC = 600
# 토큰 크기 상한 : 넘으면 pending 없이 지금 흐름으로 끝냄
MAX_BYTES = 48 * 1024
# AGENT_STATE_KEY가 빌 때 쓰는 키 : 프로세스가 뜰 때 한 번 만든다
_PROCESS_KEY = secrets.token_urlsafe(32)


def key_of(configured: str) -> str:
    """서명 키 : env 값이 있으면 그 값, 없으면 프로세스 무작위 키"""
    return configured or _PROCESS_KEY


class AgentStateError(Exception):
    """토큰 검사 실패 : reason은 로그용(서명·만료·방·버전·모양)"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class AgentState:
    """[멈춘 루프]
    - room : 대화방 번호, q : 이 턴 사용자 메시지 msgSeq, said : 그 글
    - left : 남은 도구 호출 수(한 턴 TOOL_LIMIT에서 이어 가기 포함)
    - seen : 번호 칸에 쓸 수 있는 이 턴 READ·실행 결과 번호(칸 이름 -> 번호 목록)
    - notes : 이 턴 진행 기록(READ 결과 글·실행 결과 줄), 이어 갈 때 LLM에 줌
    - cards : 이 멈춤에서 낸 카드의 {tool, input}
    - done : 이 턴에서 실행이 끝난 카드의 {tool, input} (같은 쓰기 반복 막기)
    - fixed : 칸 오류를 이미 한 번 고쳤음(두 번째 실패는 고치지 않음)"""

    room: int
    q: int
    said: str
    left: int
    seen: dict[str, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    done: list[dict] = field(default_factory=list)
    fixed: bool = False
    exp: int = 0
    v: int = VERSION


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str, key: str) -> str:
    digest = hmac.new(key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return _b64(digest)


def sign(state: AgentState, key: str, now: float) -> str | None:
    """토큰 만들기 : 키가 없거나 MAX_BYTES를 넘으면 None"""
    if not key:
        return None
    payload = {**asdict(state), "exp": int(now) + TTL_SEC, "v": VERSION}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = _b64(raw)
    token = f"{body}.{_mac(body, key)}"
    if len(token) > MAX_BYTES:
        return None
    return token


def verify(token: str, key: str, room: int, now: float) -> AgentState:
    """토큰 검사 : 서명 틀림·만료·다른 방·버전 다름·모양 틀림이면 AgentStateError"""
    if not key:
        raise AgentStateError("no_key")
    body, dot, mac = token.partition(".")
    if not dot or not body or not mac:
        raise AgentStateError("shape")
    if not hmac.compare_digest(_mac(body, key), mac):
        raise AgentStateError("signature")
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        raise AgentStateError("shape") from None
    if not isinstance(payload, dict) or payload.get("v") != VERSION:
        raise AgentStateError("version")
    try:
        state = AgentState(**payload)
    except TypeError:
        raise AgentStateError("shape") from None
    if state.exp <= now:
        raise AgentStateError("expired")
    if state.room != room:
        raise AgentStateError("room")
    return state

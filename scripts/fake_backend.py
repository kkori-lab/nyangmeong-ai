"""사람 확인용 가짜 Java. 인증 확인과 대화 내부 API를 흉내 낸다 (실제 Java가 나오기 전까지)

띄우기: uv run uvicorn scripts.fake_backend:app --port 8081
.env.local: BACKEND_BASE_URL=http://localhost:8081

쿠키 access_token 값별 결과
- member-<번호>: 200, 그 회원 번호
- expired: 401 TOKEN_EXPIRED
- inactive: 403 MEMBER_INACTIVE + 쿠키 삭제 Set-Cookie
- 그 밖·없음: 401 UNAUTHORIZED

대화 내부 API(/internal/ai/conversations)도 같은 쿠키로 회원 결정, 메모리 저장이라 끄면 소멸
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import Body, Cookie, FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="가짜 Java (인증 확인·대화 저장)")

ROLE_USER = "AIMC0024"
rooms: dict[int, dict[str, Any]] = {}
_seq = {"room": 0, "msg": 0}


def _error(http_code: int, code: str, message: str) -> JSONResponse:
    body = {"status": "error", "httpCode": http_code, "code": code, "message": message}
    return JSONResponse(status_code=http_code, content=body)


def _ok(data: Any = None, http_code: int = 200) -> JSONResponse:
    body = {"status": "success", "httpCode": http_code, "message": "ok"}
    if data is not None:
        body["data"] = data
    return JSONResponse(status_code=http_code, content=body)


def _not_found() -> JSONResponse:
    return _error(404, "NOT_FOUND", "요청한 정보를 찾을 수 없습니다.")


def _summary(room_sn: int) -> dict[str, Any]:
    r = rooms[room_sn]
    return {k: r[k] for k in ("aiCnvrsRoomSn", "petSn", "cnvrsTtl", "regDt")}


Token = Annotated[str | None, Cookie(alias="access_token")]


def _member(token: str | None) -> int | JSONResponse:
    """쿠키로 회원 번호 결정, 통과하지 못하면 Java 인증 오류 응답"""
    token = token or ""
    if token.startswith("member-") and token[7:].isdigit():
        return int(token[7:])
    if token == "expired":
        return _error(401, "TOKEN_EXPIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요.")
    if token == "inactive":
        res = _error(403, "MEMBER_INACTIVE", "이용할 수 없는 계정입니다.")
        res.delete_cookie("access_token")
        res.delete_cookie("refresh_token")
        return res
    return _error(401, "UNAUTHORIZED", "로그인이 필요합니다.")


@app.get("/internal/auth/check")
def auth_check(token: Token = None) -> JSONResponse:
    mbr_sn = _member(token)
    if isinstance(mbr_sn, JSONResponse):
        return mbr_sn
    return _ok({"mbrSn": mbr_sn, "mbrAuthrtCd": "U"})


@app.post("/internal/ai/conversations")
def create_conversation(
    body: Annotated[dict[str, Any], Body()], token: Token = None
) -> JSONResponse:
    mbr_sn = _member(token)
    if isinstance(mbr_sn, JSONResponse):
        return mbr_sn
    _seq["room"] += 1
    _seq["msg"] += 1
    room_sn = _seq["room"]
    now = datetime.now().replace(microsecond=0).isoformat()
    rooms[room_sn] = {
        "aiCnvrsRoomSn": room_sn,
        "mbrSn": mbr_sn,
        "petSn": body.get("petSn"),
        "cnvrsTtl": body["cnvrsTtl"],
        "regDt": now,
        "messages": [
            {
                "aiCnvrsMsgSn": _seq["msg"],
                "roleCd": ROLE_USER,
                "cnvrsCn": body["cnvrsCn"],
                "msgSeq": 1,
                "regDt": now,
            }
        ],
    }
    return _ok(_summary(room_sn), 201)


@app.get("/internal/ai/conversations")
def list_conversations(
    token: Token = None, pet_sn: Annotated[int | None, Query(alias="petSn")] = None
) -> JSONResponse:
    mbr_sn = _member(token)
    if isinstance(mbr_sn, JSONResponse):
        return mbr_sn
    mine = [
        sn
        for sn, r in rooms.items()
        if r["mbrSn"] == mbr_sn and (pet_sn is None or r["petSn"] == pet_sn)
    ]
    mine.sort(key=lambda sn: (rooms[sn]["regDt"], sn), reverse=True)
    return _ok([_summary(sn) for sn in mine])


@app.get("/internal/ai/conversations/{room_sn}")
def get_conversation(room_sn: int, token: Token = None) -> JSONResponse:
    mbr_sn = _member(token)
    if isinstance(mbr_sn, JSONResponse):
        return mbr_sn
    room = rooms.get(room_sn)
    if room is None or room["mbrSn"] != mbr_sn:
        return _not_found()
    return _ok(_summary(room_sn) | {"messages": room["messages"]})


@app.delete("/internal/ai/conversations/{room_sn}")
def delete_conversation(room_sn: int, token: Token = None) -> JSONResponse:
    mbr_sn = _member(token)
    if isinstance(mbr_sn, JSONResponse):
        return mbr_sn
    room = rooms.get(room_sn)
    if room is None or room["mbrSn"] != mbr_sn:
        return _not_found()
    del rooms[room_sn]
    return _ok()

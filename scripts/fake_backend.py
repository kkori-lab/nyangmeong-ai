"""사람 확인용 가짜 Java. /internal/auth/check만 흉내 낸다 (실제 Java가 나오기 전까지)

띄우기: uv run uvicorn scripts.fake_backend:app --port 8081
.env.local: BACKEND_BASE_URL=http://localhost:8081

쿠키 access_token 값으로 결과를 고른다
- member-<번호>: 200, 그 회원 번호
- expired: 401 TOKEN_EXPIRED
- inactive: 403 MEMBER_INACTIVE + 쿠키 삭제 Set-Cookie
- 그 밖·없음: 401 UNAUTHORIZED
"""

from typing import Annotated

from fastapi import Cookie, FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="가짜 Java (인증 확인)")


def _error(http_code: int, code: str, message: str) -> JSONResponse:
    body = {"status": "error", "httpCode": http_code, "code": code, "message": message}
    return JSONResponse(status_code=http_code, content=body)


@app.get("/internal/auth/check")
def auth_check(access_token: Annotated[str | None, Cookie()] = None) -> JSONResponse:
    token = access_token or ""
    if token.startswith("member-") and token[7:].isdigit():
        data = {"mbrSn": int(token[7:]), "mbrAuthrtCd": "U"}
        return JSONResponse({"status": "success", "httpCode": 200, "data": data})
    if token == "expired":
        return _error(401, "TOKEN_EXPIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요.")
    if token == "inactive":
        res = _error(403, "MEMBER_INACTIVE", "이용할 수 없는 계정입니다.")
        res.delete_cookie("access_token")
        res.delete_cookie("refresh_token")
        return res
    return _error(401, "UNAUTHORIZED", "로그인이 필요합니다.")

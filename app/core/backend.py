from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx2
from fastapi import Request

# Java 내부 API 제한 시간(초)
TIMEOUT_SEC = 3.0


def create_backend_client() -> httpx2.AsyncClient:
    # 요청끼리 공유하므로 Java의 Set-Cookie를 저장하지 않는다 : 다른 회원 요청에 섞임 방지
    jar = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
    return httpx2.AsyncClient(timeout=TIMEOUT_SEC, cookies=jar)


def get_backend_client(request: Request) -> httpx2.AsyncClient:
    return request.app.state.backend_client

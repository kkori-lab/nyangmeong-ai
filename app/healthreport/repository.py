from datetime import date
from typing import Annotated, Protocol

import httpx2
from fastapi import Depends, Request
from pydantic import ValidationError

from app.core.auth import REQUESTED_WITH
from app.core.backend import call_backend, external_error, get_backend_client
from app.core.config import Settings, get_settings
from app.healthreport.schemas import HealthReportSaveRequest, HealthReportSource

# Java 건강분석 리포트 내부 API (LJS 백엔드, 아직 없음 : 계약은 docs/api/internal.md)
PETS_PATH = "/internal/ai/pets"
REQUESTED_WITH_HEADER = "X-Requested-With"


class HealthReportRepository(Protocol):
    async def get_source(self, pet_sn: int, base_ymd: date) -> HealthReportSource: ...

    async def save(self, pet_sn: int, request: HealthReportSaveRequest) -> None: ...


class JavaHealthReportRepository:
    # 회원·반려동물 접근 판정은 Java(브라우저 Cookie) : 4xx 그대로 전달,
    # 연결 실패·5xx·응답 모양 불일치는 502
    def __init__(self, client: httpx2.AsyncClient, settings: Settings, cookie: str | None) -> None:
        self._client = client
        self._settings = settings
        self._headers = {REQUESTED_WITH_HEADER: REQUESTED_WITH}
        if cookie:
            self._headers["Cookie"] = cookie

    async def get_source(self, pet_sn: int, base_ymd: date) -> HealthReportSource:
        # FN-MAN-006 : 분석 입력 + 저장된 최근 리포트 + 새로고침·자동 재생성 가능 여부
        data = await call_backend(
            self._client,
            self._settings,
            "GET",
            f"{PETS_PATH}/{pet_sn}/health-report-input",
            headers=self._headers,
            params={"baseYmd": base_ymd.isoformat()},
        )
        try:
            return HealthReportSource.model_validate(data)
        except ValidationError:
            raise external_error() from None

    async def save(self, pet_sn: int, request: HealthReportSaveRequest) -> None:
        await call_backend(
            self._client,
            self._settings,
            "PUT",
            f"{PETS_PATH}/{pet_sn}/health-report",
            headers=self._headers,
            json=request.model_dump(mode="json", by_alias=True),
        )


def get_health_report_repository(
    request: Request,
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthReportRepository:
    return JavaHealthReportRepository(client, settings, request.headers.get("cookie"))

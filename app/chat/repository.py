from dataclasses import dataclass
from typing import Annotated, Protocol

import httpx2
from fastapi import Depends, Request
from pydantic import BaseModel, Field, ValidationError

from app.chat.schemas import ConversationDetail, ConversationMessage, ConversationSummary
from app.core.auth import REQUESTED_WITH
from app.core.backend import call_backend, external_error, get_backend_client
from app.core.config import Settings, get_settings

# Java 대화 내부 API (2026-10-26 결정 : 저장·암호화·본인 대화 판정은 Java)
CONVERSATIONS_PATH = "/internal/ai/conversations"
# Java 등록 맥락 내부 API (SCR-AIM-012 반려동물 결정·같은 이름 케어 항목 안내)
REGISTER_CONTEXT_PATH = "/internal/ai/register-context"
REQUESTED_WITH_HEADER = "X-Requested-With"


class ConversationRepository(Protocol):
    async def create_room(
        self, pet_sn: int | None, title: str, first_cn: str
    ) -> ConversationSummary: ...

    async def list_rooms(self, pet_sn: int | None) -> list[ConversationSummary]: ...

    async def get_room(self, room_sn: int) -> ConversationDetail: ...

    async def delete_room(self, room_sn: int) -> None: ...

    async def update_title(self, room_sn: int, title: str) -> ConversationSummary: ...

    async def add_message(
        self, room_sn: int, role_cd: str, cn: str, cmptn_yn: bool = True
    ) -> ConversationMessage: ...


class JavaConversationRepository:
    # 회원 판정은 Java(브라우저 Cookie). 인증 오류·404는 Java 응답 그대로 전달
    def __init__(self, client: httpx2.AsyncClient, settings: Settings, cookie: str | None) -> None:
        self._client = client
        self._settings = settings
        # Java RequestedWithFilter가 /internal/**의 POST·DELETE에도 적용
        self._headers = {REQUESTED_WITH_HEADER: REQUESTED_WITH}
        if cookie:
            self._headers["Cookie"] = cookie

    async def create_room(
        self, pet_sn: int | None, title: str, first_cn: str
    ) -> ConversationSummary:
        body = {"petSn": pet_sn, "cnvrsTtl": title, "cnvrsCn": first_cn}
        data = await self._call("POST", CONVERSATIONS_PATH, json=body)
        return _parse(ConversationSummary, data)

    async def list_rooms(self, pet_sn: int | None) -> list[ConversationSummary]:
        params = {} if pet_sn is None else {"petSn": pet_sn}
        data = await self._call("GET", CONVERSATIONS_PATH, params=params)
        if not isinstance(data, list):
            raise external_error()
        return [_parse(ConversationSummary, item) for item in data]

    async def get_room(self, room_sn: int) -> ConversationDetail:
        data = await self._call("GET", f"{CONVERSATIONS_PATH}/{room_sn}")
        return _parse(ConversationDetail, data)

    async def delete_room(self, room_sn: int) -> None:
        await self._call("DELETE", f"{CONVERSATIONS_PATH}/{room_sn}")

    async def update_title(self, room_sn: int, title: str) -> ConversationSummary:
        # 추가 요청(SCR-AIM-011) : 첫 답변 요약 제목, 암호화는 Java
        body = {"cnvrsTtl": title}
        data = await self._call("PATCH", f"{CONVERSATIONS_PATH}/{room_sn}", json=body)
        return _parse(ConversationSummary, data)

    async def add_message(
        self, room_sn: int, role_cd: str, cn: str, cmptn_yn: bool = True
    ) -> ConversationMessage:
        # msgSeq는 Java 채번. cmptnYn은 Java 기본값이 true라 미완료 답변(FN-AIM-002-07)만 전송
        body = {"roleCd": role_cd, "cnvrsCn": cn}
        if not cmptn_yn:
            body["cmptnYn"] = False
        data = await self._call("POST", f"{CONVERSATIONS_PATH}/{room_sn}/messages", json=body)
        return _parse(ConversationMessage, data)

    async def _call(self, method: str, path: str, **kwargs):
        return await call_backend(
            self._client, self._settings, method, path, headers=self._headers, **kwargs
        )


def _parse[T: BaseModel](model: type[T], data) -> T:
    # Java 응답 모양 불일치 시 502 : 받은 값을 React에 그대로 넘기지 않음
    try:
        return model.model_validate(data)
    except ValidationError:
        raise external_error() from None


def get_conversation_repository(
    request: Request,
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationRepository:
    return JavaConversationRepository(client, settings, request.headers.get("cookie"))


@dataclass(frozen=True)
class AiSettings:
    # SYS_STNG_AI_TKN_UPLMT_CNT : 답변 최대 생성 토큰(FN-AIM-002-02)
    max_tokens: int = 4500
    # SYS_STNG_AI_CNVRS_TURN_CNT : 컨텍스트 턴 수(FN-AIM-011-15)
    context_turns: int = 6


def get_ai_settings() -> AiSettings:
    # 가짜 : 명세 기본값, Java 설정값 조회 내부 API가 생기면 교체
    return AiSettings()


@dataclass(frozen=True)
class PetInfo:
    pet_sn: int
    pet_nm: str
    # FN-AIM-012-08 : 이 반려동물의 케어 항목 이름
    care_artcl_nms: tuple[str, ...] = ()


class RegisterContextRepository(Protocol):
    # 쿠키 회원이 양육하는 반려동물(SCR-AIM-012 반려동물 결정·같은 이름 케어 항목 안내)
    async def get_pets(self) -> list[PetInfo]: ...


class RegisterContextItem(BaseModel):
    # Java GET /internal/ai/register-context 응답 원소(백엔드 #54)
    pet_sn: int = Field(alias="petSn")
    pet_nm: str = Field(alias="petNm")
    care_artcl_nms: list[str] = Field(default_factory=list, alias="careArtclNms")


class JavaRegisterContextRepository:
    # 회원 판정은 Java(브라우저 Cookie). careArtclNms는 케어 항목 API가 생길 때까지 빈 배열
    def __init__(self, client: httpx2.AsyncClient, settings: Settings, cookie: str | None) -> None:
        self._client = client
        self._settings = settings
        self._headers = {REQUESTED_WITH_HEADER: REQUESTED_WITH}
        if cookie:
            self._headers["Cookie"] = cookie

    async def get_pets(self) -> list[PetInfo]:
        data = await call_backend(
            self._client, self._settings, "GET", REGISTER_CONTEXT_PATH, headers=self._headers
        )
        if not isinstance(data, list):
            raise external_error()
        items = [_parse(RegisterContextItem, item) for item in data]
        return [PetInfo(i.pet_sn, i.pet_nm, tuple(i.care_artcl_nms)) for i in items]


def get_register_context_repository(
    request: Request,
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterContextRepository:
    return JavaRegisterContextRepository(client, settings, request.headers.get("cookie"))

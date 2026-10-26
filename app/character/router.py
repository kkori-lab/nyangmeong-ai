from typing import Annotated

from fastapi import APIRouter, Depends, Form, Response, UploadFile

from app.character import service
from app.character.clients import CharacterClient, CharacterRequest, get_character_client
from app.character.schemas import PetSeCd

router = APIRouter(prefix="/internal/v1/character")


@router.post("/generate")
async def generate_character(
    photo: UploadFile,
    pet_se_cd: Annotated[PetSeCd, Form(alias="petSeCd")],
    client: Annotated[CharacterClient, Depends(get_character_client)],
    vrty_nm: Annotated[str | None, Form(alias="vrtyNm")] = None,
    colr_nm: Annotated[str | None, Form(alias="colrNm")] = None,
    chrc_cn: Annotated[str | None, Form(alias="chrcCn")] = None,
) -> Response:
    request = CharacterRequest(await photo.read(), pet_se_cd, vrty_nm, colr_nm, chrc_cn)
    image = await service.generate_character(client, request)
    # 성공 응답 = ApiResponse 껍데기 없이 PNG 본문
    return Response(content=image, media_type="image/png")

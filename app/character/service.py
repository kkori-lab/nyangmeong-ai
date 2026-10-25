from app.character.clients import CharacterApiError, CharacterClient, CharacterRequest
from app.character.rules import matches_spec
from app.core.image import detect_image_type
from app.core.response import AppError


async def generate_character(client: CharacterClient, request: CharacterRequest) -> bytes:
    # FN-MYP-010-08 : 형식·용량 검증은 Java 담당, 여기서는 이미지 판독 여부만 확인
    if detect_image_type(request.photo) is None:
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "이미지 파일로 읽을 수 없습니다.")
    try:
        image = await client.generate(request)
    except CharacterApiError:
        raise AppError("CHARACTER_API_ERROR", 502, "캐릭터 생성 중 오류가 발생했습니다.") from None
    # FN-MYP-010-17·18 : 규격 밖 결과는 내보내지 않는다
    if not matches_spec(image):
        raise AppError("CHARACTER_SPEC_MISMATCH", 502, "캐릭터 규격을 맞추지 못했습니다.")
    return image

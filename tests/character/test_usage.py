"""FN-ADM-112-01·02 : 캐릭터 OpenAI 호출마다 SYSC0017 통지"""

import asyncio
import base64
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.character import service
from app.character.clients import (
    CharacterApiError,
    CharacterRequest,
    OpenAICharacterClient,
    get_character_client,
)
from app.character.repository import CharacterJob
from app.core.config import Settings
from app.core.usage import CallResult, ExternalApi, ExternalCall
from tests.character.fakes import SavedJob
from tests.character.test_bake import BY_HINT, LAYOUT, ImageRepo, item_png, sheet
from tests.character.test_engine import _photo, _sheet

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/images/edits")
IMAGE_USAGE = SimpleNamespace(input_tokens=300, output_tokens=50)
CHAT_USAGE = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
NO_DATA = object()


class Recorder:
    def __init__(self) -> None:
        self.calls: list[ExternalCall] = []

    def record(self, call: ExternalCall) -> None:
        self.calls.append(call)


class UsageOpenAI:
    """images.edit·chat 가짜 : 답에 usage를 실음, 예외·그림 없는 응답도 낼 수 있음"""

    def __init__(self, image: bytes | Exception | object = b"", chat: str | Exception = "{}"):
        self.image = image
        self.chat_answer = chat
        self.images = SimpleNamespace(edit=self._edit)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _edit(self, **_):
        if isinstance(self.image, Exception):
            raise self.image
        if self.image is NO_DATA:
            return SimpleNamespace(data=[], usage=IMAGE_USAGE)
        data = SimpleNamespace(b64_json=base64.b64encode(self.image).decode())
        return SimpleNamespace(data=[data], usage=IMAGE_USAGE)

    def _create(self, **_):
        if isinstance(self.chat_answer, Exception):
            raise self.chat_answer
        message = SimpleNamespace(content=self.chat_answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=CHAT_USAGE)


def client_of(fake: UsageOpenAI) -> tuple[OpenAICharacterClient, Recorder]:
    recorder = Recorder()
    return OpenAICharacterClient(fake, "image-model", "vision-model", recorder), recorder


def results(recorder: Recorder) -> list[tuple]:
    return [
        (c.api, c.result, c.http_status, c.input_tokens, c.output_tokens, c.fail_reason)
        for c in recorder.calls
    ]


CHAT_OK = (ExternalApi.CHARACTER, CallResult.SUCCESS, 200, 100, 20, None)
IMAGE_OK = (ExternalApi.CHARACTER, CallResult.SUCCESS, 200, 300, 50, None)
INVALID_IMAGE = (ExternalApi.CHARACTER, CallResult.FAIL, None, 300, 50, "invalid_output")


def status_error(status: int) -> openai.APIStatusError:
    return openai.APIStatusError(
        "error", response=httpx2.Response(status, request=REQUEST), body=None
    )


def generate(client: OpenAICharacterClient):
    return asyncio.run(client.generate(CharacterRequest(_photo(), "PETC0002")))


def test_캐릭터_생성은_눈_판별과_시트_생성_두_건을_SYSC0017로_통지한다():
    client, recorder = client_of(UsageOpenAI(_sheet()))
    generate(client)
    assert results(recorder) == [CHAT_OK, IMAGE_OK]
    assert all(c.rspns_ms >= 0 for c in recorder.calls)


def test_눈_판별이_실패해도_생성은_이어_가고_실패_한_건을_통지한다():
    client, recorder = client_of(UsageOpenAI(_sheet(), chat=status_error(500)))
    generate(client)
    assert results(recorder) == [
        (ExternalApi.CHARACTER, CallResult.FAIL, 500, None, None, "api_error 500"),
        IMAGE_OK,
    ]


def test_시트_생성_시간초과는_SYSC0023으로_통지한다():
    client, recorder = client_of(UsageOpenAI(openai.APITimeoutError(request=REQUEST)))
    with pytest.raises(CharacterApiError):
        generate(client)
    assert results(recorder) == [
        CHAT_OK,
        (ExternalApi.CHARACTER, CallResult.TIMEOUT, None, None, None, "timeout"),
    ]


def test_그림_없는_응답은_실패로_통지한다():
    client, recorder = client_of(UsageOpenAI(NO_DATA))
    with pytest.raises(CharacterApiError):
        generate(client)
    assert results(recorder) == [CHAT_OK, INVALID_IMAGE]


def test_굽기_상태_오류는_실패와_상태_코드로_통지한다():
    client, recorder = client_of(UsageOpenAI(status_error(429)))
    with pytest.raises(CharacterApiError):
        asyncio.run(client.bake(sheet(), "PETC0001", BY_HINT))
    assert results(recorder) == [
        (ExternalApi.CHARACTER, CallResult.FAIL, 429, None, None, "api_error 429")
    ]


def test_굽기_지시_빈_답은_invalid_output으로_통지한다():
    client, recorder = client_of(UsageOpenAI(chat=""))
    with pytest.raises(CharacterApiError):
        asyncio.run(client.describe_item(item_png(), BY_HINT.regn_cd, "스웨터"))
    assert results(recorder) == [
        (ExternalApi.CHARACTER, CallResult.FAIL, None, 100, 20, "invalid_output")
    ]


def test_굽기_지시_성공은_토큰과_함께_통지한다():
    client, recorder = client_of(UsageOpenAI(chat="a green knitted dog sweater"))
    asyncio.run(client.describe_item(item_png(), BY_HINT.regn_cd, "스웨터"))
    assert results(recorder) == [CHAT_OK]


def test_픽셀_아이템_그림은_한_건_통지한다():
    client, recorder = client_of(UsageOpenAI(sheet(body=True)))
    asyncio.run(client.draw_item(item_png(), BY_HINT.regn_cd, "스웨터"))
    assert results(recorder) == [IMAGE_OK]


def test_굽기_큐는_작업을_넣은_요청의_통지기로_기록한다():
    # 요청 A·B가 같은 공유 큐에 넣고, 큐 비우기는 한 번만 돈다
    repo = ImageRepo()
    for sn in (1, 2):
        repo.jobs[sn] = SavedJob(CharacterJob(sn, "PETC0001"), 3, sheet=sheet(), layout=LAYOUT)
    client_a, recorder_a = client_of(UsageOpenAI(sheet(body=True)))
    client_b, recorder_b = client_of(UsageOpenAI(sheet(body=True)))
    queue = service.BakeQueue()
    queue.add(service.BakeTask(client_a, repo, 1, BY_HINT.item_sn, BY_HINT, sheet(), "PETC0001"))
    queue.add(service.BakeTask(client_b, repo, 2, BY_HINT.item_sn, BY_HINT, sheet(), "PETC0001"))
    asyncio.run(queue.drain())
    assert results(recorder_a) == [IMAGE_OK]
    assert results(recorder_b) == [IMAGE_OK]


def test_의존성은_통지기를_클라이언트에_넣는다():
    recorder = Recorder()
    settings = Settings(_env_file=None, openai_api_key="test-key")
    client = get_character_client(settings, recorder)
    assert isinstance(client, OpenAICharacterClient)
    assert client._usage is recorder

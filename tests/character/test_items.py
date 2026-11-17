import asyncio
import base64
import io
from types import SimpleNamespace

import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.character import engine, service
from app.character.clients import CharacterApiError, OpenAICharacterClient, get_character_client
from app.character.repository import (
    CharacterJob,
    JavaCharacterJobRepository,
    get_character_job_repository,
)
from app.character.rules import matches_spec
from app.character.service import BakeQueue, BakeTask, get_bake_queue
from app.core.backend import BackendError, get_backend_client
from app.core.config import Settings, get_settings
from app.core.response import AppError
from app.main import create_app
from tests.character.fakes import FakeCharacterJobRepository, SavedJob, fake_item
from tests.character.test_bake import BLUE, LAYOUT, count, rgba, sheet

ADMIN = {"X-Requested-With": "XMLHttpRequest", "Cookie": "access_token=admin"}
MEMBER = {"X-Requested-With": "XMLHttpRequest", "Cookie": "access_token=member"}
SWEATER = 108
HINT = "a green knitted dog sweater"


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    cookie = request.headers.get("cookie", "")
    if "access_token=admin" in cookie:
        return httpx2.Response(200, json={"data": {"mbrSn": 1, "mbrAuthrtCd": "USRC0005"}})
    if "access_token=" in cookie:
        return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "USRC0001"}})
    return httpx2.Response(401, json={"code": "UNAUTHORIZED"})


def item_png(color: tuple[int, int, int, int] = (200, 30, 30, 255)) -> bytes:
    image = Image.new("RGBA", (64, 64))
    image.paste(color, (16, 16, 48, 48))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class VisionOpenAI:
    """비전 호출 기록, 정해 둔 답변 반환"""

    def __init__(self, answer: str | Exception = HINT) -> None:
        self.answer = answer
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        message = SimpleNamespace(content=self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class BakeClient:
    """굽기 기록, 의상 칸을 칠한 착용 시트 반환"""

    def __init__(self) -> None:
        self.calls: list[engine.BakeItem] = []
        self.error = False

    async def bake(self, bare: bytes, pet_se_cd, item: engine.BakeItem) -> bytes:
        self.calls.append(item)
        if self.error:
            raise CharacterApiError
        return sheet(body=True)


def character(sn: int) -> SavedJob:
    return SavedJob(CharacterJob(sn, "PETC0001"), 3, sheet=sheet(), layout=LAYOUT)


@pytest.fixture
def repo() -> FakeCharacterJobRepository:
    fake = FakeCharacterJobRepository()
    fake.jobs = {sn: character(sn) for sn in (1, 2, 3)}
    return fake


def make_client(monkeypatch, repo, generator) -> TestClient:
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    queue = BakeQueue()
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_job_repository] = lambda: repo
    app.dependency_overrides[get_character_client] = lambda: generator
    app.dependency_overrides[get_bake_queue] = lambda: queue
    return TestClient(app)


# FN-ADM-070-02 : 이미지로 굽기 지시 초안
def post_hint(client: TestClient, headers=ADMIN, regn_cd="MYPC0004", name="i.png", **kwargs):
    form = {"regnCd": regn_cd, "itemNm": kwargs.pop("item_nm", "초록 스웨터")}
    files = {"image": (name, kwargs.pop("image", item_png()), "image/png")}
    return client.post("/ai/items/bake-hints", data=form, files=files, headers=headers)


def vision_client(monkeypatch, repo, answer: str | Exception = HINT):
    fake = VisionOpenAI(answer)
    generator = OpenAICharacterClient(fake, "image-model", "vision-model")
    return make_client(monkeypatch, repo, generator), fake


def test_bake_hints_그림을_비전_모델에_보내고_굽기_지시를_돌려준다(monkeypatch, repo) -> None:
    client, fake = vision_client(monkeypatch, repo)
    res = post_hint(client)
    assert res.status_code == 200
    assert res.json()["data"] == {"bakeHint": HINT}
    call = fake.calls[0]
    assert call["model"] == "vision-model"
    content = call["messages"][0]["content"]
    assert "초록 스웨터" in content[0]["text"]
    assert "on the torso" in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_bake_hints_답변_첫_줄만_따옴표와_마침표를_빼고_쓴다(monkeypatch, repo) -> None:
    client, _ = vision_client(monkeypatch, repo, '"a red ribbon headband with a big bow."\nmore')
    assert post_hint(client).json()["data"]["bakeHint"] == "a red ribbon headband with a big bow"


@pytest.mark.parametrize("answer", ["", "   \n", "x" * 151, RuntimeError("down")])
def test_bake_hints_빈_답_긴_답_비전_실패는_502(monkeypatch, repo, answer) -> None:
    client, _ = vision_client(monkeypatch, repo, answer)
    res = post_hint(client)
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_bake_hints_생성기가_없으면_502(monkeypatch, repo) -> None:
    res = post_hint(make_client(monkeypatch, repo, None))
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"regn_cd": "MYPC0006"}, "INVALID_REQUEST"),  # 신발은 굽지 않음
        ({"regn_cd": "MYPC9999"}, "INVALID_REQUEST"),
        ({"item_nm": ""}, "INVALID_REQUEST"),
        ({"item_nm": "가" * 51}, "INVALID_REQUEST"),
        ({"image": b"not image"}, "FILE_TYPE_NOT_ALLOWED"),
        ({"name": "i.pdf"}, "FILE_TYPE_NOT_ALLOWED"),
        ({"image": b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024)}, "FILE_SIZE_EXCEEDED"),
    ],
)
def test_bake_hints_입력이_틀리면_400이고_비전을_부르지_않는다(monkeypatch, repo, kwargs, code):
    client, fake = vision_client(monkeypatch, repo)
    res = post_hint(client, **kwargs)
    assert res.status_code == 400
    assert res.json()["code"] == code
    assert fake.calls == []


def test_bake_hints_그림이_없으면_400(monkeypatch, repo) -> None:
    client, _ = vision_client(monkeypatch, repo)
    form = {"regnCd": "MYPC0004", "itemNm": "스웨터"}
    res = client.post("/ai/items/bake-hints", data=form, headers=ADMIN)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_bake_hints_투명_배경은_흰_바탕으로_보낸다() -> None:
    flat = Image.open(io.BytesIO(engine.normalize_item_image(item_png())))
    assert flat.mode == "RGB"
    assert flat.getpixel((0, 0)) == (255, 255, 255)
    assert flat.getpixel((32, 32)) == (200, 30, 30)


# FN-ADM-070-02 : 시험 굽기
def post_trial(client: TestClient, headers=ADMIN, **body):
    payload = {"pixelCharSn": 1, "regnCd": "MYPC0004", "bakeHint": HINT} | body
    return client.post("/ai/items/trial-preview", json=payload, headers=headers)


def test_trial_preview_지시대로_한_번_구워_입힌_512_PNG_저장하지_않는다(monkeypatch, repo) -> None:
    generator = BakeClient()
    res = post_trial(make_client(monkeypatch, repo, generator))
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert matches_spec(res.content)
    assert count(rgba(res.content), BLUE) > 0
    assert [(item.regn_cd, item.bake_hint) for item in generator.calls] == [("MYPC0004", HINT)]
    assert all(not saved.item_sheets and not saved.failed_items for saved in repo.jobs.values())


def test_trial_preview_굽기_실패는_한_번만_시도하고_502(monkeypatch, repo) -> None:
    generator = BakeClient()
    generator.error = True
    res = post_trial(make_client(monkeypatch, repo, generator))
    assert res.status_code == 502
    assert res.json()["code"] == "CHARACTER_API_ERROR"
    assert len(generator.calls) == 1


def test_trial_preview_생성기가_없으면_502(monkeypatch, repo) -> None:
    res = post_trial(make_client(monkeypatch, repo, None))
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_trial_preview_캐릭터가_없으면_Java_404_그대로(monkeypatch, repo) -> None:
    res = post_trial(make_client(monkeypatch, repo, BakeClient()), pixelCharSn=99)
    assert res.status_code == 404
    assert res.json()["code"] == "PIXEL_CHARACTER_NOT_FOUND"


@pytest.mark.parametrize(
    "body",
    [{"regnCd": "MYPC0006"}, {"bakeHint": ""}, {"bakeHint": "x" * 301}, {"pixelCharSn": None}],
)
def test_trial_preview_형식이_틀리면_400(monkeypatch, repo, body) -> None:
    generator = BakeClient()
    res = post_trial(make_client(monkeypatch, repo, generator), **body)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert generator.calls == []


# FN-ADM-070-02 : 새 아이템 전체 굽기
def post_bake(client: TestClient, item_sn: int = SWEATER, headers=ADMIN):
    return client.post(f"/ai/items/{item_sn}/bake", headers=headers)


def test_bake_안_구운_캐릭터를_굽고_다_끝나면_200과_lastYn(monkeypatch, repo) -> None:
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.status_code == 200
    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 3, "failedCnt": 0, "lastYn": True}
    assert [item.item_sn for item in generator.calls] == [SWEATER] * 3
    assert all(SWEATER in saved.item_sheets for saved in repo.jobs.values())


def test_bake_대상이_묶음보다_많으면_나눠_굽고_마지막에_lastYn(monkeypatch, repo) -> None:
    repo.jobs = {sn: character(sn) for sn in range(1, 31)}
    generator = BakeClient()
    client = make_client(monkeypatch, repo, generator)
    results = [post_bake(client).json()["data"] for _ in range(3)]
    assert [(r["bakedCnt"], r["lastYn"]) for r in results] == [(13, False), (13, False), (4, True)]
    assert len(generator.calls) == 30
    assert all(SWEATER in saved.item_sheets for saved in repo.jobs.values())


def test_bake_이미_구운_캐릭터와_맨몸_시트_없는_캐릭터는_빼고_굽는다(monkeypatch, repo) -> None:
    repo.jobs[1].item_sheets[SWEATER] = sheet(body=True)
    repo.jobs[2].failed_items.add(SWEATER)
    repo.jobs[4] = SavedJob(CharacterJob(4, "PETC0001"), 3)
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.json()["data"]["bakedCnt"] == 1
    assert len(generator.calls) == 1
    assert SWEATER in repo.jobs[3].item_sheets


def test_bake_대상이_없으면_0과_lastYn(monkeypatch, repo) -> None:
    generator = BakeClient()
    client = make_client(monkeypatch, repo, generator)
    post_bake(client)
    res = post_bake(client)
    assert res.status_code == 200
    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 0, "failedCnt": 0, "lastYn": True}
    assert len(generator.calls) == 3


def test_bake_굽기_대상_아이템이_아니면_400(monkeypatch, repo) -> None:
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator), item_sn=999)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert generator.calls == []


def test_bake_생성기가_없으면_502(monkeypatch, repo) -> None:
    res = post_bake(make_client(monkeypatch, repo, None))
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_bake_굽기_실패는_실패로_보고하고_센다(monkeypatch, repo) -> None:
    generator = BakeClient()
    generator.error = True
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 0, "failedCnt": 3, "lastYn": True}
    assert all(SWEATER in saved.failed_items for saved in repo.jobs.values())


def _sheets_fail_for(repo, broken: set[int]) -> None:
    original = repo.find_sheets

    async def find_sheets(pixel_char_sn, item_sns):
        if pixel_char_sn in broken:
            raise BackendError(403, b'{"code":"PET_PRIMARY_ONLY"}', "application/json", [])
        return await original(pixel_char_sn, item_sns)

    repo.find_sheets = find_sheets


def test_bake_맨몸_시트를_못_받으면_굽지_않고_남겨_둔다(monkeypatch, repo) -> None:
    _sheets_fail_for(repo, {2})
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 2, "failedCnt": 0, "lastYn": False}
    assert len(generator.calls) == 2
    assert SWEATER not in repo.jobs[2].item_sheets and SWEATER not in repo.jobs[2].failed_items


def test_bake_묶음을_하나도_처리하지_못하면_502(monkeypatch, repo) -> None:
    _sheets_fail_for(repo, {1, 2, 3})
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"
    assert generator.calls == []


def _sheet_files_missing_for(repo, broken: set[int]) -> None:
    """Java sheet-files 404 FILE_NOT_FOUND : DB 행은 있고 디스크에 파일 없음"""
    original = repo.find_sheets

    async def find_sheets(pixel_char_sn, item_sns):
        if pixel_char_sn in broken:
            raise BackendError(404, b'{"code":"FILE_NOT_FOUND"}', "application/json", [])
        return await original(pixel_char_sn, item_sns)

    repo.find_sheets = find_sheets


def test_bake_맨몸_시트_파일이_없으면_굽기_실패로_표시하고_넘어가야_한다(monkeypatch, repo) -> None:
    _sheet_files_missing_for(repo, {2})
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.status_code == 200
    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 2, "failedCnt": 1, "lastYn": True}
    assert len(generator.calls) == 2
    assert SWEATER in repo.jobs[2].failed_items
    assert SWEATER not in repo.jobs[2].item_sheets


def test_bake_묶음_전부_시트_파일이_없으면_502_대신_실패로_세야_한다(monkeypatch, repo) -> None:
    _sheet_files_missing_for(repo, {1, 2, 3})
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.status_code == 200
    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 0, "failedCnt": 3, "lastYn": True}
    assert generator.calls == []
    assert all(SWEATER in saved.failed_items for saved in repo.jobs.values())


def test_bake_대상_목록의_Java_4xx는_그대로(monkeypatch, repo) -> None:
    async def list_bake_targets(item_sn):
        raise BackendError(404, b'{"code":"ITEM_NOT_FOUND"}', "application/json", [])

    repo.list_bake_targets = list_bake_targets
    generator = BakeClient()
    res = post_bake(make_client(monkeypatch, repo, generator))
    assert res.status_code == 404
    assert res.json()["code"] == "ITEM_NOT_FOUND"
    assert generator.calls == []


def test_bake_회원_미리보기가_먼저_굽고_같은_키는_다시_굽지_않는다(monkeypatch, repo) -> None:
    generator, queue = BakeClient(), BakeQueue()
    order: list[int] = []
    original = service._bake_one

    async def recording(task):
        order.append(task.pixel_char_sn)
        return await original(task)

    monkeypatch.setattr(service, "_bake_one", recording)
    preview = BakeTask(generator, repo, 3, SWEATER, fake_item("green-sweater"), sheet(), "PETC0001")

    async def scenario():
        batch = asyncio.create_task(service.bake_item_batch(generator, repo, queue, SWEATER))
        await asyncio.sleep(0)
        queue.put_first(preview)
        return await batch

    result = asyncio.run(scenario())
    assert order == [3, 1, 2]
    assert len(generator.calls) == 3
    assert (result.baked_cnt, result.failed_cnt, result.last) == (3, 0, True)


# 관리자만
@pytest.mark.parametrize(
    "call",
    [
        lambda c: post_hint(c, headers=MEMBER),
        lambda c: post_trial(c, headers=MEMBER),
        lambda c: post_bake(c, headers=MEMBER),
    ],
)
def test_관리자가_아니면_403(monkeypatch, repo, call) -> None:
    generator = BakeClient()
    res = call(make_client(monkeypatch, repo, generator))
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert generator.calls == []


def test_쿠키가_없으면_401(monkeypatch, repo) -> None:
    res = post_bake(
        make_client(monkeypatch, repo, BakeClient()), headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 401


def test_X_Requested_With가_없으면_403(monkeypatch, repo) -> None:
    res = post_bake(
        make_client(monkeypatch, repo, BakeClient()), headers={"Cookie": "access_token=admin"}
    )
    assert res.status_code == 403


# FN-MYP-011-01 : 굽기 지시는 Java bake-items 값
class ImageOpenAI:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.images = SimpleNamespace(edit=self._edit)

    def _edit(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        encoded = base64.b64encode(sheet(body=True)).decode()
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])


def test_Java가_준_굽기_지시가_착용_지시에_들어간다() -> None:
    class Repo(FakeCharacterJobRepository):
        async def list_bake_items(self) -> dict[int, engine.BakeItem]:
            return {500: engine.BakeItem(500, "MYPC0004", "a striped orange dog raincoat")}

    fake = ImageOpenAI()
    generator = OpenAICharacterClient(fake, "image-model", "vision-model")
    repo = Repo()
    repo.jobs[1] = character(1)
    tasks = asyncio.run(service._tasks(generator, repo, 1, sheet(), "PETC0002"))
    asyncio.run(service._bake_one(tasks[0]))
    assert "a striped orange cat raincoat" in fake.prompts[0]
    assert 500 in repo.jobs[1].item_sheets


# Java 호출
SETTINGS = Settings(backend_base_url="http://backend.test")


def recording(page: dict, requests: list[httpx2.Request]) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"data": page})

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def test_list_bake_targets는_첫_페이지만_읽는다() -> None:
    requests: list[httpx2.Request] = []
    page = {"pixelCharSns": [1, 2], "last": False}
    repo = JavaCharacterJobRepository(recording(page, requests), SETTINGS, "access_token=admin")
    found = asyncio.run(repo.list_bake_targets(SWEATER))
    assert (found.pixel_char_sns, found.last) == ([1, 2], False)
    assert [str(r.url) for r in requests] == [
        f"http://backend.test/internal/ai/items/{SWEATER}/bake-targets?page=0",
    ]
    assert requests[0].headers["cookie"] == "access_token=admin"


def test_list_bake_targets_응답_모양이_다르면_502() -> None:
    repo = JavaCharacterJobRepository(recording({"items": []}, []), SETTINGS, None)
    with pytest.raises(AppError) as caught:
        asyncio.run(repo.list_bake_targets(SWEATER))
    assert caught.value.http_code == 502


def test_bake_Java_호출에_요청의_관리자_쿠키가_실린다(monkeypatch) -> None:
    """대상 목록·시트 조회·시트 파일·시트 저장 모두 관리자 쿠키 (쿠키 없는 호출 없음)"""
    seen: list[httpx2.Request] = []
    bare = sheet()

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/internal/auth/check":
            return fake_auth_check(request)
        seen.append(request)
        if path.endswith("/bake-items"):
            items = [
                {
                    "itemSn": SWEATER,
                    "regnCd": "MYPC0004",
                    "bakeHint": HINT,
                    "bakeImgRefYn": False,
                    "atchFileSn": 31,
                }
            ]
            return httpx2.Response(200, json={"data": items})
        if path.endswith("/bake-targets"):
            return httpx2.Response(200, json={"data": {"pixelCharSns": [5], "last": True}})
        if path.endswith("/sheets"):
            data = {
                "petSeCd": "PETC0001",
                "sheetFileSn": 50,
                "scale": LAYOUT.scale,
                "originX": LAYOUT.origin_x,
                "originY": LAYOUT.origin_y,
                "items": [],
            }
            return httpx2.Response(200, json={"data": data})
        if "/sheet-files/" in path:
            return httpx2.Response(200, content=bare, headers={"content-type": "image/png"})
        return httpx2.Response(200, json={"data": None})

    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_client] = lambda: BakeClient()
    app.dependency_overrides[get_bake_queue] = lambda: BakeQueue()

    res = post_bake(TestClient(app))

    assert res.json()["data"] == {"itemSn": SWEATER, "bakedCnt": 1, "failedCnt": 0, "lastYn": True}
    paths = [(r.method, r.url.path) for r in seen]
    assert ("PUT", f"/internal/ai/characters/5/item-sheets/{SWEATER}") in paths
    assert any(path.endswith("/5/sheets") for _, path in paths)
    assert all(r.headers.get("cookie") == "access_token=admin" for r in seen)

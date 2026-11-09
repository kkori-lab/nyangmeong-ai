import logging
import os
import re
from collections.abc import AsyncIterator, Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core import logs
from app.core.logs import DailyFileHandler, RequestLogMiddleware

DAY = date(2026, 11, 9)
LINE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} \[\d+\] INFO app\.test - hello$")


@pytest.fixture(autouse=True)
def reset_file_handlers() -> Iterator[None]:
    yield
    logs.configure("")


def _file_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger("app").handlers if isinstance(h, DailyFileHandler)]


def test_empty_log_dir_has_no_file_handler() -> None:
    logs.configure("")

    assert _file_handlers() == []


def test_writes_dated_file_with_java_like_line(tmp_path: Path) -> None:
    logs.configure(str(tmp_path / "logs"), lambda: DAY)

    logging.getLogger("app.test").info("hello")

    text = (tmp_path / "logs" / "ai_2026-11-09.log").read_text(encoding="utf-8")
    assert LINE.match(text.splitlines()[-1])


def test_uvicorn_error_logger_goes_to_file(tmp_path: Path) -> None:
    logs.configure(str(tmp_path), lambda: DAY)

    logging.getLogger("uvicorn.error").warning("boot")

    assert "WARNING uvicorn.error - boot" in (tmp_path / "ai_2026-11-09.log").read_text("utf-8")


def test_date_change_opens_new_file_and_removes_old(tmp_path: Path) -> None:
    today = [DAY]
    next_day = DAY + timedelta(days=1)
    old = tmp_path / f"ai_{(next_day - timedelta(days=31)).isoformat()}.log"
    kept = tmp_path / f"ai_{(next_day - timedelta(days=30)).isoformat()}.log"
    other = tmp_path / "other.log"
    not_date = tmp_path / "ai_backup.log"
    for path in (old, kept, other, not_date):
        path.write_text("x", encoding="utf-8")
    logs.configure(str(tmp_path), lambda: today[0])
    assert old.exists()  # 첫날 기준으로는 30일 이내

    today[0] = next_day
    logging.getLogger("app.test").info("hello")

    assert LINE.match((tmp_path / "ai_2026-11-10.log").read_text("utf-8").strip())
    assert not old.exists()
    assert kept.exists() and other.exists() and not_date.exists()


def test_unwritable_dir_warns_and_keeps_console(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app"):
        logs.configure(str(blocked), lambda: DAY)

    assert _file_handlers() == []
    assert any("로그 폴더에 쓸 수 없어" in r.getMessage() for r in caplog.records)


def test_configure_twice_writes_one_line(tmp_path: Path) -> None:
    logs.configure(str(tmp_path), lambda: DAY)
    logs.configure(str(tmp_path), lambda: DAY)

    logging.getLogger("app.test").info("hello")

    lines = (tmp_path / "ai_2026-11-09.log").read_text("utf-8").splitlines()
    assert [line for line in lines if line.endswith("hello")] == [lines[-1]]
    assert len(_file_handlers()) == 1


@pytest.mark.skipif(os.name == "nt", reason="Windows는 POSIX 권한이 없음")
def test_new_file_mode_is_660_and_new_dir_is_2770(tmp_path: Path) -> None:
    folder = tmp_path / "logs"
    logs.configure(str(folder), lambda: DAY)

    assert (folder / "ai_2026-11-09.log").stat().st_mode & 0o777 == 0o660
    assert folder.stat().st_mode & 0o7777 == 0o2770


def _app(events: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/ok")
    async def ok() -> dict:
        return {"ok": True}

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            yield b"a"
            yield b"b"
            events.append("stream-end")

        return StreamingResponse(body(), media_type="text/event-stream")

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("boom")

    return app


class _Events(logging.Handler):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(record.getMessage())


@pytest.fixture
def events() -> Iterator[list[str]]:
    collected: list[str] = []
    handler = _Events(collected)
    request_logger = logging.getLogger("app.request")
    request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    yield collected
    request_logger.removeHandler(handler)


def test_request_line_without_query(events: list[str]) -> None:
    TestClient(_app(events)).get("/ok?token=secret")

    assert len(events) == 1
    assert re.fullmatch(r"GET /ok -> 200 \(\d+ms\)", events[0])


def test_stream_logged_after_last_chunk(events: list[str]) -> None:
    response = TestClient(_app(events)).get("/stream")

    assert response.text == "ab"
    assert events[0] == "stream-end"
    assert re.fullmatch(r"GET /stream -> 200 \(\d+ms\)", events[1])


def test_exception_logged_as_500(events: list[str]) -> None:
    response = TestClient(_app(events), raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert len(events) == 1
    assert re.fullmatch(r"GET /boom -> 500 \(\d+ms\)", events[0])

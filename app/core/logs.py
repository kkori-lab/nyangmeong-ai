import contextlib
import logging
import os
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import TextIO

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Java 백엔드(logback-spring.xml)에 맞춤 : 날짜별 파일·30일 보관
FILE_PREFIX = "ai_"
KEEP_DAYS = 30
FILE_MODE = 0o660
DIR_MODE = 0o2770
FILE_FORMAT = "%(asctime)s.%(msecs)03d [%(process)d] %(levelname)s %(name)s - %(message)s"
FILE_DATE_FORMAT = "%H:%M:%S"
CONSOLE_FORMAT = "%(levelname)s:     %(name)s - %(message)s"
# 파일에 남길 로거 : app.* INFO 이상과 서버 기동·오류
FILE_TARGETS = ("app", "uvicorn.error", "gunicorn.error")

logger = logging.getLogger("app.logs")
request_logger = logging.getLogger("app.request")


class DailyFileHandler(logging.Handler):
    # LOG_DIR/ai_YYYY-MM-DD.log 이어 쓰기 : 여러 워커가 같은 파일에 쓰므로 이름 바꾸기 회전 안 씀
    def __init__(self, folder: Path, today: Callable[[], date] = date.today) -> None:
        super().__init__()
        self.folder = folder
        self._today = today
        self._day: date | None = None
        self._stream: TextIO | None = None
        self.setFormatter(logging.Formatter(FILE_FORMAT, FILE_DATE_FORMAT))
        self._switch(today())

    def _switch(self, day: date) -> None:
        path = self.folder / f"{FILE_PREFIX}{day.isoformat()}.log"
        is_new = not path.exists()
        stream = open(path, "a", encoding="utf-8")  # noqa: SIM115 : 핸들러가 닫음
        if is_new:
            _chmod(path, FILE_MODE)
        if self._stream is not None:
            self._stream.close()
        self._stream = stream
        self._day = day
        remove_old_files(self.folder, day)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            day = self._today()
            if day != self._day:
                self._switch(day)
            assert self._stream is not None
            self._stream.write(message + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            self.release()
        super().close()


def remove_old_files(folder: Path, today: date) -> None:
    # KEEP_DAYS 지난 ai_*.log만 지움 : 이름이 날짜가 아니면 둠
    limit = today - timedelta(days=KEEP_DAYS)
    for path in folder.glob(f"{FILE_PREFIX}*.log"):
        try:
            day = date.fromisoformat(path.stem[len(FILE_PREFIX) :])
        except ValueError:
            continue
        if day < limit:
            # 다른 워커가 먼저 지웠을 수 있음
            with contextlib.suppress(OSError):
                path.unlink()


def _chmod(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    # 소유자가 아니면 폴더 setgid·umask를 따름
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def _open_folder(log_dir: str, today: Callable[[], date]) -> DailyFileHandler:
    folder = Path(log_dir)
    is_new = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    if is_new:
        _chmod(folder, DIR_MODE)
    return DailyFileHandler(folder, today)


def configure(log_dir: str, today: Callable[[], date] = date.today) -> None:
    # app.* INFO를 콘솔에 노출(원문은 원래 로그 제외), LOG_DIR이 있으면 파일에도
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not any(getattr(h, "_nyang_console", False) for h in app_logger.handlers):
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        console._nyang_console = True  # type: ignore[attr-defined]
        app_logger.addHandler(console)

    # 다시 불러도 파일 핸들러가 겹치지 않게
    for name in FILE_TARGETS:
        target = logging.getLogger(name)
        for handler in [h for h in target.handlers if isinstance(h, DailyFileHandler)]:
            target.removeHandler(handler)
            handler.close()

    if not log_dir:
        return
    try:
        file_handler = _open_folder(log_dir, today)
    except OSError as exc:
        logger.warning("로그 폴더에 쓸 수 없어 콘솔에만 기록: %s", exc)
        return
    for name in FILE_TARGETS:
        logging.getLogger(name).addHandler(file_handler)


class RequestLogMiddleware:
    # 요청마다 "METHOD 경로 -> 상태 (ms)" 한 줄 : 쿼리 문자열·본문·헤더는 남기지 않음
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500
        logged = False

        def write() -> None:
            nonlocal logged
            if logged:
                return
            logged = True
            elapsed = round((time.perf_counter() - started) * 1000)
            method, path = scope["method"], scope["path"]
            request_logger.info("%s %s -> %d (%dms)", method, path, status, elapsed)

        async def send_logged(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            # SSE도 본문 끝까지 잼
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                write()

        try:
            await self.app(scope, receive, send_logged)
        except Exception:
            status = 500
            write()
            raise
        write()  # 본문 없이 끝난 경우(연결 끊김 등)

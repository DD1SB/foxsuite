"""Start-menu entry point with an owned local server and controlled restarts."""

import argparse
import asyncio
import ctypes
import json
import logging
import os
import sys
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import BinaryIO

import uvicorn

from foxcore.errors import error_message
from foxcore.logging import SafeLogger
from foxcore.persistence import Store
from foxlive.cli import bind

from .settings import Locations, atomic_write, load, user_root
from .web import Controller, create_app

log = SafeLogger(__name__)


class AlreadyRunning(ValueError):
    pass


@contextmanager
def instance(locations: Locations) -> Iterator[None]:
    """OS lock is released on crash too; no stale PID-file guessing."""
    stream: BinaryIO = (locations.root / "desktop.lock").open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AlreadyRunning("FoxSuite is already running for this user") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise AlreadyRunning("FoxSuite is already running for this user") from exc
        yield
    finally:
        stream.close()


def notify(message: str) -> None:
    if sys.platform == "win32":
        # Also works in a PyInstaller windowed executable with no stderr.
        getattr(ctypes, "windll").user32.MessageBoxW(None, message, "FoxSuite", 0x10)
    elif sys.stderr is not None:
        print("ERROR: " + message, file=sys.stderr)


async def serve(locations: Locations, override: Path | None, open_browser: bool) -> None:
    settings = load(locations, override)
    controller = Controller(locations, settings, lambda: None)
    while True:
        settings = controller.settings
        logging.getLogger().setLevel(settings.core.logging_level)
        # Fail visibly before Uvicorn can turn an expected migration error into a traceback.
        store = Store(settings.core.database_path)
        store.close()
        endpoint = bind(settings.live)
        path = "/" if settings.completed else "/setup"
        atomic_write(
            locations.root / "running.json",
            json.dumps(
                {"host": settings.live.host, "port": settings.live.port, "path": path}
            ).encode(),
        )
        app = create_app(controller)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_level=settings.core.logging_level.lower(),
                access_log=False,
                log_config=None,
            )
        )
        controller.restart = lambda: setattr(server, "should_exit", True)
        controller.restarting = False

        async def browser() -> None:
            while not server.started:
                await asyncio.sleep(0.1)
            host = f"[{settings.live.host}]" if ":" in settings.live.host else settings.live.host
            path = "/" if settings.completed else "/setup"
            url = f"http://{host}:{settings.live.port}{path}"
            log.info("FoxSuite desktop %s database=%s", url, settings.core.database_path)
            if open_browser:
                await asyncio.to_thread(webbrowser.open, url)

        task = asyncio.create_task(browser())
        try:
            await server.serve(sockets=[endpoint])
            if not server.started:
                raise ValueError("FoxSuite could not start; see the application log")
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            endpoint.close()
        if getattr(app.state, "exit_requested", False) or controller.pending is None:
            break
        action, controller.pending = controller.pending, None
        try:
            action()  # SQLite and serial are now closed by the accepted lifespan.
            controller.result = "ok"
        except Exception as exc:
            controller.result = error_message(exc)
            log.warning("ERROR FoxSuite operation failed: %s", controller.result)
        open_browser = False


def main() -> None:
    parser = argparse.ArgumentParser(description="FoxSuite desktop launcher")
    parser.add_argument("--config", type=Path, help="Advanced read-only configuration override")
    parser.add_argument("--user-directory", type=Path, help="Isolated advanced/test user root")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        locations = Locations(args.user_directory.resolve() if args.user_directory else user_root())
        locations.create()
        handler = RotatingFileHandler(
            locations.logs / "foxsuite.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        logging.basicConfig(
            level=load(locations, args.config).core.logging_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            handlers=[handler],
        )
        with instance(locations):
            try:
                asyncio.run(serve(locations, args.config, not args.no_browser))
            finally:
                (locations.root / "running.json").unlink(missing_ok=True)
    except AlreadyRunning as exc:
        # Reopening the shortcut returns to the suite's owned operational landing page.
        try:
            state = json.loads((locations.root / "running.json").read_text(encoding="utf-8"))
            if (
                args.no_browser
                or state["host"] not in {"localhost", "127.0.0.1", "::1"}
                or not 1 <= state["port"] <= 65535
                or state["path"] not in {"/", "/setup", "/settings"}
            ):
                raise ValueError("Invalid running endpoint")
            host = f"[{state['host']}]" if ":" in state["host"] else state["host"]
            webbrowser.open(f"http://{host}:{state['port']}{state['path']}")
        except Exception:
            notify(str(exc))
            raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        notify(error_message(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import os
from pathlib import Path
import sys
import webbrowser

import uvicorn

from app.config import Settings, get_settings
from app.data_lock import player_runtime_lease
from app.player_runtime import (
    PLAYER_HOST,
    PLAYER_PORT,
    PlayerRuntime,
    create_player_runtime,
)
from app.player_workspace import (
    prepare_player_data_directory,
    require_private_player_data_parent,
)


EXPORT_AND_REMOVE_COMMAND = "export-and-remove"


def packaged_player_data_dir(
    *,
    platform_name: str | None = None,
    home: Path | None = None,
    xdg_data_home: str | None = None,
) -> Path:
    active_platform = sys.platform if platform_name is None else platform_name
    active_home = Path.home() if home is None else home
    if not active_home.is_absolute():
        raise RuntimeError("The player home directory must be absolute")
    if active_platform == "darwin":
        return active_home / "Library" / "Application Support" / "Poker Hero" / "data"
    configured_xdg_root = (
        os.environ.get("XDG_DATA_HOME")
        if xdg_data_home is None
        else xdg_data_home
    )
    if configured_xdg_root:
        data_root = Path(configured_xdg_root).expanduser()
        if not data_root.is_absolute():
            raise RuntimeError("XDG_DATA_HOME must be absolute for the player runtime")
    else:
        data_root = active_home / ".local" / "share"
    return data_root / "poker-hero" / "player" / "data"


def configure_packaged_player_data_dir() -> None:
    if not getattr(sys, "frozen", False):
        return
    configured_data_dir = os.environ.get("POKER_DATA_DIR")
    if configured_data_dir is not None:
        expanded_data_dir = Path(configured_data_dir).expanduser()
        if not expanded_data_dir.is_absolute():
            raise RuntimeError(
                "POKER_DATA_DIR must be absolute for the packaged player runtime"
            )
        os.environ["POKER_DATA_DIR"] = str(expanded_data_dir)
        return
    os.environ["POKER_DATA_DIR"] = str(packaged_player_data_dir())


def build_player_server(runtime: PlayerRuntime) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            runtime.app,
            host=PLAYER_HOST,
            port=PLAYER_PORT,
            proxy_headers=False,
            forwarded_allow_ips="",
            server_header=False,
        )
    )


def configured_player_runtime(settings: Settings) -> PlayerRuntime:
    if settings.deployment_environment != "local":
        raise RuntimeError(
            "The player runtime is available only in the local deployment environment"
        )
    return create_player_runtime(
        settings.data_dir,
        recovery_lock_timeout_seconds=settings.data_lock_recovery_timeout_seconds,
        startup_lock_timeout_seconds=settings.data_lock_startup_timeout_seconds,
        write_lock_timeout_seconds=settings.data_lock_write_timeout_seconds,
        backup_lock_timeout_seconds=settings.data_lock_export_timeout_seconds,
        max_player_backup_bytes=settings.max_backup_upload_bytes,
    )


async def serve_player_runtime(runtime: PlayerRuntime) -> None:
    launch_url = runtime.issue_launch_url()
    server = build_player_server(runtime)
    server_task = asyncio.create_task(server.serve())
    while not server.started and not server_task.done():
        await asyncio.sleep(0.01)
    if not server.started:
        await server_task
        raise RuntimeError("The local player runtime could not bind to loopback")
    if not webbrowser.open(launch_url):
        server.should_exit = True
        await server_task
        raise RuntimeError("The local player runtime could not open a browser")
    await server_task


def main(argv: Sequence[str] | None = None) -> int:
    configure_packaged_player_data_dir()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        if arguments[0] == EXPORT_AND_REMOVE_COMMAND:
            from app.player_uninstall import main as uninstall_main

            return uninstall_main(arguments[1:])
        print(
            f"Unknown player runtime command: {arguments[0]}",
            file=sys.stderr,
        )
        print(
            f"Usage: poker-hero-player [{EXPORT_AND_REMOVE_COMMAND} ...]",
            file=sys.stderr,
        )
        return 2

    # Filesystem validation, lock acquisition, and crash recovery are blocking
    # startup work. Keep them on the main thread before the async server loop
    # exists so they cannot stall Uvicorn's event loop.
    settings = get_settings()
    if settings.deployment_environment != "local":
        raise RuntimeError(
            "The player runtime is available only in the local deployment environment"
        )
    data_dir = prepare_player_data_directory(
        settings.data_dir,
        create_if_missing=True,
    )
    require_private_player_data_parent(data_dir)
    lease = player_runtime_lease(data_dir)
    descriptor = lease.acquire(exclusive=True, timeout_seconds=0)
    try:
        runtime = configured_player_runtime(
            settings.model_copy(update={"data_dir": data_dir})
        )
        asyncio.run(serve_player_runtime(runtime))
    finally:
        lease.release(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

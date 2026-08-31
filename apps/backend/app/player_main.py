from __future__ import annotations

import asyncio
import webbrowser

import uvicorn

from app.config import Settings, get_settings
from app.player_runtime import (
    PLAYER_HOST,
    PLAYER_PORT,
    PlayerRuntime,
    create_player_runtime,
)


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


def main() -> None:
    # Filesystem validation, lock acquisition, and crash recovery are blocking
    # startup work. Keep them on the main thread before the async server loop
    # exists so they cannot stall Uvicorn's event loop.
    runtime = configured_player_runtime(get_settings())
    asyncio.run(serve_player_runtime(runtime))


if __name__ == "__main__":
    main()

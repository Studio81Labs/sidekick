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
    return create_player_runtime(settings.data_dir)


async def serve_player_runtime() -> None:
    runtime = configured_player_runtime(get_settings())
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
    asyncio.run(serve_player_runtime())


if __name__ == "__main__":
    main()

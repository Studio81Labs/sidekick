#!/usr/bin/env python3
from __future__ import annotations

from argparse import ArgumentParser
import asyncio
import os
from pathlib import Path

from app.player_main import build_player_server
from app.player_runtime import create_player_runtime


def _write_launch_url(path: Path, launch_url: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        payload = launch_url.encode("utf-8")
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def _serve(data_dir: Path, launch_file: Path) -> None:
    runtime = create_player_runtime(data_dir)
    _write_launch_url(launch_file, runtime.issue_launch_url())
    await build_player_server(runtime).serve()


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--launch-file", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(_serve(args.data_dir, args.launch_file))


if __name__ == "__main__":
    main()

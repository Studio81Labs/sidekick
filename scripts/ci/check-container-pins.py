#!/usr/bin/env python3
"""Reject mutable container and Debian package inputs used by build/deploy paths."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PINNED = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*:[a-zA-Z0-9._+-]+@sha256:[a-f0-9]{64}$"
)
IMAGE_TOKEN = re.compile(
    r"(?<![$\w/])([a-z0-9][a-z0-9._/-]*:[a-zA-Z0-9._+-]+(?:@sha256:[a-f0-9]{64})?)"
)
SNAPSHOT = "https://snapshot.debian.org/archive/debian/20260825T000000Z"
GOSU = "gosu=1.17-3+b4"


def validate(path: str, text: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()

    if path.endswith("Dockerfile"):
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("# syntax="):
                image = stripped.removeprefix("# syntax=")
                if not PINNED.fullmatch(image):
                    errors.append(f"{path}:{number}: mutable Dockerfile syntax image {image!r}")
            if stripped.startswith("FROM "):
                image = stripped.split()[1]
                if not PINNED.fullmatch(image):
                    errors.append(f"{path}:{number}: mutable base image {image!r}")

    # Explicit image declarations and static docker-run references. Variable
    # references are covered by their *_IMAGE declaration.
    in_docker_run = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        declaration = re.match(r"(?:export\s+)?[A-Z0-9_]*IMAGE[=:]\s*[\"']?([^\"'\s]+)", stripped)
        yaml_declaration = re.match(r"[A-Z0-9_]*IMAGE:\s*([^\s#]+)", stripped)
        if declaration or yaml_declaration:
            image = (declaration or yaml_declaration).group(1)
            if not PINNED.fullmatch(image):
                errors.append(f"{path}:{number}: mutable image declaration {image!r}")

        if "docker run" in line:
            in_docker_run = True
        if in_docker_run:
            for image in IMAGE_TOKEN.findall(line):
                if not PINNED.fullmatch(image):
                    errors.append(f"{path}:{number}: mutable docker run image {image!r}")
            if stripped and not stripped.endswith("\\") and "docker run" not in line:
                in_docker_run = False

    if path == "apps/backend/Dockerfile":
        if SNAPSHOT not in text:
            errors.append(f"{path}: missing immutable Debian snapshot {SNAPSHOT}")
        if "deb.debian.org" in text or "security.debian.org" in text:
            errors.append(f"{path}: live Debian mirror is forbidden")
        if GOSU not in text:
            errors.append(f"{path}: gosu must be installed as {GOSU}")
        if re.search(r"apt-get install[^\n\\]*(?:\s|^)gosu(?:\s|\\|$)", text):
            errors.append(f"{path}: unversioned gosu installation")

    return errors


def self_test() -> int:
    digest = "a" * 64
    good = f"# syntax=docker/dockerfile:1.25@sha256:{digest}\nFROM python:3.12-slim@sha256:{digest}\n"
    assert validate("apps/example/Dockerfile", good) == []
    assert validate("apps/example/Dockerfile", "# syntax=docker/dockerfile:1\nFROM python:3.12\n")
    assert validate(".github/workflows/x.yml", "  TOOL_IMAGE: python:3.12\n")
    assert validate(
        ".github/workflows/x.yml",
        f"  TOOL_IMAGE: python:3.12@sha256:{digest}\n",
    ) == []
    backend = (
        good
        + f"RUN echo {SNAPSHOT} && apt-get install -y {GOSU}\n"
    )
    assert validate("apps/backend/Dockerfile", backend) == []
    assert validate("apps/backend/Dockerfile", good + "RUN apt-get install -y gosu\n")
    print("check-container-pins self-test passed")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return self_test()

    root = Path(__file__).resolve().parents[2]
    candidates = [
        *root.glob("apps/**/Dockerfile"),
        *root.glob(".github/workflows/*.yml"),
        *root.glob("scripts/**/*"),
    ]
    errors: list[str] = []
    for candidate in sorted({path for path in candidates if path.is_file()}):
        relative = candidate.relative_to(root).as_posix()
        try:
            text = candidate.read_text()
        except UnicodeDecodeError:
            continue
        errors.extend(validate(relative, text))

    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1
    print(f"Container and Debian pins verified across {len(candidates)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

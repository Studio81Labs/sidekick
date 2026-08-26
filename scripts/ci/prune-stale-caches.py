#!/usr/bin/env python3
# ported from Studio81Labs/taven@71e82cd
"""Prune obsolete, source-derived GitHub Actions caches on main."""

from __future__ import annotations

import collections
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

HASH_SUFFIX = re.compile(r"-[0-9a-f]{16,}$")
PNPM_KINDS = {"pnpm-linux", "pnpm-macos"}


class PruneError(RuntimeError):
    """A cache API operation failed without reaching the desired state."""


@dataclasses.dataclass(frozen=True)
class Plan:
    doomed: list[dict[str, Any]]
    messages: list[str]
    protected_count: int
    freed_bytes: int


def family(key: str) -> str:
    """Collapse one or more trailing content hashes into a stable family."""
    while HASH_SUFFIX.search(key):
        key = HASH_SUFFIX.sub("", key)
    return key


def cache_version(*paths: str, compression: str) -> str:
    components = [*paths, compression, "1.0"]
    return hashlib.sha256("|".join(components).encode()).hexdigest()


def managed_kind(key: str) -> str | None:
    if key.startswith("node-cache-Linux-") and "-pnpm-" in key:
        return "pnpm-linux"
    if key.startswith("node-cache-macOS-") and "-pnpm-" in key:
        return "pnpm-macos"
    for prefix, kind in (
        ("gradle-", "gradle"),
        ("cocoapods-", "cocoapods"),
        ("spm-", "spm"),
    ):
        if key.startswith(prefix):
            return kind
    return None


def source_hash(kind: str, current_hashes: Mapping[str, str]) -> str:
    return current_hashes["pnpm" if kind in PNPM_KINDS else kind]


def current_kind(key: str, current_hashes: Mapping[str, str]) -> str | None:
    kind = managed_kind(key)
    if kind is None:
        return None
    digest = source_hash(kind, current_hashes)
    suffix = f"-pnpm-{digest}" if kind in PNPM_KINDS else f"-{digest}"
    return kind if digest and key.endswith(suffix) else None


def is_current(
    cache: Mapping[str, Any],
    current_hashes: Mapping[str, str],
    current_versions: Mapping[str, str],
) -> bool:
    kind = current_kind(str(cache["key"]), current_hashes)
    return bool(kind) and cache.get("version") == current_versions[kind]


def select_keep(
    items: Sequence[dict[str, Any]],
    current_hashes: Mapping[str, str],
    current_versions: Mapping[str, str],
) -> tuple[list[dict[str, Any]], str]:
    exact = [
        cache
        for cache in items
        if is_current(cache, current_hashes, current_versions)
    ]
    if exact:
        return exact, "exact current-main key/version(s)"

    kinds = {managed_kind(str(cache["key"])) for cache in items}
    if len(kinds) != 1 or None in kinds:
        return [], "unmanaged or mixed family"
    kind = next(iter(kinds))
    assert kind is not None
    if not source_hash(kind, current_hashes):
        return [], "capability has no current source input"

    # A source change can make every stored entry obsolete before the new cache
    # is saved. Retain one immutable newest fallback so stale entries cannot
    # consume the quota needed to create the current cache.
    newest = max(items, key=lambda cache: (cache["created_at"], cache["id"]))
    return [newest], "newest fallback while current cache is absent"


def plan_deletions(
    caches: Sequence[dict[str, Any]],
    current_hashes: Mapping[str, str],
    current_versions: Mapping[str, str],
) -> Plan:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for cache in caches:
        if cache["ref"] == "refs/heads/main":
            groups[family(str(cache["key"]))].append(cache)

    protected_count = sum(
        1
        for items in groups.values()
        for cache in items
        if is_current(cache, current_hashes, current_versions)
    )
    doomed: list[dict[str, Any]] = []
    messages: list[str] = []
    freed = 0

    for cache_family, items in sorted(groups.items()):
        if len(items) < 2:
            continue
        keep, reason = select_keep(items, current_hashes, current_versions)
        if not keep:
            messages.append(
                f"{cache_family}: {len(items)} entries, {reason}; "
                "leaving this family untouched"
            )
            continue
        kept_ids = {cache["id"] for cache in keep}
        rest = [cache for cache in items if cache["id"] not in kept_ids]
        messages.append(
            f"{cache_family}: {len(items)} entries, keeping {len(keep)} {reason}"
        )
        doomed.extend(rest)
        freed += sum(int(cache["size_in_bytes"]) for cache in rest)

    return Plan(doomed, messages, protected_count, freed)


Api = Callable[..., subprocess.CompletedProcess[str]]
Emit = Callable[[str], None]


def gh_api(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def list_caches(repo: str, api: Api = gh_api) -> list[dict[str, Any]]:
    # gh concatenates paginated JSON documents. --jq emits one cache object per
    # line, avoiding an invalid multi-document json.loads call.
    result = api(
        "--paginate",
        f"repos/{repo}/actions/caches?per_page=100",
        "--jq",
        ".actions_caches[]",
    )
    if result.returncode != 0:
        raise PruneError(f"could not list caches: {result.stderr.strip()}")
    return [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def execute_deletions(
    doomed: Sequence[dict[str, Any]],
    repo: str,
    *,
    dry_run: bool,
    api: Api = gh_api,
    emit: Emit = print,
) -> None:
    for cache in doomed:
        gb = int(cache["size_in_bytes"]) / 2**30
        if dry_run:
            emit(f"  would delete {gb:.2f} GB  {str(cache['key'])[:56]}")
            continue
        result = api("-X", "DELETE", f"repos/{repo}/actions/caches/{cache['id']}")
        if result.returncode == 0:
            emit(f"  deleted {gb:.2f} GB  {str(cache['key'])[:56]}")
        elif "(HTTP 404)" in result.stderr:
            emit(f"  already gone {gb:.2f} GB  {str(cache['key'])[:56]}")
        else:
            raise PruneError(
                f"could not delete cache {cache['id']}: {result.stderr.strip()}"
            )


def compression_method() -> str:
    try:
        result = subprocess.run(
            ["zstd", "--quiet", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "gzip"
    return "zstd-without-long" if (result.stdout + result.stderr).strip() else "gzip"


def current_inputs(
    environ: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    hashes = {
        "pnpm": environ.get("CURRENT_PNPM_HASH", ""),
        "gradle": environ.get("CURRENT_GRADLE_HASH", ""),
        "cocoapods": environ.get("CURRENT_COCOAPODS_HASH", ""),
        "spm": environ.get("CURRENT_SPM_HASH", ""),
    }
    pnpm_linux_path = environ["CURRENT_PNPM_CACHE_PATH"]
    linux_home = "/home/runner/"
    if not pnpm_linux_path.startswith(linux_home):
        raise PruneError(
            "cannot derive hosted macOS pnpm cache path from "
            f"{pnpm_linux_path}"
        )
    pnpm_macos_path = pnpm_linux_path.replace(
        linux_home,
        "/Users/runner/",
        1,
    )
    compression = compression_method()
    versions = {
        "pnpm-linux": cache_version(
            pnpm_linux_path,
            compression=compression,
        ),
        "pnpm-macos": cache_version(
            pnpm_macos_path,
            compression=compression,
        ),
        "gradle": cache_version(
            "~/.gradle/caches",
            "~/.gradle/wrapper",
            compression=compression,
        ),
        "cocoapods": cache_version(
            "apps/mobile/ios/Pods",
            "~/Library/Caches/CocoaPods",
            "~/.cocoapods",
            compression=compression,
        ),
        "spm": cache_version(
            "~/Library/Caches/org.swift.swiftpm",
            compression=compression,
        ),
    }
    return hashes, versions


def run(
    environ: Mapping[str, str] = os.environ,
    *,
    api: Api = gh_api,
    emit: Emit = print,
) -> None:
    repo = environ["REPO"]
    dry_run = environ.get("DRY_RUN") == "true"
    hashes, versions = current_inputs(environ)
    caches = list_caches(repo, api)
    plan = plan_deletions(caches, hashes, versions)

    emit(
        f"::notice::found {plan.protected_count} source-derived current-main "
        "cache key/version(s)"
    )
    for message in plan.messages:
        emit(message)
    if not plan.doomed:
        emit("Nothing superseded. Store is clean.")

    execute_deletions(
        plan.doomed,
        repo,
        dry_run=dry_run,
        api=api,
        emit=emit,
    )
    verb = "would reclaim" if dry_run else "reclaimed"
    emit(
        f"::notice::{verb} {plan.freed_bytes / 2**30:.2f} GB across "
        f"{len(plan.doomed)} superseded cache(s)"
    )

    usage = api(f"repos/{repo}/actions/cache/usage")
    if usage.returncode == 0:
        size = json.loads(usage.stdout)["active_caches_size_in_bytes"] / 2**30
        emit(
            f"::notice::store reported at {size:.2f} GB of 10 GB "
            "(lags this sweep)"
        )


def main() -> int:
    try:
        run()
    except (KeyError, PruneError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# ported from Studio81Labs/taven@71e82cd
"""Fixture tests for prune-stale-caches.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("prune-stale-caches.py")
SPEC = importlib.util.spec_from_file_location("prune_stale_caches", MODULE_PATH)
assert SPEC and SPEC.loader
pruner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pruner
SPEC.loader.exec_module(pruner)

A = "a" * 64
B = "b" * 64
C = "c" * 64
CURRENT_HASHES = {
    "pnpm": C,
    "gradle": C,
    "cocoapods": C,
    "spm": C,
}
CURRENT_VERSIONS = {
    "pnpm-linux": "pnpm-linux-current",
    "pnpm-macos": "pnpm-macos-current",
    "gradle": "gradle-current",
    "cocoapods": "cocoapods-current",
    "spm": "spm-current",
}


def cache(
    cache_id: int,
    key: str,
    *,
    version: str = "old",
    created_at: str = "2026-01-01T00:00:00Z",
    ref: str = "refs/heads/main",
    size: int = 100,
) -> dict[str, Any]:
    return {
        "id": cache_id,
        "key": key,
        "version": version,
        "created_at": created_at,
        "ref": ref,
        "size_in_bytes": size,
    }


def result(
    returncode: int = 0,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class SelectionTests(unittest.TestCase):
    def test_pnpm_versions_match_pinned_cache_toolkit_identity(self) -> None:
        self.assertEqual(
            pruner.cache_version(
                "/home/runner/setup-pnpm/node_modules/.bin/store/v11",
                compression="zstd-without-long",
            ),
            "448f2d7dc1f8ceb9086f9e11e6d35c5d2161b7d5aec564630e1c5d3c3ea058b6",
        )
        self.assertEqual(
            pruner.cache_version(
                "/Users/runner/setup-pnpm/node_modules/.bin/store/v11",
                compression="zstd-without-long",
            ),
            "69b3f758a6bc32ad0a214598a78dffbdf891bf8815dff3e01112f3c397653add",
        )

    def test_family_strips_all_trailing_content_hashes(self) -> None:
        self.assertEqual(
            pruner.family(f"gradle-linux-{A}-{B}"),
            "gradle-linux",
        )

    def test_exact_current_entry_wins_over_newer_obsolete_entry(self) -> None:
        current = cache(
            1,
            f"node-cache-Linux-x64-pnpm-{C}",
            version=CURRENT_VERSIONS["pnpm-linux"],
            created_at="2026-01-01T00:00:00Z",
        )
        newer_obsolete = cache(
            2,
            f"node-cache-Linux-x64-pnpm-{B}",
            created_at="2026-02-01T00:00:00Z",
        )
        plan = pruner.plan_deletions(
            [current, newer_obsolete],
            CURRENT_HASHES,
            CURRENT_VERSIONS,
        )
        self.assertEqual([entry["id"] for entry in plan.doomed], [2])
        self.assertEqual(plan.protected_count, 1)
        self.assertEqual(plan.freed_bytes, 100)

    def test_missing_current_keeps_only_newest_fallback(self) -> None:
        older = cache(1, f"node-cache-Linux-x64-pnpm-{A}")
        newer = cache(
            2,
            f"node-cache-Linux-x64-pnpm-{B}",
            created_at="2026-02-01T00:00:00Z",
        )
        plan = pruner.plan_deletions(
            [older, newer],
            CURRENT_HASHES,
            CURRENT_VERSIONS,
        )
        self.assertEqual([entry["id"] for entry in plan.doomed], [1])
        self.assertIn("newest fallback", plan.messages[0])

    def test_unknown_family_is_untouched(self) -> None:
        entries = [
            cache(1, f"ruby-linux-{A}"),
            cache(2, f"ruby-linux-{B}"),
        ]
        plan = pruner.plan_deletions(
            entries,
            CURRENT_HASHES,
            CURRENT_VERSIONS,
        )
        self.assertEqual(plan.doomed, [])
        self.assertIn("unmanaged", plan.messages[0])

    def test_removed_capability_family_is_untouched(self) -> None:
        hashes = {**CURRENT_HASHES, "gradle": ""}
        entries = [
            cache(1, f"gradle-linux-{A}"),
            cache(2, f"gradle-linux-{B}"),
        ]
        plan = pruner.plan_deletions(entries, hashes, CURRENT_VERSIONS)
        self.assertEqual(plan.doomed, [])
        self.assertIn("no current source input", plan.messages[0])

    def test_pr_cache_is_never_considered(self) -> None:
        entries = [
            cache(1, f"gradle-linux-{A}", ref="refs/pull/4/merge"),
            cache(2, f"gradle-linux-{B}", ref="refs/pull/4/merge"),
        ]
        plan = pruner.plan_deletions(
            entries,
            CURRENT_HASHES,
            CURRENT_VERSIONS,
        )
        self.assertEqual(plan.doomed, [])
        self.assertEqual(plan.messages, [])


class DeletionTests(unittest.TestCase):
    def test_cache_listing_failure_is_fatal(self) -> None:
        def api(*_args: str) -> subprocess.CompletedProcess[str]:
            return result(1, stderr="gh: forbidden (HTTP 403)")

        with self.assertRaisesRegex(pruner.PruneError, "could not list caches"):
            pruner.list_caches("Studio81Labs/taven", api)

    def test_dry_run_never_calls_delete_api(self) -> None:
        calls: list[tuple[str, ...]] = []
        lines: list[str] = []

        def api(*args: str) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return result()

        pruner.execute_deletions(
            [cache(7, f"gradle-linux-{A}")],
            "Studio81Labs/taven",
            dry_run=True,
            api=api,
            emit=lines.append,
        )
        self.assertEqual(calls, [])
        self.assertIn("would delete", lines[0])

    def test_success_and_confirmed_404_reach_desired_state(self) -> None:
        responses = iter(
            [
                result(),
                result(1, stderr="gh: Not Found (HTTP 404)"),
            ]
        )
        lines: list[str] = []

        def api(*_args: str) -> subprocess.CompletedProcess[str]:
            return next(responses)

        pruner.execute_deletions(
            [
                cache(7, f"gradle-linux-{A}"),
                cache(8, f"gradle-linux-{B}"),
            ],
            "Studio81Labs/taven",
            dry_run=False,
            api=api,
            emit=lines.append,
        )
        self.assertIn("deleted", lines[0])
        self.assertIn("already gone", lines[1])

    def test_non_404_delete_failure_is_fatal(self) -> None:
        def api(*_args: str) -> subprocess.CompletedProcess[str]:
            return result(1, stderr="gh: forbidden (HTTP 403)")

        with self.assertRaisesRegex(pruner.PruneError, "could not delete cache 7"):
            pruner.execute_deletions(
                [cache(7, f"gradle-linux-{A}")],
                "Studio81Labs/taven",
                dry_run=False,
                api=api,
            )


if __name__ == "__main__":
    unittest.main()

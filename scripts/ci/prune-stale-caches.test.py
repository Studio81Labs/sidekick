#!/usr/bin/env python3
# ported from Studio81Labs/taven@71e82cd
"""Fixture tests for prune-stale-caches.py."""

from __future__ import annotations

import importlib.util
import json
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


class FlutterFamilyTests(unittest.TestCase):
    """A bumped Flutter pin strands a whole family, not an entry within one."""

    SDK = "flutter-linux-stable-3.41.9-x64"
    PUB = "flutter-pub-linux-stable-3.41.9-x64"

    def plan(self, items, pin):
        return pruner.plan_deletions(items, CURRENT_HASHES, CURRENT_VERSIONS, pin)

    def test_family_version_read_from_real_key_shapes(self) -> None:
        # The exact keys subosito/flutter-action wrote for this repository,
        # after family() has collapsed their content hashes.
        self.assertEqual(pruner.flutter_family_version(self.SDK), "3.41.9")
        self.assertEqual(pruner.flutter_family_version(self.PUB), "3.41.9")
        self.assertEqual(
            pruner.flutter_family_version("flutter-macos-stable-3.47.1-arm64"),
            "3.47.1",
        )

    def test_non_flutter_families_are_not_mistaken_for_one(self) -> None:
        for key in ("gradle-linux", "node-cache-Linux-x64-pnpm", "spm-macos"):
            self.assertIsNone(pruner.flutter_family_version(key))

    def test_superseded_family_is_collected_despite_being_one_entry(self) -> None:
        # The whole point: len(items) < 2 skips this family, so without the
        # explicit rule a stranded 1.7 GiB SDK is never collected.
        plan = self.plan([cache(1, f"{self.SDK}-{A}", size=1_667_372_167)], "3.47.1")
        self.assertEqual([entry["id"] for entry in plan.doomed], [1])
        self.assertEqual(plan.freed_bytes, 1_667_372_167)

    def test_pub_family_is_collected_with_its_sdk(self) -> None:
        plan = self.plan(
            [cache(1, f"{self.SDK}-{A}"), cache(2, f"{self.PUB}-{A}-{B}")],
            "3.47.1",
        )
        self.assertEqual(sorted(entry["id"] for entry in plan.doomed), [1, 2])

    def test_family_matching_the_pin_is_never_collected(self) -> None:
        plan = self.plan(
            [cache(1, f"{self.SDK}-{A}"), cache(2, f"{self.PUB}-{A}-{B}")],
            "3.41.9",
        )
        self.assertEqual(plan.doomed, [])
        self.assertEqual(plan.freed_bytes, 0)

    def test_unreadable_pin_collects_nothing(self) -> None:
        # Fail safe: an unreadable renovate.json must not authorise deleting
        # 1.7 GiB on a version nobody supplied.
        plan = self.plan([cache(1, f"{self.SDK}-{A}")], None)
        self.assertEqual(plan.doomed, [])
        self.assertIn("flutter pin unreadable", " ".join(plan.messages))

    def test_other_families_still_pruned_alongside(self) -> None:
        # The Flutter branch continues past the loop body, so it must not stop
        # the ordinary same-family supersession from happening.
        current = cache(
            1,
            f"node-cache-Linux-x64-pnpm-{C}",
            version=CURRENT_VERSIONS["pnpm-linux"],
        )
        superseded = cache(2, f"node-cache-Linux-x64-pnpm-{B}")
        plan = self.plan(
            [cache(3, f"{self.SDK}-{A}"), current, superseded],
            "3.47.1",
        )
        self.assertEqual(sorted(entry["id"] for entry in plan.doomed), [2, 3])


class FlutterPinReadTests(unittest.TestCase):
    def test_reads_the_constraint_this_repository_ships(self) -> None:
        # CAPABILITY-NEUTRAL, necessarily. This file is byte-identical across
        # the repository family and not every member ships Flutter: taven and
        # sidekick have no `constraints.flutter` at all, where None is the
        # correct answer and the pruner's documented "collect nothing". An
        # unconditional assertNotNone here asserted a capability rather than a
        # behaviour, and failed their CI on a file that was working exactly as
        # designed.
        #
        # So compare the reader against whatever renovate.json this repository
        # actually ships. That still exercises the real file rather than a
        # fixture, and it cannot encode one repo's topology into a shared file.
        root = Path(__file__).resolve().parent.parent.parent
        declared = (
            json.loads((root / "renovate.json").read_text())
            .get("constraints", {})
            .get("flutter")
        )
        pin = pruner.read_flutter_pin(root)
        self.assertEqual(pin, declared)
        if declared is not None:
            # Where a pin exists it is the same value check-flutter-pin.py holds
            # the workflows to, so the pruner and the build can never disagree
            # about which SDK is current.
            self.assertRegex(str(pin), r"^\d+\.\d+\.\d+$")

    def test_missing_or_malformed_renovate_json_reads_as_unknown(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(pruner.read_flutter_pin(root))
            (root / "renovate.json").write_text("{ not json")
            self.assertIsNone(pruner.read_flutter_pin(root))
            (root / "renovate.json").write_text('{"constraints": {}}')
            self.assertIsNone(pruner.read_flutter_pin(root))
            (root / "renovate.json").write_text('{"constraints": {"flutter": 3.4}}')
            self.assertIsNone(pruner.read_flutter_pin(root))


if __name__ == "__main__":
    unittest.main()

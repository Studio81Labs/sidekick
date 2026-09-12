from __future__ import annotations

from hashlib import sha256
from importlib import util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_script(module_name: str, filename: str) -> ModuleType:
    spec = util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


build_player_runtime = _load_script(
    "build_player_runtime_script",
    "build-player-runtime.py",
)
smoke_player_runtime = _load_script(
    "smoke_player_runtime_script",
    "smoke-player-runtime.py",
)
verify_player_runtime_update = _load_script(
    "verify_player_runtime_update_script",
    "verify-player-runtime-update.py",
)


def _runtime_archive(
    tmp_path: Path,
    *,
    output_name: str,
    payload: bytes,
    source_revision: str,
) -> Path:
    product_version = "0.1.0"
    system = smoke_player_runtime._safe_tag(platform.system())
    machine = smoke_player_runtime._safe_tag(platform.machine())
    python_parts = platform.python_version().split(".")
    artifact_name = (
        f"poker-hero-player-0-1-0-{system}-{machine}-"
        f"cp{python_parts[0]}{python_parts[1]}"
    )
    bundle = tmp_path / output_name / artifact_name
    bundle.mkdir(parents=True)
    entrypoint = bundle / "poker-hero-player"
    entrypoint.write_bytes(b"#!/bin/sh\nexit 0\n")
    entrypoint.chmod(0o755)
    (bundle / "application-bytes").write_bytes(payload)
    assets = bundle / "_internal" / "player-assets"
    assets.mkdir(parents=True)
    (assets / "index.html").write_bytes(b"<html>" + payload + b"</html>")
    (assets / "sw.js").write_bytes(b"worker-" + payload)
    build_player_runtime._write_bundle_manifest(
        bundle,
        artifact_name=artifact_name,
        product_version=product_version,
        entrypoint=entrypoint.name,
    )
    output = tmp_path / output_name / "release"
    output.mkdir()
    archive = output / f"{artifact_name}.tar.gz"
    checksum = output / f"{artifact_name}.tar.gz.sha256"
    provenance = output / f"{artifact_name}.tar.gz.provenance.json"
    build_player_runtime._publish_archive(
        bundle,
        archive,
        checksum,
        provenance,
        {
            "schema_version": 1,
            "source_revision": source_revision,
            "source_tree_clean": True,
        },
    )
    return archive


def test_launch_capture_helper_writes_a_private_single_use_ticket(
    tmp_path: Path,
) -> None:
    capture_path = tmp_path / "launch-url"
    ticket = "a" * 43
    launch_url = f"http://127.0.0.1:8765/#ticket={ticket}"
    helper = ROOT / "scripts" / "capture-player-launch-url.sh"

    subprocess.run(
        [str(helper), launch_url],
        env={
            "PATH": "/usr/bin:/bin",
            "POKER_HERO_PLAYER_LAUNCH_URL_FILE": str(capture_path),
        },
        check=True,
    )

    assert capture_path.stat().st_mode & 0o777 == 0o600
    assert smoke_player_runtime._wait_for_launch_ticket(capture_path) == ticket
    assert not capture_path.exists()


def test_archive_publication_stages_on_the_destination_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "work" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "payload").write_bytes(b"payload")
    output = tmp_path / "output"
    output.mkdir()
    archive = output / "bundle.tar.gz"
    checksum = output / "bundle.tar.gz.sha256"
    observed_sources: list[Path] = []
    original_replace = os.replace

    def record_replace(source: str | Path, destination: str | Path) -> None:
        observed_sources.append(Path(source))
        original_replace(source, destination)

    monkeypatch.setattr(build_player_runtime.os, "replace", record_replace)

    build_player_runtime._publish_archive(bundle, archive, checksum)

    assert archive.is_file()
    assert checksum.read_text(encoding="ascii") == (
        f"{sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    )
    assert len(observed_sources) == 2
    assert all(source.parent.parent == output for source in observed_sources)


def test_bundle_inventory_includes_nested_manifests_and_directory_symlinks(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    nested = bundle / "nested"
    target = bundle / "target"
    nested.mkdir(parents=True)
    target.mkdir()
    (nested / "manifest.json").write_text("{}", encoding="utf-8")
    (target / "payload").write_bytes(b"payload")
    (bundle / "current").symlink_to("target", target_is_directory=True)

    entries = {
        entry["path"]: entry for entry in build_player_runtime._bundle_entries(bundle)
    }

    assert entries["nested/manifest.json"]["kind"] == "file"
    assert entries["current"] == {
        "kind": "symlink",
        "mode": (bundle / "current").lstat().st_mode & 0o777,
        "path": "current",
        "target": "target",
    }


def test_smoke_requires_archive_checksum_sidecar(tmp_path: Path) -> None:
    archive = tmp_path / "player.tar.gz"
    archive.write_bytes(b"archive")

    with pytest.raises(
        smoke_player_runtime.PlayerPackageSmokeError,
        match="checksum sidecar is missing",
    ):
        smoke_player_runtime._verify_archive_checksum(archive)


def test_smoke_rejects_link_outside_single_archive_root(tmp_path: Path) -> None:
    archive_path = tmp_path / "player.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        root = tarfile.TarInfo("bundle")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        link = tarfile.TarInfo("bundle/link")
        link.type = tarfile.SYMTYPE
        link.linkname = ".."
        archive.addfile(link)

    with pytest.raises(
        smoke_player_runtime.PlayerPackageSmokeError,
        match="escapes the bundle root",
    ):
        smoke_player_runtime._extract_archive(archive_path, tmp_path / "extract")


def test_smoke_rejects_unsafe_manifest_entrypoint(tmp_path: Path) -> None:
    product_version = "0.1.0"
    system = smoke_player_runtime._safe_tag(platform.system())
    machine = smoke_player_runtime._safe_tag(platform.machine())
    python_version = platform.python_version()
    python_parts = python_version.split(".")
    artifact_name = (
        f"poker-hero-player-0-1-0-{system}-{machine}-"
        f"cp{python_parts[0]}{python_parts[1]}"
    )
    bundle = tmp_path / artifact_name
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "artifact": "poker-hero-player-runtime",
                "artifact_name": artifact_name,
                "entrypoint": "../outside",
                "files": [],
                "platform": {
                    "machine": machine,
                    "python": python_version,
                    "system": system,
                },
                "product_version": product_version,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        smoke_player_runtime.PlayerPackageSmokeError,
        match="entrypoint path is unsafe",
    ):
        smoke_player_runtime._bundle_manifest(bundle)


def test_smoke_accepts_matching_python_abi_with_a_different_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_version = "0.1.0"
    system = smoke_player_runtime._safe_tag(platform.system())
    machine = smoke_player_runtime._safe_tag(platform.machine())
    python_parts = platform.python_version().split(".")
    bundle_python = ".".join(
        (python_parts[0], python_parts[1], str(int(python_parts[2]) + 1))
    )
    artifact_name = (
        f"poker-hero-player-0-1-0-{system}-{machine}-"
        f"cp{python_parts[0]}{python_parts[1]}"
    )
    bundle = tmp_path / artifact_name
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "artifact": "poker-hero-player-runtime",
                "artifact_name": artifact_name,
                "entrypoint": "poker-hero-player",
                "files": [],
                "platform": {
                    "machine": machine,
                    "python": bundle_python,
                    "system": system,
                },
                "product_version": product_version,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    assert smoke_player_runtime._bundle_manifest(bundle)["platform"]["python"] == (
        bundle_python
    )
    monkeypatch.setattr(
        smoke_player_runtime.platform,
        "python_version",
        lambda: f"{python_parts[0]}.{int(python_parts[1]) + 1}.0",
    )
    with pytest.raises(
        smoke_player_runtime.PlayerPackageSmokeError,
        match="Python ABI does not match",
    ):
        smoke_player_runtime._bundle_manifest(bundle)


def test_smoke_rejects_uninventoried_nested_manifest(tmp_path: Path) -> None:
    product_version = "0.1.0"
    system = smoke_player_runtime._safe_tag(platform.system())
    machine = smoke_player_runtime._safe_tag(platform.machine())
    python_version = platform.python_version()
    python_parts = python_version.split(".")
    artifact_name = (
        f"poker-hero-player-0-1-0-{system}-{machine}-"
        f"cp{python_parts[0]}{python_parts[1]}"
    )
    bundle = tmp_path / artifact_name
    (bundle / "nested").mkdir(parents=True)
    entrypoint = bundle / "poker-hero-player"
    entrypoint.write_bytes(b"executable")
    entrypoint.chmod(0o755)
    (bundle / "nested" / "manifest.json").write_text("{}", encoding="utf-8")
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "artifact": "poker-hero-player-runtime",
                "artifact_name": artifact_name,
                "entrypoint": entrypoint.name,
                "files": [
                    {
                        "kind": "file",
                        "mode": 0o755,
                        "path": entrypoint.name,
                        "sha256": smoke_player_runtime._sha256_file(entrypoint),
                        "size": entrypoint.stat().st_size,
                    }
                ],
                "platform": {
                    "machine": machine,
                    "python": python_version,
                    "system": system,
                },
                "product_version": product_version,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        smoke_player_runtime.PlayerPackageSmokeError,
        match="file inventory does not match",
    ):
        smoke_player_runtime._verify_bundle(bundle)


def test_runtime_archive_publication_binds_clean_source_provenance(
    tmp_path: Path,
) -> None:
    archive = _runtime_archive(
        tmp_path,
        output_name="candidate",
        payload=b"candidate application bytes",
        source_revision="a" * 40,
    )

    provenance = verify_player_runtime_update._read_provenance(archive)

    assert provenance == {
        "archive_name": archive.name,
        "archive_sha256": sha256(archive.read_bytes()).hexdigest(),
        "artifact": "poker-hero-player-runtime",
        "schema_version": 1,
        "source_revision": "a" * 40,
        "source_tree_clean": True,
    }


def test_runtime_package_binds_clean_revision_to_shell_and_worker(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    assets = bundle / "_internal" / "player-assets"
    assets.mkdir(parents=True)
    index = assets / "index.html"
    worker = assets / "sw.js"
    index.write_text("<html><head></head><body></body></html>", encoding="utf-8")
    worker.write_text(
        "const cache = 'poker-hero-player-shell-deadbeef';", encoding="utf-8"
    )

    build_player_runtime._bind_player_build_provenance(
        bundle,
        source_revision="a" * 40,
    )

    assert (
        f'name="poker-hero-build-revision" content="{"a" * 40}'
        in index.read_text(encoding="utf-8")
    )
    assert "poker-hero-player-shell-deadbeef-raaaaaaaaaaaa" in worker.read_text(
        encoding="utf-8"
    )


def test_update_staging_requires_changed_clean_source_and_application_bytes(
    tmp_path: Path,
) -> None:
    base_archive = _runtime_archive(
        tmp_path,
        output_name="base",
        payload=b"base application bytes",
        source_revision="a" * 40,
    )
    candidate_archive = _runtime_archive(
        tmp_path,
        output_name="candidate",
        payload=b"candidate application bytes",
        source_revision="b" * 40,
    )

    base = verify_player_runtime_update._stage_archive(
        base_archive,
        stage_root=tmp_path / "stage",
        label="base",
    )
    candidate = verify_player_runtime_update._stage_archive(
        candidate_archive,
        stage_root=tmp_path / "stage",
        label="candidate",
    )

    verify_player_runtime_update._require_distinct_bundles(base, candidate)

    assert base.entrypoint.is_file()
    assert candidate.entrypoint.is_file()
    assert base.bundle_root.parent != candidate.bundle_root.parent


def test_update_requires_candidate_to_match_checkout_and_descend_from_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = verify_player_runtime_update.ValidatedBundle(
        archive_path=Path("base.tar.gz"),
        archive_sha256="a" * 64,
        provenance={"source_revision": "a" * 40},
        bundle_root=Path("base"),
        entrypoint=Path("base/player"),
        manifest={},
    )
    candidate = verify_player_runtime_update.ValidatedBundle(
        archive_path=Path("candidate.tar.gz"),
        archive_sha256="b" * 64,
        provenance={"source_revision": "b" * 40},
        bundle_root=Path("candidate"),
        entrypoint=Path("candidate/player"),
        manifest={},
    )
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_checked_out_source_revision",
        lambda: "b" * 40,
    )
    ancestry_checks: list[tuple[str, str]] = []

    def is_ancestor(base_revision: str, candidate_revision: str) -> bool:
        ancestry_checks.append((base_revision, candidate_revision))
        return True

    monkeypatch.setattr(
        verify_player_runtime_update,
        "_is_git_ancestor",
        is_ancestor,
    )

    verify_player_runtime_update._require_candidate_is_checked_out_descendant(
        base, candidate
    )

    assert ancestry_checks == [("a" * 40, "b" * 40)]


def test_update_rejects_downgrade_or_wrong_checked_out_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = verify_player_runtime_update.ValidatedBundle(
        archive_path=Path("base.tar.gz"),
        archive_sha256="a" * 64,
        provenance={"source_revision": "a" * 40},
        bundle_root=Path("base"),
        entrypoint=Path("base/player"),
        manifest={},
    )
    candidate = verify_player_runtime_update.ValidatedBundle(
        archive_path=Path("candidate.tar.gz"),
        archive_sha256="b" * 64,
        provenance={"source_revision": "b" * 40},
        bundle_root=Path("candidate"),
        entrypoint=Path("candidate/player"),
        manifest={},
    )
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_checked_out_source_revision",
        lambda: "b" * 40,
    )
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_is_git_ancestor",
        lambda *_: False,
    )

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="does not descend",
    ):
        verify_player_runtime_update._require_candidate_is_checked_out_descendant(
            base, candidate
        )

    monkeypatch.setattr(
        verify_player_runtime_update,
        "_checked_out_source_revision",
        lambda: "c" * 40,
    )
    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="does not match",
    ):
        verify_player_runtime_update._require_candidate_is_checked_out_descendant(
            base, candidate
        )


def test_update_staging_cleans_incomplete_application_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _runtime_archive(
        tmp_path,
        output_name="candidate",
        payload=b"candidate application bytes",
        source_revision="b" * 40,
    )

    def interrupted_extract(_archive: Path, _destination: Path) -> Path:
        raise smoke_player_runtime.PlayerPackageSmokeError("simulated interruption")

    monkeypatch.setattr(
        verify_player_runtime_update.SMOKE,
        "_extract_archive",
        interrupted_extract,
    )

    with pytest.raises(
        smoke_player_runtime.PlayerPackageSmokeError,
        match="simulated interruption",
    ):
        verify_player_runtime_update._stage_archive(
            archive,
            stage_root=tmp_path / "stage",
            label="candidate",
        )

    staged = tmp_path / "stage"
    assert not staged.exists() or list(staged.iterdir()) == []


def test_update_negative_artifact_checks_handle_truncated_gzip(
    tmp_path: Path,
) -> None:
    archive = _runtime_archive(
        tmp_path,
        output_name="candidate",
        payload=b"candidate application bytes",
        source_revision="b" * 40,
    )

    verify_player_runtime_update._assert_negative_artifacts_do_not_stage(
        archive,
        stage_root=tmp_path / "negative-artifacts",
    )


def test_update_corrupt_artifact_keeps_valid_sidecars_for_digest_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _runtime_archive(
        tmp_path,
        output_name="candidate",
        payload=b"candidate application bytes",
        source_revision="b" * 40,
    )
    original_stage_archive = verify_player_runtime_update._stage_archive
    checked_corrupt_artifact = False

    def stage_with_corrupt_artifact_check(
        archive_path: Path, *, stage_root: Path, label: str
    ) -> verify_player_runtime_update.ValidatedBundle:
        nonlocal checked_corrupt_artifact
        if archive_path.parent.name == "corrupt-artifact":
            checksum_path = archive_path.with_name(archive_path.name + ".sha256")
            provenance_path = archive_path.with_name(
                archive_path.name + ".provenance.json"
            )
            assert archive_path.name == archive.name
            assert (
                checksum_path.read_text(encoding="ascii").split()[1] == archive.name
            )
            assert json.loads(
                provenance_path.read_text(encoding="utf-8")
            ) == json.loads(
                archive.with_name(archive.name + ".provenance.json").read_text(
                    encoding="utf-8"
                )
            )
            with pytest.raises(
                smoke_player_runtime.PlayerPackageSmokeError,
                match="failed its checksum",
            ):
                smoke_player_runtime._verify_archive_checksum(archive_path)
            checked_corrupt_artifact = True
        return original_stage_archive(
            archive_path,
            stage_root=stage_root,
            label=label,
        )

    monkeypatch.setattr(
        verify_player_runtime_update,
        "_stage_archive",
        stage_with_corrupt_artifact_check,
    )

    verify_player_runtime_update._assert_negative_artifacts_do_not_stage(
        archive,
        stage_root=tmp_path / "negative-artifacts",
    )

    assert checked_corrupt_artifact


def test_update_detects_only_durable_ready_cascades(tmp_path: Path) -> None:
    cascade_root = tmp_path / "imported-hands" / ".cascade"
    ready = cascade_root / "a" / "ready"
    ready.parent.mkdir(parents=True)
    ready.write_bytes(b"")
    incomplete = cascade_root / "b"
    incomplete.mkdir()

    assert verify_player_runtime_update._ready_cascade_markers(tmp_path) == (ready,)

    second = cascade_root / "c" / "ready"
    second.parent.mkdir()
    second.write_bytes(b"")
    assert verify_player_runtime_update._ready_cascade_markers(tmp_path) == (
        ready,
        second,
    )


def test_update_recovery_requires_pending_lifecycle_and_retained_audit() -> None:
    before = {
        "raw_sources": [{"raw_source_id": "source"}],
        "detections": [{"detection_id": "detection", "confidence": 0.8}],
        "conflicts": [{"conflict_id": "conflict"}],
        "canonical_revisions": [{"revision": 1, "approval_id": "approval"}],
    }
    after = {
        "raw_sources": [{"raw_source_id": "source"}],
        "detections": [{"detection_id": "detection", "confidence": 0.8}],
        "conflicts": [{"conflict_id": "conflict"}],
        "canonical_revisions": [{"revision": 1, "approval_id": "approval"}],
        "summary": {
            "lifecycle_status": "deletion_pending",
            "canonical_revision_count": 1,
        },
        "lifecycle": {
            "reason": verify_player_runtime_update._DELETE_REASON,
        },
    }

    verify_player_runtime_update._assert_recovered_lifecycle_retains_audit_state(
        before, after
    )
    after["detections"] = []
    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="audit evidence for detections",
    ):
        verify_player_runtime_update._assert_recovered_lifecycle_retains_audit_state(
            before, after
        )


def test_update_snapshot_includes_retained_recognition_evidence() -> None:
    detail = {
        "summary": {"record_key": "record"},
        "lifecycle": {"status": "rejected"},
        "raw_sources": [{"raw_source_id": "source"}],
        "detections": [{"detection_id": "detection", "confidence": 0.8}],
        "conflicts": [{"conflict_id": "conflict"}],
        "canonical_revisions": [{"revision": 1}],
        "deletion_receipt": None,
    }

    snapshot = verify_player_runtime_update._hand_snapshot(detail)
    detail["detections"] = []

    assert verify_player_runtime_update._hand_snapshot(detail) != snapshot


def test_update_report_is_private_and_non_replaceable(tmp_path: Path) -> None:
    report_path = tmp_path / "update-report.json"
    report = {"schema_version": 1, "candidate": {"source_revision": "b" * 40}}

    verify_player_runtime_update._write_report(report_path, report)

    assert report_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="Refusing to overwrite",
    ):
        verify_player_runtime_update._write_report(report_path, report)

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

from __future__ import annotations

from hashlib import sha256
from importlib import util
import json
import os
from pathlib import Path
import platform
import tarfile
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_script(module_name: str, filename: str) -> ModuleType:
    spec = util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
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

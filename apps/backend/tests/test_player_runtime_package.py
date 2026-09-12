from __future__ import annotations

from hashlib import sha256
from importlib import util
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tarfile
from types import ModuleType
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.player_runtime import load_or_create_installation_secret
from app.player_workspace import PlayerWorkspace


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
    base_worker, candidate_worker = (
        verify_player_runtime_update._require_distinct_player_workers(base, candidate)
    )

    assert base.entrypoint.is_file()
    assert candidate.entrypoint.is_file()
    assert base.bundle_root.parent != candidate.bundle_root.parent
    assert base_worker.read_bytes() != candidate_worker.read_bytes()


def test_update_requires_a_real_browser_worker_transition(tmp_path: Path) -> None:
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
    base_worker = verify_player_runtime_update._embedded_player_asset_path(
        base, "sw.js"
    )
    candidate_worker = verify_player_runtime_update._embedded_player_asset_path(
        candidate, "sw.js"
    )
    candidate_worker.write_bytes(base_worker.read_bytes())

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="player workers are identical",
    ):
        verify_player_runtime_update._require_distinct_player_workers(base, candidate)


def test_update_browser_rehearsal_passes_validated_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched_environment: dict[str, str] = {}
    launch_options: dict[str, object] = {}

    def bundle(
        label: str, revision: str, worker: bytes
    ) -> verify_player_runtime_update.ValidatedBundle:
        root = tmp_path / label
        assets = root / "_internal" / "player-assets"
        assets.mkdir(parents=True)
        worker_path = assets / "sw.js"
        worker_path.write_bytes(worker)
        entrypoint = root / "poker-hero-player"
        entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
        return verify_player_runtime_update.ValidatedBundle(
            archive_path=root / f"{label}.tar.gz",
            archive_sha256=label * 64,
            provenance={"source_revision": revision},
            bundle_root=root,
            entrypoint=entrypoint,
            manifest={"files": [{"path": "_internal/player-assets/sw.js"}]},
        )

    class Process:
        returncode = 0

        def communicate(self, *, timeout: int) -> tuple[str, str]:
            assert (
                timeout
                == verify_player_runtime_update._BROWSER_REHEARSAL_OUTER_TIMEOUT_SECONDS
            )
            return "", ""

    def start_process(*_args: object, **kwargs: object) -> Process:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        launched_environment.update(environment)
        launch_options.update(kwargs)
        return Process()

    monkeypatch.setattr(
        verify_player_runtime_update.subprocess, "Popen", start_process
    )

    verify_player_runtime_update._run_browser_update_rehearsal(
        bundle("base", "a" * 40, b"base worker"),
        bundle("candidate", "b" * 40, b"candidate worker"),
        data_dir=tmp_path / "data",
        capture_dir=tmp_path / "capture",
    )

    assert (
        launched_environment["POKER_PLAYER_UPDATE_BASE_SOURCE_REVISION"] == "a" * 40
    )
    assert (
        launched_environment["POKER_PLAYER_UPDATE_CANDIDATE_SOURCE_REVISION"]
        == "b" * 40
    )
    assert launch_options["stdout"] is subprocess.PIPE
    assert launch_options["stderr"] is subprocess.PIPE
    assert "capture_output" not in launch_options


def test_update_recovery_interruption_duplicates_distinct_ready_cascades(
    tmp_path: Path,
) -> None:
    ready_markers = []
    for cascade, record in (("first", "primary"), ("second", "secondary")):
        source = tmp_path / "imported-hands" / ".cascade" / cascade
        staged = source / "staged" / record / "content"
        staged.mkdir(parents=True)
        (staged / "record.json").write_text(
            f'{{"record": "{record}"}}\n', encoding="utf-8"
        )
        ready = source / "ready"
        ready.write_bytes(b"")
        ready_markers.append(ready)

    markers = verify_player_runtime_update._duplicate_ready_cascades_for_recovery_interruption(
        tuple(ready_markers)
    )

    assert (
        len(markers)
        == 2
        * (
            verify_player_runtime_update._CANDIDATE_RECOVERY_REPLAY_COPIES_PER_RECORD
            + 1
        )
    )
    assert all(marker.is_file() and not marker.is_symlink() for marker in markers)
    assert {
        next((marker.parent / "staged").iterdir()).name for marker in markers
    } == {"primary", "secondary"}


def test_update_candidate_recovery_interruption_keeps_pending_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_markers = tuple(
        tmp_path / f"cascade-{index}" / "ready" for index in range(3)
    )
    observations = iter((pending_markers, pending_markers[1:], pending_markers[1:]))

    class Process:
        returncode: int | None = None
        killed = False

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self, *, timeout: int) -> None:
            assert timeout == 10

        def poll(self) -> int | None:
            return self.returncode

    process = Process()
    candidate = verify_player_runtime_update.ValidatedBundle(
        archive_path=tmp_path / "candidate.tar.gz",
        archive_sha256="c" * 64,
        provenance={"source_revision": "c" * 40},
        bundle_root=tmp_path,
        entrypoint=tmp_path / "poker-hero-player",
        manifest={},
    )
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_duplicate_ready_cascades_for_recovery_interruption",
        lambda _ready: pending_markers,
    )
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_ready_cascade_markers",
        lambda _data_dir: next(observations),
    )
    monkeypatch.setattr(
        verify_player_runtime_update.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_assert_player_listener_unreachable_during_recovery",
        lambda: None,
    )

    verify_player_runtime_update._interrupt_candidate_during_recovery(
        candidate,
        data_dir=tmp_path / "data",
        capture_path=tmp_path / "capture",
        ready_markers=pending_markers,
    )

    assert process.killed is True


def test_update_recovery_interruption_rejects_an_available_player_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_player_runtime_update.SMOKE,
        "_request",
        lambda _path: (503, b"", {}),
    )

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="bound the player listener",
    ):
        verify_player_runtime_update._assert_player_listener_unreachable_during_recovery()


def test_update_timeout_terminates_the_browser_rehearsal_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, signal.Signals]] = []
    timeouts: list[int] = []

    class Process:
        pid = 123

        def communicate(self, *, timeout: int) -> tuple[str, str]:
            timeouts.append(timeout)
            if len(timeouts) == 1:
                raise subprocess.TimeoutExpired("pnpm", timeout)
            return "", ""

    monkeypatch.setattr(
        verify_player_runtime_update.os,
        "killpg",
        lambda process_group, termination_signal: signals.append(
            (process_group, termination_signal)
        ),
    )

    verify_player_runtime_update._terminate_browser_update_rehearsal_process_group(
        Process()  # type: ignore[arg-type]
    )

    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]
    assert timeouts == [
        verify_player_runtime_update._BROWSER_REHEARSAL_TERMINATION_TIMEOUT_SECONDS,
        verify_player_runtime_update._BROWSER_REHEARSAL_TERMINATION_TIMEOUT_SECONDS,
    ]


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
    monkeypatch.setattr(
        verify_player_runtime_update,
        "_require_clean_checkout",
        lambda: None,
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
        "_require_clean_checkout",
        lambda: None,
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


def test_update_requires_a_clean_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    def dirty_status(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=" M scripts/verify-player-runtime-update.py\n",
            stderr="",
        )

    monkeypatch.setattr(verify_player_runtime_update.subprocess, "run", dirty_status)

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="requires a clean",
    ):
        verify_player_runtime_update._require_clean_checkout()


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
            "record_key": "record",
            "record_version": "version",
            "identity": {
                "namespace": "pokerstars",
                "site": "PokerStars",
                "source_hand_id": "1",
            },
            "lifecycle_status": "deletion_pending",
            "lifecycle_changed_at": "2026-09-12T00:00:00Z",
            "active_canonical_revision": None,
            "deletion_generation": 1,
            "canonical_revision_count": 1,
        },
        "lifecycle": {
            "status": "deletion_pending",
            "active_canonical_revision": None,
            "deletion_generation": 1,
            "changed_at": "2026-09-12T00:00:00Z",
            "reason": verify_player_runtime_update._DELETE_REASON,
            "deletion_request": {
                "generation": 1,
                "requested_at": "2026-09-12T00:00:00Z",
                "cleanup_status": "pending",
                "last_error": None,
            },
        },
    }
    expected_transition = {
        "summary": after["summary"].copy(),
        "lifecycle": after["lifecycle"].copy(),
    }

    verify_player_runtime_update._assert_recovered_lifecycle_retains_audit_state(
        before, after, expected_transition
    )
    after["detections"] = []
    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="audit evidence for detections",
    ):
        verify_player_runtime_update._assert_recovered_lifecycle_retains_audit_state(
            before, after, expected_transition
        )


@pytest.mark.parametrize(
    ("target", "value", "match"),
    [
        ("lifecycle.changed_at", "2026-09-12T00:00:01Z", "complete interrupted"),
        (
            "lifecycle.deletion_request.requested_at",
            "2026-09-12T00:00:01Z",
            "complete interrupted",
        ),
        ("summary.record_version", "different-version", "summary record_version"),
    ],
)
def test_update_recovery_requires_the_exact_staged_lifecycle_transition(
    target: str,
    value: str,
    match: str,
) -> None:
    before = {
        "raw_sources": [{"raw_source_id": "source"}],
        "detections": [{"detection_id": "detection", "confidence": 0.8}],
        "conflicts": [{"conflict_id": "conflict"}],
        "canonical_revisions": [{"revision": 1, "approval_id": "approval"}],
    }
    expected_transition = {
        "summary": {
            "record_key": "record",
            "record_version": "version",
            "identity": {"namespace": "pokerstars"},
            "lifecycle_status": "deletion_pending",
            "lifecycle_changed_at": "2026-09-12T00:00:00Z",
            "active_canonical_revision": None,
            "deletion_generation": 1,
            "canonical_revision_count": 1,
        },
        "lifecycle": {
            "status": "deletion_pending",
            "active_canonical_revision": None,
            "deletion_generation": 1,
            "changed_at": "2026-09-12T00:00:00Z",
            "reason": verify_player_runtime_update._DELETE_REASON,
            "deletion_request": {
                "generation": 1,
                "requested_at": "2026-09-12T00:00:00Z",
                "cleanup_status": "pending",
                "last_error": None,
            },
        },
    }
    after = json.loads(json.dumps(before | expected_transition))
    container: dict[str, object] = after
    parts = target.split(".")
    for part in parts[:-1]:
        child = container[part]
        assert isinstance(child, dict)
        container = child
    container[parts[-1]] = value

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match=match,
    ):
        verify_player_runtime_update._assert_recovered_lifecycle_retains_audit_state(
            before,
            after,
            expected_transition,
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


@pytest.mark.parametrize("missing_field", ["decision_artifacts", "grade_artifacts"])
def test_update_restore_comparison_rejects_missing_retained_artifacts(
    missing_field: str,
) -> None:
    record_key = "a" * 64
    archive_bytes = BytesIO()
    manifest = {
        "records": [
            {
                "record_key": record_key,
                "decision_artifacts": [
                    {
                        "filename": "r1-g0.json",
                        "file": f"hands/{record_key}/decisions/r1-g0.json",
                        "sha256": "b" * 64,
                        "size": 123,
                    }
                ],
                "grade_artifacts": [
                    {
                        "filename": "r1-g0-i0.json",
                        "file": f"hands/{record_key}/grades/r1-g0-i0.json",
                        "sha256": "c" * 64,
                        "size": 456,
                    }
                ],
            }
        ]
    }
    with ZipFile(archive_bytes, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))

    expected = verify_player_runtime_update._backup_record_artifact_inventory(
        archive_bytes.getvalue(),
        record_key=record_key,
    )
    restored = expected | {missing_field: ()}

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="did not preserve retained decision and grade artifacts",
    ):
        verify_player_runtime_update._assert_restored_artifact_inventory_matches(
            expected,
            restored,
            description=(
                "Backup restore rehearsal did not preserve retained decision "
                "and grade artifacts"
            ),
        )


def test_update_recovery_comparison_rejects_a_lost_primary_decision_artifact() -> None:
    expected = {
        "decision_artifacts": (("r1-g0.json", "hand/r1-g0.json", "a" * 64, 1),),
        "grade_artifacts": (),
    }

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="Candidate lifecycle recovery did not preserve the primary hand",
    ):
        verify_player_runtime_update._assert_restored_artifact_inventory_matches(
            expected,
            expected | {"decision_artifacts": ()},
            description=(
                "Candidate lifecycle recovery did not preserve the primary "
                "hand's retained artifacts"
            ),
        )


def test_update_seeds_a_valid_retained_grade_artifact(tmp_path: Path) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)

    record_key = verify_player_runtime_update._seed_retained_grade_artifact(data_dir)

    workspace = PlayerWorkspace.open(data_dir)
    assert len(
        workspace.imported_hands.list_reference_activated_grade_artifacts(record_key)
    ) == 1
    assert workspace.remote_reference_consent.load().consent is not None


def test_update_rejects_a_candidate_that_changes_current_operator_authority(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    verify_player_runtime_update._seed_retained_grade_artifact(data_dir)
    expected = verify_player_runtime_update._current_operator_authority_snapshot(
        data_dir
    )
    authority = (
        data_dir
        / verify_player_runtime_update._CURRENT_OPERATOR_AUTHORITY_FILENAMES[0]
    )
    authority.write_text('{"reset": true}\n', encoding="utf-8")

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="changed current operator authorities",
    ):
        verify_player_runtime_update._assert_current_operator_authorities_preserved(
            data_dir,
            expected=expected,
        )


def test_update_rejects_a_candidate_that_changes_the_workspace_manifest(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    verify_player_runtime_update._seed_retained_grade_artifact(data_dir)
    expected = verify_player_runtime_update._workspace_manifest_snapshot(data_dir)
    manifest = data_dir / expected[0]
    manifest.write_text('{"layout_version": 5}\n', encoding="utf-8")

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="changed the current player workspace manifest",
    ):
        verify_player_runtime_update._assert_workspace_manifest_preserved(
            data_dir,
            expected=expected,
        )


def test_update_rejects_a_candidate_that_changes_the_installation_key(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    verify_player_runtime_update._seed_retained_grade_artifact(data_dir)
    assert len(load_or_create_installation_secret(data_dir)) == 32
    expected = verify_player_runtime_update._installation_key_snapshot(data_dir)
    (data_dir / expected[0]).write_bytes(b"x" * 32)

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="changed the permanent player installation key",
    ):
        verify_player_runtime_update._assert_installation_key_preserved(
            data_dir,
            expected=expected,
        )


def test_update_rejects_a_candidate_that_changes_workspace_security_metadata(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    verify_player_runtime_update._seed_retained_grade_artifact(data_dir)
    expected = verify_player_runtime_update._workspace_metadata_snapshot(data_dir)
    data_dir.chmod(0o755)

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="changed player workspace security metadata",
    ):
        verify_player_runtime_update._assert_workspace_metadata_preserved(
            data_dir,
            expected=expected,
        )


def test_update_workspace_metadata_rejects_a_missing_retained_artifact(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    record_key = verify_player_runtime_update._seed_retained_grade_artifact(data_dir)
    expected = verify_player_runtime_update._workspace_metadata_snapshot(data_dir)
    artifact = next(
        (data_dir / "imported-hands" / record_key / "grades").glob("*.json")
    )
    artifact.unlink()

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="changed player workspace security metadata",
    ):
        verify_player_runtime_update._assert_workspace_metadata_preserved(
            data_dir,
            expected=expected,
        )


def test_update_workspace_digest_rejects_a_lease_failure_mutation(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir()
    authority = data_dir / ".poker-hero-reference-activation-catalog.json"
    authority.write_text('{"revision": 1}\n', encoding="utf-8")
    before = verify_player_runtime_update._workspace_digest(data_dir)
    authority.write_text('{"revision": 2}\n', encoding="utf-8")

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="lifetime-lease failure changed",
    ):
        verify_player_runtime_update._assert_workspace_unchanged(
            data_dir,
            expected_digest=before,
            description="Candidate lifetime-lease failure changed the player data workspace",
        )


@pytest.mark.parametrize("target", ["workspace", "entry"])
def test_update_workspace_digest_rejects_a_permission_mutation(
    tmp_path: Path,
    target: str,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    authority = data_dir / ".poker-hero-reference-activation-catalog.json"
    authority.write_text('{"revision": 1}\n', encoding="utf-8")
    authority.chmod(0o600)
    before = verify_player_runtime_update._workspace_digest(data_dir)
    (data_dir if target == "workspace" else authority).chmod(0o744)

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="startup changed the player data workspace",
    ):
        verify_player_runtime_update._assert_workspace_unchanged(
            data_dir,
            expected_digest=before,
            description="Candidate rejected startup changed the player data workspace",
        )


def test_update_restore_comparison_rejects_an_incomplete_deleted_hand() -> None:
    expected = {
        "summary": {"record_key": "record", "lifecycle_status": "deleted"},
        "lifecycle": {"status": "deleted"},
        "raw_sources": [{"raw_source_id": "source"}],
        "detections": [{"detection_id": "detection", "confidence": 0.8}],
        "conflicts": [],
        "canonical_revisions": [{"revision": 1}],
        "deletion_receipt": {"deleted_at": "2026-09-12T00:00:00Z"},
    }
    restored = expected | {"deletion_receipt": None}

    with pytest.raises(
        verify_player_runtime_update.PlayerUpdateValidationError,
        match="did not preserve the deleted hand",
    ):
        verify_player_runtime_update._assert_restored_hand_matches(
            expected,
            restored,
            description="Candidate export-before-data-removal backup did not preserve the deleted hand",
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

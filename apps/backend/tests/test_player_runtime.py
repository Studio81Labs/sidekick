import asyncio
from ipaddress import ip_address
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
from time import monotonic, sleep

import httpx
import pytest
from fastapi.testclient import TestClient

from app.application.imported_hand_ports import ImportedHandRecoveryReport
from app.bootstrap import create_app
from app.config import Settings
from app.player_main import build_player_server, configured_player_runtime
from app.player_namespace import (
    DenyHostedPlayerNamespaceMiddleware,
    is_player_api_path,
    is_player_api_scope,
)
from app.player_runtime import (
    PLAYER_AUTHORITY,
    PLAYER_CSRF_STORAGE_KEY,
    PLAYER_HOST,
    PLAYER_ORIGIN,
    PLAYER_PORT,
    PLAYER_SECRET_FILENAME,
    PLAYER_SESSION_STORAGE_KEY,
    PlayerCredentialError,
    PlayerRuntime,
    PlayerSessionAuthority,
    create_player_runtime,
    load_or_create_installation_secret,
)
from app.player_workspace import PlayerDataDirectoryError
from app.storage.imported_hand_store import FileImportedHandStore


def player_client(tmp_path: Path, **kwargs) -> tuple[TestClient, PlayerRuntime]:
    runtime = create_player_runtime(tmp_path, **kwargs)
    client = TestClient(
        runtime.app,
        base_url=PLAYER_ORIGIN,
        client=("127.0.0.1", 50000),
    )
    return client, runtime


def exchange_session(
    client: TestClient,
    runtime: PlayerRuntime,
) -> dict[str, object]:
    launch_url = runtime.issue_launch_url()
    ticket = launch_url.split("#ticket=", 1)[1]
    response = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_installation_secret_is_stable_and_owner_only(tmp_path: Path) -> None:
    first = load_or_create_installation_secret(tmp_path)
    second = load_or_create_installation_secret(tmp_path)

    assert len(first) == 32
    assert second == first
    assert (tmp_path / PLAYER_SECRET_FILENAME).stat().st_mode & 0o777 == 0o600


def test_installation_secret_rejects_insecure_permissions(tmp_path: Path) -> None:
    secret_path = tmp_path / PLAYER_SECRET_FILENAME
    secret_path.write_bytes(os.urandom(32))
    secret_path.chmod(0o644)

    with pytest.raises(PlayerCredentialError, match="readable only by its owner"):
        load_or_create_installation_secret(tmp_path)


def test_installation_secret_rejects_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(os.urandom(32))
    (tmp_path / PLAYER_SECRET_FILENAME).symlink_to(target)

    with pytest.raises(PlayerCredentialError, match="Cannot safely open"):
        load_or_create_installation_secret(tmp_path)


def test_player_runtime_rejects_a_shared_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "shared-player-data"
    data_dir.mkdir(mode=0o755)
    data_dir.chmod(0o755)

    with pytest.raises(PlayerDataDirectoryError, match="only by its owner"):
        create_player_runtime(data_dir)


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin extended ACL test")
def test_player_runtime_rejects_a_data_directory_acl(tmp_path: Path) -> None:
    data_dir = tmp_path / "acl-player-data"
    data_dir.mkdir(mode=0o700)
    subprocess.run(
        ["/bin/chmod", "+a", "everyone allow read,search", str(data_dir)],
        check=True,
    )

    with pytest.raises(PlayerDataDirectoryError, match="extended ACL"):
        create_player_runtime(data_dir)


def test_player_runtime_opens_only_the_player_store(tmp_path: Path) -> None:
    runtime = create_player_runtime(tmp_path)

    assert runtime.workspace.data_dir == tmp_path.resolve()
    assert runtime.workspace.imported_hands.list_keys() == []
    assert {path.name for path in tmp_path.iterdir()} == {
        ".player-runtime-key",
        ".poker-hero-data.lock",
        "imported-hands",
    }


def test_player_runtime_rejects_an_imported_hand_store_symlink(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    target = tmp_path / "outside-store"
    target.mkdir()
    (data_dir / "imported-hands").symlink_to(target, target_is_directory=True)

    with pytest.raises(PlayerDataDirectoryError, match="must be a directory inside"):
        create_player_runtime(data_dir)


def test_bootstrap_ticket_is_single_use_and_session_requires_csrf() -> None:
    now = [100.0]
    authority = PlayerSessionAuthority(
        b"x" * 32,
        clock=lambda: now[0],
        bootstrap_ttl_seconds=10,
        session_ttl_seconds=20,
    )
    ticket = authority.issue_bootstrap_ticket()

    session = authority.exchange_bootstrap_ticket(ticket)
    assert session is not None
    assert authority.exchange_bootstrap_ticket(ticket) is None
    assert authority.authorize(session.session_token)
    assert not authority.authorize_mutation(session.session_token, "wrong")
    assert authority.authorize_mutation(
        session.session_token,
        session.csrf_token,
    )

    now[0] = 121.0
    assert not authority.authorize(session.session_token)


def test_expired_bootstrap_ticket_cannot_create_a_session() -> None:
    now = [100.0]
    authority = PlayerSessionAuthority(
        b"x" * 32,
        clock=lambda: now[0],
        bootstrap_ttl_seconds=10,
    )
    ticket = authority.issue_bootstrap_ticket()

    now[0] = 111.0
    assert authority.exchange_bootstrap_ticket(ticket) is None


def test_player_shell_bootstraps_from_fragment_into_session_storage(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)

    shell = client.get("/")
    script = client.get("/player-bootstrap.js")
    launch_url = runtime.issue_launch_url()

    assert shell.status_code == 200
    assert "V2 hand-import workflow is not enabled" in shell.text
    assert shell.headers["Cache-Control"] == "no-store"
    assert "#ticket=" in launch_url
    assert "?ticket=" not in launch_url
    assert PLAYER_SESSION_STORAGE_KEY in script.text
    assert PLAYER_CSRF_STORAGE_KEY in script.text
    assert "history.replaceState" in script.text
    assert "location.hash" in script.text
    assert "/api/player/storage" in script.text
    assert 'id="data-location"' in shell.text
    assert "script-src 'self'" in shell.headers["Content-Security-Policy"]


def test_player_api_requires_a_session_and_one_use_launch_ticket(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    launch_url = runtime.issue_launch_url()
    ticket = launch_url.split("#ticket=", 1)[1]

    assert client.get("/api/player/health").status_code == 401
    assert client.get("/api/player/storage").status_code == 401
    response = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    session = response.json()
    assert session["expires_in_seconds"] == 86400

    replay = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    assert replay.status_code == 401

    health = client.get(
        "/api/player/health",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "runtime": "local-player"}

    storage = client.get(
        "/api/player/storage",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert storage.status_code == 200
    assert storage.json() == {
        "status": "ready",
        "storage": "player-local-file",
        "data_directory": str(tmp_path.resolve()),
        "imported_hand_record_count": 0,
        "recovery": {"completed": [], "quarantined": [], "failed": []},
    }


def test_player_storage_status_preserves_recovery_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FileImportedHandStore,
        "has_interrupted_writes",
        lambda _self: True,
    )
    monkeypatch.setattr(
        FileImportedHandStore,
        "recover",
        lambda _self: ImportedHandRecoveryReport(
            completed=("completed-cascade",),
            quarantined=("quarantined-cascade",),
            failed=("failed-cascade",),
        ),
    )
    client, runtime = player_client(tmp_path)
    session = exchange_session(client, runtime)

    storage = client.get(
        "/api/player/storage",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )

    assert storage.status_code == 200
    assert storage.json()["status"] == "attention_required"
    assert storage.json()["recovery"] == {
        "completed": ["completed-cascade"],
        "quarantined": ["quarantined-cascade"],
        "failed": ["failed-cascade"],
    }


def test_player_storage_status_preserves_quarantine_across_restarts(
    tmp_path: Path,
) -> None:
    imported_hands = tmp_path / "imported-hands"
    imported_hands.mkdir(mode=0o700)
    interrupted = imported_hands / ".cascade" / "interrupted-cascade"
    interrupted.mkdir(parents=True)
    (interrupted / "ready").write_bytes(b"")

    first = create_player_runtime(tmp_path)
    assert first.workspace.imported_hand_recovery.quarantined == (
        "interrupted-cascade",
    )
    assert first.workspace.status_payload()["status"] == "attention_required"

    second = create_player_runtime(tmp_path)
    assert second.workspace.imported_hand_recovery == ImportedHandRecoveryReport()
    assert second.workspace.status_payload()["status"] == "attention_required"
    assert second.workspace.status_payload()["recovery"]["quarantined"] == [
        "interrupted-cascade"
    ]


def test_player_api_enforces_origin_and_csrf(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path)
    launch_url = runtime.issue_launch_url()
    ticket = launch_url.split("#ticket=", 1)[1]

    missing_origin = client.post(
        "/api/player/session",
        headers={"Authorization": f"Bearer {ticket}"},
    )
    assert missing_origin.status_code == 403
    wrong_origin = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": "https://attacker.example",
        },
    )
    assert wrong_origin.status_code == 403

    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}
    missing_csrf = client.delete(
        "/api/player/session",
        headers={**authorization, "Origin": PLAYER_ORIGIN},
    )
    assert missing_csrf.status_code == 403
    wrong_csrf = client.delete(
        "/api/player/session",
        headers={
            **authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": "wrong",
        },
    )
    assert wrong_csrf.status_code == 403
    revoked = client.delete(
        "/api/player/session",
        headers={
            **authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
        },
    )
    assert revoked.status_code == 204
    assert client.get("/api/player/health", headers=authorization).status_code == 401


def test_future_player_routes_inherit_session_and_csrf_enforcement(
    tmp_path: Path,
) -> None:
    runtime = create_player_runtime(tmp_path)

    @runtime.api_application.post("/api/player/future-write")
    async def future_write() -> dict[str, bool]:
        return {"written": True}

    client = TestClient(
        runtime.app,
        base_url=PLAYER_ORIGIN,
        client=("127.0.0.1", 50000),
    )
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}

    unauthenticated = client.post(
        "/api/player/future-write",
        headers={"Origin": PLAYER_ORIGIN},
    )
    missing_csrf = client.post(
        "/api/player/future-write",
        headers={**authorization, "Origin": PLAYER_ORIGIN},
    )
    authenticated = client.post(
        "/api/player/future-write",
        headers={
            **authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
        },
    )

    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert authenticated.status_code == 200
    assert authenticated.json() == {"written": True}


@pytest.mark.parametrize(
    ("client_address", "base_url", "headers", "status_code"),
    [
        (("192.168.1.20", 50000), PLAYER_ORIGIN, {}, 403),
        (("127.0.0.1", 50000), "http://localhost:8765", {}, 400),
        (("127.0.0.1", 50000), "http://127.0.0.1", {}, 400),
        (
            ("127.0.0.1", 50000),
            PLAYER_ORIGIN,
            {"X-Forwarded-For": "127.0.0.1"},
            400,
        ),
        (
            ("127.0.0.1", 50000),
            PLAYER_ORIGIN,
            {"Origin": "https://attacker.example"},
            403,
        ),
    ],
)
def test_player_runtime_rejects_network_boundary_bypasses(
    tmp_path: Path,
    client_address: tuple[str, int],
    base_url: str,
    headers: dict[str, str],
    status_code: int,
) -> None:
    runtime = create_player_runtime(tmp_path)
    client = TestClient(
        runtime.app,
        base_url=base_url,
        client=client_address,
    )

    response = client.get("/", headers=headers)

    assert response.status_code == status_code
    assert response.headers["Cache-Control"] == "no-store"


def test_player_launcher_has_a_fixed_loopback_transport(tmp_path: Path) -> None:
    runtime = create_player_runtime(tmp_path)
    server = build_player_server(runtime)

    assert server.config.host == PLAYER_HOST == "127.0.0.1"
    assert server.config.port == PLAYER_PORT == 8765
    assert server.config.proxy_headers is False
    assert server.config.forwarded_allow_ips == ""


def test_player_launcher_rejects_a_hosted_environment(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="only in the local deployment"):
        configured_player_runtime(
            Settings(data_dir=tmp_path, deployment_environment="production")
        )


def _non_loopback_ipv4() -> str | None:
    candidates: set[str] = set()
    try:
        candidates.update(
            address[4][0]
            for address in socket.getaddrinfo(
                socket.gethostname(),
                None,
                family=socket.AF_INET,
            )
        )
    except OSError:
        pass
    route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_probe.connect(("192.0.2.1", 9))
        candidates.add(route_probe.getsockname()[0])
    except OSError:
        pass
    finally:
        route_probe.close()
    return next(
        (
            candidate
            for candidate in sorted(candidates)
            if not ip_address(candidate).is_loopback
        ),
        None,
    )


def test_player_server_accepts_loopback_and_refuses_the_lan_interface(
    tmp_path: Path,
) -> None:
    runtime = create_player_runtime(tmp_path)
    server = build_player_server(runtime)
    server_thread = Thread(target=server.run, daemon=True)
    server_thread.start()
    deadline = monotonic() + 5
    while not server.started and server_thread.is_alive() and monotonic() < deadline:
        sleep(0.01)
    assert server.started

    try:
        launch_url = runtime.issue_launch_url()
        ticket = launch_url.split("#ticket=", 1)[1]
        with httpx.Client(timeout=1, trust_env=False) as client:
            response = client.post(
                f"{PLAYER_ORIGIN}/api/player/session",
                headers={
                    "Authorization": f"Bearer {ticket}",
                    "Origin": PLAYER_ORIGIN,
                },
            )
            assert response.status_code == 200

            lan_address = _non_loopback_ipv4()
            if lan_address is not None:
                with pytest.raises(httpx.ConnectError):
                    client.get(f"http://{lan_address}:{PLAYER_PORT}/")
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
    assert not server_thread.is_alive()


@pytest.mark.parametrize(
    "path",
    [
        "/api/player",
        "/api/player/imports",
        "/api%2Fplayer%2Fimports",
        "/%61pi/%70layer/imports",
        "/%2561pi%252Fplayer%252Fimports",
    ],
)
def test_player_namespace_matches_direct_and_encoded_paths(path: str) -> None:
    assert is_player_api_path(path)


def test_player_namespace_uses_decoded_path_when_raw_utf8_is_malformed() -> None:
    assert is_player_api_scope(
        {
            "type": "http",
            "path": "/api/player/�",
            "raw_path": b"/api%2Fplayer/%FF",
        }
    )


def test_local_player_auth_denies_malformed_encoded_path_before_body(
    tmp_path: Path,
) -> None:
    body_read = False
    sent: list[dict[str, object]] = []
    runtime = create_player_runtime(tmp_path)

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player hand history"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        runtime.app(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/player/�",
                "raw_path": b"/api%2Fplayer/%FF",
                "headers": [(b"host", PLAYER_AUTHORITY.encode("ascii"))],
                "client": ("127.0.0.1", 50000),
            },
            receive,
            send,
        )
    )

    assert not body_read
    assert sent[0]["status"] == 401


def test_hosted_player_denial_does_not_read_the_request_body() -> None:
    inner_called = False
    body_read = False
    sent: list[dict[str, object]] = []

    async def inner(_scope, _receive, _send) -> None:
        nonlocal inner_called
        inner_called = True

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player data"}

    async def send(message) -> None:
        sent.append(message)

    middleware = DenyHostedPlayerNamespaceMiddleware(inner)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/player/imports",
                "raw_path": b"/api%2Fplayer%2Fimports",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not inner_called
    assert not body_read
    assert sent[0]["status"] == 404


def test_hosted_player_websocket_namespace_is_reserved() -> None:
    inner_called = False
    sent: list[dict[str, object]] = []

    async def inner(_scope, _receive, _send) -> None:
        nonlocal inner_called
        inner_called = True

    async def receive() -> dict[str, object]:
        return {"type": "websocket.connect"}

    async def send(message) -> None:
        sent.append(message)

    middleware = DenyHostedPlayerNamespaceMiddleware(inner)
    asyncio.run(
        middleware(
            {
                "type": "websocket",
                "path": "/api/player/events",
                "raw_path": b"/api/player/events",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not inner_called
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_hosted_v1_application_reserves_the_player_namespace(tmp_path: Path) -> None:
    hosted_app = create_app(
        Settings(
            data_dir=tmp_path,
            deployment_environment="production",
            proxy_shared_secret="worker-secret-with-at-least-32-characters",
        )
    )
    client = TestClient(hosted_app)

    response = client.post(
        "/api/player/imports",
        content=b"player hand history",
        headers={"X-Poker-Proxy-Secret": "worker-secret-with-at-least-32-characters"},
    )

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_final_hosted_composition_denies_before_observability_reads_body(
    tmp_path: Path,
) -> None:
    body_read = False
    sent: list[dict[str, object]] = []
    hosted_app = create_app(Settings(data_dir=tmp_path))

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player hand history"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        hosted_app(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/player/imports",
                "raw_path": b"/api%2Fplayer%2Fimports",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not body_read
    assert sent[0]["status"] == 404


def test_final_hosted_composition_denies_malformed_player_path_before_body(
    tmp_path: Path,
) -> None:
    body_read = False
    sent: list[dict[str, object]] = []
    hosted_app = create_app(Settings(data_dir=tmp_path))

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player hand history"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        hosted_app(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/player/�",
                "raw_path": b"/api%2Fplayer/%FF",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not body_read
    assert sent[0]["status"] == 404

import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.providers.base import ProviderConfigurationError
from app.solvers.registry import (
    DEPLOYMENT_SELECTABLE_LOCAL_SOLVER_ENGINE_IDS,
    LOCAL_SOLVER_ENGINE_PLUGINS,
    LOCAL_SOLVER_ENGINE_PLUGIN_IDS,
    LocalSolverEnginePlugin,
    SolverCommand,
    _plugin_catalog,
    get_local_solver_engine,
    resolve_configured_local_solver_engine,
)


def test_local_solver_engine_catalog_exposes_every_installed_engine() -> None:
    assert DEPLOYMENT_SELECTABLE_LOCAL_SOLVER_ENGINE_IDS == frozenset(
        {"local_ev", "postflop_solver"}
    )
    assert list(LOCAL_SOLVER_ENGINE_PLUGINS) == [
        "local_ev",
        "postflop_solver",
        "custom_local",
    ]
    assert LOCAL_SOLVER_ENGINE_PLUGIN_IDS == {
        "local_ev",
        "postflop_solver",
        "custom_local",
    }

    local_ev = get_local_solver_engine("local_ev")
    assert local_ev.label == "Local EV"
    assert local_ev.uses_ev_routing
    assert not local_ev.uses_postflop_routing
    assert local_ev.deployment_selectable

    postflop = get_local_solver_engine("postflop_solver")
    assert postflop.label == "Postflop CFR"
    assert postflop.uses_postflop_routing
    assert not postflop.uses_ev_routing
    assert postflop.deployment_selectable

    custom = get_local_solver_engine("custom_local")
    assert custom.label == "Custom local solver"
    assert custom.is_custom
    assert not custom.deployment_selectable


def test_engine_plugins_build_immutable_command_specs(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        postflop_solver_command='solver --profile "heads up"',
        local_solver_command='custom-solver --mode "fast local"',
    )

    local_ev = get_local_solver_engine("local_ev").build_command(
        settings,
        extra_arguments=("--preflop-chart",),
    )
    assert local_ev.engine_id == "local_ev"
    assert local_ev.arguments == (
        sys.executable,
        "-m",
        "app.solvers.ev_solver_cli",
        "--preflop-chart",
    )
    assert local_ev.cwd == Path(__file__).resolve().parents[1]

    postflop = get_local_solver_engine("postflop_solver").build_command(settings)
    assert postflop.arguments == ("solver", "--profile", "heads up")
    assert postflop.cwd is None

    custom = get_local_solver_engine("custom_local").build_command(settings)
    assert custom.arguments == ("custom-solver", "--mode", "fast local")
    assert custom.cwd is None


def test_configured_engine_resolves_custom_command_before_engine_id(
    tmp_path: Path,
) -> None:
    custom = resolve_configured_local_solver_engine(
        Settings(
            data_dir=tmp_path,
            local_solver_engine="missing",
            local_solver_command="custom-solver",
        )
    )
    local_ev = resolve_configured_local_solver_engine(
        Settings(
            data_dir=tmp_path,
            local_solver_engine="local_ev",
        )
    )

    assert custom.id == "custom_local"
    assert local_ev.id == "local_ev"


def test_local_solver_engine_rejects_unknown_id(tmp_path: Path) -> None:
    with pytest.raises(
        ProviderConfigurationError,
        match="Unknown local solver engine: missing",
    ):
        resolve_configured_local_solver_engine(
            Settings(data_dir=tmp_path, local_solver_engine="missing")
        )


def test_local_solver_engine_rejects_command_identity_mismatch(
    tmp_path: Path,
) -> None:
    mismatched = LocalSolverEnginePlugin(
        id="different",
        label="Different engine",
        mode="ev",
        command_factory=lambda _settings: SolverCommand(
            engine_id="local_ev",
            arguments=("solver",),
        ),
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="built command for 'local_ev'",
    ):
        mismatched.build_command(Settings(data_dir=tmp_path))


def test_local_solver_engine_catalog_rejects_invalid_descriptors() -> None:
    factory = LOCAL_SOLVER_ENGINE_PLUGINS["local_ev"].command_factory

    with pytest.raises(ValueError, match="identity fields"):
        LocalSolverEnginePlugin(
            id="",
            label="Missing ID",
            mode="ev",
            command_factory=factory,
        )
    with pytest.raises(ValueError, match="Unknown local solver engine mode"):
        LocalSolverEnginePlugin(  # type: ignore[arg-type]
            id="unknown_mode",
            label="Unknown mode",
            mode="other",
            command_factory=factory,
        )
    with pytest.raises(TypeError, match="command factory must be callable"):
        LocalSolverEnginePlugin(  # type: ignore[arg-type]
            id="invalid_factory",
            label="Invalid factory",
            mode="ev",
            command_factory=None,
        )
    with pytest.raises(ValueError, match="IDs must be unique"):
        _plugin_catalog(
            LOCAL_SOLVER_ENGINE_PLUGINS["local_ev"],
            LOCAL_SOLVER_ENGINE_PLUGINS["local_ev"],
        )


@pytest.mark.parametrize(
    ("engine_id", "setting", "message"),
    [
        ("postflop_solver", "", "POKER_POSTFLOP_SOLVER_COMMAND must not be blank"),
        ("postflop_solver", "'", "is not a valid shell command"),
        ("custom_local", "", "POKER_LOCAL_SOLVER_COMMAND must not be blank"),
    ],
)
def test_local_solver_engine_rejects_invalid_commands(
    tmp_path: Path,
    engine_id: str,
    setting: str,
    message: str,
) -> None:
    settings = Settings(data_dir=tmp_path)
    if engine_id == "postflop_solver":
        settings.postflop_solver_command = setting
    else:
        settings.local_solver_command = setting

    with pytest.raises(ProviderConfigurationError, match=message):
        get_local_solver_engine(engine_id).build_command(settings)

from __future__ import annotations

from collections.abc import Iterable

from app.config import (
    Settings,
)
from app.domain.pipeline import (
    AdministrativeOcrTestCapability,
    PipelineCapabilities,
    PipelineOption,
    PipelineSelection,
)
from app.parsers.registry import PARSER_PLUGINS, PARSER_PLUGIN_IDS, get_parser_plugin
from app.providers.registry import (
    RECOMMENDATION_PLUGINS,
    RECOMMENDATION_PLUGIN_IDS,
    get_recommendation_plugin,
)
from app.solvers.registry import (
    DEPLOYMENT_SELECTABLE_LOCAL_SOLVER_ENGINE_IDS,
    LOCAL_SOLVER_ENGINE_PLUGINS,
)

LAYOUT_LABELS = {
    "generic": "Generic",
    "fortuna": "Fortuna",
    "nations": "Nations",
    "fortuna_nations": "Fortuna / Nations",
    "pokerstars": "PokerStars",
}
class PipelineSelectionError(ValueError):
    pass


def _enabled(default: str, configured: Iterable[str]) -> list[str]:
    values: list[str] = []
    for value in (default, *configured):
        normalized = value.strip().lower()
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _require_known(value: str, known: frozenset[str], kind: str) -> None:
    if value not in known:
        raise PipelineSelectionError(f"Unknown {kind}: {value}")


def _require_enabled(value: str, enabled: list[str], kind: str) -> None:
    if value not in enabled:
        raise PipelineSelectionError(
            f"{kind.capitalize()} '{value}' is not enabled for this deployment"
        )


def parser_supports_layout(parser_provider: str, layout_profile: str) -> bool:
    plugin = PARSER_PLUGINS.get(parser_provider)
    # Unknown deployment defaults remain runtime parser errors so the job can
    # persist their failure; explicit user selections are rejected earlier.
    return plugin is None or plugin.supports_layout(layout_profile)


def _require_compatible_layout(parser_provider: str, layout_profile: str) -> None:
    if not parser_supports_layout(parser_provider, layout_profile):
        raise PipelineSelectionError(
            f"Layout profile '{layout_profile}' is not supported by parser provider "
            f"'{parser_provider}'"
        )


def _availability(
    settings: Settings,
    kind: str,
    value: str,
) -> str | None:
    if kind == "parser":
        plugin = PARSER_PLUGINS.get(value)
        return plugin.unavailable_reason(settings) if plugin is not None else None
    if kind == "recommendation":
        plugin = RECOMMENDATION_PLUGINS.get(value)
        return plugin.unavailable_reason(settings) if plugin is not None else None
    return None


def configured_local_solver_engine(settings: Settings) -> str:
    if (settings.local_solver_command or "").strip():
        return "custom_local"
    return settings.local_solver_engine.strip().lower()


def configured_recommendation_engine(settings: Settings) -> str | None:
    if settings.recommendation_provider.strip().lower() != "local_solver":
        return None
    return configured_local_solver_engine(settings)


def resolve_pipeline_selection(
    settings: Settings,
    *,
    parser_provider: str | None = None,
    parser_layout_profile: str | None = None,
    recommendation_provider: str | None = None,
    recommendation_engine: str | None = None,
    require_known_defaults: bool = False,
    validate_parser: bool = True,
    validate_recommendation: bool = True,
    enforce_recommendation_allowlist: bool = True,
    validate_availability: bool = True,
    validate_layout_compatibility: bool = True,
) -> PipelineSelection:
    selected_parser = (parser_provider or settings.parser_provider).strip().lower()
    selected_layout = (
        parser_layout_profile or settings.parser_layout_profile
    ).strip().lower()
    selected_recommendation = (
        recommendation_provider or settings.recommendation_provider
    ).strip().lower()

    if validate_parser:
        if parser_provider is not None or require_known_defaults:
            _require_known(selected_parser, PARSER_PLUGIN_IDS, "parser provider")
    if validate_recommendation and (
        recommendation_provider is not None or require_known_defaults
    ):
        _require_known(
            selected_recommendation,
            RECOMMENDATION_PLUGIN_IDS,
            "recommendation provider",
        )
    if validate_parser:
        _require_enabled(
            selected_parser,
            _enabled(settings.parser_provider, settings.parser_enabled_providers),
            "parser provider",
        )
        _require_enabled(
            selected_layout,
            _enabled(
                settings.parser_layout_profile,
                settings.parser_enabled_layout_profiles,
            ),
            "layout profile",
        )
        if validate_layout_compatibility:
            _require_compatible_layout(selected_parser, selected_layout)
    if validate_recommendation and enforce_recommendation_allowlist:
        _require_enabled(
            selected_recommendation,
            _enabled(
                settings.recommendation_provider,
                settings.recommendation_enabled_providers,
            ),
            "recommendation provider",
        )
    if validate_availability:
        if validate_parser:
            parser_unavailable = _availability(settings, "parser", selected_parser)
            if parser_unavailable:
                raise PipelineSelectionError(parser_unavailable)
        if validate_recommendation:
            recommendation_unavailable = _availability(
                settings,
                "recommendation",
                selected_recommendation,
            )
            if recommendation_unavailable:
                raise PipelineSelectionError(recommendation_unavailable)

    selected_engine: str | None = None
    if validate_recommendation and selected_recommendation == "local_solver":
        configured_engine = configured_local_solver_engine(settings)
        selected_engine = (recommendation_engine or configured_engine).strip().lower()
        if configured_engine == "custom_local":
            if selected_engine != "custom_local":
                raise PipelineSelectionError(
                    "A custom local solver command is fixed for this deployment"
                )
        else:
            _require_known(
                selected_engine,
                DEPLOYMENT_SELECTABLE_LOCAL_SOLVER_ENGINE_IDS,
                "recommendation engine",
            )
            if enforce_recommendation_allowlist:
                _require_enabled(
                    selected_engine,
                    _enabled(
                        settings.local_solver_engine,
                        settings.local_solver_enabled_engines,
                    ),
                    "recommendation engine",
                )
    elif validate_recommendation and recommendation_engine:
        raise PipelineSelectionError(
            "A recommendation engine can be selected only with the local solver provider"
        )

    return PipelineSelection(
        parser_provider=selected_parser,
        parser_layout_profile=selected_layout,
        recommendation_provider=selected_recommendation,
        recommendation_engine=selected_engine,
    )


def settings_for_selection(
    settings: Settings,
    selection: PipelineSelection,
) -> Settings:
    updates: dict[str, object] = {
        "parser_provider": selection.parser_provider,
        "parser_layout_profile": selection.parser_layout_profile,
        "recommendation_provider": selection.recommendation_provider,
    }
    if (
        selection.recommendation_provider == "local_solver"
        and selection.recommendation_engine not in {None, "custom_local"}
    ):
        updates["local_solver_engine"] = selection.recommendation_engine
    return settings.model_copy(update=updates)


def _option(
    value: str,
    labels: dict[str, str],
    unavailable_reason: str | None = None,
) -> PipelineOption:
    return PipelineOption(
        id=value,
        label=labels.get(value, value.replace("_", " ").title()),
        available=unavailable_reason is None,
        unavailable_reason=unavailable_reason,
    )


def _parser_option(
    settings: Settings,
    value: str,
    compatible_layouts: list[str],
) -> PipelineOption:
    unavailable_reason = _availability(settings, "parser", value)
    if unavailable_reason is None and not compatible_layouts:
        unavailable_reason = "No enabled layout profile is compatible with this parser"
    return PipelineOption(
        id=value,
        label=get_parser_plugin(value).label,
        available=unavailable_reason is None,
        unavailable_reason=unavailable_reason,
    )


def parser_options_for_layout(
    settings: Settings,
    layout_profile: str,
) -> list[PipelineOption]:
    return [
        _parser_option(settings, parser, [layout_profile])
        for parser in _enabled(
            settings.parser_provider,
            settings.parser_enabled_providers,
        )
        if parser_supports_layout(parser, layout_profile)
    ]


def _recommendation_option(settings: Settings, value: str) -> PipelineOption:
    plugin = get_recommendation_plugin(value)
    unavailable_reason = plugin.unavailable_reason(settings)
    return PipelineOption(
        id=value,
        label=plugin.label,
        available=unavailable_reason is None,
        unavailable_reason=unavailable_reason,
    )


def _solver_engine_option(value: str) -> PipelineOption:
    plugin = LOCAL_SOLVER_ENGINE_PLUGINS.get(value)
    if plugin is None:
        # Inactive stale defaults remain visible for deployment diagnosis. An
        # attempt to select local_solver still rejects the unknown engine.
        return _option(value, {})
    return PipelineOption(
        id=value,
        label=plugin.label,
        available=True,
        unavailable_reason=None,
    )


def pipeline_capabilities(settings: Settings) -> PipelineCapabilities:
    defaults = resolve_pipeline_selection(
        settings,
        require_known_defaults=True,
        validate_availability=False,
        validate_layout_compatibility=False,
    )
    parsers = _enabled(settings.parser_provider, settings.parser_enabled_providers)
    layouts = _enabled(
        settings.parser_layout_profile,
        settings.parser_enabled_layout_profiles,
    )
    recommendations = _enabled(
        settings.recommendation_provider,
        settings.recommendation_enabled_providers,
    )
    configured_engine = configured_local_solver_engine(settings)
    engines = (
        ["custom_local"]
        if configured_engine == "custom_local"
        else _enabled(settings.local_solver_engine, settings.local_solver_enabled_engines)
    )
    layout_compatibility = {
        parser: [
            layout
            for layout in layouts
            if parser_supports_layout(parser, layout)
        ]
        for parser in parsers
    }
    return PipelineCapabilities(
        defaults=defaults,
        parser_providers=[
            _parser_option(settings, value, layout_compatibility[value])
            for value in parsers
        ],
        parser_layout_profiles=[_option(value, LAYOUT_LABELS) for value in layouts],
        parser_layout_compatibility=layout_compatibility,
        recommendation_providers=[
            _recommendation_option(settings, value) for value in recommendations
        ],
        recommendation_engines=[_solver_engine_option(value) for value in engines],
        administrative_ocr_test=AdministrativeOcrTestCapability(
            enabled=settings.admin_ocr_test_enabled,
        ),
    )

from __future__ import annotations

from collections.abc import Iterable

from app.config import Settings
from app.domain.pipeline import (
    AdministrativeOcrTestCapability,
    PipelineCapabilities,
    PipelineOption,
    PipelineSelection,
)
from app.parsers.registry import PARSER_PLUGINS, PARSER_PLUGIN_IDS, get_parser_plugin

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


def _parser_availability(settings: Settings, value: str) -> str | None:
    plugin = PARSER_PLUGINS.get(value)
    return plugin.unavailable_reason(settings) if plugin is not None else None


def resolve_pipeline_selection(
    settings: Settings,
    *,
    parser_provider: str | None = None,
    parser_layout_profile: str | None = None,
    require_known_defaults: bool = False,
    validate_availability: bool = True,
    validate_layout_compatibility: bool = True,
) -> PipelineSelection:
    selected_parser = (parser_provider or settings.parser_provider).strip().lower()
    selected_layout = (
        parser_layout_profile or settings.parser_layout_profile
    ).strip().lower()

    if parser_provider is not None or require_known_defaults:
        _require_known(selected_parser, PARSER_PLUGIN_IDS, "parser provider")
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
    if validate_availability:
        parser_unavailable = _parser_availability(settings, selected_parser)
        if parser_unavailable:
            raise PipelineSelectionError(parser_unavailable)

    return PipelineSelection(
        parser_provider=selected_parser,
        parser_layout_profile=selected_layout,
    )


def settings_for_selection(
    settings: Settings,
    selection: PipelineSelection,
) -> Settings:
    updates: dict[str, object] = {
        "parser_provider": selection.parser_provider,
        "parser_layout_profile": selection.parser_layout_profile,
    }
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
    unavailable_reason = _parser_availability(settings, value)
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
        administrative_ocr_test=AdministrativeOcrTestCapability(
            enabled=settings.admin_ocr_test_enabled,
        ),
    )

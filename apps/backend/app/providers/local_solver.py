import json
import math
import os
from pathlib import Path
import subprocess
from typing import Literal

from pydantic import ValidationError

from app.config import Settings
from app.domain.poker import FacingAction
from app.models import (
    CanonicalState,
    RecommendationRequest,
    RecommendationResult,
)
from app.providers.base import ProviderConfigurationError, ProviderError, ProviderInputError
from app.solvers.preflop_context import (
    normalize_position,
    requires_hero_stack_for_preflop_chart,
    supports_preflop_chart,
)
from app.solvers.postflop_ranges import (
    resolve_cold_four_bet_pot_relative_position,
    resolve_isolation_raised_pot_relative_position,
    resolve_limp_reraised_pot_relative_position,
    resolve_squeeze_pot_relative_position,
    select_postflop_ranges,
)
from app.solvers.registry import (
    LOCAL_SOLVER_ENGINE_PLUGINS,
    LocalSolverEnginePlugin,
    resolve_configured_local_solver_engine,
)
from app.solvers.wager_context import (
    resolve_hero_wager,
    resolve_opponent_commitment_total,
    resolve_opponent_wager,
)


class _LocalSolverResponseError(ProviderError):
    pass


class LocalSolverProvider:
    name = "local_solver"
    required_fields = ["hero_cards", "street", "pot_size", "current_bet", "effective_stack", "players_in_hand"]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def required_fields_for(self, state: CanonicalState) -> list[str]:
        required_fields = list(self.required_fields)
        engine = self._engine()
        uses_builtin_chart_routing = engine.uses_postflop_routing
        chart_needs_hero_stack = (
            uses_builtin_chart_routing
            and state.street == "preflop"
            and requires_hero_stack_for_preflop_chart(state)
        )
        chart_candidate = uses_builtin_chart_routing and state.street == "preflop" and (
            chart_needs_hero_stack
            or supports_preflop_chart(
                RecommendationRequest(state=state, provider=self.name)
            )
        )
        if chart_needs_hero_stack:
            required_fields.append("hero_stack")
        uses_builtin_ev = engine.uses_ev_routing or (
            engine.uses_postflop_routing
            and self.settings.postflop_solver_fallback_enabled
        )
        if (
            uses_builtin_ev
            and not chart_candidate
            and (state.current_bet or 0) > 0
            and resolve_opponent_wager(state) is None
        ):
            required_fields.append("opponent_wager")
        if (
            uses_builtin_ev
            and not chart_candidate
            and (state.current_bet or 0) > 0
            and (state.players_in_hand or 0) > 2
        ):
            required_fields.append("opponents_at_current_bet")
        resolved_wager = resolve_opponent_wager(state)
        committed_opponents = (
            1
            if (state.players_in_hand or 0) == 2
            else state.opponents_at_current_bet
        )
        if (
            uses_builtin_ev
            and not chart_candidate
            and (state.current_bet or 0) > 0
            and resolved_wager is not None
            and committed_opponents is not None
            and resolve_opponent_commitment_total(
                state,
                opponent_wager=resolved_wager,
                opponents_at_current_bet=committed_opponents,
                hero_wager=resolve_hero_wager(
                    state,
                    opponent_wager=resolved_wager,
                ),
            )
            is None
        ):
            required_fields.append("opponent_commitment_total")
        if not self._requires_postflop_solver_inputs(state):
            return required_fields

        required_fields.append("board_cards")
        if _postflop_position_for_state(state) is None:
            if state.hero_position is None or not state.hero_position.strip():
                required_fields.append("hero_position")
            elif state.opponent_position is None or not state.opponent_position.strip():
                required_fields.append("opponent_position")
        if (state.current_bet or 0) > 0:
            required_fields.extend(["facing_action", "hero_stack"])
        if state.facing_action == "raise":
            required_fields.extend(["opponent_stack", "postflop_action_history"])
        return required_fields

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        command, cwd, fallback_reason = self._command(request)
        try:
            result = self._run(command, cwd, request)
        except _LocalSolverResponseError:
            raise
        except ProviderError as exc:
            if not self._can_fallback():
                raise
            fallback_reason = str(exc)
            fallback_command, fallback_cwd = LOCAL_SOLVER_ENGINE_PLUGINS[
                "local_ev"
            ].build_command(self.settings).subprocess_arguments()
            result = self._run(fallback_command, fallback_cwd, request)

        if fallback_reason is not None:
            result.raw["requested_engine"] = "postflop_solver"
            if result.raw.get("engine") == "preflop_chart_v1":
                result.raw["routing_reason"] = fallback_reason
                result.explanation = (
                    f"The postflop engine routed this hand to the preflop chart because "
                    f"{fallback_reason}. {result.explanation}"
                )
            else:
                result.raw["fallback_reason"] = fallback_reason
                result.explanation = (
                    f"The postflop solver used the range/EV fallback because {fallback_reason}. "
                    f"{result.explanation}"
                )
        return result

    def _run(
        self,
        command: list[str],
        cwd: Path | None,
        request: RecommendationRequest,
    ) -> RecommendationResult:
        try:
            completed = subprocess.run(
                command,
                input=request.model_dump_json(),
                text=True,
                capture_output=True,
                cwd=cwd,
                env=self._environment(request),
                timeout=self.settings.local_solver_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("Local solver timed out") from exc
        except OSError as exc:
            raise ProviderError(f"Local solver could not be started: {exc}") from exc

        if completed.returncode != 0:
            output = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise ProviderError(f"Local solver failed with return code {completed.returncode}: {output}")

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise _LocalSolverResponseError(
                "Local solver returned invalid JSON"
            ) from exc

        try:
            return RecommendationResult.model_validate(payload)
        except ValidationError as exc:
            raise _LocalSolverResponseError(
                "Local solver returned invalid payload"
            ) from exc

    def _command(
        self, request: RecommendationRequest
    ) -> tuple[list[str], Path | None, str | None]:
        engine = self._engine()
        if engine.is_custom or engine.uses_ev_routing:
            command, cwd = engine.build_command(
                self.settings
            ).subprocess_arguments()
            return command, cwd, None

        unsupported_reason = self._postflop_unsupported_reason(request)
        if unsupported_reason is not None:
            if supports_preflop_chart(request):
                command, cwd = LOCAL_SOLVER_ENGINE_PLUGINS[
                    "local_ev"
                ].build_command(
                    self.settings,
                    extra_arguments=("--preflop-chart",),
                ).subprocess_arguments()
                return command, cwd, unsupported_reason
            if not self.settings.postflop_solver_fallback_enabled:
                raise ProviderInputError(unsupported_reason)
            command, cwd = LOCAL_SOLVER_ENGINE_PLUGINS[
                "local_ev"
            ].build_command(self.settings).subprocess_arguments()
            return command, cwd, unsupported_reason

        command, cwd = engine.build_command(self.settings).subprocess_arguments()
        return command, cwd, None

    def _engine(self) -> LocalSolverEnginePlugin:
        return resolve_configured_local_solver_engine(self.settings)

    def _requires_postflop_solver_inputs(self, state: CanonicalState) -> bool:
        engine = self._engine()
        return (
            engine.uses_postflop_routing
            and not self.settings.postflop_solver_fallback_enabled
            and state.street in {"flop", "turn", "river"}
        )

    def _can_fallback(self) -> bool:
        return (
            self._engine().uses_postflop_routing
            and self.settings.postflop_solver_fallback_enabled
        )

    @staticmethod
    def _postflop_unsupported_reason(request: RecommendationRequest) -> str | None:
        state = request.state
        expected_board_cards = {"flop": 3, "turn": 4, "river": 5}
        if state.street == "preflop":
            return "the hand is preflop"
        if state.street not in expected_board_cards:
            return "the postflop street is missing"
        if len(state.hero_cards) != 2:
            return "exactly two hero cards are required"
        if len(state.board_cards) != expected_board_cards[state.street]:
            return f"the {state.street} requires {expected_board_cards[state.street]} board cards"
        if state.players_in_hand != 2:
            return "the open-source engine supports heads-up postflop spots only"
        if _postflop_position_for_state(state) is None:
            return (
                "hero position must identify IP or OOP, or hero and opponent "
                "seats must establish relative position"
            )
        history_reason = _postflop_history_unsupported_reason(state)
        if history_reason is not None:
            return history_reason
        if (state.current_bet or 0) > 0 and (state.hero_stack is None or state.hero_stack <= 0):
            return "hero stack is required to reconstruct a facing-bet postflop tree"
        return None

    def _environment(self, request: RecommendationRequest) -> dict[str, str]:
        environment = os.environ.copy()
        range_selection = select_postflop_ranges(
            request.state,
            hero_relative_position=_postflop_position_for_state(request.state),
            configured_oop_range=self.settings.postflop_solver_oop_range,
            configured_ip_range=self.settings.postflop_solver_ip_range,
            contextual_enabled=(
                self.settings.postflop_solver_range_mode == "contextual"
                and self._engine().uses_postflop_routing
            ),
        )
        environment.update(
            {
                "POKER_POSTFLOP_SOLVER_MAX_ITERATIONS": str(
                    self.settings.postflop_solver_max_iterations
                ),
                "POKER_POSTFLOP_SOLVER_TARGET_EXPLOITABILITY": str(
                    self.settings.postflop_solver_target_exploitability
                ),
                "POKER_POSTFLOP_SOLVER_MAX_MEMORY_MB": str(
                    self.settings.postflop_solver_max_memory_mb
                ),
                "POKER_POSTFLOP_SOLVER_BET_SIZES": self.settings.postflop_solver_bet_sizes,
                "POKER_POSTFLOP_SOLVER_RAISE_SIZES": self.settings.postflop_solver_raise_sizes,
                "POKER_POSTFLOP_SOLVER_RAKE_RATE": str(self.settings.postflop_solver_rake_rate),
                "POKER_POSTFLOP_SOLVER_RAKE_CAP": str(self.settings.postflop_solver_rake_cap),
                "POKER_POSTFLOP_SOLVER_OOP_RANGE": range_selection.oop_range,
                "POKER_POSTFLOP_SOLVER_IP_RANGE": range_selection.ip_range,
                "POKER_POSTFLOP_SOLVER_RANGE_SOURCE": range_selection.source,
                "POKER_POSTFLOP_SOLVER_RANGE_CONTEXT": json.dumps(
                    range_selection.context,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
        return environment


_POSTFLOP_SEAT_ORDER = {
    "small_blind": 0,
    "big_blind": 1,
    "utg": 2,
    "hijack": 3,
    "cutoff": 4,
    "button": 5,
}
_POSTFLOP_RELATIVE_POSITION_ALIASES = {
    "ip": "ip",
    "in position": "ip",
    "oop": "oop",
    "out of position": "oop",
}


def _normalize_postflop_position(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(
        value.lower().replace("_", " ").replace("-", " ").split()
    )
    return _POSTFLOP_RELATIVE_POSITION_ALIASES.get(normalized) or normalize_position(
        value
    )


def _postflop_position(
    hero_position: str | None,
    opponent_position: str | None = None,
) -> Literal["ip", "oop"] | None:
    hero = _normalize_postflop_position(hero_position)
    opponent = _normalize_postflop_position(opponent_position)
    inferred: list[Literal["ip", "oop"]] = []
    if hero in {"ip", "oop"}:
        inferred.append(hero)
    if opponent == "ip":
        inferred.append("oop")
    elif opponent == "oop":
        inferred.append("ip")
    if hero == "button":
        inferred.append("ip")
    if opponent == "button":
        inferred.append("oop")
    if inferred:
        return inferred[0] if len(set(inferred)) == 1 else None
    if hero not in _POSTFLOP_SEAT_ORDER or opponent not in _POSTFLOP_SEAT_ORDER:
        return None
    if hero == opponent or {hero, opponent} == {"small_blind", "big_blind"}:
        return None
    return (
        "ip"
        if _POSTFLOP_SEAT_ORDER[hero] > _POSTFLOP_SEAT_ORDER[opponent]
        else "oop"
    )


def _postflop_position_for_state(
    state: CanonicalState,
) -> Literal["ip", "oop"] | None:
    position = _postflop_position(
        state.hero_position,
        state.opponent_position,
    )
    if position is not None:
        return position
    position = resolve_isolation_raised_pot_relative_position(state)
    if position is not None:
        return position
    position = resolve_limp_reraised_pot_relative_position(state)
    if position is not None:
        return position
    position = resolve_squeeze_pot_relative_position(state)
    if position is not None:
        return position
    return resolve_cold_four_bet_pot_relative_position(state)


_SOLVER_MAX_CENTS = 2_147_483_647


def _solver_cents(value: float) -> int | None:
    # Rust's f64::round rounds positive half values away from zero.
    scaled = value * 100
    if not math.isfinite(scaled) or scaled > _SOLVER_MAX_CENTS:
        return None
    return int(scaled + 0.5)


def _postflop_history_unsupported_reason(state: CanonicalState) -> str | None:
    current_bet = _solver_cents(state.current_bet or 0)
    if current_bet is None:
        return "current bet is outside the postflop solver's supported range"
    history = state.postflop_action_history
    if current_bet <= 0 and state.facing_action is not None:
        return "facing action requires a positive amount to call"
    if not history:
        if current_bet > 0 and state.facing_action == "raise":
            return "a raised postflop spot requires structured action history"
        if current_bet > 0 and state.facing_action != "bet":
            return "facing action must identify the outstanding wager"
        return None

    hero_actor = _postflop_position_for_state(state)
    if hero_actor is None:
        return "hero position must identify IP or OOP"
    if state.hero_stack is None or state.hero_stack <= 0:
        return "hero stack is required for structured postflop action history"
    if state.opponent_stack is None:
        return "opponent stack is required for structured postflop action history"

    commitments = {"oop": 0, "ip": 0}
    next_actor: Literal["oop", "ip"] = "oop"
    last_aggression: FacingAction | None = None
    last_full_raise_increment = 0
    short_raise: tuple[int, Literal["oop", "ip"], int] | None = None
    for index, item in enumerate(history, start=1):
        if item.actor != next_actor:
            return f"postflop action {index} must be by {next_actor.upper()}"
        opponent: Literal["oop", "ip"] = "ip" if item.actor == "oop" else "oop"
        if item.action == "check":
            if index != 1:
                return "only the opening OOP action can be a check in current-street history"
            if commitments[item.actor] != commitments[opponent]:
                return f"postflop action {index} cannot check while facing a wager"
        elif item.action == "bet":
            if commitments[item.actor] != commitments[opponent]:
                return f"postflop action {index} must be a raise, not a bet"
            amount = _solver_cents(item.amount or 0)
            if amount is None:
                return f"postflop action {index} bet amount is outside the supported range"
            if amount <= 0:
                return f"postflop action {index} bet amount must round to at least 0.01 BB"
            commitments[item.actor] = amount
            last_full_raise_increment = amount
            last_aggression = "bet"
        else:
            if commitments[item.actor] >= commitments[opponent]:
                return f"postflop action {index} cannot raise without facing a wager"
            amount = _solver_cents(item.amount or 0)
            if amount is None:
                return f"postflop action {index} raise amount is outside the supported range"
            if amount <= 0:
                return f"postflop action {index} raise amount must round to at least 0.01 BB"
            if amount <= commitments[opponent]:
                return f"postflop action {index} raise-to amount must exceed the previous wager"
            raise_increment = amount - commitments[opponent]
            if raise_increment < last_full_raise_increment:
                if index != len(history):
                    return f"postflop action {index} raise is below the minimum full-raise amount"
                short_raise = (index, item.actor, amount)
            else:
                last_full_raise_increment = raise_increment
            commitments[item.actor] = amount
            last_aggression = "raise"
        next_actor = opponent

    if next_actor != hero_actor:
        return "structured postflop action history does not end at the hero decision"

    opponent_actor = "ip" if hero_actor == "oop" else "oop"
    expected_call = commitments[opponent_actor] - commitments[hero_actor]
    if expected_call < 0:
        return "structured postflop action history ends with the opponent facing a wager"
    expected_call = max(expected_call, 0)
    if expected_call != current_bet:
        return (
            "current bet does not match the amount to call implied by structured "
            "postflop action history"
        )
    expected_facing_action = last_aggression if expected_call > 0 else None
    if state.facing_action != expected_facing_action:
        return "facing action does not match structured postflop action history"

    if state.pot_size is not None:
        pot_size = _solver_cents(state.pot_size)
        if pot_size is None:
            return "pot size is outside the postflop solver's supported range"
        if pot_size <= sum(commitments.values()):
            return "pot size must exceed the wagers in structured postflop action history"
    if state.effective_stack is not None:
        hero_stack = _solver_cents(state.hero_stack)
        opponent_stack = _solver_cents(state.opponent_stack)
        effective_stack = _solver_cents(state.effective_stack)
        if hero_stack is None or opponent_stack is None or effective_stack is None:
            return "effective stack is outside the postflop solver's supported range"
        visible_effective = min(hero_stack, opponent_stack)
        if effective_stack != visible_effective:
            return "effective stack does not match the visible hero and opponent stacks"
        starting_effective = min(
            hero_stack + commitments[hero_actor],
            opponent_stack + commitments[opponent_actor],
        )
        if starting_effective > _SOLVER_MAX_CENTS:
            return "effective stack is outside the postflop solver's supported range"
        if max(commitments.values()) > starting_effective:
            return "postflop action history exceeds the reconstructed effective stack"
        if short_raise is not None:
            action_index, actor, amount = short_raise
            visible_stack = hero_stack if actor == hero_actor else opponent_stack
            actor_starting_stack = visible_stack + commitments[actor]
            if amount != actor_starting_stack:
                return (
                    f"postflop action {action_index} raise is below the minimum full-raise "
                    "amount and the actor is not all-in"
                )
    return None

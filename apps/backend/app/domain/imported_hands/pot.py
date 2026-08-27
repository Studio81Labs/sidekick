"""Pure amount-reconciliation oracle for canonical imported hands."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from app.domain.imported_hands.models import (
    Identifier,
    ImportedAction,
    ImportedHandModel,
    ImportedHandState,
    NonNegativeDecimal,
    NonNegativeInteger,
    PositiveDecimal,
    StatedPotSummary,
)


class PotLayer(ImportedHandModel):
    pot_index: NonNegativeInteger
    amount: PositiveDecimal
    contributors: list[Identifier] = Field(min_length=1)
    eligible_players: list[Identifier] = Field(default_factory=list)


class PotReconciliationResult(ImportedHandModel):
    schema_version: Literal["pot-reconciliation/v1"] = "pot-reconciliation/v1"
    status: Literal["pass", "fail", "indeterminate"]
    derived_gross_total: NonNegativeDecimal | None = None
    derived_net_total: NonNegativeDecimal | None = None
    stated_gross_total: NonNegativeDecimal | None = None
    stated_net_total: NonNegativeDecimal | None = None
    awarded_total: NonNegativeDecimal | None = None
    rake: NonNegativeDecimal | None = None
    discrepancy: Decimal | None = Field(default=None, allow_inf_nan=False, strict=True)
    contributions: dict[Identifier, NonNegativeDecimal] = Field(default_factory=dict)
    uncalled_returns: dict[Identifier, NonNegativeDecimal] = Field(default_factory=dict)
    pots: list[PotLayer] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    amount_parse_validated_only: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "pass" and self.errors:
            raise ValueError("a passing pot reconciliation cannot contain errors")
        if self.status == "fail" and not self.errors:
            raise ValueError("a failed pot reconciliation requires an error")
        return self


def reconcile_pot(hand: ImportedHandState) -> PotReconciliationResult:
    """Re-derive gross/net pots from ordered actions and compare stated totals.

    Contributions are accumulated independently for every player and street.
    Explicit uncalled returns reduce them before side-pot layers are built.
    A pass validates only action amounts; it cannot validate cards, chronology,
    participation, button/position, or action origin.
    """

    contributions = {seat.player_id: Decimal(0) for seat in hand.seats}
    returns = {seat.player_id: Decimal(0) for seat in hand.seats}
    folded: set[str] = set()
    all_in_players: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []
    incomplete = False

    for street in hand.streets:
        street_totals = {seat.player_id: Decimal(0) for seat in hand.seats}
        for action in street.actions:
            prior = street_totals[action.actor_id]
            resolved, action_errors, is_incomplete = _resolve_action_total(action, prior)
            errors.extend(
                f"{street.street} action {action.sequence}: {message}"
                for message in action_errors
            )
            incomplete = incomplete or is_incomplete
            if resolved is not None:
                street_totals[action.actor_id] = resolved
            if action.action_type == "uncalled_return" and action.amount is not None:
                returns[action.actor_id] += action.amount
            if action.action_type == "fold":
                folded.add(action.actor_id)
            if action.all_in:
                all_in_players.add(action.actor_id)
        for player_id, amount in street_totals.items():
            contributions[player_id] += amount

    pots = _build_pot_layers(contributions, folded, all_in_players)
    positive_contributions = sorted(
        (amount for amount in contributions.values() if amount > 0),
        reverse=True,
    )
    if not incomplete and (
        len(positive_contributions) == 1
        or (
            len(positive_contributions) > 1
            and positive_contributions[0] > positive_contributions[1]
        )
    ):
        errors.append(
            "one player retains unmatched chips; an uncalled return is missing"
        )
    derived_gross = sum(contributions.values(), Decimal(0)) if not incomplete else None
    stated = hand.results.stated_pot if hand.results is not None else None
    stated_gross = _stated_gross(stated)
    rake = stated.rake if stated is not None else None
    derived_net = (
        derived_gross - rake
        if derived_gross is not None and rake is not None and rake <= derived_gross
        else None
    )
    stated_net = stated.net_total if stated is not None else None
    awards = hand.results.awards if hand.results is not None else []
    awarded_total: Decimal | None = None
    if awards:
        if any(award.amount is None for award in awards):
            warnings.append("one or more pot awards have an unknown amount")
            incomplete = True
        else:
            awarded_total = sum(
                (award.amount or Decimal(0) for award in awards), Decimal(0)
            )

    discrepancy: Decimal | None = None
    if stated is None:
        warnings.append("source does not state a pot total")
        incomplete = True
    elif derived_gross is not None and stated_gross is not None:
        discrepancy = derived_gross - stated_gross
        if discrepancy != 0:
            errors.append(
                f"derived gross pot {derived_gross} does not match stated gross pot {stated_gross}"
            )
    elif derived_net is not None and stated_net is not None:
        discrepancy = derived_net - stated_net
        if discrepancy != 0:
            errors.append(
                f"derived net pot {derived_net} does not match stated net pot {stated_net}"
            )
    else:
        warnings.append("source totals are insufficient for a like-for-like comparison")
        incomplete = True

    if derived_net is not None and stated_net is not None and derived_net != stated_net:
        net_error = f"derived net pot {derived_net} does not match stated net pot {stated_net}"
        if net_error not in errors:
            errors.append(net_error)

    expected_awards = stated_net if stated_net is not None else derived_net
    if awarded_total is not None and expected_awards is not None:
        if awarded_total != expected_awards:
            errors.append(
                f"aggregate pot awards {awarded_total} do not match net pot {expected_awards}"
            )

    if stated is not None and stated.gross_pots and derived_gross is not None:
        derived_components = [pot.amount for pot in pots]
        if derived_components != stated.gross_pots:
            errors.append(
                "derived main/side-pot layers do not match the stated gross pot components"
            )

    status: Literal["pass", "fail", "indeterminate"]
    if errors:
        status = "fail"
    elif incomplete:
        status = "indeterminate"
    else:
        status = "pass"
    return PotReconciliationResult(
        status=status,
        derived_gross_total=derived_gross,
        derived_net_total=derived_net,
        stated_gross_total=stated_gross,
        stated_net_total=stated_net,
        awarded_total=awarded_total,
        rake=rake,
        discrepancy=discrepancy,
        contributions=contributions,
        uncalled_returns={player: amount for player, amount in returns.items() if amount > 0},
        pots=pots,
        errors=errors,
        warnings=warnings,
    )


def _resolve_action_total(
    action: ImportedAction,
    prior: Decimal,
) -> tuple[Decimal | None, list[str], bool]:
    errors: list[str] = []
    if action.action_type in {"fold", "check"}:
        if action.total_committed is not None and action.total_committed != prior:
            errors.append("fold/check total_committed changed without a chip action")
        return prior, errors, False

    if action.action_type == "uncalled_return":
        if action.amount is None and action.total_committed is None:
            return None, [], True
        resolved = action.total_committed
        if action.amount is not None:
            if action.amount > prior:
                errors.append("uncalled return exceeds the player's street commitment")
                resolved_from_amount = Decimal(0)
            else:
                resolved_from_amount = prior - action.amount
            if resolved is not None and resolved != resolved_from_amount:
                errors.append("uncalled return amount disagrees with total_committed")
            resolved = resolved_from_amount
        return resolved, errors, resolved is None

    if action.amount is None and action.total_committed is None:
        return None, [], True
    resolved = action.total_committed
    if action.amount is not None:
        resolved_from_amount = prior + action.amount
        if resolved is not None and resolved != resolved_from_amount:
            errors.append("action amount disagrees with cumulative total_committed")
        resolved = resolved_from_amount
    if resolved is not None and resolved < prior:
        errors.append("chip action cannot reduce total_committed")
    return resolved, errors, resolved is None


def _build_pot_layers(
    contributions: dict[str, Decimal],
    folded: set[str],
    all_in_players: set[str],
) -> list[PotLayer]:
    levels = sorted({amount for amount in contributions.values() if amount > 0})
    if not levels:
        return []
    split_levels = {
        contributions[player]
        for player in all_in_players
        if contributions[player] > 0
    }
    split_levels.add(levels[-1])
    previous = Decimal(0)
    pot_floor = Decimal(0)
    accumulated = Decimal(0)
    pots: list[PotLayer] = []
    for level in levels:
        contributors = [
            player for player, amount in contributions.items() if amount >= level
        ]
        accumulated += (level - previous) * len(contributors)
        if level in split_levels and accumulated > 0:
            pot_contributors = [
                player for player, amount in contributions.items() if amount > pot_floor
            ]
            pots.append(
                PotLayer(
                    pot_index=len(pots),
                    amount=accumulated,
                    contributors=pot_contributors,
                    eligible_players=[
                        player for player in pot_contributors if player not in folded
                    ],
                )
            )
            accumulated = Decimal(0)
            pot_floor = level
        previous = level
    return pots


def _stated_gross(stated: StatedPotSummary | None) -> Decimal | None:
    if stated is None:
        return None
    if stated.gross_total is not None:
        return stated.gross_total
    if stated.gross_pots:
        return sum(stated.gross_pots, Decimal(0))
    if stated.net_total is not None and stated.rake is not None:
        return stated.net_total + stated.rake
    return None

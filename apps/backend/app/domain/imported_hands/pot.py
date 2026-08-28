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
    starting_stacks = {seat.player_id: seat.starting_stack for seat in hand.seats}
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
                starting_stack = starting_stacks[action.actor_id]
                hand_commitment = contributions[action.actor_id] + resolved
                if (
                    starting_stack is not None
                    and hand_commitment > starting_stack
                ):
                    errors.append(
                        f"{street.street} action {action.sequence}: cumulative commitment"
                        f" {hand_commitment} exceeds starting stack {starting_stack}"
                    )
                if action.all_in:
                    if starting_stack is None or hand_commitment == starting_stack:
                        all_in_players.add(action.actor_id)
                    elif hand_commitment < starting_stack:
                        errors.append(
                            f"{street.street} action {action.sequence}: all-in cumulative"
                            f" commitment {hand_commitment} does not exhaust starting"
                            f" stack {starting_stack}"
                        )
            if action.action_type == "uncalled_return" and resolved is not None:
                resolved_return = prior - resolved
                if resolved_return > 0:
                    returns[action.actor_id] += resolved_return
            if action.action_type == "fold":
                folded.add(action.actor_id)
        for player_id, amount in street_totals.items():
            contributions[player_id] += amount

    all_in_players.update(
        player_id
        for player_id, contribution in contributions.items()
        if (starting_stack := starting_stacks[player_id]) is not None
        and starting_stack > 0
        and contribution == starting_stack
    )
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
    contributions_incomplete = incomplete
    awarded_total: Decimal | None = None
    if awards:
        if any(award.amount is None for award in awards):
            warnings.append("one or more pot awards have an unknown amount")
            incomplete = True
        else:
            awarded_total = sum(
                (award.amount or Decimal(0) for award in awards), Decimal(0)
            )
        if contributions_incomplete and any(
            award.pot_index is not None for award in awards
        ):
            warnings.append(
                "indexed pot awards cannot be validated with incomplete contributions"
            )
        elif not contributions_incomplete:
            awards_by_pot: dict[int, Decimal] = {}
            concrete_awards_by_player: dict[str, Decimal] = {}
            recipients_with_concrete_unindexed_awards: set[str] = set()
            for award in awards:
                if award.amount is not None:
                    concrete_awards_by_player[award.player_id] = (
                        concrete_awards_by_player.get(award.player_id, Decimal(0))
                        + award.amount
                    )
                if award.pot_index is None:
                    if award.amount is not None:
                        recipients_with_concrete_unindexed_awards.add(award.player_id)
                    if not any(
                        award.player_id in pot.eligible_players for pot in pots
                    ):
                        errors.append(
                            f"unindexed pot award recipient {award.player_id} is not"
                            " eligible for any derived pot"
                        )
                    continue
                if award.pot_index >= len(pots):
                    errors.append(
                        f"pot award references nonexistent pot index {award.pot_index}"
                    )
                    continue
                if award.player_id not in pots[award.pot_index].eligible_players:
                    errors.append(
                        f"pot award recipient {award.player_id} is not eligible for"
                        f" pot index {award.pot_index}"
                    )
                if award.amount is not None:
                    awards_by_pot[award.pot_index] = (
                        awards_by_pot.get(award.pot_index, Decimal(0))
                        + award.amount
                    )
            for player_id in sorted(recipients_with_concrete_unindexed_awards):
                eligible_total = sum(
                    (
                        pot.amount
                        for pot in pots
                        if player_id in pot.eligible_players
                    ),
                    Decimal(0),
                )
                concrete_total = concrete_awards_by_player[player_id]
                if eligible_total > 0 and concrete_total > eligible_total:
                    errors.append(
                        f"concrete awards {concrete_total} to {player_id} exceed"
                        f" eligible derived pots {eligible_total}"
                    )
            for pot_index, indexed_total in awards_by_pot.items():
                if pot_index < len(pots) and indexed_total > pots[pot_index].amount:
                    errors.append(
                        f"indexed awards {indexed_total} exceed gross pot"
                        f" {pots[pot_index].amount} at index {pot_index}"
                    )

            all_awards_indexed = bool(awards) and all(
                award.pot_index is not None and award.amount is not None
                for award in awards
            )
            zero_rake = rake == 0 or (
                stated_gross is not None
                and stated_net is not None
                and stated_gross == stated_net
            )
            if all_awards_indexed and zero_rake:
                for pot in pots:
                    indexed_total = awards_by_pot.get(pot.pot_index, Decimal(0))
                    if indexed_total != pot.amount:
                        errors.append(
                            f"indexed awards {indexed_total} do not match pot"
                            f" {pot.amount} at index {pot.pot_index}"
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

    stated_distributable_net = (
        stated_net
        if stated_net is not None
        else stated_gross - rake
        if stated_gross is not None and rake is not None
        else None
    )
    expected_awards = (
        stated_distributable_net
        if stated_distributable_net is not None
        else derived_net
    )
    if awarded_total is not None and expected_awards is not None:
        if awarded_total != expected_awards:
            errors.append(
                f"aggregate pot awards {awarded_total} do not match net pot {expected_awards}"
            )
    known_gross = stated_gross if stated_gross is not None else derived_gross
    if awarded_total is not None and known_gross is not None:
        if awarded_total > known_gross:
            errors.append(
                f"aggregate pot awards {awarded_total} exceed known gross pot {known_gross}"
            )

    player_results = hand.results.players if hand.results is not None else []
    award_entries_by_player: dict[str, list[Decimal | None]] = {}
    for award in awards:
        award_entries_by_player.setdefault(award.player_id, []).append(award.amount)
    collection_ceiling = expected_awards if expected_awards is not None else known_gross
    concrete_awards_exhaust_net = (
        awarded_total is not None
        and expected_awards is not None
        and awarded_total == expected_awards
    )
    reconciled_player_collections: dict[str, Decimal] = {}
    for player_result in player_results:
        player_awards = award_entries_by_player.get(player_result.player_id, [])
        known_awards = sum(
            (amount for amount in player_awards if amount is not None),
            Decimal(0),
        )
        awards_complete = concrete_awards_exhaust_net or (
            bool(player_awards)
            and all(amount is not None for amount in player_awards)
        )
        if player_result.total_collected is not None:
            if awards_complete and player_result.total_collected != known_awards:
                errors.append(
                    f"player result {player_result.player_id} total_collected"
                    f" {player_result.total_collected} does not match concrete"
                    f" awards {known_awards}"
                )
            elif known_awards > player_result.total_collected:
                errors.append(
                    f"player result {player_result.player_id} total_collected"
                    f" {player_result.total_collected} is below concrete awards"
                    f" {known_awards}"
                )

        collected_basis = (
            player_result.total_collected
            if player_result.total_collected is not None
            else known_awards
            if awards_complete
            else None
        )
        if collected_basis is not None:
            reconciled_player_collections[player_result.player_id] = collected_basis
        if player_result.net_result is None or contributions_incomplete:
            continue
        contribution = contributions[player_result.player_id]
        if collected_basis is not None:
            expected_net = collected_basis - contribution
            if player_result.net_result != expected_net:
                errors.append(
                    f"player result {player_result.player_id} net_result"
                    f" {player_result.net_result} does not match collected"
                    f" {collected_basis} minus contribution {contribution}"
                )
            continue
        implied_collection = player_result.net_result + contribution
        if implied_collection < 0:
            errors.append(
                f"player result {player_result.player_id} implies a negative collection"
            )
        else:
            reconciled_player_collections[player_result.player_id] = implied_collection

    known_player_collections = sum(
        reconciled_player_collections.values(), Decimal(0)
    )
    if not contributions_incomplete:
        eligible_totals_by_player = {
            player_id: sum(
                (
                    pot.amount
                    for pot in pots
                    if player_id in pot.eligible_players
                ),
                Decimal(0),
            )
            for player_id in contributions
        }
        individually_over_capacity: set[str] = set()
        for player_id, collection in reconciled_player_collections.items():
            eligible_total = eligible_totals_by_player[player_id]
            if collection <= eligible_total:
                continue
            individually_over_capacity.add(player_id)
            if eligible_total == 0:
                errors.append(
                    f"player result {player_id} has positive collection {collection}"
                    " but is not eligible for any derived pot"
                )
            else:
                errors.append(
                    f"player result {player_id} collection {collection} exceeds"
                    f" eligible derived pots {eligible_total}"
                )
        highest_eligible_pot_by_player = {
            player_id: max(
                (
                    pot.pot_index
                    for pot in pots
                    if player_id in pot.eligible_players
                ),
                default=None,
            )
            for player_id in contributions
        }
        # Derived eligibility rings only shrink as layer indexes rise. Players
        # capped at a lower ring must share the capacity through that layer.
        cumulative_capacity = Decimal(0)
        for pot in pots[:-1]:
            cumulative_capacity += pot.amount
            capacity_limited_collections = {
                player_id: collection
                for player_id, collection in reconciled_player_collections.items()
                if collection > 0
                and (
                    highest_eligible_pot_by_player[player_id] is not None
                    and highest_eligible_pot_by_player[player_id] <= pot.pot_index
                )
            }
            if (
                not capacity_limited_collections
                or individually_over_capacity.intersection(
                    capacity_limited_collections
                )
            ):
                continue
            limited_total = sum(
                capacity_limited_collections.values(), Decimal(0)
            )
            if limited_total > cumulative_capacity:
                errors.append(
                    f"known player collections {limited_total} for players"
                    f" {', '.join(sorted(capacity_limited_collections))} exceed shared"
                    f" eligible pot capacity {cumulative_capacity} through pot index"
                    f" {pot.pot_index}"
                )
    if (
        collection_ceiling is not None
        and known_player_collections > collection_ceiling
    ):
        errors.append(
            f"known player collections {known_player_collections} exceed known"
            f" distributable pot {collection_ceiling}"
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
        if resolved is not None and resolved > prior:
            errors.append("uncalled return cannot increase total_committed")
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

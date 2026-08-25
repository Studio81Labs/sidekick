from app.domain.poker import Card
from app.solvers.ev_solver_cli import _sample_prefix_outcomes


class RecordingRandom:
    def __init__(self) -> None:
        self.sampled_populations: list[list[str]] = []

    def sample(self, population: list[Card], count: int) -> list[Card]:
        self.sampled_populations.append([card.code for card in population])
        return population[:count]


def test_prefix_outcomes_release_cards_from_nonparticipating_opponents() -> None:
    cards = {
        code: Card.from_code(code)
        for code in (
            "Ah",
            "As",
            "2c",
            "3d",
            "4h",
            "5s",
            "Kc",
            "Kd",
            "Qc",
            "Qd",
            "6c",
            "7c",
        )
    }
    rng = RecordingRandom()

    outcomes = _sample_prefix_outcomes(
        hero_cards=[cards["Ah"], cards["As"]],
        board_cards=[cards[code] for code in ("2c", "3d", "4h", "5s")],
        deck=[cards[code] for code in ("Kc", "Kd", "Qc", "Qd", "6c", "7c")],
        opponent_hands=[
            [cards["Kc"], cards["Kd"]],
            [cards["Qc"], cards["Qd"]],
        ],
        board_needed=1,
        rng=rng,  # type: ignore[arg-type]
    )

    assert outcomes == {1: 1.0, 2: 1 / 3}
    assert rng.sampled_populations == [
        ["Qc", "Qd", "6c", "7c"],
        ["6c", "7c"],
    ]

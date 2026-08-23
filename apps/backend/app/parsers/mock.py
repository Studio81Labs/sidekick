from pathlib import Path

from app.domain.poker import Card
from app.models import DetectedState, ParserResult


class MockParser:
    name = "mock"

    def parse(self, image_path: Path) -> ParserResult:
        return ParserResult(
            state=DetectedState(
                hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
                board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
                pot_size=12.5,
                current_bet=2.5,
                hero_stack=97.5,
                effective_stack=96.0,
                players_in_hand=3,
                hero_position="button",
                street="flop",
                facing_action="bet",
                action_context="Cutoff bet 2.5 into 12.5",
            ),
            confidences={
                "hero_cards": 0.99,
                "board_cards": 0.98,
                "pot_size": 0.92,
                "current_bet": 0.9,
                "hero_stack": 0.89,
                "effective_stack": 0.88,
                "players_in_hand": 0.93,
                "hero_position": 0.87,
                "street": 1.0,
                "facing_action": 0.9,
            },
            warnings=[],
            raw={
                "provider": self.name,
                "image_filename": image_path.name,
            },
        )

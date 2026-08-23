from __future__ import annotations

import sys

from pydantic import ValidationError

from app.domain.recommendations import RecommendationRequest, RecommendationResult
from app.providers.rule_based import RuleBasedTrainingProvider

RULE_BASED_SUFFIX = " This is a rule-based training recommendation, not a solver output."
LOCAL_SOLVER_SUFFIX = (
    " This comes from the bundled local baseline solver adapter; it is for training, not a GTO solve."
)


def recommend(raw_request: str) -> RecommendationResult:
    request = RecommendationRequest.model_validate_json(raw_request)
    result = RuleBasedTrainingProvider().recommend(request)
    explanation = result.explanation.replace(RULE_BASED_SUFFIX, LOCAL_SOLVER_SUFFIX)
    raw = {
        **result.raw,
        "provider": "local_solver",
        "engine": "bundled_rule_based_cli_v1",
        "delegate_provider": result.raw.get("provider"),
        "delegate_engine": result.raw.get("engine"),
        "process_boundary": "stdin_stdout_json",
    }
    return RecommendationResult(
        action=result.action,
        sizing=result.sizing,
        confidence=result.confidence,
        explanation=explanation,
        raw=raw,
    )


def main() -> int:
    try:
        result = recommend(sys.stdin.read())
    except ValidationError as exc:
        print(f"Invalid solver request: {exc}", file=sys.stderr)
        return 2

    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

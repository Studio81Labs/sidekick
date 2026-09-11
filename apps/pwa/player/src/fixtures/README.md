# Player recorded-state fixtures

`recordedHandState.json` is the sanitized JSON-mode
`PlayerHandDetail.canonical_revisions[].state` projection generated from the
backend's `baseline_decision_record` fixture. It deliberately contains no raw
source excerpts. The timeline and API-contract tests use it to keep the PWA
read model aligned with a backend-produced state rather than a hand-written
frontend shape.

Refresh it from the repository root with:

```sh
cd apps/backend
PYTHONPATH=tests .venv/bin/python - <<'PY'
import json
from app.player_hands import project_player_hand
from app.storage.imported_hand_store import imported_hand_record_key
from test_imported_hand_decisions import baseline_decision_record

record = baseline_decision_record()
detail = project_player_hand(imported_hand_record_key(record.identity), record)
print(json.dumps(detail.canonical_revisions[0].state, indent=2, sort_keys=True))
PY
```

#!/usr/bin/env python3
"""Export the backend OpenAPI document using isolated, empty application data."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "backend"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages" / "openapi" / "openapi.json"

sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import create_openapi_document  # noqa: E402
from app.config import Settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="OpenAPI JSON output path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with TemporaryDirectory(prefix="poker-hero-openapi-") as temporary_directory:
        document = create_openapi_document(
            Settings(
                data_dir=Path(temporary_directory) / "data",
                mcp_enabled=False,
                sentry_dsn=None,
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check shared workflow naming, pinning, reusable calls, and required contexts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml


ACTION = re.compile(r"^[^@\s]+@[a-f0-9]{40}$")
REQUIRED = {
    ("lint-pr.yml", "validate"): "Validate PR title",
    ("format-check.yml", "format"): "ci: formatting",
    ("pwa-ci.yml", "gate"): "pwa: gate",
    ("openapi-check.yml", "gate"): "contract: gate",
    ("security-scan.yml", "secrets"): "security: secrets",
    ("security-scan.yml", "dependencies"): "security: dependencies",
    ("security-scan.yml", "code"): "security: code (semgrep)",
}


def validate_workflow(path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    try:
        document = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as error:
        return [f"{path}: invalid YAML: {error}"]

    jobs = document.get("jobs") or {}
    if not isinstance(jobs, dict):
        return [f"{path}: jobs must be a mapping"]

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        name = job.get("name")
        # Reusable workflow callers already supply the area-prefixed check
        # name. Keeping an inner job unnamed renders the accurate bare job id
        # (for example, `contract: openapi spec / export`) instead of a doubled
        # area. All directly triggered workflows still require an explicit
        # area/proof name.
        if name is None and not path.name.startswith("_"):
            errors.append(f"{path}:{job_id}: job name must use '<area>: <proof>'")
        elif name is not None and name != "Validate PR title" and ": " not in str(name):
            errors.append(f"{path}:{job_id}: job name must use '<area>: <proof>'")

        reusable = job.get("uses")
        if isinstance(reusable, str) and reusable.startswith("./"):
            target = root / reusable.removeprefix("./")
            if not target.is_file():
                errors.append(f"{path}:{job_id}: missing reusable workflow {reusable}")

        for step in job.get("steps") or []:
            if not isinstance(step, dict) or "uses" not in step:
                continue
            action = str(step["uses"])
            if action.startswith("./"):
                continue
            if not ACTION.fullmatch(action):
                errors.append(f"{path}:{job_id}: action is not pinned to a full SHA: {action}")

    return errors


def validate_tree(root: Path) -> list[str]:
    workflow_dir = root / ".github/workflows"
    errors: list[str] = []
    documents: dict[str, dict] = {}
    for path in sorted(workflow_dir.glob("*.yml")):
        errors.extend(validate_workflow(path, root))
        documents[path.name] = yaml.safe_load(path.read_text()) or {}

    for key, expected in REQUIRED.items():
        filename, job_id = key
        actual = ((documents.get(filename, {}).get("jobs") or {}).get(job_id) or {}).get("name")
        if actual != expected:
            errors.append(f"{filename}:{job_id}: expected required context {expected!r}, got {actual!r}")

    for filename in ("pwa-ci.yml", "openapi-check.yml", "format-check.yml", "security-scan.yml"):
        raw = (workflow_dir / filename).read_text()
        pull_request_block = raw.split("pull_request:", 1)[-1].split("permissions:", 1)[0]
        if re.search(r"^\s+paths:", pull_request_block, re.MULTILINE):
            errors.append(f"{filename}: required workflow must not use pull-request path filters")

    combined = "\n".join(path.read_text() for path in workflow_dir.glob("*.yml"))
    if "pnpm dlx" in combined or "wrangler@latest" in combined or "npx --yes @sentry/cli" in combined:
        errors.append("deployment workflows contain a floating CLI invocation")
    deploy_workflow = (workflow_dir / "pwa-deploy.yml").read_text()
    if "pnpm --workspace-root exec wrangler deploy" in deploy_workflow and (
        "--config apps/pwa/wrangler.jsonc" not in deploy_workflow
    ):
        errors.append("root-scoped Wrangler deploy must use the repository-relative PWA config path")
    ci_scripts = (workflow_dir / "ci-scripts.yml").read_text()
    if len(re.findall(r'^\s+- "\.github/workflows/\*\*"$', ci_scripts, re.MULTILINE)) != 2:
        errors.append("CI script policy checks must run for every workflow change")
    if not re.search(
        r"^\s+run: python3 scripts/ci/check-container-pins\.py\s*$",
        ci_scripts,
        re.MULTILINE,
    ):
        errors.append("CI must scan repository container pins after running the fixture self-test")
    listed = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
        text=True,
    ).splitlines()
    deprecated_compose = "infra/docker/" + "compose.yaml"
    if deprecated_compose in "\n".join(
        (root / relative).read_text(errors="ignore")
        for relative in listed
        if (root / relative).is_file()
        and not relative.startswith("docs/specs/")
    ):
        errors.append("deprecated Compose path remains")
    return errors


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workflow = root / ".github/workflows/test.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "jobs:\n  test:\n    name: 'ci: test'\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: actions/checkout@" + "a" * 40 + "\n"
        )
        assert validate_workflow(workflow, root) == []
        workflow.write_text("jobs:\n  test:\n    name: test\n    steps:\n      - uses: actions/checkout@v7\n")
        errors = validate_workflow(workflow, root)
        assert len(errors) == 2, errors
        reusable = workflow.with_name("_reusable.yml")
        reusable.write_text("jobs:\n  export:\n    runs-on: ubuntu-latest\n")
        assert validate_workflow(reusable, root) == []
        direct = workflow.with_name("direct.yml")
        direct.write_text("jobs:\n  export:\n    runs-on: ubuntu-latest\n")
        assert len(validate_workflow(direct, root)) == 1
    print("check-workflow-policy self-test passed")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return self_test()
    root = Path(__file__).resolve().parents[2]
    errors = validate_tree(root)
    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1
    print("Workflow policy verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

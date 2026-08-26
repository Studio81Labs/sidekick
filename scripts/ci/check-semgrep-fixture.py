#!/usr/bin/env python3
# ported from Studio81Labs/nexcue@55091c8
"""Verify semgrep findings against the ``ruleid:`` / ``ok:`` annotations in a fixture.

Why this exists rather than a count comparison: comparing totals passes when one
expected line stops matching and one ``ok:`` line starts, which is exactly the
regression the negative cases are for. It also passes a rule that fires on
everything, as long as the number happens to line up. Only a per-line comparison
checks what the annotations claim.

``semgrep --test`` is the documented tool for this and does not work here: it
reports "No unit tests found" for a correctly placed Dart fixture and exits 0,
because test discovery keys off the rule's language and Dart is Experimental.

Annotations follow semgrep's convention -- the comment sits on the line directly
above the code it describes:

    // ruleid: some-rule      the next line MUST produce a finding for some-rule
    // ok: some-rule          the next line must NOT produce one for some-rule

Usage:
    check-semgrep-fixture.py <semgrep-json> <fixture-file> <rules-file>
    check-semgrep-fixture.py --self-test
"""

from __future__ import annotations

import json
import re
import sys

ANNOTATION = re.compile(r"//\s*(ruleid|ok):\s*(?P<rule>[\w.-]+)\s*$")


def parse_annotations(text: str) -> tuple[set[tuple[int, str]], set[tuple[int, str]]]:
    """Return (expected, forbidden) as {(line, rule)} for the annotated lines.

    The line recorded is the one the annotation refers to -- the next line -- not
    the comment's own line. Consecutive annotations stack, so a line may carry
    several rules.
    """
    expected: set[tuple[int, str]] = set()
    forbidden: set[tuple[int, str]] = set()
    pending: list[tuple[str, str]] = []

    for lineno, raw in enumerate(text.splitlines(), start=1):
        match = ANNOTATION.search(raw)
        if match:
            pending.append((match.group(1), match.group("rule")))
            continue
        if not pending:
            continue
        if raw.strip():
            for kind, rule in pending:
                (expected if kind == "ruleid" else forbidden).add((lineno, rule))
            pending = []
    return expected, forbidden


def parse_findings(report: dict, fixture_name: str) -> set[tuple[int, str]]:
    """Return {(line, rule)} for findings in the fixture."""
    out: set[tuple[int, str]] = set()
    for result in report.get("results", []):
        path = result.get("path", "")
        if fixture_name not in path:
            continue
        out.add((int(result["start"]["line"]), str(result["check_id"]).split(".")[-1]))
    return out


def compare(expected, forbidden, actual) -> list[str]:
    problems = []
    for line, rule in sorted(expected - actual):
        problems.append(f"line {line}: expected {rule} to match, it did not")
    for line, rule in sorted(forbidden & actual):
        problems.append(f"line {line}: {rule} matched an `ok:` line")
    # Every actual pair must be one that was expected. Keying the check on the
    # LINE instead let a different rule fire on an annotated line unnoticed --
    # expected {(10, 'rule-a')} against actual {(10, 'rule-a'), (10, 'rule-b')}
    # compared cleanly, which is precisely how a broadened rule's cross-rule
    # false positive would slip through.
    for line, rule in sorted(actual - expected):
        if (line, rule) in forbidden:
            continue  # already reported above, with a clearer message
        problems.append(f"line {line}: unexpected {rule}")
    return problems


RULE_ID = re.compile(r"^\s*-\s*id:\s*(?P<id>[\w.-]+)\s*$")


def parse_rule_ids(text: str) -> set[str]:
    """Rule ids declared in a semgrep rule file.

    Read with a regex rather than a YAML parser on purpose: this script runs in
    security-scan.yml, which installs nothing, and adding PyYAML there to read
    three `- id:` lines would trade a real dependency for no benefit.
    """
    return {m.group("id") for line in text.splitlines() if (m := RULE_ID.match(line))}


def self_test() -> int:
    fixture = "\n".join(
        [
            "// header",
            "// ruleid: rule-a",
            "code_that_matches();",
            "// ok: rule-a",
            "code_that_must_not_match();",
            "",
            "// ruleid: rule-b",
            "",
            "another_match();",
        ]
    )
    expected, forbidden = parse_annotations(fixture)
    assert expected == {(3, "rule-a"), (9, "rule-b")}, expected
    assert forbidden == {(5, "rule-a")}, forbidden

    assert compare(expected, forbidden, {(3, "rule-a"), (9, "rule-b")}) == []

    missing = compare(expected, forbidden, {(9, "rule-b")})
    assert missing == ["line 3: expected rule-a to match, it did not"], missing

    false_pos = compare(expected, forbidden, {(3, "rule-a"), (5, "rule-a"), (9, "rule-b")})
    assert false_pos == ["line 5: rule-a matched an `ok:` line"], false_pos

    # The failure a count comparison cannot see: one expected line stops
    # matching while one forbidden line starts. Totals are unchanged.
    swapped = compare(expected, forbidden, {(5, "rule-a"), (9, "rule-b")})
    assert len(swapped) == 2, swapped

    stray = compare(expected, forbidden, {(3, "rule-a"), (9, "rule-b"), (99, "rule-c")})
    assert stray == ["line 99: unexpected rule-c"], stray

    # A different rule firing on an ANNOTATED line must not be waved through.
    cross = compare(expected, forbidden, {(3, "rule-a"), (3, "rule-b"), (9, "rule-b")})
    assert cross == ["line 3: unexpected rule-b"], cross

    rules = parse_rule_ids(
        "rules:\n  - id: rule-a\n    languages: [dart]\n  - id: rule-b\n"
    )
    assert rules == {"rule-a", "rule-b"}, rules

    print("check-semgrep-fixture self-test passed")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--self-test":
        return self_test()
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2

    report_path, fixture_path, rules_path = argv[1], argv[2], argv[3]
    with open(report_path, encoding="utf-8") as handle:
        report = json.load(handle)
    with open(fixture_path, encoding="utf-8") as handle:
        fixture = handle.read()

    with open(rules_path, encoding="utf-8") as handle:
        rule_ids = parse_rule_ids(handle.read())

    expected, forbidden = parse_annotations(fixture)
    if not expected:
        print(
            f"::error::{fixture_path} has no `ruleid:` annotations — nothing is being verified",
            file=sys.stderr,
        )
        return 1

    # Every configured rule needs at least one positive annotation. Without this
    # a rule added later with no fixture -- the likeliest way a Dart rule ends up
    # matching nothing -- rides on the existing annotations and CI stays green.
    unfixtured = sorted(rule_ids - {rule for _, rule in expected})
    if unfixtured:
        for rule in unfixtured:
            print(
                f"::error::{rule} is declared in {rules_path} but has no `ruleid:` "
                f"annotation in {fixture_path}",
                file=sys.stderr,
            )
        return 1

    actual = parse_findings(report, fixture_path.rsplit("/", 1)[-1])
    problems = compare(expected, forbidden, actual)

    print(
        f"  fixture: {len(expected)} expected, {len(forbidden)} negative, "
        f"{len(actual)} finding(s)"
    )
    if problems:
        for problem in problems:
            print(f"::error::{fixture_path} {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

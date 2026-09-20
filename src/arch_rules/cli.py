"""arch-rules check - the same rules, outside pytest."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from arch_rules.core import RulesError, files_in_scope, load

EXIT_VIOLATIONS = 1
EXIT_BAD_RULES = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arch-rules", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="report every violation of the rules file")
    check.add_argument("rules", nargs="?", default="arch-rules.toml", type=Path)
    check.add_argument("--root", type=Path, default=None, help="what scopes are relative to")
    check.add_argument("--json", action="store_true", dest="as_json")

    listing = sub.add_parser("list", help="print the rules and what each one forbids")
    listing.add_argument("rules", nargs="?", default="arch-rules.toml", type=Path)
    return parser


def _check(args: argparse.Namespace) -> int:
    ruleset = load(args.rules, args.root)
    violations = ruleset.check()
    if args.as_json:
        print(json.dumps([asdict(v) for v in violations], indent=2))
    else:
        for violation in violations:
            print(violation)
        if violations:
            # The summary goes to stderr; without this it lands above the list
            # it summarises whenever stdout is a pipe.
            sys.stdout.flush()
            described = {rule.id: rule.description for rule in ruleset.rules}
            print(f"\n{len(violations)} violation(s):", file=sys.stderr)
            for rid in sorted({v.rule for v in violations}):
                print(f"  {rid}: {described.get(rid) or '(no description)'}", file=sys.stderr)
        else:
            print(f"{len(ruleset.rules)} rule(s), no violations")
    return EXIT_VIOLATIONS if violations else 0


def _list(args: argparse.Namespace) -> int:
    ruleset = load(args.rules)
    for rule in ruleset.rules:
        covered = len(files_in_scope(rule, ruleset.root))
        # The count is the answer to "is this rule actually looking at
        # anything": a renamed directory leaves a rule guarding zero files.
        print(f"{rule.id} ({covered} file(s)): {rule.description or 'no description'}")
        for entry in rule.scope:
            print(f"  scope     {entry}")
        for module in (*rule.forbidden_imports, *rule.may_not_import):
            print(f"  no import {module}")
        for pattern in rule.forbidden_patterns:
            print(f"  no text   {pattern!r}")
        if rule.forbidden_regex:
            print(f"  no match  {rule.forbidden_regex!r}")
        for pattern in rule.required_patterns:
            print(f"  requires  {pattern!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _check(args) if args.command == "check" else _list(args)
    except (RulesError, OSError) as exc:
        # A rules file that cannot be read is not "no violations".
        print(f"arch-rules: {exc}", file=sys.stderr)
        return EXIT_BAD_RULES


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

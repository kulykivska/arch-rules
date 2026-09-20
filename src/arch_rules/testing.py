"""One line in your test suite, so the rules run where the tests run."""

from __future__ import annotations

from pathlib import Path

from arch_rules.core import load


def assert_no_violations(
    rules: Path | str = "arch-rules.toml", root: Path | str | None = None
) -> None:
    """Fail with every violation listed, not just the first.

    The point is a reviewable diff: a person adding a forbidden import should
    see which rule they broke and why it exists, in the test output.
    """
    path = Path(rules)
    ruleset = load(path, Path(root) if root is not None else None)
    violations = ruleset.check()
    if violations:
        described = {rule.id: rule.description for rule in ruleset.rules}
        lines = [f"{len(violations)} architecture violation(s):"]
        lines += [f"  {v}" for v in violations]
        broken = sorted({v.rule for v in violations})
        lines += [f"\n{rid}: {described[rid]}" for rid in broken if described.get(rid)]
        raise AssertionError("\n".join(lines))

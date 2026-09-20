"""Architecture rules that are checked rather than remembered.

Every codebase has rules nobody wrote down: this layer may not import that one,
no LLM call on the recording path, no browser session ever persisted. They hold
until the day someone new - or someone tired - does the obvious thing. A rule
in a file that a test reads is a rule that survives that day.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# What a scope means by "a file", unless a rule says otherwise.
DEFAULT_SUFFIXES = (
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".j2",
    ".feature",
    ".example",
    ".sh",
)


class RulesError(ValueError):
    """The rules file itself is wrong."""


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: [{self.rule}] {self.detail}"


@dataclass(frozen=True)
class Rule:
    id: str
    description: str = ""
    scope: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = DEFAULT_SUFFIXES
    forbidden_imports: tuple[str, ...] = ()
    # Internal module prefixes this scope may not import: the layering rule.
    may_not_import: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    forbidden_regex: str = ""
    required_patterns: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> Rule:
        if not isinstance(data, dict) or "id" not in data:
            raise RulesError(f"a rule must be a table with an id, not {data!r}")
        rule_id = str(data["id"])
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            # A misspelled key is a rule that silently checks nothing, which is
            # worse than no rule at all.
            raise RulesError(f"rule {rule_id}: unknown key(s) {sorted(unknown)}")
        rule = cls(
            id=rule_id,
            description=str(data.get("description", "")),
            scope=_strings(rule_id, data, "scope"),
            exclude=_strings(rule_id, data, "exclude"),
            suffixes=_strings(rule_id, data, "suffixes", DEFAULT_SUFFIXES),
            forbidden_imports=_strings(rule_id, data, "forbidden_imports"),
            may_not_import=_strings(rule_id, data, "may_not_import"),
            forbidden_patterns=_strings(rule_id, data, "forbidden_patterns"),
            forbidden_regex=str(data.get("forbidden_regex", "")),
            required_patterns=_strings(rule_id, data, "required_patterns"),
        )
        rule.validate()
        return rule

    def validate(self) -> None:
        """Refuse every shape that would pass forever without checking anything."""
        if not self.scope:
            raise RulesError(f"rule {self.id}: no scope, so it looks at no files")
        if self.checks_nothing():
            raise RulesError(f"rule {self.id}: forbids nothing, so it would always pass")
        bad = [s for s in self.suffixes if not s.startswith(".")]
        if bad:
            # ["py"] matches no file at all, quietly.
            raise RulesError(f"rule {self.id}: suffixes must start with a dot: {bad}")
        if self.forbidden_regex:
            try:
                re.compile(self.forbidden_regex)
            except re.error as exc:
                raise RulesError(
                    f"rule {self.id}: forbidden_regex is not valid: {exc}"
                ) from exc

    def checks_nothing(self) -> bool:
        return not (
            self.forbidden_imports
            or self.may_not_import
            or self.forbidden_patterns
            or self.forbidden_regex
            or self.required_patterns
        )


def _strings(
    rule_id: str, data: dict[str, Any], key: str, default: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """A list of strings, never a string.

    `scope = "src"` is the mistake this exists for: iterating it gives three
    one-letter paths, matches nothing, and reports green.
    """
    value = data.get(key, default)
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise RulesError(f"rule {rule_id}: {key} must be a list of strings, not {value!r}")
    if not all(isinstance(item, str) for item in value):
        raise RulesError(f"rule {rule_id}: {key} must contain only strings: {list(value)!r}")
    return tuple(value)


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)
    root: Path = Path()

    def check(self) -> list[Violation]:
        violations: list[Violation] = []
        for rule in self.rules:
            violations.extend(_check_rule(rule, self.root))
        return sorted(violations, key=lambda v: (v.path, v.line, v.rule))


def load(path: Path, root: Path | None = None) -> RuleSet:
    """Read rules from TOML, or from YAML when pyyaml is installed."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        try:
            import yaml  # noqa: PLC0415 - optional, only for YAML rule files
        except ImportError as exc:
            raise RulesError(
                f"{path} is YAML; install arch-rules[yaml] or write the rules in TOML"
            ) from exc
        data = yaml.safe_load(text) or {}
    else:
        data = tomllib.loads(text)
    if not isinstance(data, dict):
        raise RulesError(f"{path} is not a table of rules")
    raw = data.get("rules")
    if not isinstance(raw, list) or not raw:
        raise RulesError(f"{path} has no rules")
    rules = [Rule.from_dict(item) for item in raw]
    duplicated = sorted({r.id for r in rules if [x.id for x in rules].count(r.id) > 1})
    if duplicated:
        # Two rules with one id: the report cannot say which one broke.
        raise RulesError(f"{path}: duplicate rule id(s) {duplicated}")
    return RuleSet(rules=rules, root=root or path.parent)


def files_in_scope(rule: Rule, root: Path) -> list[Path]:
    """Every file the rule looks at, once each.

    Overlapping scopes - "src" and "src/core" in the same rule - would
    otherwise report the same line twice.
    """
    found: dict[str, Path] = {}
    for entry in rule.scope:
        target = root / entry
        if target.is_file():
            found[str(target)] = target
        elif target.is_dir():
            for file in sorted(target.rglob("*")):
                if file.is_file() and file.suffix in rule.suffixes:
                    found[str(file)] = file
    return [f for f in sorted(found.values()) if not _excluded(f, root, rule.exclude)]


def _relative(path: Path, root: Path) -> str:
    """How to name this file in a report. An absolute scope entry puts the file
    outside the root, and then its own path is the only name it has."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _excluded(path: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    relative = _relative(path, root)
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def _check_rule(rule: Rule, root: Path) -> list[Violation]:
    violations: list[Violation] = []
    imports = {
        module: re.compile(rf"^\s*(?:import|from)\s+{re.escape(module)}\b", re.M)
        for module in (*rule.forbidden_imports, *rule.may_not_import)
    }
    compiled = re.compile(rule.forbidden_regex) if rule.forbidden_regex else None
    for path in files_in_scope(rule, root):
        relative = _relative(path, root)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            # A file in scope that cannot be read is not a clean file.
            violations.append(Violation(rule.id, relative, 0, f"could not be read: {exc}"))
            continue
        lines = text.splitlines()

        for module, pattern in imports.items():
            for match in pattern.finditer(text):
                violations.append(
                    Violation(
                        rule.id, relative, _line_of(text, match.start()), f"imports {module}"
                    )
                )
        for needle in rule.forbidden_patterns:
            for number, line in enumerate(lines, start=1):
                if needle in line:
                    violations.append(
                        Violation(rule.id, relative, number, f"contains {needle!r}")
                    )
        if compiled is not None:
            for number, line in enumerate(lines, start=1):
                if compiled.search(line):
                    violations.append(
                        Violation(
                            rule.id, relative, number, f"matches {rule.forbidden_regex!r}"
                        )
                    )
        for needle in rule.required_patterns:
            if needle not in text:
                violations.append(Violation(rule.id, relative, 0, f"is missing {needle!r}"))
    return violations


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1

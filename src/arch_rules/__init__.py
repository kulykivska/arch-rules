"""Architecture rules as a file your tests read."""

from arch_rules.core import (
    DEFAULT_SUFFIXES,
    Rule,
    RulesError,
    RuleSet,
    Violation,
    files_in_scope,
    load,
)
from arch_rules.testing import assert_no_violations

__all__ = [
    "DEFAULT_SUFFIXES",
    "Rule",
    "RuleSet",
    "RulesError",
    "Violation",
    "assert_no_violations",
    "files_in_scope",
    "load",
]
__version__ = "0.1.0"

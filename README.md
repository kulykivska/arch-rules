# arch-rules

[![ci](https://github.com/kulykivska/arch-rules/actions/workflows/ci.yml/badge.svg)](https://github.com/kulykivska/arch-rules/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Every codebase has rules nobody wrote down. This layer may not import that one.
No model call on the path that records evidence. No browser session ever saved
to disk. They hold right up until the day someone new — or someone tired — does
the obvious thing, and then they were never rules at all.

Put them in a file. Let the test suite read it.

```bash
pip install arch-rules
```

No dependencies.

## The file

```toml
# arch-rules.toml

[[rules]]
id = "no-llm-in-evidence-path"
description = "Recording evidence must not depend on a model being reachable."
scope = ["src/app/evidence"]
forbidden_imports = ["anthropic", "openai"]

[[rules]]
id = "core-knows-nothing-about-http"
description = "The core is called by the web layer, never the other way round."
scope = ["src/app/core"]
may_not_import = ["app.web", "fastapi", "starlette"]

[[rules]]
id = "no-cookie-persistence"
description = "A saved browser session is a credential sitting in the repo."
scope = ["src", "docs"]
forbidden_patterns = ["storage_state"]
```

## The test

```python
from arch_rules import assert_no_violations

def test_the_architecture_holds():
    assert_no_violations("arch-rules.toml")
```

When it fails, it fails with every violation at once and the reason the rule
exists:

```
2 architecture violation(s):
  src/app/evidence/log.py:2: [no-llm-in-evidence-path] imports anthropic
  src/app/evidence/digest.py:9: [no-llm-in-evidence-path] imports openai

no-llm-in-evidence-path: Recording evidence must not depend on a model being reachable.
```

That last line is the whole point. A reviewer can argue with a rule they can
read; nobody can argue with `AssertionError: False is not true`.

## Outside pytest

```bash
arch-rules check                 # exit 1 on a violation
arch-rules check --json          # for CI annotations
arch-rules list                  # what each rule forbids, in words
```

`check` exits **2** when the rules file itself is broken — missing, malformed,
or naming a key that does not exist. Exiting 0 there would read as "the rules
hold", which is the one thing it does not know.

## What a rule can say

| Key | Means |
| --- | --- |
| `scope` | files and directories the rule applies to, relative to the root |
| `exclude` | glob patterns taken back out of the scope |
| `suffixes` | what counts as a file here (default: code, docs and config) |
| `forbidden_imports` | third-party modules this scope may not import |
| `may_not_import` | your **own** modules this scope may not import — the layering rule |
| `forbidden_patterns` | text that may not appear |
| `forbidden_regex` | a pattern that may not match |
| `required_patterns` | text that must appear in every file in scope |

`forbidden_imports` and `may_not_import` do the same matching; they are
separate keys because they express different intentions, and a rules file is
read by people.

## The one it refuses to load

```toml
[[rules]]
id = "no-llm-in-evidence-path"
description = "looks like a rule"
scope = ["src/app"]
forbidden_import = ["anthropic"]     # singular: a typo
```

This raises instead of passing. A rule that forbids nothing reports green
forever, and a green check that measures nothing is worse than no check —
people stop looking at the thing it was guarding.

The same refusal covers a rule with no `scope`, `scope = "src"` written as a
string instead of a list (iterating it gives three one-letter paths), a
`suffixes` entry with no leading dot, a `forbidden_regex` that does not
compile, and two rules sharing an id.

The one it cannot refuse is a scope naming a directory that was renamed last
month — so `arch-rules list` prints how many files each rule actually covers:

```
no-llm-in-evidence-path (31 file(s)): Recording evidence must not depend on a model.
no-cookie-persistence (0 file(s)): A saved browser session is a credential.
```

That zero is the rule you thought was protecting you.

## Rules in YAML

If you already keep project config in YAML, `arch-rules check rules.yaml`
works with `pip install arch-rules[yaml]`. The TOML path uses the standard
library and pulls in nothing.

## What this is not

It is not an import graph analyzer. It does not parse your AST, resolve
`__init__` re-exports, or find a cycle three modules deep — [import-linter]
does that, and does it properly. This reads text, so it also covers the rules
that are not about imports at all: a pattern in a template, a word in a
migration, a missing `downgrade`.

The tradeoff is deliberate. The rules that get written down are the ones that
take two lines to write.

[import-linter]: https://github.com/seddonym/import-linter

## License

MIT.

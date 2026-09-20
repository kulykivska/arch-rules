"""What a rules file must catch, and what it must not.

The failure mode that matters is not a missed violation - it is a rule that
quietly checks nothing and reports green for a year.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arch_rules import RulesError, assert_no_violations, load
from arch_rules.cli import main


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


RULES = """
[[rules]]
id = "no-llm-in-evidence-path"
description = "Recording evidence must not depend on a model being reachable."
scope = ["app/evidence"]
forbidden_imports = ["anthropic", "openai"]
"""


def test_a_forbidden_import_is_reported_with_its_line(tmp_path: Path) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "import json\nimport anthropic\n")
    violations = load(tmp_path / "arch-rules.toml").check()
    assert len(violations) == 1
    assert violations[0].path == "app/evidence/log.py"
    assert violations[0].line == 2
    assert violations[0].rule == "no-llm-in-evidence-path"


def test_from_imports_count_too(tmp_path: Path) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "from anthropic import Anthropic\n")
    assert len(load(tmp_path / "arch-rules.toml").check()) == 1


def test_a_similar_name_is_not_the_forbidden_module(tmp_path: Path) -> None:
    """`import openai_is_not_used_here` must not trip a rule about `openai`."""
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "import openailike\nimport anthropic_stub\n")
    assert load(tmp_path / "arch-rules.toml").check() == []


def test_the_module_is_allowed_outside_the_scope(tmp_path: Path) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/digest/classify.py", "import anthropic\n")
    assert load(tmp_path / "arch-rules.toml").check() == []


def test_a_word_in_a_comment_is_not_an_import(tmp_path: Path) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "# we deliberately do not import anthropic here\n")
    assert load(tmp_path / "arch-rules.toml").check() == []


def test_layering_names_the_project_own_modules(tmp_path: Path) -> None:
    """The rule `forbidden_imports` cannot express: the core may not reach up
    into the web layer, and nothing about third-party packages says so."""
    write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "core-knows-nothing-about-http"
description = "The core is called by the web layer, never the other way round."
scope = ["app/core"]
may_not_import = ["app.web", "fastapi"]
""",
    )
    write(tmp_path, "app/core/runs.py", "from app.web.routes import router\n")
    write(tmp_path, "app/web/routes.py", "from app.core.runs import start\n")
    violations = load(tmp_path / "arch-rules.toml").check()
    assert [v.path for v in violations] == ["app/core/runs.py"]


def test_forbidden_text_is_found_in_any_scoped_file(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "no-cookie-persistence"
description = "A saved browser session is a credential in the repo."
scope = ["app", "docs"]
forbidden_patterns = ["storage_state"]
""",
    )
    write(tmp_path, "app/capture.py", "ctx = browser.new_context(storage_state='s.json')\n")
    write(tmp_path, "docs/capture.md", "We never pass storage_state.\n")
    violations = load(tmp_path / "arch-rules.toml").check()
    assert {v.path for v in violations} == {"app/capture.py", "docs/capture.md"}


def test_a_regex_rule_reports_the_matching_line(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        r"""
[[rules]]
id = "no-secrets-in-repo"
description = "Keys belong in the environment."
scope = ["app"]
forbidden_regex = "(?i)(api[_-]?key|secret)\\s*=\\s*[\"'][^\"']{8,}"
""",
    )
    write(
        tmp_path,
        "app/conf.py",
        "import os\nAPI_KEY = os.environ['K']\nsecret = 'hunter2hunter2'\n",
    )
    violations = load(tmp_path / "arch-rules.toml").check()
    assert [v.line for v in violations] == [3]


def test_a_required_pattern_is_reported_when_missing(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "migrations-are-reversible"
description = "Every migration has a downgrade."
scope = ["migrations"]
required_patterns = ["def downgrade"]
""",
    )
    write(tmp_path, "migrations/0001.py", "def upgrade():\n    pass\n")
    write(
        tmp_path,
        "migrations/0002.py",
        "def upgrade():\n    pass\n\ndef downgrade():\n    pass\n",
    )
    violations = load(tmp_path / "arch-rules.toml").check()
    assert [v.path for v in violations] == ["migrations/0001.py"]
    assert violations[0].line == 0


def test_exclude_takes_a_file_out_of_the_scope(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "no-llm-in-evidence-path"
description = "Recording must not need a model."
scope = ["app/evidence"]
exclude = ["app/evidence/experimental/*"]
forbidden_imports = ["anthropic"]
""",
    )
    write(tmp_path, "app/evidence/experimental/try.py", "import anthropic\n")
    write(tmp_path, "app/evidence/log.py", "import anthropic\n")
    violations = load(tmp_path / "arch-rules.toml").check()
    assert [v.path for v in violations] == ["app/evidence/log.py"]


def test_suffixes_decide_what_counts_as_a_file(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "python-only"
description = "Only the code, not the fixtures beside it."
scope = ["app"]
suffixes = [".py"]
forbidden_patterns = ["TODO"]
""",
    )
    write(tmp_path, "app/x.py", "# TODO\n")
    write(tmp_path, "app/notes.md", "TODO\n")
    assert [v.path for v in load(tmp_path / "arch-rules.toml").check()] == ["app/x.py"]


def test_a_single_file_can_be_its_own_scope(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "readme-mentions-the-licence"
description = "People need to know before they copy it."
scope = ["README.md"]
required_patterns = ["## License"]
""",
    )
    write(tmp_path, "README.md", "# thing\n")
    assert len(load(tmp_path / "arch-rules.toml").check()) == 1


def test_a_rule_that_forbids_nothing_is_refused(tmp_path: Path) -> None:
    """The quiet failure: a rule with a typo'd key passes forever."""
    path = write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "no-llm-in-evidence-path"
description = "looks like a rule, checks nothing"
scope = ["app"]
""",
    )
    with pytest.raises(RulesError, match="forbids nothing"):
        load(path)


def test_an_unknown_key_is_refused_by_name(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "arch-rules.toml",
        """
[[rules]]
id = "typo"
scope = ["app"]
forbidden_import = ["anthropic"]
""",
    )
    with pytest.raises(RulesError, match="forbidden_import"):
        load(path)


def test_a_rules_file_with_no_rules_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, "arch-rules.toml", "title = 'nothing here'\n")
    with pytest.raises(RulesError, match="no rules"):
        load(path)


def test_scopes_are_relative_to_the_root_not_the_rules_file(tmp_path: Path) -> None:
    write(tmp_path, "config/arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "import anthropic\n")
    assert load(tmp_path / "config" / "arch-rules.toml").check() == []
    assert len(load(tmp_path / "config" / "arch-rules.toml", root=tmp_path).check()) == 1


def test_a_missing_scope_is_not_an_error(tmp_path: Path) -> None:
    """A directory a rule guards may not exist yet; that is not a violation and
    not a crash."""
    write(tmp_path, "arch-rules.toml", RULES)
    assert load(tmp_path / "arch-rules.toml").check() == []


def test_the_assert_helper_names_every_violation_and_the_reason(tmp_path: Path) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/a.py", "import anthropic\n")
    write(tmp_path, "app/evidence/b.py", "import openai\n")
    with pytest.raises(AssertionError) as caught:
        assert_no_violations(tmp_path / "arch-rules.toml")
    message = str(caught.value)
    assert "app/evidence/a.py:1" in message
    assert "app/evidence/b.py:1" in message
    assert "must not depend on a model being reachable" in message


def test_the_assert_helper_is_silent_when_the_rules_hold(tmp_path: Path) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "import json\n")
    assert_no_violations(tmp_path / "arch-rules.toml")


# --- the CLI --------------------------------------------------------------


def test_check_exits_one_on_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "import anthropic\n")
    assert main(["check", str(tmp_path / "arch-rules.toml")]) == 1
    out = capsys.readouterr()
    assert "app/evidence/log.py:1" in out.out
    assert "no-llm-in-evidence-path" in out.err


def test_check_exits_zero_when_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    assert main(["check", str(tmp_path / "arch-rules.toml")]) == 0
    assert "no violations" in capsys.readouterr().out


def test_a_broken_rules_file_exits_two_not_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 0 here would read as "the rules hold", which is the one thing it
    does not know."""
    assert main(["check", str(tmp_path / "absent.toml")]) == 2
    assert "arch-rules:" in capsys.readouterr().err


def test_json_output_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    write(tmp_path, "arch-rules.toml", RULES)
    write(tmp_path, "app/evidence/log.py", "import anthropic\n")
    main(["check", str(tmp_path / "arch-rules.toml"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["rule"] == "no-llm-in-evidence-path"
    assert payload[0]["line"] == 1


def test_list_prints_what_each_rule_forbids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "arch-rules.toml", RULES)
    assert main(["list", str(tmp_path / "arch-rules.toml")]) == 0
    out = capsys.readouterr().out
    assert "no import anthropic" in out
    assert "scope     app/evidence" in out
    assert "no-llm-in-evidence-path (0 file(s))" in out


def test_this_repo_obeys_its_own_rules() -> None:
    """The rules file in this repo is not decoration."""
    root = Path(__file__).resolve().parent.parent
    assert_no_violations(root / "arch-rules.toml", root=root)


def test_yaml_rules_load_the_same_way(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    write(
        tmp_path,
        "arch-rules.yaml",
        "rules:\n"
        "  - id: no-llm-in-evidence-path\n"
        "    description: Recording must not need a model.\n"
        "    scope: [app/evidence]\n"
        "    forbidden_imports: [anthropic]\n",
    )
    write(tmp_path, "app/evidence/log.py", "import anthropic\n")
    assert len(load(tmp_path / "arch-rules.yaml").check()) == 1


# --- the shapes that would pass forever ------------------------------------


def test_a_scope_written_as_a_string_is_refused(tmp_path: Path) -> None:
    """`scope = "src"` iterates into three one-letter paths, matches nothing,
    and reports green - the exact failure this project exists to prevent."""
    pytest.importorskip("yaml")
    path = write(
        tmp_path,
        "arch-rules.yaml",
        "rules:\n  - id: typo\n    scope: src\n    forbidden_imports: [anthropic]\n",
    )
    with pytest.raises(RulesError, match="scope must be a list of strings"):
        load(path)


def test_a_rule_with_no_scope_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "arch-rules.toml",
        '[[rules]]\nid = "nowhere"\nforbidden_imports = ["anthropic"]\n',
    )
    with pytest.raises(RulesError, match="no scope"):
        load(path)


def test_suffixes_without_a_dot_are_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "arch-rules.toml",
        '[[rules]]\nid = "x"\nscope = ["app"]\nsuffixes = ["py"]\n'
        'forbidden_patterns = ["TODO"]\n',
    )
    with pytest.raises(RulesError, match="must start with a dot"):
        load(path)


def test_a_broken_regex_is_refused_when_the_rules_load(tmp_path: Path) -> None:
    """Not halfway through the scan, with a traceback, on someone's CI."""
    path = write(
        tmp_path,
        "arch-rules.toml",
        '[[rules]]\nid = "x"\nscope = ["app"]\nforbidden_regex = "([unclosed"\n',
    )
    with pytest.raises(RulesError, match="not valid"):
        load(path)


def test_two_rules_with_one_id_are_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "arch-rules.toml",
        '[[rules]]\nid = "same"\nscope = ["app"]\nforbidden_patterns = ["a"]\n'
        '[[rules]]\nid = "same"\nscope = ["app"]\nforbidden_patterns = ["b"]\n',
    )
    with pytest.raises(RulesError, match="duplicate rule id"):
        load(path)


def test_overlapping_scopes_report_a_line_once(tmp_path: Path) -> None:
    write(
        tmp_path,
        "arch-rules.toml",
        '[[rules]]\nid = "x"\nscope = ["app", "app/evidence"]\n'
        'forbidden_imports = ["anthropic"]\n',
    )
    write(tmp_path, "app/evidence/log.py", "import anthropic\n")
    assert len(load(tmp_path / "arch-rules.toml").check()) == 1

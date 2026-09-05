"""The CI workflow's shell blocks are the command somebody meant to write.

TWICE NOW a change to `tests.yml` has produced a file that is valid YAML, passes
every schema check GitHub applies, and then fails on the runner for a reason the
log states only as an exit code.

The first time, a literal two-character `\\n` was written into the run block
instead of a newline, so the shell was handed a path that did not exist. The
second time, a test file was appended after the last line of a backslash
continuation without adding a backslash to the line above it: the `pytest`
command ended early, and the appended lines became separate commands, so bash
tried to EXECUTE `tests/test_mobile_perms_match_server.py`. A `.py` file is not
executable, which is exit code 126 - a number that appears in the log with no
explanation at all, and which arrives only AFTER pytest has run and passed.

That last detail is why this test cannot catch it in CI, and why it is still
worth having: it catches it here, before the push, which is the only place the
mistake is cheap.

What it checks is what bash would actually do with the block, not what it looks
like: continuations joined the way a shell joins them, then every resulting
command examined.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

BACKSLASH = chr(92)
WORKFLOW = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "tests.yml"


def _steps():
    """(job name, step, working directory, run block) for every step with a run."""
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job, jspec in spec["jobs"].items():
        for step in jspec.get("steps", []):
            if step.get("run"):
                yield job, step.get("name", "(unnamed)"), \
                    step.get("working-directory", "."), step["run"]


def _commands(run: str) -> list[str]:
    """What bash sees, after joining backslash continuations as a shell does."""
    joined = run.replace(BACKSLASH + "\n", " ")
    return [c.strip() for c in joined.split("\n")
            if c.strip() and not c.strip().startswith("#")]


def test_the_workflow_file_has_no_literal_backslash_n():
    """A two-character `\\n` where a newline was meant.

    It survives YAML parsing, survives GitHub's validation, and becomes part of
    an argument. The failure is a path that does not exist, reported as whatever
    the command says about a missing file.
    """
    # No `newline=` here: Path.read_text only grew that keyword in 3.13, and CI
    # runs 3.12. It is not needed anyway - universal-newline translation turns
    # CRLF into LF and can never manufacture a backslash followed by the letter
    # n, which is the whole of what this looks for.
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert BACKSLASH + "n" not in raw, (
        "tests.yml contains a literal backslash-n. It was almost certainly "
        "written by a script through a shell heredoc, which eats one level of "
        "escaping. Edit the file directly instead.")


def test_no_step_would_run_a_python_file_as_a_program():
    """Exit 126, and nothing in the log to say why.

    This is what a missing backslash on the line ABOVE looks like from the
    runner's side.
    """
    offenders = []
    for job, name, _wd, run in _steps():
        for cmd in _commands(run):
            head = cmd.split()[0]
            if head.endswith(".py") or head.startswith("tests/"):
                offenders.append(f"{job}/{name}: bash would execute {head!r}")
    assert offenders == [], (
        "a line continuation is missing, so these became separate commands:\n  "
        + "\n  ".join(offenders))


def test_every_path_a_step_names_exists():
    """A test file renamed or deleted, and the workflow still naming it.

    This has happened here too - the CI list referenced tests/test_tpath.py by
    exact path after the file was renamed.
    """
    repo = WORKFLOW.parent.parent.parent
    missing = []
    for job, name, wd, run in _steps():
        for cmd in _commands(run):
            for token in cmd.split():
                if token.startswith(("tests/", "src/")):
                    if not (repo / wd / token).exists():
                        missing.append(f"{job}/{name}: {wd}/{token}")
    assert missing == [], "the workflow names files that are not there:\n  " + \
        "\n  ".join(missing)


def test_the_pure_logic_job_runs_one_pytest_command():
    """The whole list is one invocation, not a first command and some stragglers.

    Pinned by shape rather than by count, so adding a test file is a one-line
    change that this still checks.
    """
    for job, name, _wd, run in _steps():
        if job == "tests" and "pure-logic" in name:
            cmds = _commands(run)
            assert len(cmds) == 1, (
                f"expected one pytest command, bash would see {len(cmds)}: "
                + "; ".join(c.split()[0] for c in cmds))
            assert cmds[0].startswith("pytest "), cmds[0][:60]
            files = [t for t in cmds[0].split() if t.startswith("tests/")]
            assert len(files) >= 15, (
                f"only {len(files)} test files reach pytest; a continuation is "
                "probably missing part way down the list")
            return
    pytest.fail("the pure-logic step is not in the workflow any more")


def test_every_pure_logic_test_file_is_listed():
    """A test file added to the suite but never added to CI runs nowhere.

    The two jobs that are deliberately excluded are named, so excluding a third
    is a deliberate edit here rather than an omission nobody notices.
    """
    tests_dir = Path(__file__).resolve().parent
    # These reach the live Firebase and a running API, so they cannot pass on a
    # runner; the `integration` job covers them instead.
    excluded = {"test_e2e_pipeline.py", "test_command_status.py"}

    on_disk = {p.name for p in tests_dir.glob("test_*.py")} - excluded
    listed = set()
    for job, name, _wd, run in _steps():
        if job == "tests" and "pure-logic" in name:
            listed = {os.path.basename(t) for t in _commands(run)[0].split()
                      if t.startswith("tests/")}

    unlisted = sorted(on_disk - listed)
    assert unlisted == [], (
        "these test files exist but CI never runs them: " + ", ".join(unlisted))

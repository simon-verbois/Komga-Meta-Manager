"""Exercise releases against temporary Git repositories, never the real origin."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def release_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    remote = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "init", "--initial-branch=main")
    for key, value in (("user.name", "Release Test"), ("user.email", "test@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("core.hooksPath", os.devnull)):
        git(repo, "config", key, value)
    (repo / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/release.sh", repo / "scripts/release.sh")
    (repo / "VERSION").write_text("2026.8.3\n")
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- New feature.\n\n"
        "## [2026.7.1] — 2026-02-10\n\n- Previous feature.\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")
    tools = tmp_path / "tools"
    tools.mkdir()
    date = tools / "date"
    date.write_text('#!/bin/sh\ncase "$1" in +%G) echo 2026;; +%V) echo 08;; +%F) echo 2026-02-19;; *) exit 1;; esac\n')
    date.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    return repo, remote, tmp_path


def release(repo, cwd):
    return subprocess.run([str(repo / "scripts/release.sh")], cwd=cwd, text=True, capture_output=True)


def test_release_updates_notes_version_and_pushes_matching_commit(release_repo):
    repo, remote, outside = release_repo
    git(repo, "tag", "2026.8.4")
    git(repo, "push", "origin", "HEAD:refs/tags/2026.8.7")
    result = release(repo, outside)
    assert result.returncode == 0, result.stderr
    assert (repo / "VERSION").read_text() == "2026.8.8\n"
    changelog = (repo / "CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [2026.8.8] — 2026-02-19" in changelog
    assert "- New feature." in changelog
    assert "## [2026.7.1] — 2026-02-10" in changelog
    commit = git(repo, "rev-parse", "HEAD")
    assert git(repo, "log", "-1", "--format=%s") == "Release 2026.8.8"
    assert git(repo, "cat-file", "-t", "refs/tags/2026.8.8") == "tag"
    assert git(remote, "rev-parse", "refs/heads/main") == commit
    assert git(remote, "rev-parse", "refs/tags/2026.8.8^{}") == commit
    assert git(repo, "status", "--porcelain") == ""
    assert release(repo, outside).returncode != 0  # The newly opened section has no notes.
    assert git(repo, "rev-parse", "HEAD") == commit


@pytest.mark.parametrize("condition", ["dirty", "staged", "untracked", "branch", "detached", "empty", "missing"])
def test_release_preconditions_do_not_publish(release_repo, condition):
    repo, remote, outside = release_repo
    if condition in {"dirty", "staged"}:
        (repo / "VERSION").write_text("2026.8.9\n")
        if condition == "staged":
            git(repo, "add", "VERSION")
    elif condition == "untracked":
        (repo / "extra").write_text("uncommitted\n")
    elif condition == "branch":
        git(repo, "checkout", "-b", "feature")
    elif condition == "detached":
        git(repo, "checkout", "--detach")
    else:
        (repo / "CHANGELOG.md").write_text("## [Unreleased]\n" if condition == "empty" else "# Changelog\n")
        git(repo, "commit", "-am", "Prepare invalid changelog")
    before = git(repo, "rev-parse", "HEAD")
    remote_before = git(remote, "rev-parse", "refs/heads/main")
    assert release(repo, outside).returncode != 0
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(remote, "rev-parse", "refs/heads/main") == remote_before
    assert git(remote, "tag", "--list") == ""


@pytest.mark.parametrize("version, notes, valid", [
    ("2026.8.1", "## [2026.8.1] — 2026-02-19\n\n- Feature.\n", True),
    ("2026.08.1", "## [2026.08.1] — 2026-02-19\n\n- Feature.\n", False),
    ("2026.8.1", "## [Unreleased]\n\n- Feature.\n", False),
    ("2026.8.1", "## [2026.8.1] — 2026-02-19\n\n## [2026.7.1] — 2026-02-10\n\n- Old.\n", False),
])
def test_ci_requires_dated_notes_for_release(tmp_path, version, notes, valid):
    workflow = yaml.safe_load((ROOT / ".forgejo/workflows/release.yml").read_text())
    step = next(s for s in workflow["jobs"]["release"]["steps"] if s["name"] == "Verify release changelog")
    (tmp_path / "CHANGELOG.md").write_text(notes)
    result = subprocess.run(["sh", "-c", step["run"]], cwd=tmp_path,
                            env={**os.environ, "RELEASE_TAG": version}, capture_output=True, text=True)
    assert (result.returncode == 0) == valid, result.stderr

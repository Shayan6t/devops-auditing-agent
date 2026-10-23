"""Unit tests for repository inspection tools."""

import subprocess
from pathlib import Path

import pytest

from tools import RepositoryInspector


@pytest.fixture
def mock_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository fixture with diverse DevOps artifacts."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, check=True)

    # 1. Create source file with mock credential and machine path
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    app_file = src_dir / "app.py"
    app_file.write_text(
        "import os\n"
        "SECRET_KEY = 'sk-live-1234567890abcdef12345678'\n"
        "LOCAL_CACHE = '/home/ubuntu/app/cache'\n"
        "def run():\n"
        "    print('Running')\n"
    )

    # 2. Create GitHub Actions workflow
    wf_dir = repo_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    wf_file = wf_dir / "ci.yml"
    wf_file.write_text(
        "name: CI\n"
        "on: [push]\n"
        "permissions: write-all\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
    )

    # 3. Create requirements.txt
    req_file = repo_dir / "requirements.txt"
    req_file.write_text("flask\nrequests\n")

    # Commit initial state
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial test commit"], cwd=repo_dir, check=True, capture_output=True)

    return repo_dir


def test_list_files(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    result = inspector.list_files()
    assert "src/" in result or "app.py" in result
    assert "requirements.txt" in result
    assert "[dir]  .git/" not in result  # .git internal directory should be excluded
    assert ".github" in result  # .github workflow directory should still be included


def test_read_file(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    content = inspector.read_file("src/app.py", start_line=1, end_line=3)
    assert "1 | import os" in content
    assert "SECRET_KEY" in content

    # Non-existent file
    error_content = inspector.read_file("does_not_exist.py")
    assert "Error: File 'does_not_exist.py' does not exist" in error_content


def test_path_traversal_prevention(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    with pytest.raises(PermissionError):
        inspector._safe_path("../../../etc/passwd")


def test_search_code(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    matches = inspector.search_code("SECRET_KEY")
    assert "src/app.py" in matches
    assert "SECRET_KEY" in matches

    no_match = inspector.search_code("nonexistent_token_xyz")
    assert "No occurrences" in no_match


def test_git_log(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    log_output = inspector.git_log(max_commits=5)
    assert "Initial test commit" in log_output
    assert "Tester" in log_output


def test_git_status(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    status_clean = inspector.git_status()
    assert "Working directory clean" in status_clean

    # Add an uncommitted file
    (mock_repo / "untracked.tmp").write_text("temporary")
    status_dirty = inspector.git_status()
    assert "untracked.tmp" in status_dirty


def test_inspect_ci_workflows(mock_repo: Path):
    inspector = RepositoryInspector(mock_repo)
    workflows = inspector.inspect_ci_workflows()
    assert "ci.yml" in workflows
    assert "permissions: write-all" in workflows

"""Inspection tools for DevOps Repository Auditing.

Implements all required tools:
- list_files(): Discover repository files and structure
- read_file(path): Inspect relevant source or configuration with line numbers
- search_code(pattern): Search for suspicious patterns across the repository
- git_log(): Inspect commit history

And bonus/optional tools:
- git_status(): Check working directory clean status and untracked files
- run_ruff(directory): Static code linting inspection
- run_pytest(test_path): Test suite execution or discovery
- inspect_ci_workflows(): Parse and inspect GitHub Actions workflows
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class RepositoryInspector:
    """Safely inspects a cloned repository without modifying its state."""

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).resolve()
        if not self.root_dir.is_dir():
            raise ValueError(f"Repository root directory does not exist: {self.root_dir}")

    def _safe_path(self, relative_path: str) -> Path:
        """Resolve path and ensure it remains strictly inside root_dir."""
        target = (self.root_dir / relative_path).resolve()
        try:
            target.relative_to(self.root_dir)
        except ValueError:
            raise PermissionError(f"Access denied: Path '{relative_path}' is outside repository root.")
        return target

    def list_files(
        self,
        directory: str = "",
        max_depth: int = 4,
        include_hidden: bool = True,
    ) -> str:
        """Discover repository files and directory structure up to max_depth."""
        try:
            base = self._safe_path(directory)
            if not base.exists():
                return f"Error: Directory '{directory}' does not exist."
            if not base.is_dir():
                return f"Error: '{directory}' is not a directory."

            lines: List[str] = []
            base_parts_len = len(base.parts)

            for root, dirs, files in os.walk(base):
                # Filter out .git internal objects to prevent clutter
                if ".git" in dirs:
                    dirs.remove(".git")
                # Also ignore common virtual environments and heavy caches
                for ign in [".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"]:
                    if ign in dirs:
                        dirs.remove(ign)

                rel_dir = Path(root).relative_to(self.root_dir)
                depth = len(Path(root).parts) - base_parts_len
                if depth >= max_depth:
                    dirs.clear()
                    continue

                indent = "  " * depth
                if str(rel_dir) != ".":
                    lines.append(f"{indent}[dir]  {rel_dir.name}/")

                file_indent = "  " * (depth + 1) if str(rel_dir) != "." else ""
                for f in sorted(files):
                    if not include_hidden and f.startswith("."):
                        continue
                    lines.append(f"{file_indent}[file] {f}")

            if not lines:
                return "Repository is empty or no matching files found."
            return "\n".join(lines[:400])
        except Exception as e:
            return f"Error listing files: {str(e)}"

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
        max_lines: int = 300,
    ) -> str:
        """Inspect source or configuration files with line numbers for precise referencing."""
        try:
            target = self._safe_path(path)
            if not target.exists():
                return f"Error: File '{path}' does not exist."
            if not target.is_file():
                return f"Error: '{path}' is a directory, not a file."

            # Check for binary file
            try:
                with open(target, "rb") as f:
                    chunk = f.read(1024)
                    if b"\0" in chunk:
                        return f"Error: '{path}' appears to be a binary file."
            except Exception as e:
                return f"Error reading file headers: {str(e)}"

            with open(target, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()

            total_lines = len(all_lines)
            s_idx = max(1, start_line)
            e_idx = min(total_lines, end_line if end_line is not None else s_idx + max_lines - 1)

            if s_idx > total_lines:
                return f"File '{path}' has only {total_lines} lines (requested start: {s_idx})."

            formatted: List[str] = [f"--- File: {path} (Lines {s_idx}-{e_idx} of {total_lines}) ---"]
            for idx in range(s_idx - 1, e_idx):
                line_content = all_lines[idx].rstrip("\r\n")
                formatted.append(f"{idx + 1:4d} | {line_content}")

            if e_idx < total_lines:
                formatted.append(f"... ({total_lines - e_idx} lines remaining) ...")

            return "\n".join(formatted)
        except Exception as e:
            return f"Error reading file '{path}': {str(e)}"

    def search_code(
        self,
        pattern: str,
        file_extension: Optional[str] = None,
        max_matches: int = 25,
    ) -> str:
        """Search for suspicious patterns or strings across repository files."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"Invalid regular expression '{pattern}': {str(e)}"

        matches: List[str] = []
        try:
            for root, dirs, files in os.walk(self.root_dir):
                if ".git" in dirs:
                    dirs.remove(".git")
                for ign in [".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"]:
                    if ign in dirs:
                        dirs.remove(ign)

                for file_name in files:
                    if file_extension and not file_name.endswith(file_extension):
                        continue

                    full_path = Path(root) / file_name
                    rel_path = full_path.relative_to(self.root_dir)

                    # Quick binary check
                    try:
                        with open(full_path, "rb") as bf:
                            if b"\0" in bf.read(512):
                                continue
                    except Exception:
                        continue

                    try:
                        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                            for line_num, line in enumerate(f, 1):
                                if regex.search(line):
                                    preview = line.strip()
                                    if len(preview) > 140:
                                        preview = preview[:140] + "..."
                                    matches.append(f"{rel_path}:{line_num}: {preview}")
                                    if len(matches) >= max_matches:
                                        return (
                                            f"Matches for pattern '{pattern}' (capped at {max_matches}):\n"
                                            + "\n".join(matches)
                                        )
                    except Exception:
                        continue

            if not matches:
                return f"No occurrences of pattern '{pattern}' found."
            return f"Matches for pattern '{pattern}':\n" + "\n".join(matches)
        except Exception as e:
            return f"Error searching code: {str(e)}"

    def git_log(self, max_commits: int = 15) -> str:
        """Inspect repository commit history, authors, and commit messages."""
        try:
            cmd = [
                "git",
                "log",
                f"-n{max_commits}",
                "--pretty=format:%h | %an | %ad | %s",
                "--date=short",
            ]
            result = subprocess.run(
                cmd,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return f"Git log error: {result.stderr.strip() or 'No commit history available'}"
            return result.stdout.strip() or "No commits in repository."
        except Exception as e:
            return f"Error running git log: {str(e)}"

    def git_status(self) -> str:
        """Check git status for uncommitted, tracked, or leftover files."""
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return f"Git status error: {result.stderr.strip()}"
            out = result.stdout.strip()
            return out if out else "Working directory clean."
        except Exception as e:
            return f"Error running git status: {str(e)}"

    def run_ruff(self, directory: str = "") -> str:
        """Run ruff linter check non-destructively to assess code quality."""
        try:
            target_path = str(self._safe_path(directory))
            result = subprocess.run(
                ["ruff", "check", "--no-fix", "--output-format=concise", target_path],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = result.stdout.strip() or result.stderr.strip()
            if result.returncode == 0:
                return "Ruff check passed: No linting or formatting defects detected."
            return f"Ruff findings (exit code {result.returncode}):\n" + (out[:2000] if out else "Lint violations detected.")
        except FileNotFoundError:
            return "Ruff linter is not installed in the environment."
        except Exception as e:
            return f"Error running ruff: {str(e)}"

    def run_pytest(self, test_path: str = "") -> str:
        """Run pytest in discovery/collection mode or quick non-destructive execution."""
        try:
            cmd = ["pytest", "--collect-only", "-q"]
            if test_path:
                cmd.append(str(self._safe_path(test_path)))
            result = subprocess.run(
                cmd,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = result.stdout.strip() or result.stderr.strip()
            return f"Pytest collection summary:\n{out[:2000]}"
        except FileNotFoundError:
            return "Pytest is not installed in the environment."
        except Exception as e:
            return f"Error running pytest: {str(e)}"

    def inspect_ci_workflows(self) -> str:
        """Inspect GitHub Actions workflow files under .github/workflows/."""
        wf_dir = self.root_dir / ".github" / "workflows"
        if not wf_dir.exists() or not wf_dir.is_dir():
            return "No GitHub Actions workflows found ('.github/workflows' directory is absent)."

        workflows = []
        for file in wf_dir.glob("*.y*ml"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    content = f.read()
                    workflows.append(f"=== Workflow: {file.name} ===\n{content[:2500]}")
            except Exception as e:
                workflows.append(f"Error reading {file.name}: {e}")

        if not workflows:
            return "Directory '.github/workflows' exists but contains no YAML workflow files."
        return "\n\n".join(workflows)


# Tool schemas for LLM function calling / tool dispatch
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "Discover files and directory hierarchy in the repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Relative subdirectory to list, or empty for repo root.",
                    "default": "",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to traverse (default: 4).",
                    "default": 4,
                },
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents with numbered lines for detailed source or config inspection.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the file to inspect.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed).",
                    "default": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Line number to end reading (optional).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Search across repository files for suspicious strings, secret keys, or code patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search string or regular expression pattern.",
                },
                "file_extension": {
                    "type": "string",
                    "description": "Optional file extension filter (e.g. '.py', '.yml', '.env').",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "git_log",
        "description": "Inspect recent git commit messages, dates, and author information.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_commits": {
                    "type": "integer",
                    "description": "Number of recent commits to display (default: 15).",
                    "default": 15,
                },
            },
        },
    },
    {
        "name": "git_status",
        "description": "Check git repository status for dirty working tree, untracked artifacts, or leftover files.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "inspect_ci_workflows",
        "description": "Inspect all GitHub Actions workflow configurations located in .github/workflows/.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_ruff",
        "description": "Run ruff code quality linter non-destructively to check for Python formatting and lint errors.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Relative subdirectory to lint, or empty for entire repository.",
                    "default": "",
                },
            },
        },
    },
    {
        "name": "run_pytest",
        "description": "Run pytest in test collection mode to check test availability and test discovery status.",
        "parameters": {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Optional test file or directory path.",
                    "default": "",
                },
            },
        },
    },
]

#!/usr/bin/env python3
"""CLI Entrypoint for the DevOps Repository Auditing Agent.

Conforms to Assignment Execution Interface:
    python agent.py --repo <github_repository_url> --output report.json

Execution behavior:
- Runs unattended without interactive prompts.
- Clones remote repository into an isolated temporary directory.
- Leaves inspected repository completely unchanged.
- Writes valid JSON report to specified output path.
- On fatal errors, exits non-zero with useful error message.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from core.agent_loop import DevOpsAuditorAgent
from core.llm_client import LLMClient
from tools import RepositoryInspector


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments according to assignment contract."""
    parser = argparse.ArgumentParser(
        description="Autonomous AI Agent for DevOps Repository Auditing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="Public GitHub repository URL (or path to local repository for testing)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path where the final JSON report will be written",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["gemini", "groq", "openai"],
        help="LLM provider override (default: auto-detect or .env)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=15,
        help="Maximum tool-use iterations for the agent loop",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress step-by-step reasoning logs to stderr",
    )
    return parser.parse_args()


def clone_repository(repo_url: str, destination_dir: str) -> None:
    """Clone remote git repository shallowly into isolated directory."""
    sys.stderr.write(f"[*] Cloning repository {repo_url} into sandbox...\n")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "25", "--quiet", repo_url, destination_dir],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"Error cloning repository: {e.stderr.strip()}\n")
        raise RuntimeError(f"Failed to clone repository: {e.stderr.strip()}") from e
    except subprocess.TimeoutExpired as e:
        sys.stderr.write("Error: Git clone timed out after 120 seconds.\n")
        raise RuntimeError("Git clone operation timed out.") from e


def main() -> None:
    args = parse_arguments()

    repo_target = args.repo.strip()
    output_path = Path(args.output).resolve()
    verbose = not args.quiet

    # Ensure output parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize LLM client
    try:
        llm_client = LLMClient(
            provider=args.provider,
            model=args.model,
        )
    except Exception as e:
        sys.stderr.write(f"Fatal Configuration Error: {str(e)}\n")
        sys.exit(1)

    # Inspect either remote repository or local path
    is_remote = repo_target.startswith(("http://", "https://", "git@"))

    try:
        if is_remote:
            with tempfile.TemporaryDirectory(prefix="devops_audit_") as temp_dir:
                clone_repository(repo_target, temp_dir)
                inspector = RepositoryInspector(temp_dir)
                agent = DevOpsAuditorAgent(
                    inspector=inspector,
                    repository_url=repo_target,
                    llm_client=llm_client,
                    max_steps=args.max_steps,
                    verbose=verbose,
                )
                report = agent.audit()
        else:
            local_path = Path(repo_target).resolve()
            if not local_path.exists() or not local_path.is_dir():
                sys.stderr.write(f"Fatal Error: Local repository path does not exist: {local_path}\n")
                sys.exit(1)
            inspector = RepositoryInspector(local_path)
            agent = DevOpsAuditorAgent(
                inspector=inspector,
                repository_url=repo_target,
                llm_client=llm_client,
                max_steps=args.max_steps,
                verbose=verbose,
            )
            report = agent.audit()

        # Write validated JSON output report
        report_data = report.to_json_dict()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        sys.stderr.write(f"\n[+] Audit successfully completed! Report written to: {output_path}\n")
        sys.exit(0)

    except Exception as e:
        sys.stderr.write(f"\n[!] Fatal Audit Execution Error: {str(e)}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Unit tests for agent reasoning loop, schema contracts, and secret redaction."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from core.agent_loop import DevOpsAuditorAgent, extract_json_block
from core.llm_client import LLMClient
from core.schemas import AuditReport, Violation, redact_secrets
from tools import RepositoryInspector


def test_schema_validation_and_secret_redaction():
    # Test secret redaction logic
    raw_evidence = "Found secret key sk-live-9876543210abcdef12345 in source"
    sanitized = redact_secrets(raw_evidence)
    assert "***REDACTED***" in sanitized
    assert "9876543210abcdef12345" not in sanitized

    # Test violation model instantiation and category normalization
    v = Violation(
        rule_id="SEC-001",
        category="sec",  # should be normalized to "security"
        severity="CRITICAL",  # should be normalized to "critical"
        file="config.py",
        line=10,
        description="Found password='SuperSecretPassword123'",
        evidence="Assigned secret key sk-live-9876543210abcdef12345 directly",
        recommendation="Use env vars",
    )
    assert v.category == "security"
    assert v.severity == "critical"
    assert "SuperSecretPassword123" not in v.description
    assert "***REDACTED***" in v.description

    # Test report serialization conforming to contract
    report = AuditReport(repository="https://github.com/test/repo", violations=[v])
    data = report.to_json_dict()
    assert data["repository"] == "https://github.com/test/repo"
    assert len(data["violations"]) == 1
    assert data["violations"][0]["rule_id"] == "SEC-001"
    assert data["violations"][0]["file"] == "config.py"
    assert data["violations"][0]["line"] == 10


def test_null_file_and_line_handling():
    v = Violation(
        rule_id="HYG-001",
        category="repository hygiene",
        severity="medium",
        file=None,
        line=None,
        description="Missing README",
        evidence="README is absent",
        recommendation="Create README.md",
    )
    report = AuditReport(repository="https://github.com/test/repo", violations=[v])
    json_str = json.dumps(report.to_json_dict())
    parsed = json.loads(json_str)
    assert parsed["violations"][0]["file"] is None
    assert parsed["violations"][0]["line"] is None


def test_extract_json_block():
    markdown_text = (
        "Here is my final report:\n"
        "```json\n"
        "{\n"
        '  "repository": "https://github.com/test/demo",\n'
        '  "violations": []\n'
        "}\n"
        "```\n"
        "Hope this helps!"
    )
    extracted = extract_json_block(markdown_text)
    assert extracted is not None
    assert extracted["repository"] == "https://github.com/test/demo"
    assert extracted["violations"] == []


def test_mocked_agent_loop(tmp_path: Path):
    """Test full agent loop execution using mocked LLM responses."""
    dummy_file = tmp_path / "README.md"
    dummy_file.write_text("# Test Project")

    inspector = RepositoryInspector(tmp_path)
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.provider = "gemini"
    mock_llm.model = "gemini-2.5-flash"

    # Step 1: Model selects tool 'list_files'
    # Step 2: Model emits final JSON report
    step1_tool_calls = [
        {"id": "call_1", "name": "list_files", "arguments": {"directory": ""}}
    ]
    step2_content = json.dumps({
        "repository": "https://github.com/test/demo",
        "violations": [
            {
                "rule_id": "HYG-002",
                "category": "repository hygiene",
                "severity": "low",
                "file": None,
                "line": None,
                "description": "Missing .gitignore file",
                "evidence": ".gitignore not found in root directory",
                "recommendation": "Add a standard .gitignore file",
            }
        ],
    })

    mock_llm.chat_step.side_effect = [
        ("I will first list the files to inspect the repo.", step1_tool_calls),
        (f"```json\n{step2_content}\n```", []),
    ]

    agent = DevOpsAuditorAgent(
        inspector=inspector,
        repository_url="https://github.com/test/demo",
        llm_client=mock_llm,
        max_steps=5,
        verbose=False,
    )
    report = agent.audit()

    assert report.repository == "https://github.com/test/demo"
    assert len(report.violations) == 1
    assert report.violations[0].rule_id == "HYG-002"
    assert report.violations[0].severity == "low"
    assert mock_llm.chat_step.call_count == 2

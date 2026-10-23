"""Data schemas and validation contracts for DevOps Auditing Agent.

Conforms strictly to the Output Contract specified in Assignment 2:
{
  "repository": "https://github.com/example/demo-project",
  "violations": [
    {
      "rule_id": "SEC-001",
      "category": "security",
      "severity": "critical",
      "file": "config.py",
      "line": 17,
      "description": "Hardcoded API credential",
      "evidence": "Credential assigned directly in source code",
      "recommendation": "Use a secrets manager or environment variable"
    }
  ]
}
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    """Allowed severity levels according to specification."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Standard DevOps violation categories from assignment specification
VALID_CATEGORIES = {
    "repository hygiene",
    "dependency management",
    "code quality",
    "testing",
    "github actions / ci",
    "security",
    "configuration",
    "collaboration",
    "build and release",
}

# Regex patterns for accidental secrets to enforce "never reproduce secret values"
SECRET_PATTERNS = [
    re.compile(r"(ghp_[A-Za-z0-9_]{20,})"),
    re.compile(r"(github_pat_[A-Za-z0-9_]{40,})"),
    re.compile(r"(sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"(AIza[0-9A-Za-z-_]{35})"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
    re.compile(r"([a-f0-9]{32,64})"),
    re.compile(r"(password\s*[:=]\s*['\"])([^'\"]+)(['\"])", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    """Mask any potential secrets in evidence or descriptions."""
    if not text:
        return text

    sanitized = text
    # Mask known token prefixes
    sanitized = re.sub(r"(ghp_[A-Za-z0-9_]{4})[A-Za-z0-9_]+", r"\1***REDACTED***", sanitized)
    sanitized = re.sub(r"(github_pat_[A-Za-z0-9_]{6})[A-Za-z0-9_]+", r"\1***REDACTED***", sanitized)
    sanitized = re.sub(r"(sk-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+", r"\1***REDACTED***", sanitized)
    sanitized = re.sub(r"(AIza[0-9A-Za-z-_]{4})[0-9A-Za-z-_]+", r"\1***REDACTED***", sanitized)
    sanitized = re.sub(r"(AKIA[0-9A-Z]{4})[0-9A-Z]+", r"\1***REDACTED***", sanitized)
    sanitized = re.sub(
        r"(password\s*[:=]\s*['\"])([^'\"]+)(['\"])",
        r"\1***REDACTED***\3",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


class Violation(BaseModel):
    """Individual DevOps violation record."""
    rule_id: str = Field(
        ...,
        description="Standardized rule code (e.g. SEC-001, HYG-001, CI-001, DEP-001)",
    )
    category: str = Field(
        ...,
        description="One of the 9 DevOps inspection areas",
    )
    severity: Literal["critical", "high", "medium", "low"] = Field(
        ...,
        description="Severity level: critical, high, medium, or low",
    )
    file: Optional[str] = Field(
        None,
        description="Relative file path where the issue occurs, or null if repo-wide",
    )
    line: Optional[int] = Field(
        None,
        description="Line number where issue occurs, or null if file-wide/repo-wide",
    )
    description: str = Field(
        ...,
        description="Clear, concise description of the DevOps defect",
    )
    evidence: str = Field(
        ...,
        description="Concrete, verifiable evidence without revealing raw secret values",
    )
    recommendation: str = Field(
        ...,
        description="Actionable, production-grade remediation steps",
    )

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        if not isinstance(v, str):
            return "repository hygiene"
        clean = v.strip().lower()
        if clean in VALID_CATEGORIES:
            return clean
        # Match common aliases
        mapping = {
            "hygiene": "repository hygiene",
            "repo hygiene": "repository hygiene",
            "dependencies": "dependency management",
            "deps": "dependency management",
            "quality": "code quality",
            "lint": "code quality",
            "tests": "testing",
            "ci": "github actions / ci",
            "actions": "github actions / ci",
            "github actions": "github actions / ci",
            "sec": "security",
            "config": "configuration",
            "collab": "collaboration",
            "build": "build and release",
            "release": "build and release",
        }
        return mapping.get(clean, clean)

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: str) -> str:
        if not isinstance(v, str):
            return "medium"
        clean = v.strip().lower()
        if clean in ("critical", "high", "medium", "low"):
            return clean
        return "medium"

    @field_validator("evidence", "description", mode="after")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        return redact_secrets(v)


class AuditReport(BaseModel):
    """Top-level Audit Report matching exact assignment specification."""
    repository: str = Field(..., description="Target repository URL or path")
    violations: List[Violation] = Field(
        default_factory=list,
        description="List of detected DevOps violations",
    )

    def to_json_dict(self) -> dict:
        """Convert to dict guaranteeing exact JSON types (null for None)."""
        return {
            "repository": self.repository,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "category": v.category,
                    "severity": v.severity,
                    "file": v.file,
                    "line": v.line,
                    "description": v.description,
                    "evidence": v.evidence,
                    "recommendation": v.recommendation,
                }
                for v in self.violations
            ],
        }

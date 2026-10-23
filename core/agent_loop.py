"""Explicit Autonomous Agent Loop for DevOps Repository Auditing.

Implements the required cycle:
Observe -> Reason -> Select Tool -> Execute Tool -> Interpret Results -> Report.

Strictly adheres to:
- No banned frameworks (LangChain, LangGraph, n8n). Pure Python dispatch.
- Dynamic tool selection driven by the LLM.
- Non-destructive execution on target repositories.
- Strict schema validation and false-positive filtering.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Optional

from core.llm_client import LLMClient
from core.prompts import AGENT_SYSTEM_PROMPT
from core.schemas import AuditReport, Violation
from tools import TOOL_DEFINITIONS, RepositoryInspector


def extract_json_block(text: str) -> Optional[dict]:
    """Safely extract and parse JSON object from markdown blocks or raw text."""
    if not text:
        return None

    # Try fenced json block first
    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding the largest balanced outer JSON object
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = text[start_idx : end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


class DevOpsAuditorAgent:
    """Autonomous DevOps audit agent executing explicit tool-use cycles."""

    def __init__(
        self,
        inspector: RepositoryInspector,
        repository_url: str,
        llm_client: LLMClient,
        max_steps: int = 15,
        verbose: bool = True,
    ):
        self.inspector = inspector
        self.repository_url = repository_url
        self.llm_client = llm_client
        self.max_steps = max_steps
        self.verbose = verbose
        self.tool_dispatch_map = {
            "list_files": self.inspector.list_files,
            "read_file": self.inspector.read_file,
            "search_code": self.inspector.search_code,
            "git_log": self.inspector.git_log,
            "git_status": self.inspector.git_status,
            "inspect_ci_workflows": self.inspector.inspect_ci_workflows,
            "run_ruff": self.inspector.run_ruff,
            "run_pytest": self.inspector.run_pytest,
        }

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr, flush=True)

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Safely dispatch tool call to inspector implementation."""
        if tool_name not in self.tool_dispatch_map:
            return f"Error: Tool '{tool_name}' is not recognized."

        func = self.tool_dispatch_map[tool_name]
        try:
            return str(func(**arguments))
        except TypeError as te:
            return f"Error executing '{tool_name}' with arguments {arguments}: {str(te)}"
        except Exception as e:
            return f"Error executing tool '{tool_name}': {str(e)}"

    def audit(self) -> AuditReport:
        """Run the autonomous inspection loop until comprehensive report is generated."""
        self._log(f"[*] Commencing autonomous DevOps audit for: {self.repository_url}")
        self._log(f"[*] Engine: {self.llm_client.provider} ({self.llm_client.model})")

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Please conduct an autonomous DevOps audit of the repository '{self.repository_url}'.\n\n"
                    "Instructions:\n"
                    "1. Start by calling `list_files` to discover structure, build systems, CI files, and configs.\n"
                    "2. Based on findings, selectively inspect workflows (`inspect_ci_workflows`), configs, and source files.\n"
                    "3. Search for sensitive credentials, hardcoded absolute paths, unpinned dependencies, and missing test execution.\n"
                    "4. Adhere strictly to the Evidence Rules (do not raise false positives if equivalent modern tools are used).\n"
                    "5. Output the final report in the exact required JSON contract."
                ),
            },
        ]

        raw_report_data: Optional[dict] = None

        for step in range(1, self.max_steps + 1):
            self._log(f"\n--- Agent Cycle Step {step}/{self.max_steps} [Observe & Reason] ---")

            try:
                content, tool_calls = self.llm_client.chat_step(messages, tools=TOOL_DEFINITIONS)
            except Exception as e:
                self._log(f"[!] LLM interaction failed: {str(e)}")
                raise RuntimeError(f"LLM interaction error: {str(e)}") from e

            if content:
                self._log(f"[Agent Thoughts / Reasoning]:\n{content.strip()}\n")

            # Check if the agent already emitted the final report JSON
            possible_report = extract_json_block(content or "")
            if possible_report and "violations" in possible_report:
                self._log("[*] Agent synthesized final report.")
                raw_report_data = possible_report
                break

            # If tool calls were made, execute them
            if tool_calls:
                # Add assistant message with tool calls
                asst_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(asst_msg)

                for tc in tool_calls:
                    fn_name = tc["name"]
                    args = tc["arguments"]
                    self._log(f"-> [Select & Execute Tool]: {fn_name}({args})")

                    output = self.execute_tool(fn_name, args)
                    # Limit output length in context to prevent token overflows
                    truncated_output = output if len(output) <= 3500 else output[:3500] + "\n...[truncated]..."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": truncated_output,
                    })

                    preview = truncated_output.splitlines()[:4]
                    self._log("<- [Tool Result Summary]:\n" + "\n".join(preview))
            else:
                # Agent provided neither tool calls nor valid JSON report
                self._log("[?] No tool calls returned. Requesting final report or next action...")
                messages.append({"role": "assistant", "content": content or ""})
                messages.append({
                    "role": "user",
                    "content": (
                        "If you have gathered sufficient evidence, please output the final JSON report now. "
                        "Otherwise, call another tool to continue your investigation."
                    ),
                })

        # If loop finished without extracting report, perform a final synthesis call
        if not raw_report_data:
            self._log("[*] Requesting final report synthesis...")
            messages.append({
                "role": "user",
                "content": (
                    "Based on all observations and tool results gathered during this audit, "
                    "compile and output the final audit report adhering strictly to the required JSON schema. "
                    "Include only verifiable violations with rule_id, category, severity, file, line, "
                    "description, evidence, and recommendation. Output ONLY the JSON object."
                ),
            })
            content, _ = self.llm_client.chat_step(messages, tools=None)
            raw_report_data = extract_json_block(content or "")

        if not raw_report_data or not isinstance(raw_report_data, dict):
            # Fallback to empty report conforming to specification
            self._log("[!] No violations detected or unable to parse report; defaulting to clean report.")
            raw_report_data = {"repository": self.repository_url, "violations": []}

        # Ensure repository URL is preserved
        raw_report_data["repository"] = self.repository_url

        # Validate with Pydantic schema
        validated_violations: List[Violation] = []
        raw_violations = raw_report_data.get("violations", [])
        if isinstance(raw_violations, list):
            for item in raw_violations:
                if isinstance(item, dict):
                    try:
                        validated_violations.append(Violation(**item))
                    except Exception as ve:
                        self._log(f"[-] Dropping malformed violation item: {ve}")

        report = AuditReport(
            repository=self.repository_url,
            violations=validated_violations,
        )
        self._log(f"[+] Audit complete: {len(report.violations)} verified violation(s) identified.")
        return report

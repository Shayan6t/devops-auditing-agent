"""LLM Client interface supporting Google Gemini, Groq, and OpenAI without 3rd party agent frameworks."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class LLMClient:
    """Universal LLM client for agent tool-use and reasoning."""

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.1,
    ):
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "").strip().lower()
        self.temperature = float(os.getenv("AGENT_TEMPERATURE", str(temperature)))

        # Auto-detect provider based on available environment keys if not explicitly set
        if not self.provider or self.provider not in ("gemini", "groq", "openai"):
            if os.getenv("GEMINI_API_KEY"):
                self.provider = "gemini"
            elif os.getenv("GROQ_API_KEY"):
                self.provider = "groq"
            elif os.getenv("OPENAI_API_KEY"):
                self.provider = "openai"
            else:
                self.provider = "gemini"

        if self.provider == "gemini":
            self.api_key = api_key or os.getenv("GEMINI_API_KEY")
            self.model = model or os.getenv("GEMINI_MODEL") or "gemini-flash-latest"
            self.base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif self.provider == "groq":
            self.api_key = api_key or os.getenv("GROQ_API_KEY")
            self.model = model or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"
            self.base_url = "https://api.groq.com/openai/v1"
        elif self.provider == "openai":
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            self.model = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
            self.base_url = None
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

        if not self.api_key:
            key_name = f"{self.provider.upper()}_API_KEY"
            raise ValueError(
                f"Missing API key for provider '{self.provider}'. "
                f"Please set '{key_name}' in your environment or '.env' file."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=float(os.getenv("AGENT_TIMEOUT_SECONDS", "180")),
        )

    def chat_step(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Execute a single step in the agent loop.

        Returns:
            (content_text, list_of_tool_calls)
            tool_calls format: [{"id": call_id, "name": tool_name, "arguments": dict}]
        """
        formatted_tools = None
        if tools:
            formatted_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if formatted_tools:
            kwargs["tools"] = formatted_tools
            kwargs["tool_choice"] = "auto"

        # Resilient execution with exponential backoff for rate limits or server spikes
        max_retries = 4
        response = None
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                err_msg = str(e)
                is_transient = any(code in err_msg for code in ("503", "429", "timeout", "unavailable", "rate"))
                if is_transient and attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) * 2
                    sys.stderr.write(f"[*] Transient API rate/demand spike ({err_msg[:60]}...). Retrying in {sleep_time}s...\n")
                    time.sleep(sleep_time)
                else:
                    raise

        choice = response.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls: List[Dict[str, Any]] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": fn_name,
                    "arguments": args,
                })

        return content, tool_calls

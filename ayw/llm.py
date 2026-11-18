"""LLM clients. Everything the agent needs is `generate(messages) -> LLMResponse`.

OllamaClient talks to a local Ollama server over HTTP (standard library only, no API key).
The other clients are deterministic stand-ins used by the tests and to validate the evaluation harness.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def generate(self, messages: list[dict]) -> LLMResponse: ...


class OllamaClient:
    def __init__(self, model: str, host: str = "http://localhost:11434",
                 num_ctx: int = 4096, timeout_s: float = 300.0, seed: int = 0):
        self.model, self.host = model, host.rstrip("/")
        self.num_ctx, self.timeout_s, self.seed = num_ctx, timeout_s, seed
        self.name = f"ollama:{model}"

    def generate(self, messages: list[dict]) -> LLMResponse:
        body = json.dumps({
            "model": self.model, "messages": messages, "stream": False,
            "options": {"temperature": 0, "seed": self.seed, "num_ctx": self.num_ctx},
        }).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise LLMError(f"model '{self.model}' not found. Run: ollama pull {self.model}") from e
            raise LLMError(f"Ollama returned HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMError(f"cannot reach Ollama at {self.host}. Is it running? Start it with: ollama serve") from e
        try:
            return LLMResponse(data["message"]["content"],
                               data.get("prompt_eval_count", 0), data.get("eval_count", 0))
        except (KeyError, TypeError) as e:
            raise LLMError("unexpected response format from Ollama") from e


class ScriptedClient:
    """Returns pre-written responses in order. For tests."""
    def __init__(self, responses: list[str], name: str = "scripted"):
        self.responses, self.name, self.calls = list(responses), name, []

    def generate(self, messages: list[dict]) -> LLMResponse:
        self.calls.append(messages)
        text = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return LLMResponse(text, prompt_tokens=sum(len(m["content"]) for m in messages) // 4,
                           completion_tokens=len(text) // 4)


class FunctionClient:
    def __init__(self, fn: Callable[[list[dict]], str], name: str = "function"):
        self.fn, self.name = fn, name

    def generate(self, messages: list[dict]) -> LLMResponse:
        return LLMResponse(self.fn(messages))


_FENCE = re.compile(r"```(?:sql|SQL|duckdb)?\s*\n?(.*?)```", re.DOTALL)
_START = re.compile(r"\b(WITH|SELECT)\b", re.IGNORECASE)


def extract_sql(text: str) -> str:
    """Pull the SQL out of a model reply: a ```sql fence if present, else from the first SELECT/WITH."""
    m = _FENCE.search(text)
    if m:
        return m.group(1).strip()
    m = _START.search(text)
    return text[m.start():].strip() if m else text.strip()

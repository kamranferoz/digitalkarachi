"""Provider-agnostic LLM interface.

Default implementation: `OllamaLLM` talking to a local Ollama server
(`http://localhost:11434`). The model can be overridden with the
`OLLAMA_MODEL` env var (default `qwen2.5:7b-instruct`).

Usage:
    from generators.llm import get_llm
    llm = get_llm()
    text = llm.complete("Write a haiku about Karachi.")
    data = llm.complete("Return {\"city\":\"Karachi\"}", json_mode=True)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Any: ...


@dataclass
class OllamaLLM:
    model: str = "qwen2.5:7b-instruct"
    url: str = "http://localhost:11434"
    timeout: int = 300  # seconds; long-form generation on CPU is slow
    retries: int = 2

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Any:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    f"{self.url.rstrip('/')}/api/generate",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                body = json.loads(raw)
                text = body.get("response", "")
                if not text:
                    raise LLMError(f"Empty response from {self.name}: {body!r}")
                if json_mode:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        raise LLMError(
                            f"{self.name} returned invalid JSON: {e}\n--- response ---\n{text[:500]}"
                        ) from e
                return text
            except (urllib.error.URLError, TimeoutError, LLMError) as e:
                last_exc = e
                if attempt < self.retries:
                    wait = 2 ** attempt
                    print(
                        f"  WARN: {self.name} attempt {attempt+1} failed: {e}; "
                        f"retrying in {wait}s",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                break
        raise LLMError(f"{self.name} failed after {self.retries + 1} attempts: {last_exc}")


def get_llm() -> LLM:
    """Factory honouring env vars OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT."""
    timeout = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
    retries = int(os.environ.get("OLLAMA_RETRIES", "2"))
    return OllamaLLM(
        model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
        url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        timeout=timeout,
        retries=retries,
    )


def health_check(llm: LLM | None = None) -> tuple[bool, str]:
    """Quick liveness probe; returns (ok, message)."""
    llm = llm or get_llm()
    try:
        out = llm.complete(
            "Reply with the single word PONG.",
            temperature=0.0,
            max_tokens=8,
        )
        return ("PONG" in (out or "").upper(), str(out)[:60])
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}")

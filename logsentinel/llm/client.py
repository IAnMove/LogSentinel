"""LLM client for local Ollama and OpenAI-compatible inference backends."""

from __future__ import annotations
import asyncio
from typing import Any, Dict, List, Optional
import httpx
from logsentinel.config import LLMConfig
from logsentinel.core.models import Category, Incident, LLMVerdict, Severity
from logsentinel.llm.parser import ResponseParser
from logsentinel.llm.prompts import SYSTEM_PROMPT, build_analysis_prompt


class LLMClient:
    """Interface to local LLMs via Ollama or OpenAI-compatible APIs."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.openai_base_url = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"

    async def check_health(self) -> Dict[str, Any]:
        """Check connection to the LLM backend and list available models."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            if self.config.provider == "ollama":
                try:
                    resp = await client.get(f"{self.base_url}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m.get("name") for m in data.get("models", [])]
                        return {
                            "status": "healthy" if self.config.model in models or (":" not in self.config.model and self.config.model + ":latest" in models) else "unhealthy",
                            "error": None if self.config.model in models else "Configured model is not available",
                            "provider": "ollama",
                            "base_url": self.base_url,
                            "configured_model": self.config.model,
                            "model_available": self.config.model in models or (":" not in self.config.model and self.config.model + ":latest" in models),
                            "available_models": models,
                        }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "provider": "ollama",
                        "base_url": self.base_url,
                        "error": str(e),
                    }
            else:
                try:
                    headers = {}
                    if self.config.api_key:
                        headers["Authorization"] = f"Bearer {self.config.api_key}"
                    resp = await client.get(f"{self.openai_base_url}/models", headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m.get("id") for m in data.get("data", [])]
                        return {
                            "status": "healthy",
                            "provider": "openai-compatible",
                            "base_url": self.base_url,
                            "configured_model": self.config.model,
                            "available_models": models,
                        }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "provider": "openai-compatible",
                        "base_url": self.base_url,
                        "error": str(e),
                    }

        return {"status": "unhealthy", "error": "Unknown provider or endpoint"}

    async def analyze(self, incident: Incident, memory_context: Optional[str] = None) -> LLMVerdict:
        """Submit incident for LLM analysis and parse the verdict."""
        prompt = build_analysis_prompt(incident, memory_context)

        raw_response = ""
        try:
            if self.config.provider == "ollama":
                raw_response = await self._call_ollama(prompt)
            else:
                raw_response = await self._call_openai(prompt)
        except Exception as e:
            # Safe fallback if LLM request failed or timed out
            is_urgent = incident.category_hint in (Category.SECURITY, Category.SYSTEM_ERROR)
            sev = Severity.HIGH if is_urgent else Severity.MEDIUM
            return LLMVerdict(
                alert_needed=True,
                severity=sev,
                category=incident.category_hint,
                title=f"Potential Alert in {incident.service}",
                summary=f"Aggregated {incident.count} events for {incident.service}. LLM offline or timed out: {str(e)[:90]}",
                recommended_action=f"Check logs: journalctl -u {incident.service} -n 50",
                confidence=0.5,
                reasoning=f"LLM call exception: {e}",
            )

        return ResponseParser.parse(raw_response, incident)

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama /api/chat with JSON format enforcement."""
        endpoint = f"{self.base_url}/api/chat"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("done") is False or data.get("done_reason") not in (None, "stop"):
                raise ValueError("Incomplete Ollama response")
            message = data.get("message", {})
            content = message.get("content", "")
            return content

    async def _call_openai(self, prompt: str) -> str:
        """Call OpenAI-compatible /v1/chat/completions."""
        endpoint = f"{self.openai_base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                if choices[0].get("finish_reason") not in (None, "stop"):
                    raise ValueError("Incomplete OpenAI-compatible response")
                return choices[0].get("message", {}).get("content", "")
            return ""

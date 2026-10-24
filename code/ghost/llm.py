"""Thin LLM provider wrapper with disk caching, rate limiting, and usage accounting.

Design goals:
* Provider-swappable: currently Gemini via the official google-genai SDK.
* Deterministic when possible: temperature=0, structured JSON output.
* Disk cache keyed by sha256(model + prompt_version + input_bytes) so repeated
  runs are free and offline-reproducible.
* Graceful degradation: if the API key or network is unavailable the pipeline
  falls back to cached results, and if no cache exists it skips LLM features
  with a warning.
* Every *real* API call (not cache hits) is appended to a usage log with
  timestamp, model, task, input/output tokens, and latency.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO_ROOT / "code" / "llm_cache"
USAGE_LOG = REPO_ROOT / "code" / "llm_cache" / "usage_log.jsonl"
PRICING_PATH = Path(__file__).resolve().parent / "llm_pricing.json"

# Prompt versioning: bump when prompt semantics change so old caches are invalidated.
PROMPT_VERSIONS = {
    "screenshot_extract": "v1",
    "pdf_extract": "v1",
    "intent_classify": "v1",
}


@dataclass
class UsageRecord:
    timestamp: str = ""
    model: str = ""
    task: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False


@dataclass
class UsageSummary:
    total_calls: int = 0
    cache_hits: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    by_task: Dict[str, Dict[str, int]] = field(default_factory=dict)


def _load_pricing() -> Dict[str, Dict[str, float]]:
    try:
        data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
        return data.get("models", {})
    except Exception:
        return {}


def _cache_key(model: str, prompt_version: str, input_bytes: bytes) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(prompt_version.encode("utf-8"))
    h.update(input_bytes)
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(key)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _write_cache(key: str, data: Dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _append_usage(record: UsageRecord) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(USAGE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": record.timestamp,
            "model": record.model,
            "task": record.task,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "latency_ms": record.latency_ms,
            "cached": record.cached,
        }) + "\n")


class LLMClient:
    """Provider-agnostic LLM client with caching and rate limiting."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        fresh: bool = False,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model_name = model_name or os.environ.get("GEMINI_MODEL", "")
        self.fresh = fresh
        self._client = None
        self._resolved_model: str = ""
        self._available = False
        self._last_call_time: float = 0.0
        self._min_interval: float = 4.0  # seconds between calls (free tier: 15 RPM)
        self.usage = UsageSummary()
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            print("[llm] No GEMINI_API_KEY found; LLM features will use cache only.", file=sys.stderr)
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
            # Resolve model name
            if self._model_name:
                self._resolved_model = self._model_name
            else:
                self._resolved_model = self._pick_model()
            self._available = True
            print(f"[llm] Initialized with model={self._resolved_model}", file=sys.stderr)
        except Exception as e:
            print(f"[llm] Failed to initialize GenAI client: {e}", file=sys.stderr)
            self._available = False

    def _pick_model(self) -> str:
        """List available models and pick the cheapest vision-capable Flash-class model."""
        preferred = [
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
        ]
        try:
            available = []
            for model in self._client.models.list():
                name = model.name
                if name.startswith("models/"):
                    name = name[len("models/"):]
                available.append(name)
            print(f"[llm] Available models: {len(available)} total", file=sys.stderr)
            for pref in preferred:
                if pref in available:
                    print(f"[llm] Selected model: {pref}", file=sys.stderr)
                    return pref
            # Fallback: any flash model
            for name in available:
                if "flash" in name.lower():
                    print(f"[llm] Fallback model: {name}", file=sys.stderr)
                    return name
        except Exception as e:
            print(f"[llm] Could not list models: {e}", file=sys.stderr)
        return "gemini-2.0-flash"

    @property
    def model_name(self) -> str:
        return self._resolved_model or self._model_name or "unknown"

    @property
    def available(self) -> bool:
        return self._available

    def _rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def _call_with_retry(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/png",
        task: str = "unknown",
        max_retries: int = 5,
    ) -> Tuple[str, int, int]:
        """Make an API call with exponential backoff on 429/5xx.

        Returns (response_text, input_tokens, output_tokens).
        """
        from google import genai
        from google.genai import types

        contents = []
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))
        contents.append(prompt)

        config = types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        )

        for attempt in range(max_retries + 1):
            try:
                self._rate_limit()
                t0 = time.time()
                response = self._client.models.generate_content(
                    model=self._resolved_model,
                    contents=contents,
                    config=config,
                )
                latency_ms = int((time.time() - t0) * 1000)

                # Extract token counts from usage metadata
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    um = response.usage_metadata
                    input_tokens = getattr(um, "prompt_token_count", 0) or 0
                    output_tokens = getattr(um, "candidates_token_count", 0) or 0

                text = response.text or ""

                record = UsageRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    model=self._resolved_model,
                    task=task,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    cached=False,
                )
                _append_usage(record)
                self.usage.total_calls += 1
                self.usage.total_input_tokens += input_tokens
                self.usage.total_output_tokens += output_tokens
                task_stats = self.usage.by_task.setdefault(task, {
                    "calls": 0, "cache_hits": 0,
                    "input_tokens": 0, "output_tokens": 0,
                })
                task_stats["calls"] += 1
                task_stats["input_tokens"] += input_tokens
                task_stats["output_tokens"] += output_tokens

                return text, input_tokens, output_tokens

            except Exception as e:
                error_str = str(e)
                is_retryable = (
                    "429" in error_str
                    or "500" in error_str
                    or "502" in error_str
                    or "503" in error_str
                    or "RESOURCE_EXHAUSTED" in error_str
                    or "rate" in error_str.lower()
                )
                if is_retryable and attempt < max_retries:
                    wait = min(2 ** attempt * 2, 120)
                    print(
                        f"[llm] Retryable error (attempt {attempt+1}/{max_retries}): "
                        f"{error_str[:100]}; waiting {wait}s",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError("Max retries exceeded")

    def call(
        self,
        prompt: str,
        input_bytes: bytes,
        task: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/png",
    ) -> Optional[Dict[str, Any]]:
        """Call the LLM with caching. Returns parsed JSON or None."""
        prompt_version = PROMPT_VERSIONS.get(task, "v0")
        # Cache key includes model, prompt version, and the prompt+input content hash
        cache_input = prompt.encode("utf-8") + b"\x00" + input_bytes
        key = _cache_key(self._resolved_model or "no_model", prompt_version, cache_input)

        # Check cache
        if not self.fresh:
            cached = _read_cache(key)
            if cached is not None:
                self.usage.cache_hits += 1
                task_stats = self.usage.by_task.setdefault(task, {
                    "calls": 0, "cache_hits": 0,
                    "input_tokens": 0, "output_tokens": 0,
                })
                task_stats["cache_hits"] = task_stats.get("cache_hits", 0) + 1
                return cached.get("result")

        # No cache hit — need API
        if not self._available:
            print(
                f"[llm] No API available and no cache for task={task}; skipping.",
                file=sys.stderr,
            )
            return None

        try:
            text, in_tok, out_tok = self._call_with_retry(
                prompt=prompt,
                image_bytes=image_bytes,
                image_mime=image_mime,
                task=task,
            )
            # Parse JSON response
            # Strip markdown code fences if present
            cleaned = text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            result = json.loads(cleaned)
            # Cache the result
            _write_cache(key, {
                "model": self._resolved_model,
                "task": task,
                "prompt_version": prompt_version,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "result": result,
            })
            return result
        except json.JSONDecodeError as e:
            print(f"[llm] JSON parse error for task={task}: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[llm] API error for task={task}: {e}", file=sys.stderr)
            return None

    def estimate_cost(self) -> Dict[str, Any]:
        """Estimate cost from usage summary and pricing config."""
        pricing = _load_pricing()
        model_pricing = pricing.get(self._resolved_model, pricing.get("default", {}))
        input_rate = model_pricing.get("input_per_1m", 0.15)
        output_rate = model_pricing.get("output_per_1m", 0.60)

        input_cost = (self.usage.total_input_tokens / 1_000_000) * input_rate
        output_cost = (self.usage.total_output_tokens / 1_000_000) * output_rate
        total_cost = input_cost + output_cost

        return {
            "model": self._resolved_model,
            "total_calls": self.usage.total_calls,
            "cache_hits": self.usage.cache_hits,
            "total_input_tokens": self.usage.total_input_tokens,
            "total_output_tokens": self.usage.total_output_tokens,
            "total_tokens": self.usage.total_input_tokens + self.usage.total_output_tokens,
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(total_cost, 6),
            "pricing_source": f"input=${input_rate}/1M, output=${output_rate}/1M",
            "by_task": dict(self.usage.by_task),
        }


def load_usage_log() -> List[Dict[str, Any]]:
    """Load all usage log entries."""
    entries = []
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries

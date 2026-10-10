"""
risk/llm_enhancer.py
--------------------
Optional LLM enhancement layer (OpenAI-compatible chat/completions).

The deterministic Risk Engine is the **source of truth** for the risk level.
This module never decides or changes the level; it only:

  * rewrites the human-facing `summary` in clearer, calm language, and
  * adds a short `explanation` (reasoning) for the verdict already given.

Hard safety rules enforced here (not left to the prompt alone):

  * Disabled unless `LLM_ENABLED=true` — the app works identically without it.
  * Strict timeout and total exception isolation: any failure returns None
    and the caller keeps the engine's own output.
  * Language discipline: output is rejected if it contains banned conclusion
    phrasing ("this is a scam", "this is fake", ...).
  * A Critical verdict is never softened: an enhanced summary that downplays
    Critical risk is rejected.

Provider support: any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq,
Ollama's `/v1`, vLLM, LM Studio, ...) via `LLM_BASE_URL` + `LLM_MODEL`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import requests

import config
from risk.language import check_language

logger = logging.getLogger("scam_sentry.llm_enhancer")

# How much posting text to send (characters). Keeps prompts small/fast.
MAX_TEXT_CHARS = 4000
# Hard cap on how much of an indicator evidence snippet we inline.
MAX_EVIDENCE_CHARS = 200

SYSTEM_PROMPT = (
    "You are a careful job-advertisement risk assistant. You are given a job "
    "posting excerpt and a risk assessment already produced by a deterministic "
    "rules engine. Your ONLY job is to (1) rewrite the summary in clearer, calm, "
    "professional language and (2) add a short reasoning note that explains WHY "
    "that risk level was reached.\n\n"
    "Hard rules:\n"
    "1. NEVER claim the posting 'is a scam', 'is fake', or 'is a ghost job'. "
    "Describe patterns and indicators instead ('shows patterns consistent with...', "
    "'indicators suggest...').\n"
    "2. The risk level is decided elsewhere and MUST NOT be contradicted, changed, "
    "or evaluated; you never output a level. In particular, never soften or "
    "downplay a Critical assessment.\n"
    "3. Where plausible, acknowledge a legitimate alternative explanation.\n"
    "4. Do not invent facts that are not in the posting or the assessment.\n"
    "5. Do not give legal advice.\n\n"
    'Reply with ONLY a JSON object, no markdown, of the form: '
    '{"summary": "<2-3 sentences>", "explanation": "<1-3 sentences>"}'
)

# Phrases that would soften a Critical verdict — reject the enhancement.
_CRITICAL_SOFTEN_RE = re.compile(
    r"\b(low risk|likely genuine|no significant|seems safe|looks genuine|"
    r"appears legitimate|not a concern)\b",
    re.IGNORECASE,
)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def is_enabled() -> bool:
    """True when the LLM layer is enabled by configuration."""
    return bool(getattr(config, "LLM_ENABLED", False))


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " ...[truncated]"


def _indicator_lines(risk_result: dict[str, Any]) -> str:
    """Compact, human-readable list of the fired indicators."""
    lines = []
    for d in risk_result.get("key_indicators") or []:
        ind_id = d.get("id", "?")
        name = d.get("name", "")
        severity = d.get("severity", "")
        evidence = _truncate(str(d.get("evidence") or ""), MAX_EVIDENCE_CHARS)
        line = "- [%s] %s (%s)" % (ind_id, name, severity)
        if evidence:
            line += ": %s" % evidence
        lines.append(line)
    return "\n".join(lines) if lines else "- (no indicators fired)"


def build_user_prompt(risk_result: dict[str, Any], text: str) -> str:
    """Compose the user message: the engine's verdict + the posting excerpt."""
    level = risk_result.get("overall_risk_level", "Low")
    categories = ", ".join(risk_result.get("risk_categories") or []) or "None"
    confidence = risk_result.get("confidence", "Low")
    engine_summary = risk_result.get("summary", "")
    return (
        "RISK ASSESSMENT (produced by the rules engine — do not change it):\n"
        "Overall risk level: %s\n"
        "Categories: %s\n"
        "Confidence: %s\n"
        "Engine summary: %s\n"
        "Key indicators:\n%s\n\n"
        "JOB POSTING EXCERPT:\n%s\n"
        % (level, categories, confidence, engine_summary,
           _indicator_lines(risk_result), _truncate(text, MAX_TEXT_CHARS))
    )


def _endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _headers(cfg: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = cfg.get("api_key") or ""
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    return headers


def _extract_content(api_json: dict[str, Any]) -> Optional[str]:
    try:
        choices = api_json.get("choices") or []
        message = choices[0].get("message") or {}
        content = message.get("content")
    except (AttributeError, IndexError, TypeError):
        return None
    if isinstance(content, list):
        # Some providers return content as a list of parts.
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        return None
    return content.strip()


def _parse_content(content: str) -> tuple[str, str]:
    """Return (summary, explanation) from a model reply, tolerating fences."""
    cleaned = _JSON_FENCE_RE.sub("", content.strip())
    data = None
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        match = _JSON_OBJECT_RE.search(cleaned)
        if match:
            try:
                data = json.loads(match.group(0))
            except (json.JSONDecodeError, TypeError):
                data = None
    if isinstance(data, dict):
        summary = str(data.get("summary") or "").strip()
        explanation = str(data.get("explanation") or "").strip()
        if summary:
            return summary, explanation
    # Fallback: treat the whole reply as the summary.
    return cleaned.strip(), ""


def _is_valid(risk_result: dict[str, Any], summary: str, explanation: str) -> bool:
    """Apply language discipline + Critical-safety checks."""
    combined = "%s\n%s" % (summary, explanation)
    violations = check_language(combined)
    if violations:
        logger.warning("LLM output rejected (banned phrasing): %s", violations)
        return False
    if risk_result.get("overall_risk_level") == "Critical":
        if _CRITICAL_SOFTEN_RE.search(combined):
            logger.warning("LLM output rejected (would soften a Critical verdict)")
            return False
    return True


def _resolve_cfg(cfg: Optional[dict[str, Any]]) -> dict[str, Any]:
    if cfg is not None:
        return cfg
    return {
        "base_url": getattr(config, "LLM_BASE_URL", ""),
        "api_key": getattr(config, "LLM_API_KEY", ""),
        "model": getattr(config, "LLM_MODEL", ""),
        "timeout": getattr(config, "LLM_TIMEOUT", 12),
        "max_tokens": getattr(config, "LLM_MAX_TOKENS", 400),
        "temperature": getattr(config, "LLM_TEMPERATURE", 0.2),
    }


def enhance(risk_result: dict[str, Any], text: str,
            cfg: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Return an enhanced {"summary", "explanation", "model"} or None.

    Never raises. Returns None whenever the layer is disabled, misconfigured,
    times out, fails, or produces output that violates the safety checks.
    """
    if cfg is None and not is_enabled():
        return None
    resolved = _resolve_cfg(cfg)
    url = _endpoint(resolved.get("base_url", ""))
    model = (resolved.get("model") or "").strip()
    if not url or not model:
        logger.warning("LLM enhancer skipped: missing base URL or model")
        return None

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(risk_result, text)},
        ],
        "temperature": resolved.get("temperature", 0.2),
        "max_tokens": resolved.get("max_tokens", 400),
    }
    try:
        resp = requests.post(url, headers=_headers(resolved), json=payload,
                             timeout=resolved.get("timeout", 12))
        resp.raise_for_status()
        api_json = resp.json()
    except Exception as exc:  # timeout, connection, HTTP, JSON, ...
        logger.warning("LLM enhancer request failed: %s", exc)
        return None

    content = _extract_content(api_json)
    if not content:
        logger.warning("LLM enhancer returned no usable content")
        return None

    summary, explanation = _parse_content(content)
    if not summary or not _is_valid(risk_result, summary, explanation):
        return None

    return {
        "summary": summary,
        "explanation": explanation,
        "model": model,
    }

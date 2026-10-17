"""Optional LLM phrasing for Role C messages (off unless --llm and a key is set).

The deterministic policy decides everything: who is notified, where, priority,
water source and every number. The model may only *rephrase* the template
messages. Its output is accepted only if it passes validate_rewrite(); otherwise
the template text is used unchanged. Standard library only (no SDK), so it
installs on s390x / LinuxONE.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any, Callable

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"  # override with AGENT_MODEL
SMS_MAX_CHARS = 160
MAX_MESSAGE_CHARS = 600
LANG_PREFIX = {"id": "Simulasi", "en": "Simulation"}  # alerts stay labelled as simulated
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

SYSTEM_PROMPT = (
    "You rephrase short bilingual (Indonesian 'id', English 'en') peat-fire alert messages for "
    "Indonesian response agencies. You receive FACTS and TEMPLATE messages. Rewrite each message "
    "so it reads naturally for its audience, keeping every fact. Rules: use only numbers, "
    "coordinates and place details that appear in FACTS or TEMPLATE; never invent or change a "
    "number, coordinate, distance or place; every message must still begin with 'Simulasi' (id) "
    "or 'Simulation' (en); the 'mpa' message is an SMS of at most 160 characters; keep the same "
    "audience keys. Reply with ONLY a JSON object: {audience: {\"id\": ..., \"en\": ...}}. "
    "No markdown, no commentary."
)

Post = Callable[[dict[str, Any]], str]


def numbers_in(text: str) -> set[float]:
    return {round(float(token), 4) for token in _NUMBER.findall(text)}


def validate_rewrite(
    candidate: Any,
    template: dict[str, dict[str, str]],
    facts: dict[str, Any],
) -> str | None:
    """Return None if the candidate is safe to use, else a short reason."""
    if not isinstance(candidate, dict) or set(candidate) != set(template):
        return "audience keys differ from the template"
    allowed = numbers_in(json.dumps(facts, ensure_ascii=False)) | numbers_in(
        json.dumps(template, ensure_ascii=False)
    )
    for audience, message in candidate.items():
        if not isinstance(message, dict) or set(message) != {"id", "en"}:
            return f"{audience}: needs exactly id and en"
        for lang, prefix in LANG_PREFIX.items():
            text = message[lang]
            if not isinstance(text, str) or not text.strip():
                return f"{audience}.{lang}: empty"
            if len(text) > MAX_MESSAGE_CHARS:
                return f"{audience}.{lang}: too long"
            if not text.strip().startswith(prefix):
                return f"{audience}.{lang}: must start with '{prefix}'"
            invented = numbers_in(text) - allowed
            if invented:
                return f"{audience}.{lang}: numbers not in the facts: {sorted(invented)}"
            if audience == "mpa" and len(text.strip()) > SMS_MAX_CHARS:
                return f"{audience}.{lang}: SMS over {SMS_MAX_CHARS} characters"
    return None


def _parse_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


def _http_post(api_key: str, timeout: float) -> Post:
    def post(payload: dict[str, Any]) -> str:
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
        return "".join(block.get("text", "") for block in body["content"] if block.get("type") == "text")

    return post


def make_rewriter(
    *,
    api_key: str | None = None,
    model: str | None = None,
    post: Post | None = None,
    timeout: float = 25.0,
    log: Callable[[str], None] = print,
) -> Callable[[str, dict[str, Any], dict[str, dict[str, str]]], dict[str, dict[str, str]]] | None:
    """Build a rewriter, or None when no key / transport is available."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if post is None:
        if not key:
            return None
        post = _http_post(key, timeout)
    model_name = model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL)

    def rewrite(action: str, ctx: dict[str, Any], template: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        payload = {
            "model": model_name,
            "max_tokens": 1000,
            "system": SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": json.dumps(
                    {"ACTION": action, "FACTS": ctx, "TEMPLATE": template}, ensure_ascii=False
                ),
            }],
        }
        try:
            candidate = _parse_json(post(payload))
        except Exception as exc:  # network, auth, bad JSON: never block a dispatch
            log(f"C: LLM unavailable for {action} ({type(exc).__name__}); using templates")
            return template
        reason = validate_rewrite(candidate, template, ctx)
        if reason:
            log(f"C: LLM rewrite rejected for {action} ({reason}); using templates")
            return template
        return {
            audience: {"id": message["id"].strip(), "en": message["en"].strip()}
            for audience, message in candidate.items()
        }

    return rewrite

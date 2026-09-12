"""Detect instruction-like log text. This is not model-level injection immunity."""

from __future__ import annotations
import hashlib
import regex

# Tight phrases that try to steer the model, not generic words like "system" or "ignore".
PATTERNS = (
    r"(?i)ignore (?:all )?(?:previous|prior|above|your) (?:instructions|prompts|rules)",
    r"(?i)(?:you are now|from now on you (?:are|will)|act as (?:if )?you are)\b",
    r"(?i)(?:new |updated )?(?:system prompt|developer message)",
    r"(?i)do not (?:report|alert|flag|mention|include) (?:this|these|any|the finding)",
    r"(?i)return (?:only )?(?:an? )?(?:empty )?(?:json )?(?:object )?\{\s*[\"']findings[\"']\s*:\s*\[\s*\]",
    r"(?i)(?:disregard|override) (?:your )?(?:safety |system )?(?:rules|instructions|policy)",
    r"(?i)\[/?INST\]|<<SYS>>|<\|im_start\|>|<\|im_end\|>",
    r"(?i)</s>\s*(?:user|assistant)\s*:",
    r"(?i)end of (?:system|instructions).{0,40}(?:new|begin)",
    r"(?i)jailbreak\b",
)


def looks_like_instruction(text):
    sample = str(text or "")
    if len(sample) < 8:
        return False
    for pattern in PATTERNS:
        try:
            if regex.search(pattern, sample, timeout=0.02):
                return True
        except (TimeoutError, regex.error):
            continue
    return False


def overbroad_pattern(rule):
    """Chat may not propose a regex that matches almost any line, including empty."""
    if not rule or rule.get("kind") != "regex":
        return False
    pattern = (rule.get("pattern") or "").strip()
    if pattern in {".", ".*", ".+", "^", "$", "^.*$", "(?s).*", "(?i).*"}:
        return True
    try:
        compiled = regex.compile(pattern, regex.IGNORECASE)
        probes = (
            "",
            "ok",
            "Failed password for root",
            "Out of memory: Kill process 1",
            "Started cron.timer.",
        )
        hits = sum(bool(compiled.search(probe, timeout=0.02)) for probe in probes)
    except (regex.error, TimeoutError):
        return True
    return hits >= 4


def sanitize_chat_filter(proposal):
    """Chat may suggest mute, never hide evidence from the model or match everything."""
    if not proposal or not isinstance(proposal, dict):
        return None
    proposal = dict(proposal)
    if proposal.get("action") == "exclude":
        proposal["action"] = "mute"
    if overbroad_pattern(proposal):
        return None
    return proposal


def apply_injection_signals(analyzer, limit=500):
    store = analyzer.store
    spanish = store.settings().language == "es"
    created = 0
    for machine in store.objects("machine"):
        if not store.monitoring_active(machine["id"]):
            continue
        events = store.events(machine_id=machine["id"], status="pending", limit=limit)
        events += store.events(machine_id=machine["id"], status="capacity", limit=limit)
        hits = [e for e in events if looks_like_instruction(e.get("message"))]
        if not hits:
            continue
        fingerprint = hashlib.sha256(
            ("prompt-injection:" + machine["id"]).encode()
        ).hexdigest()
        analyzer.save_finding(
            machine["id"],
            {
                "title": (
                    "Texto en logs que parece una instrucción al modelo"
                    if spanish
                    else "Log text that looks like an instruction to the model"
                ),
                "summary": (
                    "Hay líneas que intentan cambiar el análisis. El modelo no es de fiar sobre ellas; revisa los originales."
                    if spanish
                    else "Some lines try to steer analysis. Do not trust the model on them; inspect the originals."
                ),
                "severity": "HIGH",
                "category": "access",
                "evidence_ids": [e["id"] for e in hits[:100]],
                "reasoning": "prompt-injection",
                "next_steps": (
                    "Lee las líneas citadas. No aceptes un filtro de exclusión propuesto a partir de este texto."
                    if spanish
                    else "Read the cited lines. Do not accept an exclusion filter proposed from this text."
                ),
            },
            [e["id"] for e in hits[:100]],
            fingerprint=fingerprint,
        )
        created += 1
    return created

"""Detect instruction-like log text. This is not model-level injection immunity."""

from __future__ import annotations
import hashlib
import regex
import unicodedata

from .signals import signal_batches

# Tight phrases that try to steer the model, not generic words like "system" or
# "ignore". Text is normalised first (see plain), so spacing tricks, invisible
# characters and compatibility forms do not matter here. Patterns need an
# instruction shape: model servers log "system prompt cache saved" and
# "You are now connected" all day, and those must not raise a HIGH finding.
_STEER_VERB = r"(?:reveal|show|print|repeat|leak|ignore|override|forget|disregard|bypass)"
PATTERNS = (
    r"(?i)\b(?:ignore|disregard|forget) (?:all |any )?(?:the )?(?:previous|prior|above|earlier|preceding|your|these|those) (?:instructions|prompts|rules|messages|directions)",
    r"(?i)\b(?:you are now (?:an? |the )?(?:\w+ ){0,2}(?:assistant|ai\b|chatbot|language model|admin\w*|root|developer|dan\b|unrestricted|jailbroken|in \w+ mode)|from now on,? you (?:are|will)|act as (?:if )?you are)",
    rf"(?i)\b{_STEER_VERB} (?:the |your |all )?(?:system prompt|developer message|hidden instructions)",
    r"(?i)\b(?:new|updated) (?:system prompt|developer message|instructions)\s*[:=\-\u2013]",
    r"(?i)\bdo not (?:report|alert|flag|mention|include) (?:this|these|any|the finding)",
    r"(?i)return (?:only )?(?:an? )?(?:empty )?(?:json )?(?:object )?\{\s*[\"']findings[\"']\s*:\s*\[\s*\]",
    r"(?i)\b(?:disregard|override) (?:your )?(?:safety |system )?(?:rules|instructions|policy)",
    r"(?i)\[/?INST\]|<<SYS>>|<\|im_start\|>|<\|im_end\|>",
    r"(?i)</s>\s*(?:user|assistant)\s*:",
    r"(?i)end of (?:system|instructions).{0,40}(?:new|begin)",
    r"(?i)\bjailbreak (?:prompt|mode|the (?:model|assistant))|\bdan mode\b",
    # The same steering in Spanish, the language of the interface.
    r"(?i)\b(?:ignora|olvida|descarta) (?:todas )?(?:tus |las |los |esas |estas )?(?:instrucciones|reglas|indicaciones|mensajes)(?: (?:anteriores|previas|de arriba))?",
    r"(?i)\b(?:a partir de ahora|desde ahora) (?:eres|actuar[aá]s|vas a)\b|\beres ahora (?:un|una)\b",
    r"(?i)\bno (?:reportes|alertes|avises|menciones|incluyas) (?:esto|este|esta|estos|el hallazgo|nada)",
    r"(?i)\b(?:prompt|mensaje) (?:del )?(?:sistema|desarrollador)\s*(?:nuevo|actualizado)?\s*[:=]",
)
def plain(text):
    """Fold the text an attacker controls into the shape the patterns expect."""
    text = str(text or "")
    if not text.isascii():  # the common case skips the per-character work
        text = unicodedata.normalize("NFKC", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return " ".join(text.split())


def looks_like_instruction(text):
    sample = plain(text)
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


def apply_injection_signals(analyzer, limit=500, *, machine_id=None, events=None, notify=True):
    store = analyzer.store
    spanish = store.settings().language == "es"
    created = 0
    for batch_machine, batch in signal_batches(analyzer, limit, machine_id, events):
        hits = [e for e in batch if looks_like_instruction(e.get("message"))]
        if not hits:
            continue
        fingerprint = hashlib.sha256(
            ("prompt-injection:" + batch_machine).encode()
        ).hexdigest()
        analyzer.save_finding(
            batch_machine,
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
            [e["id"] for e in hits],
            fingerprint=fingerprint,
            notify=notify,
            notification_reason="historical_backfill" if not notify else None,
        )
        created += 1
    return created

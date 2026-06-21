"""Claude-powered relationship intelligence.

Every function degrades gracefully: if no ANTHROPIC_API_KEY is configured (or
a call fails), a deterministic rule-based fallback is returned so the product
keeps working. AI is an enhancement, never a hard dependency.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from . import models, warmth
from .config import settings

logger = logging.getLogger("networking.ai")

_client = None


def _get_client():
    """Lazily build the Anthropic client. Returns None if unavailable."""
    global _client
    if not settings.ai_enabled:
        return None
    if _client is None:
        try:
            import anthropic

            _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        except Exception as exc:  # pragma: no cover - import/credential issues
            logger.warning("Anthropic client unavailable: %s", exc)
            return None
    return _client


# ── Prompt context building ──────────────────────────────────────────────────


def _contact_context(contact: models.Contact) -> str:
    """A compact, AI-readable digest of everything known about a contact."""
    lines: list[str] = []
    lines.append(f"Name: {contact.full_name}")
    lines.append(f"Relationship: {contact.relationship_type.value}")
    lines.append(f"Desired contact cadence: {contact.contact_frequency.value}")
    if contact.company or contact.position:
        lines.append(
            f"Role: {contact.position or '?'} at {contact.company or '?'}"
        )
    if contact.location:
        lines.append(f"Location: {contact.location}")
    if contact.birth_date:
        lines.append(f"Birthday: {contact.birth_date.isoformat()}")

    socials = {
        "Instagram": contact.instagram_url,
        "LinkedIn": contact.linkedin_url,
        "Facebook": contact.facebook_url,
        "Twitter/X": contact.twitter_url,
        "Website": contact.website_url,
    }
    socials = {k: v for k, v in socials.items() if v}
    if socials:
        lines.append("Social: " + ", ".join(f"{k} {v}" for k, v in socials.items()))

    if contact.tags:
        lines.append("Tags: " + ", ".join(t.name for t in contact.tags))
    if contact.notes:
        lines.append(f"Notes: {contact.notes}")

    score, status = warmth.compute_warmth(contact)
    elapsed = round(warmth.days_since_last_contact(contact))
    lines.append(
        f"Relationship warmth: {score}/100 ({status}); "
        f"{elapsed} days since last contact."
    )

    if contact.key_dates:
        lines.append("Key dates:")
        for kd in contact.key_dates:
            lines.append(f"  - {kd.date.isoformat()}: {kd.label}")

    if contact.interactions:
        lines.append("Recent interactions (newest first):")
        for itx in contact.interactions[:8]:
            when = itx.occurred_at.date().isoformat()
            lines.append(
                f"  - {when} [{itx.channel.value}/{itx.direction.value}] "
                f"sentiment={itx.sentiment:+.1f}: {itx.summary or '(no summary)'}"
            )

    if contact.life_events:
        lines.append("Known life events:")
        for ev in contact.life_events[:6]:
            when = ev.event_date.isoformat() if ev.event_date else "?"
            lines.append(f"  - {when} {ev.event_type}: {ev.title}")

    if contact.social_snapshots:
        lines.append("Social snapshots captured:")
        for snap in contact.social_snapshots[:4]:
            text = (snap.raw_text or snap.title or "").strip().replace("\n", " ")
            lines.append(f"  - {snap.platform} ({snap.url}): {text[:300]}")

    return "\n".join(lines)


def _extract_text(response) -> str:
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def _extract_json(response) -> dict | list | None:
    text = _extract_text(response)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Be forgiving: pull the first {...} or [...] block.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
    return None


# ── Public API ───────────────────────────────────────────────────────────────


def generate_dossier(contact: models.Contact) -> str:
    """A short, warm intelligence brief on the person."""
    client = _get_client()
    if client is None:
        return _fallback_dossier(contact)

    system = (
        "You are a thoughtful networking assistant who helps the user nurture "
        "genuine relationships. Write concise, human dossiers — never creepy, "
        "never salesy. Base everything strictly on the data given; do not invent "
        "facts. If information is missing, say what would be worth learning."
    )
    prompt = (
        "Write a short relationship dossier (120–200 words) for the contact "
        "below. Cover: who they are, the state and trajectory of the "
        "relationship, and 2–3 concrete things to keep in mind when engaging. "
        "Plain prose, no headings.\n\n"
        f"{_contact_context(contact)}"
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=1200,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(resp)
        return text or _fallback_dossier(contact)
    except Exception as exc:  # pragma: no cover - network/runtime
        logger.warning("generate_dossier failed: %s", exc)
        return _fallback_dossier(contact)


_RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "should_contact": {"type": "boolean"},
        "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
        "channel": {
            "type": "string",
            "enum": ["call", "message", "email", "meeting", "social", "event", "other"],
        },
        "timing": {"type": "string"},
        "reason": {"type": "string"},
        "talking_points": {"type": "array", "items": {"type": "string"}},
        "draft_message": {"type": "string"},
    },
    "required": [
        "should_contact",
        "urgency",
        "channel",
        "timing",
        "reason",
        "talking_points",
        "draft_message",
    ],
    "additionalProperties": False,
}


def recommend_outreach(contact: models.Contact) -> dict:
    """Structured advice on whether/how/when to reach out, plus a draft."""
    client = _get_client()
    if client is None:
        return _fallback_recommendation(contact)

    system = (
        "You are a networking strategist. Give practical, specific outreach "
        "advice grounded only in the provided data. Drafts should sound like "
        "the user wrote them: warm, natural, brief. Respond with JSON only."
    )
    prompt = (
        "Based on the contact below, decide whether the user should reach out "
        "now, through which channel, when, and why. Provide 2–4 talking points "
        "and a ready-to-send draft message (2–4 sentences).\n\n"
        f"{_contact_context(contact)}"
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=1500,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": _RECOMMENDATION_SCHEMA}
            },
        )
        data = _extract_json(resp)
        if isinstance(data, dict):
            data["source"] = "ai"
            return data
    except Exception as exc:  # pragma: no cover
        logger.warning("recommend_outreach failed: %s", exc)
    return _fallback_recommendation(contact)


def suggest_event_message(contact: models.Contact, event: models.LifeEvent) -> str:
    """A short congratulatory / supportive message for a life event."""
    client = _get_client()
    if client is None:
        return _fallback_event_message(contact, event)

    system = (
        "You write short, sincere, personal messages for meaningful moments. "
        "No clichés, no emojis unless natural, match a warm friendly tone."
    )
    prompt = (
        f"Write a 1–3 sentence message to {contact.full_name} about this event:\n"
        f"  {event.event_type}: {event.title}\n"
        f"  {event.description or ''}\n\n"
        f"Relationship: {contact.relationship_type.value}."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_text(resp) or _fallback_event_message(contact, event)
    except Exception as exc:  # pragma: no cover
        logger.warning("suggest_event_message failed: %s", exc)
        return _fallback_event_message(contact, event)


_EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
                "required": ["event_type", "title", "description", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


def detect_life_events(contact: models.Contact, snapshot: models.SocialSnapshot) -> list[dict]:
    """Read a social snapshot and extract candidate life events.

    Returns a list of dicts: {event_type, title, description, confidence}.
    """
    client = _get_client()
    if client is None:
        return []
    text = (snapshot.raw_text or snapshot.title or "").strip()
    if not text:
        return []

    system = (
        "You detect meaningful life events from social media text — new job, "
        "promotion, relocation, marriage/engagement, new baby, a launch, an "
        "award, a loss. Only report events clearly supported by the text. "
        "Respond with JSON only."
    )
    prompt = (
        f"Contact: {contact.full_name} ({contact.relationship_type.value}).\n"
        f"Source: {snapshot.platform} — {snapshot.url}\n\n"
        f"Content:\n{text[:4000]}\n\n"
        "List any significant life events you can confidently detect."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=1200,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": _EVENTS_SCHEMA}
            },
        )
        data = _extract_json(resp)
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return data["events"]
    except Exception as exc:  # pragma: no cover
        logger.warning("detect_life_events failed: %s", exc)
    return []


# ── Rule-based fallbacks (used when AI is unavailable) ────────────────────────


def _fallback_dossier(contact: models.Contact) -> str:
    score, status = warmth.compute_warmth(contact)
    elapsed = round(warmth.days_since_last_contact(contact))
    role = ""
    if contact.position or contact.company:
        role = f" — {contact.position or 'works'} at {contact.company or 'an organisation'}"
    bits = [
        f"{contact.full_name} is a {contact.relationship_type.value} contact{role}.",
        f"The relationship is currently {status} ({score}/100); it has been about "
        f"{elapsed} days since your last contact, and your target cadence is "
        f"{contact.contact_frequency.value}.",
    ]
    if contact.notes:
        bits.append(f"Notes on file: {contact.notes}")
    if warmth.is_due(contact):
        bits.append("They are due for a check-in — a light, genuine message would help.")
    bits.append("(Add an Anthropic API key to generate richer AI dossiers.)")
    return " ".join(bits)


def _fallback_recommendation(contact: models.Contact) -> dict:
    due = warmth.is_due(contact)
    ratio = warmth.overdue_ratio(contact)
    urgency = "high" if ratio >= 2 else "medium" if due else "low"
    channel = "message"
    if contact.relationship_type in (models.Relationship.client, models.Relationship.investor):
        channel = "email"
    elif contact.relationship_type in (models.Relationship.friend, models.Relationship.family):
        channel = "call"

    first = contact.first_name
    draft = (
        f"Hi {first}, you popped into my mind today — it's been a while. "
        "How are things going? Would love to catch up soon."
    )
    points = ["Ask an open question about their current focus."]
    if contact.company:
        points.append(f"Reference their work at {contact.company}.")
    if contact.birth_date:
        points.append("Remember their birthday is on file.")

    return {
        "should_contact": due,
        "urgency": urgency,
        "channel": channel,
        "timing": "this week" if due else "no rush",
        "reason": (
            f"It's been {round(warmth.days_since_last_contact(contact))} days; "
            f"target cadence is {contact.contact_frequency.value}."
        ),
        "talking_points": points,
        "draft_message": draft,
        "source": "rule-based",
    }


def _fallback_event_message(contact: models.Contact, event: models.LifeEvent) -> str:
    return (
        f"Hi {contact.first_name}, I just heard about {event.title.lower()} — "
        "congratulations, that's wonderful news! Really happy for you."
    )

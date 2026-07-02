"""Claude-powered relationship intelligence.

Every function degrades gracefully: if no ANTHROPIC_API_KEY is configured (or
a call fails), a deterministic rule-based fallback is returned so the product
keeps working. AI is an enhancement, never a hard dependency.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from app import models, warmth
from app.core.config import settings

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
    if contact.tone:
        lines.append(f"Preferred communication tone: {contact.tone}")
    if contact.notes:
        lines.append(f"Notes: {contact.notes}")

    current_facts = [f for f in getattr(contact, "facts", []) if f.is_current]
    if current_facts:
        lines.append("Known facts (current):")
        for fct in current_facts[:20]:
            lines.append(f"  - [{fct.fact_type.value}] {fct.value}")

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


_SENTIMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {"type": "number"},
        }
    },
    "required": ["scores"],
    "additionalProperties": False,
}


def score_sentiments(texts: list[str]) -> list[float]:
    """Score the tone of each text in [-1, 1] (warm/positive → +1).

    Batched into a single Claude call for efficiency. Returns 0.0 for every
    item when AI is unavailable or on any error (neutral, never blocks sync).
    """
    if not texts:
        return []
    client = _get_client()
    if client is None:
        return [0.0] * len(texts)

    numbered = "\n".join(f"{i+1}. {t[:400]}" for i, t in enumerate(texts))
    system = (
        "You rate the emotional tone of short interaction snippets (emails, "
        "meeting titles, chat messages) from the point of view of relationship "
        "warmth. Return a JSON array 'scores' with one number per item in the "
        "same order, each between -1 (cold/negative/conflict) and 1 "
        "(warm/positive/friendly); 0 is neutral or purely transactional."
    )
    prompt = f"Rate these {len(texts)} items:\n{numbered}"
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": _SENTIMENT_SCHEMA}
            },
        )
        data = _extract_json(resp)
        if isinstance(data, dict) and isinstance(data.get("scores"), list):
            scores = data["scores"]
            out: list[float] = []
            for i in range(len(texts)):
                try:
                    out.append(max(-1.0, min(1.0, float(scores[i]))))
                except (IndexError, TypeError, ValueError):
                    out.append(0.0)
            return out
    except Exception as exc:  # pragma: no cover
        logger.warning("score_sentiments failed: %s", exc)
    return [0.0] * len(texts)


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


def _dialogue_history(contact: models.Contact, limit: int = 12) -> str:
    """Recent message exchange with this contact, oldest first, labeled by
    speaker — the raw material for mimicking the user's own voice."""
    msgs = [
        i
        for i in contact.interactions
        if i.channel == models.Channel.message and i.summary
    ][:limit]
    if not msgs:
        return "(немає історії листування)"
    lines = []
    for i in reversed(msgs):  # interactions are newest-first on the model
        who = "Я" if i.direction == models.Direction.outbound else contact.first_name
        when = i.occurred_at.strftime("%d.%m")
        lines.append(f"[{when}] {who}: {i.summary}")
    return "\n".join(lines)


def draft_reply(contact: models.Contact, incoming_text: str) -> str | None:
    """Draft a reply to an incoming Telegram DM, in the user's own voice.

    Returns None when AI is unavailable or fails — the caller then shows the
    incoming message to the admin without a draft (never a canned reply).
    """
    client = _get_client()
    if client is None:
        return None

    system = (
        "Ти пишеш відповіді в Telegram ВІД ІМЕНІ користувача (Степана). "
        "Пиши так, як пише він сам — уважно дивись на його попередні репліки "
        "в історії та копіюй його стиль, лексику, довжину речень і емодзі. "
        "1–3 речення, без формальних привітань і підписів, природна "
        "месенджерна мова. Відповідай МОВОЮ співрозмовника. Верни ЛИШЕ текст "
        "повідомлення, без лапок і пояснень."
    )
    prompt = (
        f"{_contact_context(contact)}\n\n"
        f"Історія листування:\n{_dialogue_history(contact)}\n\n"
        f"Нове повідомлення від {contact.first_name}:\n«{incoming_text}»\n\n"
        "Напиши відповідь від Степана."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(resp).strip().strip('"«»')
        return text or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("draft_reply failed: %s", exc)
        return None


def draft_outreach(contact: models.Contact, reason: str) -> str | None:
    """Draft a proactive first-touch Telegram message (outreach queue).

    Grounded in the full relationship context; written in the user's own
    voice. Returns None when AI is unavailable — the queue card then asks
    the user to write manually."""
    client = _get_client()
    if client is None:
        return None

    system = (
        "Ти пишеш перше повідомлення в Telegram ВІД ІМЕНІ користувача "
        "(Степана), щоб відновити контакт з людиною. Пиши так, як пише він "
        "сам — дивись на його репліки в історії і копіюй стиль, лексику та "
        "емодзі. 1–3 речення, тепло і природно, без формальностей і без "
        "вибачень за паузу, якщо це не доречно. Якщо є свіжий привід "
        "(подія, факт) — обіграй його. Відповідай мовою, якою вони "
        "листувалися. Верни ЛИШЕ текст повідомлення."
    )
    prompt = (
        f"{_contact_context(contact)}\n\n"
        f"Історія листування:\n{_dialogue_history(contact)}\n\n"
        f"Привід написати зараз: {reason}\n\n"
        f"Напиши повідомлення від Степана до {contact.first_name}."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(resp).strip().strip('"«»')
        return text or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("draft_outreach failed: %s", exc)
        return None


_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "company": {"type": "string"},
        "position": {"type": "string"},
        "note": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": [
                            "role",
                            "employer",
                            "location",
                            "interest",
                            "family",
                            "relationship",
                            "preference",
                            "other",
                        ],
                    },
                    "value": {"type": "string"},
                },
                "required": ["fact_type", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["name", "first_name", "last_name", "company", "position", "note", "facts"],
    "additionalProperties": False,
}


def parse_voice_intake(text: str) -> dict | None:
    """Turn a dictated note ("познайомився з Андрієм, робить фінтех...")
    into structured contact data: name, company/position, facts, note.
    Returns None when AI is off or nothing useful was extracted."""
    client = _get_client()
    if client is None or not text.strip():
        return None

    system = (
        "Ти асистент нетворкінг-CRM. Користувач надиктував нотатку про людину "
        "(нове знайомство або оновлення). Витягни структуровано: ім'я людини, "
        "компанію/посаду якщо є, стабільні факти (інтереси, локація, сім'я, "
        "домовленості) і коротку нотатку-резюме. Пиши значення мовою нотатки. "
        "Поля, яких немає в нотатці, лиши порожніми рядками. Respond with "
        "JSON only."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": f"Нотатка:\n{text}"}],
            output_config={
                "format": {"type": "json_schema", "schema": _INTAKE_SCHEMA}
            },
        )
        data = _extract_json(resp)
        if isinstance(data, dict) and (data.get("name") or "").strip():
            return data
    except Exception as exc:  # pragma: no cover - network
        logger.warning("parse_voice_intake failed: %s", exc)
    return None


_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["contact_id", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


def search_network(query: str, corpus: list[str]) -> list[dict] | None:
    """Natural-language search over the user's own network.

    ``corpus`` is one compact line per contact ("id | name | role | facts…").
    Returns [{contact_id, why}] ranked by relevance (why = one transparent
    sentence, the Happenstance pattern), or None when AI is unavailable."""
    client = _get_client()
    if client is None:
        return None

    system = (
        "Ти шукаєш людей у особистій мережі користувача. Нижче — по одному "
        "рядку на контакт. Поверни до 8 найрелевантніших запиту контактів, "
        "для кожного — one-line пояснення 'чому' мовою запиту, спираючись "
        "ЛИШЕ на надані дані. Якщо збігів немає — порожній список. "
        "Respond with JSON only."
    )
    prompt = "Запит: " + query + "\n\nМережа:\n" + "\n".join(corpus)
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=1500,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": _SEARCH_SCHEMA}
            },
        )
        data = _extract_json(resp)
        if isinstance(data, dict) and isinstance(data.get("matches"), list):
            return data["matches"]
    except Exception as exc:  # pragma: no cover - network
        logger.warning("search_network failed: %s", exc)
    return None


_TRANSLATE_LANGS = {
    "en": "англійську",
    "cs": "чеську",
    "ru": "російську",
    "uk": "українську",
}


def translate_message(text: str, lang: str) -> str | None:
    """Translate a drafted messenger message, preserving its casual tone,
    emoji and length. Returns None when AI is unavailable or fails."""
    client = _get_client()
    if client is None or not text.strip():
        return None
    language = _TRANSLATE_LANGS.get(lang, lang)

    system = (
        "Ти перекладаєш коротке месенджерне повідомлення. Збережи неформальний "
        "тон, емодзі та довжину — це має звучати природно для носія мови, а не "
        "як машинний переклад. Верни ЛИШЕ перекладений текст."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=600,
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": f"Переклади на {language}:\n\n{text}",
                }
            ],
        )
        out = _extract_text(resp).strip().strip('"«»')
        return out or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("translate_message failed: %s", exc)
        return None


def refine_reply(
    contact: models.Contact, current_draft: str, instruction: str
) -> str | None:
    """Rewrite a drafted message according to the user's instruction
    (typed or transcribed from a voice note)."""
    client = _get_client()
    if client is None:
        return None

    system = (
        "Ти редагуєш чернетку Telegram-повідомлення від імені користувача "
        "(Степана). Збережи його стиль — коротко, природно, месенджерно. "
        "Верни ЛИШЕ фінальний текст повідомлення, без лапок і пояснень."
    )
    prompt = (
        f"Кому: {contact.full_name}"
        + (f" (тон: {contact.tone})" if contact.tone else "")
        + f"\n\nПоточна чернетка:\n«{current_draft}»\n\n"
        f"Інструкція від Степана: {instruction}\n\n"
        "Перепиши чернетку згідно з інструкцією."
    )
    try:
        resp = client.messages.create(
            model=settings.ai_model,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(resp).strip().strip('"«»')
        return text or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("refine_reply failed: %s", exc)
        return None


_FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": [
                            "role",
                            "employer",
                            "location",
                            "interest",
                            "family",
                            "relationship",
                            "preference",
                            "other",
                        ],
                    },
                    "value": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
                "required": ["fact_type", "value", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}


def extract_facts(contact: models.Contact) -> list[dict]:
    """Read everything known about a contact and extract durable facts.

    Returns a list of {fact_type, value, confidence}. Only facts clearly
    supported by the data are returned; empty on any error or when AI is off.
    This is the consolidation step: episodic history → semantic facts.
    """
    client = _get_client()
    if client is None:
        return []

    system = (
        "You extract durable, stable facts about a person from a relationship "
        "CRM record — role, employer, location, interests, family, key "
        "relationships and communication preferences. Only report facts clearly "
        "supported by the data. Each fact must be a short, standalone statement "
        "(e.g. 'Works at Acme as CTO', 'Lives in Berlin', 'Into trail running'). "
        "Do not invent anything. Respond with JSON only."
    )
    prompt = (
        "From the contact record below, extract the stable facts worth "
        "remembering long-term. Skip transient chatter and one-off events.\n\n"
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
                "format": {"type": "json_schema", "schema": _FACTS_SCHEMA}
            },
        )
        data = _extract_json(resp)
        if isinstance(data, dict) and isinstance(data.get("facts"), list):
            return [f for f in data["facts"] if f.get("value")]
    except Exception as exc:  # pragma: no cover
        logger.warning("extract_facts failed: %s", exc)
    return []


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

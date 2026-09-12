"""Чисті функції протоколу: версії, токен, конверти JSON-RPC, вибір JSON/SSE.

Без БД і без FastAPI — усе це юніт-тестується напряму. Транспорт у router.py
лише склеює ці шматки.
"""

from __future__ import annotations

import json
import re

#: Найновіша — перша: вона дефолт, коли клієнт просить невідому версію.
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

#: 32 байти з криптографічного генератора у hex. Перевіряти ДО запиту в БД:
#: порожнє чи сміттєве значення інакше могло б зматчитись із чужим ключем.
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")

SERVER_INFO = {"name": "networking_ai", "title": "Networking AI", "version": "1.0.0"}

INSTRUCTIONS = (
    "Це персональний CRM власника: люди, памʼять про них, пошта, задачі, цілі.\n"
    "Порядок роботи, коли треба щось написати людині:\n"
    "1) crm_get_owner_voice — як пише власник (стиль і правила);\n"
    "2) crm_get_contact_memory — усе, що система памʼятає про людину: досьє, "
    "факти, історія, свіжі дописи;\n"
    "3) напиши текст САМ, у голосі власника, тією ж мовою, що й співрозмовник;\n"
    "4) crm_save_message_draft або crm_save_email_draft — збережи дослівно, "
    "система нічого не переписує;\n"
    "5) після реальної відправки — crm_log_interaction.\n"
    "Жоден інструмент тут не витрачає AI-кредити застосунку: генерація — твоя "
    "робота. Факти не вигадуй: пиши лише те, що є в памʼяті або сказав власник. "
    "Перед незворотною дією (crm_send_email_draft) покажи текст людині. "
    "Ідентифікатори у відповідях мають вигляд #12 — передавай їх назад як є."
)


def negotiate_version(requested: str | None) -> str:
    """Ехо версії клієнта, якщо ми її знаємо; інакше наша найновіша."""
    if requested in SUPPORTED_VERSIONS:
        return requested
    return SUPPORTED_VERSIONS[0]


def valid_token_format(token: str | None) -> bool:
    return bool(token) and bool(TOKEN_RE.match(token))


def wants_sse(accept: str | None) -> bool:
    """SSE — лише коли клієнт НЕ приймає JSON, а лише потік подій.

    Простий JSON надійніший: напіввідкриті потоки крізь nginx — зайвий клас
    проблем, тож віддаємо його всюди, де можна.
    """
    value = (accept or "").lower()
    if "application/json" in value or "*/*" in value:
        return False
    return "text/event-stream" in value


def rpc_result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def rpc_error(req_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def tool_ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def tool_fail(text: str) -> dict:
    """Помилка ІНСТРУМЕНТА — всередині result, не помилка протоколу.

    Так Claude бачить причину і виправляється сам, а клієнт не рве зʼєднання.
    """
    return {"content": [{"type": "text", "text": text}], "isError": True}


def is_notification(message: dict) -> bool:
    return isinstance(message, dict) and "id" not in message


def sse_frame(payload: dict) -> str:
    return f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def validate_tool_specs(tools: list[dict]) -> list[str]:
    """Статична перевірка схем: кожен required існує, імена унікальні."""
    problems: list[str] = []
    seen: set[str] = set()
    for spec in tools:
        name = spec.get("name", "")
        if not name or not re.match(r"^[a-z][a-z0-9_]*$", name):
            problems.append(f"bad tool name: {name!r}")
        if name in seen:
            problems.append(f"duplicate tool name: {name}")
        seen.add(name)
        schema = spec.get("inputSchema") or {}
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in props:
                problems.append(f"{name}: required {req!r} is not in properties")
        if schema.get("type") != "object":
            problems.append(f"{name}: inputSchema.type must be 'object'")
        if "description" not in spec:
            problems.append(f"{name}: missing description")
    return problems

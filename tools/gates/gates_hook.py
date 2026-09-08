#!/usr/bin/env python3
"""Хуки Claude Code, які тримають відкриті ворота перед очима.

Три режими:

  session  SessionStart      — тягне ворота з сервісу і кладе їх у контекст сесії
  prompt   UserPromptSubmit  — щоразу підкладає актуальний список із кешу
  stop     Stop (async)      — оновлює кеш у фоні й пінгає Telegram про застояні

Мережу чіпають тільки `session` і `stop`. `prompt` читає локальний кеш, тому
жоден твій запит не чекає на HTTP.

Хук завжди завершується кодом 0: зламаний або недоступний сервіс не має
блокувати роботу в редакторі.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

HOME = pathlib.Path.home() / ".claude"
CONFIG = HOME / "gates.env"
CACHE = HOME / "gates.cache.json"
NUDGE_STAMP = HOME / "gates.nudged"
TIMEOUT = 5
#: Не пінгати Telegram частіше, ніж раз на стільки годин (сервер має свій ліміт).
NUDGE_EVERY_HOURS = 6
STALE_HOURS = 24


def config() -> tuple[str, str] | None:
    base = os.environ.get("GATES_API_BASE", "").rstrip("/")
    key = os.environ.get("GATES_API_KEY", "")
    if not CONFIG.exists():
        return (base, key) if base and key else None
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if name.strip() == "GATES_API_BASE" and not base:
            base = value.rstrip("/")
        elif name.strip() == "GATES_API_KEY" and not key:
            key = value
    return (base, key) if base and key else None


def call(method: str, path: str):
    cfg = config()
    if cfg is None:
        return None
    base, key = cfg
    request = urllib.request.Request(
        f"{base}{path}",
        method=method,
        data=b"" if method == "POST" else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else None


def refresh_cache() -> list[dict]:
    gates = call("GET", "/api/gates") or []
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(gates, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return gates


def read_cache() -> list[dict]:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def block(gates: list[dict]) -> str:
    """Текст, який бачить Claude. Порожній рядок — коли говорити нема про що."""
    if not gates:
        return ""
    lines = ["ВОРОТА (задачі поза кодом, які висять на власнику):"]
    for gate in gates:
        days = gate.get("age_hours", 0) // 24
        age = f"{days} дн" if days else f"{gate.get('age_hours', 0)} год"
        goal = f" Блокує ціль: {gate['goal']}." if gate.get("goal") else ""
        lines.append(f"- [{gate['uid']}] {gate['text']} — висить {age}.{goal}")
    stale = [g for g in gates if g.get("age_hours", 0) >= STALE_HOURS]
    if stale:
        lines.append(
            "Є ворота старші за добу — почни відповідь рядком за правилом "
            "ВОРОТА з CLAUDE.md, до основної відповіді."
        )
    return "\n".join(lines)


def should_nudge() -> bool:
    try:
        last = NUDGE_STAMP.stat().st_mtime
    except OSError:
        return True
    return time.time() - last > NUDGE_EVERY_HOURS * 3600


def stamp_nudge() -> None:
    try:
        NUDGE_STAMP.parent.mkdir(parents=True, exist_ok=True)
        NUDGE_STAMP.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    # Хуки отримують JSON на stdin; нам він не потрібен, але прочитати треба,
    # щоб не лишати процес із заповненим буфером.
    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        if mode == "session":
            text = block(refresh_cache())
            if text:
                print(text)
        elif mode == "prompt":
            text = block(read_cache())
            if text:
                print(text)
        elif mode == "stop":
            gates = refresh_cache()
            stale = [g for g in gates if g.get("age_hours", 0) >= STALE_HOURS]
            if stale and should_nudge():
                call("POST", "/api/gates/nudge")
                stamp_nudge()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        # Сервіс лежить або немає мережі — мовчимо, робота в редакторі триває.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

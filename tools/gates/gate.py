#!/usr/bin/env python3
"""gate — завести «ворота»: задачу, яку не зробиш у редакторі коду.

Ворота падають у той самий список задач, що й усе інше, і одразу штовхаються
в Telegram. Прив'язка до цілі не обов'язкова, але саме вона робить нагадування
дієвим: «зроби скринкаст» ігнорується, «скринкаст блокує підключення
клієнтів» — ні.

    gate "зробити скринкаст" --goal "підключення клієнтів"
    gate --list
    gate --done ab12cd34

Налаштування читаються з ~/.claude/gates.env:
    GATES_API_BASE=https://твій-домен
    GATES_API_KEY=...
Ключ ніде більше не зберігається і в репозиторій не потрапляє.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

CONFIG = pathlib.Path.home() / ".claude" / "gates.env"
TIMEOUT = 10


def load_config() -> tuple[str, str]:
    base = os.environ.get("GATES_API_BASE", "")
    key = os.environ.get("GATES_API_KEY", "")
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip('"').strip("'")
            if name == "GATES_API_BASE" and not base:
                base = value
            elif name == "GATES_API_KEY" and not key:
                key = value
    if not base or not key:
        raise SystemExit(
            f"Немає налаштувань. Створи {CONFIG} з рядками:\n"
            "GATES_API_BASE=https://твій-домен\nGATES_API_KEY=..."
        )
    return base.rstrip("/"), key


def call(method: str, path: str, payload: dict | None = None):
    base, key = load_config()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate", description="Ворота: задачі поза кодом")
    parser.add_argument("text", nargs="*", help="Що треба зробити")
    parser.add_argument("--goal", default=None, help="Ціль, яку це блокує (частина назви)")
    parser.add_argument("--project", default=None, help="Проєкт")
    parser.add_argument("--list", action="store_true", help="Показати відкриті ворота")
    parser.add_argument("--done", metavar="UID", help="Закрити ворота")
    args = parser.parse_args(argv)

    try:
        if args.done:
            gate = call("POST", f"/api/gates/{args.done}/done")
            print(f"Закрито: {gate['text']}")
            return 0

        if args.list or not args.text:
            gates = call("GET", "/api/gates") or []
            if not gates:
                print("Відкритих воріт немає.")
                return 0
            for gate in gates:
                days = gate["age_hours"] // 24
                age = f"{days} дн" if days else f"{gate['age_hours']} год"
                goal = f" -> {gate['goal']}" if gate.get("goal") else ""
                print(f"{gate['uid']}  {gate['text']}{goal}  ({age})")
            return 0

        gate = call(
            "POST",
            "/api/gates",
            {
                "text": " ".join(args.text),
                "goal": args.goal,
                "project": args.project,
            },
        )
        goal = f" -> {gate['goal']}" if gate.get("goal") else ""
        print(f"Ворота заведено: {gate['uid']}  {gate['text']}{goal}")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Сервіс недоступний: {exc.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

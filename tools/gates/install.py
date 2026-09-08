#!/usr/bin/env python3
"""Ставить ворота в Claude Code: скрипти, хуки і правило в CLAUDE.md.

    python tools/gates/install.py --base https://твій-домен --key <API_KEY>

Що робить:
  1. копіює gate.py і gates_hook.py у ~/.claude/
  2. пише ~/.claude/gates.env з базою і ключем (тільки для власника, 0600)
  3. додає три хуки в ~/.claude/settings.json, не чіпаючи наявні
  4. вставляє блок правила у ~/.claude/CLAUDE.md між маркерами gates

Запускати можна повторно: блок правила і хуки замінюються, а не дублюються.
Ключ ніколи не потрапляє в репозиторій — він живе тільки в gates.env.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home() / ".claude"
SETTINGS = HOME / "settings.json"
CLAUDE_MD = HOME / "CLAUDE.md"
START, END = "<!-- gates:start -->", "<!-- gates:end -->"

HOOK_EVENTS = {
    "SessionStart": {"mode": "session", "async": False},
    "UserPromptSubmit": {"mode": "prompt", "async": False},
    "Stop": {"mode": "stop", "async": True},
}


def hook_entry(python: str, script: pathlib.Path, mode: str, is_async: bool) -> dict:
    entry = {
        "type": "command",
        "command": f'"{python}" "{script}" {mode}',
        "timeout": 15,
    }
    if is_async:
        entry["async"] = True
    return entry


def is_ours(entry: dict) -> bool:
    return "gates_hook.py" in str(entry.get("command", ""))


def patch_settings(python: str, script: pathlib.Path) -> None:
    settings: dict = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError:
            backup = SETTINGS.with_suffix(".json.bak")
            shutil.copy2(SETTINGS, backup)
            print(f"settings.json не читається як JSON; копія: {backup}")
            settings = {}

    hooks = settings.setdefault("hooks", {})
    for event, cfg in HOOK_EVENTS.items():
        groups = hooks.setdefault(event, [])
        # Прибираємо свої попередні записи, чужі лишаємо як є.
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if not is_ours(h)]
        groups[:] = [g for g in groups if g.get("hooks")]
        groups.append(
            {"hooks": [hook_entry(python, script, cfg["mode"], cfg["async"])]}
        )

    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Хуки прописані: {SETTINGS}")


def patch_claude_md() -> None:
    rule = (HERE / "CLAUDE.gates.md").read_text(encoding="utf-8").strip()
    current = CLAUDE_MD.read_text(encoding="utf-8") if CLAUDE_MD.exists() else ""
    if START in current and END in current:
        head, _, rest = current.partition(START)
        _, _, tail = rest.partition(END)
        updated = f"{head.rstrip()}\n\n{rule}\n{tail.lstrip()}"
    else:
        updated = f"{current.rstrip()}\n\n{rule}\n" if current.strip() else rule + "\n"
    CLAUDE_MD.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_MD.write_text(updated, encoding="utf-8")
    print(f"Правило ВОРОТА у {CLAUDE_MD}")


def write_env(base: str, key: str) -> None:
    path = HOME / "gates.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"GATES_API_BASE={base.rstrip('/')}\nGATES_API_KEY={key}\n", encoding="utf-8"
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows — права керуються інакше
    print(f"Налаштування: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Встановити ворота в Claude Code")
    parser.add_argument("--base", required=True, help="https://твій-домен")
    parser.add_argument("--key", required=True, help="API_KEY сервісу")
    args = parser.parse_args()

    HOME.mkdir(parents=True, exist_ok=True)
    for name in ("gate.py", "gates_hook.py"):
        shutil.copy2(HERE / name, HOME / name)
    print(f"Скрипти: {HOME / 'gate.py'}, {HOME / 'gates_hook.py'}")

    write_env(args.base, args.key)
    patch_settings(sys.executable, HOME / "gates_hook.py")
    patch_claude_md()

    print(
        "\nГотово. Перевір:\n"
        f'  "{sys.executable}" "{HOME / "gate.py"}" "тестові ворота"\n'
        f'  "{sys.executable}" "{HOME / "gate.py"}" --list\n'
        "Далі відкрий нову сесію Claude Code — ворота підтягнуться в контекст."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

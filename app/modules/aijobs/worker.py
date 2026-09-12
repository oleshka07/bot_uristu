"""Воркер: бере задачу з черги і запускає `claude -p` через наш MCP.

Запуск — лише коли є робота. Порожній цикл нічого не коштує: жодного
системного промпта, жодних схем інструментів. Це головна причина, чому
воркер за подією дешевший за «опитувати раз на 10 хвилин».

Гальма, які тримають квоту підписки під контролем: пауза з панелі, тихі
години, стеля запусків на годину, одна задача за раз, `--model sonnet` за
замовчуванням і профіль MCP на 5–8 інструментів замість усіх.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import SessionLocal

from . import brain, prompts
from . import service as jobs

logger = logging.getLogger("networking.worker")

MCP_SERVER_NAME = "networking"
#: Вбудовані інструменти Claude Code, які воркеру не потрібні і небезпечні.
DISALLOWED = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Read", "Glob", "Grep"]


def mcp_url(db) -> str | None:
    """Адреса нашого MCP зсередини docker-мережі. Токен береться з БД."""
    from app.modules.mcp import service as mcp

    token = mcp.current_token(db) or mcp.issue_token(db)
    base = settings.mcp_internal_url.rstrip("/")
    return f"{base}/mcp/{token}"


def write_mcp_config(url: str, profile: str) -> str:
    """Тимчасовий JSON для --mcp-config; профіль у query обмежує tools/list."""
    cfg = {"mcpServers": {MCP_SERVER_NAME: {"type": "http", "url": f"{url}?profile={profile}"}}}
    fd, path = tempfile.mkstemp(prefix="mcp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return path


def build_command(prompt: str, config_path: str) -> list[str]:
    cmd = [
        settings.claude_code_bin,
        "-p", prompt,
        "--output-format", "json",
        "--model", settings.claude_code_model,
        "--max-turns", str(settings.claude_code_max_turns),
        "--mcp-config", config_path,
        "--strict-mcp-config",
        "--allowedTools", f"mcp__{MCP_SERVER_NAME}",
        "--disallowedTools", ",".join(DISALLOWED),
        "--append-system-prompt", prompts.COMMON,
    ]
    return cmd


def parse_result(stdout: str) -> dict:
    """Толерантний розбір відповіді claude -p --output-format json.

    Повертає {"ok": bool, "text": str, "usage": {...}}. Якщо stdout не JSON —
    вважаємо текст результатом, а запуск успішним лише коли текст не порожній.
    """
    text = (stdout or "").strip()
    if not text:
        return {"ok": False, "text": "", "usage": {}}
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        # stream-json чи зайві рядки: беремо останній JSON-обʼєкт у виводі
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except ValueError:
                    continue
    if not isinstance(data, dict):
        return {"ok": True, "text": text[:4000], "usage": {}}
    usage = {
        k: data.get(k)
        for k in ("total_cost_usd", "usage", "num_turns", "duration_ms", "duration_api_ms", "session_id")
        if data.get(k) is not None
    }
    result_text = str(data.get("result") or "")
    return {"ok": not bool(data.get("is_error")), "text": result_text[:4000], "usage": usage}


def run_claude(prompt: str, profile: str, url: str) -> dict:
    config_path = write_mcp_config(url, profile)
    try:
        env = dict(os.environ)
        env.setdefault("HOME", "/home/worker")
        proc = subprocess.run(
            build_command(prompt, config_path),
            capture_output=True,
            text=True,
            timeout=settings.claude_code_timeout,
            env=env,
        )
    except FileNotFoundError:
        return {"ok": False, "text": f"{settings.claude_code_bin} не знайдено в контейнері", "usage": {}}
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": f"claude не відповів за {settings.claude_code_timeout}с", "usage": {}}
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass
    parsed = parse_result(proc.stdout)
    if proc.returncode != 0 and not parsed["text"]:
        parsed = {"ok": False, "text": (proc.stderr or "")[-2000:] or f"код виходу {proc.returncode}", "usage": {}}
    elif proc.returncode != 0:
        parsed["ok"] = False
    return parsed


def can_run_now(db) -> tuple[bool, str]:
    if brain.mode() != "claude_code":
        return False, f"режим {brain.mode()}"
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return False, "немає CLAUDE_CODE_OAUTH_TOKEN"
    if jobs.is_paused(db):
        return False, "пауза"
    if jobs.in_quiet_hours():
        return False, "тихі години"
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    if jobs.runs_since(db, hour_ago) >= settings.aijobs_max_per_hour:
        return False, "стеля запусків на годину"
    return True, ""


def process_one(db) -> bool:
    """Одна задача. True — щось зробили (є сенс не спати перед наступною)."""
    job = jobs.claim_next(db)
    if job is None:
        return False
    payload = jobs.payload_of(job)
    prompt, profile = prompts.build(job.kind, payload)
    url = mcp_url(db)
    logger.info("job %s %s attempt %s", job.id, job.kind, job.attempts)
    result = run_claude(prompt, profile, url)

    if result["ok"]:
        jobs.complete(db, job, backend="claude_code", result=result["text"], usage=result["usage"])
        return True

    logger.warning("job %s failed: %s", job.id, result["text"][:300])
    if jobs.fail(db, job, result["text"], retry_in=90):
        return True
    # Спроби вичерпано — відкат на API, якщо дозволено.
    if (settings.background_ai_fallback or "").lower() == "api":
        try:
            report = brain.execute_via_api(db, job.kind, payload)
            jobs.complete(db, job, backend="api", result=f"[відкат на API] {report}", usage={})
        except Exception as exc:  # pragma: no cover
            db.rollback()
            job.status = "failed"
            job.error = f"{job.error}\nвідкат на API теж впав: {exc}"[:2000]
            db.commit()
    return True


def run_forever(poll_seconds: int = 5) -> None:
    logger.info("worker up: mode=%s model=%s", brain.mode(), settings.claude_code_model)
    last_note = ""
    while True:
        try:
            with SessionLocal() as db:
                jobs.requeue_stale(db)
                ok, why = can_run_now(db)
                if not ok:
                    if why != last_note:
                        logger.info("worker idle: %s", why)
                        last_note = why
                    time.sleep(30)
                    continue
                last_note = ""
                busy = process_one(db)
            time.sleep(1 if busy else poll_seconds)
        except KeyboardInterrupt:  # pragma: no cover
            raise
        except Exception as exc:  # pragma: no cover - воркер не має падати
            logger.exception("worker loop error: %s", exc)
            time.sleep(15)

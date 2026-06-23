# Networking AI

A personal **relationship intelligence** service. It keeps a database of your
contacts, builds an AI dossier on each person, scores how "warm" each
relationship is, and tells you **who to reach out to today and what to say** —
powered by Claude (`claude-opus-4-8`).

> Status: working MVP. Runs locally in one command; deploys to your Hetzner
> server with Docker Compose. Social scraping ships as a connector framework
> (generic public-page fetch today; authenticated connectors plug in later).

---

## What it does

- **Contact database** — full profiles: relationship type, desired contact
  cadence, birthday, phone/email/messengers, every social link, key dates,
  tags and notes.
- **Warmth engine** — turns interaction history + your target cadence into a
  0–100 warmth score (`hot / warm / cooling / cold`) per contact.
- **Daily dashboard** — a short list of people you should contact today, ranked
  by how overdue and how cold they are, plus upcoming birthdays/key dates and
  newly detected life events.
- **AI dossier** — Claude writes a concise brief on each person from their data.
- **Outreach suggestions** — whether/how/when to reach out, talking points, and
  a ready-to-send draft message.
- **Gmail + Calendar auto-sync** — connect your Google account and real emails
  and meetings with your contacts become interactions automatically (with AI
  tone scoring), so warmth reflects reality with zero manual logging.
- **Chater import** — pull contacts and Telegram message history straight from
  your existing Chater bot's PostgreSQL database (schema auto-detected).
- **Telegram** — receive the daily digest in Telegram and query your network
  with a command bot (`/today`, `/due`, `/find`).
- **Daily automation** — an optional scheduler refreshes warmth, syncs Google,
  imports nothing destructive, and sends your digest by email and/or Telegram.
- **Social import** — paste a profile/post URL to capture a snapshot; the AI
  scans it for significant life events (new job, move, baby, launch…) and
  suggests congratulations messages. A scraping provider can be plugged in for
  JS-heavy networks (Instagram/LinkedIn).
- **Graceful without AI** — no API key? It falls back to rule-based
  recommendations so the product still works.

---

## Detailed guides

- **`docs/SETUP_GOOGLE.md`** — click-by-click Google Cloud OAuth setup.
- **`docs/DEPLOY_HETZNER.md`** — deploy to Hetzner with Caddy auto-HTTPS and
  GitHub Actions auto-deploy, coexisting with the Chater bot.
- **`docs/AUTONOMY.md`** — how to grant the assistant safe, autonomous
  deploy/config access without exposing secrets.
- **`docs/CHATER_BRIDGE.md`** — single-bot setup: the existing Chater bot pulls
  `GET /api/digest/text` and serves networking commands (no second bot).
- **`docs/PR_WORKFLOW.md`** — optional PR-mode + branch protection so changes
  are reviewed before they auto-deploy.

> **Public deployment?** Set `APP_PASSWORD` (and optionally `API_KEY`) so the
> whole site + API require login. The Chater bridge authenticates with
> `X-API-Key`. With `APP_PASSWORD` empty, auth is off (local dev only).

## Architecture

```
Browser SPA  ──>  FastAPI (/api)  ──>  PostgreSQL
 (static/)         │
                   ├── warmth.py     relationship scoring (pure functions)
                   ├── ai.py         Claude integration (+ rule-based fallback)
                   ├── social.py     social connector framework
                   └── dashboard.py  daily suggestions & stats
```

- **Backend:** FastAPI + SQLAlchemy 2.0. JSON API under `/api`.
- **Database:** PostgreSQL in production (SQLite for instant local runs).
- **AI:** the official `anthropic` SDK; structured outputs for recommendations,
  prose for dossiers.
- **Frontend:** a self-contained vanilla-JS single-page app served by the
  backend — no Node build step.

The data model is deliberately AI-friendly: a contact's entire story
(profile + interactions + key dates + life events + social snapshots) lives in
one object graph that the AI reads to reason about the relationship.

---

## Quick start (local, no Postgres needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # optional: add ANTHROPIC_API_KEY for AI features
python -m app.seed            # optional: load sample contacts
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. The API docs are at `/docs`.

Without `ANTHROPIC_API_KEY` set, AI buttons return rule-based results and the
sidebar shows **AI off**. Add the key to `.env` to enable Claude.

---

## Run with Docker Compose (Postgres)

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY, POSTGRES_PASSWORD, etc.
docker compose up --build
```

App on <http://localhost:8000>, Postgres data persisted in the `pgdata` volume.

---

## Deploy to Hetzner

On the server (Docker + Docker Compose installed):

```bash
git clone <this-repo> && cd bot_uristu
cp .env.example .env
# Edit .env: set a strong POSTGRES_PASSWORD and your ANTHROPIC_API_KEY.
docker compose up -d --build
```

Then point a reverse proxy (Caddy / Nginx / Traefik) with TLS at
`web:8000`, or expose `WEB_PORT` directly. Tables are created automatically on
startup. To load demo data once: `docker compose exec web python -m app.seed`.

---

## Configuration (`.env`)

| Variable               | Default                | Purpose                                   |
| ---------------------- | ---------------------- | ----------------------------------------- |
| `ANTHROPIC_API_KEY`    | _(empty)_              | Enables Claude features.                  |
| `AI_MODEL`             | `claude-opus-4-8`      | Model used for AI.                        |
| `DATABASE_URL`         | sqlite (local)         | Compose overrides with Postgres.          |
| `DAILY_SUGGESTIONS`    | `5`                    | People suggested per day.                 |
| `UPCOMING_WINDOW_DAYS` | `14`                   | Look-ahead for birthdays/key dates.       |
| `CORS_ORIGINS`         | `*`                    | Allowed origins.                          |
| `GOOGLE_CLIENT_ID/SECRET` | _(empty)_           | Enables Gmail + Calendar sync.            |
| `GOOGLE_REDIRECT_URI`  | localhost callback     | Must match the OAuth client exactly.      |
| `SYNC_WINDOW_DAYS`     | `120`                  | How far back to pull email/calendar.      |
| `SCHEDULER_ENABLED`    | `false`                | Run the daily job in-process.             |
| `DAILY_RUN_HOUR`       | `8`                    | Server hour for the daily job.            |
| `DIGEST_EMAIL_TO`      | account email          | Where to send the daily digest.           |
| `SCRAPER_PROVIDER/KEY` | _(empty)_              | Scraping API for JS-heavy social pages.   |

---

## Gmail + Calendar auto-sync

1. In [Google Cloud Console](https://console.cloud.google.com/) create a
   project, **enable the Gmail API and Google Calendar API**, and create an
   OAuth **Web application** client.
2. Add your redirect URI to the client (must match `GOOGLE_REDIRECT_URI`):
   - local: `http://localhost:8000/api/integrations/google/callback`
   - prod: `https://your-domain/api/integrations/google/callback`
3. Put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env` and restart.
4. Open the app → **Integrations** → **Connect Google**, approve access.
5. Click **Sync now** (or let the daily job do it). Emails and meetings with
   any contact whose email is on file become interactions, tagged *via Gmail*
   / *via Calendar*, de-duplicated, and feed the warmth score.

Scopes requested: `gmail.readonly`, `gmail.send` (for the digest),
`calendar.readonly`, `userinfo.email`. The refresh token is stored in the
`integration_tokens` table.

## Daily automation

Set `SCHEDULER_ENABLED=true` to run a daily job at `DAILY_RUN_HOUR` that:
refreshes warmth → syncs Google → emails you a digest of who to contact.

For multi-process / cron-based setups, leave the scheduler off and run:

```bash
python -m app.run_daily          # or: docker compose exec web python -m app.run_daily
```

Trigger on demand from **Integrations → Run daily job**, or
`POST /api/maintenance/run-daily?send_digest=true`.

---

## Extending social connectors

`app/social.py` exposes a registry. To add an authenticated Instagram/LinkedIn
connector (official API, a scraping service, or your own), implement a
`func(url) -> SnapshotData` and register it:

```python
from app import social

def instagram_connector(url: str) -> social.SnapshotData:
    ...  # fetch via API/scraper, return SnapshotData(...)

social.register_connector("instagram", instagram_connector)
```

Everything else — storage, AI life-event detection, the UI — works unchanged.

---

## Project layout

```
app/
  main.py        FastAPI app + static hosting
  config.py      settings (.env)
  database.py    engine / session / Base
  models.py      SQLAlchemy models (the relationship graph)
  schemas.py     Pydantic request/response models
  crud.py        database operations
  warmth.py      relationship scoring engine
  ai.py          Claude integration + rule-based fallbacks
  social.py      social import connector framework (+ scraper provider)
  dashboard.py   daily suggestions & stats
  daily.py       the daily job (warmth + sync + digest)
  scheduler.py   background scheduler
  run_daily.py   cron entrypoint (python -m app.run_daily)
  migrations.py  idempotent schema reconciliation
  integrations/  Google Gmail + Calendar (OAuth + sync + send)
  seed.py        sample data
  routers/       API endpoints
  static/        single-page frontend
```

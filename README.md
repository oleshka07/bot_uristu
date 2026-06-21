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
- **Social import** — paste a profile/post URL to capture a snapshot; the AI
  scans it for significant life events (new job, move, baby, launch…) and
  suggests congratulations messages.
- **Graceful without AI** — no API key? It falls back to rule-based
  recommendations so the product still works.

---

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
  social.py      social import connector framework
  dashboard.py   daily suggestions & stats
  seed.py        sample data
  routers/       API endpoints
  static/        single-page frontend
```

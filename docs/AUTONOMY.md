# Giving the assistant safe autonomy

You asked me to run as much as possible autonomously, and to tell you how to
grant access **securely** — without exposing secrets. Here's the model and
exactly what to set up. The principle: **I write code; secrets live in GitHub
Actions secrets and on your server — never in chat, never in the repo, never
held by me.**

---

## What I can already do autonomously
- **Read/write code** in this repo and **push to GitHub**
  (`oleshka07/bot_uristu`). You've seen this — each step is a commit + push.
- Iterate, test, and document.

## What needs a one-time grant from you (then it's automatic)
Two pipelines make deploys and config autonomous after a single setup:

### 1) Auto-deploy on push  → set up GitHub Actions (see `docs/DEPLOY_HETZNER.md`)
Once the secrets below exist, **every commit I push deploys itself** to Hetzner.
I never touch the server directly and never see the key.

Add these repository secrets (GitHub → Settings → Secrets and variables →
Actions). Your browser agent can do this:

| Secret | What it is | How to get it safely |
|---|---|---|
| `SSH_PRIVATE_KEY` | CI deploy key (private half) | `ssh-keygen -t ed25519 -f ci_deploy -N ""` → paste the **private** file's contents here; put the **public** half in the server's `~/.ssh/authorized_keys`. This key is dedicated to deploys and can be revoked anytime by removing it from `authorized_keys`. |
| `SSH_HOST` | `46.225.132.220` | your server IP |
| `SSH_USER` | `root` | |
| `DEPLOY_PATH` | `/root/projects/networking-ai` | |
| `ENV_FILE` | full production `.env` contents | this is where **all app secrets live** (API keys, DB password, Google secret, Telegram token). GitHub encrypts secrets at rest and never prints them in logs. |

Why this is safe:
- Secrets are stored encrypted by GitHub and injected only into the runner at
  deploy time; they're masked in logs.
- The deploy key only grants SSH to deploy; scope it to the deploy user and
  revoke by deleting one line in `authorized_keys`.
- I author the workflow, but I cannot read the secret values back.

### 2) App configuration / `.env`  → the `ENV_FILE` secret
You don't need to give me write access to environment variables directly.
Instead, keep the single source of truth in the `ENV_FILE` secret. When you (or
your browser agent) update it and re-run the deploy, the new `.env` is written
on the server. If you'd rather I propose the exact `.env`, I'll generate the
full file content for you to paste into the secret — **with placeholders for the
actual secret values**, which you fill in. I never need the real values.

---

## If you ever want me to act on the server directly (not recommended)
The CI path above is safer and already fully autonomous. If you specifically
want me to run server commands myself, that requires handing this session a
private SSH key, which would mean a secret lives in the session. I'd rather not
hold long-lived secrets. If you choose to anyway, create a **dedicated,
revocable** deploy user/key with minimal rights and share it deliberately — and
rotate it afterwards.

---

## Secrets I will need from you (and where they go — not into chat)
Put each of these into the production `.env` / `ENV_FILE` secret. Don't paste
real values into the chat; placeholders are enough for me to wire things up.

| Variable | Purpose | Where to obtain |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude (dossiers, recs, sentiment) | console.anthropic.com |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Gmail + Calendar sync | `docs/SETUP_GOOGLE.md` |
| `CHATER_DATABASE_URL` | import Chater contacts + Telegram history | Chater's `.env` on the server |
| `TELEGRAM_BOT_TOKEN` | Networking AI digest + command bot | @BotFather (a **new** bot) |
| `TELEGRAM_CHAT_ID` | where to send your digest | @userinfobot, or `/getUpdates` |
| `POSTGRES_PASSWORD` | bundled DB password | choose a strong one |
| `DOMAIN` / `ACME_EMAIL` | HTTPS via Caddy | your DNS + email |

---

## TL;DR for your browser agent
1. Follow `docs/SETUP_GOOGLE.md` → get `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
2. Follow `docs/DEPLOY_HETZNER.md` section A → bootstrap the server once.
3. Add the GitHub Actions secrets in `docs/DEPLOY_HETZNER.md` section B.
4. From then on: I push → it deploys. You only touch secrets when they change.

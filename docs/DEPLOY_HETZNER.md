# Deploy to Hetzner (auto-HTTPS + auto-deploy)

This sets up Networking AI on your Hetzner VPS (`46.225.132.220`) alongside the
existing Chater bot, with:

- **Caddy** reverse proxy + automatic Let's Encrypt HTTPS,
- **GitHub Actions** that auto-deploys on every push (no manual `scp`),
- the bundled **PostgreSQL** for Networking AI's own data.

Chater keeps running untouched (it's a systemd Node service and doesn't use
ports 80/443, which Caddy will take). Networking AI runs in Docker under
`/root/projects/networking-ai`.

---

## A. One-time server bootstrap (≈10 min)

SSH into the server as root.

### 1. Install Docker (if not already present)
```bash
curl -fsSL https://get.docker.com | sh
docker compose version   # confirm the compose plugin is available
```

### 2. Make sure ports 80/443 are free
```bash
ss -ltnp | grep -E ':80 |:443 ' || echo "80/443 are free"
```
If something is listening (e.g. an old nginx), stop it. Chater itself does not
serve HTTP, so this is usually clear.

### 3. Create a read-only GitHub **deploy key** (so the server can pull)
```bash
ssh-keygen -t ed25519 -f ~/.ssh/networking_deploy -N "" -C "networking-ai-deploy"
cat ~/.ssh/networking_deploy.pub
```
Add the printed public key to the repo: GitHub → repo **Settings → Deploy keys
→ Add deploy key** (read-only is enough). Then tell git to use it:
```bash
cat >> ~/.ssh/config <<'EOF'
Host github-networking
  HostName github.com
  User git
  IdentityFile ~/.ssh/networking_deploy
  IdentitiesOnly yes
EOF
```

### 4. Clone the repo
```bash
mkdir -p /root/projects && cd /root/projects
git clone github-networking:oleshka07/bot_uristu.git networking-ai
cd networking-ai
git checkout claude/networking-ai-contact-service-o73dse
```

### 5. Create the production `.env`
```bash
cp .env.example .env
nano .env
```
Set at least:
```
DATABASE_URL=postgresql+psycopg://networking:CHANGE_ME@db:5432/networking
POSTGRES_PASSWORD=CHANGE_ME
ANTHROPIC_API_KEY=...
DOMAIN=networking.swipescape.eu          # the subdomain you'll point at the server
ACME_EMAIL=o.stepeniev@swipescape.eu
GOOGLE_CLIENT_ID=...                      # from docs/SETUP_GOOGLE.md
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://networking.swipescape.eu/api/integrations/google/callback
SCHEDULER_ENABLED=true
DAILY_RUN_HOUR=8
TELEGRAM_BOT_TOKEN=...                    # optional
TELEGRAM_CHAT_ID=...                      # optional
CHATER_DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/chater  # optional, see below
```

### 6. Point DNS at the server
Create an **A record**: `networking.swipescape.eu → 46.225.132.220`. Wait until
`dig +short networking.swipescape.eu` returns the IP (so Caddy can get a cert).

### 7. First launch
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose logs -f caddy   # watch it obtain the TLS certificate
```
Open `https://networking.swipescape.eu`. Load demo data once if you like:
```bash
docker compose exec web python -m app.seed
```

---

## B. Enable auto-deploy (GitHub Actions)

After the one-time bootstrap, every push to the branch redeploys automatically.

### 1. Create a deploy SSH key for GitHub Actions
On your machine (or the server), generate a separate key for CI and authorize it
on the server:
```bash
ssh-keygen -t ed25519 -f ci_deploy -N "" -C "github-actions"
ssh-copy-id -i ci_deploy.pub root@46.225.132.220   # or append ci_deploy.pub to ~/.ssh/authorized_keys
```

### 2. Add repository secrets
GitHub → repo **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret | Value |
|---|---|
| `SSH_HOST` | `46.225.132.220` |
| `SSH_USER` | `root` |
| `SSH_PRIVATE_KEY` | the **contents** of the `ci_deploy` private key file |
| `SSH_PORT` | `22` (optional) |
| `DEPLOY_PATH` | `/root/projects/networking-ai` |
| `ENV_FILE` | the entire contents of your production `.env` |

The workflow (`.github/workflows/deploy.yml`) writes `ENV_FILE` to `.env` on the
server, pulls the branch, and runs the prod compose. Secrets are never printed.

### 3. Trigger it
Push any commit (or run the workflow manually from the **Actions** tab). Watch
the run; on success the site updates within ~1–2 minutes.

---

## C. Connecting to the Chater database (optional but recommended)

Chater stores its data in PostgreSQL on the same server. To import its contacts
and Telegram history, set `CHATER_DATABASE_URL` to that database.

Find the connection details (check Chater's own `.env`, usually under
`/root/projects/chater/.env`). If Chater's Postgres listens on the host's
`localhost:5432`, the Networking AI **container** must reach the host. Two ways:

1. **Easiest** — use the server's LAN/host IP instead of `localhost`:
   ```
   CHATER_DATABASE_URL=postgresql+psycopg://chater_user:pass@172.17.0.1:5432/chater
   ```
   `172.17.0.1` is the default Docker bridge gateway (the host as seen from the
   container). Ensure Postgres `listen_addresses` and `pg_hba.conf` allow it, or
2. add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `web` service
   and use `host.docker.internal`.

Then: app → **Integrations → Chater → Inspect (dry run)** to confirm the schema
mapping, then **Import now**. Re-running is safe (idempotent).

> Read-only is enough — create a dedicated read-only Postgres user for Chater's
> DB if you want to be strict.

---

## D. Operations cheatsheet
```bash
cd /root/projects/networking-ai
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart web
docker compose exec web python -m app.run_daily      # run the daily job now
```

The Telegram command bot runs as the `bot` service automatically (idle until
`TELEGRAM_BOT_TOKEN` is set).

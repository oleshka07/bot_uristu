# Chater ↔ Networking AI bridge (single Telegram bot)

We use **one** Telegram bot — your existing **Chater**. Networking AI has no bot
of its own; it exposes an HTTP API on the same server, and Chater pulls from it.

```
Telegram ── Chater bot (grammY, systemd) ──HTTP──▶ Networking AI API
                                                   http://127.0.0.1:8002
```

Networking AI listens on `127.0.0.1:8002` (per the deployment). From Chater
(running on the host) it's reachable at `http://127.0.0.1:8002`.

Give this file to the Antigraviti agent — it adds a few lines to Chater.

---

## Endpoints Chater can call

| Method & path | Returns | Use |
|---|---|---|
| `GET /api/digest/text` | `{ "text": "<b>…</b>", "parse_mode": "HTML" }` | ready-to-send digest |
| `GET /api/dashboard` | full JSON (stats, suggestions, upcoming, events) | custom formatting |
| `POST /api/maintenance/run-daily` | runs warmth refresh + Google sync | call before the digest for fresh data |
| `GET /api/contacts?search=NAME` | contact list | `/find` style lookups |

No auth (localhost-only binding). If you later expose it publicly, add a shared
secret header — tell me and I'll add it.

---

## Minimal change in Chater (TypeScript / grammY)

Add a base URL to Chater's `.env`:
```
NETWORKING_AI_URL=http://127.0.0.1:8002
```

A small helper:
```ts
// src/networking.ts
const BASE = process.env.NETWORKING_AI_URL ?? "http://127.0.0.1:8002";

export async function networkingDigest(): Promise<string> {
  // Optional: refresh data first (warmth + Google sync). Ignore failures.
  try {
    await fetch(`${BASE}/api/maintenance/run-daily`, { method: "POST" });
  } catch (_) {}
  const res = await fetch(`${BASE}/api/digest/text`);
  if (!res.ok) throw new Error(`Networking AI ${res.status}`);
  const data = await res.json();
  return data.text as string; // already HTML-formatted
}
```

A new command:
```ts
// where other bot.command(...) handlers are registered
bot.command("network", async (ctx) => {
  try {
    const text = await networkingDigest();
    await ctx.reply(text, { parse_mode: "HTML", disable_web_page_preview: true });
  } catch (e) {
    await ctx.reply("Networking AI is unavailable right now.");
  }
});
```

That's the whole bridge: `/network` in your existing bot now shows “who to
contact today”, upcoming dates and detected life events.

---

## Fold it into the existing morning digest (recommended)

Chater already sends a digest at **07:30**. Append the networking section so
you get everything in one message. In that cron handler:

```ts
import { networkingDigest } from "./networking";

// after building Chater's own digest text:
try {
  const net = await networkingDigest();
  await bot.api.sendMessage(ADMIN_ID, net, { parse_mode: "HTML", disable_web_page_preview: true });
} catch (_) { /* Networking AI optional */ }
```

(If you'd rather have a single combined message, concatenate Chater's text and
`net` before sending.)

---

## What stays where
- **Chater**: the only Telegram bot; owns the chat UI, the morning cron, the
  Business-account proxy, Todoist/Notion.
- **Networking AI**: the relationship brain — contacts, warmth, dossiers,
  Gmail/Calendar sync, “who to contact”, life-event detection. Reached over
  HTTP; also has its own web dashboard at `https://networking.swipescape.eu`.

Deeper two-way features (e.g. Networking AI reading Chater's freshest messages
live, or writing back `contact_events`) come next, once the schema is mapped —
that work happens after Chater's `db_schema.sql` is reviewed.

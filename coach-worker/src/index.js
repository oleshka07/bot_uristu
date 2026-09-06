/** Персональний коуч по цілях: Telegram-бот + сторінка-дашборд.
 *
 * fetch()     — вебхук Telegram і HTML-сторінка з таблицею цілей.
 * scheduled() — щогодинний крон, який сам вирішує, чи час діяти за київським
 *               часом (питання о 16:00, нагадування о 22:00, саммері в суботу).
 */

import {
  askDaily,
  handleReply,
  nudge,
  statusReport,
  weeklySummary,
} from "./coach.js";
import { dashboardHtml } from "./dashboard.js";
import { parseGoals } from "./goals.js";
import { readGrid } from "./sheets.js";
import { sendMessage } from "./telegram.js";
import { localParts } from "./time.js";

const HELP = [
  "Команди:",
  "/ask — питання по цілі просто зараз",
  "/status — цифри по Pers, Work і разом",
  "/week — тижневе саммері зараз",
  "/site — посилання на сторінку з таблицею",
].join("\n");

/** Порівняння секретів без ранньої зупинки на першому різному символі. */
function safeEqual(a, b) {
  const x = String(a ?? "");
  const y = String(b ?? "");
  if (!x || !y || x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x.charCodeAt(i) ^ y.charCodeAt(i);
  return diff === 0;
}

function themeOf(rows) {
  for (const row of rows.slice(0, 12)) {
    for (const cell of row || []) {
      const value = String(cell ?? "").trim();
      if (value.toLowerCase().startsWith("тема року")) return value;
    }
  }
  return "";
}

async function renderDashboard(env, tz) {
  const { rows } = await readGrid(env);
  const { goals } = parseGoals(rows, { firstRowNumber: 1 });
  const p = localParts(new Date(), tz);
  const updatedAt = `${String(p.day).padStart(2, "0")}.${String(p.month).padStart(2, "0")}.${p.year} ${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
  return dashboardHtml(goals, { theme: themeOf(rows), updatedAt });
}

async function handleUpdate(env, update, origin) {
  const message = update?.message || update?.edited_message;
  const text = String(message?.text || "").trim();
  const chatId = String(message?.chat?.id || "");
  // Чужі чати — тиша, жодної відповіді назовні.
  if (!chatId || chatId !== String(env.ALLOWED_CHAT_ID)) return;
  if (!text) return;

  const now = new Date();
  const command = text.split(/\s+/)[0].toLowerCase().replace(/@.*$/, "");

  if (command === "/start" || command === "/help") {
    await sendMessage(env, HELP);
    return;
  }
  if (command === "/ask") {
    await askDaily(env, now, { force: true });
    return;
  }
  if (command === "/status") {
    await sendMessage(env, await statusReport(env));
    return;
  }
  if (command === "/week") {
    await weeklySummary(env, now);
    return;
  }
  if (command === "/site") {
    if (!env.DASHBOARD_TOKEN) {
      await sendMessage(env, "DASHBOARD_TOKEN не заданий — сторінка вимкнена.");
    } else {
      await sendMessage(env, `${origin}/dashboard?t=${env.DASHBOARD_TOKEN}`);
    }
    return;
  }
  if (command.startsWith("/")) {
    await sendMessage(env, HELP);
    return;
  }

  await handleReply(env, text, now);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const tz = env.TIMEZONE || "Europe/Kyiv";

    if (url.pathname === "/health") {
      return new Response("ok", { headers: { "content-type": "text/plain" } });
    }

    if (url.pathname === "/telegram" && request.method === "POST") {
      const given = request.headers.get("x-telegram-bot-api-secret-token");
      if (!safeEqual(given, env.WEBHOOK_SECRET)) {
        return new Response("forbidden", { status: 403 });
      }
      let update;
      try {
        update = await request.json();
      } catch {
        return new Response("bad request", { status: 400 });
      }
      // Telegram чекає 200 одразу, інакше повторює апдейт.
      ctx.waitUntil(
        handleUpdate(env, update, url.origin).catch(async (err) => {
          console.error("update failed", err);
          try {
            await sendMessage(env, `Збій обробки: ${String(err.message).slice(0, 200)}`);
          } catch {
            /* Telegram теж міг впасти — не роздуваємо помилку далі */
          }
        }),
      );
      return new Response("ok");
    }

    if (url.pathname === "/dashboard" || url.pathname === "/") {
      if (!env.DASHBOARD_TOKEN || !safeEqual(url.searchParams.get("t"), env.DASHBOARD_TOKEN)) {
        return new Response("forbidden", { status: 403 });
      }
      try {
        return new Response(await renderDashboard(env, tz), {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
          },
        });
      } catch (err) {
        return new Response(`Помилка таблиці: ${err.message}`, { status: 502 });
      }
    }

    // Одноразова реєстрація вебхука без ручного curl із токеном у консолі.
    if (url.pathname === "/admin/set-webhook" && request.method === "POST") {
      if (!env.DASHBOARD_TOKEN || !safeEqual(url.searchParams.get("t"), env.DASHBOARD_TOKEN)) {
        return new Response("forbidden", { status: 403 });
      }
      const res = await fetch(
        `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/setWebhook`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            url: `${url.origin}/telegram`,
            secret_token: env.WEBHOOK_SECRET,
            allowed_updates: ["message", "edited_message"],
          }),
        },
      );
      return new Response(await res.text(), { status: res.status });
    }

    return new Response("not found", { status: 404 });
  },

  async scheduled(event, env, ctx) {
    const now = new Date(event.scheduledTime || Date.now());
    const tz = env.TIMEZONE || "Europe/Kyiv";
    const p = localParts(now, tz);
    const askHour = Number(env.ASK_HOUR ?? 16);
    const nudgeHour = Number(env.NUDGE_HOUR ?? 22);
    const weeklyHour = Number(env.WEEKLY_HOUR ?? 9);

    const job = async () => {
      try {
        if (p.weekday === 6 && p.hour === weeklyHour) await weeklySummary(env, now);
        if (p.hour === askHour) await askDaily(env, now);
        if (p.hour === nudgeHour) await nudge(env, now);
      } catch (err) {
        console.error("scheduled failed", err);
        try {
          await sendMessage(env, `Збій за розкладом: ${String(err.message).slice(0, 200)}`);
        } catch {
          /* нічого не вдієш */
        }
      }
    };
    ctx.waitUntil(job());
  },
};

/** Наскрізний прогін: питання дня → відповідь власника → запис у таблицю.
 *
 * Мережа вся йде через fetch, тож підміняємо глобальний fetch і KV — і
 * перевіряємо реальні побічні ефекти, включно з клітинками, які бот пише.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";

import { askDaily, handleReply, weeklySummary } from "../src/coach.js";

function pem(der) {
  const b64 = Buffer.from(der).toString("base64").match(/.{1,64}/g).join("\n");
  return `-----BEGIN PRIVATE KEY-----\n${b64}\n-----END PRIVATE KEY-----\n`;
}

async function serviceAccountJson() {
  const pair = await webcrypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  );
  const der = await webcrypto.subtle.exportKey("pkcs8", pair.privateKey);
  return JSON.stringify({
    client_email: "coach@example.iam.gserviceaccount.com",
    private_key: pem(der),
  });
}

function fakeKv() {
  const store = new Map();
  return {
    store,
    async get(key) {
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      store.set(key, value);
    },
  };
}

const HEADER = ["На що впливає?", "Пріоритет", "Тип цілі", "Ціль", "Відп.", "Відп. #2", "Статус", "Коуч"];
const GRID = [
  ["Тема року: Здоровʼя. Комфорт. Гроші."],
  HEADER,
  ["Present", 100, "Work", "Аудит AI в бізнесі", "Олег", "", "in progress", "01.05.26: почав"],
  ["Future", 90, "Pers", "Прочитати 25 книг", "Олег", "", "not started", ""],
];

function harness({ claudeQueue }) {
  const sent = [];
  const writes = [];
  const claude = [...claudeQueue];

  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    const json = (body) => new Response(JSON.stringify(body), { status: 200 });

    if (url.startsWith("https://oauth2.googleapis.com/token")) {
      return json({ access_token: "test-token", expires_in: 3600 });
    }
    if (url.includes("/values:batchUpdate")) {
      writes.push(...JSON.parse(init.body).data);
      return json({ totalUpdatedCells: 1 });
    }
    if (url.includes("sheets.googleapis.com") && url.includes("/values/")) {
      return json({ values: GRID });
    }
    if (url.includes("sheets.googleapis.com")) {
      return json({ sheets: [{ properties: { title: "Цілі 2026" } }] });
    }
    if (url.startsWith("https://api.anthropic.com")) {
      return json(claude.shift() || { content: [{ type: "text", text: "ок" }] });
    }
    if (url.includes("api.telegram.org")) {
      sent.push(JSON.parse(init.body).text);
      return json({ ok: true });
    }
    throw new Error(`несподіваний запит: ${url}`);
  };

  return { sent, writes };
}

async function makeEnv() {
  return {
    SHEET_ID: "sheet-1",
    SHEET_TAB: "Цілі 2026",
    ALLOWED_CHAT_ID: "42",
    TIMEZONE: "Europe/Kyiv",
    TELEGRAM_BOT_TOKEN: "tg",
    ANTHROPIC_API_KEY: "sk-test",
    GOOGLE_SA_JSON: await serviceAccountJson(),
    COACH_KV: fakeKv(),
  };
}

test("питання дня йде по цілі, якої бот ще не торкався", async () => {
  const env = await makeEnv();
  const { sent } = harness({
    claudeQueue: [{ content: [{ type: "text", text: "Скільки книг прочитав цього тижня?" }] }],
  });
  const now = new Date("2026-09-07T13:00:00Z"); // 16:00 за Києвом

  const out = await askDaily(env, now);
  assert.equal(out.asked, "Прочитати 25 книг");
  assert.equal(sent.length, 1);
  assert.match(sent[0], /книг/);

  const state = JSON.parse(await env.COACH_KV.get("ask:current"));
  assert.equal(state.date, "2026-09-07");
  assert.equal(state.answered, false);
  assert.equal(state.row, 4); // 1-based рядок у аркуші
});

test("повторний крон о тій самій даті не питає вдруге", async () => {
  const env = await makeEnv();
  harness({ claudeQueue: [{ content: [{ type: "text", text: "питання" }] }] });
  const now = new Date("2026-09-07T13:00:00Z");
  await askDaily(env, now);
  const again = await askDaily(env, now);
  assert.equal(again.skipped, "вже питав сьогодні");
});

test("відповідь власника пише нотатку і змінює статус у потрібних клітинках", async () => {
  const env = await makeEnv();
  const { sent, writes } = harness({
    claudeQueue: [
      { content: [{ type: "text", text: "Що по книгах?" }] },
      {
        content: [
          { type: "tool_use", id: "t1", name: "save_progress", input: { summary: "прочитав дві книги" } },
          { type: "tool_use", id: "t2", name: "set_status", input: { status: "in progress" } },
        ],
      },
      { content: [{ type: "text", text: "Дві за тиждень — темп нижчий за план." }] },
    ],
  });
  const now = new Date("2026-09-07T13:00:00Z");

  await askDaily(env, now);
  const out = await handleReply(env, "прочитав дві книги, продовжую", now);

  assert.equal(out.handled, "Прочитати 25 книг");
  assert.equal(writes.length, 2);
  const ranges = writes.map((w) => w.range).sort();
  assert.deepEqual(ranges, ["'Цілі 2026'!G4", "'Цілі 2026'!H4"]);
  const note = writes.find((w) => w.range.endsWith("H4")).values[0][0];
  assert.equal(note, "07.09.26: прочитав дві книги");
  assert.equal(writes.find((w) => w.range.endsWith("G4")).values[0][0], "in progress");

  assert.match(sent.at(-1), /записав, статус → in progress/);
  assert.equal(JSON.parse(await env.COACH_KV.get("ask:current")).answered, true);
});

test("невідомий статус від моделі не потрапляє в таблицю", async () => {
  const env = await makeEnv();
  const { writes } = harness({
    claudeQueue: [
      { content: [{ type: "text", text: "Що по книгах?" }] },
      { content: [{ type: "tool_use", id: "t1", name: "set_status", input: { status: "готово" } }] },
      { content: [{ type: "text", text: "Не зрозумів статус." }] },
    ],
  });
  const now = new Date("2026-09-07T13:00:00Z");
  await askDaily(env, now);
  await handleReply(env, "готово", now);
  assert.equal(writes.length, 0);
});

test("тиждень без руху називається злитим прямим текстом", async () => {
  const env = await makeEnv();
  const { sent } = harness({
    claudeQueue: [{ content: [{ type: "text", text: "Тиждень злитий. У понеділок — одна ціль, один крок." }] }],
  });
  const now = new Date("2026-09-12T06:00:00Z"); // субота, 09:00 за Києвом

  // Знімок минулої суботи збігається з поточним — отже руху не було.
  await env.COACH_KV.put(
    "snapshot:last",
    JSON.stringify({
      date: "2026-09-05",
      map: { "аудит ai в бізнесі": "in progress", "прочитати 25 книг": "not started" },
    }),
  );

  const out = await weeklySummary(env, now);
  assert.equal(out.stalled, true);
  const text = sent.at(-1);
  assert.match(text, /Статуси за тиждень не змінилися/);
  assert.match(text, /Записів по жодній цілі за тиждень немає/);
  assert.match(text, /Pers: 1 цілей/);
  assert.match(text, /Разом: 2 цілей/);

  const snapshot = JSON.parse(await env.COACH_KV.get("snapshot:last"));
  assert.equal(snapshot.date, "2026-09-12");
});

test("сторінка малює три дашборди і таблицю за пріоритетом", async () => {
  const { parseGoals } = await import("../src/goals.js");
  const { dashboardHtml } = await import("../src/dashboard.js");
  const { goals } = parseGoals(GRID, { firstRowNumber: 1 });
  const html = dashboardHtml(goals, { theme: "Тема року: Тест", updatedAt: "07.09.2026 16:00" });

  assert.match(html, /Pers and Work/);
  assert.match(html, /Тема року: Тест/);
  // Ціль із пріоритетом 100 має стояти вище за ціль з 90.
  assert.ok(html.indexOf("Аудит AI") < html.indexOf("Прочитати 25 книг"));
  // Розмітка не має ламатися на лапках і кутових дужках із таблиці.
  assert.ok(!html.includes("<script"));
});

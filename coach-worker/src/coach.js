/** Сценарії коуча: питання дня, нагадування, тижневе саммері, розбір відповіді. */

import { runWithTools, messages, textOf } from "./claude.js";
import {
  ACTIVE_STATUSES,
  NOTES_COLUMN_LETTER,
  STATUSES,
  appendNote,
  diffSnapshots,
  goalKey,
  isActive,
  parseGoals,
  pickGoal,
  snapshotOf,
  statusSummary,
  touchedSince,
} from "./goals.js";
import { readGrid, writeCells } from "./sheets.js";
import { sendMessage } from "./telegram.js";
import { localIsoDate, noteDate, previousIsoDate } from "./time.js";

const CURRENT_KEY = "ask:current";
const SNAPSHOT_KEY = "snapshot:last";
const ASK_TTL = 60 * 60 * 24 * 120; // історія питань — чотири місяці

const PERSONA = [
  "Ти — особистий коуч власника по його річних цілях. Мова: українська.",
  "Пиши коротко, по суті, без емодзі, без лестощів і без вступів на кшталт «чудово».",
  "Ти не помічник із гарними словами, а той, хто щодня тисне на прогрес.",
  "Одне питання за раз. Формулюй конкретно, спирайся на попередні записи по цілі.",
].join(" ");

const TOOLS = [
  {
    name: "save_progress",
    description:
      "Записати прогрес по цілі в таблицю. Викликай на БУДЬ-ЯКУ змістовну відповідь власника про ціль.",
    input_schema: {
      type: "object",
      properties: {
        summary: {
          type: "string",
          description: "Суть відповіді, 3–15 слів, без дати і без емодзі.",
        },
      },
      required: ["summary"],
    },
  },
  {
    name: "set_status",
    description:
      "Змінити статус цілі, коли зі слів власника це однозначно: зробив — done, майже — almost, почав — in progress, скасував або переніс — відповідний статус.",
    input_schema: {
      type: "object",
      properties: {
        status: { type: "string", enum: STATUSES },
      },
      required: ["status"],
    },
  },
];

async function kvJson(env, key) {
  const raw = await env.COACH_KV.get(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Завантажує таблицю і повертає цілі разом із назвою вкладки. */
export async function loadGoals(env) {
  const { tab, rows } = await readGrid(env);
  const { goals, headerRow } = parseGoals(rows, { firstRowNumber: 1 });
  if (headerRow < 0) throw new Error("Не знайшов шапку таблиці (колонка A)");
  return { tab, goals };
}

async function ai(env, system, prompt, fallback, maxTokens = 300) {
  try {
    const reply = await messages(env, {
      system,
      messages: [{ role: "user", content: prompt }],
      maxTokens,
    });
    return textOf(reply) || fallback;
  } catch {
    return fallback;
  }
}

function goalContext(goal) {
  const notes = goal.notes ? goal.notes : "записів ще немає";
  return [
    `Ціль: ${goal.text}`,
    `Тип: ${goal.type || "—"}; горизонт: ${goal.horizon || "—"}; пріоритет: ${goal.priority}`,
    `Поточний статус: ${goal.status}`,
    `Історія записів:\n${notes}`,
  ].join("\n");
}

/** Щоденне питання о 16:00 по одній активній цілі. */
export async function askDaily(env, now, { force = false } = {}) {
  const tz = env.TIMEZONE || "Europe/Kyiv";
  const today = localIsoDate(now, tz);
  const current = await kvJson(env, CURRENT_KEY);
  if (!force && current?.date === today) return { skipped: "вже питав сьогодні" };

  const { goals } = await loadGoals(env);
  const yesterday = await kvJson(env, `ask:${previousIsoDate(today)}`);
  const exclude = yesterday?.answered ? [yesterday.key] : [];

  const goal = pickGoal(goals, { excludeKeys: exclude });
  if (!goal) {
    await sendMessage(
      env,
      "Активних цілей у таблиці немає — усе або закрито, або перенесено. Питати нема про що.",
    );
    return { skipped: "немає активних цілей" };
  }

  const question = await ai(
    env,
    PERSONA,
    [
      "Задай власнику одне питання про стан цієї цілі — коротко, без передмов.",
      "Якщо в історії є записи, спирайся на останній: питай, що зрушило з того часу.",
      "Максимум два речення.",
      "",
      goalContext(goal),
    ].join("\n"),
    `Ціль: ${goal.text}\nСтатус: ${goal.status}. Що по ній зараз?`,
  );

  await sendMessage(env, question);
  const state = {
    date: today,
    row: goal.row,
    key: goal.key,
    text: goal.text,
    status: goal.status,
    askedAt: now.toISOString(),
    answered: false,
  };
  await env.COACH_KV.put(CURRENT_KEY, JSON.stringify(state));
  await env.COACH_KV.put(`ask:${today}`, JSON.stringify(state), {
    expirationTtl: ASK_TTL,
  });
  return { asked: goal.text };
}

/** Колюче нагадування о 22:00, якщо на питання дня не відповіли. */
export async function nudge(env, now) {
  const tz = env.TIMEZONE || "Europe/Kyiv";
  const today = localIsoDate(now, tz);
  const current = await kvJson(env, CURRENT_KEY);
  if (!current || current.date !== today || current.answered) {
    return { skipped: "нічого нагадувати" };
  }
  if (current.nudged) return { skipped: "вже нагадував" };

  const text = await ai(
    env,
    PERSONA,
    [
      "Власник за день не відповів на питання про ціль. Нагадай колюче й коротко:",
      "без образ, але прямо — мовчання це теж відповідь, і вона не на його користь.",
      "Одне-два речення.",
      "",
      `Ціль: ${current.text}`,
    ].join("\n"),
    `Питання про «${current.text}» висить з 16:00 без відповіді. Ігнор — теж відповідь, і вона зрозуміла.`,
  );
  await sendMessage(env, text);
  await env.COACH_KV.put(
    CURRENT_KEY,
    JSON.stringify({ ...current, nudged: true }),
  );
  return { nudged: current.text };
}

function bucketLine(label, stats) {
  const parts = STATUSES.filter((s) => stats.counts[s] > 0).map(
    (s) => `${s}: ${stats.counts[s]}`,
  );
  return `${label}: ${stats.total} цілей, done ${stats.done} (${stats.donePct}%)${
    parts.length ? `\n  ${parts.join(", ")}` : ""
  }`;
}

/** Тижневе саммері в суботу о 09:00 з порівнянням до минулої суботи. */
export async function weeklySummary(env, now) {
  const tz = env.TIMEZONE || "Europe/Kyiv";
  const today = localIsoDate(now, tz);
  const { goals } = await loadGoals(env);
  const stats = statusSummary(goals);
  const previous = await kvJson(env, SNAPSHOT_KEY);
  const { changed, added } = diffSnapshots(previous?.map, goals);
  const weekAgo = now.getTime() - 7 * 24 * 60 * 60 * 1000;
  const touched = touchedSince(goals, weekAgo);

  const lines = [
    `Тиждень до ${today}`,
    "",
    bucketLine("Pers", stats.pers),
    bucketLine("Work", stats.work),
    bucketLine("Разом", stats.all),
    "",
  ];

  if (changed.length) {
    lines.push("Зміни статусів за тиждень:");
    for (const c of changed) lines.push(`- ${c.goal.text}: ${c.from} → ${c.to}`);
  } else {
    lines.push("Статуси за тиждень не змінилися.");
  }
  if (added.length) {
    lines.push("", "Нові цілі в таблиці:");
    for (const g of added) lines.push(`- ${g.text}`);
  }
  if (touched.length) {
    lines.push("", "Записи зʼявилися по цілях:");
    for (const g of touched) lines.push(`- ${g.text}`);
  } else {
    lines.push("", "Записів по жодній цілі за тиждень немає.");
  }

  const stalled = !changed.length && !touched.length;
  const verdict = await ai(
    env,
    PERSONA,
    [
      stalled
        ? "Тиждень пройшов без жодного руху по цілях. Скажи це прямо, без пом'якшення, і назви одну дію на понеділок."
        : "Дай короткий підсумок тижня: що реально зрушило і де провал. Назви одну дію на понеділок.",
      "Два-три речення, без емодзі.",
      "",
      lines.join("\n"),
    ].join("\n"),
    stalled
      ? "Тиждень злитий: жодного руху по жодній цілі. У понеділок обери одну ціль і зроби по ній перший крок."
      : "Підсумок вище. У понеділок візьми одну ціль і зрушь її.",
  );
  lines.push("", verdict);

  await sendMessage(env, lines.join("\n"));
  await env.COACH_KV.put(
    SNAPSHOT_KEY,
    JSON.stringify({ date: today, map: snapshotOf(goals) }),
  );
  return { weekly: today, stalled };
}

/** Розбір відповіді власника: Claude вирішує, що записати і чи міняти статус. */
export async function handleReply(env, text, now) {
  const tz = env.TIMEZONE || "Europe/Kyiv";
  const current = await kvJson(env, CURRENT_KEY);
  if (!current) {
    await sendMessage(env, "Питання дня ще не було. Напиши /ask, якщо хочеш зараз.");
    return { skipped: "немає відкритого питання" };
  }

  const { tab, goals } = await loadGoals(env);
  // Рядок міг зʼїхати від вставок — шукаємо ціль за текстом, номер лише запасний.
  const goal =
    goals.find((g) => g.key === goalKey(current.key)) ||
    goals.find((g) => g.row === current.row);
  if (!goal) {
    await sendMessage(env, `Не знайшов у таблиці ціль «${current.text}». Перевір рядок.`);
    return { skipped: "ціль зникла з таблиці" };
  }

  const writes = [];
  let notes = goal.notes;
  let newStatus = null;

  const handlers = {
    save_progress: async ({ summary }) => {
      if (!summary || !String(summary).trim()) return "Порожній summary — не записано";
      notes = appendNote(notes, noteDate(now, tz), summary);
      writes.push({ a1: `${NOTES_COLUMN_LETTER}${goal.row}`, value: notes, tag: "notes" });
      return "Записано в колонку нотаток";
    },
    set_status: async ({ status }) => {
      const value = String(status || "").toLowerCase().trim();
      if (!STATUSES.includes(value)) return `Невідомий статус: ${status}`;
      newStatus = value;
      writes.push({ a1: `G${goal.row}`, value, tag: "status" });
      return `Статус буде змінено на ${value}`;
    },
  };

  const { text: replyText, used } = await runWithTools(env, {
    system: PERSONA,
    messages: [
      {
        role: "user",
        content: [
          "Власник відповів на питання про ціль. Обробити відповідь інструментами,",
          "потім коротко відреагувати: без похвали, одне-два речення, за потреби — уточнення.",
          "",
          goalContext(goal),
          "",
          `Відповідь власника: ${text}`,
        ].join("\n"),
      },
    ],
    tools: TOOLS,
    handlers,
  });

  // Останній запис по кожній клітинці перемагає — щоб не слати два PUT на одну.
  const byCell = new Map();
  for (const w of writes) byCell.set(w.a1, w);
  if (byCell.size) await writeCells(env, tab, [...byCell.values()]);

  await env.COACH_KV.put(
    CURRENT_KEY,
    JSON.stringify({
      ...current,
      answered: true,
      answeredAt: now.toISOString(),
      status: newStatus || current.status,
    }),
  );
  await env.COACH_KV.put(
    `ask:${current.date}`,
    JSON.stringify({ ...current, answered: true, answeredAt: now.toISOString() }),
    { expirationTtl: ASK_TTL },
  );

  const tail = [];
  if (byCell.has(`${NOTES_COLUMN_LETTER}${goal.row}`)) tail.push("записав");
  if (newStatus) tail.push(`статус → ${newStatus}`);
  const suffix = tail.length ? `\n\n(${tail.join(", ")})` : "";
  await sendMessage(env, `${replyText || "Прийняв."}${suffix}`);
  return { handled: goal.text, used };
}

/** Поточні цифри на запит (/status) — той самий зріз, що й у суботу. */
export async function statusReport(env) {
  const { goals } = await loadGoals(env);
  const stats = statusSummary(goals);
  const active = goals.filter(isActive).length;
  return [
    bucketLine("Pers", stats.pers),
    bucketLine("Work", stats.work),
    bucketLine("Разом", stats.all),
    "",
    `Активних (${ACTIVE_STATUSES.join(", ")}): ${active}`,
  ].join("\n");
}

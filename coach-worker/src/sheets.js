/** Тонка обгортка над Google Sheets API v4 — читання й точковий запис. */

import { getAccessToken } from "./google-auth.js";

const API = "https://sheets.googleapis.com/v4/spreadsheets";

let cachedTab = { sheetId: null, title: null };

async function call(env, path, init = {}) {
  const token = await getAccessToken(env);
  const res = await fetch(`${API}/${env.SHEET_ID}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`Sheets ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  return res.json();
}

/** Назва вкладки: із SHEET_TAB, інакше — перша вкладка таблиці. */
export async function resolveTab(env) {
  if (env.SHEET_TAB) return env.SHEET_TAB;
  if (cachedTab.sheetId === env.SHEET_ID && cachedTab.title) return cachedTab.title;
  const meta = await call(env, "?fields=sheets.properties.title");
  const title = meta?.sheets?.[0]?.properties?.title;
  if (!title) throw new Error("Не вдалося визначити вкладку таблиці");
  cachedTab = { sheetId: env.SHEET_ID, title };
  return title;
}

function quoteTab(title) {
  return `'${String(title).replace(/'/g, "''")}'`;
}

/** Усі рядки колонок A..H разом із порожніми — 1-based нумерація зберігається. */
export async function readGrid(env) {
  const tab = await resolveTab(env);
  const range = encodeURIComponent(`${quoteTab(tab)}!A:H`);
  const data = await call(
    env,
    `/values/${range}?majorDimension=ROWS&valueRenderOption=UNFORMATTED_VALUE`,
  );
  return { tab, rows: data.values || [] };
}

/**
 * Записує кілька клітинок одним запитом. RAW — щоб Sheets не перетворив
 * нотатку «06.09.26: ...» на дату і не зіпсував текст статусу.
 */
export async function writeCells(env, tab, cells) {
  if (!cells.length) return;
  await call(env, "/values:batchUpdate", {
    method: "POST",
    body: JSON.stringify({
      valueInputOption: "RAW",
      data: cells.map(({ a1, value }) => ({
        range: `${quoteTab(tab)}!${a1}`,
        values: [[value]],
      })),
    }),
  });
}

/** Чиста логіка над рядками таблиці цілей: розбір, вибір цілі, статистика.
 *
 * Тут навмисно немає жодного мережевого виклику — усе це юніт-тестується
 * (`npm test`), бо саме ця логіка вирішує, що бот спитає і що запише.
 */

export const STATUSES = [
  "not started",
  "in progress",
  "almost",
  "done",
  "cancelled",
  "postponed to next year",
  "postponed to far future",
];

/** «Активні» для бота — тільки ті, по яких ще є що робити. */
export const ACTIVE_STATUSES = ["not started", "in progress", "almost"];

// Розкладка колонок за домовленістю: A..H.
export const COL = {
  horizon: 0,
  priority: 1,
  type: 2,
  text: 3,
  owner: 4,
  owner2: 5,
  status: 6,
  notes: 7,
};
export const NOTES_COLUMN_LETTER = "H";

const HEADER_HINTS = ["на що впливає", "на шо впливає"];

function norm(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function lower(value) {
  return norm(value).toLowerCase();
}

/** Ключ цілі — сам текст. Стійкий до вставки рядків, на відміну від номера. */
export function goalKey(text) {
  return lower(text);
}

export function normalizeStatus(value) {
  const v = lower(value);
  return STATUSES.includes(v) ? v : "";
}

export function isActive(goal) {
  return ACTIVE_STATUSES.includes(goal.status);
}

/**
 * Шукає рядок шапки динамічно, щоб вставка рядків зверху нічого не ламала.
 * Повертає 0-based індекс у масиві rows або -1.
 */
export function findHeaderRow(rows) {
  for (let i = 0; i < rows.length; i++) {
    const first = lower(rows[i]?.[COL.horizon]);
    if (HEADER_HINTS.some((hint) => first.startsWith(hint))) return i;
    // Запасний варіант: шапку впізнаємо за «Пріоритет» + «Статус» у рядку.
    const cells = (rows[i] || []).map(lower);
    if (cells.includes("пріоритет") && cells.some((c) => c.startsWith("статус"))) {
      return i;
    }
  }
  return -1;
}

/**
 * Перетворює сирі рядки таблиці на цілі. Рядок вважається ціллю, якщо в
 * колонці D є текст — так підвал зі списком ресурсів відсіюється сам.
 * `row` — 1-based номер рядка в аркуші, придатний для запису в діапазон.
 */
export function parseGoals(rows, { firstRowNumber = 1 } = {}) {
  const headerIdx = findHeaderRow(rows);
  if (headerIdx < 0) return { headerRow: -1, goals: [] };

  const goals = [];
  for (let i = headerIdx + 1; i < rows.length; i++) {
    const cells = rows[i] || [];
    const text = norm(cells[COL.text]);
    if (!text) continue;
    const priority = Number(String(cells[COL.priority] ?? "").replace(/[^\d]/g, ""));
    goals.push({
      row: firstRowNumber + i,
      key: goalKey(text),
      horizon: norm(cells[COL.horizon]),
      priority: Number.isFinite(priority) ? priority : 0,
      type: norm(cells[COL.type]),
      text,
      owner: norm(cells[COL.owner]),
      owner2: norm(cells[COL.owner2]),
      status: normalizeStatus(cells[COL.status]),
      rawStatus: norm(cells[COL.status]),
      notes: String(cells[COL.notes] ?? ""),
    });
  }
  return { headerRow: firstRowNumber + headerIdx, goals };
}

/** Остання дата з нотаток «дд.мм.рр: ...» або null, якщо бот ще не торкався. */
export function lastTouchedAt(notes) {
  const found = String(notes ?? "").matchAll(/(\d{2})\.(\d{2})\.(\d{2})/g);
  let best = null;
  for (const m of found) {
    const [, dd, mm, yy] = m;
    const ts = Date.UTC(2000 + Number(yy), Number(mm) - 1, Number(dd));
    if (!Number.isNaN(ts) && (best === null || ts > best)) best = ts;
  }
  return best;
}

/**
 * Вибір цілі дня: спершу ті, яких бот ще не торкався; далі — найдавніше
 * торкані; за рівності — вищий пріоритет. Учорашня відповіджена ціль
 * виключається, щоб не питати те саме два дні поспіль.
 */
export function pickGoal(goals, { excludeKeys = [] } = {}) {
  const skip = new Set(excludeKeys.map(goalKey));
  const pool = goals.filter((g) => isActive(g) && !skip.has(g.key));
  if (!pool.length) return null;

  const scored = pool.map((g) => ({ goal: g, touched: lastTouchedAt(g.notes) }));
  scored.sort((a, b) => {
    const aNew = a.touched === null ? 0 : 1;
    const bNew = b.touched === null ? 0 : 1;
    if (aNew !== bNew) return aNew - bNew;
    if (aNew === 1 && a.touched !== b.touched) return a.touched - b.touched;
    if (b.goal.priority !== a.goal.priority) return b.goal.priority - a.goal.priority;
    return a.goal.row - b.goal.row;
  });
  return scored[0].goal;
}

/** Дописує рядок «дд.мм.рр: суть» у кінець нотаток, не затираючи старі. */
export function appendNote(existing, dateStr, summary) {
  const clean = norm(summary);
  const line = `${dateStr}: ${clean}`;
  const before = String(existing ?? "").replace(/\s+$/, "");
  return before ? `${before}\n${line}` : line;
}

function emptyCounts() {
  const counts = {};
  for (const s of STATUSES) counts[s] = 0;
  return counts;
}

function bucketStats(goals) {
  const counts = emptyCounts();
  for (const g of goals) if (g.status) counts[g.status] += 1;
  const total = goals.length;
  const done = counts.done;
  const closed = counts.done + counts.cancelled;
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0);
  return {
    total,
    counts,
    percents: Object.fromEntries(STATUSES.map((s) => [s, pct(counts[s])])),
    done,
    donePct: pct(done),
    closed,
    // Заголовний відсоток у шаблоні таблиці — «done and cancelled».
    closedPct: pct(closed),
  };
}

/** Три дашборди шаблону: Pers, Work і разом. */
export function statusSummary(goals) {
  const pers = goals.filter((g) => lower(g.type) === "pers");
  const work = goals.filter((g) => lower(g.type) === "work");
  return {
    pers: bucketStats(pers),
    work: bucketStats(work),
    all: bucketStats(goals),
  };
}

/** Знімок «ключ цілі → статус» для порівняння тижня з тижнем. */
export function snapshotOf(goals) {
  const out = {};
  for (const g of goals) out[g.key] = g.status;
  return out;
}

/** Що змінилося зі знімка минулої суботи: нові цілі та зміни статусів. */
export function diffSnapshots(previous, goals) {
  const prev = previous || {};
  const changed = [];
  const added = [];
  for (const g of goals) {
    if (!(g.key in prev)) {
      added.push(g);
    } else if (prev[g.key] !== g.status) {
      changed.push({ goal: g, from: prev[g.key], to: g.status });
    }
  }
  return { changed, added };
}

/** Цілі, по яких за останні `days` днів зʼявився запис у нотатках. */
export function touchedSince(goals, sinceTs) {
  return goals.filter((g) => {
    const t = lastTouchedAt(g.notes);
    return t !== null && t >= sinceTs;
  });
}

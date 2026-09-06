/** Сторінка-дашборд: той самий шаблон, що й у Google Таблиці, тільки свій. */

import { STATUSES, statusSummary } from "./goals.js";

const STATUS_CLASS = {
  "done": "s-done",
  "almost": "s-almost",
  "in progress": "s-progress",
  "not started": "s-none",
  "cancelled": "s-cancelled",
  "postponed to next year": "s-postponed",
  "postponed to far future": "s-postponed",
};

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function lastNote(notes) {
  const lines = String(notes || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.length ? lines[lines.length - 1] : "";
}

function card(label, stats) {
  const rows = STATUSES.map(
    (s) => `<tr><td>${esc(s)}</td><td class="num">${stats.counts[s]}</td>
      <td class="num muted">${stats.percents[s]}%</td></tr>`,
  ).join("");
  return `<section class="card">
    <header><h2>${esc(label)}</h2><span class="big">${stats.closedPct}%</span></header>
    <p class="muted">Цілей на рік: <b>${stats.total}</b> · done: <b>${stats.done}</b> (${stats.donePct}%)</p>
    <table class="mini">${rows}
      <tr class="sum"><td>done and cancelled</td><td class="num">${stats.closed}</td>
      <td class="num muted">${stats.closedPct}%</td></tr>
    </table>
  </section>`;
}

export function dashboardHtml(goals, { theme = "", updatedAt = "" } = {}) {
  const stats = statusSummary(goals);
  const sorted = [...goals].sort(
    (a, b) => b.priority - a.priority || a.row - b.row,
  );
  const rows = sorted
    .map(
      (g) => `<tr>
        <td>${esc(g.horizon)}</td>
        <td class="num">${g.priority || ""}</td>
        <td>${esc(g.type)}</td>
        <td class="goal">${esc(g.text)}</td>
        <td>${esc(g.owner)}${g.owner2 ? `, ${esc(g.owner2)}` : ""}</td>
        <td><span class="chip ${STATUS_CLASS[g.status] || "s-none"}">${esc(g.rawStatus || g.status)}</span></td>
        <td class="note">${esc(lastNote(g.notes))}</td>
      </tr>`,
    )
    .join("");

  return `<!doctype html>
<html lang="uk"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Цілі року</title>
<style>
:root{--bg:#f6f7f9;--fg:#1c1e21;--muted:#6b7280;--line:#e2e5ea;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8eaed;--muted:#9aa1ab;--line:#2a2e35;--card:#1c1f24}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}
.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:20px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card header{display:flex;align-items:baseline;justify-content:space-between}
.card h2{font-size:15px;margin:0}
.big{font-size:24px;font-weight:600}
table{width:100%;border-collapse:collapse}
.mini td{padding:2px 0;font-size:13px}
.mini .sum td{border-top:1px solid var(--line);padding-top:6px;font-weight:600}
.num{text-align:right;width:52px}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
.grid{min-width:900px}
.grid th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.03em;
  color:var(--muted);padding:10px 12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--card)}
.grid td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
.grid tr:last-child td{border-bottom:0}
.goal{min-width:320px}
.note{color:var(--muted);font-size:12px;max-width:260px}
.chip{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;white-space:nowrap;border:1px solid var(--line)}
.s-done{background:#dcfce7;color:#14532d;border-color:#bbf7d0}
.s-almost{background:#fef9c3;color:#713f12;border-color:#fde68a}
.s-progress{background:#dbeafe;color:#1e3a8a;border-color:#bfdbfe}
.s-none{background:transparent;color:var(--muted)}
.s-cancelled{background:#fee2e2;color:#7f1d1d;border-color:#fecaca}
.s-postponed{background:#ede9fe;color:#4c1d95;border-color:#ddd6fe}
</style></head><body><div class="wrap">
<h1>${esc(theme || "Цілі року")}</h1>
<p class="muted">Оновлено: ${esc(updatedAt)}</p>
<div class="cards">${card("Pers", stats.pers)}${card("Work", stats.work)}${card("Pers and Work", stats.all)}</div>
<div class="scroll"><table class="grid">
<thead><tr><th>На що впливає</th><th>Пріоритет</th><th>Тип</th><th>Ціль</th>
<th>Відповідальні</th><th>Статус</th><th>Останній запис</th></tr></thead>
<tbody>${rows}</tbody></table></div>
</div></body></html>`;
}

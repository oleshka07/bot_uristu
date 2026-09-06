import { test } from "node:test";
import assert from "node:assert/strict";

import {
  appendNote,
  diffSnapshots,
  findHeaderRow,
  lastTouchedAt,
  parseGoals,
  pickGoal,
  snapshotOf,
  statusSummary,
  touchedSince,
} from "../src/goals.js";

const HEADER = [
  "На що впливає?",
  "Пріоритет",
  "Тип цілі",
  "Тема року",
  "Відповідальний",
  "Відповідальний #2",
  "Статус",
  "Коуч",
];

function sheet(rows) {
  return [
    ["Тема року: Здоровʼя. Комфорт. Гроші."],
    [],
    HEADER,
    ...rows,
  ];
}

const ROWS = [
  ["Present", "100", "Work", "Аудит AI в бізнесі", "Олег", "", "in progress", "01.05.26: почав"],
  ["Future", "90", "Pers", "Прочитати 25 книг", "Олег", "", "in progress", ""],
  ["Present", "80", "Work", "Найняти sales", "Олег", "", "done", "10.05.26: закрито"],
  ["Present", "70", "Pers", "Digital detox", "Олег", "", "not started", "20.04.26: думав"],
  ["Far Future", "10", "Pers", "Roadtrip Європою", "", "", "postponed to far future", ""],
  ["", "", "> Instagram\n> Книга", "", "", "", "", ""],
];

test("шапка знаходиться навіть зі зсувом рядків зверху", () => {
  assert.equal(findHeaderRow(sheet(ROWS)), 2);
  assert.equal(findHeaderRow([["щось"], ["інше"]]), -1);
});

test("підвал без тексту цілі не потрапляє в цілі", () => {
  const { goals, headerRow } = parseGoals(sheet(ROWS), { firstRowNumber: 1 });
  assert.equal(headerRow, 3);
  assert.equal(goals.length, 5);
  assert.deepEqual(
    goals.map((g) => g.text),
    [
      "Аудит AI в бізнесі",
      "Прочитати 25 книг",
      "Найняти sales",
      "Digital detox",
      "Roadtrip Європою",
    ],
  );
  // 1-based номер рядка в аркуші, придатний для запису.
  assert.equal(goals[0].row, 4);
  assert.equal(goals[0].priority, 100);
});

test("остання дата з нотаток", () => {
  assert.equal(lastTouchedAt(""), null);
  assert.equal(lastTouchedAt("01.05.26: а\n03.06.26: б"), Date.UTC(2026, 5, 3));
});

test("першою питається ціль, якої бот ще не торкався", () => {
  const { goals } = parseGoals(sheet(ROWS));
  assert.equal(pickGoal(goals).text, "Прочитати 25 книг");
});

test("далі — найдавніше торкана активна ціль", () => {
  const { goals } = parseGoals(sheet(ROWS));
  const picked = pickGoal(goals, { excludeKeys: ["Прочитати 25 книг"] });
  assert.equal(picked.text, "Digital detox"); // 20.04 давніше за 01.05
});

test("неактивні статуси не питаються взагалі", () => {
  const { goals } = parseGoals(sheet(ROWS));
  const picked = pickGoal(goals, {
    excludeKeys: ["Прочитати 25 книг", "Digital detox", "Аудит AI в бізнесі"],
  });
  assert.equal(picked, null); // done і postponed — поза грою
});

test("за рівних дат перемагає вищий пріоритет", () => {
  const rows = [
    ["Present", "50", "Work", "Низька", "", "", "in progress", "01.05.26: а"],
    ["Present", "90", "Work", "Висока", "", "", "in progress", "01.05.26: б"],
  ];
  const { goals } = parseGoals(sheet(rows));
  assert.equal(pickGoal(goals).text, "Висока");
});

test("нотатка дописується, а не затирає попередні", () => {
  assert.equal(appendNote("01.05.26: а", "02.05.26", "б"), "01.05.26: а\n02.05.26: б");
  assert.equal(appendNote("", "02.05.26", "  б  "), "02.05.26: б");
});

test("три дашборди рахуються як у шаблоні таблиці", () => {
  const { goals } = parseGoals(sheet(ROWS));
  const s = statusSummary(goals);
  assert.equal(s.pers.total, 3);
  assert.equal(s.work.total, 2);
  assert.equal(s.all.total, 5);
  assert.equal(s.work.counts.done, 1);
  assert.equal(s.work.donePct, 50);
  assert.equal(s.all.donePct, 20);
});

test("порівняння тижня з тижнем ловить зміну статусу і нову ціль", () => {
  const { goals } = parseGoals(sheet(ROWS));
  const prev = snapshotOf(goals);
  const moved = goals.map((g) =>
    g.text === "Digital detox" ? { ...g, status: "in progress" } : g,
  );
  moved.push({ key: "нова ціль", text: "Нова ціль", status: "not started", type: "Work" });
  const { changed, added } = diffSnapshots(prev, moved);
  assert.equal(changed.length, 1);
  assert.equal(changed[0].from, "not started");
  assert.equal(changed[0].to, "in progress");
  assert.equal(added.length, 1);
  assert.equal(added[0].text, "Нова ціль");
});

test("touchedSince бере лише цілі із записами за період", () => {
  const { goals } = parseGoals(sheet(ROWS));
  const recent = touchedSince(goals, Date.UTC(2026, 4, 5));
  assert.deepEqual(recent.map((g) => g.text), ["Найняти sales"]);
});

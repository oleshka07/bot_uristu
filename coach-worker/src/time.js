/** Локальний час власника. Крон воркера — UTC, а розклад у нього київський. */

/** Розкладає момент часу на київські (або інші, за tz) частини. */
export function localParts(date, tz) {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short",
    hour12: false,
  });
  const got = {};
  for (const part of fmt.formatToParts(date)) got[part.type] = part.value;
  const weekdays = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return {
    year: Number(got.year),
    month: Number(got.month),
    day: Number(got.day),
    // "24" о півночі трапляється у деяких рантаймів — зводимо до 0.
    hour: Number(got.hour) % 24,
    minute: Number(got.minute),
    weekday: weekdays[got.weekday],
    isoDate: `${got.year}-${got.month}-${got.day}`,
  };
}

/** Дата у форматі, яким бот пише нотатки в таблицю: "дд.мм.рр". */
export function noteDate(date, tz) {
  const p = localParts(date, tz);
  const dd = String(p.day).padStart(2, "0");
  const mm = String(p.month).padStart(2, "0");
  const yy = String(p.year % 100).padStart(2, "0");
  return `${dd}.${mm}.${yy}`;
}

/** ISO-дата (YYYY-MM-DD) за локальним часом власника — ключ для KV. */
export function localIsoDate(date, tz) {
  return localParts(date, tz).isoDate;
}

/** Учорашня локальна дата в ISO. */
export function previousIsoDate(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() - 1);
  return dt.toISOString().slice(0, 10);
}
